"""Pydantic request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Event ingestion bounds. A recommendation has at most ``top_n <= 100``
# candidates, so a larger batch is always abusive or accidental. Metadata is a
# small audit payload, not a free-form document store.
MAX_EVENTS_PER_BATCH = 200
MAX_EVENT_METADATA_KEYS = 20
MAX_EVENT_METADATA_TEXT = 2_000
MAX_EVENTS_BODY_BYTES = 1 * 1024 * 1024


class RecommendWorkersRequest(BaseModel):
    task_id: str
    top_n: int = Field(default=10, ge=1, le=100)
    explain: bool = True
    user_id: str | None = None


class RecommendTasksRequest(BaseModel):
    worker_id: str
    top_n: int = Field(default=10, ge=1, le=100)
    explain: bool = True
    user_id: str | None = None


class CandidateResponse(BaseModel):
    candidate_id: str
    score: float
    breakdown: dict[str, float]
    reasons: list[str]
    cold_start: bool
    propensity: float = 1.0


class RecommendResponse(BaseModel):
    query_id: str
    candidates: list[CandidateResponse]
    reason: str | None = None
    request_id: str = ""


class EventItem(BaseModel):
    request_id: str
    candidate_id: str
    candidate_type: str = "worker"
    action: Literal["click", "apply", "accept", "reject", "ignore"]
    task_id: str | None = None
    user_id: str | None = None
    role: str = "customer"
    metadata: dict = Field(default_factory=dict)

    @field_validator("request_id", "candidate_id")
    @classmethod
    def _bounded_id(cls, value: str) -> str:
        if not value or len(value) > 128:
            raise ValueError("id must be 1-128 characters")
        return value

    @field_validator("metadata")
    @classmethod
    def _bounded_metadata(cls, value: dict) -> dict:
        if len(value) > MAX_EVENT_METADATA_KEYS:
            raise ValueError(
                f"metadata has more than {MAX_EVENT_METADATA_KEYS} keys"
            )
        text_length = sum(
            len(str(key)) + len(str(item)) for key, item in value.items()
        )
        if text_length > MAX_EVENT_METADATA_TEXT:
            raise ValueError(
                f"metadata exceeds {MAX_EVENT_METADATA_TEXT} characters"
            )
        return value


class EventsRequest(BaseModel):
    events: list[EventItem] = Field(
        min_length=1, max_length=MAX_EVENTS_PER_BATCH
    )


class EventsResponse(BaseModel):
    accepted: int
    rejected: list[dict] = Field(default_factory=list)


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=4, max_length=5000)
    top_k: int = Field(default=3, ge=1, le=6)


class ResumeAnalyzeRequest(BaseModel):
    """Paste-text resume path for ``POST /resume/analyze`` (no file upload)."""

    text: str = Field(min_length=4, max_length=50000)
    top_n: int = Field(default=5, ge=1, le=50)


class SubmissionRequest(BaseModel):
    worker_id: str
    artifacts: dict
    submitted_at: datetime | None = None


class ReviewRequest(BaseModel):
    reviewer_id: str = "customer"
    layer: str = "customer"
    scores: dict[str, float]
    comments: dict[str, str] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    reviewer_id: str = "customer"
    decision: str
    comment: str = ""


class DecomposeRequest(BaseModel):
    task_id: str
    mode: str = "template"
    variant: str = "standard"
    categories: list[str] | None = None


class NodeRecommendRequest(BaseModel):
    top_n: int = Field(default=10, ge=1, le=100)


class RecommendationContext(BaseModel):
    score: float = 0.0
    rank: int = 0
    propensity: float = Field(default=1.0, ge=0, le=1)
    weights_version: str = "v0000"
    request_id: str = ""


class CreateAssignmentRequest(BaseModel):
    task_id: str
    worker_id: str
    customer_id: str
    recommendation_context: RecommendationContext | None = None


class FeedbackRequest(BaseModel):
    assignment_id: str
    overall_rating: int = Field(ge=1, le=5)
    quality_rating: int | None = Field(default=None, ge=1, le=5)
    timeliness_rating: int | None = Field(default=None, ge=1, le=5)
    communication_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = ""


class RollbackRequest(BaseModel):
    to_version: str
    reason: str = ""


class PlanRollbackRequest(BaseModel):
    version: int = Field(ge=1)


class ReplanRequest(BaseModel):
    failed_node: str
    delay_hours: float = 0.0
    locked_nodes: list[str] = Field(default_factory=list)


class NodeStatusRequest(BaseModel):
    status: str
    worker_id: str | None = None


class OnboardingRequest(BaseModel):
    role: str = "unknown"
    industry: str = "unknown"
    experience_years: float = Field(default=0.0, ge=0)
    declared_preferences: dict | None = None
    preferences: dict[str, float] | None = None
    reset: bool = False
