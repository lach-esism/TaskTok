from datetime import datetime, timezone

from app.nlp.extract import extract_fields_v2

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_extract_budget_range_with_evidence():
    fields = extract_fields_v2(
        "我们要做一个会员小程序，预算 8,000–30,000 元，支持远程。", now=NOW
    )
    budget = fields["budget"]
    assert budget["value"] == [8000, 30000]
    assert budget["confidence"] > 0.8
    assert "8,000" in budget["evidence"] and "30,000" in budget["evidence"]


def test_extract_budget_shared_ten_thousand_unit():
    fields = extract_fields_v2("这个项目预算 1-2 万，两周内完成。", now=NOW)
    assert fields["budget"]["value"] == [10000, 20000]


def test_extract_budget_enforces_min_leq_max():
    fields = extract_fields_v2("预算 3-1 万。", now=NOW)
    low, high = fields["budget"]["value"]
    assert low <= high
    assert [low, high] == [10000, 30000]


def test_extract_budget_single_amount():
    fields = extract_fields_v2("招聘一名工程师，预算 8000 元。", now=NOW)
    assert fields["budget"]["value"] == [8000, 8000]


def test_date_fragment_is_not_parsed_as_budget():
    fields = extract_fields_v2(
        "需要一名工程师，截止 2026-12-05 交付，支持远程。", now=NOW
    )
    assert fields["budget"]["value"] is None
    assert fields["date"]["value"] == "2026-12-05"


def test_extract_duration_days_and_weeks():
    assert extract_fields_v2("期望 30 天内交付。", now=NOW)["duration"]["value"] == 30
    assert extract_fields_v2("两周内完成。", now=NOW)["duration"]["value"] == 14
    assert extract_fields_v2("一个月内完成。", now=NOW)["duration"]["value"] == 30


def test_extract_date_deadline_future_and_past():
    fields = extract_fields_v2("截止 2026-12-01 交付。", now=NOW)
    assert fields["date"]["value"] == "2026-12-01"
    assert fields["date"]["confidence"] > 0.8
    assert "2026-12-01" in fields["date"]["evidence"]

    past = extract_fields_v2("截止 2020-01-01 交付。", now=NOW)
    assert past["date"]["value"] is None


def test_extract_remote():
    assert extract_fields_v2("支持远程协作。", now=NOW)["remote"]["value"] is True
    assert extract_fields_v2("需要线下驻场。", now=NOW)["remote"]["value"] is False
    assert extract_fields_v2("普通需求。", now=NOW)["remote"]["value"] is None


def test_extract_count():
    assert extract_fields_v2("对 10 万张图片做标注。", now=NOW)["count"]["value"] == 100000
    assert extract_fields_v2("写 3 篇文章。", now=NOW)["count"]["value"] == 3


def test_extract_experience():
    fields = extract_fields_v2("要求 3 年以上相关经验。", now=NOW)
    assert fields["experience"]["value"] == 3.0


def test_extract_language():
    fields = extract_fields_v2("翻译成英文和日文。", now=NOW)
    assert fields["language"]["value"] == ["英文", "日文"]


def test_extract_skills_in_taxonomy():
    fields = extract_fields_v2("要求熟悉微信小程序和支付接口。", now=NOW)
    skills = fields["skills"]["value"]
    assert "frontend" in skills
    assert "backend" in skills
    # Unknown phrases never leak into the result.
    assert "量子计算" not in skills
    from app.nlp.lexicon import known_skills

    assert set(skills) <= known_skills()


def test_extract_fields_v2_evidence_spans_present():
    fields = extract_fields_v2(
        "预算 5000 元，10 天内交付，截止 2026-12-05，需要线下。", now=NOW
    )
    for key in ("budget", "duration", "date", "remote"):
        entry = fields[key]
        assert "value" in entry and "confidence" in entry and "evidence" in entry
    assert fields["budget"]["evidence"]
    assert fields["duration"]["evidence"]
    assert fields["date"]["evidence"]
    assert fields["remote"]["evidence"] == "线下"
