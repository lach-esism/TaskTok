import pytest

from app.feedback import FeedbackService


def test_record_feedback_updates_worker_rating_once(small_store):
    service = FeedbackService(small_store)
    assignment = service.record_assignment("t1", "w_good", "c1")
    first = service.record_feedback(
        assignment.assignment_id, 5, quality_rating=5
    )
    assert first.overall_rating == 5
    assert small_store.workers["w_good"].ratings[-1] == 5.0
    with pytest.raises(ValueError):
        service.record_feedback(assignment.assignment_id, 4)
    assert len(small_store.workers["w_good"].ratings) == 3


def test_unknown_assignment_feedback_raises_keyerror(small_store):
    with pytest.raises(KeyError):
        FeedbackService(small_store).record_feedback("missing", 5)


def test_feedback_api_flow(client):
    assignment = client.post(
        "/assignments",
        json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1"},
    )
    assert assignment.status_code == 200
    assignment_id = assignment.json()["assignment_id"]

    feedback = client.post(
        "/feedback",
        json={
            "assignment_id": assignment_id,
            "overall_rating": 5,
            "quality_rating": 5,
        },
    )
    assert feedback.status_code == 200

    reputation = client.get("/workers/w_good/reputation")
    assert reputation.status_code == 200
    assert reputation.json()["ratings_count"] == 3


def test_duplicate_feedback_returns_409(client):
    assignment = client.post(
        "/assignments",
        json={"task_id": "t2", "worker_id": "w_good", "customer_id": "c1"},
    )
    assignment_id = assignment.json()["assignment_id"]
    assert (
        client.post(
            "/feedback",
            json={"assignment_id": assignment_id, "overall_rating": 5},
        ).status_code
        == 200
    )
    duplicate = client.post(
        "/feedback",
        json={"assignment_id": assignment_id, "overall_rating": 4},
    )
    assert duplicate.status_code == 409


def test_unknown_assignment_feedback_returns_404(client):
    response = client.post(
        "/feedback", json={"assignment_id": "missing", "overall_rating": 5}
    )
    assert response.status_code == 404


def test_duplicate_assignment_returns_409(client):
    first = client.post(
        "/assignments",
        json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1"},
    )
    assert first.status_code == 200
    second = client.post(
        "/assignments",
        json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1"},
    )
    assert second.status_code == 409


def test_bad_recommendation_context_returns_422(client):
    response = client.post(
        "/assignments",
        json={
            "task_id": "t1",
            "worker_id": "w_good",
            "customer_id": "c1",
            "recommendation_context": {"score": "bad"},
        },
    )
    assert response.status_code == 422


def test_feedback_updates_category_ratings(small_store):
    service = FeedbackService(small_store)
    assignment = service.record_assignment("t1", "w_good", "c1")
    service.record_feedback(assignment.assignment_id, 5)
    assert small_store.workers["w_good"].category_ratings[
        "software_dev"
    ][-1] == 5.0


def test_record_feedback_appends_communication_rating(small_store):
    service = FeedbackService(small_store)
    assignment = service.record_assignment("t1", "w_good", "c1")
    worker = small_store.workers["w_good"]
    assert worker.communication_ratings == []
    service.record_feedback(
        assignment.assignment_id, 5, communication_rating=2
    )
    assert worker.communication_ratings == [2.0]


def test_record_feedback_clears_semantic_text_cache(small_store):
    import app.semantic as semantic

    semantic.clear_text_caches()
    semantic.build_worker_text(small_store.workers["w_good"])
    assert semantic._WORKER_TEXT_CACHE
    service = FeedbackService(small_store)
    assignment = service.record_assignment("t1", "w_good", "c1")
    service.record_feedback(assignment.assignment_id, 5)
    assert semantic._WORKER_TEXT_CACHE == {}


def test_reputation_returns_normalized_rating_and_status(client):
    assignment = client.post(
        "/assignments",
        json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1"},
    ).json()
    client.post(
        "/feedback",
        json={"assignment_id": assignment["assignment_id"], "overall_rating": 5},
    )
    reputation = client.get("/workers/w_good/reputation").json()
    assert 0.0 <= reputation["rating"] <= 1.0
    assert reputation["status"] in {"active", "warning", "excluded"}
