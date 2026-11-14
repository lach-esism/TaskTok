## Task 12: AcceptanceModel (`P(accept)`)

**Files:**
- Create: `app/learning/acceptance.py`
- Modify: `app/features.py` (accept `p_accept` in `candidate_features`; already added in Task 11)
- Test: `tests/test_acceptance_model.py` (create)

**Interfaces:**
- Consumes: event features.
- Produces:
  - `AcceptanceModel(prior: float = 0.5, l2: float = 0.1)`.
  - `AcceptanceModel.fit(samples: list[tuple[dict[str, float], int]], sample_weight: list[float] | None = None) -> "AcceptanceModel"`.
  - `AcceptanceModel.predict(features: dict[str, float]) -> float`.
  - `AcceptanceModel.is_fitted -> bool`.
  - `accept_features(worker, task, skill, pay_fit, region_match, historical_accept_rate) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_acceptance_model.py`:

```python
import pytest
from app.learning.acceptance import AcceptanceModel


def test_acceptance_model_learns_direction():
    positive = {"skill_match": 1.0, "pay_fit": 0.9, "category_match": 1.0, "load_ratio": 0.1, "region_match": 1.0, "historical_accept_rate": 0.9}
    negative = {"skill_match": 0.1, "pay_fit": 0.1, "category_match": 0.0, "load_ratio": 0.9, "region_match": 0.3, "historical_accept_rate": 0.1}
    samples = [(positive, 1)] * 30 + [(negative, 0)] * 30
    model = AcceptanceModel().fit(samples)
    assert model.is_fitted
    assert model.predict(positive) > model.predict(negative)
    assert 0.0 <= model.predict(positive) <= 1.0


def test_cold_start_returns_prior():
    model = AcceptanceModel(prior=0.42)
    assert model.predict({"skill_match": 1.0}) == pytest.approx(0.42)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_acceptance_model.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Use `sklearn.linear_model.LogisticRegression(fit_intercept=True, C=1/l2, max_iter=1000)`. Fit on the ordered feature keys; use a fixed order `["category_match","skill_match","pay_fit","load_ratio","region_match","historical_accept_rate"]`; missing keys default to 0.0. If fewer than 20 samples, remain unfitted and return `prior`. `accept_features` returns the six keys with:
- `category_match = worker.preferred_categories.get(task.category, 0.0)`
- `skill_match = skill`
- `pay_fit = pay_fit`
- `load_ratio = clamp((worker.current_load_hours + task.estimated_hours) / max(worker.capacity_hours, 1), 0, 1)`
- `region_match = 1.0` same region; `0.8` both remote; else `0.3`
- `historical_accept_rate = (accepted + 1) / (accepted + rejected + 2)`

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_acceptance_model.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

