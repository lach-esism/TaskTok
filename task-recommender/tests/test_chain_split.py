import pytest

from app.chains.split import SplitPolicy, parse_split_policy
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
