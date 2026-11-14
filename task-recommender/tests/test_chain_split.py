import pytest

from app.chains.split import (
    RequirementItem,
    SplitPolicy,
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
