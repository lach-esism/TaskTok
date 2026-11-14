"""Self-evolution demo: run -> client feedback -> new version -> better run -> rollback."""

import pytest
from fastapi.testclient import TestClient

from app.evolution.lab import EvolutionLab
from app.main import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("evo")
    return TestClient(
        create_app(
            weights_dir=root / "weights",
            events_dir=root / "events",
            evolution_dir=root / "evolution",
            exploration_seed=7,
        )
    )


def test_second_run_is_better_and_rollback_restores(client):
    client.post("/evolution/reset")
    first = client.post("/evolution/run").json()["run"]
    assert first["version"] == "v0000"
    assert len(first["tasks"]) == 10
    assert all(len(task["shown"]) == 5 for task in first["tasks"])

    learned = client.post("/evolution/feedback", json={"run_id": first["runId"]})
    assert learned.status_code == 200, learned.text
    body = learned.json()
    assert body["memory"]["toVersion"] == "v0001"
    assert body["memory"]["pairs"] == 40
    assert any(abs(item["delta"]) > 0.01 for item in body["diff"])
    assert body["overview"]["activeVersion"] == "v0001"

    second = client.post("/evolution/run").json()["run"]
    assert second["version"] == "v0001"
    assert second["batch"]["hit_rate"] > first["batch"]["hit_rate"]
    assert second["batch"]["satisfaction_gap"] < first["batch"]["satisfaction_gap"]
    # Generalises to tasks that were never part of the feedback.
    assert second["holdout"]["hit_rate"] > first["holdout"]["hit_rate"]

    undo = client.post("/evolution/rollback", json={}).json()
    assert (undo["from"], undo["to"]) == ("v0001", "v0000")
    assert undo["overview"]["memory"][0]["rolledBack"] is True
    third = client.post("/evolution/run").json()["run"]
    assert third["batch"] == first["batch"]
    assert third["holdout"] == first["holdout"]


def test_feedback_guards(client):
    client.post("/evolution/reset")
    run = client.post("/evolution/run").json()["run"]
    task = run["tasks"][0]
    bad = client.post(
        "/evolution/feedback",
        json={"run_id": run["runId"], "picks": {task["taskId"]: "nobody"}},
    )
    assert bad.status_code == 422

    manual = task["shown"][-1]["workerId"]
    ok = client.post(
        "/evolution/feedback",
        json={"run_id": run["runId"], "picks": {task["taskId"]: manual}},
    ).json()
    first_item = ok["memory"]["items"][0]
    assert first_item["chosen"] == manual and first_item["source"] == "manual"

    again = client.post("/evolution/feedback", json={"run_id": run["runId"]})
    assert again.status_code == 409
    assert client.post("/evolution/feedback", json={"run_id": "run_x"}).status_code == 404

    client.post("/evolution/rollback", json={})
    assert client.post("/evolution/rollback", json={}).status_code == 409


def test_state_survives_restart(tmp_path):
    lab = EvolutionLab(tmp_path)
    run = lab.run()
    lab.feedback(run["runId"])
    reopened = EvolutionLab(tmp_path)
    overview = reopened.overview()
    assert overview["activeVersion"] == "v0001"
    assert len(overview["runs"]) == 1 and len(overview["memory"]) == 1


def test_marketplace_weights_untouched(client):
    before = client.get("/weights").json()
    client.post("/evolution/reset")
    run = client.post("/evolution/run").json()["run"]
    client.post("/evolution/feedback", json={"run_id": run["runId"]})
    assert client.get("/weights").json() == before
