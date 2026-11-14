"""Recommendation orchestration: hard constraints, scoring, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import (
    BREACH_EXCLUDE_THRESHOLD,
    DEFAULT_WEIGHTS,
)
from app.data.store import Store
from app.domain import Customer, Task, Worker
from app.features import (
    candidate_features,
    fuse_scores,
    pay_fit_score,
    skill_score,
)
from app.learning.acceptance import AcceptanceModel, accept_features
from app.reputation import recent_breach_count as _recent_breach_count
from app.models.itemcf import ItemCF
from app.semantic import (
    SemanticMatcher,
    build_task_text,
    build_worker_text,
)


@dataclass
class ScoredCandidate:
    candidate_id: str
    score: float
    breakdown: dict[str, float]
    reasons: list[str]
    cold_start: bool
    propensity: float = 1.0


def is_eligible(
    worker: Worker,
    task: Task,
    store: Store,
    now: datetime | None = None,
    require_skills: bool = True,
) -> tuple[bool, str]:
    if task.status != "open":
        return False, "task is not open"
    if worker.status != "active":
        return False, "worker is not active"
    if require_skills:
        for skill, minimum in task.required_skills.items():
            if worker.skills.get(skill, 0) < minimum:
                return False, f"missing skill: {skill}"
    if worker.level < task.required_level:
        return False, "worker level below required"
    if (
        worker.current_load_hours + task.estimated_hours
        > worker.capacity_hours
    ):
        return False, "worker capacity exceeded"
    if store.has_assignment_pair(task.task_id, worker.worker_id):
        return False, "worker already assigned to this task"
    if _recent_breach_count(worker, now or store.reference_time) >= BREACH_EXCLUDE_THRESHOLD:
        return False, "worker has two or more recent breaches"
    return True, "eligible"


def _as_aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _build_itemcf(store: Store) -> ItemCF:
    assignment_ids = {
        assignment.assignment_id for assignment in store.assignments
    }
    rated_pairs = {
        (feedback.worker_id, feedback.task_id)
        for feedback in store.feedback
        if feedback.assignment_id in assignment_ids
    }
    interactions: list[tuple[str, str, float]] = []
    for assignment in store.assignments:
        if assignment.status != "completed":
            continue
        weight = (
            1.0
            if (assignment.worker_id, assignment.task_id) in rated_pairs
            else 0.5
        )
        interactions.append(
            (assignment.worker_id, assignment.task_id, weight)
        )
    return ItemCF(interactions)


class RecommendationService:
    def __init__(
        self,
        store: Store,
        weights: dict[str, float] | None = None,
        semantic_matcher: SemanticMatcher | None = None,
        acceptance_model: AcceptanceModel | None = None,
    ) -> None:
        self.store = store
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.itemcf = _build_itemcf(store)
        self.semantic_matcher = semantic_matcher
        self.acceptance_model = acceptance_model
        self._acceptance_cache_key = None
        self._acceptance_cache: dict[str, tuple[int, int]] = {}
        self._collaboration_cache_key = None
        self._collaboration_cache: dict[tuple[str, str], int] = {}

    @property
    def reference_time(self) -> datetime:
        """Data-relative ``now``; cheap because ``Store`` caches it."""
        return self.store.reference_time

    def _weights_for(
        self, user_id: str | None = None
    ) -> dict[str, float]:
        if user_id:
            profile = self.store.user_weight_profiles.get(user_id)
            if profile is not None:
                return profile.weights
        return self.weights

    @staticmethod
    def _communication(worker: Worker) -> float:
        ratings = worker.communication_ratings
        if not ratings:
            return 0.5
        return max(0.0, min(1.0, sum(ratings) / len(ratings) / 5.0))

    @staticmethod
    def _region_match(worker: Worker, task: Task) -> float:
        if worker.region == task.region:
            return 1.0
        if worker.remote_ok and task.remote_ok:
            return 0.8
        return 0.3

    def _acceptance_counts(self) -> dict[str, tuple[int, int]]:
        if self.acceptance_model is None:
            return {}
        key = (id(self.store.events), len(self.store.events))
        if self._acceptance_cache_key == key:
            return self._acceptance_cache
        counts: dict[str, tuple[int, int]] = {}
        for event in self.store.events:
            if event.candidate_type != "worker":
                continue
            if event.action not in {"accept", "reject"}:
                continue
            accepted, rejected = counts.get(event.candidate_id, (0, 0))
            if event.action == "accept":
                accepted += 1
            else:
                rejected += 1
            counts[event.candidate_id] = (accepted, rejected)
        self._acceptance_cache_key = key
        self._acceptance_cache = counts
        return counts

    def _collaboration_counts(self) -> dict[tuple[str, str], int]:
        """Prior completed pairs, indexed once and reused while data is static."""
        cutoff = _as_aware(self.reference_time)
        key = (
            id(self.store.assignments),
            len(self.store.assignments),
            cutoff,
        )
        if self._collaboration_cache_key == key:
            return self._collaboration_cache
        counts: dict[tuple[str, str], int] = {}
        for assignment in self.store.assignments:
            if assignment.status != "completed":
                continue
            if _as_aware(assignment.created_at) >= cutoff:
                continue
            key_pair = (assignment.customer_id, assignment.worker_id)
            counts[key_pair] = counts.get(key_pair, 0) + 1
        self._collaboration_cache_key = key
        self._collaboration_cache = counts
        return counts

    @staticmethod
    def _historical_accept_rate(
        counts: dict[str, tuple[int, int]], worker_id: str
    ) -> float:
        accepted, rejected = counts.get(worker_id, (0, 0))
        if accepted + rejected == 0:
            return 0.5
        return (accepted + 1) / (accepted + rejected + 2)

    def _semantic(
        self, worker: Worker, task: Task
    ) -> float:
        if self.semantic_matcher is None:
            return 0.5
        return self.semantic_matcher.similarity(
            build_task_text(task), build_worker_text(worker)
        )

    def _p_accept(
        self,
        worker: Worker,
        task: Task,
        task_skill: float,
        pay_fit: float,
        accept_counts: dict[str, tuple[int, int]],
    ) -> float | None:
        model = self.acceptance_model
        if model is None or not model.is_fitted:
            return None
        features = accept_features(
            worker,
            task,
            skill=task_skill,
            pay_fit=pay_fit,
            region_match=self._region_match(worker, task),
            historical_accept_rate=self._historical_accept_rate(
                accept_counts, worker.worker_id
            ),
        )
        return model.predict(features)

    def _build_features(
        self,
        worker: Worker,
        task: Task,
        customer: Customer,
        cf_score: float,
        recent_impressions: int,
        accept_counts: dict[str, tuple[int, int]],
        collaboration_counts: dict[tuple[str, str], int],
    ) -> dict[str, float]:
        pay_fit = pay_fit_score(worker, task)
        return candidate_features(
            worker,
            task,
            customer,
            cf_score=cf_score,
            now=self.reference_time,
            worker_profile=self.store.worker_preferences.get(
                worker.worker_id
            ),
            customer_profile=self.store.customer_preferences.get(
                customer.customer_id
            ),
            semantic_similarity=self._semantic(worker, task),
            p_accept=self._p_accept(
                worker,
                task,
                skill_score(worker, task),
                pay_fit,
                accept_counts,
            ),
            recent_impressions=recent_impressions,
            pay_fit=pay_fit,
            communication=self._communication(worker),
            collaboration=collaboration_counts.get(
                (customer.customer_id, worker.worker_id), 0
            ),
        )

    def _task_context(self, task: Task):
        """Shared serving context: eligible pool, normalized CF, and counts.

        Mirrors exactly the inputs used by ``recommend_workers_for_task`` so
        ``features_for`` stays in feature parity with serving.
        """
        customer = self.store.customers.get(task.customer_id)
        if customer is None:
            customer = Customer(
                customer_id=task.customer_id,
                name="Unknown",
                region=task.region,
            )
        eligible = [
            worker
            for worker in self.store.workers.values()
            if is_eligible(
                worker, task, self.store, now=self.reference_time
            )[0]
        ]
        raw_cf = {
            (worker.worker_id, task.task_id): self.itemcf.score(
                worker.worker_id, task.task_id
            )
            for worker in eligible
        }
        return (
            customer,
            eligible,
            self.itemcf.normalize(raw_cf),
            self.store.recent_impression_counts(self.reference_time),
            self._acceptance_counts(),
            self._collaboration_counts(),
        )

    def features_for(
        self, task_id: str, worker_id: str
    ) -> dict[str, float]:
        """Build the seven fusion features for one (task, worker) pair.

        Reuses the same feature-building path as serving: normalized ItemCF,
        semantic matcher similarity (0.5 only without a matcher), ``p_accept``
        from a fitted acceptance model, recent impressions, collaboration,
        communication, pay fit, profiles, and the service reference time.
        ``KeyError`` is raised for unknown task or worker IDs so callers can
        skip events that no longer resolve to store entities.
        """
        task = self.store.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        worker = self.store.workers.get(worker_id)
        if worker is None:
            raise KeyError(worker_id)
        (
            customer,
            _eligible,
            normalized_cf,
            recent_impressions,
            accept_counts,
            collaboration_counts,
        ) = self._task_context(task)
        return self._build_features(
            worker,
            task,
            customer,
            normalized_cf.get((worker_id, task_id), 0.0),
            recent_impressions.get(worker_id, 0),
            accept_counts,
            collaboration_counts,
        )

    def recommend_workers(
        self, task_id: str, top_n: int = 10, user_id: str | None = None
    ) -> list[ScoredCandidate]:
        task = self.store.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return self.recommend_workers_for_task(
            task, top_n=top_n, user_id=user_id
        )

    def recommend_workers_for_task(
        self,
        task: Task,
        top_n: int = 10,
        user_id: str | None = None,
    ) -> list[ScoredCandidate]:
        weights = self._weights_for(user_id)
        (
            customer,
            eligible,
            normalized_cf,
            recent_impressions,
            accept_counts,
            collaboration_counts,
        ) = self._task_context(task)

        candidates: list[ScoredCandidate] = []
        for worker in eligible:
            cf_score = normalized_cf.get(
                (worker.worker_id, task.task_id), 0.0
            )
            features = self._build_features(
                worker,
                task,
                customer,
                cf_score,
                recent_impressions.get(worker.worker_id, 0),
                accept_counts,
                collaboration_counts,
            )
            score = fuse_scores(features, weights)
            cold_start = not self.store.worker_assignments(worker.worker_id)
            reasons = [
                f"skill={features['skill']:.2f}",
                f"reputation={features['reputation']:.2f}",
                f"expertise={features['expertise']:.2f}",
            ]
            if cold_start:
                reasons.append("cold start: no assignment history")
            candidates.append(
                ScoredCandidate(
                    candidate_id=worker.worker_id,
                    score=score,
                    breakdown={key: round(value, 4) for key, value in features.items()},
                    reasons=reasons,
                    cold_start=cold_start,
                )
            )

        candidates.sort(key=lambda c: (-c.score, c.candidate_id))
        return candidates[: max(0, top_n)]

    def recommend_tasks(
        self,
        worker_id: str,
        top_n: int = 10,
        user_id: str | None = None,
        candidate_ids: set[str] | None = None,
        require_skills: bool = True,
    ) -> list[ScoredCandidate]:
        worker = self.store.workers.get(worker_id)
        if worker is None:
            raise KeyError(worker_id)
        weights = self._weights_for(user_id)

        assigned_task_ids = {
            assignment.task_id
            for assignment in self.store.worker_assignments(worker_id)
        }
        eligible: list[Task] = []
        for task in self.store.tasks.values():
            if candidate_ids is not None and task.task_id not in candidate_ids:
                continue
            if task.task_id in assigned_task_ids:
                continue
            ok, _ = is_eligible(
                worker,
                task,
                self.store,
                now=self.reference_time,
                require_skills=require_skills,
            )
            if ok:
                eligible.append(task)

        raw_cf = {
            (worker.worker_id, task.task_id): self.itemcf.score(
                worker.worker_id, task.task_id
            )
            for task in eligible
        }
        normalized_cf = self.itemcf.normalize(raw_cf)
        recent_impressions = self.store.recent_impression_counts(
            self.reference_time
        )
        accept_counts = self._acceptance_counts()
        collaboration_counts = self._collaboration_counts()

        candidates: list[ScoredCandidate] = []
        cold_start = not self.store.worker_assignments(worker_id)
        for task in eligible:
            customer = self.store.customers.get(task.customer_id)
            if customer is None:
                customer = Customer(
                    customer_id=task.customer_id,
                    name="Unknown",
                    region=task.region,
                )
            cf_score = normalized_cf.get(
                (worker.worker_id, task.task_id), 0.0
            )
            features = self._build_features(
                worker,
                task,
                customer,
                cf_score,
                recent_impressions.get(worker.worker_id, 0),
                accept_counts,
                collaboration_counts,
            )
            score = fuse_scores(features, weights)
            reasons = [
                f"skill={features['skill']:.2f}",
                f"preference={features['preference']:.2f}",
                f"load={features['load']:.2f}",
            ]
            if cold_start:
                reasons.append("cold start: no assignment history")
            candidates.append(
                ScoredCandidate(
                    candidate_id=task.task_id,
                    score=score,
                    breakdown={key: round(value, 4) for key, value in features.items()},
                    reasons=reasons,
                    cold_start=cold_start,
                )
            )

        candidates.sort(key=lambda c: (-c.score, c.candidate_id))
        return candidates[: max(0, top_n)]
