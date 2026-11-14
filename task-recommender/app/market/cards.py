"""Turn backend Tasks/Workers into the card fields the TaskTok frontend renders.

Field names follow ``frontend/js/data/mock.js`` (TASKS / APPLICANT_POOL) so
the frontend adapter only has to copy them.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.domain import Task, Worker
from app.nlp.lexicon import CATEGORY_LABELS

LEVEL_TEXT = {"L1": "简单执行", "L2": "专业任务", "L3": "复杂分析", "L4": "跨任务协调"}
VERIFY_LABELS = {"manual": "逐项核对", "metrics": "数据指标"}
# Covers that exist in frontend/assets; other categories use the data-bar cover.
CATEGORY_COVERS = {
    "consulting_research": "assets/cover-market-900.jpg",
    "software_dev": "assets/cover-robot-900.jpg",
    "data_annotation": "assets/cover-bio-900.jpg",
    "marketing_campaign": "assets/cover-funnel-900.jpg",
    "ecommerce_ops": "assets/cover-funnel-900.jpg",
}
# Card level from task difficulty (1–5); publishing maps back with LEVEL_DIFFICULTY.
LEVEL_DIFFICULTY = {"L1": 1, "L2": 2, "L3": 3, "L4": 5}
FEATURE_REASONS = {
    "skill": "技能匹配度",
    "preference": "与你偏好的类别和难度契合",
    "load": "当前负荷可以接下",
    "reputation": "历史口碑",
    "expertise": "同类任务经验",
    "collaborative": "相似执行者也做过",
}

_OUTPUTS = re.compile(r"主要交付物包括(.+?)。")


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def iso(value: datetime | None) -> str | None:
    return aware(value).isoformat() if value is not None else None


def card_level(difficulty: int) -> str:
    if difficulty <= 1:
        return "L1"
    if difficulty == 2:
        return "L2"
    if difficulty <= 4:
        return "L3"
    return "L4"


def yuan(amount: float) -> str:
    return f"¥{int(round(amount)):,}"


def deadline_text(deadline: datetime, now: datetime) -> tuple[str, int]:
    hours = max(0, int((aware(deadline) - aware(now)).total_seconds() // 3600))
    if hours < 72:
        return f"{hours} 小时", hours
    local = aware(deadline)
    return f"至 {local.month} 月 {local.day} 日", hours


def task_outputs(task: Task) -> list[str]:
    if task.meta.get("outputs"):
        return list(task.meta["outputs"])
    match = _OUTPUTS.search(task.description or "")
    if not match:
        return []
    return [part.strip() for part in re.split(r"[、，,]", match.group(1)) if part.strip()]


def task_reasons(breakdown: dict[str, float], worker: Worker | None) -> list[str]:
    """Chinese 'why recommended' lines from the score breakdown."""
    reasons = []
    for key, value in sorted(breakdown.items(), key=lambda kv: -kv[1]):
        label = FEATURE_REASONS.get(key)
        if label and value > 0 and len(reasons) < 2:
            reasons.append(f"{label} {round(value * 100)} 分")
    if worker is not None and worker.completed:
        rate = round(100 * worker.on_time / worker.completed)
        reasons.append(f"已完成 {worker.completed} 个任务，按时率 {rate}%")
    return reasons


def worker_card(worker: Worker, note: str = "", match: float | None = None) -> dict:
    """Applicant object, same shape as APPLICANT_POOL in mock.js."""
    on_time = round(100 * worker.on_time / worker.completed) if worker.completed else 0
    card = {
        "id": worker.worker_id,
        "name": worker.name,
        "avatar": worker.name[:1],
        "level": f"L{min(max(worker.level, 1), 4)}",
        "done": worker.completed,
        "onTime": on_time,
        "note": note,
    }
    if match is not None:
        card["match"] = round(match * 100)
    return card


def task_card(
    task: Task,
    *,
    poster: str,
    now: datetime,
    checks: list[str],
    match: float = 0.0,
    why: list[str] | None = None,
    applicants: int = 0,
    rate: int = 0,
) -> dict:
    level = task.meta.get("level") or card_level(task.difficulty)
    verify = task.meta.get("verify", "manual")
    outputs = task_outputs(task)
    accept = list(task.meta.get("accept") or task.requirements)
    deadline, hours = deadline_text(task.deadline, now)
    goal = (task.description or task.title).split("。")[0]
    contract = [
        ["目标", goal],
        ["交付物", "；".join(outputs) or "见任务说明"],
        ["验收方式", VERIFY_LABELS.get(verify, "逐项核对")],
    ]
    if task.budget_min and task.budget_max:
        contract.append(["预算区间", f"{yuan(task.budget_min)}–{yuan(task.budget_max)}"])
    return {
        "id": task.task_id,
        "title": task.title,
        "poster": poster,
        "avatar": poster[:1],
        "cover": CATEGORY_COVERS.get(task.category),
        "cat": CATEGORY_LABELS.get(task.category, task.category),
        "category": task.category,
        "level": level,
        "levelText": LEVEL_TEXT[level],
        "budget": yuan(task.budget),
        "budgetNum": round(task.budget),
        "deadline": deadline,
        "hours": hours,
        "match": round(match * 100),
        "applicants": applicants,
        "rate": rate,
        "publishedAt": iso(task.created_at),
        "verify": verify,
        "desc": task.description,
        "outputs": outputs,
        "accept": accept,
        "why": why or [],
        "contract": contract,
        "checks": checks or outputs,
    }
