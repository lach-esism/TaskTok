"""Pydantic request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class EventsRequest(BaseModel):
    events: list[EventItem]


class EventsResponse(BaseModel):
    accepted: int
    rejected: list[dict] = Field(default_factory=list)


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=4, max_length=5000)
    top_k: int = Field(default=3, ge=1, le=6)


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
