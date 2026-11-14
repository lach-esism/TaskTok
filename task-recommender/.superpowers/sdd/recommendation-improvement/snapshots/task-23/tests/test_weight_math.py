import pytest

from app.learning.weights import (
    AHP_PRIOR,
    combine_weights,
    entropy_weights,
    project_weights,
)


def test_entropy_and_combine_sum_to_one():
    rows = [
        {
            "reputation": 0.9,
            "skill": 0.4,
            "expertise": 0.2,
            "collaborative": 0.1,
            "preference": 0.5,
            "load": 0.8,
            "customer_preference": 0.6,
        },
        {
            "reputation": 0.3,
            "skill": 0.8,
            "expertise": 0.7,
            "collaborative": 0.4,
            "preference": 0.2,
            "load": 0.5,
            "customer_preference": 0.3,
        },
    ]
    entropy = entropy_weights(rows)
    combined = combine_weights(AHP_PRIOR, entropy)
    assert set(combined) == set(AHP_PRIOR)
    assert sum(combined.values()) == pytest.approx(1.0)


def test_projection_preserves_floors():
    projected = project_weights(
        {
            "reputation": 0.01,
            "skill": 0.40,
            "expertise": 0.10,
            "collaborative": 0.20,
            "preference": 0.10,
            "load": 0.10,
            "customer_preference": 0.09,
        }
    )
    assert 0.25 <= projected["reputation"] <= 0.40
    assert projected["skill"] + projected["expertise"] >= 0.25 - 1e-9
    assert min(projected.values()) >= 0.02 - 1e-9
    assert sum(projected.values()) == pytest.approx(1.0)


def test_projection_handles_all_zero_input():
    projected = project_weights({key: 0.0 for key in AHP_PRIOR})
    assert sum(projected.values()) == pytest.approx(1.0)
    assert 0.25 <= projected["reputation"] <= 0.40
    assert min(projected.values()) >= 0.02 - 1e-9


def test_projection_is_idempotent():
    once = project_weights(
        {
            "reputation": 0.01,
            "skill": 0.80,
            "expertise": 0.01,
            "collaborative": 0.10,
            "preference": 0.03,
            "load": 0.03,
            "customer_preference": 0.02,
        }
    )
    twice = project_weights(once)
    assert twice == pytest.approx(once, abs=1e-9)


def test_projection_keeps_reputation_largest():
    projected = project_weights(
        {
            "reputation": 0.01,
            "skill": 0.60,
            "expertise": 0.20,
            "collaborative": 0.10,
            "preference": 0.05,
            "load": 0.02,
            "customer_preference": 0.02,
        }
    )
    assert projected["reputation"] >= max(
        value
        for key, value in projected.items()
        if key != "reputation"
    ) - 1e-9


def test_projection_reviewer_repro_is_stable():
    raw = {
        "reputation": 0.25,
        "skill": 0.15,
        "expertise": 0.15,
        "collaborative": 0.05,
        "preference": 0.34,
        "load": 0.04,
        "customer_preference": 0.02,
    }
    once = project_weights(raw)
    twice = project_weights(once)
    assert once["preference"] <= once["reputation"] + 1e-9
    assert twice == pytest.approx(once, abs=1e-9)


def test_projection_fuzz_invariants():
    import random

    rng = random.Random(123)
    for index in range(100):
        raw = {key: rng.random() for key in AHP_PRIOR}
        if index % 2 == 0:
            total = sum(raw.values())
            raw = {key: value / total for key, value in raw.items()}
        projected = project_weights(raw)
        assert sum(projected.values()) == pytest.approx(1.0, abs=1e-9)
        assert 0.25 - 1e-9 <= projected["reputation"] <= 0.40 + 1e-9
        assert (
            projected["skill"] + projected["expertise"]
            >= 0.25 - 1e-9
        )
        assert min(projected.values()) >= 0.02 - 1e-9
        assert projected["reputation"] >= max(
            value
            for key, value in projected.items()
            if key != "reputation"
        ) - 1e-9
        assert project_weights(projected) == pytest.approx(
            projected, abs=1e-9
        )
