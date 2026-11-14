import json

from app.evaluation_strict import build_eval_store, task_to_workers_metrics
from app.features import candidate_features  # noqa: F401  (import smoke)
from app.service import RecommendationService


def test_build_eval_store_excludes_test_feedback(dataset):
    store = build_eval_store(dataset)
    test_ids = {item.feedback_id for item in dataset.test_feedback}
    store_ids = {item.feedback_id for item in store.feedback}
    assert test_ids.isdisjoint(store_ids)
    assert len(store.assignments) == len(dataset.train)


def test_task_to_workers_metrics_are_bounded(dataset):
    store = build_eval_store(dataset)
    service = RecommendationService(store)
    metrics = task_to_workers_metrics(
        store, service, dataset.test[:20], k=10, candidate_mode="all",
    )
    assert metrics["queries"] > 0
    assert 0.0 <= metrics["hr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0
    assert 0.0 <= metrics["mrr"] <= 1.0


def test_exposed_mode_resolves_by_assignment_id(dataset):
    """Two impressions sharing query_id/created_at must resolve by assignment_id."""
    from app.domain import Impression

    store = build_eval_store(dataset)
    assignment = dataset.test[0]
    first = Impression(
        request_id="r1", query_id=assignment.task_id, candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": "other"},
    )
    second = Impression(
        request_id="r2", query_id=assignment.task_id, candidate_ids=["w2"],
        propensities={"w2": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": assignment.assignment_id},
    )
    store.impressions = [first, second]
    # The helper should select `second`; assert through the public metrics path.
    metrics = task_to_workers_metrics(
        store, RecommendationService(store), [assignment], k=10,
        candidate_mode="exposed",
    )
    assert metrics["queries"] == 1


def test_exposed_mode_ranks_the_resolved_candidate_set(dataset):
    """The assignment-id match (not the tied impression) defines the candidates."""
    from app.domain import Impression

    store = build_eval_store(dataset)
    assignment = dataset.test[0]
    tied_other = Impression(
        request_id="r1", query_id=assignment.task_id, candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": "other"},
    )
    tied_ours = Impression(
        request_id="r2", query_id=assignment.task_id,
        candidate_ids=[assignment.worker_id],
        propensities={assignment.worker_id: 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": assignment.assignment_id},
    )
    store.impressions = [tied_other, tied_ours]
    metrics = task_to_workers_metrics(
        store, RecommendationService(store), [assignment], k=10,
        candidate_mode="exposed",
    )
    assert metrics["queries"] == 1
    assert metrics["hr"] == 1.0


def test_exposed_mode_accepts_test_impressions_without_store_mutation(dataset):
    """Evaluation-only impressions must not contaminate the train-only store."""
    store = build_eval_store(dataset)
    before = list(store.impressions)
    train_ids = {item.request_id for item in dataset.train_impressions}
    test_ids = {item.request_id for item in dataset.test_impressions}

    metrics = task_to_workers_metrics(
        store, RecommendationService(store), dataset.test, k=10,
        candidate_mode="exposed", impressions=dataset.test_impressions,
    )

    assert metrics["queries"] == len(dataset.test)
    assert metrics["hr"] == 1.0
    assert store.impressions == before
    assert {item.request_id for item in store.impressions} == train_ids
    assert {item.request_id for item in store.impressions}.isdisjoint(
        test_ids
    )


from app.evaluation_strict import paired_bootstrap, worker_to_tasks_metrics


def test_worker_to_tasks_metrics_are_bounded(dataset):
    store = build_eval_store(dataset)
    service = RecommendationService(store)
    metrics = worker_to_tasks_metrics(store, service, dataset.test[:20], k=10)
    assert metrics["queries"] > 0
    assert 0.0 <= metrics["hr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0


def test_paired_bootstrap_detects_positive_delta():
    result = paired_bootstrap([0.1] * 50, n_boot=200, seed=42)
    assert result["mean"] == 0.1
    assert result["low"] > 0.0
    assert result["high"] >= result["low"]
    assert 0.0 <= result["p_value"] <= 1.0


def test_worker_to_tasks_exposed_uses_test_impressions_without_mutation(
    dataset,
):
    """Evaluation-only exposures must not contaminate the train-only store."""
    store = build_eval_store(dataset)
    before = list(store.impressions)
    train_ids = {item.request_id for item in dataset.train_impressions}
    test_ids = {item.request_id for item in dataset.test_impressions}
    assignments = dataset.test[:20]

    metrics = worker_to_tasks_metrics(
        store,
        RecommendationService(store),
        assignments,
        k=10,
        candidate_mode="exposed",
        impressions=dataset.test_impressions,
    )

    assert metrics["queries"] == len(assignments)
    assert 0.0 <= metrics["hr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0
    assert store.impressions == before
    assert {item.request_id for item in store.impressions} == train_ids
    assert {item.request_id for item in store.impressions}.isdisjoint(
        test_ids
    )


from dataclasses import replace

import pytest

from app.config import DEFAULT_WEIGHTS
from app.evaluation_strict import evaluate_strict


def _feedback_with_both_classes(dataset):
    """The small fixture generates only 4-5 ratings; force a valid mix."""
    feedback = [
        replace(item, overall_rating=3 if index % 4 == 0 else 5)
        for index, item in enumerate(dataset.feedback)
    ]
    return replace(dataset, feedback=feedback)


def test_evaluate_strict_reports_test_calibration(dataset):
    result = evaluate_strict(
        _feedback_with_both_classes(dataset),
        dict(DEFAULT_WEIGHTS),
        k=10,
        seeds=(),
    )
    calibration = result["calibration"]

    assert calibration["available"] is True
    assert calibration["reason"] is None
    assert calibration["label"] == "rating>=4"
    assert calibration["train_samples"] >= 10
    assert calibration["test_samples"] > 0
    assert 0.0 <= calibration["brier"] <= 1.0
    assert 0.0 <= calibration["raw_brier"] <= 1.0
    assert calibration["a"] is not None
    assert calibration["b"] is not None

    bins = calibration["reliability_bins"]
    assert len(bins) == 5
    assert sum(item["count"] for item in bins) == calibration[
        "test_samples"
    ]
    for item in bins:
        if item["count"] == 0:
            assert item["mean_predicted"] is None
            assert item["observed_rate"] is None
        else:
            assert 0.0 <= item["mean_predicted"] <= 1.0
            assert 0.0 <= item["observed_rate"] <= 1.0


def test_evaluate_strict_marks_calibration_unavailable_without_feedback(
    dataset,
):
    empty = replace(dataset, feedback=[])
    result = evaluate_strict(
        empty, dict(DEFAULT_WEIGHTS), k=10, seeds=()
    )
    calibration = result["calibration"]

    assert calibration["available"] is False
    assert calibration["reason"]
    assert calibration["train_samples"] == 0
    assert calibration["test_samples"] == 0
    assert calibration["brier"] is None
    assert calibration["raw_brier"] is None
    assert calibration["a"] is None
    assert calibration["b"] is None
    assert calibration["reliability_bins"] == []


def test_cli_render_markdown_includes_calibration(dataset):
    from scripts import evaluate_strict as cli

    result = evaluate_strict(
        _feedback_with_both_classes(dataset),
        dict(DEFAULT_WEIGHTS),
        k=10,
        seeds=(),
    )
    text = cli._render_markdown(result, dict(DEFAULT_WEIGHTS), "override")

    assert "## Calibration: P(rating>=4)" in text
    assert "Brier (calibrated):" in text
    assert "Brier (raw score):" in text
    assert "Reliability bins (test):" in text
    assert "- available: true" in text


def test_cli_rejects_invalid_candidate_weights(tmp_path):
    from scripts import evaluate_strict as cli

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        cli._read_weight_payload(empty)

    partial = tmp_path / "partial.json"
    partial.write_text(
        '{"reputation": 0.5, "skill": 0.5}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="seven canonical keys"):
        cli._read_weight_payload(partial)

    extra = dict(DEFAULT_WEIGHTS)
    extra["mystery"] = 0.1
    extra["skill"] = extra["skill"] - 0.1
    extra_path = tmp_path / "extra.json"
    extra_path.write_text(json.dumps(extra), encoding="utf-8")
    with pytest.raises(ValueError, match="seven canonical keys"):
        cli._read_weight_payload(extra_path)

    negative = dict(DEFAULT_WEIGHTS)
    negative["reputation"] = -0.01
    negative["skill"] = negative["skill"] + 0.01
    negative_path = tmp_path / "negative.json"
    negative_path.write_text(json.dumps(negative), encoding="utf-8")
    with pytest.raises(ValueError, match="non-negative"):
        cli._read_weight_payload(negative_path)

    bad_sum = dict(DEFAULT_WEIGHTS)
    bad_sum["reputation"] = 0.01
    bad_sum_path = tmp_path / "bad_sum.json"
    bad_sum_path.write_text(json.dumps(bad_sum), encoding="utf-8")
    with pytest.raises(ValueError, match="sum to 1.0"):
        cli._read_weight_payload(bad_sum_path)

    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(
        json.dumps({"version": "v0007", "weights": DEFAULT_WEIGHTS}),
        encoding="utf-8",
    )
    assert cli._read_weight_payload(wrapped) == dict(DEFAULT_WEIGHTS)


def test_evaluate_strict_identity_uses_effective_weights(dataset):
    same = evaluate_strict(
        dataset, dict(DEFAULT_WEIGHTS), k=10, seeds=()
    )
    assert same["baseline_equals_candidate"] is True

    near = dict(DEFAULT_WEIGHTS)
    near["reputation"] += 5e-10
    near["skill"] -= 5e-10
    near_result = evaluate_strict(dataset, near, k=10, seeds=())
    assert near_result["baseline_equals_candidate"] is True

    different = dict(DEFAULT_WEIGHTS)
    different["reputation"] += 0.01
    different["skill"] -= 0.01
    different_result = evaluate_strict(
        dataset, different, k=10, seeds=()
    )
    assert different_result["baseline_equals_candidate"] is False


def test_evaluate_strict_reports_cold_start_machine_fields(dataset):
    result = evaluate_strict(
        dataset, dict(DEFAULT_WEIGHTS), k=10, seeds=()
    )
    cold = result["cold_start"]

    assert isinstance(cold["queries"], int)
    assert cold["queries"] >= 0
    assert cold["measured"] == (
        bool(cold["available"]) and cold["queries"] > 0
    )


def _target_result(
    *,
    equal: bool = False,
    task_ndcg: tuple[float, float, float, float] = (0.10, 0.10, 0.05, 0.15),
    task_hr: tuple[float, float, float, float] = (0.50, 0.50, 0.40, 0.60),
    worker_ndcg: tuple[float, float, float, float] = (0.10, 0.10, 0.05, 0.15),
    worker_hr: tuple[float, float, float, float] = (0.50, 0.50, 0.40, 0.60),
    cold_available: bool = False,
    cold_queries: int = 0,
) -> dict:
    """Build the minimal result consumed by the target-check renderer."""

    def delta(values: tuple[float, float, float, float]) -> dict:
        mean, low, high, p_value = values
        return {"mean": mean, "low": low, "high": high, "p_value": p_value}

    def metrics(ndcg: float, hr: float) -> dict:
        return {"ndcg": ndcg, "hr": hr, "mrr": 0.0, "queries": 10}

    return {
        "baseline_equals_candidate": equal,
        "baselines": {
            "task_to_workers": metrics(0.10, 0.50),
            "worker_to_tasks": metrics(0.10, 0.50),
        },
        "candidate": {
            "task_to_workers": metrics(task_ndcg[1] + 0.10, task_hr[1] + 0.50),
            "worker_to_tasks": metrics(
                worker_ndcg[1] + 0.10, worker_hr[1] + 0.50
            ),
        },
        "deltas": {
            "task_to_workers": {
                "ndcg": delta(task_ndcg),
                "hr": delta(task_hr),
            },
            "worker_to_tasks": {
                "ndcg": delta(worker_ndcg),
                "hr": delta(worker_hr),
            },
        },
        "constraint_violations": 0,
        "cold_start": {
            "available": cold_available,
            "reason": None,
            "queries": cold_queries,
            "measured": bool(cold_available and cold_queries > 0),
        },
        "calibration": {"available": True},
    }


def test_target_check_reports_met():
    from scripts.evaluate_strict import _target_lines

    # task_to_workers NDCG: baseline 0.10 -> candidate 0.20 (+100%),
    # CI low > 0; worker_to_tasks deltas are non-negative.
    result = _target_result(
        task_ndcg=(0.10, 0.05, 0.15, 0.01),
        task_hr=(0.10, 0.05, 0.15, 0.01),
        worker_ndcg=(0.0, 0.0, 0.0, 1.0),
        worker_hr=(0.0, 0.0, 0.0, 1.0),
    )
    text = "\n".join(_target_lines(result))
    assert "- status: MET" in text


def test_target_check_reports_not_met():
    from scripts.evaluate_strict import _target_lines

    result = _target_result(
        task_ndcg=(0.0, -0.001, 0.001, 1.0),
        task_hr=(0.0, -0.001, 0.001, 1.0),
        worker_ndcg=(0.0, -0.001, 0.001, 1.0),
        worker_hr=(0.0, -0.001, 0.001, 1.0),
    )
    text = "\n".join(_target_lines(result))
    assert "- status: NOT MET" in text
    assert "- gap:" in text


def test_target_check_not_met_when_other_direction_deteriorates():
    from scripts.evaluate_strict import _target_lines

    result = _target_result(
        task_ndcg=(0.10, 0.05, 0.15, 0.01),
        task_hr=(0.10, 0.05, 0.15, 0.01),
        worker_ndcg=(-0.001, -0.002, 0.0, 1.0),
        worker_hr=(-0.001, -0.002, 0.0, 1.0),
    )
    text = "\n".join(_target_lines(result))
    assert "- status: NOT MET" in text


def test_target_check_reports_na_for_identity():
    from scripts.evaluate_strict import _target_lines

    result = _target_result(equal=True)
    text = "\n".join(_target_lines(result))
    assert "n/a (candidate weights are identical" in text
    assert "- status: MET" not in text
    assert "- status: NOT MET" not in text


def test_build_serving_components_fits_train_only_store(dataset):
    from app.evaluation_strict import build_eval_store
    from app.serving import build_serving_components

    store = build_eval_store(dataset)
    semantic_matcher, acceptance_model = build_serving_components(store)
    assert semantic_matcher is not None
    assert semantic_matcher.is_fitted
    assert acceptance_model is not None
    assert acceptance_model.is_fitted
    # The train-only store has no test events to fit on.
    assert {item.event_id for item in store.events} == {
        item.event_id for item in dataset.train_events
    }


def test_evaluate_strict_injects_serving_components(dataset, monkeypatch):
    """Baseline and candidate services must receive the serving components."""
    from app import evaluation_strict as strict

    recorded: list[dict] = []
    real_service = strict.RecommendationService

    class RecordingService(real_service):
        def __init__(self, *args, **kwargs):
            recorded.append(dict(kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(strict, "RecommendationService", RecordingService)
    result = strict.evaluate_strict(
        dataset, dict(DEFAULT_WEIGHTS), k=10, seeds=()
    )

    assert result["serving_features"]["parity"] == "serving"
    assert result["serving_features"]["semantic_matcher"] is True
    assert result["serving_features"]["acceptance_model"] is True
    assert recorded
    assert all(
        item.get("semantic_matcher") is not None for item in recorded
    )
    assert all(
        item.get("acceptance_model") is not None for item in recorded
    )


def test_evaluate_strict_marks_endpoint_latency_na(dataset):
    from app.evaluation_strict import evaluate_strict

    candidate = dict(DEFAULT_WEIGHTS)
    candidate["reputation"] += 0.01
    candidate["skill"] -= 0.01
    result = evaluate_strict(
        dataset, candidate, k=10, seeds=()
    )
    assert "scoring_latency_p50_ms" in result
    assert "scoring_latency_p95_ms" in result
    assert result["endpoint_latency"]["available"] is False
    assert result["endpoint_latency"]["guardrail"] == "N/A"

    from scripts import evaluate_strict as cli

    text = cli._render_markdown(result, candidate, "override")
    assert "NOT HTTP endpoint latency" in text
    assert "Latency guardrail: N/A" in text


def test_cold_start_zero_queries_renders_na(dataset):
    from scripts import evaluate_strict as cli

    different = dict(DEFAULT_WEIGHTS)
    different["reputation"] += 0.01
    different["skill"] -= 0.01
    result = evaluate_strict(dataset, different, k=10, seeds=())
    result["cold_start"].update(
        {
            "available": False,
            "reason": "no cold workers",
            "queries": 0,
            "measured": False,
        }
    )
    text = cli._render_markdown(result, different, "override")

    assert "- available: false" in text
    assert "- queries: 0" in text
    assert "- measured: false" in text
    assert "n/a (cold-start subset not measured)" in text
    assert "- Cold start: N/A (not measured) (queries=0)" in text
