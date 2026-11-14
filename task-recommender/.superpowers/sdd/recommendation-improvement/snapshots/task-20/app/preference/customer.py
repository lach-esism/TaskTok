"""Customer attribute preference updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain import Task, Worker

DEFAULT_ATTRIBUTE_WEIGHTS = {
    "reputation": 0.30,
    "expertise": 0.20,
    "speed": 0.15,
    "communication": 0.10,
    "price": 0.10,
    "collaboration": 0.10,
    "deadline_fit": 0.05,
}


@dataclass
class CustomerPreferenceProfile:
    customer_id: str
    attribute_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_ATTRIBUTE_WEIGHTS)
    )
    confidence: float = 0.0
    last_updated: datetime | None = None


def update_customer_preferences(
    profile: CustomerPreferenceProfile,
    worker: Worker,
    task: Task,
    rating: int,
    now: datetime | None = None,
) -> CustomerPreferenceProfile:
    weights = dict(profile.attribute_weights)
    if rating >= 4:
        weights["reputation"] = weights.get("reputation", 0.0) + 0.05
        weights["expertise"] = weights.get("expertise", 0.0) + 0.03
        weights["speed"] = weights.get("speed", 0.0) + 0.02
    else:
        weights["communication"] = (
            weights.get("communication", 0.0) + 0.05
        )
        weights["price"] = weights.get("price", 0.0) + 0.03

    total = sum(weights.values())
    if total > 0:
        weights = {
            key: value / total for key, value in weights.items()
        }
    return CustomerPreferenceProfile(
        customer_id=profile.customer_id,
        attribute_weights=weights,
        confidence=min(1.0, profile.confidence + 0.1),
        last_updated=now,
    )
