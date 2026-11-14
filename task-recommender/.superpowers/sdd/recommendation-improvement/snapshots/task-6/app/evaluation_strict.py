"""Strict, leakage-free evaluation for the task->workers ranking task.

Training-side data is assembled from train-only splits. Test assignments are
scored against that store, and test impressions may only define the candidate
set in ``candidate_mode="exposed"``. Ground-truth weights and benchmark labels
are never read here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.data.store import Store
from app.domain import Assignment, Dataset, Impression
from app.service import RecommendationService

VALID_CANDIDATE_MODES = ("all", "exposed")


def build_eval_store(dataset: Dataset) -> Store:
    """Build a store that contains train-side data only."""
    return Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.train_feedback,
        events=dataset.train_events,
        impressions=dataset.train_impressions,
    )


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _assignment_id(impression: Impression) -> str | None:
    metadata = impression.metadata
    if not isinstance(metadata, dict):
        return None
    return metadata.get("assignment_id")


def _resolve_impression(
    impressions: list[Impression], assignment: Assignment
) -> Impression | None:
    """Resolve the impression that produced ``assignment``.

    Ids are authoritative; the timestamp fallback only applies to impressions
    whose metadata does not identify an assignment, so a stamped impression for
    a different assignment can never be selected on a timestamp tie.
    """
    for impression in impressions:
        if _assignment_id(impression) == assignment.assignment_id:
            return impression

    created_at = _as_utc(assignment.created_at)
    for impression in impressions:
        if _assignment_id(impression) is not None:
            continue
        if (
            impression.query_id == assignment.task_id
            and _as_utc(impression.created_at) == created_at
        ):
            return impression
    return None


def _ranked_candidates(
    store: Store,
    service: RecommendationService,
    assignment: Assignment,
    candidate_mode: str,
    impressions: list[Impression],
) -> list[str]:
    ranking = [
        candidate.candidate_id
        for candidate in service.recommend_workers(
            assignment.task_id, top_n=len(store.workers)
        )
    ]
    if candidate_mode == "all":
        return ranking

    impression = _resolve_impression(impressions, assignment)
    if impression is None:
        return ranking

    candidate_ids = list(dict.fromkeys(impression.candidate_ids))
    allowed = set(candidate_ids)
    ranked = [
        candidate_id for candidate_id in ranking if candidate_id in allowed
    ]
    seen = set(ranked)
    for candidate_id in candidate_ids:
        if candidate_id not in seen:
            ranked.append(candidate_id)
            seen.add(candidate_id)
    return ranked


def task_to_workers_metrics(
    store: Store,
    service: RecommendationService,
    test_assignments: list[Assignment],
    k: int = 10,
    candidate_mode: str = "all",
    impressions: list[Impression] | None = None,
) -> dict:
    """Return bounded HR/NDCG/MRR for task->workers ranking over test queries.

    ``impressions`` is evaluation-only: when provided, ``"exposed"`` mode
    searches it instead of ``store.impressions``. It is never written into the
    store or used by feature/training code.

    Assignments whose task is missing from ``store.tasks`` are skipped. An
    assignment whose accepted worker is absent from the ranking contributes
    zero but still counts as an evaluated query.
    """
    if candidate_mode not in VALID_CANDIDATE_MODES:
        raise ValueError(
            f"unknown candidate_mode: {candidate_mode!r}; "
            f"expected one of {VALID_CANDIDATE_MODES}"
        )

    source_impressions = (
        store.impressions if impressions is None else impressions
    )
    hr_values: list[float] = []
    ndcg_values: list[float] = []
    mrr_values: list[float] = []
    queries = 0

    for assignment in test_assignments:
        if store.tasks.get(assignment.task_id) is None:
            continue
        queries += 1
        ranked = _ranked_candidates(
            store, service, assignment, candidate_mode, source_impressions
        )
        try:
            rank = ranked.index(assignment.worker_id)
        except ValueError:
            rank = None

        if rank is not None and rank < k:
            hr_values.append(1.0)
            ndcg_values.append(1.0 / math.log2(rank + 2))
            mrr_values.append(1.0 / (rank + 1))
        else:
            hr_values.append(0.0)
            ndcg_values.append(0.0)
            mrr_values.append(0.0)

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "hr": _mean(hr_values),
        "ndcg": _mean(ndcg_values),
        "mrr": _mean(mrr_values),
        "queries": queries,
    }
