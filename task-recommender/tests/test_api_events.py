import json
from pathlib import Path

import pytest

from app.schemas import (
    MAX_EVENT_METADATA_KEYS,
    MAX_EVENTS_BODY_BYTES,
    MAX_EVENTS_PER_BATCH,
)


def test_recommend_returns_request_id_and_events_flow(client):
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    candidate = body["candidates"][0]["candidate_id"]
    event = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": candidate,
            "action": "click",
            "task_id": "t1",
            "user_id": "c1",
            "role": "customer",
        }]},
    )
    assert event.status_code == 200
    metrics = client.get("/events/metrics").json()
    assert metrics["clicks"] >= 1


def test_events_reject_duplicates_and_invalid_actions(client):
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 1})
    body = response.json()
    candidate = body["candidates"][0]["candidate_id"]
    payload = {"events": [{
        "request_id": body["request_id"], "candidate_id": candidate,
        "action": "click", "task_id": "t1",
    }]}
    assert client.post("/events", json=payload).status_code == 200
    assert client.post("/events", json=payload).status_code == 409
    bad = {"events": [{
        "request_id": body["request_id"], "candidate_id": candidate,
        "action": "nope", "task_id": "t1",
    }]}
    assert client.post("/events", json=bad).status_code == 422


def test_task_event_uses_candidate_task_id(client):
    response = client.post(
        "/recommend/tasks", json={"worker_id": "w_good", "top_n": 1}
    )
    body = response.json()
    candidate = body["candidates"][0]["candidate_id"]
    event = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": candidate,
            "candidate_type": "task",
            "action": "click",
            "task_id": candidate,
        }]},
    )
    assert event.status_code == 200
    stored = client.app.state.store.events[-1]
    assert stored.candidate_type == "task"
    assert stored.task_id == candidate


def test_task_event_labels_fall_back_to_impression(client):
    response = client.post(
        "/recommend/tasks", json={"worker_id": "w_good", "top_n": 1}
    )
    body = response.json()
    candidate = body["candidates"][0]["candidate_id"]
    event = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": candidate,
            "action": "click",
        }]},
    )
    assert event.status_code == 200
    stored = client.app.state.store.events[-1]
    assert stored.candidate_type == "task"
    assert stored.task_id == candidate


def test_empty_recommendations_do_not_record_impressions(client):
    before = client.get("/events/metrics").json()["impressions"]
    workers = client.post(
        "/recommend/workers", json={"task_id": "t_empty"}
    ).json()
    tasks = client.post(
        "/recommend/tasks", json={"worker_id": "w_bad"}
    ).json()
    assert workers["candidates"] == []
    assert tasks["candidates"] == []
    assert workers["request_id"]
    assert tasks["request_id"]
    assert client.get("/events/metrics").json()["impressions"] == before


def test_recompute_with_events_changes_weights(client):
    before = client.get("/weights").json()["weights"]
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 2})
    body = response.json()
    chosen = body["candidates"][0]["candidate_id"]
    rejected = body["candidates"][1]["candidate_id"]
    client.post("/events", json={"events": [
        {"request_id": body["request_id"], "candidate_id": chosen, "action": "accept", "task_id": "t1", "user_id": "c1"},
        {"request_id": body["request_id"], "candidate_id": rejected, "action": "reject", "task_id": "t1", "user_id": "c1"},
    ]})
    recomputed = client.post("/weights/recompute?include_events=true")
    assert recomputed.status_code == 200
    payload = recomputed.json()
    assert payload["weights"]
    assert payload.get("updates", 0) > 0
    assert payload["weights"] != before
    assert abs(sum(payload["weights"].values()) - 1.0) < 1e-9
    assert payload["source"] == "batch+pairwise"
    assert payload["mode"] == "pairwise"


def test_assignment_from_task_recommendation_records_accept(client):
    response = client.post(
        "/recommend/tasks", json={"worker_id": "w_good", "top_n": 2}
    )
    body = response.json()
    chosen_task = body["candidates"][0]["candidate_id"]
    assignment = client.post(
        "/assignments",
        json={
            "task_id": chosen_task,
            "worker_id": "w_good",
            "customer_id": "c1",
            "recommendation_context": {"request_id": body["request_id"]},
        },
    )
    assert assignment.status_code == 200
    stored = client.app.state.store.events[-1]
    assert stored.action == "accept"
    assert stored.request_id == body["request_id"]
    assert stored.candidate_id == chosen_task
    assert stored.candidate_type == "task"
    assert client.get("/events/metrics").json()["accepts"] == 1


def test_recompute_with_listwise_mode_changes_weights(client):
    client.app.state.choice_learning_mode = "listwise"
    before = client.get("/weights").json()["weights"]
    response = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 2}
    )
    body = response.json()
    chosen = body["candidates"][0]["candidate_id"]
    rejected = body["candidates"][1]["candidate_id"]
    client.post("/events", json={"events": [
        {
            "request_id": body["request_id"],
            "candidate_id": chosen,
            "action": "accept",
            "task_id": "t1",
            "user_id": "c1",
        },
        {
            "request_id": body["request_id"],
            "candidate_id": rejected,
            "action": "reject",
            "task_id": "t1",
            "user_id": "c1",
        },
    ]})
    recomputed = client.post("/weights/recompute?include_events=true")
    assert recomputed.status_code == 200
    payload = recomputed.json()
    assert payload["updates"] > 0
    assert payload["weights"] != before
    assert abs(sum(payload["weights"].values()) - 1.0) < 1e-9
    assert payload["source"] == "batch+listwise"
    assert payload["mode"] == "listwise"


def test_split_accept_reject_updates_personal_weights(client):
    body = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 2}
    ).json()
    chosen = body["candidates"][0]["candidate_id"]
    rejected = body["candidates"][1]["candidate_id"]
    accept = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": chosen,
            "action": "accept",
            "task_id": "t1",
            "user_id": "c1",
        }]},
    )
    assert accept.status_code == 200
    store = client.app.state.store
    assert "c1" not in store.user_weight_profiles
    reject = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": rejected,
            "action": "reject",
            "task_id": "t1",
            "user_id": "c1",
        }]},
    )
    assert reject.status_code == 200
    profile = store.user_weight_profiles["c1"]
    assert profile.source == "online_pair"
    assert profile.sample_count == 1
    # A later accept for the same recommendation must not re-learn the pair.
    again = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": rejected,
            "action": "accept",
            "task_id": "t1",
            "user_id": "c1",
        }]},
    )
    assert again.status_code == 200
    assert store.user_weight_profiles["c1"].sample_count == 1


def test_weight_binding_endpoint_reports_last_recompute(
    client, tmp_path, monkeypatch
):
    import app.main as main_module

    monkeypatch.setattr(main_module, "REPORTS_DIR", tmp_path)
    binding_path = tmp_path / "weight_binding.json"
    client.app.state.last_binding = None
    assert client.get("/weights/binding").json() == {"available": False}
    recomputed = client.post("/weights/recompute?include_events=false")
    assert recomputed.status_code == 200
    report = recomputed.json()["binding"]
    assert binding_path.exists()
    stored = json.loads(binding_path.read_text(encoding="utf-8"))
    assert stored == report
    assert set(stored["min_hits"]) == set(report["min_hits"])
    client.app.state.last_binding = None
    binding = client.get("/weights/binding").json()
    assert binding["available"] is True
    assert binding["min_hits"] == report["min_hits"]
    assert binding["iterations"] >= 1


def test_events_reject_mismatched_target_labels_and_drop_extra_metadata(
    client,
):
    body = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 2}
    ).json()
    candidate = body["candidates"][0]["candidate_id"]
    request_id = body["request_id"]

    wrong_type = {
        "events": [{
            "request_id": request_id,
            "candidate_id": candidate,
            "candidate_type": "task",
            "action": "click",
        }]
    }
    assert client.post("/events", json=wrong_type).status_code == 409

    wrong_task = {
        "events": [{
            "request_id": request_id,
            "candidate_id": candidate,
            "task_id": "t2",
            "action": "apply",
        }]
    }
    assert client.post("/events", json=wrong_task).status_code == 409

    accepted = client.post(
        "/events",
        json={"events": [{
            "request_id": request_id,
            "candidate_id": candidate,
            "task_id": "t1",
            "action": "ignore",
            "metadata": {"untrusted": "drop-me", "score": 0.5},
        }]},
    )
    assert accepted.status_code == 200
    stored = client.app.state.store.events[-1]
    assert stored.candidate_type == "worker"
    assert stored.task_id == "t1"
    assert "untrusted" not in stored.metadata
    assert stored.metadata["score"] == 0.5


def test_worker_assignment_records_accept_only_for_matching_impression(
    client,
):
    store = client.app.state.store
    body = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 3}
    ).json()
    candidate = next(
        item["candidate_id"]
        for item in body["candidates"]
        if item["candidate_id"] != "w_other"
    )
    before = len(store.events)

    # A different task with the same request_id must not manufacture an accept.
    mismatched = client.post(
        "/assignments",
        json={
            "task_id": "t2",
            "worker_id": candidate,
            "customer_id": "c1",
            "recommendation_context": {"request_id": body["request_id"]},
        },
    )
    assert mismatched.status_code == 200
    assert len(store.events) == before

    matched = client.post(
        "/assignments",
        json={
            "task_id": "t1",
            "worker_id": candidate,
            "customer_id": "c1",
            "recommendation_context": {"request_id": body["request_id"]},
        },
    )
    assert matched.status_code == 200
    stored = store.events[-1]
    assert stored.action == "accept"
    assert stored.candidate_type == "worker"
    assert stored.task_id == "t1"
    assert stored.candidate_id == candidate
    assert stored.role == "customer"


def test_events_batch_metadata_and_body_are_bounded(client):
    events = [
        {"request_id": "r", "candidate_id": "w", "action": "click"}
    ] * (MAX_EVENTS_PER_BATCH + 1)
    assert client.post("/events", json={"events": events}).status_code == 422

    metadata = {f"key{i}": "value" for i in range(MAX_EVENT_METADATA_KEYS + 1)}
    oversized_metadata = {
        "events": [{
            "request_id": "r",
            "candidate_id": "w",
            "action": "click",
            "metadata": metadata,
        }]
    }
    assert (
        client.post("/events", json=oversized_metadata).status_code == 422
    )

    oversized_body = json.dumps(
        {"events": [], "padding": "x" * (MAX_EVENTS_BODY_BYTES + 64)}
    )
    response = client.post(
        "/events",
        content=oversized_body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_recommend_reuses_cached_service_and_invalidates_on_assignment(
    client,
):
    body = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 2}
    ).json()
    first = client.app.state.service_cache[1]
    client.post("/recommend/workers", json={"task_id": "t1", "top_n": 2})
    assert client.app.state.service_cache[1] is first

    candidate = body["candidates"][0]["candidate_id"]
    client.post(
        "/assignments",
        json={
            "task_id": "t1",
            "worker_id": candidate,
            "customer_id": "c1",
        },
    )
    client.post("/recommend/workers", json={"task_id": "t1", "top_n": 2})
    assert client.app.state.service_cache is not None
    assert client.app.state.service_cache[1] is not first


def test_feedback_updates_live_communication_signal(client):
    assignment = client.post(
        "/assignments",
        json={
            "task_id": "t2",
            "worker_id": "w_new",
            "customer_id": "c1",
        },
    ).json()
    store = client.app.state.store
    worker = store.workers["w_new"]
    from app.service import RecommendationService

    service = RecommendationService(store)
    assert service._communication(worker) == pytest.approx(0.5)

    response = client.post(
        "/feedback",
        json={
            "assignment_id": assignment["assignment_id"],
            "overall_rating": 5,
            "communication_rating": 1,
        },
    )
    assert response.status_code == 200
    assert worker.communication_ratings[-1] == pytest.approx(1.0)
    assert service._communication(worker) == pytest.approx(0.2)


def test_frontend_recommendation_flow_uses_request_id_and_events():
    text = Path("frontend/app.js").read_text(encoding="utf-8")
    assert "postRecommendationEvent" in text
    assert "request_id: requestId" in text
    assert '"/events"' in text
    assert '"apply"' in text
    assert '"reject"' in text


def test_assignment_succeeds_after_duplicate_accept_event(client):
    response = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 3}
    )
    body = response.json()
    candidate = body["candidates"][0]["candidate_id"]
    accept = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": candidate,
            "action": "accept",
            "task_id": "t1",
            "user_id": "c1",
            "role": "customer",
        }]},
    )
    assert accept.status_code == 200
    assignment = client.post(
        "/assignments",
        json={
            "task_id": "t1",
            "worker_id": candidate,
            "customer_id": "c1",
            "recommendation_context": {"request_id": body["request_id"]},
        },
    )
    assert assignment.status_code == 200
    stored = client.app.state.store.events[-1]
    assert stored.action == "accept"
    assert stored.weights_version == (
        client.app.state.weight_store.active().version
    )
    assert client.get("/events/metrics").json()["accepts"] == 1
