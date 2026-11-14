"""Split policy for dynamic task-chain splitting."""

from __future__ import annotations

from dataclasses import dataclass

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
