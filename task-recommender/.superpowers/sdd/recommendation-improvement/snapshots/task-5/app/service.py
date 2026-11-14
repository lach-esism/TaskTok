"""Recommendation orchestration: hard constraints, scoring, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.config import (
    BREACH_EXCLUDE_THRESHOLD,
    DEFAULT_WEIGHTS,
)
from app.data.store import Store
from app.domain import Customer, Task, Worker
from app.features import candidate_features, fuse_scores
from app.reputation import recent_breach_count as _recent_breach_count
from app.models.itemcf import ItemCF


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
) -> tuple[bool, str]:
    if task.status != "open":
        return False, "task is not open"
    if worker.status != "active":
        return False, "worker is not active"
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
    if any(
        assignment.task_id == task.task_id
        and assignment.worker_id == worker.worker_id
        for assignment in store.assignments
    ):
        return False, "worker already assigned to this task"
    if _recent_breach_count(worker, now or store.reference_time) >= BREACH_EXCLUDE_THRESHOLD:
        return False, "worker has two or more recent breaches"
    return True, "eligible"


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
    ) -> None:
        self.store = store
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.reference_time = store.reference_time
        self.itemcf = _build_itemcf(store)

    def _weights_for(
        self, user_id: str | None = None
    ) -> dict[str, float]:
        if user_id:
            profile = self.store.user_weight_profiles.get(user_id)
            if profile is not None:
                return profile.weights
        return self.weights

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
        customer = self.store.customers.get(task.customer_id)
        if customer is None:
            customer = Customer(
                customer_id=task.customer_id,
                name="Unknown",
                region=task.region,
            )

        eligible: list[Worker] = []
        for worker in self.store.workers.values():
            ok, _ = is_eligible(
                worker, task, self.store, now=self.reference_time
            )
            if ok:
                eligible.append(worker)

        raw_cf = {
            (worker.worker_id, task.task_id): self.itemcf.score(
                worker.worker_id, task.task_id
            )
            for worker in eligible
        }
        normalized_cf = self.itemcf.normalize(raw_cf)

        candidates: list[ScoredCandidate] = []
        for worker in eligible:
            cf_score = normalized_cf.get(
                (worker.worker_id, task.task_id), 0.0
            )
            features = candidate_features(
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
        self, worker_id: str, top_n: int = 10, user_id: str | None = None
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
            if task.task_id in assigned_task_ids:
                continue
            ok, _ = is_eligible(
                worker, task, self.store, now=self.reference_time
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
            features = candidate_features(
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
