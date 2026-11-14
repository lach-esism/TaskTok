"""Marketplace flow behind the TaskTok frontend, with SQLite persistence."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market import DEMO_WORKER_ID


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    return tmp_path_factory.mktemp("market") / "tasktok.sqlite"


@pytest.fixture(scope="module")
def client(db_path, tmp_path_factory):
    events = tmp_path_factory.mktemp("events")
    return TestClient(
        create_app(db_path=db_path, events_dir=events, exploration_seed=7)
    )


def _publish(client, **overrides):
    now = client.app.state.market.clock()
    payload = {
        "title": "TikTok 投放诊断",
        "desc": "分析近 30 天广告数据，找出 CAC 偏高原因并给出 A/B 方案。",
        "budget": 3200,
        "level": "L2",
        "claimDeadline": (now + timedelta(days=2)).isoformat(),
        "deliverDeadline": (now + timedelta(days=8)).isoformat(),
        "verify": "metrics",
        "outputs": ["诊断报告", "A/B 方案"],
        "accept": ["CAC 下降", "附后台截图"],
    }
    payload.update(overrides)
    return client.post("/market/tasks", json=payload)


def test_feed_cards_have_frontend_fields(client):
    body = client.get("/market/feed").json()
    assert body["request_id"] and body["items"]
    card = body["items"][0]
    for key in (
        "id", "title", "poster", "avatar", "cat", "level", "levelText",
        "budget", "budgetNum", "deadline", "hours", "match", "applicants",
        "rate", "publishedAt", "verify", "desc", "outputs", "accept", "why",
        "contract", "checks",
    ):
        assert key in card
    assert card["level"] in {"L1", "L2", "L3", "L4"}
    assert any("按时率" in reason for reason in card["why"])


def test_fresh_database_seeds_demo_workspace(client):
    rows = client.get("/market/work-items").json()
    statuses = {row["status"] for row in rows["items"]}
    assert {"accepted", "active", "rework", "submitted", "completed"} <= statuses
    rework = next(row for row in rows["items"] if row["status"] == "rework")
    assert rework["review"]["reason"]
    assert {card["id"] for card in rows["tasks"]} == {row["taskId"] for row in rows["items"]}


def test_claim_records_event_and_withdraw(client):
    feed = client.get("/market/feed").json()
    claimed = {row["taskId"] for row in client.get("/market/work-items").json()["items"]}
    task_id = next(card["id"] for card in feed["items"] if card["id"] not in claimed)
    before = len(client.app.state.store.events)
    item = client.post(
        f"/market/tasks/{task_id}/applications",
        json={"request_id": feed["request_id"], "note": "可以做"},
    ).json()
    assert item == {"taskId": task_id, "status": "accepted", "addedAt": item["addedAt"]}
    assert len(client.app.state.store.events) == before + 1
    assert client.post(f"/market/tasks/{task_id}/applications", json={}).status_code == 409
    rows = client.get("/market/work-items").json()["items"]
    assert any(r["taskId"] == task_id and r["status"] == "accepted" for r in rows)
    assert client.delete(f"/market/tasks/{task_id}/applications").json()["status"] == "withdrawn"


def test_publish_validation(client):
    assert _publish(client, title="").status_code == 422
    assert _publish(client, budget=0).status_code == 422
    now = client.app.state.market.clock()
    assert _publish(
        client,
        claimDeadline=(now + timedelta(days=3)).isoformat(),
        deliverDeadline=(now + timedelta(days=1)).isoformat(),
    ).status_code == 422


def test_publish_keeps_client_id(client):
    task = _publish(client, id="pub_client0001").json()
    assert task["id"] == "pub_client0001"
    # Reused or malformed ids fall back to a server id.
    assert _publish(client, id="pub_client0001").json()["id"] != "pub_client0001"
    assert _publish(client, id="t0001").json()["id"].startswith("pub_")


def test_publish_select_rework_pass(client, db_path):
    response = _publish(client)
    assert response.status_code == 200
    task = response.json()
    task_id = task["id"]
    assert task_id.startswith("pub_") and task["status"] == "recruiting"
    assert task["checks"] == ["CAC 下降", "附后台截图"]

    applicants = client.get(f"/market/tasks/{task_id}/applicants").json()
    assert 1 <= len(applicants) <= 3
    assert all(a["id"] != DEMO_WORKER_ID and a["note"] for a in applicants)
    assert client.patch(f"/market/tasks/{task_id}", json={"budget": 3500}).json()["budgetNum"] == 3500

    worker_id = applicants[0]["id"]
    worker = client.app.state.store.workers[worker_id]
    completed = worker.completed
    selected = client.post(f"/market/tasks/{task_id}/select", json={"worker_id": worker_id}).json()
    assert selected["status"] == "working" and selected["workerId"] == worker_id
    assert client.patch(f"/market/tasks/{task_id}", json={"budget": 1}).status_code == 409
    assert len(client.get(f"/market/tasks/{task_id}/applicants").json()) == 1

    assert client.post(f"/market/tasks/{task_id}/simulate-delivery").json()["status"] == "reviewing"
    short = client.post(f"/market/tasks/{task_id}/review", json={"decision": "rework", "reason": "短"})
    assert short.status_code == 422
    reworked = client.post(
        f"/market/tasks/{task_id}/review",
        json={"decision": "rework", "reason": "第二个环节数据对不上，请重算"},
    ).json()
    assert reworked["status"] == "working" and len(reworked["reworks"]) == 1

    client.post(f"/market/tasks/{task_id}/simulate-delivery")
    assert client.post(f"/market/tasks/{task_id}/review", json={"passed": [0]}).status_code == 422
    done = client.post(f"/market/tasks/{task_id}/review", json={"passed": [0, 1]}).json()
    assert done["status"] == "done" and done["review"]["decision"] == "pass"
    assert worker.completed == completed + 1
    assert any(t["id"] == task_id and t["status"] == "done" for t in client.get("/market/published").json())

    # Restart from the same database: the whole flow survived.
    events = client.app.state.events.persist_dir if hasattr(client.app.state.events, "persist_dir") else None
    again = TestClient(create_app(db_path=db_path, events_dir=events, exploration_seed=7))
    restored = again.get(f"/market/tasks/{task_id}").json()
    assert restored["status"] == "done"
    assert restored["workerId"] == worker_id
    assert len(restored["reworks"]) == 1
    assert again.app.state.store.workers[worker_id].completed == completed + 1


def test_me_numbers(client):
    me = client.get("/market/me").json()
    assert me["name"] == "李洋"
    assert me["level"] in {"L1", "L2", "L3", "L4"}
    assert len(me["incomeSeries"]) == 13
    assert me["capability"] and all(0 <= row["score"] <= 100 for row in me["capability"])


def test_worker_side_demo_buttons(client):
    """Workspace demo buttons: customer declines / selects / reviews the demo worker."""
    feed = client.get("/market/feed").json()
    claimed = {row["taskId"] for row in client.get("/market/work-items").json()["items"]}
    free = [card["id"] for card in feed["items"] if card["id"] not in claimed][:2]
    for task_id in free:
        client.post(f"/market/tasks/{task_id}/applications", json={})
    declined = client.post(f"/market/tasks/{free[0]}/decline", json={"worker_id": DEMO_WORKER_ID})
    assert declined.json()["status"] == "declined"
    client.post(f"/market/tasks/{free[1]}/select", json={"worker_id": DEMO_WORKER_ID})
    client.post(f"/market/tasks/{free[1]}/submission", json={"files": ["a.pdf"], "note": ""})
    accept = client.get(f"/market/tasks/{free[1]}").json()["accept"]
    done = client.post(f"/market/tasks/{free[1]}/review", json={"passed": list(range(len(accept)))})
    assert done.json()["status"] == "done"
    rows = {r["taskId"]: r["status"] for r in client.get("/market/work-items").json()["items"]}
    assert rows[free[0]] == "declined" and rows[free[1]] == "completed"
