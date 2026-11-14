import pytest

from app.learning.exploration import ExplorationPolicy, ips_score, snips_score


def test_ips_perfect_policy_matches_mean_reward():
    assert ips_score([1.0, 0.0], [1.0, 1.0], [1.0, 1.0]) == pytest.approx(
        0.5
    )


def test_snips_perfect_policy_matches_mean_reward():
    assert snips_score([1.0, 0.0], [1.0, 1.0], [1.0, 1.0]) == pytest.approx(
        0.5
    )


def test_exploration_is_deterministic_with_seed(small_store):
    from app.service import RecommendationService

    candidates = RecommendationService(small_store).recommend_workers(
        "t1", top_n=5
    )
    first = ExplorationPolicy(seed=42).rerank(candidates, k=5)
    second = ExplorationPolicy(seed=42).rerank(candidates, k=5)
    assert [item.candidate_id for item in first] == [
        item.candidate_id for item in second
    ]


def test_explored_candidate_gets_uniform_propensity(small_store):
    from app.service import RecommendationService

    candidates = RecommendationService(small_store).recommend_workers(
        "t1", top_n=3
    )
    policy = ExplorationPolicy(epsilon=1.0, seed=7)
    reranked = policy.rerank(candidates, k=min(3, len(candidates)))
    assert reranked
    assert policy.propensity_for(reranked[-1].candidate_id) > 0.0
