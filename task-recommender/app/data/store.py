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
        # Incremental indexes. Records are only appended (or the list is
        # replaced); both cases are detected here so repeated request-path
        # calls do not rescan the whole history.
        self._reference_ids: tuple[int, int, int] | None = None
        self._reference_seen: list[int] = [0, 0, 0]
        self._reference_value: datetime | None = None
        self._recent_key = None
        self._recent_seen = 0
        self._recent_counts: dict[str, int] = {}
        self._assignment_pairs_key = None
        self._assignment_pairs: set[tuple[str, str]] = set()

    def has_assignment_pair(self, task_id: str, worker_id: str) -> bool:
        """Whether ``(task_id, worker_id)`` was ever assigned.

        Eligibility checks run once per worker per query; scanning the full
        assignment list there makes evaluation quadratic. The pair index is
        rebuilt only when the assignment list length or identity changes.
        """
        key = (id(self.assignments), len(self.assignments))
        if self._assignment_pairs_key != key:
            self._assignment_pairs = {
                (assignment.task_id, assignment.worker_id)
                for assignment in self.assignments
            }
            self._assignment_pairs_key = key
        return (task_id, worker_id) in self._assignment_pairs

    @property
    def reference_time(self) -> datetime:
        """Data-relative 'now' so recency checks do not drift with wall clock.

        The maximum timestamp is maintained incrementally: only newly appended
        records are inspected. A replaced or shortened list triggers a full
        rebuild. This keeps per-request eligibility/exposure checks from
        scanning the entire assignment/event/impression history.
        """
        lists = (self.assignments, self.events, self.impressions)
        ids = tuple(id(items) for items in lists)
        if self._reference_ids != ids or any(
            len(items) < seen
            for items, seen in zip(lists, self._reference_seen)
        ):
            self._reference_ids = ids
            self._reference_seen = [0, 0, 0]
            self._reference_value = None
        for index, items in enumerate(lists):
            for record in items[self._reference_seen[index]:]:
                timestamp = _aware(record.created_at)
                if (
                    self._reference_value is None
                    or timestamp > self._reference_value
                ):
                    self._reference_value = timestamp
            self._reference_seen[index] = len(items)
        if self._reference_value is None:
            return datetime.now(timezone.utc)
        return self._reference_value

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
        """Candidate impression counts in the trailing window.

        The window result is cached per ``(list identity, cutoff, end)`` and
        extended only with newly appended impressions. Serving calls this once
        per recommendation, so an O(history) rescan would make the request path
        quadratic as the log grows.
        """
        cutoff = _aware(now) - timedelta(days=days)
        end = _aware(now)
        key = (id(self.impressions), cutoff, end)
        if (
            self._recent_key == key
            and len(self.impressions) >= self._recent_seen
        ):
            new_items = self.impressions[self._recent_seen:]
        else:
            self._recent_key = key
            self._recent_seen = 0
            self._recent_counts = {}
            new_items = self.impressions
        for impression in new_items:
            created_at = _aware(impression.created_at)
            if cutoff <= created_at <= end:
                for candidate_id in impression.candidate_ids:
                    self._recent_counts[candidate_id] = (
                        self._recent_counts.get(candidate_id, 0) + 1
                    )
        self._recent_seen = len(self.impressions)
        return dict(self._recent_counts)

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
