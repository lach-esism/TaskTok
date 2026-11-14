import math

import pytest
from app.learning.calibration import PlattCalibrator


def test_calibration_is_monotonic_and_bounded():
    scores = [0.1, 0.2, 0.8, 0.9] * 10
    labels = [0, 0, 1, 1] * 10
    calibrator = PlattCalibrator().fit(scores, labels)
    assert 0.0 <= calibrator.predict(0.1) <= 1.0
    assert calibrator.predict(0.9) > calibrator.predict(0.1)


def test_brier_is_lower_than_raw():
    scores = [0.4, 0.6] * 20
    labels = [0, 1] * 20
    calibrator = PlattCalibrator().fit(scores, labels)
    raw = sum((s - y) ** 2 for s, y in zip(scores, labels)) / len(scores)
    assert calibrator.brier(scores, labels) <= raw + 1e-9


def _noisy_scores_and_labels():
    """Deterministic noisy data: each score carries both label classes."""
    scores = []
    labels = []
    for index in range(50):
        scores.append(0.35)
        labels.append(1 if index % 10 == 0 else 0)
        scores.append(0.65)
        labels.append(0 if index % 10 == 0 else 1)
    return scores, labels


def test_held_out_brier_beats_raw_without_saturation():
    scores, labels = _noisy_scores_and_labels()
    split = int(len(scores) * 0.8)
    calibrator = PlattCalibrator().fit(scores[:split], labels[:split])
    held_scores = scores[split:]
    held_labels = labels[split:]
    raw = sum(
        (s - y) ** 2 for s, y in zip(held_scores, held_labels)
    ) / len(held_scores)
    assert calibrator.brier(held_scores, held_labels) <= raw
    predictions = [calibrator.predict(s) for s in held_scores]
    assert all(0.0 < p < 1.0 for p in predictions)


def test_identity_fallback_below_ten_samples():
    scores = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.95]
    labels = [0, 0, 0, 0, 1, 1, 1, 1, 1]
    calibrator = PlattCalibrator().fit(scores, labels)
    assert calibrator.a == pytest.approx(1.0)
    assert calibrator.b == pytest.approx(0.0)
    for score in scores:
        expected = 1.0 / (1.0 + math.exp(-score))
        assert calibrator.predict(score) == pytest.approx(expected)
        assert 0.0 <= calibrator.predict(score) <= 1.0
