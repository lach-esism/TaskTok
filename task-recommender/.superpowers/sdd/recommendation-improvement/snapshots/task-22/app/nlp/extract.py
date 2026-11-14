"""Structured field extraction v2 for free-form task postings (no LLM).

Every field is returned as ``{"value": ..., "confidence": float, "evidence":
str}`` so downstream callers can show *what* was found and *why*. Evidence is
the matched span in the normalized text. Post-validation is applied after
extraction:

* ``budget``: ``[min, max]`` with ``min <= max`` enforced (swapped when
  reversed), units 万/千 handled;
* ``date`` (deadline): must be strictly in the future relative to ``now``;
* ``skills``: matched phrases are mapped through the taxonomy and unknown
  phrases are dropped.

No ground-truth or label storage is read here; the module only consumes the
caller-supplied text and the lexicons in :mod:`app.nlp.lexicon`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.nlp.lexicon import SKILL_KEYWORDS, normalize_skill
from app.nlp.normalize import normalize_text

_NUM = r"\d[\d,]*(?:\.\d+)?"

_BUDGET_RANGE_RE = re.compile(
    rf"(?<!\d)({_NUM})\s*(万|千|w|k)?\s*元?\s*[-~至到]\s*"
    rf"({_NUM})\s*(万|千|w|k)?\s*元?(?!\d)"
)
_BUDGET_UNIT_RE = re.compile(r"元|万|千|w|k", re.IGNORECASE)
_BUDGET_SINGLE_RE = re.compile(
    rf"(?:预算|报酬|薪酬|费用|价格|总价|稿费|佣金|服务费|报价|总预算)\s*"
    rf"(?:为|是|约|大概|在|：|:)?\s*"
    rf"({_NUM})\s*(万|千|w|k)?\s*元?"
)
_BUDGET_BARE_RE = re.compile(rf"({_NUM})\s*(万|千|w|k)\s*元?\s*预算")

_CN_NUM = r"[一二两三四五六七八九十百千万亿\d]+"
_DAYS_RE = re.compile(rf"({_CN_NUM})\s*(?:个)?(?:工作日|天|日)(?:内|以内)?")
_WEEKS_RE = re.compile(rf"({_CN_NUM})\s*(?:个)?(?:周|星期|礼拜)(?:内|以内)?")
_MONTHS_RE = re.compile(rf"({_CN_NUM})\s*(?:个)?月(?:内|以内)?")

_ISO_DATE_RE = re.compile(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")
_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DEADLINE_CUE_RE = re.compile(r"(?:截止|截止日期|截止时间|deadline)\s*[:：]?\s*")

_REMOTE_CUES = ("远程", "线上", "居家", "异地")
_ONSITE_CUES = ("现场", "线下", "驻场", "到岗", "坐班")

_COUNT_RE = re.compile(
    rf"({_CN_NUM})\s*(万|千|百)?\s*(张|个|条|篇|份|支|套|次|场|人|名|家|款|期|节|门|页|帧)"
)

_EXPERIENCE_RANGE_RE = re.compile(
    rf"({_NUM})\s*(?:-|~|至)\s*({_NUM})\s*年"
)
_EXPERIENCE_RE = re.compile(
    rf"({_CN_NUM})\s*年(?:以上|及以上|左右|经验|工作经验|相关经验)?"
)

_LANGUAGES = {
    "中文": ("中文", "汉语", "普通话", "简体中文", "繁体中文"),
    "英文": ("英文", "英语", "english"),
    "日文": ("日文", "日语", "japanese"),
    "韩文": ("韩文", "韩语", "朝鲜语"),
    "法文": ("法文", "法语"),
    "德文": ("德文", "德语"),
    "西班牙文": ("西班牙文", "西班牙语", "西语"),
    "俄文": ("俄文", "俄语"),
    "阿拉伯文": ("阿拉伯文", "阿拉伯语"),
    "葡萄牙文": ("葡萄牙文", "葡萄牙语"),
}
_LANG_LOOKUP = {
    alias.lower(): canonical
    for canonical, aliases in _LANGUAGES.items()
    for alias in aliases
}

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _now_utc(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _to_int(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    value = 0
    section = 0
    for char in token:
        if char in _CN_DIGITS:
            section = _CN_DIGITS[char]
        elif char == "十":
            value += (section or 1) * 10
            section = 0
        elif char == "百":
            value += (section or 1) * 100
            section = 0
        elif char == "千":
            value += (section or 1) * 1000
            section = 0
        elif char == "万":
            value = (value + section) * 10000
            section = 0
        else:
            return None
    return value + section if token else None


def _amount(number: str, unit: str | None) -> float:
    value = float(number.replace(",", ""))
    unit = (unit or "").lower()
    if unit in {"万", "w"}:
        return value * 10000.0
    if unit in {"千", "k"}:
        return value * 1000.0
    return value


def _span(normalized: str, match: re.Match) -> str:
    return normalized[match.start():match.end()].strip()


def _extract_budget(normalized: str) -> dict:
    # A bare "2026-12" or "12-05" date fragment must never be read as money.
    # Require a currency unit inside the matched range.
    for match in _BUDGET_RANGE_RE.finditer(normalized):
        if not _BUDGET_UNIT_RE.search(match.group(0)):
            continue
        low = _amount(match.group(1), match.group(2))
        high = _amount(match.group(3), match.group(4))
        if match.group(4) and not match.group(2):
            low *= 10000.0 if (match.group(4).lower() in {"万", "w"}) else 1000.0
        elif match.group(2) and not match.group(4):
            high *= 10000.0 if (match.group(2).lower() in {"万", "w"}) else 1000.0
        low, high = sorted((low, high))
        return {
            "value": [low, high],
            "confidence": 0.92,
            "evidence": _span(normalized, match),
        }

    match = _BUDGET_SINGLE_RE.search(normalized)
    if match:
        value = _amount(match.group(1), match.group(2))
        return {
            "value": [value, value],
            "confidence": 0.85,
            "evidence": _span(normalized, match),
        }

    match = _BUDGET_BARE_RE.search(normalized)
    if match:
        value = _amount(match.group(1), match.group(2))
        return {
            "value": [value, value],
            "confidence": 0.6,
            "evidence": _span(normalized, match),
        }
    return {"value": None, "confidence": 0.0, "evidence": ""}


def _extract_duration(normalized: str) -> dict:
    match = _DAYS_RE.search(normalized)
    if match:
        value = _to_int(match.group(1))
        if value is not None and 1 <= value <= 3660:
            return {"value": value, "confidence": 0.9, "evidence": _span(normalized, match)}
    match = _WEEKS_RE.search(normalized)
    if match:
        value = _to_int(match.group(1))
        if value is not None and 1 <= value <= 520:
            return {"value": value * 7, "confidence": 0.9, "evidence": _span(normalized, match)}
    match = _MONTHS_RE.search(normalized)
    if match:
        value = _to_int(match.group(1))
        if value is not None and 1 <= value <= 120:
            return {"value": value * 30, "confidence": 0.8, "evidence": _span(normalized, match)}
    return {"value": None, "confidence": 0.0, "evidence": ""}


def _extract_date(normalized: str, now: datetime) -> dict:
    candidates: list[tuple[str, str, float]] = []
    for match in _ISO_DATE_RE.finditer(normalized):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        value = f"{year:04d}-{month:02d}-{day:02d}"
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        cue = _DEADLINE_CUE_RE.search(normalized, 0, match.start())
        confidence = 0.95 if cue else 0.8
        candidates.append((value, _span(normalized, match), confidence))

    for match in _MONTH_DAY_RE.finditer(normalized):
        month, day = int(match.group(1)), int(match.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        if any(item[0].endswith(f"-{month:02d}-{day:02d}") for item in candidates):
            continue
        year = now.year
        value = f"{year:04d}-{month:02d}-{day:02d}"
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if parsed <= now:
            value = f"{year + 1:04d}-{month:02d}-{day:02d}"
        candidates.append((value, _span(normalized, match), 0.6))

    # Prefer a deadline-cued full date, then the first future full date.
    for value, evidence, confidence in candidates:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if parsed > now:
            return {"value": value, "confidence": confidence, "evidence": evidence}
    return {"value": None, "confidence": 0.0, "evidence": ""}


def _extract_remote(normalized: str) -> dict:
    for cue in _REMOTE_CUES:
        if cue in normalized:
            return {"value": True, "confidence": 0.85, "evidence": cue}
    for cue in _ONSITE_CUES:
        if cue in normalized:
            return {"value": False, "confidence": 0.85, "evidence": cue}
    return {"value": None, "confidence": 0.0, "evidence": ""}


def _extract_count(normalized: str) -> dict:
    match = _COUNT_RE.search(normalized)
    if match:
        base = _to_int(match.group(1))
        if base is None:
            return {"value": None, "confidence": 0.0, "evidence": ""}
        unit = match.group(2)
        if unit == "万":
            base *= 10000
        elif unit == "千":
            base *= 1000
        elif unit == "百":
            base *= 100
        if base > 0:
            return {"value": base, "confidence": 0.8, "evidence": _span(normalized, match)}
    return {"value": None, "confidence": 0.0, "evidence": ""}


def _extract_experience(normalized: str) -> dict:
    match = _EXPERIENCE_RANGE_RE.search(normalized)
    if match:
        low = float(match.group(1).replace(",", ""))
        high = float(match.group(2).replace(",", ""))
        return {
            "value": min(low, high),
            "confidence": 0.85,
            "evidence": _span(normalized, match),
        }
    match = _EXPERIENCE_RE.search(normalized)
    if match:
        value = _to_int(match.group(1))
        if value is not None and 0 <= value <= 60:
            return {"value": float(value), "confidence": 0.8, "evidence": _span(normalized, match)}
    return {"value": None, "confidence": 0.0, "evidence": ""}


def _extract_languages(normalized: str) -> dict:
    lowered = normalized.lower()
    found: list[str] = []
    evidence: list[str] = []
    for alias, canonical in _LANG_LOOKUP.items():
        if alias in lowered and canonical not in found:
            found.append(canonical)
            evidence.append(alias)
    return {
        "value": found,
        "confidence": (0.85 if found else 0.0),
        "evidence": "、".join(evidence),
    }


def _extract_skills(normalized: str) -> dict:
    lowered = normalized
    matched: dict[str, str] = {}
    for skill, phrases in SKILL_KEYWORDS.items():
        for phrase in phrases:
            if phrase in lowered:
                matched[skill] = phrase
                break
    # Also pick up multi-token keywords from the alias normalizer so that
    # ``后端开发`` normalizes to ``backend`` even when ``后端开发`` is not an
    # exact SKILL_KEYWORDS phrase.
    for alias in ("后端开发", "前端开发", "数据分析", "平面设计", "视频剪辑", "课程开发"):
        if alias in lowered:
            skill = normalize_skill(alias)
            if skill and skill not in matched:
                matched[skill] = alias
    value = sorted(matched)
    return {
        "value": value,
        "confidence": (0.9 if value else 0.0),
        "evidence": matched,
    }


def extract_fields_v2(text: str | None, now: datetime | None = None) -> dict:
    """Extract structured fields with value, confidence, and evidence.

    Returns one entry per field. ``date`` is the deadline (must be > ``now``),
    ``budget.value`` is ``[min, max]`` (equal when a single amount is given),
    and ``skills.value`` only contains taxonomy keys.
    """
    normalized = normalize_text(text)
    now = _now_utc(now)

    budget = _extract_budget(normalized)
    if budget["value"] is not None:
        low, high = budget["value"]
        budget["value"] = [min(low, high), max(low, high)]

    date = _extract_date(normalized, now)

    return {
        "budget": budget,
        "duration": _extract_duration(normalized),
        "date": date,
        "remote": _extract_remote(normalized),
        "count": _extract_count(normalized),
        "experience": _extract_experience(normalized),
        "language": _extract_languages(normalized),
        "skills": _extract_skills(normalized),
    }
