"""Exploration policy, propensity logging, and IPS/SNIPS estimators."""

from __future__ import annotations

import random
from dataclasses import replace


MIN_PROPENSITY = 1e-6
MAX_PROPENSITY = 1.0


def _clamp_propensity(probability: float) -> float:
    return max(MIN_PROPENSITY, min(MAX_PROPENSITY, probability))


def epsilon_greedy_propensities(
    candidate_ids: list[str], k: int, epsilon: float
) -> dict[str, float]:
    """Exact inclusion probability of each ranked candidate under ε-greedy.

    With ``K = min(k, N)`` candidates returned:

    * ranks in the top ``K - 1`` are always included (``p = 1``);
    * rank ``K`` is included by exploitation or by exploration
      (``p = (1 - ε) + ε / (N - K + 1)``);
    * ranks below ``K`` are included only by exploration
      (``p = ε / (N - K + 1)``).

    When ``N <= K`` every candidate is returned, so ``p = 1`` for all.
    """
    n = len(candidate_ids)
    if n == 0:
        return {}
    k = min(k, n)
    if n <= k:
        return {candidate_id: 1.0 for candidate_id in candidate_ids}

    epsilon = max(0.0, min(1.0, epsilon))
    exploration_pool_size = n - k + 1
    propensities: dict[str, float] = {}
    for index, candidate_id in enumerate(candidate_ids):
        if index < k - 1:
            probability = 1.0
        elif index == k - 1:
            probability = (1.0 - epsilon) + epsilon / exploration_pool_size
        else:
            probability = epsilon / exploration_pool_size
        propensities[candidate_id] = _clamp_propensity(probability)
    return propensities


class ExplorationPolicy:
    def __init__(self, epsilon: float = 0.10, seed: int | None = None) -> None:
        self.epsilon = max(0.0, min(1.0, epsilon))
        self.random = random.Random(seed)
        self._propensities: dict[str, float] = {}

    def rerank(self, candidates: list, k: int) -> list:
        k = min(max(0, k), len(candidates))
        self._propensities = {}
        if k == 0:
            return []

        candidate_ids = [item.candidate_id for item in candidates]
        propensities = epsilon_greedy_propensities(
            candidate_ids, k=k, epsilon=self.epsilon
        )
        result = list(candidates[:k])
        if (
            self.epsilon > 0
            and len(candidates) > k
            and self.random.random() < self.epsilon
        ):
            # Sample uniformly from the K-th candidate plus the tail
            # (N - K + 1 options). Sampling the K-th leaves the top-K
            # unchanged; sampling a tail candidate replaces the last slot.
            pool = list(candidates[k - 1:])
            sampled = self.random.choice(pool)
            if sampled is not candidates[k - 1]:
                result[-1] = sampled

        reranked = []
        for item in result:
            propensity = propensities.get(item.candidate_id, 1.0)
            self._propensities[item.candidate_id] = propensity
            reranked.append(replace(item, propensity=propensity))
        return reranked

    def propensity_for(self, candidate_id: str) -> float:
        return self._propensities.get(candidate_id, 0.0)


def ips_score(
    rewards: list[float],
    propensities: list[float],
    policy_probs: list[float],
) -> float:
    if not rewards:
        return 0.0
    return sum(
        reward * policy_prob / max(1e-6, min(1.0, propensity))
        for reward, propensity, policy_prob in zip(
            rewards, propensities, policy_probs
        )
    ) / len(rewards)


def snips_score(
    rewards: list[float],
    propensities: list[float],
    policy_probs: list[float],
) -> float:
    if not rewards:
        return 0.0
    numerator = sum(
        reward * policy_prob / max(1e-6, min(1.0, propensity))
        for reward, propensity, policy_prob in zip(
            rewards, propensities, policy_probs
        )
    )
    denominator = sum(
        policy_prob / max(1e-6, min(1.0, propensity))
        for propensity, policy_prob in zip(propensities, policy_probs)
    )
    return numerator / denominator if denominator > 0 else 0.0
