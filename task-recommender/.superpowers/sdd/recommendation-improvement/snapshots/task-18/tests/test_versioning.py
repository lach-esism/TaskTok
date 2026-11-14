import pytest

from app.versioning import WeightStore


def test_weight_store_creates_and_rolls_back(tmp_path):
    store = WeightStore(tmp_path, prior={"reputation": 0.32, "skill": 0.68})
    first = store.create(
        {"reputation": 0.32, "skill": 0.68}, 0, "prior"
    )
    second = store.create(
        {"reputation": 0.34, "skill": 0.66}, 10, "online"
    )
    assert store.active().version == second.version
    rolled = store.rollback(first.version, "test")
    assert rolled.version == first.version
    assert store.active().version == first.version
    assert store.diff(first.version, second.version)["reputation"][
        "delta"
    ] == pytest.approx(0.02)


def test_rollback_restores_exact_baseline_weights(tmp_path):
    store = WeightStore(tmp_path, prior={"reputation": 0.32, "skill": 0.68})
    baseline = store.create(
        {"reputation": 0.32, "skill": 0.68}, 0, "prior"
    )
    store.create({"reputation": 0.40, "skill": 0.60}, 20, "online")
    store.rollback(baseline.version, "restore")
    assert store.active().weights == baseline.weights


def test_changelog_records_rollback(tmp_path):
    store = WeightStore(tmp_path, prior={"reputation": 0.32, "skill": 0.68})
    baseline = store.create(
        {"reputation": 0.32, "skill": 0.68}, 0, "prior"
    )
    store.create({"reputation": 0.35, "skill": 0.65}, 5, "online")
    store.rollback(baseline.version, "demo")
    events = store.changelog()
    assert events[-1]["event_type"] == "rollback"
    assert events[-1]["version"] == baseline.version


def test_invalid_weights_are_rejected(tmp_path):
    store = WeightStore(
        tmp_path, prior={"reputation": 0.32, "skill": 0.68}
    )
    with pytest.raises(ValueError):
        store.create(
            {"reputation": 0.10, "skill": 0.90}, 1, "bad"
        )


def test_weight_api_rollback(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    active = client.get("/weights")
    assert active.status_code == 200
    version = active.json()["version"]
    rollback = client.post(
        "/weights/rollback",
        json={"to_version": version, "reason": "test"},
    )
    assert rollback.status_code == 200
    assert client.get("/weights").json()["version"] == version
    changelog = client.get("/learning/changelog")
    assert changelog.status_code == 200
    assert changelog.json()[-1]["event_type"] == "rollback"
