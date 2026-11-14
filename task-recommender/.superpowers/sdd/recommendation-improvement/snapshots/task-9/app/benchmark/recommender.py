"""A label-free recommender for the round benchmark."""

from __future__ import annotations

import math

from app.benchmark.features import BenchmarkFeatureBuilder, FEATURE_KEYS
from app.learning.weights import project_weights


class BenchmarkRecommender:
    def __init__(
        self,
        workers: list[dict],
        tasks: list[dict],
        customers: list[dict],
        weights: dict[str, float],
    ) -> None:
        self.workers = workers
        self.tasks = tasks
        self.weights = dict(weights)
        self.prior = dict(weights)
        self.feature_builder = BenchmarkFeatureBuilder(
            workers, tasks, customers
        )
        self.last_recommendations: dict[str, list[str]] = {}
        self.last_scores: dict[str, dict[str, float]] = {}
        self.reset_count = 0

    def reset(self) -> None:
        """Forget the previous round's recommendations, keep learned weights."""
        self.last_recommendations = {}
        self.last_scores = {}
        self.reset_count += 1

    def rank(self, task_id: str, top_k: int = 5) -> list[tuple[str, float]]:
        scored = []
        for worker in self.workers:
            features = self.feature_builder.features(
                task_id, worker["worker_id"]
            )
            score = sum(
                self.weights.get(key, 0.0) * features.get(key, 0.0)
                for key in FEATURE_KEYS
            )
            scored.append((worker["worker_id"], score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:top_k]

    def recommend_all(
        self, tasks: list[dict], top_k: int = 5
    ) -> dict[str, list[str]]:
        predictions = {}
        scores = {}
        for task in tasks:
            ranked = self.rank(task["task_id"], top_k=top_k)
            predictions[task["task_id"]] = [
                worker_id for worker_id, _ in ranked
            ]
            scores[task["task_id"]] = {
                worker_id: score for worker_id, score in ranked
            }
        self.last_recommendations = predictions
        self.last_scores = scores
        return predictions

    def learn(
        self,
        labels: dict[str, str],
        train_task_ids: list[str],
        learning_rate: float = 1.0,
        l2_lambda: float = 0.01,
    ) -> dict:
        """Listwise softmax update over the current top candidates.

        A single pairwise hard negative oscillated on this benchmark; the
        softmax gradient uses a candidate set and averages over tasks.
        """
        gradients = {key: 0.0 for key in FEATURE_KEYS}
        used = 0
        for task_id in train_task_ids:
            gold = labels.get(task_id)
            if gold is None:
                continue
            ranked = self.rank(task_id, top_k=20)
            worker_ids = [worker_id for worker_id, _ in ranked]
            if gold not in worker_ids:
                worker_ids = worker_ids[:-1] + [gold]
            features = [
                self.feature_builder.features(task_id, worker_id)
                for worker_id in worker_ids
            ]
            scores = [
                sum(
                    self.weights.get(key, 0.0) * vector.get(key, 0.0)
                    for key in FEATURE_KEYS
                )
                for vector in features
            ]
            maximum = max(scores)
            exponentials = [
                math.exp(score - maximum) for score in scores
            ]
            total = sum(exponentials)
            for index, worker_id in enumerate(worker_ids):
                coefficient = exponentials[index] / total - (
                    1.0 if worker_id == gold else 0.0
                )
                for key in FEATURE_KEYS:
                    gradients[key] += (
                        coefficient * features[index][key]
                    )
            used += 1

        if used:
            for key in FEATURE_KEYS:
                gradients[key] /= used
            raw = {
                key: self.weights[key]
                - learning_rate * gradients[key]
                - l2_lambda
                * (self.weights[key] - self.prior.get(key, self.weights[key]))
                for key in FEATURE_KEYS
            }
            self.weights = project_weights(raw)
        return {"updates": used, "weights": dict(self.weights)}
