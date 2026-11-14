import pytest

from app.chains.split import (
    RequirementItem,
    SplitPolicy,
    apply_split,
    extract_quantity,
    extract_structured_requirements,
    parse_split_policy,
)
from app.chains.split_rules import batch_rule_for, rules_for


def test_split_policy_defaults():
    assert parse_split_policy(None) == SplitPolicy(8.0, 1.0, 16.0, 12, 50, 500)


def test_split_policy_accepts_overrides():
    policy = parse_split_policy({"target_hours": 4, "max_pieces": 6})
    assert policy.target_hours == 4.0
    assert policy.max_pieces == 6


def test_split_policy_rejects_inverted_band():
    with pytest.raises(ValueError, match="min_hours"):
        parse_split_policy({"min_hours": 10, "target_hours": 8})


def test_rules_for_unknown_category_is_empty():
    assert rules_for("unknown") == ()


def test_batch_rule_defaults_by_category():
    assert batch_rule_for("data_annotation").default_batch_size == 500
    assert batch_rule_for("translation_localization").default_batch_size == 2000


def test_extracts_numbered_requirements_and_modules(split_task_factory):
    items = extract_structured_requirements(
        split_task_factory("1. 后端接口开发；2. 前端页面；3. 联调测试。")
    )
    assert [item.text for item in items] == [
        "后端接口开发",
        "前端页面",
        "联调测试",
    ]
    assert [item.module_key for item in items] == [
        "backend",
        "frontend",
        "integration",
    ]


def test_parses_quantity_with_commas():
    assert extract_quantity("共 1,200 条数据") == 1200


def test_chinese_numeral_quantity_is_none():
    assert extract_quantity("约一千字") is None


def test_empty_description_falls_back_to_title(split_task_factory):
    items = extract_structured_requirements(split_task_factory(""))
    assert items == [RequirementItem("测试任务", None, None)]


def test_duplicate_requirements_are_removed(split_task_factory):
    items = extract_structured_requirements(
        split_task_factory("后端接口；后端接口；前端页面")
    )
    assert [item.text for item in items] == ["后端接口", "前端页面"]


def test_scales_template_hours_to_task_hours(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=48
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    total = sum(node.estimated_hours for node in draft.chain.nodes)
    assert abs(total - 48) <= 48 * 0.05


def test_splits_nodes_over_max_hours(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=64
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    task_nodes = [
        node for node in draft.chain.nodes if node.node_type == "task"
    ]
    assert task_nodes
    assert all(node.estimated_hours <= 16.0 + 0.01 for node in task_nodes)
    assert len(draft.chain.nodes) <= 12


def test_batch_quantity_splits_annotation_node(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "标注 2500 条数据", category="data_annotation"
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    batches = [
        node
        for node in draft.chain.nodes
        if node.key.startswith("batch_annotation_")
    ]
    assert len(batches) == 5
    assert all("500 条" in node.split_reason for node in batches)


def test_no_evidence_falls_back_to_template(
    split_task_factory, split_draft_factory
):
    task = split_task_factory("完成这个项目", estimated_hours=40)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert all(node.split_source == "template" for node in draft.chain.nodes)
    assert draft.split_count == len(draft.chain.nodes)


def test_many_modules_converge_or_raise(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端；前端；数据看板；支付；会员；联调；测试；部署",
        estimated_hours=120,
    )
    try:
        draft = apply_split(
            split_draft_factory(task), task, SplitPolicy()
        )
    except ValueError as error:
        assert "max_pieces" in str(error)
    else:
        assert len(draft.chain.nodes) <= 12


def test_same_input_produces_same_split(
    split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=64
    )
    first = apply_split(split_draft_factory(task), task, SplitPolicy())
    second = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert [
        (node.key, round(node.estimated_hours, 4))
        for node in first.chain.nodes
    ] == [
        (node.key, round(node.estimated_hours, 4))
        for node in second.chain.nodes
    ]
