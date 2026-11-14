"""In-memory data store for Phase 1."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain import (
    Assignment,
    Customer,
    Feedback,
    Impression,
    LearningSnapshot,
    RecommendationEvent,
    Task,
    TaskChain,
    UserProfile,
    UserWeightProfile,
    Worker,
)
from app.preference.customer import CustomerPreferenceProfile
from app.preference.worker import WorkerPreferenceProfile


def _aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


class Store:
    """Indexes domain entities by ID and keeps interaction history."""

    def __init__(
        self,
        workers: list[Worker],
        customers: list[Customer],
        tasks: list[Task],
        assignments: list[Assignment],
        feedback: list[Feedback],
        templates: dict[str, dict] | None = None,
        chains: dict[str, TaskChain] | None = None,
        profiles: dict[str, UserProfile] | None = None,
        user_weight_profiles: dict[str, UserWeightProfile] | None = None,
        learning_snapshots: list[LearningSnapshot] | None = None,
        worker_preferences: dict[str, WorkerPreferenceProfile] | None = None,
        customer_preferences: dict[str, CustomerPreferenceProfile] | None = None,
        events: list[RecommendationEvent] | None = None,
        impressions: list[Impression] | None = None,
    ) -> None:
        self.workers = {worker.worker_id: worker for worker in workers}
        self.customers = {customer.customer_id: customer for customer in customers}
        self.tasks = {task.task_id: task for task in tasks}
        self.assignments = list(assignments)
        self.feedback = list(feedback)
        self.templates = dict(templates or {})
        self.chains = dict(chains or {})
        self.profiles = dict(profiles or {})
        self.user_weight_profiles = dict(user_weight_profiles or {})
        self.learning_snapshots = list(learning_snapshots or [])
        self.worker_preferences = dict(worker_preferences or {})
        self.customer_preferences = dict(customer_preferences or {})
        self.events = list(events or [])
        self.impressions = list(impressions or [])

    @property
    def reference_time(self) -> datetime:
        """Data-relative 'now' so recency checks do not drift with wall clock."""
        timestamps = [
            _aware(assignment.created_at) for assignment in self.assignments
        ]
        timestamps.extend(_aware(event.created_at) for event in self.events)
        timestamps.extend(
            _aware(impression.created_at) for impression in self.impressions
        )
        if not timestamps:
            return datetime.now(timezone.utc)
        return max(timestamps)

    def events_for(self, request_id: str) -> list[RecommendationEvent]:
        return sorted(
            (
                event
                for event in self.events
                if event.request_id == request_id
            ),
            key=lambda event: _aware(event.created_at),
        )

    def events_for_user(self, user_id: str) -> list[RecommendationEvent]:
        return sorted(
            (
                event
                for event in self.events
                if event.user_id == user_id
            ),
            key=lambda event: _aware(event.created_at),
        )

    def recent_impression_counts(
        self,
        now: datetime,
        days: int = 30,
    ) -> dict[str, int]:
        cutoff = _aware(now) - timedelta(days=days)
        end = _aware(now)
        counts: dict[str, int] = {}
        for impression in self.impressions:
            if cutoff <= _aware(impression.created_at) <= end:
                for candidate_id in impression.candidate_ids:
                    counts[candidate_id] = counts.get(candidate_id, 0) + 1
        return counts

    def prior_collaboration_count(
        self,
        customer_id: str,
        worker_id: str,
        before: datetime | None = None,
    ) -> int:
        reference = before if before is not None else self.reference_time
        cutoff = _aware(reference)
        return sum(
            1
            for assignment in self.assignments
            if assignment.status == "completed"
            and assignment.customer_id == customer_id
            and assignment.worker_id == worker_id
            and _aware(assignment.created_at) < cutoff
        )

    def worker_ratings(self, worker_id: str) -> list[float]:
        worker = self.workers.get(worker_id)
        return list(worker.ratings) if worker else []

    def worker_assignments(self, worker_id: str) -> list[Assignment]:
        return [a for a in self.assignments if a.worker_id == worker_id]
