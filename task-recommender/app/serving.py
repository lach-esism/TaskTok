"""Serving-parity construction of semantic and acceptance components.

``create_app`` injects one fitted :class:`SemanticMatcher` and one
:class:`AcceptanceModel` into every recommendation service. Offline evaluation
and weight tuning must inject the same components, fitted from a **train-only**
store, otherwise their evidence does not describe the serving ranker.

The helpers here are deliberately free of FastAPI imports so
``evaluation_strict`` and ``scripts/tune_weights.py`` can use them without
importing ``app.main``.
"""

from __future__ import annotations

from app.data.store import Store
from app.domain import Task, Worker
from app.features import pay_fit_score, skill_score
from app.learning.acceptance import AcceptanceModel, accept_features
from app.semantic import (
    SemanticMatcher,
    build_matcher,
    build_task_text,
    build_worker_text,
)


def region_match(worker: Worker, task: Task) -> float:
    """1.0 for the same region, 0.8 when both sides accept remote, else 0.3."""
    if worker.region == task.region:
        return 1.0
    if worker.remote_ok and task.remote_ok:
        return 0.8
    return 0.3


def build_semantic_matcher(store: Store) -> SemanticMatcher | None:
    """Fit one matcher over the store's worker/task surface text.

    No labels or outcomes are read; the text corpus comes from worker and task
    entities only, so fitting on a train-only store cannot leak test outcomes.
    """
    try:
        matcher = build_matcher()
        matcher.fit(
            [
                build_worker_text(worker)
                for worker in store.workers.values()
            ],
            [
                build_task_text(task)
                for task in store.tasks.values()
            ],
        )
    except Exception:  # noqa: BLE001 - a missing matcher degrades to neutral
        return None
    return matcher if matcher.is_fitted else None


def build_acceptance_model(store: Store) -> AcceptanceModel | None:
    """Fit the global ``P(accept)`` model from the store's accept/reject events."""
    counts: dict[str, tuple[int, int]] = {}
    for event in store.events:
        if event.candidate_type != "worker":
            continue
        if event.action not in {"accept", "reject"}:
            continue
        accepted, rejected = counts.get(event.candidate_id, (0, 0))
        if event.action == "accept":
            accepted += 1
        else:
            rejected += 1
        counts[event.candidate_id] = (accepted, rejected)

    samples: list[tuple[dict[str, float], int]] = []
    for event in store.events:
        if event.candidate_type != "worker":
            continue
        if event.action not in {"accept", "reject"}:
            continue
        worker = store.workers.get(event.candidate_id)
        task = store.tasks.get(event.task_id)
        if worker is None or task is None:
            continue
        accepted, rejected = counts.get(worker.worker_id, (0, 0))
        historical = (
            (accepted + 1) / (accepted + rejected + 2)
            if accepted + rejected > 0
            else 0.5
        )
        samples.append(
            (
                accept_features(
                    worker,
                    task,
                    skill=skill_score(worker, task),
                    pay_fit=pay_fit_score(worker, task),
                    region_match=region_match(worker, task),
                    historical_accept_rate=historical,
                ),
                1 if event.action == "accept" else 0,
            )
        )
    try:
        model = AcceptanceModel().fit(samples)
    except Exception:  # noqa: BLE001 - an unfitted model degrades to prior
        return None
    return model if model.is_fitted else None


def build_serving_components(
    store: Store,
) -> tuple[SemanticMatcher | None, AcceptanceModel | None]:
    """Return the ``(semantic_matcher, acceptance_model)`` serving pair."""
    return build_semantic_matcher(store), build_acceptance_model(store)


def serving_components(
    store: Store,
) -> tuple[SemanticMatcher | None, AcceptanceModel | None]:
    """Fit (once per store) and reuse serving components for this store.

    Tuning evaluates many weight vectors against the same fit store; refitting
    TF-IDF/SVD for each candidate would dominate runtime. The cache lives on the
    store instance and is discarded with it, so a new train-only store always
    gets freshly fitted, train-only components.
    """
    cached = getattr(store, "_serving_components_cache", None)
    if cached is None:
        cached = build_serving_components(store)
        store._serving_components_cache = cached
    return cached
