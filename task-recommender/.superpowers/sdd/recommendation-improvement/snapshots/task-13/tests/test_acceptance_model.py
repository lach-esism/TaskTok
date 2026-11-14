from datetime import datetime, timezone

import pytest

from app.domain import Task, Worker
from app.learning.acceptance import FEATURE_KEYS, AcceptanceModel, accept_features

POSITIVE = {
    "skill_match": 1.0,
    "pay_fit": 0.9,
    "category_match": 1.0,
    "load_ratio": 0.1,
    "region_match": 1.0,
    "historical_accept_rate": 0.9,
}
NEGATIVE = {
    "skill_match": 0.1,
    "pay_fit": 0.1,
    "category_match": 0.0,
    "load_ratio": 0.9,
    "region_match": 0.3,
    "historical_accept_rate": 0.1,
}


def test_acceptance_model_learns_direction():
    positive = {"skill_match": 1.0, "pay_fit": 0.9, "category_match": 1.0, "load_ratio": 0.1, "region_match": 1.0, "historical_accept_rate": 0.9}
    negative = {"skill_match": 0.1, "pay_fit": 0.1, "category_match": 0.0, "load_ratio": 0.9, "region_match": 0.3, "historical_accept_rate": 0.1}
    samples = [(positive, 1)] * 30 + [(negative, 0)] * 30
    model = AcceptanceModel().fit(samples)
    assert model.is_fitted
    assert model.predict(positive) > model.predict(negative)
    assert 0.0 <= model.predict(positive) <= 1.0


def test_cold_start_returns_prior():
    model = AcceptanceModel(prior=0.42)
    assert model.predict({"skill_match": 1.0}) == pytest.approx(0.42)


def test_fewer_than_twenty_samples_stays_unfitted():
    samples = [(POSITIVE, 1)] * 10 + [(NEGATIVE, 0)] * 9
    model = AcceptanceModel(prior=0.37).fit(samples)

    assert not model.is_fitted
    assert model.predict(POSITIVE) == pytest.approx(0.37)


def test_single_class_events_stay_unfitted():
    model = AcceptanceModel(prior=0.6).fit([(POSITIVE, 1)] * 30)

    assert not model.is_fitted
    assert model.predict(NEGATIVE) == pytest.approx(0.6)


def test_fit_returns_self_and_accepts_sample_weight():
    samples = [(POSITIVE, 1)] * 30 + [(NEGATIVE, 0)] * 30
    model = AcceptanceModel()

    assert model.fit(samples, sample_weight=[1.0] * len(samples)) is model
    assert model.is_fitted


def test_predict_ignores_unknown_keys_and_defaults_missing_to_zero():
    model = AcceptanceModel().fit([(POSITIVE, 1)] * 30 + [(NEGATIVE, 0)] * 30)

    assert model.predict({**POSITIVE, "unknown_feature": 99.0}) == pytest.approx(
        model.predict(POSITIVE)
    )
    sparse = model.predict({"skill_match": 1.0})
    assert 0.0 <= sparse <= 1.0


def _make_worker(
    *,
    preferred_categories: dict[str, float] | None = None,
    current_load_hours: float = 10.0,
    capacity_hours: float = 40.0,
) -> Worker:
    return Worker(
        worker_id="w1",
        name="Worker",
        skills={},
        specialties={},
        level=3,
        capacity_hours=capacity_hours,
        current_load_hours=current_load_hours,
        preferred_categories=preferred_categories or {},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
    )


def _make_task(
    *, category: str = "software_dev", estimated_hours: float = 10.0
) -> Task:
    return Task(
        task_id="t1",
        customer_id="c1",
        title="Task",
        category=category,
        required_skills={},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=estimated_hours,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        region="CN",
        remote_ok=True,
    )


def test_accept_features_returns_fixed_order_and_values():
    worker = _make_worker(
        preferred_categories={"software_dev": 0.8},
        current_load_hours=10.0,
        capacity_hours=40.0,
    )
    task = _make_task(estimated_hours=10.0)

    features = accept_features(
        worker, task, skill=0.7, pay_fit=0.6, region_match=0.8,
        historical_accept_rate=0.75,
    )

    assert list(features) == list(FEATURE_KEYS)
    assert features == pytest.approx(
        {
            "category_match": 0.8,
            "skill_match": 0.7,
            "pay_fit": 0.6,
            "load_ratio": 0.5,
            "region_match": 0.8,
            "historical_accept_rate": 0.75,
        }
    )


def test_accept_features_defaults_missing_category_to_zero():
    worker = _make_worker(preferred_categories={"writing": 0.9})
    features = accept_features(
        worker, _make_task(category="software_dev"), skill=0.5, pay_fit=0.5,
        region_match=1.0, historical_accept_rate=0.5,
    )

    assert features["category_match"] == 0.0


def test_accept_features_clamps_load_ratio():
    overloaded = _make_worker(current_load_hours=35.0, capacity_hours=40.0)
    features = accept_features(
        overloaded, _make_task(estimated_hours=20.0), skill=0.5, pay_fit=0.5,
        region_match=1.0, historical_accept_rate=0.5,
    )
    assert features["load_ratio"] == pytest.approx(1.0)

    zero_capacity = _make_worker(current_load_hours=0.0, capacity_hours=0.0)
    features = accept_features(
        zero_capacity, _make_task(estimated_hours=0.0), skill=0.5, pay_fit=0.5,
        region_match=1.0, historical_accept_rate=0.5,
    )
    assert features["load_ratio"] == pytest.approx(0.0)
