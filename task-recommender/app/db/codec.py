"""Dataclass <-> JSON codec for the SQLite repository.

Domain entities are plain dataclasses. They are stored as one JSON document
per row (plus a few typed columns for querying). ``encode`` turns an entity
into JSON-safe primitives; ``decode`` rebuilds it from its type hints, so
nested dataclasses, datetimes and tuples round-trip without per-type code.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
import typing
from datetime import datetime, timezone
from functools import lru_cache


def encode(value):
    """Convert dataclasses / datetimes / tuples to JSON-safe primitives."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: encode(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [encode(item) for item in value]
    return value


def dumps(value) -> str:
    return json.dumps(encode(value), ensure_ascii=False, sort_keys=True)


@lru_cache(maxsize=None)
def _hints(cls) -> dict:
    module = sys.modules.get(cls.__module__)
    return typing.get_type_hints(cls, vars(module) if module else None)


def _decode_value(hint, value):
    if value is None:
        return None
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):
        options = [arg for arg in args if arg is not type(None)]
        return _decode_value(options[0], value) if options else value
    if hint is datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        return decode(hint, value)
    if origin is list:
        inner = args[0] if args else typing.Any
        return [_decode_value(inner, item) for item in value]
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_value(args[0], item) for item in value)
        if args:
            return tuple(
                _decode_value(arg, item) for arg, item in zip(args, value)
            )
        return tuple(value)
    if origin is dict:
        inner = args[1] if len(args) == 2 else typing.Any
        return {key: _decode_value(inner, item) for key, item in value.items()}
    if hint is float and isinstance(value, int):
        return float(value)
    return value


def decode(cls, payload: dict):
    """Rebuild dataclass ``cls`` from ``encode`` output; unknown keys are ignored."""
    hints = _hints(cls)
    kwargs = {}
    for item in dataclasses.fields(cls):
        if item.name in payload:
            kwargs[item.name] = _decode_value(
                hints.get(item.name, typing.Any), payload[item.name]
            )
    return cls(**kwargs)


def loads(cls, text: str):
    return decode(cls, json.loads(text))
