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
