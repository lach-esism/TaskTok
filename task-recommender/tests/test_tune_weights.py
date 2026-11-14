"""Tests for the choice-learned weight candidate and validation-only tuning."""

import json

from app.config import DEFAULT_WEIGHTS
from app.data.synthetic import generate_dataset
from app.learning.weights import (
    KEYS,
    MIN_WEIGHT,
    REPUTATION_MAX,
    REPUTATION_MIN,
    validate_weights,
)
from scripts import tune_weights as tw


def _assert_valid(weights: dict) -> None:
    assert set(weights) == set(KEYS)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    validate_weights(weights)  # raises on any simplex-constraint violation
    assert all(value >= MIN_WEIGHT - 1e-9 for value in weights.values())
    assert (
        REPUTATION_MIN - 1e-9
        <= weights["reputation"]
        <= REPUTATION_MAX + 1e-9
    )


def test_build_choice_candidate_is_valid_and_deterministic(dataset):
    first = tw.build_choice_candidate(dataset, seed=42)
    second = tw.build_choice_candidate(dataset, seed=42)
    _assert_valid(first)
    assert first == second
    assert first != dict(DEFAULT_WEIGHTS)


def test_tune_on_validation_returns_valid_weights(dataset):
    base = tw.build_choice_candidate(dataset, seed=42)
    tuned = tw.tune_on_validation(dataset, base, budget=6)
    _assert_valid(tuned)


def test_tune_on_validation_is_deterministic(dataset):
    base = tw.build_choice_candidate(dataset, seed=42)
    first = tw.tune_on_validation(dataset, base, budget=6)
    second = tw.tune_on_validation(dataset, base, budget=6)
    assert first == second


def test_validation_split_holds_out_last_20_percent_and_excludes_test(dataset):
    fit, validation, store = tw._validation_split(dataset)
    assert len(fit) + len(validation) == len(dataset.train)
    assert len(validation) == int(len(dataset.train) * tw.VALIDATION_FRACTION)

    test_ids = {item.assignment_id for item in dataset.test}
    validation_ids = {item.assignment_id for item in validation}
    fit_ids = {item.assignment_id for item in fit}

    store_assignment_ids = {item.assignment_id for item in store.assignments}
    assert store_assignment_ids == fit_ids
    assert store_assignment_ids.isdisjoint(test_ids)
    assert store_assignment_ids.isdisjoint(validation_ids)

    store_feedback_ids = {item.assignment_id for item in store.feedback}
    assert store_feedback_ids.isdisjoint(test_ids)
    assert store_feedback_ids.isdisjoint(validation_ids)

    def event_assignment_ids(records):
        return {
            (item.metadata or {}).get("assignment_id") for item in records
        }

    store_event_ids = event_assignment_ids(store.events)
    assert store_event_ids.isdisjoint(test_ids)
    assert store_event_ids.isdisjoint(validation_ids)

    store_impression_ids = event_assignment_ids(store.impressions)
    assert store_impression_ids.isdisjoint(test_ids)
    assert store_impression_ids.isdisjoint(validation_ids)


def test_tune_on_validation_never_scores_test_assignments(dataset, monkeypatch):
    original = tw._validation_metrics
    test_ids = {item.assignment_id for item in dataset.test}
    train_ids = {item.assignment_id for item in dataset.train}
    calls = []

    def counting(store, validation_assignments, weights):
        scored_ids = {item.assignment_id for item in validation_assignments}
        assert scored_ids.isdisjoint(test_ids)
        assert scored_ids <= train_ids
        calls.append(1)
        return original(store, validation_assignments, weights)

    monkeypatch.setattr(tw, "_validation_metrics", counting)
    base = tw.build_choice_candidate(dataset, seed=42)
    tw.tune_on_validation(dataset, base, budget=6)

    # One baseline call plus at most `budget` candidate evaluations.
    assert calls
    assert len(calls) <= 6 + 1


def test_tune_on_validation_respects_budget(dataset, monkeypatch):
    original = tw._validation_metrics
    budget = 5

    def counting(store, validation_assignments, weights):
        counting.calls += 1
        return original(store, validation_assignments, weights)

    counting.calls = 0
    monkeypatch.setattr(tw, "_validation_metrics", counting)
    base = tw.build_choice_candidate(dataset, seed=42)
    tw.tune_on_validation(dataset, base, budget=budget)
    assert counting.calls <= budget + 1


def test_tuning_services_use_serving_parity_components(dataset, monkeypatch):
    """Both choice-feature and validation services get the serving components."""
    recorded: list[dict] = []
    real_service = tw.RecommendationService

    class RecordingService(real_service):
        def __init__(self, *args, **kwargs):
            recorded.append(dict(kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(tw, "RecommendationService", RecordingService)

    tw.build_choice_candidate(dataset, seed=42)
    assert recorded
    assert all(
        item.get("semantic_matcher") is not None for item in recorded
    )
    assert all(
        item.get("acceptance_model") is not None for item in recorded
    )

    recorded.clear()
    _, validation, store = tw._validation_split(dataset)
    tw._validation_metrics(store, validation, dict(DEFAULT_WEIGHTS))
    assert recorded
    assert all(
        item.get("semantic_matcher") is not None for item in recorded
    )
    assert all(
        item.get("acceptance_model") is not None for item in recorded
    )


def test_write_weights_round_trips_seven_keys(tmp_path):
    small = generate_dataset(
        n_workers=12, n_tasks=30, n_assignments=80, seed=42, n_new_users=0,
    )
    weights = tw.build_choice_candidate(small, seed=42)
    path = tmp_path / "weights_choice.json"
    tw._write_weights(path, weights)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == set(KEYS)
    _assert_valid(payload)
