import pytest
from app.config import DEFAULT_WEIGHTS
from app.learning.choice import ChoicePair, PairwiseChoiceLearner, build_pairs


def _features(**overrides):
    base = {key: 0.5 for key in DEFAULT_WEIGHTS}
    base.update(overrides)
    return base


def test_pairwise_learner_increases_chosen_dimension():
    prior = dict(DEFAULT_WEIGHTS)
    pairs = [
        ChoicePair(chosen=_features(skill=1.0), rejected=_features(skill=0.0), weight=1.0)
        for _ in range(50)
    ]
    weights = PairwiseChoiceLearner(prior).fit(pairs)
    assert weights["skill"] >= prior["skill"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_propensity_clipping():
    learner = PairwiseChoiceLearner(dict(DEFAULT_WEIGHTS))
    pair = ChoicePair(chosen=_features(skill=1.0), rejected=_features(skill=0.0), weight=20.0)
    weights = learner.fit([pair])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
