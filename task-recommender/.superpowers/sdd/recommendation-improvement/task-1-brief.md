## Task 1: Domain Models, Store Extensions, and Dataset Split Helpers

**Files:**
- Modify: `app/domain.py`
- Modify: `app/data/store.py`
- Test: `tests/test_events.py` (create)

**Interfaces:**
- Consumes: existing dataclasses.
- Produces:
  - `Impression` and `RecommendationEvent` dataclasses (fields exactly as spec §5.1–5.2).
  - `Worker.expected_pay: float = 0.0`, `Worker.certifications: dict[str, float] = field(default_factory=dict)`, `Worker.communication_ratings: list[float] = field(default_factory=list)`.
  - `Task.required_skill_weights: dict[str, float] = field(default_factory=dict)`.
  - `Dataset.events` and `Dataset.impressions` defaulted lists.
  - `Dataset.split_time -> datetime`, `Dataset.train_feedback`, `Dataset.test_feedback`, `Dataset.train_events`, `Dataset.test_events`, `Dataset.train_impressions`, `Dataset.test_impressions`.
  - `Store.__init__(..., events: list[RecommendationEvent] | None = None, impressions: list[Impression] | None = None)`.
  - `Store.events_for(request_id: str) -> list[RecommendationEvent]`.
  - `Store.events_for_user(user_id: str) -> list[RecommendationEvent]`.
  - `Store.recent_impression_counts(now: datetime, days: int = 30) -> dict[str, int]` keyed by candidate ID.
  - `Store.prior_collaboration_count(customer_id: str, worker_id: str, before: datetime | None = None) -> int` counting `status == "completed"` assignments before `before` (default `reference_time`).
  - `Store.reference_time` includes `assignments`, `events`, and `impressions`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_events.py` with:

```python
from datetime import datetime, timedelta, timezone

from app.data.store import Store
from app.domain import (
    Assignment, Customer, Impression, RecommendationEvent, Task, Worker,
)

NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)


def test_impression_fields():
    impression = Impression(
        request_id="r1", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
    )
    assert impression.request_id == "r1"
    assert impression.candidate_ids == ["w1"]


def _worker(worker_id: str = "w1") -> Worker:
    return Worker(
        worker_id=worker_id,
        name=worker_id,
        skills={"python": 4},
        specialties={"software_dev": 3},
        level=3,
        capacity_hours=40,
        current_load_hours=0,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
    )


def test_new_worker_and_task_fields_have_defaults():
    worker = _worker()
    assert worker.expected_pay == 0.0
    assert worker.certifications == {}
    assert worker.communication_ratings == []
    task = Task(
        task_id="t1", customer_id="c1", title="T", category="software_dev",
        required_skills={}, required_level=1, difficulty=3, priority=3,
        estimated_hours=2, deadline=NOW, region="CN", remote_ok=True,
    )
    assert task.required_skill_weights == {}


def test_store_reference_time_includes_events_and_impressions():
    worker = _worker()
    event = RecommendationEvent(
        event_id="e1", request_id="r1", user_id="c1", role="customer",
        task_id="t1", candidate_id="w1", candidate_type="worker",
        rank=1, score=0.9, propensity=0.5, weights_version="v0000",
        action="click", created_at=NOW + timedelta(days=2),
    )
    store = Store(
        workers=[worker], customers=[], tasks=[], assignments=[], feedback=[],
        events=[event],
    )
    assert store.reference_time == event.created_at
    assert store.events_for("r1") == [event]
    assert store.events_for_user("c1") == [event]


def test_recent_impression_counts_window():
    from app.domain import Impression

    worker = _worker()
    old = Impression(
        request_id="r_old", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW - timedelta(days=60),
    )
    new = Impression(
        request_id="r_new", query_id="t2", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW - timedelta(days=5),
    )
    store = Store(
        workers=[worker], customers=[], tasks=[], assignments=[], feedback=[],
        impressions=[old, new],
    )
    assert store.recent_impression_counts(NOW, days=30)["w1"] == 1


def test_prior_collaboration_counts_only_completed_before():
    worker = _worker()
    customer = Customer(customer_id="c1", name="C", region="CN")
    old = Assignment(
        assignment_id="a1", task_id="t1", worker_id="w1", customer_id="c1",
        status="completed", created_at=NOW - timedelta(days=10),
    )
    new = Assignment(
        assignment_id="a2", task_id="t2", worker_id="w1", customer_id="c1",
        status="completed", created_at=NOW + timedelta(days=10),
    )
    cancelled = Assignment(
        assignment_id="a3", task_id="t3", worker_id="w1", customer_id="c1",
        status="cancelled", created_at=NOW - timedelta(days=5),
    )
    store = Store(
        workers=[worker], customers=[customer], tasks=[],
        assignments=[old, new, cancelled], feedback=[],
    )
    assert store.prior_collaboration_count("c1", "w1", before=NOW) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_events.py -v`
Expected: collection error importing `Impression` / `RecommendationEvent` (classes not defined yet).

- [ ] **Step 3: Implement the dataclasses and Store extensions**

Add the two dataclasses to `app/domain.py` with the exact fields from spec §5.1–5.2. Add `metadata: dict = field(default_factory=dict)` to `Impression` for assignment correlation (used by synthetic generation). Add the new fields to `Worker`, `Task`, and `Dataset`. Implement the `Dataset` properties using `split_time = max(a.created_at for a in train)` with a fallback to `datetime.now(timezone.utc)` when `train` is empty. Implement the Store methods; `recent_impression_counts` counts candidate IDs from `store.impressions` whose `created_at` is within `days` of `now`. Update `reference_time` to include events/impressions.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. If a dataclass ordering error occurs, move all new fields after existing defaulted fields.

- [ ] **Step 6: Checkpoint**

No git commit (not a git repository). Record that the full suite passes.

---

