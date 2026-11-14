from app.chains.materialize import (
    build_subtask_task,
    validate_materialization,
)
from app.domain import SubTask, TaskChain


def test_build_subtask_task_inherits_parent_fields(small_store):
    parent = small_store.tasks["t1"]
    node = SubTask(
        subtask_id="s1",
        chain_id="ch1",
        key="backend_dev",
        title="后端开发",
        node_type="task",
        estimated_hours=8.0,
        required_skills={"backend": 3},
        depends_on=[],
        acceptance=["接口可用"],
        budget=4000.0,
        deadline=parent.deadline,
        split_source="module",
        split_reason="后端模块",
        confidence=0.9,
    )
    chain = TaskChain(
        chain_id="ch1",
        root_task_id=parent.task_id,
        customer_id=parent.customer_id,
        deadline=parent.deadline,
        budget=parent.budget,
        nodes=[node],
    )
    task = build_subtask_task(parent, node, chain, "draft1")
    assert task.task_id.startswith("sub_")
    assert task.parent_task_id == parent.task_id
    assert task.chain_id == "ch1"
    assert task.subtask_key == "backend_dev"
    assert task.status == "open"
    assert task.budget == 4000.0
    assert task.deadline == parent.deadline


def test_validate_materialization_reports_empty_plan(
    small_store, make_draft
):
    errors = validate_materialization(
        make_draft([]), small_store.tasks["t1"], [], False
    )
    assert any("no subtasks" in error for error in errors)


def test_validate_materialization_rejects_past_deadline(small_store):
    from app.chains.materialize import build_subtask_task
    from app.domain import DecompositionDraft, TaskChain

    parent = small_store.tasks["t_past"]
    parent.status = "open"
    node = SubTask(
        subtask_id="s_past",
        chain_id="ch1",
        key="backend_dev",
        title="后端开发",
        node_type="task",
        estimated_hours=8.0,
        required_skills={"backend": 3},
        depends_on=[],
        acceptance=["ok"],
        budget=1000.0,
        deadline=parent.deadline,
        split_source="template",
    )
    chain = TaskChain(
        chain_id="ch1",
        root_task_id=parent.task_id,
        customer_id=parent.customer_id,
        deadline=parent.deadline,
        budget=parent.budget,
        nodes=[node],
    )
    draft = DecompositionDraft(
        draft_id="d1",
        task_id=parent.task_id,
        template_id="t",
        variant="standard",
        chain=chain,
        requirements=[],
        coverage={},
    )
    planned = [build_subtask_task(parent, node, chain, "d1")]
    errors = validate_materialization(draft, parent, planned, False)
    assert any("deadline" in error for error in errors)


def _split_draft(client):
    body = client.post(
        "/chains/decompose", json={"task_id": "t1", "split": True}
    ).json()
    return body["draft_id"], body


def test_materialize_creates_tasks_and_splits_parent(client):
    draft_id, _ = _split_draft(client)
    response = client.post(f"/chains/drafts/{draft_id}/materialize")
    assert response.status_code == 200
    data = response.json()
    assert data["parent_status"] == "split"
    store = client.app.state.store
    assert store.tasks["t1"].status == "split"
    assert data["task_ids"]
    assert all(
        store.tasks[task_id].parent_task_id == "t1"
        for task_id in data["task_ids"]
    )


def test_materialize_is_idempotent(client):
    draft_id, _ = _split_draft(client)
    assert (
        client.post(
            f"/chains/drafts/{draft_id}/materialize"
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/chains/drafts/{draft_id}/materialize"
        ).status_code
        == 409
    )


def test_parent_is_not_eligible_but_subtasks_are(client):
    from app.domain import Worker
    from app.service import is_eligible

    draft_id, _ = _split_draft(client)
    data = client.post(
        f"/chains/drafts/{draft_id}/materialize"
    ).json()
    store = client.app.state.store
    worker = Worker(
        worker_id="w_split",
        name="w_split",
        skills={
            "backend": 5,
            "frontend": 5,
            "requirements": 5,
            "architecture": 5,
        },
        specialties={"software_dev": 4},
        level=4,
        capacity_hours=80,
        current_load_hours=0,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
    )
    assert not is_eligible(worker, store.tasks["t1"], store)[0]
    assert any(
        is_eligible(worker, store.tasks[task_id], store)[0]
        for task_id in data["task_ids"]
    )


def test_rollback_restores_parent(client):
    draft_id, _ = _split_draft(client)
    data = client.post(
        f"/chains/drafts/{draft_id}/materialize"
    ).json()
    response = client.post(
        f"/chains/drafts/{draft_id}/materialize/rollback"
    )
    assert response.status_code == 200
    assert client.app.state.store.tasks["t1"].status == "open"
    assert all(
        task_id not in client.app.state.store.tasks
        for task_id in data["task_ids"]
    )


def test_materialize_rejects_non_open_parent(client):
    draft_id, _ = _split_draft(client)
    client.app.state.store.tasks["t1"].status = "completed"
    response = client.post(f"/chains/drafts/{draft_id}/materialize")
    assert response.status_code == 422


def test_second_materialization_for_same_parent_is_rejected(client):
    first_id, _ = _split_draft(client)
    second_id, _ = _split_draft(client)
    assert (
        client.post(
            f"/chains/drafts/{first_id}/materialize"
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/chains/drafts/{second_id}/materialize"
        ).status_code
        == 409
    )


def test_rollback_rejected_when_subtask_assigned(client):
    from datetime import datetime, timezone

    from app.domain import Assignment

    draft_id, _ = _split_draft(client)
    data = client.post(
        f"/chains/drafts/{draft_id}/materialize"
    ).json()
    client.app.state.store.assignments.append(
        Assignment(
            assignment_id="a1",
            task_id=data["task_ids"][0],
            worker_id="w_good",
            customer_id="c1",
            status="assigned",
            created_at=datetime.now(timezone.utc),
        )
    )
    assert (
        client.post(
            f"/chains/drafts/{draft_id}/materialize/rollback"
        ).status_code
        == 409
    )
