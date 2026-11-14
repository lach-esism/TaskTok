"""Pairwise choice learning and pair construction from events."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from sklearn.linear_model import LogisticRegression

from app.domain import RecommendationEvent
from app.learning.online import decay_weight
from app.learning.weights import project_weights

POSITIVE_ACTIONS = frozenset({"click", "apply", "accept"})
NEGATIVE_ACTIONS = frozenset({"reject", "ignore"})
WEIGHT_MIN = 0.1
WEIGHT_MAX = 10.0
SECONDS_PER_DAY = 86_400.0
DEFAULT_TAU_DAYS = 30.0


@dataclass(frozen=True)
class ChoicePair:
    """A preference observation: ``chosen`` should outrank ``rejected``."""

    chosen: dict[str, float]
    rejected: dict[str, float]
    weight: float = 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_utc(value: datetime) -> datetime:
    """Normalize naive datetimes to UTC for safe comparisons."""
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


class PairwiseChoiceLearner:
    """Learn the seven fusion weights from pairwise choices.

    The learner keeps the global feature keys and constrains every fitted or
    updated weight vector with :func:`project_weights`, so the AHP simplex
    constraints (sum to one, floors, reputation bounds) always hold.
    """

    def __init__(self, prior: dict[str, float], l2: float = 0.1) -> None:
        self.prior = {key: float(value) for key, value in prior.items()}
        self.keys = list(self.prior)
        self.l2 = max(float(l2), 0.0)
        self.weights = project_weights(self.prior)

    @property
    def _regularization(self) -> float:
        # ``C = 1 / l2``; guard against a division by zero when l2=0.
        return 1.0 / max(self.l2, 1e-12)

    def fit(self, pairs: list[ChoicePair]) -> dict[str, float]:
        """Fit weights from batch pairs and return a projected vector."""
        if not pairs:
            self.weights = project_weights(self.prior)
            return dict(self.prior)

        rows = [
            [
                float(pair.chosen.get(key, 0.0))
                - float(pair.rejected.get(key, 0.0))
                for key in self.keys
            ]
            for pair in pairs
        ]
        labels = [1] * len(rows)
        sample_weight = [
            _clamp(float(pair.weight), WEIGHT_MIN, WEIGHT_MAX)
            for pair in pairs
        ]

        # A logistic model needs two classes, while the pairwise objective
        # uses a constant label on the difference X = chosen - rejected.
        # One neutral row (zero features, label 0, negligible weight) only
        # adds a constant to the loss: its gradient is w * 0 == 0.
        rows.append([0.0] * len(self.keys))
        labels.append(0)
        sample_weight.append(1e-6)

        model = LogisticRegression(
            fit_intercept=False,
            C=self._regularization,
            max_iter=1000,
        )
        model.fit(rows, labels, sample_weight=sample_weight)
        coefficients = model.coef_[0]
        learned = {
            key: float(coefficients[index])
            for index, key in enumerate(self.keys)
        }
        self.weights = project_weights(learned)
        return dict(self.weights)

    def update_online(
        self,
        chosen: dict[str, float],
        rejected: dict[str, float],
        learning_rate: float = 0.05,
    ) -> dict[str, float]:
        """Apply one pairwise gradient step (the ``update_pair`` update)."""
        weights = dict(self.weights)
        differences = {
            key: float(chosen.get(key, 0.0))
            - float(rejected.get(key, 0.0))
            for key in self.keys
        }
        chosen_score = sum(
            weights[key] * float(chosen.get(key, 0.0))
            for key in self.keys
        )
        rejected_score = sum(
            weights[key] * float(rejected.get(key, 0.0))
            for key in self.keys
        )
        error = 1.0 - _sigmoid(chosen_score - rejected_score)
        norm = math.sqrt(
            sum(value * value for value in differences.values())
        )
        if norm <= 1e-12:
            return dict(self.weights)
        for key in self.keys:
            gradient = (
                error * differences[key] / norm
                - self.l2 * (weights[key] - self.prior.get(key, 0.0))
            )
            weights[key] += float(learning_rate) * gradient
        self.weights = project_weights(weights)
        return dict(self.weights)


def build_pairs(
    events: Iterable[RecommendationEvent],
    feature_lookup: Callable[[RecommendationEvent], dict[str, float]],
    time_decay_tau_days: float = DEFAULT_TAU_DAYS,
) -> list[ChoicePair]:
    """Build weighted preference pairs from per-request recommendation events.

    Positives are ``click``/``apply``/``accept`` events and negatives are
    ``reject``/``ignore`` events. Every positive-negative combination in the
    same request becomes a pair weighted by time decay and inverse propensity.
    """
    grouped: dict[str, list[RecommendationEvent]] = {}
    for event in events:
        grouped.setdefault(event.request_id, []).append(event)

    pairs: list[ChoicePair] = []
    for request_events in grouped.values():
        positives = [
            event
            for event in request_events
            if event.action in POSITIVE_ACTIONS
        ]
        negatives = [
            event
            for event in request_events
            if event.action in NEGATIVE_ACTIONS
        ]
        if not positives or not negatives:
            continue
        chosen_features = [
            (event, dict(feature_lookup(event))) for event in positives
        ]
        rejected_features = [
            (event, dict(feature_lookup(event))) for event in negatives
        ]
        for positive, chosen_vector in chosen_features:
            for negative, rejected_vector in rejected_features:
                delta_seconds = abs(
                    (
                        _as_utc(positive.created_at)
                        - _as_utc(negative.created_at)
                    ).total_seconds()
                )
                decay = decay_weight(
                    max(delta_seconds, 0.0) / SECONDS_PER_DAY,
                    time_decay_tau_days,
                )
                propensity = max(float(positive.propensity), 1e-12)
                inverse_propensity = _clamp(
                    1.0 / propensity, WEIGHT_MIN, WEIGHT_MAX
                )
                pairs.append(
                    ChoicePair(
                        chosen=dict(chosen_vector),
                        rejected=dict(rejected_vector),
                        weight=decay * inverse_propensity,
                    )
                )
    return pairs
