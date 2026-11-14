from datetime import datetime

from app.data.store import Store
from app.domain import Worker


def test_store_indexes_workers_and_computes_ratings():
    worker = Worker(
        worker_id="w1",
        name="A",
        skills={"python": 4},
        specialties={"software_dev": 3},
        level=3,
        capacity_hours=40,
        current_load_hours=0,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
        ratings=[5.0, 4.0],
    )
    store = Store(workers=[worker], customers=[], tasks=[], assignments=[], feedback=[])
    assert store.workers["w1"] is worker
    assert store.worker_ratings("w1") == [5.0, 4.0]
    assert store.worker_ratings("missing") == []
