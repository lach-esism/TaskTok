"""Worker category and difficulty preference updates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from app.domain import Task


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass
class WorkerPreferenceProfile:
    worker_id: str
    category_preferences: dict[str, float] = field(default_factory=dict)
    difficulty_preference: tuple[int, int] = (1, 5)
    confidence: float = 0.0
    last_updated: datetime | None = None


def update_worker_preferences(
    profile: WorkerPreferenceProfile,
    task: Task,
    accepted: bool,
    rating: int | None,
    now: datetime,
    tau_days: float = 30.0,
) -> WorkerPreferenceProfile:
    decay = 1.0
    if profile.last_updated is not None:
        delta_days = (
            now - profile.last_updated
        ).total_seconds() / 86400.0
        decay = math.exp(-max(delta_days, 0.0) / max(tau_days, 1e-9))

    preferences = {
        category: value * decay
        for category, value in profile.category_preferences.items()
    }
    current = preferences.get(task.category, 0.5)

    positive = accepted and (rating is None or rating >= 4)
    negative = (not accepted) or (rating is not None and rating < 3)
    if positive:
        current += (1.0 - current) * 0.3
    elif negative:
        current *= 0.7
    preferences[task.category] = _clamp(current)

    confidence = profile.confidence
    if positive or negative:
        confidence = _clamp(confidence + 0.1)

    return WorkerPreferenceProfile(
        worker_id=profile.worker_id,
        category_preferences=preferences,
        difficulty_preference=profile.difficulty_preference,
        confidence=confidence,
        last_updated=now,
    )
