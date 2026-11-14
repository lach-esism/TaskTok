"""Domain entities for the Phase 1 task assignment recommender."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypeVar

RecordT = TypeVar("RecordT")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normalize naive datetimes to UTC for safe comparisons."""
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _split_by_assignment(
    records: list[RecordT],
    train_ids: set[str],
    test_ids: set[str],
    split_time: datetime,
) -> tuple[list[RecordT], list[RecordT]]:
    """Split event/impression records, preferring assignment metadata.

    Records carrying ``metadata["assignment_id"]`` are classified by the
    assignment's split, which stays correct when a train and a test assignment
    share the boundary timestamp. Records without assignment metadata fall
    back to timestamps; ties at ``split_time`` are conservatively placed in
    test so a test record can never leak into train.
    """
    train: list[RecordT] = []
    test: list[RecordT] = []
    for record in records:
        metadata = getattr(record, "metadata", None)
        assignment_id = (
            metadata.get("assignment_id")
            if isinstance(metadata, dict)
            else None
        )
        if assignment_id in train_ids:
            train.append(record)
        elif assignment_id in test_ids:
            test.append(record)
        elif _as_utc(record.created_at) < split_time:
            train.append(record)
        else:
            test.append(record)
    return train, test


@dataclass
class Worker:
    worker_id: str
    name: str
    skills: dict[str, int]
    specialties: dict[str, int]
    level: int
    capacity_hours: float
    current_load_hours: float
    preferred_categories: dict[str, float]
    preferred_difficulty: tuple[int, int]
    region: str
    remote_ok: bool
    status: str = "active"
    ratings: list[float] = field(default_factory=list)
    completed: int = 0
    on_time: int = 0
    rework_count: int = 0
    breach_dates: list[datetime] = field(default_factory=list)
    category_ratings: dict[str, list[float]] = field(default_factory=dict)
    expected_pay: float = 0.0
    certifications: dict[str, float] = field(default_factory=dict)
    communication_ratings: list[float] = field(default_factory=list)


@dataclass
class Customer:
    customer_id: str
    name: str
    region: str
    preference_weights: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class UserProfile:
    user_id: str
    entity_type: str
    role: str
    industry: str
    experience_years: float
    skills: dict[str, int]
    specialties: dict[str, int]
    region: str
    preferred_categories: dict[str, float]
    profile_completeness: float
    segment_id: str
    declared_preferences: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Segment:
    segment_id: str
    name: str
    centroid: dict
    weights: dict[str, float]
    member_count: int


@dataclass
class UserWeightProfile:
    user_id: str
    weights: dict[str, float]
    source: str
    segment_id: str
    sample_count: int
    confidence: float
    version: str
    updated_at: datetime = field(default_factory=_utcnow)
    initial_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class LearningSnapshot:
    user_id: str
    n_feedback: int
    weights: dict[str, float]
    ndcg_at_10: float
    hr_at_10: float
    regret: float
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Task:
    task_id: str
    customer_id: str
    title: str
    category: str
    required_skills: dict[str, int]
    required_level: int
    difficulty: int
    priority: int
    estimated_hours: float
    deadline: datetime
    region: str
    remote_ok: bool
    description: str = ""
    status: str = "open"
    budget: float = 0.0
    requirements: list[str] = field(default_factory=list)
    budget_min: float = 0.0
    budget_max: float = 0.0
    created_at: datetime = field(default_factory=_utcnow)
    required_skill_weights: dict[str, float] = field(default_factory=dict)
    # Marketplace presentation data set by the publisher (verify method,
    # deliverables, acceptance notes, checklist). Not used for ranking.
    meta: dict = field(default_factory=dict)


@dataclass
class Application:
    """A worker's request to take an open task (marketplace flow).

    ``pending`` → ``accepted`` (customer selected this worker, an
    ``Assignment`` exists) | ``rejected`` (another worker was selected) |
    ``withdrawn`` (worker cancelled).
    """

    application_id: str
    task_id: str
    worker_id: str
    status: str = "pending"
    note: str = ""
    source: str = "self"   # self (worker applied) | invited (recommended)
    request_id: str | None = None
    score: float | None = None
    assignment_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Assignment:
    assignment_id: str
    task_id: str
    worker_id: str
    customer_id: str
    status: str = "completed"
    on_time: bool = True
    rework_count: int = 0
    breach_type: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    recommended_at: datetime | None = None
    recommendation_score: float = 0.0
    recommendation_rank: int = 0
    propensity: float = 1.0
    weights_version: str = "v0000"


@dataclass
class Feedback:
    feedback_id: str
    assignment_id: str
    worker_id: str
    task_id: str
    overall_rating: int
    created_at: datetime = field(default_factory=_utcnow)
    quality_rating: int | None = None
    timeliness_rating: int | None = None
    communication_rating: int | None = None
    comment: str = ""
    propensity: float = 1.0


@dataclass
class Impression:
    request_id: str
    query_id: str
    candidate_ids: list[str]
    propensities: dict[str, float]
    policy: str
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)


@dataclass
class RecommendationEvent:
    event_id: str
    request_id: str
    user_id: str | None
    role: str
    task_id: str
    candidate_id: str
    candidate_type: str
    rank: int
    score: float
    propensity: float
    weights_version: str
    action: str
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)


@dataclass
class AcceptanceCriterion:
    key: str
    label: str
    dimension: str
    layer: str = "machine"
    required: bool = False
    weight: float = 0.0
    check_type: str = "manual"
    check_config: dict = field(default_factory=dict)
    evidence_required: bool = False


@dataclass
class AcceptanceSpec:
    spec_id: str
    task_id: str
    version: int
    criteria: list[AcceptanceCriterion]
    accept_threshold: float = 0.80
    rework_threshold: float = 0.50
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class CriterionResult:
    criterion_key: str
    passed: bool
    score: float
    evidence: str = ""
    comment: str = ""


@dataclass
class Submission:
    submission_id: str
    task_id: str
    worker_id: str
    version: int
    artifacts: dict
    submitted_at: datetime
    spec_version: int = 1
    status: str = "submitted"
    machine_results: list[CriterionResult] = field(default_factory=list)
    human_results: list[CriterionResult] = field(default_factory=list)


@dataclass
class AcceptanceRecord:
    record_id: str
    submission_id: str
    task_id: str
    worker_id: str
    spec_version: int
    layer: str
    reviewer_id: str
    criterion_results: list[CriterionResult] = field(default_factory=list)
    total_score: float = 0.0
    decision: str = "pending"
    comment: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class LearningEvent:
    event_id: str
    event_type: str
    version: str
    user_id: str | None
    sample_count: int
    metrics: dict
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Dataset:
    workers: list[Worker]
    customers: list[Customer]
    tasks: list[Task]
    assignments: list[Assignment]
    feedback: list[Feedback]
    train: list[Assignment]
    test: list[Assignment]
    true_weights: dict[str, dict[str, float]] = field(default_factory=dict)
    new_users: list[Worker] = field(default_factory=list)
    events: list[RecommendationEvent] = field(default_factory=list)
    impressions: list[Impression] = field(default_factory=list)

    @property
    def split_time(self) -> datetime:
        """End of the training window, derived from the latest train assignment."""
        if not self.train:
            return datetime.now(timezone.utc)
        return max(_as_utc(assignment.created_at) for assignment in self.train)

    @property
    def train_feedback(self) -> list[Feedback]:
        train_ids = {assignment.assignment_id for assignment in self.train}
        return [
            item
            for item in self.feedback
            if item.assignment_id in train_ids
        ]

    @property
    def test_feedback(self) -> list[Feedback]:
        test_ids = {assignment.assignment_id for assignment in self.test}
        return [
            item
            for item in self.feedback
            if item.assignment_id in test_ids
        ]

    def _event_split(
        self,
    ) -> tuple[list[RecommendationEvent], list[RecommendationEvent]]:
        return _split_by_assignment(
            self.events,
            {assignment.assignment_id for assignment in self.train},
            {assignment.assignment_id for assignment in self.test},
            _as_utc(self.split_time),
        )

    def _impression_split(self) -> tuple[list[Impression], list[Impression]]:
        return _split_by_assignment(
            self.impressions,
            {assignment.assignment_id for assignment in self.train},
            {assignment.assignment_id for assignment in self.test},
            _as_utc(self.split_time),
        )

    @property
    def train_events(self) -> list[RecommendationEvent]:
        return self._event_split()[0]

    @property
    def test_events(self) -> list[RecommendationEvent]:
        return self._event_split()[1]

    @property
    def train_impressions(self) -> list[Impression]:
        return self._impression_split()[0]

    @property
    def test_impressions(self) -> list[Impression]:
        return self._impression_split()[1]


@dataclass
class SubTask:
    subtask_id: str
    chain_id: str
    key: str
    title: str
    node_type: str
    estimated_hours: float
    required_skills: dict[str, int]
    depends_on: list[str]
    acceptance: list[str]
    optional: bool = False
    parallel_group: str | None = None
    risk_flags: list[str] = field(default_factory=list)
    status: str = "pending"
    assigned_worker_id: str | None = None


@dataclass
class ChainEdge:
    chain_id: str
    from_node: str
    to_node: str
    edge_type: str = "finish_to_start"


@dataclass
class TaskChain:
    chain_id: str
    root_task_id: str
    customer_id: str
    deadline: datetime
    budget: float
    nodes: list[SubTask] = field(default_factory=list)
    edges: list[ChainEdge] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    status: str = "draft"


@dataclass
class ChainPlanNode:
    subtask_id: str
    worker_id: str | None
    rank: int
    node_score: float


@dataclass
class ChainPlan:
    plan_id: str
    chain_id: str
    score: float
    nodes: list[ChainPlanNode]
    blocked: list[str] = field(default_factory=list)
    planner: str = "greedy"


@dataclass
class DecompositionDraft:
    draft_id: str
    task_id: str
    template_id: str
    variant: str
    chain: TaskChain
    requirements: list[str]
    coverage: dict[str, list[str]]
    quality: "DecompositionQuality | None" = None


@dataclass
class DecompositionQuality:
    coverage: float
    granularity: float
    dependency: float
    feasibility: float
    template_fit: float
    historical_success: float
    risk_penalty: float
    total: float
    issues: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    order: list[str]


@dataclass
class BreachImpact:
    failed_node: str
    affected_nodes: list[str]
    critical_path_delay: float
    chain_slack: float
    severity: float
    requires_replan: bool
