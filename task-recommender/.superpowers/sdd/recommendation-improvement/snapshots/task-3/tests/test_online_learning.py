import pytest

from app.learning.online import OnlineWeightLearner, shrink_weights


def test_learning_increases_reputation_weight_when_it_predicts_high_ratings():
    prior = {
        "reputation": 0.25,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.13,
        "preference": 0.10,
        "load": 0.06,
        "customer_preference": 0.11,
    }
    learner = OnlineWeightLearner(prior, learning_rate=0.05)
    before = learner.weights["reputation"]
    for _ in range(200):
        learner.update(
            {
                "reputation": 1.0,
                "skill": 0.0,
                "expertise": 0.0,
                "collaborative": 0.0,
                "preference": 0.0,
                "load": 0.0,
                "customer_preference": 0.0,
            },
            5,
        )
    assert learner.weights["reputation"] > before
    assert sum(learner.weights.values()) == pytest.approx(1.0)


def test_shrinkage_returns_prior_for_zero_samples():
    prior = {
        "reputation": 0.32,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.13,
        "preference": 0.10,
        "load": 0.06,
        "customer_preference": 0.04,
    }
    learned = {
        "reputation": 0.40,
        "skill": 0.15,
        "expertise": 0.15,
        "collaborative": 0.10,
        "preference": 0.10,
        "load": 0.05,
        "customer_preference": 0.05,
    }
    shrunk = shrink_weights(learned, prior, 0)
    assert shrunk == pytest.approx(prior)


def test_repeated_online_updates_preserve_all_weight_floors():
    prior = {
        "reputation": 0.32,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.13,
        "preference": 0.10,
        "load": 0.06,
        "customer_preference": 0.04,
    }
    learner = OnlineWeightLearner(prior)
    for index in range(100):
        learner.update(
            {
                "reputation": 0.9,
                "skill": 0.8,
                "expertise": 0.7,
                "collaborative": 0.4,
                "preference": 0.6,
                "load": 0.3,
                "customer_preference": 0.5,
            },
            5 if index % 2 == 0 else 1,
        )
    weights = learner.weights
    assert 0.25 <= weights["reputation"] <= 0.40
    assert weights["skill"] + weights["expertise"] >= 0.25 - 1e-9
    assert min(weights.values()) >= 0.02 - 1e-9
    assert sum(weights.values()) == pytest.approx(1.0)


def test_batch_fit_keeps_simplex():
    prior = {
        "reputation": 0.32,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.13,
        "preference": 0.10,
        "load": 0.06,
        "customer_preference": 0.04,
    }
    learner = OnlineWeightLearner(prior)
    records = [
        (
            {
                "reputation": 1.0,
                "skill": 0.0,
                "expertise": 0.0,
                "collaborative": 0.0,
                "preference": 0.0,
                "load": 0.0,
                "customer_preference": 0.0,
            },
            5,
        ),
        (
            {
                "reputation": 0.0,
                "skill": 1.0,
                "expertise": 0.0,
                "collaborative": 0.0,
                "preference": 0.0,
                "load": 0.0,
                "customer_preference": 0.0,
            },
            1,
        ),
    ]
    learner.batch_fit(records, epochs=2)
    assert sum(learner.weights.values()) == pytest.approx(1.0)
    assert 0.25 <= learner.weights["reputation"] <= 0.40
