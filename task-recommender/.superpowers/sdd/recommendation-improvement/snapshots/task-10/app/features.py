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


#: Shrinkage strength pulling a worker's category history toward the global
#: Bayesian rating. Matches the ``m`` used by ``category_reputation``.
CATEGORY_HISTORY_PRIOR = 10


def category_history_score(
    worker: Worker, category: str | None = None
) -> float:
    """Bayesian-shrunk category rating on a ``[0, 1]`` scale.

    ``worker.category_ratings`` values are on a 1-5 scale. With no history for
    ``category`` the global Bayesian rating is used. ``category=None`` means
    "no category history", i.e. the global rating.

    ``compute_reputation(...).rating`` is already normalized to ``[0, 1]`` in
    this codebase (the spec's 0-5 global rating is the same value expressed on
    a 5-point scale), so it is used directly as the weighted prior:
    ``(n * mean/5 + m * global_rating) / (n + m)`` with ``m = 10``.
    """
    global_rating = compute_reputation(worker).rating
    category_values = worker.category_ratings.get(category, []) if category else []
    n = len(category_values)
    if n == 0:
        return _clamp(global_rating)
    mean = sum(category_values) / n
    return _clamp(
        (
            n * mean / 5.0
            + CATEGORY_HISTORY_PRIOR * global_rating
        )
        / (n + CATEGORY_HISTORY_PRIOR)
    )


def skill_score(worker: Worker, task: Task) -> float:
    if not task.required_skills:
        return _clamp(
            0.5 * expertise_score(worker, task)
            + 0.5 * category_history_score(worker, task.category)
        )
    weighted_total = 0.0
    total_weight = 0.0
    for skill, minimum in task.required_skills.items():
        weight = task.required_skill_weights.get(skill, 1.0)
        match = min(worker.skills.get(skill, 0) / max(minimum, 1), 1.0)
        weighted_total += weight * match
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return _clamp(weighted_total / total_weight)


def expertise_score(
    worker: Worker,
    task: Task,
    semantic_similarity: float | None = None,
) -> float:
    specialty = worker.specialties.get(task.category, 0) / 5.0
    certification = _clamp(worker.certifications.get(task.category, 0.0))
    category_history = category_history_score(worker, task.category)
    if semantic_similarity is None:
        semantic = 0.5
    else:
        semantic = float(semantic_similarity)
        semantic = 0.5 if semantic != semantic else _clamp(semantic)
    return _clamp(
        0.35 * specialty
        + 0.15 * certification
        + 0.25 * category_history
        + 0.25 * semantic
    )


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
    semantic_similarity: float = 0.5,
) -> dict[str, float]:
    reputation = reputation_score(worker, task.category, now=now)
    expertise = expertise_score(worker, task, semantic_similarity)
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
