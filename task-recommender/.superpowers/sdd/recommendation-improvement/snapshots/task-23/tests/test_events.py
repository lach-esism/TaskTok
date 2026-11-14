from datetime import datetime, timedelta, timezone

from app.data.store import Store
from app.domain import (
    Assignment, Customer, Dataset, Feedback, Impression, RecommendationEvent,
    Task, Worker,
)

NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)


def test_impression_fields():
    impression = Impression(
        request_id="r1", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
    )
    assert impression.request_id == "r1"
    assert impression.candidate_ids == ["w1"]


def _worker(worker_id: str = "w1") -> Worker:
    return Worker(
        worker_id=worker_id,
        name=worker_id,
        skills={"python": 4},
        specialties={"software_dev": 3},
        level=3,
        capacity_hours=40,
        current_load_hours=0,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
    )


def test_new_worker_and_task_fields_have_defaults():
    worker = _worker()
    assert worker.expected_pay == 0.0
    assert worker.certifications == {}
    assert worker.communication_ratings == []
    task = Task(
        task_id="t1", customer_id="c1", title="T", category="software_dev",
        required_skills={}, required_level=1, difficulty=3, priority=3,
        estimated_hours=2, deadline=NOW, region="CN", remote_ok=True,
    )
    assert task.required_skill_weights == {}


def test_store_reference_time_includes_events_and_impressions():
    worker = _worker()
    event = RecommendationEvent(
        event_id="e1", request_id="r1", user_id="c1", role="customer",
        task_id="t1", candidate_id="w1", candidate_type="worker",
        rank=1, score=0.9, propensity=0.5, weights_version="v0000",
        action="click", created_at=NOW + timedelta(days=2),
    )
    impression = Impression(
        request_id="r1", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW + timedelta(days=1),
    )
    store = Store(
        workers=[worker], customers=[], tasks=[], assignments=[], feedback=[],
        events=[event], impressions=[impression],
    )
    assert store.reference_time == event.created_at
    assert store.events_for("r1") == [event]
    assert store.events_for_user("c1") == [event]

    later_impression = Impression(
        request_id="r2", query_id="t2", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW + timedelta(days=3),
    )
    store.impressions.append(later_impression)
    assert store.reference_time == later_impression.created_at


def test_recent_impression_counts_window():
    from app.domain import Impression

    worker = _worker()
    old = Impression(
        request_id="r_old", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW - timedelta(days=60),
    )
    new = Impression(
        request_id="r_new", query_id="t2", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW - timedelta(days=5),
    )
    store = Store(
        workers=[worker], customers=[], tasks=[], assignments=[], feedback=[],
        impressions=[old, new],
    )
    assert store.recent_impression_counts(NOW, days=30)["w1"] == 1


def test_prior_collaboration_counts_only_completed_before():
    worker = _worker()
    customer = Customer(customer_id="c1", name="C", region="CN")
    old = Assignment(
        assignment_id="a1", task_id="t1", worker_id="w1", customer_id="c1",
        status="completed", created_at=NOW - timedelta(days=10),
    )
    new = Assignment(
        assignment_id="a2", task_id="t2", worker_id="w1", customer_id="c1",
        status="completed", created_at=NOW + timedelta(days=10),
    )
    cancelled = Assignment(
        assignment_id="a3", task_id="t3", worker_id="w1", customer_id="c1",
        status="cancelled", created_at=NOW - timedelta(days=5),
    )
    store = Store(
        workers=[worker], customers=[customer], tasks=[],
        assignments=[old, new, cancelled], feedback=[],
    )
    assert store.prior_collaboration_count("c1", "w1", before=NOW) == 1


def _split_dataset() -> Dataset:
    """Train and test assignments share the boundary timestamp on purpose."""
    worker = _worker()
    train_assignment = Assignment(
        assignment_id="a_train", task_id="t1", worker_id="w1",
        customer_id="c1", status="completed", created_at=NOW,
    )
    test_assignment = Assignment(
        assignment_id="a_test", task_id="t2", worker_id="w1",
        customer_id="c1", status="completed", created_at=NOW,
    )
    feedback = [
        Feedback(
            feedback_id="f_train", assignment_id="a_train", worker_id="w1",
            task_id="t1", overall_rating=5, created_at=NOW,
        ),
        Feedback(
            feedback_id="f_test", assignment_id="a_test", worker_id="w1",
            task_id="t2", overall_rating=3, created_at=NOW,
        ),
    ]
    impressions = [
        Impression(
            request_id="r_train", query_id="t1", candidate_ids=["w1"],
            propensities={"w1": 1.0}, policy="test", created_at=NOW,
            metadata={"assignment_id": "a_train"},
        ),
        Impression(
            request_id="r_test", query_id="t2", candidate_ids=["w1"],
            propensities={"w1": 1.0}, policy="test", created_at=NOW,
            metadata={"assignment_id": "a_test"},
        ),
    ]
    events = [
        RecommendationEvent(
            event_id="e_train", request_id="r_train", user_id="c1",
            role="customer", task_id="t1", candidate_id="w1",
            candidate_type="worker", rank=1, score=0.9, propensity=1.0,
            weights_version="v0000", action="accept", created_at=NOW,
            metadata={"assignment_id": "a_train"},
        ),
        RecommendationEvent(
            event_id="e_test", request_id="r_test", user_id="c1",
            role="customer", task_id="t2", candidate_id="w1",
            candidate_type="worker", rank=1, score=0.8, propensity=1.0,
            weights_version="v0000", action="accept", created_at=NOW,
            metadata={"assignment_id": "a_test"},
        ),
    ]
    return Dataset(
        workers=[worker],
        customers=[Customer(customer_id="c1", name="C", region="CN")],
        tasks=[],
        assignments=[train_assignment, test_assignment],
        feedback=feedback,
        train=[train_assignment],
        test=[test_assignment],
        events=events,
        impressions=impressions,
    )


def test_dataset_split_prefers_assignment_metadata_on_timestamp_ties():
    dataset = _split_dataset()
    assert dataset.split_time == NOW
    assert [event.event_id for event in dataset.train_events] == ["e_train"]
    assert [event.event_id for event in dataset.test_events] == ["e_test"]
    assert [
        impression.request_id for impression in dataset.train_impressions
    ] == ["r_train"]
    assert [
        impression.request_id for impression in dataset.test_impressions
    ] == ["r_test"]


def test_dataset_event_impression_and_feedback_splits_are_disjoint():
    dataset = _split_dataset()

    train_event_ids = {event.event_id for event in dataset.train_events}
    test_event_ids = {event.event_id for event in dataset.test_events}
    assert train_event_ids.isdisjoint(test_event_ids)
    assert len(train_event_ids) + len(test_event_ids) == len(dataset.events)

    train_impression_ids = {
        impression.request_id for impression in dataset.train_impressions
    }
    test_impression_ids = {
        impression.request_id for impression in dataset.test_impressions
    }
    assert train_impression_ids.isdisjoint(test_impression_ids)
    assert (
        len(train_impression_ids) + len(test_impression_ids)
        == len(dataset.impressions)
    )

    train_feedback_ids = {
        item.feedback_id for item in dataset.train_feedback
    }
    test_feedback_ids = {
        item.feedback_id for item in dataset.test_feedback
    }
    assert train_feedback_ids.isdisjoint(test_feedback_ids)
    assert (
        len(train_feedback_ids) + len(test_feedback_ids) == len(dataset.feedback)
    )


def test_dataset_split_without_metadata_falls_back_to_timestamps():
    worker = _worker()
    train_assignment = Assignment(
        assignment_id="a_train", task_id="t1", worker_id="w1",
        customer_id="c1", status="completed",
        created_at=NOW - timedelta(days=1),
    )
    test_assignment = Assignment(
        assignment_id="a_test", task_id="t2", worker_id="w1",
        customer_id="c1", status="completed",
        created_at=NOW + timedelta(days=1),
    )
    early_event = RecommendationEvent(
        event_id="e_early", request_id="r1", user_id="c1", role="customer",
        task_id="t1", candidate_id="w1", candidate_type="worker",
        rank=1, score=0.9, propensity=1.0, weights_version="v0000",
        action="accept", created_at=NOW - timedelta(days=2),
    )
    late_event = RecommendationEvent(
        event_id="e_late", request_id="r2", user_id="c1", role="customer",
        task_id="t2", candidate_id="w1", candidate_type="worker",
        rank=1, score=0.9, propensity=1.0, weights_version="v0000",
        action="accept", created_at=NOW + timedelta(hours=1),
    )
    dataset = Dataset(
        workers=[worker], customers=[], tasks=[],
        assignments=[train_assignment, test_assignment], feedback=[],
        train=[train_assignment], test=[test_assignment],
        events=[early_event, late_event],
    )
    assert [event.event_id for event in dataset.train_events] == ["e_early"]
    assert [event.event_id for event in dataset.test_events] == ["e_late"]


def test_dataset_split_time_is_timezone_aware_with_empty_train():
    dataset = Dataset(
        workers=[], customers=[], tasks=[], assignments=[], feedback=[],
        train=[], test=[],
    )
    assert dataset.split_time.tzinfo is not None
    assert dataset.train_events == []
    assert dataset.test_events == []


def test_dataset_split_time_normalizes_naive_train_timestamps():
    assignment = Assignment(
        assignment_id="a1", task_id="t1", worker_id="w1", customer_id="c1",
        status="completed", created_at=datetime(2026, 1, 10),
    )
    dataset = Dataset(
        workers=[], customers=[], tasks=[], assignments=[assignment],
        feedback=[], train=[assignment], test=[],
    )
    assert dataset.split_time.tzinfo is not None


import json

import pytest
from app.events import EventService


def test_event_service_records_and_counts(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store, persist_dir=tmp_path)
    service.record_impression(
        "r1", "t1", ["w1", "w2"], {"w1": 0.9, "w2": 0.1}, "test",
    )
    service.record_event("r1", "w1", "click", user_id="c1")
    service.record_event("r1", "w1", "accept", user_id="c1")
    metrics = service.funnel_metrics()
    assert metrics["impressions"] == 1
    assert metrics["candidates"] == 2
    assert metrics["clicks"] == 1
    assert metrics["accepts"] == 1
    assert metrics["click_rate"] == pytest.approx(0.5)
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "impressions.jsonl").exists()


def test_event_service_rejects_duplicates_and_unknowns(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store)
    service.record_impression("r1", "t1", ["w1"], {"w1": 1.0}, "test")
    service.record_event("r1", "w1", "click")
    with pytest.raises(ValueError):
        service.record_event("r1", "w1", "click")
    with pytest.raises(KeyError):
        service.record_event("r_missing", "w1", "click")
    with pytest.raises(KeyError):
        service.record_event("r1", "w_missing", "click")
    with pytest.raises(ValueError):
        service.record_event("r1", "w1", "invalid_action")


def test_event_service_rotates_jsonl(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store, persist_dir=tmp_path, max_events=2)
    for request_id in ("r1", "r2", "r3"):
        service.record_impression(
            request_id, "t1", ["w1"], {"w1": 1.0}, "test",
        )
    service.record_event("r1", "w1", "click")
    service.record_event("r1", "w1", "apply")
    service.record_event("r1", "w1", "accept")
    assert (tmp_path / "events.1.jsonl").exists()
    assert len(
        (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ) == 1
    assert (tmp_path / "impressions.1.jsonl").exists()
    assert len(
        (tmp_path / "impressions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 1


def test_event_service_funnel_rates_and_jsonl_fields(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store, persist_dir=tmp_path)
    service.record_impression(
        "r1", "t1", ["w1", "w2", "w3"],
        {"w1": 0.6, "w2": 0.2, "w3": 0.2}, "test",
    )
    service.record_event("r1", "w1", "click")
    service.record_event("r1", "w1", "apply")
    service.record_event("r1", "w1", "accept")
    reject = service.record_event(
        "r1", "w2", "reject", metadata={"weights_version": 7},
    )
    service.record_event("r1", "w3", "ignore")

    metrics = service.funnel_metrics()
    assert metrics["click_rate"] == pytest.approx(1 / 3)
    assert metrics["apply_rate"] == pytest.approx(1.0)
    assert metrics["accept_rate"] == pytest.approx(1.0)
    assert metrics["reject_rate"] == pytest.approx(1 / 3)
    assert metrics["ignore_rate"] == pytest.approx(1 / 3)
    assert reject.weights_version == "7"

    lines = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    reject_line = next(line for line in lines if line["action"] == "reject")
    assert reject_line["candidate_id"] == "w2"
    assert reject_line["rank"] == 2
    assert reject_line["propensity"] == pytest.approx(0.2)
    assert reject_line["weights_version"] == "7"
