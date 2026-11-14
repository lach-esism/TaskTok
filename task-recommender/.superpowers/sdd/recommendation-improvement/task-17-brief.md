## Task 17: Platt Calibration

**Files:**
- Create: `app/learning/calibration.py`
- Test: `tests/test_calibration.py` (create)

**Interfaces:**
- Produces:
  - `PlattCalibrator.fit(scores: list[float], labels: list[int]) -> "PlattCalibrator"`.
  - `PlattCalibrator.predict(score: float) -> float`.
  - `PlattCalibrator.brier(scores: list[float], labels: list[int]) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_calibration.py`:

```python
import pytest
from app.learning.calibration import PlattCalibrator


def test_calibration_is_monotonic_and_bounded():
    scores = [0.1, 0.2, 0.8, 0.9] * 10
    labels = [0, 0, 1, 1] * 10
    calibrator = PlattCalibrator().fit(scores, labels)
    assert 0.0 <= calibrator.predict(0.1) <= 1.0
    assert calibrator.predict(0.9) > calibrator.predict(0.1)


def test_brier_is_lower_than_raw():
    scores = [0.4, 0.6] * 20
    labels = [0, 1] * 20
    calibrator = PlattCalibrator().fit(scores, labels)
    raw = sum((s - y) ** 2 for s, y in zip(scores, labels)) / len(scores)
    assert calibrator.brier(scores, labels) <= raw + 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Fit `P = sigmoid(a*score + b)` using `sklearn.linear_model.LogisticRegression(fit_intercept=True, C=5.0, max_iter=1000)` with a single feature `[[score]]`; store `a = coef_[0][0]`, `b = intercept_[0]`. **Do not use `penalty=None`**: unregularized MLE at the 10-sample floor can invert or saturate the slope. `C=5.0` bounds the slope and still passes the mandated Brier check. `predict` clamps to `[0,1]`. `brier` returns `mean((predict(score) - label)^2)`. If fewer than 10 samples, use `a=1,b=0` (identity). Add a held-out noisy test: fit on 80%, evaluate Brier on 20%, assert `brier <= raw` and no probability is pinned at exactly 0/1; add an identity-fallback test for `<10` samples. Document that calibration at n≈10 is uncertain.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_calibration.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

