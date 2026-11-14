"""Tests for the standalone learning-process demo."""

from __future__ import annotations

import json
import re

from app.learning.demo_data import build_demo_data
from app.learning.demo_html import render_demo_html
from app.learning.weights import validate_weights


def test_demo_data_builds_linked_two_sided_feeds():
    data = build_demo_data(rounds=6)
    scenario = data["scenario"]
    pair = scenario["pair"]

    assert pair["task_id"] == scenario["task"]["id"]
    assert pair["worker_id"] == scenario["worker"]["id"]

    expected_gold = {
        "worker": pair["task_id"],
        "customer": pair["worker_id"],
    }
    for side in ("worker", "customer"):
        rounds = data[side]["rounds"]
        assert len(rounds) == 6
        for round_data in rounds:
            assert len(round_data["feed"]) == 5
            assert round_data["gold"] == expected_gold[side]
            assert {item["rank"] for item in round_data["feed"]} == {1, 2, 3, 4, 5}
            assert all(
                {"id", "title", "score", "rank", "is_gold"} <= set(item)
                for item in round_data["feed"]
            )
            validate_weights(round_data["weights_after"])
            assert 0.0 <= round_data["cosine_after"] <= 1.0


def test_demo_data_shows_learning_progress_on_both_sides():
    data = build_demo_data(rounds=12)

    for side in ("worker", "customer"):
        rounds = data[side]["rounds"]
        assert rounds[0]["gold_rank"] > 1
        assert rounds[-1]["gold_rank"] == 1
        assert rounds[-1]["cosine_after"] > rounds[0]["cosine_after"]


def test_demo_data_exposes_tag_matrix_and_case_wall():
    data = build_demo_data(rounds=12)

    assert len(data["scenarios"]) == 27
    assert data["baseline_key"] in data["scenarios"]
    assert len(data["case_wall"]) >= 8
    assert len({case["category"] for case in data["case_wall"]}) >= 6

    baseline = data["scenarios"][data["baseline_key"]]
    validate_weights(baseline["worker"]["initial_weights"])
    validate_weights(baseline["customer"]["initial_weights"])
    for scenario in data["scenarios"].values():
        assert scenario["worker"]["rounds"][-1]["gold_rank"] == 1
        assert scenario["customer"]["rounds"][-1]["gold_rank"] == 1


def test_domain_and_preference_tags_change_the_starting_point():
    data = build_demo_data(rounds=12)
    scenarios = data["scenarios"]

    def worker_initial_rank(key):
        return scenarios[key]["worker"]["rounds"][0]["gold_rank"]

    assert worker_initial_rank("video_production|none|none") <= worker_initial_rank(
        "all|none|none"
    )
    assert worker_initial_rank("all|none|none") <= worker_initial_rank(
        "ecommerce_ops|none|none"
    )

    baseline_weights = scenarios["all|none|none"]["worker"]["initial_weights"]
    quality_weights = scenarios["all|quality|none"]["worker"]["initial_weights"]
    assert baseline_weights != quality_weights
    validate_weights(quality_weights)


def test_render_demo_html_is_self_contained():
    html = render_demo_html(build_demo_data(rounds=4))

    assert "接单端" in html
    assert "任务端" in html
    assert "初始标签" in html
    assert "案例墙" in html
    assert "自定义案例" in html
    assert "window.__DEMO_DATA__" in html
    assert not re.search(
        r"<(?:script|link)[^>]+(?:src|href)=[\"']https?://", html
    )

    match = re.search(
        r"window\.__DEMO_DATA__ = (\{.*?\});\n", html, re.DOTALL
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert payload["scenario"]["pair"]["task_id"]
    assert len(payload["worker"]["rounds"]) == 4
