"""Round runner: score first, learn after, forget recommendations, repeat."""

from __future__ import annotations

import math
from pathlib import Path

from app.benchmark.db import BenchmarkRepository
from app.benchmark.recommender import BenchmarkRecommender
from app.learning_simulation import SIM_INITIAL_WEIGHTS


def _metrics(
    predictions: dict[str, list[str]],
    labels: dict[str, str],
    task_ids: list[str],
) -> dict:
    if not task_ids:
        return {
            "top1": 0.0,
            "top5": 0.0,
            "mrr": 0.0,
            "ndcg": 0.0,
        }
    top1 = 0
    top5 = 0
    reciprocal = 0.0
    ndcg = 0.0
    for task_id in task_ids:
        gold = labels[task_id]
        ranked = predictions.get(task_id, [])
        if ranked and ranked[0] == gold:
            top1 += 1
        if gold in ranked[:5]:
            top5 += 1
        if gold in ranked:
            rank = ranked.index(gold)
            reciprocal += 1.0 / (rank + 1)
            if rank < 5:
                ndcg += 1.0 / math.log2(rank + 2)
    total = len(task_ids)
    return {
        "top1": round(top1 / total, 4),
        "top5": round(top5 / total, 4),
        "mrr": round(reciprocal / total, 4),
        "ndcg": round(ndcg / total, 4),
    }


class BenchmarkRoundRunner:
    def __init__(
        self,
        db_path: Path,
        initial_weights: dict[str, float] | None = None,
        learning_rate: float = 0.05,
        top_k: int = 5,
    ) -> None:
        self.repo = BenchmarkRepository(db_path)
        self.workers = self.repo.load_workers()
        self.tasks = self.repo.load_tasks()
        self.customers = self.repo.load_customers()
        self.labels = self.repo.load_labels()
        self.splits = self.repo.load_splits()
        self.top_k = top_k
        self.learning_rate = learning_rate
        self.recommender = BenchmarkRecommender(
            self.workers,
            self.tasks,
            self.customers,
            initial_weights or SIM_INITIAL_WEIGHTS,
        )
        self.train_task_ids = [
            task["task_id"]
            for task in self.tasks
            if self.splits[task["task_id"]] == "train"
        ]
        self.test_task_ids = [
            task["task_id"]
            for task in self.tasks
            if self.splits[task["task_id"]] == "test"
        ]

    def run(self, rounds: int = 5) -> list[dict]:
        all_task_ids = [task["task_id"] for task in self.tasks]
        self.repo.clear_rounds()
        results = []
        for round_no in range(1, rounds + 1):
            cached_before = len(self.recommender.last_recommendations)
            self.recommender.reset()
            forgotten = (
                cached_before == 0
                or len(self.recommender.last_recommendations) == 0
            )

            predictions = self.recommender.recommend_all(
                self.tasks, top_k=self.top_k
            )
            overall = _metrics(predictions, self.labels, all_task_ids)
            train = _metrics(predictions, self.labels, self.train_task_ids)
            test = _metrics(predictions, self.labels, self.test_task_ids)
            metrics = {
                **overall,
                "train_top1": train["top1"],
                "train_top5": train["top5"],
                "test_top1": test["top1"],
                "test_top5": test["top5"],
            }

            weights_before = dict(self.recommender.weights)
            learned = self.recommender.learn(
                self.labels,
                self.train_task_ids,
                learning_rate=self.learning_rate,
            )
            weights_after = dict(self.recommender.weights)

            self.repo.save_round(round_no, metrics, weights_after)
            self.repo.save_recommendations(
                round_no,
                predictions,
                self.recommender.last_scores,
                top_k=self.top_k,
            )
            results.append(
                {
                    "round": round_no,
                    "metrics": metrics,
                    "train": train,
                    "test": test,
                    "updates": learned["updates"],
                    "forgot_previous_answers": forgotten,
                    "cache_size_at_round_start": cached_before,
                    "cache_size_after_round": len(
                        self.recommender.last_recommendations
                    ),
                    "weights_before": weights_before,
                    "weights_after": weights_after,
                }
            )
        return results
