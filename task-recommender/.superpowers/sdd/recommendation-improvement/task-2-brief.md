## Task 2: EventService and Funnel Metrics

**Files:**
- Create: `app/events.py`
- Test: `tests/test_events.py` (extend)

**Interfaces:**
- Consumes: `Store`, `Impression`, `RecommendationEvent`.
- Produces:
  - `ACTIONS = {"click", "apply", "accept", "reject", "ignore"}`
  - `EventService.__init__(self, store: Store, persist_dir: Path | None = None, max_events: int = 1_000_000)`.
  - `EventService.record_impression(self, request_id: str, query_id: str, candidate_ids: list[str], propensities: dict[str, float], policy: str, metadata: dict | None = None) -> Impression`.
  - `EventService.record_event(self, request_id: str, candidate_id: str, action: str, user_id: str | None = None, role: str = "customer", metadata: dict | None = None) -> RecommendationEvent`.
  - `EventService.funnel_metrics(self) -> dict`.
  - JSONL persistence: `persist_dir/impressions.jsonl`, `persist_dir/events.jsonl` when `persist_dir` is set. When a file reaches `max_events` lines, rotate it to `<name>.1.jsonl`, `<name>.2.jsonl`, … and continue with a fresh active file.
  - `weights_version` is stored as `str(...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_events.py`:

```python
import pytest
from app.events import EventService


def test_event_service_records_and_counts(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store, persist_dir=tmp_path)
    service.record_impression(
        "r1", "t1", ["w1", "w2"], {"w1": 0.9, "w2": 0.1}, "test",
    )
    service.record_event("r1", "w1", "click", user_id="c1")
    service.record_event("r1", "w1", "accept", user_id="c1")
    metrics = service.funnel_metrics()
    assert metrics["impressions"] == 1
    assert metrics["candidates"] == 2
    assert metrics["clicks"] == 1
    assert metrics["accepts"] == 1
    assert metrics["click_rate"] == pytest.approx(0.5)
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "impressions.jsonl").exists()


def test_event_service_rejects_duplicates_and_unknowns(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store)
    service.record_impression("r1", "t1", ["w1"], {"w1": 1.0}, "test")
    service.record_event("r1", "w1", "click")
    with pytest.raises(ValueError):
        service.record_event("r1", "w1", "click")
    with pytest.raises(KeyError):
        service.record_event("r_missing", "w1", "click")
    with pytest.raises(KeyError):
        service.record_event("r1", "w_missing", "click")
    with pytest.raises(ValueError):
        service.record_event("r1", "w1", "invalid_action")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_events.py::test_event_service_records_and_counts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.events'`.

- [ ] **Step 3: Implement `EventService`**

`record_impression` appends to `store.impressions` and writes one JSONL line. `record_event` looks up the impression by `request_id`, validates `candidate_id` is in `impression.candidate_ids`, rejects duplicate `(request_id, candidate_id, action)` with `ValueError`, rejects unknown IDs with `KeyError`, and appends a `RecommendationEvent` with `rank = candidate_ids.index(candidate_id) + 1`, `score = 0.0` (unless provided in metadata), `propensity = impression.propensities[candidate_id]`, and `weights_version = str(metadata.get("weights_version", "v0000"))`. `funnel_metrics` returns counts plus rates:

Add `test_event_service_rotates_jsonl` with `max_events=2`: record three events, assert `events.1.jsonl` exists and the active `events.jsonl` contains the remainder. Add a focused non-click funnel test covering `apply_rate`/`accept_rate`/`reject_rate`/`ignore_rate`, and parse one persisted JSONL line to assert its fields.

```text
click_rate  = clicks  / max(1, candidates)
apply_rate  = applies / max(1, clicks)
accept_rate = accepts / max(1, applies)
reject_rate = rejects / max(1, candidates)
ignore_rate = ignores / max(1, candidates)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit. Record the focused test result.

---

