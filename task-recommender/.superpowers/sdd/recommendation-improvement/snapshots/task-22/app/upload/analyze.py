"""Deterministic analysis of uploaded task postings and resumes (no LLM).

Two entry points mirror the two upload directions:

* :func:`analyze_task_text` uses the Task 23 classifier plus evidence-bearing
  field extraction and returns a category, calibrated confidence, the top-3
  categories, and the fields the recommender needs.
* :func:`analyze_resume_text` uses the resume section parser, the skill
  lexicon/aliases, and small rule-based extractors for experience, region,
  remote preference and expected pay. It returns a draft ``Worker`` profile.

Neither function writes to the store. The API layer builds a temporary
``Task`` / ``Worker`` object from these results and only returns drafts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, fields as dataclass_fields
from datetime import datetime, timedelta, timezone

from app.domain import Task, Worker
from app.nlp.classifier import extract_fields, get_default_classifier
from app.nlp.extract import extract_fields_v2
from app.nlp.lexicon import CATEGORY_LABELS, SKILL_KEYWORDS, normalize_skill
from app.nlp.normalize import normalize_text
from app.nlp.sections import parse_resume_sections
from app.resume import CATEGORY_SKILLS, CITIES, REGION_LABELS

_MAX_SKILLS = 40
_MAX_SKILL_TOKEN_LENGTH = 30

_SKILL_HEADER_WORDS = {
    "技能",
    "专业技能",
    "技能特长",
    "核心技能",
    "技术栈",
    "擅长",
}
_SECTION_BOUNDARY_WORDS = {
    "教育经历",
    "教育背景",
    "教育",
    "学历",
    "学习经历",
    "工作经历",
    "工作经验",
    "职业经历",
    "工作",
    "任职经历",
    "项目经历",
    "项目经验",
    "项目",
    "证书",
    "认证",
    "资格证书",
    "证书与认证",
    "语言",
    "语言能力",
    "外语",
    "自我评价",
    "个人简介",
    "个人信息",
    "联系方式",
    "求职意向",
    "期望薪资",
    "兴趣爱好",
}

_TOKEN_SPLIT_RE = re.compile(r"[|;；·、,，/／\s()（）\[\]【】{}<>:：]+")
# Raw skill tokens are only kept when they are ASCII tool/language names
# (python, figma, ...). Chinese free text is already covered by the lexicon
# scan, and keeping arbitrary Chinese tokens would turn city/location lines
# into fake skills.
_RAW_SKILL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+#.]{1,29}$")
_GENERIC_SKILL_WORDS = {
    "熟练",
    "熟悉",
    "掌握",
    "精通",
    "了解",
    "使用",
    "具备",
    "能力",
    "经验",
    "相关",
    "以上",
    "负责",
    "参与",
    "技能",
    "专业",
    "良好",
    "较强",
}

# Raw tool/language tokens are mapped to a category for the inferred-category
# display. Unknown raw tokens still become worker skills; they simply do not
# vote on a category.
_RAW_SKILL_CATEGORY = {
    "python": "software_dev",
    "java": "software_dev",
    "golang": "software_dev",
    "go": "software_dev",
    "javascript": "software_dev",
    "typescript": "software_dev",
    "sql": "software_dev",
    "mysql": "software_dev",
    "postgresql": "software_dev",
    "redis": "software_dev",
    "react": "software_dev",
    "vue": "software_dev",
    "node": "software_dev",
    "docker": "software_dev",
    "kubernetes": "software_dev",
    "aws": "software_dev",
    "linux": "software_dev",
    "figma": "ui_ux_design",
    "sketch": "ui_ux_design",
    "axure": "ui_ux_design",
    "photoshop": "brand_design",
    "illustrator": "brand_design",
    "premiere": "video_production",
    "aftereffects": "video_production",
    "excel": "consulting_research",
    "tableau": "consulting_research",
    "ppt": "consulting_research",
}

_REMOTE_CUES = ("远程", "线上", "居家", "异地", "可远程")
_ONSITE_CUES = ("现场", "线下", "驻场", "到岗", "坐班", "坐班制")

_REGION_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "US",
        ("美国", *CITIES.get("US", [])),
    ),
    (
        "EU",
        ("欧洲", *CITIES.get("EU", [])),
    ),
    (
        "CN",
        ("中国", "中国大陆", "国内", *CITIES.get("CN", [])),
    ),
)

_EXPECTED_PAY_RE = re.compile(
    r"(?P<label>期望(?:薪资|薪酬|报酬|日薪|时薪|月薪)?|"
    r"薪资要求|报价|日薪|时薪|月薪)\s*[:：]?\s*"
    r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>万|千|k|w)?\s*元?"
    r"(?:\s*(?:/|每)\s*(?P<period>天|日|月|小时|时))?",
    re.IGNORECASE,
)
_PAY_UNIT_SCALE = {"万": 10000.0, "w": 10000.0, "千": 1000.0, "k": 1000.0}


def _utcnow(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Task analysis
# ---------------------------------------------------------------------------


def analyze_task_text(
    text: str, now: datetime | None = None
) -> dict:
    """Classify a posting and return its structured fields (no store write).

    Raises :class:`ValueError` for blank input so the API can return 422.
    """
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("任务文本不能为空")

    # Pass the original text so line-based requirement sentences survive;
    # the classifier normalizes internally for matching.
    prediction = get_default_classifier().predict(text, top_k=3, now=now)
    extracted = prediction.get("extracted") or extract_fields(normalized)
    fields_v2 = prediction.get("extracted_v2") or extract_fields_v2(
        normalized, now=now
    )

    budget = fields_v2.get("budget", {}).get("value")
    budget_min = budget_max = None
    if budget:
        budget_min, budget_max = min(budget), max(budget)

    skills = fields_v2.get("skills", {}).get("value") or extracted.get(
        "skills", []
    )
    remote_ok = fields_v2.get("remote", {}).get("value")
    if remote_ok is None:
        remote_ok = extracted.get("remote_ok")
    duration_days = fields_v2.get("duration", {}).get("value")
    deadline = fields_v2.get("date", {}).get("value")

    requirements = extracted.get("requirements") or []
    region = _infer_region(normalized)
    fields = {
        "budget": budget,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "duration_days": duration_days,
        "deadline": deadline,
        "skills": list(skills),
        "remote_ok": remote_ok,
        "requirements": list(requirements),
        "suggested_title": extracted.get("suggested_title", ""),
        "experience_years": fields_v2.get("experience", {}).get("value"),
        "language": fields_v2.get("language", {}).get("value", []),
        "region": region,
        "region_label": REGION_LABELS.get(region, "中国大陆"),
    }

    return {
        "category": prediction["category"],
        "label": prediction.get(
            "label", CATEGORY_LABELS.get(prediction["category"], "")
        ),
        "confidence": prediction.get(
            "calibrated_confidence", prediction.get("confidence", 0.0)
        ),
        "confidence_raw": prediction.get("confidence", 0.0),
        "needs_clarification": bool(prediction.get("needs_clarification")),
        "top_categories": list(prediction.get("candidates", []))[:3],
        "evidence": list(prediction.get("evidence", [])),
        "fields": fields,
        "fields_v2": fields_v2,
    }


def _parse_deadline(value: str | None, now: datetime) -> datetime:
    if value:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            parsed = parsed.replace(hour=23, minute=59, second=59)
            if parsed > now:
                return parsed
    return now + timedelta(days=14)


def task_from_analysis(
    analysis: dict,
    *,
    customer_id: str = "draft_customer",
    text: str = "",
    task_id: str | None = None,
    now: datetime | None = None,
) -> Task:
    """Build an in-memory ``Task`` that the recommender can score.

    The task is never inserted into the store. ``status`` stays ``open`` so
    eligibility rules behave exactly as they do for catalog tasks.
    """
    reference = _utcnow(now)
    fields = analysis.get("fields", {})
    digest = hashlib.sha256(
        normalize_text(text or analysis.get("category", "")).encode("utf-8")
    ).hexdigest()[:12]
    resolved_id = task_id or f"draft_task_{digest}"

    skills = [skill for skill in fields.get("skills", []) if skill]
    required_skills = {skill: 2 for skill in dict.fromkeys(skills)}
    duration = fields.get("duration_days")
    estimated_hours = max(
        4.0, min(float(duration) if duration else 8.0, 16.0)
    )
    budget_min = _as_float(fields.get("budget_min"))
    budget_max = _as_float(fields.get("budget_max"))
    if budget_min is None and budget_max is not None:
        budget_min = budget_max
    if budget_max is None and budget_min is not None:
        budget_max = budget_min
    budget = (
        (budget_min + budget_max) / 2.0
        if budget_min is not None and budget_max is not None
        else 0.0
    )

    return Task(
        task_id=resolved_id,
        customer_id=customer_id,
        title=fields.get("suggested_title") or "上传任务书",
        description=(text or "")[:4000],
        category=analysis.get("category", "consulting_research"),
        required_skills=required_skills,
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=estimated_hours,
        deadline=_parse_deadline(fields.get("deadline"), reference),
        region=fields.get("region") or "CN",
        remote_ok=(
            fields.get("remote_ok")
            if fields.get("remote_ok") is not None
            else True
        ),
        status="open",
        budget=budget,
        budget_min=budget_min or 0.0,
        budget_max=budget_max or 0.0,
        requirements=list(fields.get("requirements") or []),
    )


def build_task_draft(task: Task, analysis: dict) -> dict:
    """Return the JSON-safe draft payload shown to the user."""
    return {
        "task_id": task.task_id,
        "customer_id": task.customer_id,
        "title": task.title,
        "description": task.description,
        "category": task.category,
        "category_label": CATEGORY_LABELS.get(task.category, task.category),
        "required_skills": dict(task.required_skills),
        "required_level": task.required_level,
        "difficulty": task.difficulty,
        "priority": task.priority,
        "estimated_hours": task.estimated_hours,
        "deadline": task.deadline.isoformat(),
        "region": task.region,
        "region_label": REGION_LABELS.get(task.region, task.region),
        "remote_ok": task.remote_ok,
        "budget": task.budget,
        "budget_min": task.budget_min,
        "budget_max": task.budget_max,
        "requirements": list(task.requirements),
        "confidence": analysis.get("confidence", 0.0),
        "needs_clarification": analysis.get("needs_clarification", False),
        "status": "draft",
    }


# ---------------------------------------------------------------------------
# Resume analysis
# ---------------------------------------------------------------------------


def _infer_region(text: str) -> str:
    for region, cues in _REGION_CUES:
        if any(cue and cue in text for cue in cues):
            return region
    return "CN"


def _infer_remote_preference(text: str) -> bool | None:
    if any(cue in text for cue in _REMOTE_CUES):
        return True
    if any(cue in text for cue in _ONSITE_CUES):
        return False
    return None


def _canonical_skills_from_text(normalized: str) -> list[str]:
    lowered = normalized.lower()
    found: list[str] = []
    for skill, phrases in SKILL_KEYWORDS.items():
        if any(phrase.lower() in lowered for phrase in phrases):
            found.append(skill)
    return found


def _skills_section_lines(text: str) -> list[str]:
    lines = [
        normalize_text(line)
        for line in str(text or "").splitlines()
        if normalize_text(line)
    ]
    collected: list[str] = []
    inside = False
    for line in lines:
        header = line.strip().strip(":：").strip()
        if header in _SKILL_HEADER_WORDS:
            inside = True
            continue
        if header in _SECTION_BOUNDARY_WORDS:
            if inside:
                break
            inside = False
            continue
        if inside:
            if any(
                marker in line
                for marker in (
                    "期望",
                    "薪资",
                    "电话",
                    "邮箱",
                    "联系",
                    "地址",
                    "居住",
                    "城市",
                )
            ):
                break
            collected.append(line)
    return collected


def _clean_skill_token(token: str) -> str | None:
    token = token.strip().strip("。.、；;:：-*•·\"'“”‘’")
    if not token or len(token) > _MAX_SKILL_TOKEN_LENGTH:
        return None
    if token in _GENERIC_SKILL_WORDS:
        return None
    if token.isdigit():
        return None
    return token


def _raw_skill_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for line in _skills_section_lines(text):
        for token in _TOKEN_SPLIT_RE.split(line):
            cleaned = _clean_skill_token(token)
            if not cleaned:
                continue
            canonical = normalize_skill(cleaned)
            tokens.append(canonical or cleaned.lower())
    return tokens


def _collect_skills(text: str, normalized: str) -> list[str]:
    skills: list[str] = []
    for skill in _canonical_skills_from_text(normalized):
        if skill not in skills:
            skills.append(skill)
    for token in _raw_skill_tokens(text):
        if not token or token in skills:
            continue
        if _RAW_SKILL_RE.fullmatch(token):
            skills.append(token)
    return skills[:_MAX_SKILLS]


def _infer_categories(
    skills: list[str], normalized: str
) -> list[dict]:
    reverse = {
        skill: category
        for category, category_skills in CATEGORY_SKILLS.items()
        for skill in category_skills
    }
    scores: dict[str, float] = {}
    for skill in skills:
        category = reverse.get(skill) or _RAW_SKILL_CATEGORY.get(skill)
        if category:
            scores[category] = scores.get(category, 0.0) + 1.0

    if not scores:
        # Without recognizable skills, fall back to the task classifier as a
        # weak, clearly low-confidence signal.
        try:
            prediction = get_default_classifier().predict(normalized, top_k=3)
        except (ValueError, ImportError):
            return []
        return [
            {
                "category": item["category"],
                "label": item.get(
                    "label",
                    CATEGORY_LABELS.get(item["category"], item["category"]),
                ),
                "confidence": round(float(item["confidence"]), 4),
            }
            for item in prediction.get("candidates", [])[:3]
        ]

    top_score = max(scores.values())
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "category": category,
            "label": CATEGORY_LABELS.get(category, category),
            "confidence": round(score / top_score, 4),
        }
        for category, score in ranked[:3]
    ]


def _infer_expected_pay(text: str) -> dict:
    match = _EXPECTED_PAY_RE.search(text)
    if not match:
        return {"value": None, "period": None, "evidence": ""}
    value = float(match.group("amount").replace(",", ""))
    unit = (match.group("unit") or "").lower()
    value *= _PAY_UNIT_SCALE.get(unit, 1.0)
    period = match.group("period") or ""
    if not period:
        # Label-only forms such as “月薪 15000 元” and “期望时薪 100 元”
        # carry the period in the label rather than a “/月” suffix.
        label = match.group("label")
        if "月薪" in label:
            period = "月"
        elif "时薪" in label:
            period = "小时"
        elif "日薪" in label:
            period = "天"
    if period in {"日", "天"}:
        period = "天"
    elif period in {"时", "小时"}:
        period = "小时"
    return {
        "value": value,
        "period": period or None,
        "evidence": match.group(0).strip(),
    }


def _worker_level(experience_years: float) -> int:
    return max(1, min(5, 1 + int(experience_years // 2)))


def _worker_expected_pay(expected_pay: dict) -> float:
    """Return only a per-task-compatible pay figure.

    Monthly and hourly quotes cannot be compared with a task budget, so they
    stay in the analysis payload and map to ``0.0`` (unknown per-task pay).
    Per-day quotes and unqualified amounts are kept as-is.
    """
    value = expected_pay.get("value")
    if value is None:
        return 0.0
    if expected_pay.get("period") in {"月", "小时"}:
        return 0.0
    return float(value)


def _build_worker(
    skills: list[str],
    categories: list[dict],
    *,
    experience_years: float,
    region: str,
    remote_preference: bool | None,
    expected_pay: float,
    worker_id: str,
) -> Worker:
    top_score = categories[0]["confidence"] if categories else 1.0
    specialties = {
        item["category"]: max(
            1, min(5, 2 + int(round(item["confidence"] * 3)))
        )
        for item in categories
    }
    preferred_categories = {
        item["category"]: round(item["confidence"] / top_score, 3)
        for item in categories
    }
    return Worker(
        worker_id=worker_id,
        name="候选人草稿",
        skills={skill: 3 for skill in skills},
        specialties=specialties,
        level=_worker_level(experience_years),
        capacity_hours=40.0,
        current_load_hours=0.0,
        preferred_categories=preferred_categories,
        preferred_difficulty=(2, 4),
        region=region,
        remote_ok=(
            remote_preference if remote_preference is not None else True
        ),
        status="active",
        expected_pay=float(expected_pay or 0.0),
    )


def analyze_resume_text(
    text: str,
    now: datetime | None = None,
    worker_id: str | None = None,
) -> dict:
    """Parse a resume and return a draft ``Worker`` plus inferred profile.

    The draft is not written anywhere. ``worker_id`` is derived from a hash of
    the normalized text by default, so repeating an upload reuses the semantic
    text caches instead of growing them.
    """
    normalized_all = normalize_text(text)
    if not normalized_all or not re.search(r"[一-鿿A-Za-z0-9]", normalized_all):
        raise ValueError("简历文本不能为空")

    sections = parse_resume_sections(text, now=now)
    skills = _collect_skills(text, normalized_all)
    categories = _infer_categories(skills, normalized_all)
    experience_years = float(sections.get("experience_years") or 0.0)
    region = _infer_region(normalized_all)
    remote_preference = _infer_remote_preference(normalized_all)
    expected_pay = _infer_expected_pay(normalized_all)

    digest = hashlib.sha256(normalized_all.encode("utf-8")).hexdigest()[:12]
    resolved_worker_id = worker_id or f"draft_resume_{digest}"
    worker = _build_worker(
        skills,
        categories,
        experience_years=experience_years,
        region=region,
        remote_preference=remote_preference,
        expected_pay=_worker_expected_pay(expected_pay),
        worker_id=resolved_worker_id,
    )
    draft = asdict(worker)
    draft.update(
        {
            "draft": True,
            "categories": categories,
            "confidence": (
                categories[0]["confidence"] if categories else 0.0
            ),
            "expected_pay_period": expected_pay["period"],
        }
    )

    return {
        "sections": sections,
        "skills": skills,
        "categories": categories,
        "experience_years": experience_years,
        "region": region,
        "region_label": REGION_LABELS.get(region, region),
        "remote_preference": remote_preference,
        "expected_pay": expected_pay,
        "draft_worker": draft,
        "worker_id": resolved_worker_id,
    }


def worker_from_draft(draft: dict) -> Worker:
    """Rebuild a ``Worker`` from ``analyze_resume_text``'s draft payload."""
    known = {item.name for item in dataclass_fields(Worker)}
    values = {key: value for key, value in draft.items() if key in known}
    difficulty = values.get("preferred_difficulty", (2, 4))
    values["preferred_difficulty"] = tuple(difficulty)
    values.setdefault("worker_id", "draft_resume")
    return Worker(**values)
