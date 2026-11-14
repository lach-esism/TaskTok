"""Turn split subtasks into independently dispatchable tasks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.chains.dag import validate_dag
from app.domain import DecompositionDraft, SubTask, Task, TaskChain

MATERIALIZATION_LOG = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "chains"
    / "materialized.jsonl"
)


def _as_aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def build_subtask_task(
    parent: Task,
    node: SubTask,
    chain: TaskChain,
    draft_id: str,
) -> Task:
    """Build a standalone Task from one split subtask."""
    total_hours = parent.estimated_hours
    difficulty = int(
        round(
            min(
                5,
                max(
                    1,
                    1
                    + 4
                    * node.estimated_hours
                    / max(total_hours, 1),
                ),
            )
        )
    )
    required_skills = dict(
        node.required_skills or parent.required_skills
    )
    acceptance = "；".join(node.acceptance)
    return Task(
        task_id="sub_" + uuid.uuid4().hex,
        customer_id=parent.customer_id,
        title=f"{parent.title}｜{node.title}",
        category=parent.category,
        required_skills=required_skills,
        required_level=parent.required_level,
        difficulty=difficulty,
        priority=parent.priority,
        estimated_hours=node.estimated_hours,
        deadline=node.deadline or parent.deadline,
        region=parent.region,
        remote_ok=parent.remote_ok,
        description=(
            f"{node.title}\n验收：{acceptance}\n"
            f"拆分依据：{node.split_reason}\n"
            f"任务链：{chain.chain_id}\n草稿：{draft_id}"
        ),
        status="open",
        budget=node.budget,
        requirements=list(node.acceptance),
        budget_min=node.budget,
        budget_max=node.budget,
        required_skill_weights={
            skill: weight
            for skill, weight in parent.required_skill_weights.items()
            if skill in required_skills
        },
        parent_task_id=parent.task_id,
        chain_id=chain.chain_id,
        subtask_key=node.key,
        split_source=node.split_source,
    )


def validate_materialization(
    draft: DecompositionDraft,
    parent: Task,
    planned: list[Task],
    has_parent_assignment: bool,
) -> list[str]:
    """Return every reason the draft cannot be materialized."""
    errors: list[str] = []
    if not planned:
        errors.append("no subtasks to materialize")
        return errors

    validation = validate_dag(draft.chain.nodes)
    if not validation.valid:
        errors.extend(
            f"invalid dag: {error}" for error in validation.errors
        )

    total_hours = sum(task.estimated_hours for task in planned)
    effective_hours = (
        parent.estimated_hours
        if parent.estimated_hours > 0
        else sum(node.estimated_hours for node in draft.chain.nodes)
    )
    if total_hours <= 0:
        errors.append("subtasks have no estimated hours")
    elif effective_hours > 0 and (
        abs(total_hours - effective_hours) / effective_hours > 0.05
    ):
        errors.append(
            f"hours mismatch: {total_hours:.2f} vs {effective_hours:.2f}"
        )

    total_budget = sum(task.budget for task in planned)
    if total_budget > parent.budget + 0.01:
        errors.append(
            f"budget exceeds parent: {total_budget:.2f} > "
            f"{parent.budget:.2f}"
        )

    parent_deadline = _as_aware(parent.deadline)
    now = datetime.now(timezone.utc)
    for task in planned:
        deadline = _as_aware(task.deadline)
        if deadline > parent_deadline:
            errors.append(
                f"deadline after parent: {task.task_id}"
            )
        if deadline < now:
            errors.append(f"deadline has passed: {task.task_id}")
        if task.estimated_hours <= 0:
            errors.append(f"invalid hours: {task.task_id}")
        if task.budget < 0:
            errors.append(f"invalid budget: {task.task_id}")
        if task.required_level < 1:
            errors.append(f"invalid required level: {task.task_id}")
        if not task.required_skills:
            errors.append(f"missing required skills: {task.task_id}")

    if has_parent_assignment:
        errors.append("parent task already has an assignment")
    return errors
