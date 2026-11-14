"""Two-layer capability evaluation for the resume push demo.

Static dimensions come from the parsed resume draft. Dynamic dimensions are
deterministic simulations of acceptance outcomes for tasks the user accepted;
the UI labels them as simulated. The system is intentionally transparent:
every score is a fixed rule, not a trained model.
"""

from __future__ import annotations

from statistics import mean

STATIC_WEIGHTS = {
    "skill_breadth": 0.20,
    "domain_expertise": 0.30,
    "experience": 0.20,
    "focus": 0.15,
    "completeness": 0.15,
}

DYNAMIC_WEIGHTS = {
    "first_pass": 0.30,
    "acceptance_score": 0.30,
    "on_time": 0.20,
    "rework": 0.10,
    "dispute": 0.10,
}

STATIC_LABELS = {
    "skill_breadth": "技能广度",
    "domain_expertise": "领域专业度",
    "experience": "经验等级",
    "focus": "领域聚焦度",
    "completeness": "简历完整度",
}

DYNAMIC_LABELS = {
    "first_pass": "一次通过率",
    "acceptance_score": "平均验收分",
    "on_time": "按时率",
    "rework": "返工率（反向）",
    "dispute": "争议率（反向）",
}

COMPLETION_WEIGHTS = {
    "requirement_coverage": 0.30,
    "quality": 0.25,
    "timeliness": 0.20,
    "completeness": 0.15,
    "communication": 0.10,
}

COMPLETION_LABELS = {
    "requirement_coverage": "需求覆盖",
    "quality": "交付质量",
    "timeliness": "时效",
    "completeness": "完整度",
    "communication": "沟通",
}

OVERALL_WEIGHTS = {"static": 0.6, "dynamic": 0.4}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _score(value: float) -> float:
    return round(_clamp(value) * 100.0, 1)


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _dimension(key: str, label: str, score: float, weight: float, layer: str, detail: str) -> dict:
    return {
        "key": key,
        "label": label,
        "score": score,
        "weight": weight,
        "layer": layer,
        "detail": detail,
    }


def _categories(draft: dict) -> list[dict]:
    raw = draft.get("categories")
    if isinstance(raw, list):
        output = []
        for item in raw:
            if isinstance(item, dict) and item.get("category"):
                try:
                    confidence = _clamp(float(item.get("confidence", 0.0)))
                except (TypeError, ValueError):
                    confidence = 0.0
                output.append(
                    {
                        "category": str(item["category"]),
                        "confidence": confidence,
                    }
                )
        if output:
            return output
    preferred = draft.get("preferred_categories") or {}
    if isinstance(preferred, dict):
        return [
            {"category": str(category), "confidence": _clamp(float(value))}
            for category, value in preferred.items()
        ]
    return []


def _static_dimensions(draft: dict) -> list[dict]:
    skills = draft.get("skills") or {}
    specialties = draft.get("specialties") or {}
    categories = _categories(draft)
    try:
        level = int(draft.get("level", 0))
    except (TypeError, ValueError):
        level = 0

    breadth = _score(min(1.0, len(skills) / 8.0))
    if categories:
        total_confidence = sum(item["confidence"] for item in categories)
        if total_confidence > 0:
            expertise = sum(
                item["confidence"]
                * _clamp(float(specialties.get(item["category"], 3)) / 5.0)
                for item in categories
            ) / total_confidence
            focus = max(item["confidence"] for item in categories) / total_confidence
        else:
            expertise = 0.0
            focus = 0.0
    elif specialties:
        expertise = mean(_clamp(float(value) / 5.0) for value in specialties.values())
        focus = 0.5
    else:
        expertise = 0.0
        focus = 0.0

    experience = _score(level / 5.0)
    present = [
        bool(skills),
        bool(categories),
        level > 1,
        bool(str(draft.get("region") or "").strip()),
        draft.get("remote_ok") is not None,
        bool(draft.get("expected_pay"))
        or bool(draft.get("expected_pay_period")),
    ]
    completeness = _score(sum(1 for item in present if item) / len(present))

    return [
        _dimension(
            "skill_breadth",
            STATIC_LABELS["skill_breadth"],
            breadth,
            STATIC_WEIGHTS["skill_breadth"],
            "static",
            f"识别 {len(skills)} 项技能",
        ),
        _dimension(
            "domain_expertise",
            STATIC_LABELS["domain_expertise"],
            _score(expertise),
            STATIC_WEIGHTS["domain_expertise"],
            "static",
            f"加权领域专长 {expertise:.2f}",
        ),
        _dimension(
            "experience",
            STATIC_LABELS["experience"],
            experience,
            STATIC_WEIGHTS["experience"],
            "static",
            f"L{level} / 5",
        ),
        _dimension(
            "focus",
            STATIC_LABELS["focus"],
            _score(focus),
            STATIC_WEIGHTS["focus"],
            "static",
            f"最高领域占比 {focus * 100:.0f}%",
        ),
        _dimension(
            "completeness",
            STATIC_LABELS["completeness"],
            completeness,
            STATIC_WEIGHTS["completeness"],
            "static",
            f"识别 {sum(1 for item in present if item)}/6 项",
        ),
    ]


def auto_completion(
    features: dict[str, float],
    score: float,
) -> dict:
    """Deterministic first-pass completion scores for a pushed task."""
    score = _clamp(float(score))
    skill = _clamp(float(features.get("skill", 0.5)))
    expertise = _clamp(float(features.get("expertise", 0.5)))
    preference = _clamp(float(features.get("preference", 0.5)))
    load = _clamp(float(features.get("load", 0.5)))
    customer = _clamp(float(features.get("customer_preference", 0.5)))
    dimensions = {
        "requirement_coverage": _score(
            0.7 * skill + 0.3 * customer
        ),
        "quality": _score(0.55 + 0.45 * score),
        "timeliness": _score(load),
        "completeness": _score(
            0.6 * expertise + 0.4 * preference
        ),
        "communication": _score(0.5 + 0.5 * customer),
    }
    total = round(
        sum(
            dimensions[key] * COMPLETION_WEIGHTS[key]
            for key in COMPLETION_WEIGHTS
        ),
        1,
    )
    return {
        "dimensions": dimensions,
        "total": total,
        "weights": dict(COMPLETION_WEIGHTS),
        "auto": True,
    }


def normalize_completion(completion) -> dict | None:
    """Validate a manual completion record and recompute its total."""
    if not isinstance(completion, dict):
        return None
    raw = completion.get("dimensions")
    if not isinstance(raw, dict):
        return None
    dimensions = {}
    for key in COMPLETION_WEIGHTS:
        if key not in raw:
            return None
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            return None
        dimensions[key] = round(_clamp(value / 100.0) * 100.0, 1)
    total = round(
        sum(
            dimensions[key] * COMPLETION_WEIGHTS[key]
            for key in COMPLETION_WEIGHTS
        ),
        1,
    )
    return {
        "dimensions": dimensions,
        "total": total,
        "weights": dict(COMPLETION_WEIGHTS),
    }


def _dynamic_dimensions(accepted: list[dict]) -> tuple[list[dict], int]:
    samples = [item for item in accepted if isinstance(item, dict)]
    if not samples:
        return [], 0
    first_pass = []
    ratings = []
    on_time = []
    rework = []
    dispute = []
    for item in samples:
        completion = normalize_completion(item.get("completion"))
        if completion is not None:
            dimension_scores = completion["dimensions"]
            total = completion["total"]
            first_pass.append(
                1.0
                if (
                    total >= 60.0
                    and min(dimension_scores.values()) >= 40.0
                )
                else 0.0
            )
            ratings.append(1.0 + 4.0 * (total / 100.0))
            on_time.append(
                1.0 if dimension_scores["timeliness"] >= 60.0 else 0.0
            )
            rework.append(
                1.0
                if (
                    total < 55.0
                    or dimension_scores["quality"] < 50.0
                )
                else 0.0
            )
            dispute.append(
                1.0
                if (
                    total < 40.0
                    or dimension_scores["communication"] < 30.0
                )
                else 0.0
            )
            continue
        try:
            score = _clamp(float(item.get("score", 0.0)))
            load = _clamp(float(item.get("load", score)))
        except (TypeError, ValueError):
            score = 0.0
            load = 0.0
        quality = _clamp(0.55 + 0.45 * score)
        ratings.append(1.0 + 4.0 * quality)
        is_rework = score < 0.5
        is_dispute = score < 0.35
        rework.append(1.0 if is_rework else 0.0)
        dispute.append(1.0 if is_dispute else 0.0)
        first_pass.append(
            0.0 if (is_rework or is_dispute) else 1.0
        )
        on_time.append(
            1.0 if (load >= 0.45 and score >= 0.4) else 0.0
        )

    count = len(samples)
    dimensions = [
        _dimension(
            "first_pass",
            DYNAMIC_LABELS["first_pass"],
            _score(sum(first_pass) / count),
            DYNAMIC_WEIGHTS["first_pass"],
            "dynamic",
            f"{int(sum(first_pass))}/{count} 次首发通过",
        ),
        _dimension(
            "acceptance_score",
            DYNAMIC_LABELS["acceptance_score"],
            _score((mean(ratings) - 1.0) / 4.0),
            DYNAMIC_WEIGHTS["acceptance_score"],
            "dynamic",
            f"平均 {mean(ratings):.2f} / 5",
        ),
        _dimension(
            "on_time",
            DYNAMIC_LABELS["on_time"],
            _score(sum(on_time) / count),
            DYNAMIC_WEIGHTS["on_time"],
            "dynamic",
            f"{int(sum(on_time))}/{count} 次按时",
        ),
        _dimension(
            "rework",
            DYNAMIC_LABELS["rework"],
            _score(1.0 - sum(rework) / count),
            DYNAMIC_WEIGHTS["rework"],
            "dynamic",
            f"返工 {int(sum(rework))}/{count}",
        ),
        _dimension(
            "dispute",
            DYNAMIC_LABELS["dispute"],
            _score(1.0 - sum(dispute) / count),
            DYNAMIC_WEIGHTS["dispute"],
            "dynamic",
            f"争议 {int(sum(dispute))}/{count}",
        ),
    ]
    return dimensions, count


def _weighted(dimensions: list[dict]) -> float:
    total = sum(item["weight"] for item in dimensions)
    if total <= 0:
        return 0.0
    return round(
        sum(item["score"] * item["weight"] for item in dimensions) / total,
        1,
    )


def evaluate_capability(
    draft: dict,
    accepted: list[dict] | None = None,
) -> dict:
    """Return static + simulated fulfillment capability for a resume draft."""
    static_dimensions = _static_dimensions(draft)
    static_overall = _weighted(static_dimensions)
    dynamic_dimensions, samples = _dynamic_dimensions(accepted or [])
    dynamic_available = samples > 0
    dynamic_overall = _weighted(dynamic_dimensions) if dynamic_available else None

    if dynamic_available and dynamic_overall is not None:
        overall = round(
            OVERALL_WEIGHTS["static"] * static_overall
            + OVERALL_WEIGHTS["dynamic"] * dynamic_overall,
            1,
        )
    else:
        overall = static_overall

    combined = list(static_dimensions)
    if dynamic_available:
        combined.extend(dynamic_dimensions)
    ranked = sorted(combined, key=lambda item: item["score"], reverse=True)

    return {
        "static": {
            "overall": static_overall,
            "grade": _grade(static_overall),
            "dimensions": static_dimensions,
        },
        "dynamic": {
            "available": dynamic_available,
            "overall": dynamic_overall,
            "grade": _grade(dynamic_overall) if dynamic_overall is not None else None,
            "samples": samples,
            "dimensions": dynamic_dimensions,
            "note": (
                "动态分为模拟履约结果，不是真实验收记录。"
                if dynamic_available
                else "接单后才会生成模拟履约数据。"
            ),
        },
        "overall": overall,
        "grade": _grade(overall),
        "weights": dict(OVERALL_WEIGHTS),
        "strengths": ranked[:2],
        "gaps": list(reversed(ranked[-2:])),
        "note": "静态分来自简历解析；动态分为确定性模拟，规则写在页面口径中。",
    }
