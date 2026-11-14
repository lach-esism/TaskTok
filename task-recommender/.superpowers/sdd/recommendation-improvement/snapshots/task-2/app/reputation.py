"""Reputation breakdown, breach warning, and category shrinkage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import BREACH_WINDOW_DAYS
from app.domain import Worker


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def recent_breach_count(
    worker: Worker, now: datetime | None = None
) -> int:
    current = _aware(now or datetime.now(timezone.utc))
    cutoff = current - timedelta(days=BREACH_WINDOW_DAYS)
    return sum(1 for breach in worker.breach_dates if _aware(breach) >= cutoff)


# Backward-compatible alias used by Phase 1 modules.
_recent_breach_count = recent_breach_count


@dataclass
class ReputationBreakdown:
    rating: float
    completion: float
    on_time: float
    rework: float
    breach_penalty: float
    total: float
    recent_breaches: int
    warning: bool
    excluded: bool


def compute_reputation(
    worker: Worker, now: datetime | None = None
) -> ReputationBreakdown:
    ratings = worker.ratings
    bayesian_rating = (sum(ratings) + 10 * 4.2) / (len(ratings) + 10) / 5.0

    total_breaches = len(worker.breach_dates)
    if worker.completed + total_breaches > 0:
        completion = worker.completed / (worker.completed + total_breaches)
    else:
        completion = 0.5
    on_time = (
        worker.on_time / worker.completed if worker.completed > 0 else 0.5
    )
    rework = (
        1.0 - min(worker.rework_count / worker.completed, 1.0)
        if worker.completed > 0
        else 1.0
    )
    recent = recent_breach_count(worker, now)
    breach_penalty = 1.0 if recent == 0 else (0.5 if recent == 1 else 0.0)

    total = _clamp(
        0.4 * bayesian_rating
        + 0.2 * completion
        + 0.2 * on_time
        + 0.1 * rework
        + 0.1 * breach_penalty
    )
    return ReputationBreakdown(
        rating=bayesian_rating,
        completion=completion,
        on_time=on_time,
        rework=rework,
        breach_penalty=breach_penalty,
        total=total,
        recent_breaches=recent,
        warning=recent == 1,
        excluded=recent >= 2,
    )


def category_reputation(
    worker: Worker,
    category: str,
    m: int = 10,
    now: datetime | None = None,
) -> float:
    global_score = compute_reputation(worker, now=now).total
    category_values = worker.category_ratings.get(category, [])
    if not category_values:
        return global_score
    category_mean = sum(category_values) / len(category_values) / 5.0
    n = len(category_values)
    return _clamp(
        (n * category_mean + m * global_score) / (n + m)
    )
