"""Phase 1 feature scoring for the seven-dimension fusion model."""

from __future__ import annotations

from datetime import datetime

from app.domain import Customer, Task, Worker
from app.preference.customer import CustomerPreferenceProfile
from app.preference.worker import WorkerPreferenceProfile
from app.reputation import (
    category_reputation,
    compute_reputation,
    recent_breach_count as _recent_breach_count,
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def skill_score(worker: Worker, task: Task) -> float:
    if not task.required_skills:
        return 1.0
    total = 0.0
    for skill, minimum in task.required_skills.items():
        total += min(worker.skills.get(skill, 0) / max(minimum, 1), 1.0)
    return _clamp(total / len(task.required_skills))


def expertise_score(worker: Worker, task: Task) -> float:
    return _clamp(worker.specialties.get(task.category, 0) / 5.0)


def reputation_score(
    worker: Worker,
    category: str | None = None,
    now: datetime | None = None,
) -> float:
    if category:
        return category_reputation(worker, category, now=now)
    return compute_reputation(worker, now=now).total


def preference_score(
    worker: Worker,
    task: Task,
    profile: WorkerPreferenceProfile | None = None,
) -> float:
    if profile is not None and profile.confidence >= 0.2:
        category_preference = profile.category_preferences.get(
            task.category, 0.5
        )
        low, high = profile.difficulty_preference
        midpoint = (low + high) / 2.0
        difficulty_fit = 1.0 - abs(task.difficulty - midpoint) / 4.0
        return _clamp(
            0.6 * category_preference + 0.4 * difficulty_fit
        )
    category_preference = worker.preferred_categories.get(task.category, 0.0)
    low, high = worker.preferred_difficulty
    midpoint = (low + high) / 2.0
    difficulty_fit = 1.0 - abs(task.difficulty - midpoint) / 4.0
    return _clamp(0.6 * category_preference + 0.4 * difficulty_fit)


def load_score(worker: Worker, task: Task) -> float:
    if worker.capacity_hours <= 0:
        return 0.0
    remaining = worker.capacity_hours - (
        worker.current_load_hours + task.estimated_hours
    )
    return _clamp(remaining / worker.capacity_hours)


def customer_preference_score(
    customer: Customer,
    worker: Worker,
    task: Task,
    reputation: float,
    expertise: float,
    profile: CustomerPreferenceProfile | None = None,
) -> float:
    if profile is not None and profile.confidence >= 0.2:
        weights = profile.attribute_weights
        speed = (
            worker.on_time / worker.completed if worker.completed > 0 else 0.5
        )
        values = {
            "reputation": reputation,
            "expertise": expertise,
            "speed": speed,
            "communication": 0.7,
            "price": 0.5,
        }
        total = sum(weights.values())
        if total > 0:
            return _clamp(
                sum(
                    weights.get(key, 0.0) * value
                    for key, value in values.items()
                )
                / total
            )
    load = load_score(worker, task)
    return _clamp(0.5 * reputation + 0.3 * expertise + 0.2 * load)


def candidate_features(
    worker: Worker,
    task: Task,
    customer: Customer,
    cf_score: float = 0.0,
    now: datetime | None = None,
    worker_profile: WorkerPreferenceProfile | None = None,
    customer_profile: CustomerPreferenceProfile | None = None,
) -> dict[str, float]:
    reputation = reputation_score(worker, task.category, now=now)
    expertise = expertise_score(worker, task)
    return {
        "reputation": reputation,
        "skill": skill_score(worker, task),
        "expertise": expertise,
        "collaborative": _clamp(cf_score),
        "preference": preference_score(worker, task, worker_profile),
        "load": load_score(worker, task),
        "customer_preference": customer_preference_score(
            customer,
            worker,
            task,
            reputation,
            expertise,
            customer_profile,
        ),
    }


def fuse_scores(features: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0, got {total_weight}")
    score = sum(features.get(key, 0.0) * weight for key, weight in weights.items())
    return _clamp(score)
