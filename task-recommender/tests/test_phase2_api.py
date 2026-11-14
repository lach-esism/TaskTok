import pytest


def test_phase2_api_flow(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    onboarding = client.post(
        "/workers/w_new/onboarding",
        json={
            "role": "engineer",
            "industry": "software",
            "experience_years": 2,
        },
    )
    assert onboarding.status_code == 200
    weights = client.get("/workers/w_new/weight-profile")
    assert weights.status_code == 200
    assert sum(weights.json()["weights"].values()) == pytest.approx(1.0)
    rollback = client.post(
        "/weights/rollback",
        json={"to_version": "v0000", "reason": "test"},
    )
    assert rollback.status_code == 200
    assert client.get("/weights").json()["version"] == "v0000"


def test_customer_onboarding(client):
    response = client.post(
        "/customers/c1/onboarding",
        json={"role": "buyer", "industry": "software", "experience_years": 4},
    )
    assert response.status_code == 200
    profile = client.get("/customers/c1/weight-profile")
    assert profile.status_code == 200
    assert sum(profile.json()["weights"].values()) == pytest.approx(1.0)


def test_recommend_accepts_user_id(client):
    response = client.post(
        "/recommend/workers",
        json={"task_id": "t1", "top_n": 3, "user_id": "w_good"},
    )
    assert response.status_code == 200
    assert response.json()["candidates"]


def test_recommendations_include_propensity(client):
    response = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 3}
    )
    candidates = response.json()["candidates"]
    assert candidates
    assert all(0.0 < candidate["propensity"] <= 1.0 for candidate in candidates)
    assert any(candidate["propensity"] < 1.0 for candidate in candidates)


def test_active_weight_version_changes_and_rollback_restores(
    small_store, tmp_path
):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(
        create_app(
            small_store,
            weights_dir=tmp_path,
            events_dir=tmp_path / "events",
            exploration_seed=42,
        )
    )
    baseline = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 5}
    ).json()
    # Impressions are exposure-fairness inputs; reset them so the rollback
    # comparison runs under identical exposure state.
    small_store.impressions.clear()
    client.app.state.weight_store.create(
        {
            "reputation": 0.40,
            "skill": 0.25,
            "expertise": 0.10,
            "collaborative": 0.10,
            "preference": 0.05,
            "load": 0.06,
            "customer_preference": 0.04,
        },
        10,
        "test",
    )
    learned = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 5}
    ).json()
    assert [
        candidate["score"] for candidate in learned["candidates"]
    ] != [
        candidate["score"] for candidate in baseline["candidates"]
    ]
    small_store.impressions.clear()
    client.post(
        "/weights/rollback",
        json={"to_version": "v0000", "reason": "test"},
    )
    restored = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 5}
    ).json()
    assert [
        candidate["candidate_id"] for candidate in restored["candidates"]
    ] == [
        candidate["candidate_id"] for candidate in baseline["candidates"]
    ]
    assert [
        candidate["score"] for candidate in restored["candidates"]
    ] == pytest.approx(
        [candidate["score"] for candidate in baseline["candidates"]]
    )


def test_onboarding_reset_switches_preferences(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    first = client.post(
        "/workers/w_new/onboarding",
        json={
            "role": "engineer",
            "industry": "software",
            "experience_years": 2,
            "preferences": {"quality": 1.0},
            "reset": True,
        },
    ).json()
    second = client.post(
        "/workers/w_new/onboarding",
        json={
            "role": "engineer",
            "industry": "software",
            "experience_years": 2,
            "preferences": {"speed": 1.0},
            "reset": True,
        },
    ).json()
    assert first["weights"]["reputation"] > second["weights"]["reputation"]
    assert second["weights"]["load"] > first["weights"]["load"]
    profile = client.get("/workers/w_new/weight-profile").json()
    assert profile["sample_count"] == 0


def test_feedback_updates_personal_weights_and_snapshot(
    small_store, tmp_path
):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    client.post(
        "/workers/w_new/onboarding",
        json={
            "role": "engineer",
            "industry": "software",
            "experience_years": 2,
        },
    )
    before = client.get("/workers/w_new/weight-profile").json()
    assignment = client.post(
        "/assignments",
        json={"task_id": "t1", "worker_id": "w_new", "customer_id": "c1"},
    ).json()
    client.post(
        "/feedback",
        json={
            "assignment_id": assignment["assignment_id"],
            "overall_rating": 5,
        },
    )
    after = client.get("/workers/w_new/weight-profile").json()
    assert after["sample_count"] == before["sample_count"] + 1
    assert client.get("/workers/w_new/learning-curve").json()


def test_metrics_compare_rejects_unknown_version(client):
    response = client.get(
        "/metrics/compare?run_a=v0000&run_b=v9999"
    )
    assert response.status_code == 404


def test_metrics_compare_success_with_heldout(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(weights_dir=tmp_path))
    response = client.get(
        "/metrics/compare?run_a=v0000&run_b=v0000"
    )
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["baseline_hr"] > 0.0
