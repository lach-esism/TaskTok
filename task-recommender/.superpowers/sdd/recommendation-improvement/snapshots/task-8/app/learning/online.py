"""Online constrained weight learning and batch refit."""

from __future__ import annotations

import math

from app.learning.weights import KEYS, project_weights


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def decay_weight(delta_days: float, tau_days: float = 30.0) -> float:
    return math.exp(-max(delta_days, 0.0) / max(tau_days, 1e-9))


def shrink_weights(
    learned: dict[str, float],
    prior: dict[str, float],
    sample_count: int,
    n0: int = 50,
) -> dict[str, float]:
    if sample_count <= 0:
        return dict(prior)
    ratio = sample_count / (sample_count + n0)
    blended = {
        key: ratio * learned.get(key, 0.0)
        + (1.0 - ratio) * prior.get(key, 0.0)
        for key in prior
    }
    return project_weights(blended)


class OnlineWeightLearner:
    def __init__(
        self,
        prior: dict[str, float],
        weights: dict[str, float] | None = None,
        l2_lambda: float = 0.1,
        learning_rate: float = 0.05,
    ) -> None:
        self.prior = dict(prior)
        self.weights = project_weights(weights or prior)
        self.l2_lambda = l2_lambda
        self.learning_rate = learning_rate
        self.bias = 0.0

    def _predict(self, features: dict[str, float]) -> float:
        score = (
            sum(
                self.weights[key] * features.get(key, 0.0)
                for key in KEYS
            )
            - self.bias
        )
        return _sigmoid(score)

    def update(
        self, features: dict[str, float], rating: int
    ) -> dict[str, float]:
        label = 1.0 if rating >= 4 else 0.0
        probability = self._predict(features)
        error = label - probability
        for key in KEYS:
            gradient = (
                error * features.get(key, 0.0)
                - self.l2_lambda
                * (self.weights[key] - self.prior.get(key, 0.0))
            )
            self.weights[key] += self.learning_rate * gradient
        self.bias += self.learning_rate * (probability - label)
        self.weights = project_weights(self.weights)
        return dict(self.weights)

    def update_pair(
        self,
        chosen: dict[str, float],
        rejected: dict[str, float],
    ) -> dict[str, float]:
        """Learn from a pairwise choice: chosen should outrank rejected."""
        chosen_score = sum(
            self.weights[key] * chosen.get(key, 0.0) for key in KEYS
        )
        rejected_score = sum(
            self.weights[key] * rejected.get(key, 0.0) for key in KEYS
        )
        probability = _sigmoid(chosen_score - rejected_score)
        error = 1.0 - probability
        differences = {
            key: chosen.get(key, 0.0) - rejected.get(key, 0.0)
            for key in KEYS
        }
        norm = math.sqrt(
            sum(value * value for value in differences.values())
        )
        if norm <= 1e-12:
            return dict(self.weights)
        for key in KEYS:
            gradient = (
                error * differences[key] / norm
                - self.l2_lambda
                * (self.weights[key] - self.prior.get(key, 0.0))
            )
            self.weights[key] += self.learning_rate * gradient
        self.weights = project_weights(self.weights)
        return dict(self.weights)

    def batch_fit(
        self,
        records: list[tuple[dict[str, float], int]],
        epochs: int = 1,
    ) -> dict[str, float]:
        for _ in range(max(1, epochs)):
            gradients = {key: 0.0 for key in KEYS}
            bias_gradient = 0.0
            for features, rating in records:
                label = 1.0 if rating >= 4 else 0.0
                probability = self._predict(features)
                error = label - probability
                for key in KEYS:
                    gradients[key] += (
                        error * features.get(key, 0.0)
                        - self.l2_lambda
                        * (self.weights[key] - self.prior.get(key, 0.0))
                    )
                bias_gradient += probability - label
            count = max(1, len(records))
            for key in KEYS:
                self.weights[key] += (
                    self.learning_rate * gradients[key] / count
                )
            self.bias += self.learning_rate * bias_gradient / count
            self.weights = project_weights(self.weights)
        return dict(self.weights)
