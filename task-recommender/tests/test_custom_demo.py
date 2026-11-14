"""Tests for the user-supplied custom case simulation."""

from __future__ import annotations

import pytest

from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.learning.custom_demo import simulate_custom_step
from app.learning.weights import validate_weights


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


def task_payload():
    return {
        "mode": "task",
        "preferences": {"quality": 0.6},
        "task": {
            "title": "跨境品牌短视频投放",
            "category": "video_production",
            "description": "需要 3 条 30 秒投放素材",
            "budget": 8000,
            "deadline_days": 10,
            "difficulty": 3,
            "required_skills": {"video_editing": 4},
        },
    }


def worker_payload():
    return {
        "mode": "worker",
        "preferences": {"speed": 0.5},
        "worker": {
            "name": "自建画像",
            "skills": {"video_editing": 4, "storyboard": 3},
            "preferred_categories": {"video_production": 0.9},
            "expected_pay": 7000,
            "current_load_hours": 4,
            "region": "CN",
            "remote_ok": True,
        },
    }


def test_custom_task_step_returns_ranked_workers(base_store):
    result = simulate_custom_step(base_store, task_payload())

    assert result["mode"] == "task"
    assert result["round"] == 1
    assert len(result["feed"]) == 5
    assert [item["rank"] for item in result["feed"]] == [1, 2, 3, 4, 5]
    assert all(
        {
            "id",
            "title",
            "subtitle",
            "score",
            "rank",
            "features",
        }
        <= set(item)
        for item in result["feed"]
    )
    validate_weights(result["weights"])
    assert result["choice"] is None


def test_custom_step_updates_weights_after_choice(base_store):
    start = simulate_custom_step(base_store, task_payload())
    chosen = start["feed"][2]["id"]
    payload = dict(task_payload())
    payload.update(
        {
            "weights": start["weights"],
            "round": start["round"],
            "choice": chosen,
        }
    )

    updated = simulate_custom_step(base_store, payload)

    assert updated["round"] == 2
    assert updated["choice"] == chosen
    validate_weights(updated["weights"])
    assert updated["weights"] != start["weights"]
    assert any(
        abs(updated["weights"][key] - start["weights"][key]) > 1e-9
        for key in updated["weights"]
    )
    assert len(updated["feed"]) == 5


def test_custom_worker_mode_returns_tasks(base_store):
    result = simulate_custom_step(base_store, worker_payload())

    assert result["mode"] == "worker"
    assert len(result["feed"]) == 5
    assert all(item["id"].startswith("t") for item in result["feed"])
    validate_weights(result["weights"])


def test_custom_choice_outside_feed_is_rejected(base_store):
    start = simulate_custom_step(base_store, task_payload())
    payload = dict(task_payload())
    payload.update(
        {
            "weights": start["weights"],
            "round": 1,
            "choice": "worker-not-shown",
        }
    )

    with pytest.raises(ValueError):
        simulate_custom_step(base_store, payload)


def test_custom_unknown_category_is_rejected(base_store):
    payload = task_payload()
    payload["task"]["category"] = "not-a-real-category"

    with pytest.raises(ValueError):
        simulate_custom_step(base_store, payload)


def test_custom_endpoint_returns_ranked_feed(client):
    response = client.post(
        "/demo/custom/step",
        json={
            "mode": "task",
            "preferences": {"quality": 0.5},
            "task": {
                "title": "接口开发",
                "category": "software_dev",
                "budget": 5000,
                "required_skills": {"python": 3},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "task"
    assert len(payload["feed"]) == 5
    assert payload["feed"][0]["rank"] == 1


def test_custom_endpoint_rejects_unknown_category(client):
    response = client.post(
        "/demo/custom/step",
        json={
            "mode": "task",
            "task": {
                "title": "接口开发",
                "category": "not-a-real-category",
                "budget": 5000,
            },
        },
    )

    assert response.status_code == 422
