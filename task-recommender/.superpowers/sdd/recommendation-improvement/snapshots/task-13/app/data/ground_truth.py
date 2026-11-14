"""Latent true weights and evaluation-only ground truth."""

from __future__ import annotations

import csv
from pathlib import Path

from app.data.latent import true_weight_simplex
from app.domain import Customer, Dataset

__all__ = ["build_ground_truth", "true_weight_simplex"]


def build_ground_truth(
    dataset: Dataset,
    path: Path,
    seed: int = 42,
) -> Path:
    from app.features import candidate_features

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    reference = (
        dataset.assignments[-1].created_at
        if dataset.assignments
        else max(task.created_at for task in dataset.tasks)
    )
    customers = {customer.customer_id: customer for customer in dataset.customers}

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["worker_id", "task_id", "true_match"])
        for worker in dataset.workers:
            weights = dataset.true_weights.get(worker.worker_id)
            if not weights:
                continue
            for task in dataset.tasks:
                customer = customers.get(task.customer_id)
                if customer is None:
                    customer = Customer(
                        customer_id=task.customer_id,
                        name="Unknown",
                        region=task.region,
                    )
                features = candidate_features(
                    worker,
                    task,
                    customer,
                    cf_score=0.0,
                    now=reference,
                )
                match = sum(
                    weights.get(key, 0.0) * features.get(key, 0.0)
                    for key in weights
                )
                writer.writerow(
                    [worker.worker_id, task.task_id, round(match, 6)]
                )
    return path


def compute_target_stats(dataset: Dataset) -> dict[str, float]:
    ratings = [item.overall_rating for item in dataset.feedback]
    breaches = sum(
        1 for item in dataset.assignments if item.breach_type
    )
    return {
        "workers": float(len(dataset.workers)),
        "tasks": float(len(dataset.tasks)),
        "assignments": float(len(dataset.assignments)),
        "rating_mean": (
            sum(ratings) / len(ratings) if ratings else 0.0
        ),
        "breach_rate": (
            breaches / len(dataset.assignments)
            if dataset.assignments
            else 0.0
        ),
    }


def validate_targets(
    stats: dict[str, float],
    targets: dict[str, float],
    tolerances: dict[str, float],
) -> dict[str, bool]:
    return {
        key: abs(stats.get(key, 0.0) - target) <= tolerances.get(key, 0.0)
        for key, target in targets.items()
    }
