"""Exploration policy, propensity logging, and IPS/SNIPS estimators."""

from __future__ import annotations

import random
from dataclasses import replace


class ExplorationPolicy:
    def __init__(self, epsilon: float = 0.10, seed: int = 42) -> None:
        self.epsilon = max(0.0, min(1.0, epsilon))
        self.random = random.Random(seed)
        self._propensities: dict[str, float] = {}

    def rerank(self, candidates: list, k: int) -> list:
        k = min(max(0, k), len(candidates))
        if k == 0:
            return []
        result = list(candidates[:k])
        explored_id: str | None = None
        if (
            self.epsilon > 0
            and len(candidates) > k
            and self.random.random() < self.epsilon
        ):
            selected = {item.candidate_id for item in result}
            pool = [
                item
                for item in candidates
                if item.candidate_id not in selected
            ]
            if pool:
                explored = self.random.choice(pool)
                result[-1] = explored
                explored_id = explored.candidate_id

        uniform = 1.0 / len(candidates)
        exploited = max(1.0 - self.epsilon, 0.0)
        reranked = []
        self._propensities = {}
        for item in result:
            propensity = (
                uniform
                if item.candidate_id == explored_id
                else exploited
            )
            propensity = max(1e-6, min(1.0, propensity))
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
