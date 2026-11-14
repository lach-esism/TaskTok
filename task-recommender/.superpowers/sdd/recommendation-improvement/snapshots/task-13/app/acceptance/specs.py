"""Versioned acceptance specs for the first B2B research-task wedge."""

from __future__ import annotations

import uuid

from app.domain import AcceptanceCriterion, AcceptanceSpec

RESEARCH_SPEC_VERSION = 1


def research_criteria() -> list[AcceptanceCriterion]:
    """Ten criteria for a B2B market-research deliverable."""
    section_keys = [
        ("market_size", "包含市场规模章节"),
        ("customer_segments", "包含客户细分章节"),
        ("competitive_landscape", "包含竞争格局章节"),
        ("entry_recommendation", "包含进入建议章节"),
    ]
    criteria = [
        AcceptanceCriterion(
            key=f"{key}_section",
            label=label,
            dimension="completeness",
            layer="machine",
            required=True,
            weight=0.08,
            check_type="section_present",
            check_config={"section": key, "min_chars": 30},
        )
        for key, label in section_keys
    ]
    criteria.extend(
        [
            AcceptanceCriterion(
                key="sources",
                label="至少 8 个来源，且含 URL 与日期",
                dimension="evidence",
                layer="machine",
                required=True,
                weight=0.15,
                check_type="min_sources",
                check_config={
                    "min_count": 8,
                    "require_url": True,
                    "require_date": True,
                },
                evidence_required=True,
            ),
            AcceptanceCriterion(
                key="data_table",
                label="数据表含市场/规模/CAGR/来源字段",
                dimension="format",
                layer="machine",
                required=True,
                weight=0.10,
                check_type="table_schema",
                check_config={
                    "columns": ["market", "size", "cagr", "source"],
                    "min_rows": 3,
                },
            ),
            AcceptanceCriterion(
                key="tam_sam_som",
                label="TAM ≥ SAM ≥ SOM 且均为正数",
                dimension="accuracy",
                layer="machine",
                required=True,
                weight=0.08,
                check_type="arithmetic",
                check_config={"keys": ["tam", "sam", "som"]},
            ),
            AcceptanceCriterion(
                key="insight",
                label="洞察与决策价值",
                dimension="insight",
                layer="customer",
                required=False,
                weight=0.20,
                check_type="manual",
            ),
            AcceptanceCriterion(
                key="citation_consistency",
                label="引用与结论一致",
                dimension="evidence",
                layer="peer",
                required=False,
                weight=0.10,
                check_type="manual",
            ),
            AcceptanceCriterion(
                key="deadline",
                label="在截止时间前提交",
                dimension="timeliness",
                layer="machine",
                required=True,
                weight=0.05,
                check_type="deadline",
                check_config={},
            ),
        ]
    )
    return criteria


def build_research_spec(task_id: str) -> AcceptanceSpec:
    return AcceptanceSpec(
        spec_id=uuid.uuid4().hex,
        task_id=task_id,
        version=RESEARCH_SPEC_VERSION,
        criteria=research_criteria(),
        accept_threshold=0.80,
        rework_threshold=0.50,
    )
