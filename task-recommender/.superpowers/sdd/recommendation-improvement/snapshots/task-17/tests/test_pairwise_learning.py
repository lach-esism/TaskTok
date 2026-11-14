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


from app.learning.choice import ListwiseChoiceLearner


def test_listwise_learner_prefers_chosen_candidate():
    prior = dict(DEFAULT_WEIGHTS)
    learner = ListwiseChoiceLearner(prior, learning_rate=0.5)
    candidates = [
        _features(skill=1.0, reputation=1.0),
        _features(skill=0.1, reputation=0.1),
        _features(skill=0.2, reputation=0.2),
    ]
    weights = prior
    for _ in range(20):
        weights = learner.learn(candidates, chosen_index=0, sample_weight=1.0)
    score = lambda f: sum(weights[k] * f[k] for k in weights)
    assert score(candidates[0]) > score(candidates[1])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
