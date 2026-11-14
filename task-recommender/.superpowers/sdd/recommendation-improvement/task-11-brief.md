## Task 11: `preference` Pay/Time Fit

**Files:**
- Modify: `app/features.py`
- Test: `tests/test_features_v2.py` (extend)

**Interfaces:**
- Consumes: `Worker.expected_pay`, `Task.budget`, `Task.deadline`, `Task.estimated_hours`, `Worker.current_load_hours`.
- Produces:
  - `pay_fit_score(worker: Worker, task: Task) -> float`.
  - `time_fit_score(worker: Worker, task: Task, now: datetime | None = None) -> float`.
  - `preference_score(worker: Worker, task: Task, profile: WorkerPreferenceProfile | None = None, p_accept: float | None = None, now: datetime | None = None) -> float`.
  - `candidate_features(..., now=None)` must forward its `now` into `preference_score` so the time term uses the data-relative reference, not the wall clock.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features_v2.py`:

```python
from datetime import datetime, timedelta, timezone
from app.features import pay_fit_score, preference_score, time_fit_score


def test_pay_fit_exact_match_and_missing():
    worker = make_worker(expected_pay=1000)
    assert pay_fit_score(worker, make_task(budget=1000)) == pytest.approx(1.0)
    assert pay_fit_score(worker, make_task(budget=2000)) == pytest.approx(1 - 1000 / 2000)
    assert pay_fit_score(make_worker(expected_pay=0), make_task(budget=1000)) == pytest.approx(0.5)


def test_time_fit_exact_value():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(current_load_hours=0)
    task = make_task(estimated_hours=5, deadline=now + timedelta(hours=10))
    assert time_fit_score(worker, task, now=now) == pytest.approx(0.5)


def test_preference_weighted_formula():
    worker = make_worker()
    task = make_task()
    value = preference_score(worker, task, p_accept=0.8)
    declared = 0.6 * 0.8 + 0.4 * 1.0  # category 0.8, difficulty midpoint 3 = task difficulty 3
    pay = pay_fit_score(worker, task)
    time_fit = time_fit_score(worker, task)
    expected = 0.4 * 0.8 + 0.3 * declared + 0.15 * pay + 0.15 * time_fit
    assert value == pytest.approx(expected)
```

Adjust the `declared` expectation to the actual `make_task` difficulty (3) and `make_worker` preferred difficulty `(2, 4)` midpoint 3, so `difficulty_fit = 1.0`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_features_v2.py::test_pay_fit_exact_match_and_missing -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

- `pay_fit_score`: `1 - |task.budget - worker.expected_pay| / max(task.budget, worker.expected_pay, 1)`; if `expected_pay == 0`, 0.5; clamp.
- `time_fit_score`: `now = now or datetime.now(timezone.utc)` **exactly** (no minute truncation); `hours_until = max(0, (deadline - now).total_seconds()/3600)`; `available = max(0, hours_until - worker.current_load_hours)`; `1 - clamp(task.estimated_hours / max(available, 1), 0, 1)`.
- `preference_score`: keep the existing profile/declared logic for `declared`; use `p_accept if provided else declared`; pass `now` to `time_fit_score`; return `0.4*p_accept + 0.3*declared + 0.15*pay_fit + 0.15*time_fit`, clamped. `candidate_features` forwards its `now` here.
- Update `tests/test_preference_profiles.py`'s wall-clock equality assertion to `pytest.approx` (or pass a fixed `now`); this file is in scope for this task because the spec changes `preference_score`'s inputs.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_features_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. Existing preference tests should still pass; if they assert the old formula, update only those assertions to the new formula.

- [ ] **Step 6: Checkpoint**

No git commit.

---

