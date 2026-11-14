"""Platt calibration of the seven-dimension score into ``P(rating >= 4)``.

Calibration maps a raw recommender score to an interpretable probability.
It is reported alongside ranking metrics but never feeds back into ranking.

The logistic fit uses a bounded regularization strength (``C=5.0``).
Calibration estimated from around ten observations is uncertain, and an
unregularized fit at that sample size can invert or saturate the slope on
noisy data; the bounded choice keeps predictions interior to ``(0, 1)``.

The module only consumes caller-supplied ``(score, label)`` pairs; it never
reads ground-truth or label storage itself.
"""

from __future__ import annotations

import math

from sklearn.linear_model import LogisticRegression

#: Below this many observations the identity mapping is used.
MIN_SAMPLES = 10


def _sigmoid(value: float) -> float:
    """Numerically stable logistic function."""
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


class PlattCalibrator:
    """Fit ``P = sigmoid(a * score + b)`` on observed ratings.

    ``fit`` uses a bounded L2-regularized one-feature logistic regression
    (``C=5.0``). The bound is deliberate: at the 10-sample floor an
    unregularized maximum-likelihood fit can invert or saturate the slope
    on noisy data, so calibration at ``n ~ 10`` is inherently uncertain.
    With ``C=5.0`` predictions stay smooth and away from the exact 0/1
    extremes. Until enough heterogeneous observations are available, the
    calibrator keeps the identity mapping ``a=1, b=0``.
    """

    def __init__(self) -> None:
        self.a = 1.0
        self.b = 0.0

    def fit(
        self,
        scores: list[float],
        labels: list[int],
    ) -> "PlattCalibrator":
        """Fit the calibration curve and return ``self``.

        Falls back to the identity mapping when there are fewer than
        :data:`MIN_SAMPLES` observations or when only one label class is
        observed (in which case logistic regression has no finite
        maximum-likelihood slope). Raises ``ValueError`` for
        length-mismatched inputs.
        """
        rows = [float(score) for score in scores]
        targets = [int(label) for label in labels]
        if len(rows) != len(targets):
            raise ValueError("scores and labels must have equal length")
        if len(rows) < MIN_SAMPLES or len(set(targets)) < 2:
            self.a = 1.0
            self.b = 0.0
            return self
        model = LogisticRegression(
            fit_intercept=True,
            C=5.0,
            max_iter=1000,
        )
        model.fit([[score] for score in rows], targets)
        self.a = float(model.coef_[0][0])
        self.b = float(model.intercept_[0])
        return self

    def predict(self, score: float) -> float:
        """Return ``P(rating >= 4)`` for ``score``, clamped to ``[0, 1]``."""
        return _clamp(_sigmoid(self.a * float(score) + self.b))

    def brier(self, scores: list[float], labels: list[int]) -> float:
        """Return the mean squared error of the calibrated probabilities."""
        rows = [float(score) for score in scores]
        targets = [int(label) for label in labels]
        if len(rows) != len(targets):
            raise ValueError("scores and labels must have equal length")
        if not rows:
            return 0.0
        total = sum(
            (self.predict(score) - label) ** 2
            for score, label in zip(rows, targets)
        )
        return total / len(rows)
