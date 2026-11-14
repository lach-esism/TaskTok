"""Chain draft materializations survive a restart of the SQLite-backed app."""

from fastapi.testclient import TestClient

from app.main import create_app


def _app(db_path, tmp_path):
    return TestClient(
        create_app(
            db_path=db_path,
            events_dir=tmp_path / "events",
            exploration_seed=7,
            materialization_log=tmp_path / "materialized.jsonl",
        )
    )


def test_materialization_round_trip(tmp_path):
    db_path = tmp_path / "tasktok.sqlite"
    client = _app(db_path, tmp_path)
    store = client.app.state.store
    parent_id = next(
        task.task_id
        for task in store.tasks.values()
        if task.status == "open"
        and not any(a.task_id == task.task_id for a in store.assignments)
        and client.post(
            "/chains/decompose", json={"task_id": task.task_id, "split": True}
        ).status_code == 200
    )
    draft_id = client.post(
        "/chains/decompose", json={"task_id": parent_id, "split": True}
    ).json()["draft_id"]
    response = client.post(f"/chains/drafts/{draft_id}/materialize")
    assert response.status_code == 200, response.text
    record = response.json()
    client.app.state.db.close()

    restarted = _app(db_path, tmp_path)
    state = restarted.app.state
    assert state.materializations[draft_id]["task_ids"] == record["task_ids"]
    assert state.store.tasks[parent_id].status == "split"
    assert all(
        state.store.tasks[task_id].parent_task_id == parent_id
        for task_id in record["task_ids"]
    )

    # Rollback works after the restart and is persisted too.
    undo = restarted.post(f"/chains/drafts/{draft_id}/materialize/rollback")
    assert undo.status_code == 200, undo.text
    state.db.close()

    again = _app(db_path, tmp_path).app.state
    assert draft_id not in again.materializations
    assert again.store.tasks[parent_id].status == "open"
    assert not any(task_id in again.store.tasks for task_id in record["task_ids"])
    again.db.close()
