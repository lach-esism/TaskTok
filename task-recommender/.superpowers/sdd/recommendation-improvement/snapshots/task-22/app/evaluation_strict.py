"""Strict, leakage-free evaluation for task<->worker ranking.

Training-side data is assembled from train-only splits. Test assignments are
scored against that store, and test impressions may only define the candidate
set in ``candidate_mode="exposed"``. Ground-truth weights and benchmark labels
are never read here.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from datetime import datetime, timezone

from app.config import DEFAULT_WEIGHTS
from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.domain import Assignment, Dataset, Feedback, Impression
from app.features import fuse_scores
from app.learning.calibration import MIN_SAMPLES, PlattCalibrator
from app.service import RecommendationService, is_eligible

VALID_CANDIDATE_MODES = ("all", "exposed")

# Defaults for the strict report. They mirror the plan's protocol: a paired
# bootstrap over all test queries and 100 timed recommendations.
BOOTSTRAP_SAMPLES = 1000
BOOTSTRAP_SEED = 42
LATENCY_SAMPLES = 100
CALIBRATION_BINS = 5
POSITIVE_RATING = 4
IDENTITY_TOLERANCE = 1e-9

_DIRECTIONS = (
    "task_to_workers",
    "task_to_workers_exposed",
    "worker_to_tasks",
    "worker_to_tasks_exposed",
)
_METRICS = ("hr", "ndcg", "mrr")

# (assignment, hr, ndcg, mrr, served top-k candidates)
Row = tuple[Assignment, float, float, float, list[str]]


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
    cache: dict[str, list[str]] | None = None,
) -> list[str]:
    ranking = None
    if cache is not None:
        ranking = cache.get(assignment.assignment_id)
    if ranking is None:
        ranking = [
            candidate.candidate_id
            for candidate in service.recommend_workers(
                assignment.task_id, top_n=len(store.workers)
            )
        ]
        if cache is not None:
            cache[assignment.assignment_id] = ranking
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


def _scores_for_rank(
    ranked: list[str], positive: str, k: int
) -> tuple[float, float, float]:
    try:
        rank = ranked.index(positive)
    except ValueError:
        rank = None
    if rank is not None and rank < k:
        return 1.0, 1.0 / math.log2(rank + 2), 1.0 / (rank + 1)
    return 0.0, 0.0, 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _aggregate_rows(
    rows: list[Row],
) -> dict:
    return {
        "hr": _mean([row[1] for row in rows]),
        "ndcg": _mean([row[2] for row in rows]),
        "mrr": _mean([row[3] for row in rows]),
        "queries": len(rows),
    }


def _task_to_workers_rows(
    store: Store,
    service: RecommendationService,
    test_assignments: list[Assignment],
    k: int = 10,
    candidate_mode: str = "all",
    impressions: list[Impression] | None = None,
    cache: dict[str, list[str]] | None = None,
) -> list[Row]:
    if candidate_mode not in VALID_CANDIDATE_MODES:
        raise ValueError(
            f"unknown candidate_mode: {candidate_mode!r}; "
            f"expected one of {VALID_CANDIDATE_MODES}"
        )

    source_impressions = (
        store.impressions if impressions is None else impressions
    )
    rows: list[Row] = []
    for assignment in test_assignments:
        if store.tasks.get(assignment.task_id) is None:
            continue
        ranked = _ranked_candidates(
            store,
            service,
            assignment,
            candidate_mode,
            source_impressions,
            cache,
        )
        hr, ndcg, mrr = _scores_for_rank(
            ranked, assignment.worker_id, k
        )
        rows.append(
            (assignment, hr, ndcg, mrr, ranked[: max(0, k)])
        )
    return rows


def _worker_to_tasks_rows(
    store: Store,
    service: RecommendationService,
    test_assignments: list[Assignment],
    k: int = 10,
    candidate_mode: str = "all",
    impressions: list[Impression] | None = None,
    cache: dict[str, list[str]] | None = None,
) -> list[Row]:
    """Group test assignments by worker and rank that worker's tasks once.

    In ``"exposed"`` mode the ranked tasks are restricted to tasks whose
    impression lists this worker as a candidate. ``impressions`` is
    evaluation-only and never written into the store; when it is ``None`` the
    store's own impressions are used. If no exposed task appears for a worker,
    the full eligible ranking is used instead.
    """
    if candidate_mode not in VALID_CANDIDATE_MODES:
        raise ValueError(
            f"unknown candidate_mode: {candidate_mode!r}; "
            f"expected one of {VALID_CANDIDATE_MODES}"
        )

    exposed_by_worker: dict[str, set[str]] = {}
    if candidate_mode == "exposed":
        source_impressions = (
            store.impressions if impressions is None else impressions
        )
        for impression in source_impressions:
            for candidate_id in impression.candidate_ids:
                exposed_by_worker.setdefault(
                    candidate_id, set()
                ).add(impression.query_id)

    grouped: dict[str, list[Assignment]] = {}
    for assignment in test_assignments:
        grouped.setdefault(assignment.worker_id, []).append(assignment)

    rows: list[Row] = []
    for worker_id, assignments in grouped.items():
        if store.workers.get(worker_id) is None:
            continue
        ranked = None
        if cache is not None:
            ranked = cache.get(worker_id)
        if ranked is None:
            ranked = [
                candidate.candidate_id
                for candidate in service.recommend_tasks(
                    worker_id, top_n=len(store.tasks)
                )
            ]
            if cache is not None:
                cache[worker_id] = ranked
        if candidate_mode == "exposed":
            exposed_tasks = exposed_by_worker.get(worker_id, set())
            restricted = [
                task_id for task_id in ranked if task_id in exposed_tasks
            ]
            if restricted:
                ranked = restricted
        for assignment in assignments:
            if store.tasks.get(assignment.task_id) is None:
                continue
            hr, ndcg, mrr = _scores_for_rank(
                ranked, assignment.task_id, k
            )
            rows.append(
                (assignment, hr, ndcg, mrr, ranked[: max(0, k)])
            )
    return rows


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
    rows = _task_to_workers_rows(
        store,
        service,
        test_assignments,
        k=k,
        candidate_mode=candidate_mode,
        impressions=impressions,
    )
    return _aggregate_rows(rows)


def worker_to_tasks_metrics(
    store: Store,
    service: RecommendationService,
    test_assignments: list[Assignment],
    k: int = 10,
    candidate_mode: str = "all",
    impressions: list[Impression] | None = None,
) -> dict:
    """Return bounded HR/NDCG/MRR for worker->tasks ranking over test queries.

    Queries are grouped by worker so each worker's tasks are ranked once. In
    ``"exposed"`` mode candidates are restricted to tasks where the worker
    appears in ``impressions`` (or ``store.impressions`` when ``impressions``
    is ``None``); the provided list is evaluation-only and never written into
    the store.

    An assignment whose worker or task is missing from the store is skipped. An
    assignment whose accepted task is absent from the ranking contributes zero
    but still counts as an evaluated query.
    """
    rows = _worker_to_tasks_rows(
        store,
        service,
        test_assignments,
        k=k,
        candidate_mode=candidate_mode,
        impressions=impressions,
    )
    return _aggregate_rows(rows)


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    fraction = position - lower
    return (
        sorted_values[lower]
        + (sorted_values[upper] - sorted_values[lower]) * fraction
    )


def paired_bootstrap(
    deltas: list[float], n_boot: int = 1000, seed: int = 42
) -> dict:
    """Paired bootstrap over per-query deltas.

    Returns the observed mean, the 2.5/97.5 percentile interval of the
    bootstrap means, and the two-sided bootstrap p-value
    ``2 * min(P(mean <= 0), P(mean >= 0))`` capped at 1.0.
    """
    values = [float(value) for value in deltas]
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0, "p_value": 1.0}

    mean = statistics.fmean(values)
    if n_boot <= 0:
        return {"mean": mean, "low": mean, "high": mean, "p_value": 1.0}

    rng = random.Random(seed)
    count = len(values)
    means = [
        statistics.fmean(
            [values[rng.randrange(count)] for _ in range(count)]
        )
        for _ in range(n_boot)
    ]
    ordered = sorted(means)
    low = _percentile(ordered, 0.025)
    high = _percentile(ordered, 0.975)
    fraction_le_zero = sum(1 for item in means if item <= 0.0) / len(means)
    fraction_ge_zero = sum(1 for item in means if item >= 0.0) / len(means)
    p_value = min(1.0, 2.0 * min(fraction_le_zero, fraction_ge_zero))
    return {
        "mean": mean,
        "low": low,
        "high": high,
        "p_value": p_value,
    }


def weights_equivalent(
    left: dict[str, float],
    right: dict[str, float],
    tolerance: float = IDENTITY_TOLERANCE,
) -> bool:
    """Return whether two weight dicts are numerically the same model.

    Key sets must match exactly, so a partial or extra-key candidate is never
    reported as identical to the baseline just because the shared keys match.
    """
    if set(left) != set(right):
        return False
    return all(
        abs(float(left[key]) - float(right[key])) <= tolerance
        for key in left
    )


def _positive_rate(labels: list[int]) -> float | None:
    return sum(labels) / len(labels) if labels else None


def _raw_brier(scores: list[float], labels: list[int]) -> float:
    if not scores:
        return 0.0
    return sum(
        (float(score) - label) ** 2 for score, label in zip(scores, labels)
    ) / len(scores)


def _calibration_pairs(
    service: RecommendationService,
    assignments: list[Assignment],
    feedback: list[Feedback],
    weights: dict[str, float],
    cache: dict[tuple[str, str], float],
) -> tuple[list[float], list[int]]:
    """Return candidate scores and ``rating >= 4`` labels for assignments.

    Scores come from the same serving-parity ``features_for`` path used by the
    recommender, fused with the candidate weights. Only pairs with feedback are
    returned. ``cache`` is scoped to one train-only store, so features computed
    for a train pair cannot be reused against a different dataset.
    """
    ratings = {
        item.assignment_id: int(item.overall_rating) for item in feedback
    }
    scores: list[float] = []
    labels: list[int] = []
    for assignment in assignments:
        rating = ratings.get(assignment.assignment_id)
        if rating is None:
            continue
        key = (assignment.task_id, assignment.worker_id)
        score = cache.get(key)
        if score is None:
            try:
                features = service.features_for(
                    assignment.task_id, assignment.worker_id
                )
            except KeyError:
                continue
            score = fuse_scores(features, weights)
            cache[key] = score
        scores.append(score)
        labels.append(1 if rating >= POSITIVE_RATING else 0)
    return scores, labels


def _reliability_bins(
    calibrator: PlattCalibrator,
    scores: list[float],
    labels: list[int],
    n_bins: int = CALIBRATION_BINS,
) -> list[dict]:
    """Equal-width reliability bins over calibrated test probabilities."""
    counts = [0] * n_bins
    predicted_sums = [0.0] * n_bins
    positive_sums = [0] * n_bins
    for score, label in zip(scores, labels):
        probability = calibrator.predict(score)
        index = min(int(probability * n_bins), n_bins - 1)
        counts[index] += 1
        predicted_sums[index] += probability
        positive_sums[index] += label

    bins: list[dict] = []
    for index in range(n_bins):
        low = index / n_bins
        high = (index + 1) / n_bins
        count = counts[index]
        bins.append(
            {
                "bin_low": round(low, 6),
                "bin_high": round(high, 6),
                "count": count,
                "mean_predicted": (
                    predicted_sums[index] / count if count else None
                ),
                "observed_rate": (
                    positive_sums[index] / count if count else None
                ),
            }
        )
    return bins


def _calibration_report(
    train_scores: list[float],
    train_labels: list[int],
    test_scores: list[float],
    test_labels: list[int],
) -> dict:
    """Fit on train and report Brier/reliability on test.

    Calibration is unavailable unless there are enough train observations,
    both label classes, and at least one test observation. Unavailable reports
    never contain fabricated Brier scores or bins.
    """
    report = {
        "available": False,
        "reason": None,
        "label": "rating>=4",
        "train_samples": len(train_scores),
        "test_samples": len(test_scores),
        "train_positive_rate": _positive_rate(train_labels),
        "test_positive_rate": _positive_rate(test_labels),
        "brier": None,
        "raw_brier": None,
        "a": None,
        "b": None,
        "reliability_bins": [],
    }
    if len(train_scores) < MIN_SAMPLES:
        report["reason"] = (
            f"fewer than {MIN_SAMPLES} train (score, label) pairs"
        )
        return report
    if len(set(train_labels)) < 2:
        report["reason"] = "train labels contain a single class"
        return report
    if not test_scores:
        report["reason"] = "no test (score, label) pairs"
        return report

    calibrator = PlattCalibrator().fit(train_scores, train_labels)
    report.update(
        {
            "available": True,
            "brier": calibrator.brier(test_scores, test_labels),
            "raw_brier": _raw_brier(test_scores, test_labels),
            "a": calibrator.a,
            "b": calibrator.b,
            "reliability_bins": _reliability_bins(
                calibrator, test_scores, test_labels
            ),
        }
    )
    return report


def _paired_delta_values(
    baseline_rows: list[Row],
    candidate_rows: list[Row],
) -> dict[str, list[float]]:
    baseline = {row[0].assignment_id: row for row in baseline_rows}
    candidate = {row[0].assignment_id: row for row in candidate_rows}
    keys = sorted(baseline.keys() & candidate.keys())
    return {
        "hr": [
            candidate[key][1] - baseline[key][1] for key in keys
        ],
        "ndcg": [
            candidate[key][2] - baseline[key][2] for key in keys
        ],
        "mrr": [
            candidate[key][3] - baseline[key][3] for key in keys
        ],
    }


def _evaluation_rows(
    store: Store,
    service: RecommendationService,
    test_assignments: list[Assignment],
    k: int,
    test_impressions: list[Impression],
) -> dict[str, list[Row]]:
    task_cache: dict[str, list[str]] = {}
    worker_cache: dict[str, list[str]] = {}
    return {
        "task_to_workers": _task_to_workers_rows(
            store, service, test_assignments, k, "all", None, task_cache
        ),
        "task_to_workers_exposed": _task_to_workers_rows(
            store,
            service,
            test_assignments,
            k,
            "exposed",
            test_impressions,
            task_cache,
        ),
        "worker_to_tasks": _worker_to_tasks_rows(
            store, service, test_assignments, k, "all", None, worker_cache
        ),
        "worker_to_tasks_exposed": _worker_to_tasks_rows(
            store,
            service,
            test_assignments,
            k,
            "exposed",
            test_impressions,
            worker_cache,
        ),
    }


def _task_to_workers_violations(
    store: Store,
    rows: list[Row],
) -> int:
    violations = 0
    for assignment, _, _, _, ranked in rows:
        task = store.tasks.get(assignment.task_id)
        if task is None:
            continue
        for worker_id in ranked:
            worker = store.workers.get(worker_id)
            if worker is None:
                violations += 1
                continue
            eligible, _ = is_eligible(
                worker, task, store, now=store.reference_time
            )
            if not eligible:
                violations += 1
    return violations


def _worker_to_tasks_violations(
    store: Store,
    rows: list[Row],
) -> int:
    violations = 0
    for assignment, _, _, _, ranked in rows:
        worker = store.workers.get(assignment.worker_id)
        if worker is None:
            continue
        for task_id in ranked:
            task = store.tasks.get(task_id)
            if task is None:
                violations += 1
                continue
            eligible, _ = is_eligible(
                worker, task, store, now=store.reference_time
            )
            if not eligible:
                violations += 1
    return violations


def _measure_latency(
    store: Store,
    service: RecommendationService,
    test_assignments: list[Assignment],
    k: int,
    n_samples: int = LATENCY_SAMPLES,
) -> list[float]:
    pairs = [
        (assignment.task_id, assignment.worker_id)
        for assignment in test_assignments
        if store.tasks.get(assignment.task_id) is not None
        and store.workers.get(assignment.worker_id) is not None
    ]
    if not pairs or n_samples <= 0:
        return []

    latencies: list[float] = []
    for index in range(n_samples):
        task_id, worker_id = pairs[index % len(pairs)]
        started = time.perf_counter()
        if index % 2 == 0:
            service.recommend_workers(task_id, top_n=k)
        else:
            service.recommend_tasks(worker_id, top_n=k)
        latencies.append((time.perf_counter() - started) * 1000.0)
    return latencies


def evaluate_strict(
    dataset: Dataset,
    weights: dict[str, float],
    k: int = 10,
    seeds: tuple[int, ...] = (42,),
) -> dict:
    """Evaluate ``DEFAULT_WEIGHTS`` against ``weights`` over one or more seeds.

    For each seed a fresh dataset is generated with
    ``generate_dataset(seed=seed)``, a train-only eval store is built, and both
    directions are scored with per-query HR/NDCG/MRR. Deltas are pooled across
    seeds and reported with a paired bootstrap. Both ``"exposed"`` modes
    receive ``dataset.test_impressions`` as evaluation-only input; the store
    itself is never mutated.

    ``dataset`` is used only when ``seeds`` is empty, so callers that already
    hold the dataset can evaluate it without another generation pass.
    ``cold_start["available"]`` is false when none of the evaluated datasets
    contains a worker with zero train assignments; ``cold_start["reason"]``
    explains an unavailable or empty subset.
    """
    seed_list = tuple(int(seed) for seed in seeds)
    if seed_list:
        datasets = [
            generate_dataset(seed=seed) for seed in seed_list
        ]
    else:
        datasets = [dataset]

    pooled_baseline: dict[str, list] = {name: [] for name in _DIRECTIONS}
    pooled_candidate: dict[str, list] = {name: [] for name in _DIRECTIONS}
    pooled_cold_baseline: dict[str, list] = {
        name: [] for name in _DIRECTIONS
    }
    pooled_cold_candidate: dict[str, list] = {
        name: [] for name in _DIRECTIONS
    }
    delta_values: dict[str, dict[str, list[float]]] = {
        name: {metric: [] for metric in _METRICS}
        for name in _DIRECTIONS
    }
    cold_delta_values: dict[str, dict[str, list[float]]] = {
        name: {metric: [] for metric in _METRICS}
        for name in _DIRECTIONS
    }
    violations = 0
    latencies: list[float] = []
    saw_cold_workers = False
    cold_query_count = 0
    calibration_train_scores: list[float] = []
    calibration_train_labels: list[int] = []
    calibration_test_scores: list[float] = []
    calibration_test_labels: list[int] = []

    for data in datasets:
        store = build_eval_store(data)
        test_assignments = data.test
        test_impressions = data.test_impressions
        baseline_service = RecommendationService(
            store, weights=DEFAULT_WEIGHTS
        )
        candidate_service = RecommendationService(store, weights=weights)

        baseline_rows = _evaluation_rows(
            store, baseline_service, test_assignments, k, test_impressions
        )
        candidate_rows = _evaluation_rows(
            store, candidate_service, test_assignments, k, test_impressions
        )

        calibration_cache: dict[tuple[str, str], float] = {}
        train_scores, train_labels = _calibration_pairs(
            candidate_service,
            data.train,
            data.train_feedback,
            weights,
            calibration_cache,
        )
        test_scores, test_labels = _calibration_pairs(
            candidate_service,
            test_assignments,
            data.test_feedback,
            weights,
            calibration_cache,
        )
        calibration_train_scores.extend(train_scores)
        calibration_train_labels.extend(train_labels)
        calibration_test_scores.extend(test_scores)
        calibration_test_labels.extend(test_labels)

        train_workers = {
            assignment.worker_id for assignment in data.train
        }
        cold_worker_ids = {
            worker_id
            for worker_id in store.workers
            if worker_id not in train_workers
        }
        if cold_worker_ids:
            saw_cold_workers = True
        cold_ids = {
            assignment.assignment_id
            for assignment in test_assignments
            if assignment.worker_id in cold_worker_ids
        }
        cold_query_count += len(cold_ids)

        for name in _DIRECTIONS:
            pooled_baseline[name].extend(baseline_rows[name])
            pooled_candidate[name].extend(candidate_rows[name])

            cold_baseline = [
                row
                for row in baseline_rows[name]
                if row[0].assignment_id in cold_ids
            ]
            cold_candidate = [
                row
                for row in candidate_rows[name]
                if row[0].assignment_id in cold_ids
            ]
            pooled_cold_baseline[name].extend(cold_baseline)
            pooled_cold_candidate[name].extend(cold_candidate)

            for metric, values in _paired_delta_values(
                baseline_rows[name], candidate_rows[name]
            ).items():
                delta_values[name][metric].extend(values)
            for metric, values in _paired_delta_values(
                cold_baseline, cold_candidate
            ).items():
                cold_delta_values[name][metric].extend(values)

        violations += _task_to_workers_violations(
            store, candidate_rows["task_to_workers"]
        )
        violations += _worker_to_tasks_violations(
            store, candidate_rows["worker_to_tasks"]
        )
        latencies.extend(
            _measure_latency(
                store, candidate_service, test_assignments, k
            )
        )

    baselines = {
        name: _aggregate_rows(pooled_baseline[name]) for name in _DIRECTIONS
    }
    candidate = {
        name: _aggregate_rows(pooled_candidate[name])
        for name in _DIRECTIONS
    }
    deltas = {
        name: {
            metric: paired_bootstrap(
                values, n_boot=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED
            )
            for metric, values in delta_values[name].items()
        }
        for name in _DIRECTIONS
    }
    if not saw_cold_workers:
        cold_reason: str | None = (
            "no workers without train assignments in the evaluated seeds"
        )
    elif not pooled_cold_baseline["task_to_workers"]:
        cold_reason = (
            "cold workers exist but have no test assignments"
        )
    else:
        cold_reason = None

    cold_start = {
        "available": saw_cold_workers,
        "reason": cold_reason,
        "queries": cold_query_count,
        "measured": bool(saw_cold_workers and cold_query_count > 0),
        "baseline": {
            name: _aggregate_rows(pooled_cold_baseline[name])
            for name in _DIRECTIONS
        },
        "candidate": {
            name: _aggregate_rows(pooled_cold_candidate[name])
            for name in _DIRECTIONS
        },
        "deltas": {
            name: {
                metric: paired_bootstrap(
                    values,
                    n_boot=BOOTSTRAP_SAMPLES,
                    seed=BOOTSTRAP_SEED,
                )
                for metric, values in cold_delta_values[name].items()
            }
            for name in _DIRECTIONS
        },
    }

    ordered_latencies = sorted(latencies)
    return {
        "seeds": list(seed_list),
        "k": k,
        "baselines": baselines,
        "candidate": candidate,
        "deltas": deltas,
        "cold_start": cold_start,
        "calibration": _calibration_report(
            calibration_train_scores,
            calibration_train_labels,
            calibration_test_scores,
            calibration_test_labels,
        ),
        "baseline_equals_candidate": weights_equivalent(
            DEFAULT_WEIGHTS, weights
        ),
        "constraint_violations": violations,
        "latency_p50_ms": (
            round(_percentile(ordered_latencies, 0.5), 4)
            if ordered_latencies
            else 0.0
        ),
        "latency_p95_ms": (
            round(_percentile(ordered_latencies, 0.95), 4)
            if ordered_latencies
            else 0.0
        ),
    }
