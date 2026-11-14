"""Checks for the standalone natural-language resume push-feed page."""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "resume-feed.html"


def test_resume_feed_page_is_self_contained():
    html = PAGE.read_text(encoding="utf-8")

    for marker in (
        "自然语言简历",
        "刷新",
        "自动刷",
        "上滑",
        "/resume/analyze",
        "/demo/resume/refresh",
        "接单",
        "跳过",
        "能力评价",
        "静态能力画像",
        "动态履约",
        "完成度",
        "需求覆盖",
        "提交并评价",
        "我的任务",
        "交付说明",
        "localStorage",
        "调试数据",
    ):
        assert marker in html

    assert not re.search(
        r"<(?:script|link)[^>]+(?:src|href)=[\"']https?://", html
    )
    assert "<textarea" in html
    # The modal uses display:grid, so the UA [hidden] rule needs an override
    # or closeTaskModal() cannot visually hide it.
    assert "[hidden]" in html
    assert "display:none !important" in html
