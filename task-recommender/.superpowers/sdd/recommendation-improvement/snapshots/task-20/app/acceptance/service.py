"""Acceptance workflow: submit, machine check, review, decide, learn."""

from __future__ import annotations

import statistics
import uuid
from datetime import datetime, timezone

from app.acceptance.checks import run_machine_checks
from app.acceptance.specs import build_research_spec
from app.data.store import Store
from app.domain import (
    AcceptanceRecord,
    AcceptanceSpec,
    CriterionResult,
    Submission,
    Task,
)
from app.learning.weights import KEYS

DECISIONS = {"accepted", "rework", "rejected", "disputed"}

DIMENSION_TO_WEIGHTS = {
    "completeness": {"skill": 0.6, "expertise": 0.4},
    "accuracy": {"reputation": 0.5, "skill": 0.5},
    "evidence": {"expertise": 0.6, "reputation": 0.4},
    "insight": {"expertise": 0.7, "reputation": 0.3},
    "format": {"skill": 0.5, "load": 0.5},
    "timeliness": {"load": 1.0},
}


def _aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _weighted_score(
    spec: AcceptanceSpec, results: list[CriterionResult]
) -> float:
    by_key = {result.criterion_key: result for result in results}
    present = [criterion for criterion in spec.criteria if criterion.key in by_key]
    denominator = sum(criterion.weight for criterion in present)
    if denominator <= 0:
        return 0.0
    numerator = sum(
        criterion.weight * by_key[criterion.key].score
        for criterion in present
    )
    return round(numerator / denominator, 4)


def _criterion_map(spec: AcceptanceSpec) -> dict:
    return {criterion.key: criterion for criterion in spec.criteria}


class AcceptanceService:
    def __init__(self, store: Store, personalizer=None) -> None:
        self.store = store
        self.personalizer = personalizer
        self.specs: dict[str, AcceptanceSpec] = {}
        self.submissions: dict[str, Submission] = {}
        self.records: dict[str, list[AcceptanceRecord]] = {}
        self.final_records: dict[str, AcceptanceRecord] = {}

    # ------------------------------------------------------------------
    # Specs
    # ------------------------------------------------------------------
    def spec_for(self, task: Task) -> AcceptanceSpec:
        existing = self.specs.get(task.task_id)
        if existing is not None:
            return existing
        if task.category != "consulting_research":
            raise ValueError(
                "acceptance specs currently support consulting_research "
                "tasks only"
            )
        spec = build_research_spec(task.task_id)
        self.specs[task.task_id] = spec
        return spec

    # ------------------------------------------------------------------
    # Submission + machine checks
    # ------------------------------------------------------------------
    def submit(
        self,
        task_id: str,
        worker_id: str,
        artifacts: dict,
        submitted_at: datetime | None = None,
    ) -> tuple[Submission, AcceptanceRecord]:
        task = self.store.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        if worker_id not in self.store.workers:
            raise KeyError(f"unknown worker: {worker_id}")
        spec = self.spec_for(task)

        version = 1 + sum(
            1
            for submission in self.submissions.values()
            if submission.task_id == task_id
        )
        moment = _aware(submitted_at or self.store.reference_time)
        submission = Submission(
            submission_id=uuid.uuid4().hex,
            task_id=task_id,
            worker_id=worker_id,
            version=version,
            artifacts=dict(artifacts or {}),
            submitted_at=moment,
            spec_version=spec.version,
        )
        submission.machine_results = run_machine_checks(
            spec, submission, task
        )
        required_failed = [
            result
            for result in submission.machine_results
            if (
                not result.passed
                and _criterion_map(spec)[result.criterion_key].required
            )
        ]
        submission.status = (
            "machine_failed" if required_failed else "machine_checked"
        )
        self.submissions[submission.submission_id] = submission

        record = AcceptanceRecord(
            record_id=uuid.uuid4().hex,
            submission_id=submission.submission_id,
            task_id=task_id,
            worker_id=worker_id,
            spec_version=spec.version,
            layer="machine",
            reviewer_id="system",
            criterion_results=list(submission.machine_results),
            total_score=_weighted_score(
                spec, submission.machine_results
            ),
            decision="pending",
            comment=(
                "required criteria failed"
                if required_failed
                else "machine checks passed"
            ),
            created_at=moment,
        )
        self.records.setdefault(task_id, []).append(record)
        return submission, record

    def review(
        self,
        submission_id: str,
        reviewer_id: str,
        scores: dict[str, float],
        comments: dict[str, str] | None = None,
        layer: str = "customer",
    ) -> AcceptanceRecord:
        submission = self.submissions.get(submission_id)
        if submission is None:
            raise KeyError(f"unknown submission: {submission_id}")
        if layer not in {"peer", "customer", "model"}:
            raise ValueError(f"invalid review layer: {layer}")
        spec = self.specs[submission.task_id]
        comments = comments or {}

        human_criteria = [
            criterion
            for criterion in spec.criteria
            if criterion.layer != "machine"
        ]
        missing = [
            criterion.key
            for criterion in human_criteria
            if criterion.key not in scores
        ]
        if missing:
            raise ValueError(
                f"missing scores for criteria: {', '.join(missing)}"
            )

        results = []
        for criterion in human_criteria:
            score = float(scores[criterion.key])
            if not 0.0 <= score <= 1.0:
                raise ValueError(
                    f"score for {criterion.key} must be between 0 and 1"
                )
            results.append(
                CriterionResult(
                    criterion_key=criterion.key,
                    passed=score >= 0.6,
                    score=score,
                    comment=comments.get(criterion.key, ""),
                )
            )

        submission.human_results = results
        submission.status = "reviewed"
        record = AcceptanceRecord(
            record_id=uuid.uuid4().hex,
            submission_id=submission_id,
            task_id=submission.task_id,
            worker_id=submission.worker_id,
            spec_version=spec.version,
            layer=layer,
            reviewer_id=reviewer_id,
            criterion_results=results,
            total_score=_weighted_score(spec, results),
            decision="pending",
            comment="human review recorded",
            created_at=self.store.reference_time,
        )
        self.records.setdefault(submission.task_id, []).append(record)
        return record

    # ------------------------------------------------------------------
    # Final decision + learning
    # ------------------------------------------------------------------
    def decide(
        self,
        submission_id: str,
        reviewer_id: str,
        decision: str,
        comment: str = "",
        learn: bool = True,
    ) -> tuple[AcceptanceRecord, dict | None]:
        if decision not in DECISIONS:
            raise ValueError(f"invalid decision: {decision}")
        submission = self.submissions.get(submission_id)
        if submission is None:
            raise KeyError(f"unknown submission: {submission_id}")
        task = self.store.tasks[submission.task_id]
        spec = self.specs[submission.task_id]

        combined = {
            result.criterion_key: result
            for result in submission.machine_results + submission.human_results
        }
        missing = [
            criterion.key
            for criterion in spec.criteria
            if criterion.key not in combined
        ]
        if missing:
            raise ValueError(
                "cannot decide before reviewing: " + ", ".join(missing)
            )

        all_results = [
            combined[criterion.key] for criterion in spec.criteria
        ]
        total = _weighted_score(spec, all_results)
        required_failed = [
            criterion.key
            for criterion in spec.criteria
            if criterion.required and not combined[criterion.key].passed
        ]

        actual = decision
        note = comment
        if actual == "accepted":
            if required_failed:
                raise ValueError(
                    "cannot accept: required criteria failed: "
                    + ", ".join(required_failed)
                )
            if total < spec.accept_threshold:
                raise ValueError(
                    f"cannot accept: total {total:.2f} below "
                    f"threshold {spec.accept_threshold:.2f}"
                )
        elif actual == "rejected":
            if not required_failed and total >= spec.rework_threshold:
                actual = "disputed"
                note = (
                    (comment + " ").strip()
                    + "[converted to dispute: rejection did not cite a "
                    "failed criterion]"
                )

        record = AcceptanceRecord(
            record_id=uuid.uuid4().hex,
            submission_id=submission_id,
            task_id=submission.task_id,
            worker_id=submission.worker_id,
            spec_version=spec.version,
            layer="customer",
            reviewer_id=reviewer_id,
            criterion_results=all_results,
            total_score=total,
            decision=actual,
            comment=note,
            created_at=self.store.reference_time,
        )
        self.records.setdefault(submission.task_id, []).append(record)
        self.final_records[submission_id] = record
        submission.status = actual

        learning = None
        if (
            learn
            and self.personalizer is not None
            and actual != "disputed"
        ):
            learning = self._learn_from_acceptance(task, record)
        return record, learning

    def _learn_from_acceptance(
        self,
        task: Task,
        record: AcceptanceRecord,
        customer_id: str | None = None,
    ) -> dict | None:
        customer = self.store.customers.get(
            customer_id or task.customer_id
        )
        if customer is None:
            return None
        spec = self.specs[task.task_id]
        by_key = {
            result.criterion_key: result
            for result in record.criterion_results
        }
        dimension_scores: dict[str, list[float]] = {}
        for criterion in spec.criteria:
            result = by_key.get(criterion.key)
            if result is None:
                continue
            # A passed machine check is a baseline requirement, not a
            # preference signal. Failed machine checks and human scores
            # are what tell us which dimension this customer cares about.
            if criterion.layer == "machine" and result.passed:
                continue
            dimension_scores.setdefault(
                criterion.dimension, []
            ).append(result.score)
        averaged = {
            dimension: statistics.mean(scores)
            for dimension, scores in dimension_scores.items()
        }

        signals = {key: 0.0 for key in KEYS}
        for dimension, score in averaged.items():
            centered = max(-1.0, min(1.0, (score - 0.5) * 2.0))
            for key, weight in DIMENSION_TO_WEIGHTS.get(
                dimension, {}
            ).items():
                signals[key] += weight * centered
        if record.decision == "accepted":
            signals["reputation"] += 0.2
            signals["customer_preference"] += 0.2
        elif record.decision == "rework":
            signals["reputation"] -= 0.3
            signals["customer_preference"] -= 0.3
        elif record.decision == "rejected":
            signals["reputation"] -= 0.5
            signals["customer_preference"] -= 0.5
        signals = {
            key: round(max(-1.0, min(1.0, value)), 4)
            for key, value in signals.items()
        }

        before = dict(
            self.personalizer.weights_for(customer.customer_id).weights
        )
        updated = self.personalizer.nudge_weights(
            customer.customer_id,
            signals,
            strength=0.35,
            n0=5.0,
        )
        deltas = {
            key: round(updated.weights.get(key, 0.0) - before.get(key, 0.0), 4)
            for key in before
        }
        increases = {
            key: value for key, value in deltas.items() if value > 0
        }
        decreases = {
            key: value for key, value in deltas.items() if value < 0
        }
        return {
            "customer_id": customer.customer_id,
            "decision": record.decision,
            "sample_count": updated.sample_count,
            "confidence": round(updated.confidence, 4),
            "signals": signals,
            "before": before,
            "after": dict(updated.weights),
            "deltas": deltas,
            "top_up": (
                max(increases, key=increases.get) if increases else None
            ),
            "top_down": (
                min(decreases, key=decreases.get) if decreases else None
            ),
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def records_for_task(self, task_id: str) -> list[AcceptanceRecord]:
        return list(self.records.get(task_id, []))

    def submission_history(self, task_id: str) -> list[Submission]:
        return sorted(
            (
                submission
                for submission in self.submissions.values()
                if submission.task_id == task_id
            ),
            key=lambda submission: submission.version,
        )

    def capability(self, worker_id: str) -> dict:
        if worker_id not in self.store.workers:
            raise KeyError(f"unknown worker: {worker_id}")
        submissions = [
            submission
            for submission in self.submissions.values()
            if submission.worker_id == worker_id
        ]
        finals = [
            self.final_records[submission.submission_id]
            for submission in submissions
            if submission.submission_id in self.final_records
        ]
        total = len(submissions)
        accepted = sum(1 for record in finals if record.decision == "accepted")
        first_pass = sum(
            1
            for submission in submissions
            if submission.version == 1
            and submission.submission_id in self.final_records
            and self.final_records[submission.submission_id].decision
            == "accepted"
        )
        rework = sum(1 for record in finals if record.decision == "rework")
        rejected = sum(1 for record in finals if record.decision == "rejected")
        disputed = sum(1 for record in finals if record.decision == "disputed")

        on_time = 0
        deadline_total = 0
        for submission in submissions:
            for result in submission.machine_results:
                if result.criterion_key == "deadline":
                    deadline_total += 1
                    on_time += int(result.passed)

        criteria_total = sum(
            len(record.criterion_results) for record in finals
        )
        criteria_passed = sum(
            sum(1 for result in record.criterion_results if result.passed)
            for record in finals
        )

        def rate(value: int, denominator: int, prior: float = 0.5) -> float:
            alpha = 5.0
            return round(
                (value + alpha * prior) / (denominator + alpha), 4
            )

        return {
            "worker_id": worker_id,
            "submissions": total,
            "decided": len(finals),
            "accepted": accepted,
            "first_pass_accepted": first_pass,
            "rework": rework,
            "rejected": rejected,
            "disputed": disputed,
            "acceptance_rate": rate(accepted, len(finals)),
            "acceptance_rate_raw": (
                round(accepted / len(finals), 4) if finals else None
            ),
            "first_pass_rate": rate(first_pass, total),
            "first_pass_rate_raw": round(first_pass / total, 4) if total else None,
            "rework_rate": rate(rework, total, prior=0.2),
            "rework_rate_raw": round(rework / total, 4) if total else None,
            "dispute_rate": rate(disputed, total, prior=0.05),
            "dispute_rate_raw": round(disputed / total, 4) if total else None,
            "on_time_rate": rate(on_time, deadline_total, prior=0.8),
            "avg_acceptance_score": (
                round(
                    statistics.mean(record.total_score for record in finals),
                    4,
                )
                if finals
                else None
            ),
            "criteria_pass_rate": (
                round(criteria_passed / criteria_total, 4)
                if criteria_total
                else None
            ),
        }

    def metrics(self) -> dict:
        finals = list(self.final_records.values())
        submissions = len(self.submissions)
        accepted = sum(1 for record in finals if record.decision == "accepted")
        rework = sum(1 for record in finals if record.decision == "rework")
        rejected = sum(1 for record in finals if record.decision == "rejected")
        disputed = sum(1 for record in finals if record.decision == "disputed")
        first_pass = sum(
            1
            for submission_id, record in self.final_records.items()
            if record.decision == "accepted"
            and self.submissions[submission_id].version == 1
        )
        cycles = [
            (
                _aware(record.created_at)
                - _aware(self.submissions[submission_id].submitted_at)
            ).total_seconds()
            / 3600.0
            for submission_id, record in self.final_records.items()
        ]
        criteria_total = sum(len(record.criterion_results) for record in finals)
        criteria_passed = sum(
            sum(1 for result in record.criterion_results if result.passed)
            for record in finals
        )

        def rate(value: int, denominator: int, prior: float = 0.5) -> float:
            alpha = 5.0
            return round(
                (value + alpha * prior) / (denominator + alpha), 4
            )

        return {
            "submissions": submissions,
            "decided": len(finals),
            "accepted": accepted,
            "rework": rework,
            "rejected": rejected,
            "disputed": disputed,
            "first_pass_rate": rate(first_pass, submissions),
            "first_pass_rate_raw": (
                round(first_pass / submissions, 4) if submissions else None
            ),
            "acceptance_rate": rate(accepted, len(finals)),
            "acceptance_rate_raw": (
                round(accepted / len(finals), 4) if finals else None
            ),
            "rework_rate": rate(rework, submissions, prior=0.2),
            "rework_rate_raw": (
                round(rework / submissions, 4) if submissions else None
            ),
            "dispute_rate": rate(disputed, submissions, prior=0.05),
            "dispute_rate_raw": (
                round(disputed / submissions, 4) if submissions else None
            ),
            "criteria_pass_rate": (
                round(criteria_passed / criteria_total, 4)
                if criteria_total
                else None
            ),
            "avg_cycle_hours": (
                round(statistics.mean(cycles), 2) if cycles else None
            ),
            "avg_acceptance_score": (
                round(
                    statistics.mean(record.total_score for record in finals),
                    4,
                )
                if finals
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Demo helpers
    # ------------------------------------------------------------------
    def run_learning_demo(self, rounds: int = 5) -> dict:
        """Accept several tasks, then show weight and ranking drift."""
        if self.personalizer is None:
            raise ValueError("personalizer is required for the learning demo")
        rounds = max(1, min(int(rounds), 10))
        payload = self.demo_payload()
        customer = self.store.customers[payload["task"].customer_id]
        customer_id = customer.customer_id
        reference = self.store.reference_time

        from app.service import RecommendationService

        def candidates() -> list[Task]:
            return sorted(
                [
                    task
                    for task in self.store.tasks.values()
                    if task.category == "consulting_research"
                    and task.status == "open"
                    and _aware(task.deadline) > reference
                ],
                key=lambda task: task.deadline,
            )

        available = candidates()
        if not available:
            available = [payload["task"]]
        learning_tasks = available[:rounds]
        if len(learning_tasks) < rounds:
            learning_tasks = [
                available[index % len(available)]
                for index in range(rounds)
            ]
        target_tasks = available[:12]

        def ranking(task: Task, weights: dict) -> list[dict]:
            service = RecommendationService(self.store, weights=weights)
            return [
                {
                    "worker_id": candidate.candidate_id,
                    "score": round(candidate.score, 4),
                }
                for candidate in service.recommend_workers_for_task(
                    task, top_n=5
                )
            ]

        before = dict(
            self.personalizer.weights_for(customer_id).weights
        )
        before_rankings = {
            task.task_id: ranking(task, before) for task in target_tasks
        }
        scores = [
            (0.9, 0.8),
            (0.85, 0.8),
            (0.95, 0.85),
            (0.8, 0.75),
            (0.9, 0.9),
        ]

        history = []
        learning = None
        used_workers: list[str] = []
        for index in range(rounds):
            task = learning_tasks[index]
            current_weights = self.personalizer.weights_for(
                customer_id
            ).weights
            picks = RecommendationService(
                self.store, weights=current_weights
            ).recommend_workers_for_task(task, top_n=1)
            if not picks:
                continue
            worker_id = picks[0].candidate_id
            used_workers.append(worker_id)
            insight, citation = scores[index % len(scores)]
            submission, _ = self.submit(
                task.task_id,
                worker_id,
                example_research_artifacts(),
                submitted_at=reference,
            )
            self.review(
                submission.submission_id,
                customer_id,
                {
                    "insight": insight,
                    "citation_consistency": citation,
                },
            )
            record, _ = self.decide(
                submission.submission_id,
                customer_id,
                "accepted",
                comment="learning demo",
                learn=False,
            )
            learning = self._learn_from_acceptance(
                task, record, customer_id=customer_id
            )
            history.append(
                {
                    "round": index + 1,
                    "task_id": task.task_id,
                    "task_title": task.title,
                    "worker_id": worker_id,
                    "decision": record.decision,
                    "score": record.total_score,
                    "sample_count": (
                        learning["sample_count"] if learning else 0
                    ),
                    "weights": (
                        dict(learning["after"]) if learning else {}
                    ),
                }
            )

        after = dict(
            self.personalizer.weights_for(customer_id).weights
        )
        after_rankings = {
            task.task_id: ranking(task, after) for task in target_tasks
        }

        best_task = target_tasks[0]
        best_before = before_rankings[best_task.task_id]
        best_after = after_rankings[best_task.task_id]
        best_movement = -1.0
        best_score_delta = -1.0
        for task in target_tasks:
            before_ranking = before_rankings[task.task_id]
            after_ranking = after_rankings[task.task_id]
            before_position = {
                item["worker_id"]: index + 1
                for index, item in enumerate(before_ranking)
            }
            movement = sum(
                abs(index + 1 - before_position.get(item["worker_id"], index + 1))
                for index, item in enumerate(after_ranking)
            )
            score_delta = sum(
                abs(
                    item["score"]
                    - next(
                        (
                            old["score"]
                            for old in before_ranking
                            if old["worker_id"] == item["worker_id"]
                        ),
                        item["score"],
                    )
                )
                for item in after_ranking
            )
            if movement > best_movement or (
                movement == best_movement
                and score_delta > best_score_delta
            ):
                best_movement = movement
                best_score_delta = score_delta
                best_task = task
                best_before = before_ranking
                best_after = after_ranking

        before_position = {
            item["worker_id"]: index + 1
            for index, item in enumerate(best_before)
        }
        ranking_changes = [
            {
                "worker_id": item["worker_id"],
                "after_rank": index + 1,
                "before_rank": before_position.get(item["worker_id"]),
                "score": item["score"],
            }
            for index, item in enumerate(best_after)
        ]
        deltas = {
            key: round(after[key] - before.get(key, 0.0), 4)
            for key in after
        }
        increases = {
            key: value for key, value in deltas.items() if value > 0
        }
        decreases = {
            key: value for key, value in deltas.items() if value < 0
        }
        return {
            "task_id": best_task.task_id,
            "task_title": best_task.title,
            "worker_id": used_workers[-1] if used_workers else None,
            "worker_count": len(set(used_workers)),
            "customer_id": customer_id,
            "rounds": history,
            "weights_before": before,
            "weights_after": after,
            "deltas": deltas,
            "top_up": (
                max(increases, key=increases.get) if increases else None
            ),
            "top_down": (
                min(decreases, key=decreases.get) if decreases else None
            ),
            "sample_count": (
                learning["sample_count"] if learning else 0
            ),
            "before_ranking": best_before,
            "after_ranking": best_after,
            "ranking_changes": ranking_changes,
            "capability": (
                self.capability(used_workers[-1])
                if used_workers
                else None
            ),
        }

    def demo_payload(self) -> dict:
        reference = self.store.reference_time
        candidates = [
            task
            for task in self.store.tasks.values()
            if task.category == "consulting_research"
            and task.status == "open"
            and _aware(task.deadline) > reference
        ]
        if not candidates:
            candidates = [
                task
                for task in self.store.tasks.values()
                if task.category == "consulting_research"
            ]
        if not candidates:
            raise ValueError("no consulting_research task available")
        task = min(candidates, key=lambda item: item.deadline)
        spec = self.spec_for(task)
        workers = [
            worker
            for worker in self.store.workers.values()
            if worker.status == "active"
            and worker.skills.get("research", 0) >= 3
        ]
        if not workers:
            workers = list(self.store.workers.values())
        worker = max(
            workers,
            key=lambda item: (
                item.skills.get("research", 0),
                item.level,
            ),
        )
        return {
            "task": task,
            "spec": spec,
            "worker_id": worker.worker_id,
            "worker_name": worker.name,
            "reference_time": self.store.reference_time,
            "example_artifacts": example_research_artifacts(),
        }


def example_research_artifacts() -> dict:
    sources = [
        {
            "title": f"Market source {index + 1}",
            "url": f"https://example.com/source/{index + 1}",
            "date": "2026-10-01",
        }
        for index in range(8)
    ]
    return {
        "content": "B2B 市场进入研究：覆盖市场规模、客户细分、竞争格局与进入建议。" * 3,
        "sections": {
            "market_size": "2026 年目标市场规模约 120 亿元，预计未来三年复合增速 18%。" * 2,
            "customer_segments": "核心客户分为大型制造企业、区域经销商与成长型品牌三类。" * 2,
            "competitive_landscape": "头部三家占据约 45% 份额，剩余市场高度分散，存在整合机会。" * 2,
            "entry_recommendation": "建议先以华东区域中型制造企业为切入口，采用渠道合作加直销。" * 2,
        },
        "sources": sources,
        "data_table": [
            {
                "market": "华东",
                "size": 42,
                "cagr": 0.18,
                "source": "source/1",
            },
            {
                "market": "华南",
                "size": 31,
                "cagr": 0.15,
                "source": "source/2",
            },
            {
                "market": "华北",
                "size": 27,
                "cagr": 0.12,
                "source": "source/3",
            },
        ],
        "tam": 120,
        "sam": 48,
        "som": 12,
    }
