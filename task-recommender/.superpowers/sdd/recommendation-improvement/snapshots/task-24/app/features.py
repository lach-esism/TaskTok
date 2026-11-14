"""Phase 1 feature scoring for the seven-dimension fusion model."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.domain import Customer, Task, Worker
from app.preference.customer import (
    DEFAULT_ATTRIBUTE_WEIGHTS,
    CustomerPreferenceProfile,
)
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


def _as_aware(value: datetime) -> datetime:
    """Attach UTC to naive datetimes so deadline math never raises."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def pay_fit_score(worker: Worker, task: Task) -> float:
    """How closely a task's budget matches the worker's expected pay."""
    expected_pay = worker.expected_pay
    if expected_pay == 0:
        return 0.5
    budget = task.budget
    denominator = max(budget, expected_pay, 1.0)
    return _clamp(1.0 - abs(budget - expected_pay) / denominator)


def time_fit_score(
    worker: Worker,
    task: Task,
    now: datetime | None = None,
) -> float:
    """Whether the worker's remaining time before the deadline fits the task.

    Naive datetimes are treated as UTC. Callers that need reproducible scores
    should pass an explicit ``now`` (``candidate_features`` forwards its own).
    """
    current = _as_aware(now) if now is not None else datetime.now(timezone.utc)
    deadline = _as_aware(task.deadline)
    hours_until = max(
        0.0, (deadline - current).total_seconds() / 3600.0
    )
    available = max(0.0, hours_until - worker.current_load_hours)
    utilization = _clamp(task.estimated_hours / max(available, 1.0))
    return _clamp(1.0 - utilization)


def preference_score(
    worker: Worker,
    task: Task,
    profile: WorkerPreferenceProfile | None = None,
    p_accept: float | None = None,
    now: datetime | None = None,
) -> float:
    if profile is not None and profile.confidence >= 0.2:
        category_preference = profile.category_preferences.get(
            task.category, 0.5
        )
        low, high = profile.difficulty_preference
        midpoint = (low + high) / 2.0
        difficulty_fit = 1.0 - abs(task.difficulty - midpoint) / 4.0
        declared = _clamp(
            0.6 * category_preference + 0.4 * difficulty_fit
        )
    else:
        category_preference = worker.preferred_categories.get(
            task.category, 0.0
        )
        low, high = worker.preferred_difficulty
        midpoint = (low + high) / 2.0
        difficulty_fit = 1.0 - abs(task.difficulty - midpoint) / 4.0
        declared = _clamp(0.6 * category_preference + 0.4 * difficulty_fit)
    acceptance = declared if p_accept is None else float(p_accept)
    return _clamp(
        0.4 * acceptance
        + 0.3 * declared
        + 0.15 * pay_fit_score(worker, task)
        + 0.15 * time_fit_score(worker, task, now=now)
    )


def load_score(
    worker: Worker,
    task: Task,
    now: datetime | None = None,
    recent_impressions: int = 0,
) -> float:
    """Blend capacity, deadline feasibility, and exposure fairness.

    ``exposure_fairness = exp(-recent_impressions / 20)`` counteracts the
    rich-get-richer feedback loop by down-weighting workers who already
    received many recent impressions. With no impressions it is ``1.0``.
    """
    if worker.capacity_hours <= 0:
        capacity_score = 0.0
    else:
        remaining = worker.capacity_hours - (
            worker.current_load_hours + task.estimated_hours
        )
        capacity_score = _clamp(remaining / worker.capacity_hours)
    deadline_feasibility = time_fit_score(worker, task, now=now)
    exposure_fairness = math.exp(
        -max(0, recent_impressions) / 20.0
    )
    return _clamp(
        0.6 * capacity_score
        + 0.25 * deadline_feasibility
        + 0.15 * exposure_fairness
    )


def customer_preference_score(
    customer: Customer,
    worker: Worker,
    task: Task,
    reputation: float,
    expertise: float,
    profile: CustomerPreferenceProfile | None = None,
    *,
    pay_fit: float = 0.5,
    deadline_feasibility: float = 0.5,
    collaboration: float = 0.0,
    communication: float = 0.5,
    now: datetime | None = None,
) -> float:
    """Weighted customer satisfaction estimate on a ``[0, 1]`` scale.

    A confident profile (``confidence >= 0.2``) contributes its attribute
    weights on top of :data:`DEFAULT_ATTRIBUTE_WEIGHTS`; the merged weights
    are normalized by their own sum. Without a confident profile the score
    falls back to the legacy reputation/expertise/load/pay blend.
    """
    if profile is not None and profile.confidence >= 0.2:
        weights = dict(DEFAULT_ATTRIBUTE_WEIGHTS)
        for key, value in profile.attribute_weights.items():
            if key in weights:
                weights[key] = value
        speed = (
            worker.on_time / worker.completed if worker.completed > 0 else 0.5
        )
        values = {
            "reputation": _clamp(reputation),
            "expertise": _clamp(expertise),
            "speed": _clamp(speed),
            "communication": _clamp(communication),
            "price": _clamp(pay_fit),
            "collaboration": _clamp(min(1.0, collaboration / 3.0)),
            "deadline_fit": _clamp(deadline_feasibility),
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
    load = load_score(worker, task, now=now)
    return _clamp(
        0.4 * reputation
        + 0.3 * expertise
        + 0.15 * load
        + 0.15 * pay_fit
    )


def _communication_score(worker: Worker) -> float:
    ratings = worker.communication_ratings
    if not ratings:
        return 0.5
    return _clamp((sum(ratings) / len(ratings)) / 5.0)


def candidate_features(
    worker: Worker,
    task: Task,
    customer: Customer,
    cf_score: float = 0.0,
    now: datetime | None = None,
    worker_profile: WorkerPreferenceProfile | None = None,
    customer_profile: CustomerPreferenceProfile | None = None,
    semantic_similarity: float = 0.5,
    p_accept: float | None = None,
    recent_impressions: int = 0,
    *,
    pay_fit: float | None = None,
    communication: float | None = None,
    collaboration: float = 0.0,
) -> dict[str, float]:
    """Build the seven fusion features, all bounded to ``[0, 1]``.

    ``p_accept`` and ``recent_impressions`` are supplied by the service when
    an acceptance model and impression log are available. ``pay_fit``,
    ``communication``, and ``collaboration`` may also be supplied to avoid
    recomputing store-derived context; omitted values fall back to sensible
    defaults.
    """
    reputation = reputation_score(worker, task.category, now=now)
    expertise = expertise_score(worker, task, semantic_similarity)
    if pay_fit is None:
        pay_fit = pay_fit_score(worker, task)
    if communication is None:
        communication = _communication_score(worker)
    deadline_feasibility = time_fit_score(worker, task, now=now)
    return {
        "reputation": reputation,
        "skill": skill_score(worker, task),
        "expertise": expertise,
        "collaborative": _clamp(cf_score),
        "preference": preference_score(
            worker, task, worker_profile, p_accept=p_accept, now=now
        ),
        "load": load_score(
            worker,
            task,
            now=now,
            recent_impressions=recent_impressions,
        ),
        "customer_preference": customer_preference_score(
            customer,
            worker,
            task,
            reputation,
            expertise,
            customer_profile,
            pay_fit=pay_fit,
            deadline_feasibility=deadline_feasibility,
            collaboration=collaboration,
            communication=communication,
            now=now,
        ),
    }


def fuse_scores(features: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        raise ValueError(f"weights must sum to 1.0, got {total_weight}")
    score = sum(features.get(key, 0.0) * weight for key, weight in weights.items())
    return _clamp(score)
