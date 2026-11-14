import pytest
from app.learning.exploration import ExplorationPolicy, epsilon_greedy_propensities


def test_exact_epsilon_greedy_propensities():
    props = epsilon_greedy_propensities(["a", "b", "c", "d", "e"], k=3, epsilon=0.1)
    assert props["a"] == 1.0
    assert props["b"] == 1.0
    assert props["c"] == pytest.approx(0.9 + 0.1 / 3)
    assert props["d"] == pytest.approx(0.1 / 3)
    assert props["e"] == pytest.approx(0.1 / 3)
    assert sum(props.values()) == pytest.approx(3.0)


def test_k_ge_n_returns_ones():
    props = epsilon_greedy_propensities(["a", "b"], k=5, epsilon=0.1)
    assert props == {"a": 1.0, "b": 1.0}


def test_forced_exploration_replaces_last_and_uses_exact_propensity():
    from app.service import ScoredCandidate

    candidates = [
        ScoredCandidate(
            candidate_id=f"c{i}", score=1.0 - i * 0.01,
            breakdown={}, reasons=[], cold_start=False,
        )
        for i in range(10)
    ]
    policy = ExplorationPolicy(epsilon=1.0, seed=42)
    result = policy.rerank(candidates, k=3)
    assert len(result) == 3
    pool_ids = {candidate.candidate_id for candidate in candidates[2:]}
    assert result[-1].candidate_id in pool_ids
    for item in result:
        assert item.propensity == pytest.approx(policy.propensity_for(item.candidate_id))


def test_empirical_inclusion_matches_theoretical_propensity():
    from app.service import ScoredCandidate

    candidates = [
        ScoredCandidate(
            candidate_id=f"c{i}", score=1.0 - i * 0.01,
            breakdown={}, reasons=[], cold_start=False,
        )
        for i in range(5)
    ]
    theoretical = epsilon_greedy_propensities(
        [candidate.candidate_id for candidate in candidates], k=3, epsilon=0.1
    )
    policy = ExplorationPolicy(epsilon=0.1, seed=123)
    trials = 100_000
    counts = {candidate_id: 0 for candidate_id in theoretical}
    for _ in range(trials):
        for item in policy.rerank(candidates, k=3):
            counts[item.candidate_id] += 1
    for candidate_id, expected in theoretical.items():
        empirical = counts[candidate_id] / trials
        assert empirical == pytest.approx(expected, abs=0.01)
