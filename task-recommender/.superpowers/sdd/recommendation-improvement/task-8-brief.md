## Task 8: `project_weights_with_report`

**Files:**
- Modify: `app/learning/weights.py`
- Test: `tests/test_weight_binding.py` (create)

**Interfaces:**
- Consumes: existing `project_weights`.
- Produces:
  - `WeightBindingReport` dataclass with `reputation_hit_low: int`, `reputation_hit_high: int`, `min_hits: dict[str, int]`, `iterations: int`.
  - `project_weights_with_report(weights: dict[str, float]) -> tuple[dict[str, float], WeightBindingReport]`.
  - `project_weights(weights) -> dict[str, float]` delegates and returns only the weights.

- [ ] **Step 1: Write the failing test**

Create `tests/test_weight_binding.py`:

```python
from app.config import DEFAULT_WEIGHTS
from app.learning.weights import project_weights_with_report


def test_projection_reports_reputation_high_bound():
    weights = dict(DEFAULT_WEIGHTS)
    weights["reputation"] = 0.9
    projected, report = project_weights_with_report(weights)
    assert projected["reputation"] <= 0.40 + 1e-9
    assert report.reputation_hit_high == 1
    assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_projection_reports_min_weight_hits():
    weights = dict(DEFAULT_WEIGHTS)
    weights["customer_preference"] = 0.0
    projected, report = project_weights_with_report(weights)
    assert projected["customer_preference"] >= 0.02 - 1e-9
    assert report.min_hits.get("customer_preference", 0) >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_weight_binding.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the report**

Refactor `project_weights` into `project_weights_with_report`; keep the existing projection logic and add counters when:
- `reputation` is clamped to `REPUTATION_MIN` / `REPUTATION_MAX`;
- any dimension is allocated at `MIN_WEIGHT`.
Increment `iterations` once per call. `project_weights` returns `project_weights_with_report(weights)[0]`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_weight_binding.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

