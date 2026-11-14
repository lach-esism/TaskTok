"""AHP prior, entropy weights, and constrained projection."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.config import DEFAULT_WEIGHTS

AHP_PRIOR: dict[str, float] = dict(DEFAULT_WEIGHTS)
KEYS: list[str] = list(AHP_PRIOR)
MIN_WEIGHT = 0.02
REPUTATION_MIN = 0.25
REPUTATION_MAX = 0.40
SKILL_EXPERTISE_MIN = 0.25


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    values = {key: max(float(value), 0.0) for key, value in weights.items()}
    total = sum(values.values())
    if total <= 0:
        return {key: 1.0 / len(values) for key in values}
    return {key: value / total for key, value in values.items()}


def entropy_weights(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {key: 1.0 / len(KEYS) for key in KEYS}
    n = len(rows)
    deltas: dict[str, float | None] = {}
    for key in KEYS:
        values = [max(float(row.get(key, 0.0)), 0.0) for row in rows]
        total = sum(values)
        if total <= 0:
            deltas[key] = None
            continue
        if n == 1:
            deltas[key] = 1.0
            continue
        probabilities = [value / total for value in values]
        entropy = -sum(
            probability * math.log(probability)
            for probability in probabilities
            if probability > 0
        ) / math.log(n)
        deltas[key] = 1.0 - entropy

    known = [value for value in deltas.values() if value is not None]
    fallback = sum(known) / len(known) if known else 1.0 / len(KEYS)
    resolved = {
        key: (fallback if value is None else value)
        for key, value in deltas.items()
    }
    total = sum(resolved.values())
    if total <= 0:
        return {key: 1.0 / len(KEYS) for key in KEYS}
    return {key: resolved[key] / total for key in KEYS}


def combine_weights(
    prior: dict[str, float], entropy: dict[str, float]
) -> dict[str, float]:
    keys = list(prior)
    raw = {
        key: max(float(prior.get(key, 0.0)), 0.0)
        * max(float(entropy.get(key, 1.0)), 0.0)
        for key in keys
    }
    return _normalize(raw)


def _allocate_capped(
    mass: float,
    raws: dict[str, float],
    minimum: float = MIN_WEIGHT,
    cap: float | None = None,
) -> dict[str, float]:
    keys = list(raws)
    values = {key: max(float(raws[key]), 0.0) for key in keys}
    if cap is not None:
        mass = min(mass, len(keys) * cap)
    mass = max(mass, len(keys) * minimum)
    if (
        abs(sum(values.values()) - mass) <= 1e-9
        and all(value >= minimum - 1e-9 for value in values.values())
        and (
            cap is None
            or all(value <= cap + 1e-9 for value in values.values())
        )
    ):
        return dict(values)

    allocation = {key: minimum for key in keys}
    remaining = mass - len(keys) * minimum
    if remaining <= 0:
        return allocation

    active = list(keys)
    while remaining > 1e-12 and active:
        total = sum(values[key] for key in active)
        if total <= 0:
            share = remaining / len(active)
            for key in active:
                allocation[key] += share
            break
        shares = {
            key: remaining * values[key] / total for key in active
        }
        capped: list[str] = []
        overflow = 0.0
        for key in active:
            room = (
                cap - allocation[key]
                if cap is not None
                else shares[key]
            )
            if shares[key] > room + 1e-12:
                capped.append(key)
                overflow += shares[key] - room
        if not capped:
            for key in active:
                allocation[key] += shares[key]
            break
        for key in active:
            if key in capped:
                allocation[key] += (
                    cap - allocation[key]
                    if cap is not None
                    else shares[key]
                )
            else:
                allocation[key] += shares[key]
        remaining = overflow
        active = [key for key in active if key not in capped]
    return allocation


def validate_weights(weights: dict[str, float]) -> None:
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError("weights must sum to 1.0")
    if any(value < MIN_WEIGHT - 1e-9 for value in weights.values()):
        raise ValueError(f"each weight must be >= {MIN_WEIGHT}")
    if "reputation" in weights and not (
        REPUTATION_MIN - 1e-9
        <= weights["reputation"]
        <= REPUTATION_MAX + 1e-9
    ):
        raise ValueError("reputation weight outside [0.25, 0.40]")
    if (
        "skill" in weights
        and "expertise" in weights
        and weights["skill"] + weights["expertise"]
        < SKILL_EXPERTISE_MIN - 1e-9
    ):
        raise ValueError("skill + expertise must be >= 0.25")
    if len(weights) >= 7 and "reputation" in weights:
        others = [
            value for key, value in weights.items() if key != "reputation"
        ]
        if others and weights["reputation"] < max(others) - 1e-9:
            raise ValueError("reputation must be the largest weight")


@dataclass(frozen=True)
class WeightBindingReport:
    """Counts of constraint bindings observed during projection."""

    reputation_hit_low: int = 0
    reputation_hit_high: int = 0
    min_hits: dict[str, int] = field(default_factory=dict)
    iterations: int = 1


def project_weights_with_report(
    weights: dict[str, float],
) -> tuple[dict[str, float], WeightBindingReport]:
    raw = {key: max(float(weights.get(key, 0.0)), 0.0) for key in KEYS}
    reputation_hit_low = 1 if raw["reputation"] < REPUTATION_MIN else 0
    reputation_hit_high = 1 if raw["reputation"] > REPUTATION_MAX else 0
    reputation = min(
        REPUTATION_MAX, max(REPUTATION_MIN, raw["reputation"])
    )

    skill_expertise_raw = {
        "skill": raw["skill"],
        "expertise": raw["expertise"],
    }
    skill_expertise_mass = max(
        SKILL_EXPERTISE_MIN, sum(skill_expertise_raw.values())
    )
    skill_expertise_mass = min(
        skill_expertise_mass,
        1.0 - reputation - 4 * MIN_WEIGHT,
        2.0 * reputation,
    )
    skill_expertise_mass = max(
        SKILL_EXPERTISE_MIN, skill_expertise_mass
    )
    skill_expertise = _allocate_capped(
        skill_expertise_mass,
        skill_expertise_raw,
        cap=reputation,
    )

    remaining = 1.0 - reputation - sum(skill_expertise.values())
    others = _allocate_capped(
        remaining,
        {
            key: raw[key]
            for key in (
                "collaborative",
                "preference",
                "load",
                "customer_preference",
            )
        },
        cap=reputation,
    )

    result = {
        "reputation": reputation,
        "skill": skill_expertise["skill"],
        "expertise": skill_expertise["expertise"],
        "collaborative": others["collaborative"],
        "preference": others["preference"],
        "load": others["load"],
        "customer_preference": others["customer_preference"],
    }
    total = sum(result.values())
    if abs(total - 1.0) > 1e-12:
        difference = 1.0 - total
        candidates = sorted(
            (key for key in result if key != "reputation"),
            key=lambda key: result[key],
        )
        for key in candidates:
            if abs(difference) <= 1e-12:
                break
            if difference > 0:
                room = reputation - result[key]
                addition = min(difference, max(0.0, room))
            else:
                addition = max(difference, MIN_WEIGHT - result[key])
            result[key] += addition
            difference -= addition
        if abs(difference) > 1e-12:
            room = REPUTATION_MAX - result["reputation"]
            result["reputation"] += max(-room, min(room, difference))

    projected = {key: round(result[key], 12) for key in KEYS}
    min_hits = {
        key: 1 if value <= MIN_WEIGHT + 1e-9 else 0
        for key, value in projected.items()
    }
    report = WeightBindingReport(
        reputation_hit_low=reputation_hit_low,
        reputation_hit_high=reputation_hit_high,
        min_hits=min_hits,
        iterations=1,
    )
    return projected, report


def project_weights(weights: dict[str, float]) -> dict[str, float]:
    return project_weights_with_report(weights)[0]
