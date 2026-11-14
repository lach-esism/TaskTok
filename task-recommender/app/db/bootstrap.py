"""Open (or seed) the business database and restore serving state."""

from __future__ import annotations

import dataclasses
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.db.repository import Database, LoadedState
from app.domain import Assignment, Customer
from app.resume import build_resume

_CITY = list("沪京深杭苏蓉宁汉渝厦")
_BRAND = [
    "星河", "青禾", "远帆", "云栖", "知行", "拾光", "木石", "海川",
    "启明", "听澜", "南风", "银杏", "北辰", "若水", "长桥", "初见",
]
_TRADE = [
    "科技", "咨询", "消费品", "新能源", "生物医药", "文化传媒",
    "供应链", "数字营销", "教育", "智能制造",
]


def _company_name(customer_id: str) -> str:
    rng = random.Random(f"{customer_id}|company")
    return f"{rng.choice(_CITY)}{rng.choice(_BRAND)}{rng.choice(_TRADE)}"


def localize_names(store: Store) -> None:
    """Replace synthetic 'Customer N' / 'Worker N' with display names.

    Worker names reuse the resume generator so the resume page and the
    marketplace show the same person.
    """
    for customer in store.customers.values():
        if customer.name.startswith("Customer "):
            customer.name = _company_name(customer.customer_id)
    for worker in store.workers.values():
        if worker.name.startswith("Worker "):
            worker.name = build_resume(worker)["resume"]["name"]


def _shift(value, delta: timedelta):
    """Shift every datetime inside a dataclass/list/dict by ``delta``."""
    if isinstance(value, datetime):
        return value + delta
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _shift(item, delta)
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            value[key] = _shift(item, delta)
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            current = getattr(value, item.name)
            shifted = _shift(current, delta)
            if shifted is not current:
                setattr(value, item.name, shifted)
        return value
    return value


def align_clock(store: Store, test: list[Assignment], now: datetime | None = None) -> timedelta:
    """Move the synthetic timeline so the data clock lands on today.

    The generator writes a fixed calendar (history ends in 2026-08). The
    marketplace shows deadlines and publish times to people, so the whole
    history is shifted by a whole number of days; relative spacing, the
    train/test split and every recency feature are unchanged.
    """
    now = now or datetime.now(timezone.utc)
    reference = store.reference_time
    days = (now - reference).days
    if days <= 0:
        return timedelta(0)
    delta = timedelta(days=days)
    for collection in (
        store.workers.values(),
        store.tasks.values(),
        store.assignments,
        store.feedback,
        store.events,
        store.impressions,
        test,
    ):
        for item in collection:
            _shift(item, delta)
    # Index caches keyed on list identity would keep the old maximum.
    store._reference_ids = None
    return delta


def _seed_store() -> tuple[Store, list[Assignment]]:
    dataset = generate_dataset()
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.train_feedback,
        events=dataset.train_events,
        impressions=dataset.train_impressions,
    )
    localize_names(store)
    align_clock(store, dataset.test)
    return store, dataset.test


def open_database(path: Path | str) -> tuple[Database, LoadedState | None, Store, list[Assignment]]:
    """Return ``(db, loaded, store, test_assignments)``.

    ``loaded`` is ``None`` when the database was just seeded (nothing beyond
    the store to restore).
    """
    db = Database(path)
    if db.is_empty():
        store, test = _seed_store()
        db.sync(store, test_assignments=test)
        return db, None, store, test
    loaded = db.load()
    return db, loaded, loaded.store, loaded.test_assignments


__all__ = ["open_database", "localize_names", "align_clock", "Customer"]
