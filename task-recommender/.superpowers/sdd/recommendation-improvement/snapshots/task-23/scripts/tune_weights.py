"""Build and tune a choice-learned weight candidate on a validation split.

Pipeline (Task 24):

1. ``build_choice_candidate`` builds a train-only eval store, computes
   serving-parity features for train events, builds choice pairs, fits a
   ``PairwiseChoiceLearner``, blends it 50/50 with the rating batch fit, and
   projects the result onto the AHP simplex.
2. ``tune_on_validation`` holds out the last 20% of train assignments as
   validation and runs a bounded coordinate search over the seven weights,
   scored only on validation metrics. Test assignments/feedback are never
   read for tuning.
3. ``evaluate_candidate`` runs the existing strict evaluator with
   ``DEFAULT_WEIGHTS`` as the baseline and the candidate as the override.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_WEIGHTS  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.data.store import Store  # noqa: E402
from app.domain import Dataset, _split_by_assignment  # noqa: E402
from app.evaluation_strict import (  # noqa: E402
    build_eval_store,
    evaluate_strict,
    task_to_workers_metrics,
    worker_to_tasks_metrics,
)
from app.features import candidate_features  # noqa: E402
from app.learning.choice import (  # noqa: E402
    NEGATIVE_ACTIONS,
    POSITIVE_ACTIONS,
    PairwiseChoiceLearner,
    build_pairs,
)
from app.learning.online import OnlineWeightLearner  # noqa: E402
from app.learning.weights import (  # noqa: E402
    AHP_PRIOR,
    KEYS,
    project_weights,
)
from app.service import RecommendationService  # noqa: E402
from scripts.evaluate_strict import (  # noqa: E402
    _parse_seeds,
    _render_markdown,
)

VALIDATION_FRACTION = 0.2
DEFAULT_BUDGET = 20
DEFAULT_EVAL_SEEDS = (42, 43, 44, 45, 46)
DEFAULT_K = 10
CHOICE_ACTIONS = POSITIVE_ACTIONS | NEGATIVE_ACTIONS

PRIMARY_DIRECTIONS = ("task_to_workers", "worker_to_tasks")


def _event_target(event, impressions_by_request):
    """Map an event to its ``(task_id, worker_id)`` feature target."""
    if event.candidate_type == "task":
        impression = impressions_by_request.get(event.request_id)
        if impression is None:
            return None
        return event.candidate_id, impression.query_id
    if not event.task_id:
        return None
    return event.task_id, event.candidate_id


def _choice_features(events, service):
    """Resolve serving-parity feature vectors for usable choice events.

    Events whose impression, task, or worker no longer resolves are dropped so
    a stale log row can never fail choice learning.
    """
    impressions_by_request = {
        impression.request_id: impression
        for impression in service.store.impressions
    }
    cache: dict[tuple[str, str], dict[str, float]] = {}
    usable = []
    features_by_event: dict[str, dict[str, float]] = {}
    for event in events:
        if event.action not in CHOICE_ACTIONS:
            continue
        target = _event_target(event, impressions_by_request)
        if target is None:
            continue
        features = cache.get(target)
        if features is None:
            try:
                features = service.features_for(*target)
            except KeyError:
                continue
            cache[target] = features
        features_by_event[event.event_id] = features
        usable.append(event)
    return usable, features_by_event


def build_choice_candidate(dataset: Dataset, seed: int = 42) -> dict[str, float]:
    """Build the choice-learned candidate from train data only.

    ``seed`` is accepted for interface compatibility; every step here is
    deterministic (no RNG is used), so the result is reproducible.
    """
    store = build_eval_store(dataset)

    feedback_by_assignment = {
        item.assignment_id: item for item in store.feedback
    }
    records = []
    for assignment in store.assignments:
        feedback = feedback_by_assignment.get(assignment.assignment_id)
        if feedback is None:
            continue
        task = store.tasks.get(assignment.task_id)
        worker = store.workers.get(assignment.worker_id)
        if task is None or worker is None:
            continue
        customer = store.customers.get(task.customer_id)
        if customer is None:
            continue
        records.append(
            (
                candidate_features(
                    worker,
                    task,
                    customer,
                    cf_score=0.0,
                    now=store.reference_time,
                ),
                feedback.overall_rating,
            )
        )

    batch_learner = OnlineWeightLearner(AHP_PRIOR)
    batch_weights = batch_learner.batch_fit(records, epochs=1)

    service = RecommendationService(store, weights=AHP_PRIOR)
    usable, features_by_event = _choice_features(store.events, service)
    pairs = build_pairs(
        usable, lambda event: features_by_event[event.event_id]
    )

    merged = dict(batch_weights)
    if pairs:
        choice_weights = PairwiseChoiceLearner(prior=AHP_PRIOR).fit(pairs)
        merged = {
            key: 0.5 * merged[key] + 0.5 * choice_weights[key]
            for key in KEYS
        }
    return project_weights(merged)


def _validation_split(dataset: Dataset):
    """Split train into a fit store and a held-out validation set.

    Validation is the last ``VALIDATION_FRACTION`` of train assignments. The
    returned store contains only the fit portion, and every event, impression,
    and feedback record belonging to a validation or test assignment is
    excluded explicitly (by assignment id), so test data can never leak into
    the ranking store used for tuning.
    """
    train = sorted(dataset.train, key=lambda item: item.created_at)
    index = int(len(train) * (1.0 - VALIDATION_FRACTION))
    fit = train[:index]
    validation = train[index:]

    fit_ids = {item.assignment_id for item in fit}
    other_ids = {item.assignment_id for item in validation} | {
        item.assignment_id for item in dataset.test
    }
    split_time = (
        max(item.created_at for item in fit) if fit else dataset.split_time
    )
    fit_events, _ = _split_by_assignment(
        dataset.events, fit_ids, other_ids, split_time
    )
    fit_impressions, _ = _split_by_assignment(
        dataset.impressions, fit_ids, other_ids, split_time
    )
    fit_feedback = [
        item for item in dataset.feedback if item.assignment_id in fit_ids
    ]

    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=fit,
        feedback=fit_feedback,
        events=fit_events,
        impressions=fit_impressions,
    )
    return fit, validation, store


def _validation_metrics(
    store: Store, validation_assignments, weights: dict[str, float]
) -> dict:
    """Score one weight vector on the validation queries (primary directions)."""
    service = RecommendationService(store, weights=weights)
    return {
        "task_to_workers": task_to_workers_metrics(
            store, service, validation_assignments, k=DEFAULT_K
        ),
        "worker_to_tasks": worker_to_tasks_metrics(
            store, service, validation_assignments, k=DEFAULT_K
        ),
    }


def _direction_gain(base: dict, candidate: dict) -> float:
    """Unit gain toward the accuracy target for one direction.

    HR +5pp or NDCG +10% relative both count as one unit.
    """
    hr_pp = (candidate["hr"] - base["hr"]) * 100.0
    ndcg_rel = (
        (candidate["ndcg"] - base["ndcg"]) / base["ndcg"]
        if base["ndcg"] > 0.0
        else 0.0
    )
    return max(hr_pp / 5.0, ndcg_rel / 0.10)


def _validation_objective(base_metrics: dict, candidate_metrics: dict) -> float:
    """Scalar, target-aligned objective over validation metrics.

    Maximizes the best primary direction's gain and subtracts a quarter of any
    HR (pp) / NDCG (relative) deterioration across both directions, so a large
    worker->tasks gain cannot be bought with a collapsing task->workers side.
    """

    def deterioration(name: str) -> float:
        base = base_metrics[name]
        candidate = candidate_metrics[name]
        hr_pp = (candidate["hr"] - base["hr"]) * 100.0
        ndcg_rel = (
            (candidate["ndcg"] - base["ndcg"]) / base["ndcg"]
            if base["ndcg"] > 0.0
            else 0.0
        )
        return min(0.0, hr_pp) + 10.0 * min(0.0, ndcg_rel)

    best_gain = max(
        _direction_gain(base_metrics[name], candidate_metrics[name])
        for name in PRIMARY_DIRECTIONS
    )
    penalty = sum(deterioration(name) for name in PRIMARY_DIRECTIONS)
    return best_gain + 0.25 * penalty


def tune_on_validation(
    dataset: Dataset,
    base_weights: dict[str, float],
    budget: int = DEFAULT_BUDGET,
) -> dict[str, float]:
    """Coordinate-search the seven weights using validation metrics only.

    The search perturbs one raw weight at a time (projecting back onto the
    simplex after every change), evaluates at most ``budget`` candidate vectors
    on the validation split, and never reads test assignments or feedback.
    """
    _, validation, store = _validation_split(dataset)
    base_metrics = _validation_metrics(store, validation, dict(DEFAULT_WEIGHTS))
    current = project_weights(dict(base_weights))

    def objective(weights: dict[str, float]) -> float:
        return _validation_objective(
            base_metrics, _validation_metrics(store, validation, weights)
        )

    current_score = objective(current)
    evaluations = 1
    deltas = (0.04, 0.02, 0.01)
    for delta in deltas:
        if evaluations >= budget:
            break
        seen = {json.dumps(current, sort_keys=True)}
        best_trial = None
        best_score = current_score
        for key in KEYS:
            if evaluations >= budget:
                break
            for sign in (1.0, -1.0):
                if evaluations >= budget:
                    break
                raw = dict(current)
                raw[key] = max(0.0, raw[key] + sign * delta)
                trial = project_weights(raw)
                fingerprint = json.dumps(trial, sort_keys=True)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                trial_score = objective(trial)
                evaluations += 1
                if trial_score > best_score:
                    best_score = trial_score
                    best_trial = trial
        if best_trial is not None and best_score > current_score:
            current = best_trial
            current_score = best_score
        else:
            break
    return current


def evaluate_candidate(
    candidate: dict[str, float],
    seeds: tuple[int, ...] = DEFAULT_EVAL_SEEDS,
    k: int = DEFAULT_K,
) -> dict:
    """Run the strict evaluator with the candidate as the weight override."""
    dataset = generate_dataset(seed=seeds[0] if seeds else 42)
    result = evaluate_strict(dataset, candidate, k=k, seeds=seeds)
    result["candidate_source"] = "choice-tuned"
    return result


def _primary_deltas(result: dict) -> dict:
    stats = {}
    for name in PRIMARY_DIRECTIONS:
        baseline = result["baselines"][name]
        candidate = result["candidate"][name]
        ndcg_rel = (
            (candidate["ndcg"] - baseline["ndcg"]) / baseline["ndcg"]
            if baseline["ndcg"] > 0.0
            else 0.0
        )
        stats[name] = {
            "ndcg_rel": ndcg_rel,
            "hr_pp": (candidate["hr"] - baseline["hr"]) * 100.0,
        }
    return stats


def _target_met(result: dict) -> bool:
    if result.get("baseline_equals_candidate"):
        return False
    stats = _primary_deltas(result)

    def qualifies(name: str) -> bool:
        item = stats[name]
        deltas = result["deltas"][name]
        return (
            item["ndcg_rel"] >= 0.10 and deltas["ndcg"]["low"] > 0.0
        ) or (
            item["hr_pp"] >= 5.0 and deltas["hr"]["low"] > 0.0
        )

    qualifying = [name for name in PRIMARY_DIRECTIONS if qualifies(name)]
    if not qualifying:
        return False
    others = [name for name in PRIMARY_DIRECTIONS if name not in qualifying]
    if not others:
        return True
    other = others[0]
    return (
        result["deltas"][other]["ndcg"]["mean"] >= 0.0
        and result["deltas"][other]["hr"]["mean"] >= 0.0
    )


def _write_weights(path: Path, weights: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(weights, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a choice-learned weight candidate, tune it on a validation "
            "split, and run the strict evaluator on the untouched test set."
        )
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="seed for the train/validation dataset used for the candidate",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help="max candidate evaluations for the validation coordinate search",
    )
    parser.add_argument(
        "--seeds",
        type=_parse_seeds,
        default=DEFAULT_EVAL_SEEDS,
        help="comma-separated strict-eval seeds",
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--weights-out",
        default=str(ROOT / "data" / "weights" / "weights_choice.json"),
        help="path for the candidate weight JSON",
    )
    parser.add_argument(
        "--report-dir",
        default=str(ROOT / "reports"),
        help="directory for strict_eval_tuned.json/.md",
    )
    args = parser.parse_args(argv)

    dataset = generate_dataset(seed=args.seed)
    choice_candidate = build_choice_candidate(dataset, seed=args.seed)
    tuned = tune_on_validation(dataset, choice_candidate, budget=args.budget)

    weights_path = Path(args.weights_out)
    _write_weights(weights_path, tuned)

    # Validation diagnostics (reported for interpretability only).
    _, validation, store = _validation_split(dataset)
    validation_report = {
        "baseline": _validation_metrics(
            store, validation, dict(DEFAULT_WEIGHTS)
        ),
        "choice_candidate": _validation_metrics(
            store, validation, choice_candidate
        ),
        "tuned": _validation_metrics(store, validation, tuned),
    }

    result = evaluate_candidate(tuned, seeds=args.seeds, k=args.k)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strict_eval_tuned.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "strict_eval_tuned.md").write_text(
        _render_markdown(result, tuned, "choice-tuned"),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "choice_candidate": choice_candidate,
                "tuned_weights": tuned,
                "budget": args.budget,
                "seeds": result["seeds"],
                "k": result["k"],
                "candidate_source": result["candidate_source"],
                "baseline_equals_candidate": result[
                    "baseline_equals_candidate"
                ],
                "target_met": _target_met(result),
                "primary_deltas": _primary_deltas(result),
                "validation": validation_report,
                "constraint_violations": result["constraint_violations"],
                "cold_start": {
                    "available": result["cold_start"]["available"],
                    "reason": result["cold_start"]["reason"],
                    "queries": result["cold_start"]["queries"],
                    "measured": result["cold_start"]["measured"],
                },
                "calibration": {
                    "available": result["calibration"]["available"],
                    "reason": result["calibration"]["reason"],
                    "brier": result["calibration"]["brier"],
                    "raw_brier": result["calibration"]["raw_brier"],
                },
                "latency_p50_ms": result["latency_p50_ms"],
                "latency_p95_ms": result["latency_p95_ms"],
                "reports": [
                    str(weights_path),
                    str(report_dir / "strict_eval_tuned.json"),
                    str(report_dir / "strict_eval_tuned.md"),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
