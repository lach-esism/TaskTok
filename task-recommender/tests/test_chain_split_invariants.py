from datetime import datetime

from app.chains.dag import validate_dag
from app.chains.split import SplitPolicy, apply_split


def test_split_invariants_hold(split_task_factory, split_draft_factory):
    task = split_task_factory(
        "后端接口开发；前端页面；数据看板；支付模块", estimated_hours=72
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert 1 <= len(draft.chain.nodes) <= 12
    assert validate_dag(draft.chain.nodes).valid
    assert (
        abs(sum(node.estimated_hours for node in draft.chain.nodes) - 72)
        <= 72 * 0.05
    )


def test_budget_sums_to_parent_budget(split_task_factory, split_draft_factory):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=48, budget=24000
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert abs(sum(node.budget for node in draft.chain.nodes) - 24000) <= 0.01


def test_deadlines_do_not_exceed_parent(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=48
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert all(node.deadline <= task.deadline for node in draft.chain.nodes)


def test_zero_budget_and_zero_hours_do_not_divide_by_zero(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端接口开发；前端页面", estimated_hours=0, budget=0
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert all(node.budget == 0 for node in draft.chain.nodes)
    assert all(node.estimated_hours > 0 for node in draft.chain.nodes)


def test_naive_parent_deadline_is_supported(
    split_task_factory, split_draft_factory
):
    task = split_task_factory("后端接口开发", estimated_hours=16)
    task.deadline = datetime(2026, 12, 31)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert draft.chain.nodes
