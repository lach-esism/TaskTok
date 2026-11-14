"""Tests for the natural-language resume push-feed simulator."""

from __future__ import annotations

import pytest

from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.events import EventService
from app.learning.exploration import ExplorationPolicy
from app.learning.resume_feed import (
    build_resume_demo_store,
    simulate_resume_refresh,
)
from app.learning.weights import validate_weights
from app.service import is_eligible
from app.upload.analyze import analyze_resume_text, worker_from_draft

RESUME = """张三，5 年视频制作经验，熟练使用 Premiere、After Effects、达芬奇。
做过品牌宣传片、短视频投放、分镜脚本和剪辑后期，服务过消费品牌。
期望月薪 8000 元，可远程。"""


@pytest.fixture(scope="module")
def base_store():
    dataset = generate_dataset(seed=42)
    return Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
        events=dataset.events,
        impressions=dataset.impressions,
    )


@pytest.fixture(scope="module")
def draft():
    return analyze_resume_text(RESUME)["draft_worker"]


def refresh_payload(draft, **overrides):
    payload = {
        "draft": draft,
        "seen": [],
        "refresh": 0,
        "accepted": [],
        "skipped": [],
    }
    payload.update(overrides)
    return payload


def test_resume_demo_store_has_real_history():
    store = build_resume_demo_store(
        n_workers=20, n_tasks=100, n_assignments=300
    )

    assert len(store.tasks) == 100
    assert len({task.task_id for task in store.tasks.values()}) == 100
    assert all(
        task.customer_id in store.customers
        for task in store.tasks.values()
    )
    assert len(store.assignments) == 300
    assert store.feedback


def test_first_refresh_returns_five_tasks(base_store, draft):
    result = simulate_resume_refresh(base_store, refresh_payload(draft))

    assert result["refresh"] == 1
    assert len(result["feed"]) == 5
    assert [item["rank"] for item in result["feed"]] == [1, 2, 3, 4, 5]
    assert result["pool_size"] > 5
    assert result["retrieval_pool"] >= 5
    assert result["exhausted"] is False
    validate_weights(result["weights"])
    assert result["profile"]["skills"]
    assert len(result["capability"]["static"]["dimensions"]) == 5
    assert result["capability"]["dynamic"]["available"] is False
    completion = result["feed"][0]["completion"]
    assert completion["total"] > 0
    assert set(completion["dimensions"]) == {
        "requirement_coverage",
        "quality",
        "timeliness",
        "completeness",
        "communication",
    }


def test_seen_tasks_are_not_pushed_twice(base_store, draft):
    first = simulate_resume_refresh(base_store, refresh_payload(draft))
    first_ids = [item["id"] for item in first["feed"]]
    second = simulate_resume_refresh(
        base_store,
        refresh_payload(draft, seen=first_ids, refresh=1),
    )

    assert not set(first_ids) & {item["id"] for item in second["feed"]}
    assert second["refresh"] == 2


def test_accepting_updates_weights_and_changes_feed(base_store, draft):
    first = simulate_resume_refresh(base_store, refresh_payload(draft))
    chosen = first["feed"][0]["id"]
    second = simulate_resume_refresh(
        base_store,
        refresh_payload(
            draft,
            seen=[item["id"] for item in first["feed"]],
            refresh=1,
            accepted=[chosen],
        ),
    )

    assert second["refresh"] == 2
    assert second["weights"] != first["weights"]
    assert any(abs(value) > 1e-9 for value in second["delta"].values())
    validate_weights(second["weights"])


def test_accepted_history_populates_dynamic_capability(base_store, draft):
    first = simulate_resume_refresh(base_store, refresh_payload(draft))
    accepted_task = first["feed"][0]["id"]
    seen = [item["id"] for item in first["feed"]]
    second = simulate_resume_refresh(
        base_store,
        refresh_payload(
            draft,
            seen=seen,
            refresh=1,
            accepted=[accepted_task],
            accepted_history=[accepted_task],
        ),
    )

    capability = second["capability"]
    assert capability["dynamic"]["available"] is True
    assert capability["dynamic"]["samples"] == 1
    assert capability["overall"] != capability["static"]["overall"]


def test_accepted_but_not_evaluated_does_not_count_for_capability(
    base_store, draft
):
    first = simulate_resume_refresh(base_store, refresh_payload(draft))
    accepted_task = first["feed"][0]["id"]
    second = simulate_resume_refresh(
        base_store,
        refresh_payload(
            draft,
            seen=[item["id"] for item in first["feed"]],
            refresh=1,
            accepted=[accepted_task],
            request_id=first["request_id"],
        ),
    )

    assert second["capability"]["dynamic"]["available"] is False
    assert second["capability"]["overall"] == (
        second["capability"]["static"]["overall"]
    )


def test_completion_records_override_simulated_metrics(base_store, draft):
    first = simulate_resume_refresh(base_store, refresh_payload(draft))
    accepted_task = first["feed"][0]["id"]
    seen = [item["id"] for item in first["feed"]]
    result = simulate_resume_refresh(
        base_store,
        refresh_payload(
            draft,
            seen=seen,
            refresh=1,
            accepted=[accepted_task],
            accepted_history=[accepted_task],
            completion_records=[
                {
                    "task_id": accepted_task,
                    "dimensions": {
                        "requirement_coverage": 90,
                        "quality": 90,
                        "timeliness": 20,
                        "completeness": 90,
                        "communication": 90,
                    },
                }
            ],
        ),
    )

    on_time = next(
        item
        for item in result["capability"]["dynamic"]["dimensions"]
        if item["key"] == "on_time"
    )
    assert on_time["score"] == 0.0


def test_feed_exposes_exploration_eligibility_and_impressions(base_store, draft):
    events = EventService(base_store)
    exploration = ExplorationPolicy(epsilon=0.1, seed=7)
    result = simulate_resume_refresh(
        base_store,
        refresh_payload(draft),
        exploration=exploration,
        events=events,
    )

    assert result["request_id"]
    assert result["personalization"]["segment_id"]
    assert all(
        0.0 < item["propensity"] <= 1.0 for item in result["feed"]
    )
    worker = worker_from_draft(draft)
    for item in result["feed"]:
        eligible, _ = is_eligible(
            worker,
            base_store.tasks[item["id"]],
            base_store,
            require_skills=False,
        )
        assert eligible
    assert len(events.store.impressions) >= 1
    assert result["funnel"]["impressions"] >= 1
    assert result["funnel"]["accepts"] >= 0


def test_accept_records_an_event_against_the_impression(base_store, draft):
    events = EventService(base_store)
    first = simulate_resume_refresh(
        base_store, refresh_payload(draft), events=events
    )
    chosen = first["feed"][0]["id"]
    simulate_resume_refresh(
        base_store,
        refresh_payload(
            draft,
            seen=[item["id"] for item in first["feed"]],
            refresh=1,
            accepted=[chosen],
            request_id=first["request_id"],
        ),
        events=events,
    )

    assert any(
        event.action == "accept" and event.candidate_id == chosen
        for event in events.store.events
    )


def test_exhausted_pool_returns_empty_feed(base_store, draft):
    all_open = [
        task.task_id
        for task in base_store.tasks.values()
        if task.status == "open"
    ]
    result = simulate_resume_refresh(
        base_store,
        refresh_payload(draft, seen=all_open, refresh=1),
    )

    assert result["exhausted"] is True
    assert result["feed"] == []


def test_resume_refresh_endpoint(client):
    draft = analyze_resume_text(
        "李四，3 年 Python 后端开发，熟悉 Django、FastAPI、PostgreSQL。"
    )["draft_worker"]
    response = client.post(
        "/demo/resume/refresh",
        json={
            "draft": draft,
            "seen": [],
            "refresh": 0,
            "accepted": [],
            "skipped": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # The shared ``client`` fixture uses a small store with fewer than five
    # open tasks, so assert the batch is populated without assuming a size.
    assert 0 < len(payload["feed"]) <= 5
    validate_weights(payload["weights"])


def test_resume_refresh_endpoint_rejects_bad_draft(client):
    response = client.post(
        "/demo/resume/refresh",
        json={"draft": {"skills": {}}, "seen": [], "refresh": 0},
    )

    assert response.status_code == 422
