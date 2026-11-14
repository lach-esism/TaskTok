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
