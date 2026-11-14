"""In-memory data store for Phase 1."""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain import (
    Assignment,
    Customer,
    Feedback,
    LearningSnapshot,
    Task,
    TaskChain,
    UserProfile,
    UserWeightProfile,
    Worker,
)
from app.preference.customer import CustomerPreferenceProfile
from app.preference.worker import WorkerPreferenceProfile


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

    @property
    def reference_time(self) -> datetime:
        """Data-relative 'now' so recency checks do not drift with wall clock."""
        if not self.assignments:
            return datetime.now(timezone.utc)

        def aware(value: datetime) -> datetime:
            return (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value
            )

        return max(aware(assignment.created_at) for assignment in self.assignments)

    def worker_ratings(self, worker_id: str) -> list[float]:
        worker = self.workers.get(worker_id)
        return list(worker.ratings) if worker else []

    def worker_assignments(self, worker_id: str) -> list[Assignment]:
        return [a for a in self.assignments if a.worker_id == worker_id]
