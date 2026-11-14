"""Offline ranking and chain decomposition metrics."""

from __future__ import annotations

import math

from app.chains.decompose import decompose, quality_score
from app.chains.dag import validate_dag
from app.chains.planner import plan_chain
from app.data.store import Store
from app.service import RecommendationService, is_eligible


def hr_at_k(recommended: list[str], relevant: set[str], k: int) -> float:
    if not recommended or not relevant or k <= 0:
        return 0.0
    return 1.0 if any(item in relevant for item in recommended[:k]) else 0.0


def ndcg_at_k(
    recommended: list[str], relevance: dict[str, float], k: int
) -> float:
    if not recommended or not relevance or k <= 0:
        return 0.0
    dcg = sum(
        relevance.get(item, 0.0) / math.log2(index + 2)
        for index, item in enumerate(recommended[:k])
    )
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum(
        gain / math.log2(index + 2)
        for index, gain in enumerate(ideal)
    )
    return dcg / idcg if idcg > 0 else 0.0


def evaluate_recommender(
    store: Store,
    service: RecommendationService,
    k: int = 10,
) -> dict[str, float]:
    task_to_workers_hr: list[float] = []
    task_to_workers_ndcg: list[float] = []
    worker_to_tasks_hr: list[float] = []
    worker_to_tasks_ndcg: list[float] = []

    train_pairs = {
        (assignment.task_id, assignment.worker_id)
        for assignment in service.store.assignments
    }

    for assignment in store.assignments:
        if (assignment.task_id, assignment.worker_id) in train_pairs:
            continue
        task = store.tasks.get(assignment.task_id)
        worker = store.workers.get(assignment.worker_id)
        if task is None or worker is None:
            continue
        eligible, _ = is_eligible(
            worker,
            task,
            service.store,
            now=service.reference_time,
        )
        if not eligible:
            continue

        worker_candidates = service.recommend_workers(
            assignment.task_id, top_n=k
        )
        recommended_workers = [item.candidate_id for item in worker_candidates]
        task_to_workers_hr.append(
            hr_at_k(recommended_workers, {assignment.worker_id}, k)
        )
        task_to_workers_ndcg.append(
            ndcg_at_k(
                recommended_workers, {assignment.worker_id: 1.0}, k
            )
        )

        task_candidates = service.recommend_tasks(
            assignment.worker_id, top_n=k
        )
        recommended_tasks = [item.candidate_id for item in task_candidates]
        worker_to_tasks_hr.append(
            hr_at_k(recommended_tasks, {assignment.task_id}, k)
        )
        worker_to_tasks_ndcg.append(
            ndcg_at_k(recommended_tasks, {assignment.task_id: 1.0}, k)
        )

    return {
        "task_to_workers_hr": _mean(task_to_workers_hr),
        "task_to_workers_ndcg": _mean(task_to_workers_ndcg),
        "worker_to_tasks_hr": _mean(worker_to_tasks_hr),
        "worker_to_tasks_ndcg": _mean(worker_to_tasks_ndcg),
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_chains(
    store: Store,
    templates: dict[str, dict],
    n_samples: int = 50,
) -> dict[str, float]:
    tasks = [
        task
        for task in store.tasks.values()
        if task.category in templates
    ][:n_samples]
    if not tasks:
        return {
            "decompose_success_rate": 0.0,
            "mean_coverage": 0.0,
            "mean_quality": 0.0,
            "mean_plan_coverage": 0.0,
            "acyclic_rate": 0.0,
        }

    service = RecommendationService(store)
    successes = 0
    acyclic = 0
    coverage_values: list[float] = []
    quality_values: list[float] = []
    plan_coverages: list[float] = []

    for task in tasks:
        try:
            draft = decompose(task, templates[task.category])
            quality = quality_score(draft, store)
            plan = plan_chain(draft.chain, service)
        except Exception:
            continue
        successes += 1
        if validate_dag(draft.chain.nodes).valid:
            acyclic += 1
        coverage_values.append(quality.coverage)
        quality_values.append(quality.total)
        assigned = sum(
            1 for node in plan.nodes if node.worker_id is not None
        )
        plan_coverages.append(assigned / max(1, len(plan.nodes)))

    return {
        "decompose_success_rate": successes / len(tasks),
        "mean_coverage": _mean(coverage_values),
        "mean_quality": _mean(quality_values),
        "mean_plan_coverage": _mean(plan_coverages),
        "acyclic_rate": acyclic / len(tasks),
    }
