"""Phase 2 evaluation: two-run comparison and learning curves."""

from __future__ import annotations

import math
from statistics import mean

from app.domain import Customer
from app.features import candidate_features
from app.metrics import evaluate_recommender, hr_at_k, ndcg_at_k
from app.service import RecommendationService, is_eligible


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(key, 0.0) * b.get(key, 0.0) for key in keys)
    norm_a = math.sqrt(sum(a.get(key, 0.0) ** 2 for key in keys))
    norm_b = math.sqrt(sum(b.get(key, 0.0) ** 2 for key in keys))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def weight_recovery(
    learned: dict[str, float], truth: dict[str, float]
) -> float:
    return _cosine(learned, truth)


def _true_match(store, user, task, true_weights, now) -> float:
    customer = store.customers.get(task.customer_id)
    if customer is None:
        customer = Customer(
            customer_id=task.customer_id,
            name="Unknown",
            region=task.region,
        )
    features = candidate_features(
        user, task, customer, cf_score=0.0, now=now
    )
    return sum(
        true_weights.get(key, 0.0) * features.get(key, 0.0)
        for key in true_weights
    )


def _constraint_violations(store, service, k: int) -> float:
    violations = 0
    for assignment in store.assignments:
        task = service.store.tasks.get(assignment.task_id)
        if task is None:
            continue
        try:
            candidates = service.recommend_workers(
                assignment.task_id, top_n=k
            )
        except KeyError:
            continue
        for candidate in candidates:
            worker = service.store.workers.get(candidate.candidate_id)
            if worker is None:
                continue
            eligible, _ = is_eligible(
                worker, task, service.store, now=service.reference_time
            )
            if not eligible:
                violations += 1
    return float(violations)


def evaluate_two_runs(
    store,
    service: RecommendationService,
    baseline_weights: dict[str, float],
    learned_weights: dict[str, float],
    k: int = 10,
) -> dict:
    baseline = RecommendationService(
        service.store, weights=baseline_weights
    )
    learned = RecommendationService(
        service.store, weights=learned_weights
    )
    baseline_metrics = evaluate_recommender(store, baseline, k=k)
    learned_metrics = evaluate_recommender(store, learned, k=k)
    breaches = sum(
        1
        for assignment in store.assignments
        if assignment.breach_type
    )
    total = max(1, len(store.assignments))
    return {
        "baseline_ndcg": (
            baseline_metrics["task_to_workers_ndcg"]
            + baseline_metrics["worker_to_tasks_ndcg"]
        )
        / 2.0,
        "learned_ndcg": (
            learned_metrics["task_to_workers_ndcg"]
            + learned_metrics["worker_to_tasks_ndcg"]
        )
        / 2.0,
        "baseline_hr": (
            baseline_metrics["task_to_workers_hr"]
            + baseline_metrics["worker_to_tasks_hr"]
        )
        / 2.0,
        "learned_hr": (
            learned_metrics["task_to_workers_hr"]
            + learned_metrics["worker_to_tasks_hr"]
        )
        / 2.0,
        "baseline_rmse": None,
        "learned_rmse": None,
        "breach_rate": breaches / total,
        "constraint_violations": _constraint_violations(store, service, k),
        "gini": None,
    }


def learning_curve(
    store,
    personalizer,
    user_ids: list[str],
    steps=(0, 5, 10, 20, 50, 100),
) -> dict[str, list[float]]:
    service = RecommendationService(store)
    true_weights = getattr(store, "true_weights", {})
    updates = {user_id: 0 for user_id in user_ids}
    result: dict[str, list[float]] = {
        "n": [],
        "ndcg": [],
        "hr": [],
        "regret": [],
        "weight_cosine": [],
    }
    tasks = list(store.tasks.values())
    if not tasks:
        return result

    for step in steps:
        ndcg_values: list[float] = []
        hr_values: list[float] = []
        regret_values: list[float] = []
        cosine_values: list[float] = []
        for user_id in user_ids:
            user = store.workers.get(user_id) or store.customers.get(user_id)
            if user is None:
                continue
            entity_type = (
                "worker" if user_id in store.workers else "customer"
            )
            personalizer.ensure_profile(user_id, entity_type)
            while updates[user_id] < step:
                task = tasks[updates[user_id] % len(tasks)]
                weights = true_weights.get(user_id, {})
                match = (
                    _true_match(
                        store, user, task, weights, store.reference_time
                    )
                    if weights
                    else 0.5
                )
                customer = store.customers.get(task.customer_id)
                if customer is None:
                    customer = Customer(
                        customer_id=task.customer_id,
                        name="Unknown",
                        region=task.region,
                    )
                features = candidate_features(
                    user,
                    task,
                    customer,
                    cf_score=0.0,
                    now=store.reference_time,
                )
                personalizer.update(
                    user_id, features, 5 if match >= 0.5 else 2
                )
                updates[user_id] += 1

            current = personalizer.weights_for(user_id).weights
            if user_id in true_weights:
                cosine_values.append(
                    weight_recovery(current, true_weights[user_id])
                )
            else:
                cosine_values.append(0.0)

            if user_id in store.workers:
                candidates = service.recommend_tasks(
                    user_id, top_n=10, user_id=user_id
                )
                recommended = [item.candidate_id for item in candidates]
                relevance = {
                    task.task_id: (
                        _true_match(
                            store,
                            user,
                            task,
                            true_weights.get(user_id, {}),
                            store.reference_time,
                        )
                        if user_id in true_weights
                        else 0.0
                    )
                    for task in tasks
                }
                ndcg = ndcg_at_k(recommended, relevance, 10)
                oracle = set(
                    sorted(
                        relevance,
                        key=lambda task_id: relevance[task_id],
                        reverse=True,
                    )[:10]
                )
                ndcg_values.append(ndcg)
                hr_values.append(hr_at_k(recommended, oracle, 10))
                regret_values.append(max(0.0, 1.0 - ndcg))
            else:
                ndcg_values.append(0.0)
                hr_values.append(0.0)
                regret_values.append(1.0)

        result["n"].append(float(step))
        result["ndcg"].append(mean(ndcg_values) if ndcg_values else 0.0)
        result["hr"].append(mean(hr_values) if hr_values else 0.0)
        result["regret"].append(
            mean(regret_values) if regret_values else 0.0
        )
        result["weight_cosine"].append(
            mean(cosine_values) if cosine_values else 0.0
        )
    return result


def compare_queries(
    store,
    service_a: RecommendationService,
    service_b: RecommendationService,
    queries: list[dict],
    k: int = 10,
) -> list[dict]:
    rows = []
    for query in queries:
        task_id = query["task_id"]
        baseline = [
            item.candidate_id
            for item in service_a.recommend_workers(task_id, top_n=k)
        ]
        learned = [
            item.candidate_id
            for item in service_b.recommend_workers(task_id, top_n=k)
        ]
        rows.append(
            {
                "task_id": task_id,
                "baseline": baseline,
                "learned": learned,
                "changed": baseline != learned,
            }
        )
    return rows
