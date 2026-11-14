"""Tests for the resume capability evaluation system."""

from __future__ import annotations

from app.learning.capability import auto_completion, evaluate_capability
from app.upload.analyze import analyze_resume_text

RESUME = """张三，5 年视频制作经验，熟练使用 Premiere、After Effects、达芬奇。
做过品牌宣传片、短视频投放、分镜脚本和剪辑后期，服务过消费品牌。
期望月薪 8000 元，可远程。"""


def draft():
    return analyze_resume_text(RESUME)["draft_worker"]


def test_static_capability_has_five_dimensions():
    result = evaluate_capability(draft())

    static = result["static"]
    assert len(static["dimensions"]) == 5
    assert all(0 <= item["score"] <= 100 for item in static["dimensions"])
    assert 0 <= static["overall"] <= 100
    assert static["grade"] in {"A", "B", "C", "D"}
    assert result["dynamic"]["available"] is False
    assert result["overall"] == static["overall"]
    assert result["grade"] == static["grade"]


def test_dynamic_capability_grows_with_accepted_tasks():
    accepted = [
        {"task_id": "t1", "score": 0.8, "load": 0.7},
        {"task_id": "t2", "score": 0.75, "load": 0.65},
        {"task_id": "t3", "score": 0.6, "load": 0.55},
    ]
    result = evaluate_capability(draft(), accepted)

    dynamic = result["dynamic"]
    assert dynamic["available"] is True
    assert dynamic["samples"] == 3
    assert len(dynamic["dimensions"]) == 5
    assert 0 <= dynamic["overall"] <= 100
    assert result["weights"] == {"static": 0.6, "dynamic": 0.4}
    assert result["overall"] != result["static"]["overall"]


def test_low_quality_tasks_reduce_dynamic_score():
    good = evaluate_capability(
        draft(),
        [{"task_id": "t1", "score": 0.85, "load": 0.8}],
    )
    poor = evaluate_capability(
        draft(),
        [{"task_id": "t1", "score": 0.3, "load": 0.2}],
    )

    assert good["dynamic"]["overall"] > poor["dynamic"]["overall"]
    assert good["dynamic"]["samples"] == poor["dynamic"]["samples"] == 1


def test_auto_completion_has_five_dimensions():
    features = {
        "reputation": 0.8,
        "skill": 0.7,
        "expertise": 0.75,
        "collaborative": 0.2,
        "preference": 0.6,
        "load": 0.8,
        "customer_preference": 0.7,
    }
    completion = auto_completion(features, 0.82)

    assert set(completion["dimensions"]) == {
        "requirement_coverage",
        "quality",
        "timeliness",
        "completeness",
        "communication",
    }
    assert 0 <= completion["total"] <= 100
    assert completion["weights"]["requirement_coverage"] == 0.30


def test_manual_completion_drives_dynamic_metrics():
    strong = {
        "task_id": "t1",
        "score": 0.8,
        "load": 0.8,
        "completion": {
            "dimensions": {
                "requirement_coverage": 90,
                "quality": 90,
                "timeliness": 90,
                "completeness": 90,
                "communication": 90,
            }
        },
    }
    weak = {
        "task_id": "t2",
        "score": 0.8,
        "load": 0.8,
        "completion": {
            "dimensions": {
                "requirement_coverage": 40,
                "quality": 35,
                "timeliness": 20,
                "completeness": 45,
                "communication": 20,
            }
        },
    }

    strong_result = evaluate_capability(draft(), [strong])
    weak_result = evaluate_capability(draft(), [weak])

    assert strong_result["dynamic"]["overall"] > weak_result["dynamic"]["overall"]
    strong_on_time = next(
        item for item in strong_result["dynamic"]["dimensions"]
        if item["key"] == "on_time"
    )
    weak_on_time = next(
        item for item in weak_result["dynamic"]["dimensions"]
        if item["key"] == "on_time"
    )
    assert strong_on_time["score"] > weak_on_time["score"]


def test_strengths_and_gaps_are_reported():
    result = evaluate_capability(draft(), [])

    assert len(result["strengths"]) == 2
    assert len(result["gaps"]) == 2
    assert all("label" in item and "score" in item for item in result["strengths"])
