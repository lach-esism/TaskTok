## Task 14: ItemCF Normalization and Benchmark `collaborative` Fix

**Files:**
- Modify: `app/models/itemcf.py`
- Modify: `app/benchmark/features.py`
- Test: `tests/test_itemcf.py`, `tests/test_benchmark.py` (update)

**Interfaces:**
- Produces:
  - `ItemCF.normalize(raw) -> dict` divides by the maximum positive score; all-zero input returns zeros.
  - `BenchmarkFeatureBuilder.__init__(workers, tasks, customers, itemcf: ItemCF | None = None)`.
  - `BenchmarkFeatureBuilder.features(...)["collaborative"]` uses the normalized ItemCF score, not region/remote matching.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_itemcf.py`:

```python
from app.models.itemcf import ItemCF


def test_normalize_divides_by_max():
    cf = ItemCF([])
    result = cf.normalize({("w1", "t1"): 0.2, ("w2", "t2"): 0.4})
    assert result[("w1", "t1")] == 0.5
    assert result[("w2", "t2")] == 1.0


def test_normalize_all_zero_returns_zero():
    cf = ItemCF([])
    result = cf.normalize({("w1", "t1"): 0.0, ("w2", "t2"): 0.0})
    assert result == {("w1", "t1"): 0.0, ("w2", "t2"): 0.0}
```

Append to `tests/test_benchmark.py`:

```python
def test_benchmark_collaborative_uses_itemcf_not_region():
    # Build a tiny builder with one worker who completed a similar task.
    from app.benchmark.features import BenchmarkFeatureBuilder
    from app.models.itemcf import ItemCF

    workers = [{"worker_id": "w1", "resume_text": "Python 后端", "skills": {"python": 4},
                "capacity_hours": 40, "current_load_hours": 0, "region": "CN",
                "remote_ok": True, "rating": 4.5, "on_time_rate": 0.9,
                "preferred_categories": {"software_dev": 0.8}}]
    tasks = [
        {"task_id": "t1", "task_text": "Python 后端开发", "region": "CN", "remote_ok": True,
         "customer_id": "c1", "required_skills": {"python": 4}},
        {"task_id": "t2", "task_text": "Python 后端开发", "region": "US", "remote_ok": False,
         "customer_id": "c1", "required_skills": {"python": 4}},
    ]
    customers = [{"customer_id": "c1", "preferred_categories": {"software_dev": 0.8}}]
    cf = ItemCF([("w1", "t1", 1.0)])
    builder = BenchmarkFeatureBuilder(workers, tasks, customers, itemcf=cf)
    assert builder.features("t1", "w1")["collaborative"] > 0.0
    assert builder.features("t2", "w1")["collaborative"] >= 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_itemcf.py::test_normalize_divides_by_max -v`
Expected: FAIL because the current normalization is min-max.

- [ ] **Step 3: Implement**

- `ItemCF.normalize`: `maximum = max(raw.values())`; if `maximum <= 0`, return zeros; else `max(0, value) / maximum`.
- `BenchmarkFeatureBuilder`: accept `itemcf`; in `features`, set `collaborative = itemcf.normalize({(worker_id, task_id): itemcf.score(worker_id, task_id)})[...]` if `itemcf` is not None, else 0.0. Remove the region/remote assignment to `collaborative`.
- Update existing benchmark tests that assert the old region behavior; keep the `preference`/`customer_preference` fields unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_itemcf.py tests/test_benchmark.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

