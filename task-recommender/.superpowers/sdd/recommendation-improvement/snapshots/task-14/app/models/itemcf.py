"""Item-based collaborative filtering with cosine shrinkage."""

from __future__ import annotations

import math


class ItemCF:
    """ItemCF over (worker_id, task_id, weight) interactions."""

    def __init__(
        self,
        interactions: list[tuple[str, str, float]],
        shrinkage: float = 5.0,
    ) -> None:
        self.shrinkage = shrinkage
        self.user_items: dict[str, dict[str, float]] = {}
        self.item_users: dict[str, dict[str, float]] = {}
        for worker_id, task_id, weight in interactions:
            if weight <= 0:
                continue
            self.user_items.setdefault(worker_id, {})[task_id] = weight
            self.item_users.setdefault(task_id, {})[worker_id] = weight

    def _similarity(self, item_a: str, item_b: str) -> float:
        users_a = self.item_users.get(item_a, {})
        users_b = self.item_users.get(item_b, {})
        common = set(users_a) & set(users_b)
        if not common:
            return 0.0
        cooc = sum(users_a[user] * users_b[user] for user in common)
        norm_a = sum(users_a.values())
        norm_b = sum(users_b.values())
        if norm_a <= 0 or norm_b <= 0:
            return 0.0
        return cooc / (math.sqrt(norm_a * norm_b) + self.shrinkage)

    def score(self, worker_id: str, task_id: str) -> float:
        user_tasks = self.user_items.get(worker_id, {})
        if not user_tasks:
            return 0.0

        numerator = 0.0
        denominator = 0.0
        for other_task, weight in user_tasks.items():
            similarity = self._similarity(task_id, other_task)
            numerator += similarity * weight
            denominator += abs(similarity)
        return max(0.0, numerator / max(1.0, denominator))

    def normalize(
        self, raw: dict[tuple[str, str], float]
    ) -> dict[tuple[str, str], float]:
        if not raw:
            return {}
        maximum = max(raw.values())
        if maximum <= 0:
            return {key: 0.0 for key in raw}
        return {
            key: max(0.0, value) / maximum
            for key, value in raw.items()
        }
