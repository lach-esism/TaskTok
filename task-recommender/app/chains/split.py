"""Split policy for dynamic task-chain splitting."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chains.split_rules import ModuleRule, rules_for
from app.domain import Task

_FLOAT_FIELDS = ("target_hours", "min_hours", "max_hours")
_INT_FIELDS = ("max_pieces", "min_batch_size", "default_batch_size")


@dataclass(frozen=True)
class SplitPolicy:
    """Thresholds governing when and how a task chain is split."""

    target_hours: float = 8.0
    min_hours: float = 1.0
    max_hours: float = 16.0
    max_pieces: int = 12
    min_batch_size: int = 50
    default_batch_size: int = 500


def _as_float(raw: object, field: str) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def _as_int(raw: object, field: str) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def parse_split_policy(raw: dict | None) -> SplitPolicy:
    """Build a validated SplitPolicy from a raw mapping or defaults."""
    values: dict[str, float | int] = {}
    for field in _FLOAT_FIELDS:
        values[field] = _as_float(
            (raw or {}).get(field, getattr(SplitPolicy, field)), field
        )
    for field in _INT_FIELDS:
        values[field] = _as_int(
            (raw or {}).get(field, getattr(SplitPolicy, field)), field
        )

    for field in (*_FLOAT_FIELDS, "min_batch_size", "default_batch_size"):
        if values[field] <= 0:
            raise ValueError(f"{field} must be greater than 0")
    if values["max_pieces"] < 1:
        raise ValueError("max_pieces must be at least 1")
    if values["target_hours"] < values["min_hours"]:
        raise ValueError(
            f"min_hours ({values['min_hours']}) must not exceed "
            f"target_hours ({values['target_hours']})"
        )
    if values["target_hours"] > values["max_hours"]:
        raise ValueError(
            f"target_hours ({values['target_hours']}) must not exceed "
            f"max_hours ({values['max_hours']})"
        )
    return SplitPolicy(**values)  # type: ignore[arg-type]


_LIST_MARKER = re.compile(
    r"^\s*(\d+[.、)]|[一二三四五六七八九十]+、|[-*•])\s*"
)
_SENTENCE_SPLIT = re.compile(r"[。；;\n]+")
_QUANTITY = re.compile(
    r"(\d[\d,]*)\s*(条|个|篇|页|张|字|词|章|节|款|套|人|单|段)"
)


@dataclass(frozen=True)
class RequirementItem:
    """One structured requirement extracted from a task description."""

    text: str
    module_key: str | None
    quantity: int | None
    unit: str | None = None


def _split_description(description: str) -> list[str]:
    parts: list[str] = []
    for chunk in _SENTENCE_SPLIT.split(description):
        text = _LIST_MARKER.sub("", chunk).strip()
        if text:
            parts.append(text)
    return parts


def _match_module(
    text: str, rules: tuple[ModuleRule, ...]
) -> str | None:
    lowered = text.lower()
    for rule in rules:
        if any(keyword.lower() in lowered for keyword in rule.keywords):
            return rule.key
    return None


def _quantity_match(text: str) -> tuple[int, str] | None:
    match = _QUANTITY.search(text)
    if match is None:
        return None
    return int(match.group(1).replace(",", "")), match.group(2)


def extract_quantity(text: str) -> int | None:
    """Return the first batch quantity in ``text``, or ``None``."""
    match = _quantity_match(text)
    return match[0] if match else None


def extract_structured_requirements(task: Task) -> list[RequirementItem]:
    """Extract ordered, de-duplicated requirements with module and batch."""
    rules = rules_for(task.category)
    parts = _split_description(task.description)
    if not parts:
        return [RequirementItem(task.title, None, None)]

    items: list[RequirementItem] = []
    seen: set[str] = set()
    for text in parts:
        if text in seen:
            continue
        seen.add(text)
        quantity_match = _quantity_match(text)
        items.append(
            RequirementItem(
                text=text,
                module_key=_match_module(text, rules),
                quantity=quantity_match[0] if quantity_match else None,
                unit=quantity_match[1] if quantity_match else None,
            )
        )
    return items
