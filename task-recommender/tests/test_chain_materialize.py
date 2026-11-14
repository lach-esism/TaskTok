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
