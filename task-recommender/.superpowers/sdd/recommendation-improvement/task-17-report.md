# Task 17 Report: Platt Calibration

## Status

DONE

## Files changed

- Created `app/learning/calibration.py` with `PlattCalibrator`.
- Created `tests/test_calibration.py` with the two tests from the brief,
  verbatim.
- Created this report (`.superpowers/sdd/recommendation-improvement/task-17-report.md`).

No other project files were modified. This directory is not a git
repository, so no commit was created and no git commands were run.

## What was implemented

`app/learning/calibration.py`:

- Module docstring states the purpose (`P(rating >= 4)` for the
  seven-dimension score), that calibration does not feed ranking, and that
  the module only consumes caller-supplied `(score, label)` pairs and
  never reads ground-truth/label storage.
- `MIN_SAMPLES = 10`.
- `_sigmoid(value)`: numerically stable logistic function (branch on the
  sign of the exponent, so large-magnitude scores do not overflow
  `math.exp`).
- `_clamp(value, low=0.0, high=1.0)`.
- `PlattCalibrator`:
  - `__init__` initializes `a = 1.0`, `b = 0.0` (identity mapping usable
    before `fit`).
  - `fit(scores, labels) -> PlattCalibrator` converts inputs to
    `list[float]` / `list[int]`, validates equal lengths (`ValueError`
    otherwise), and:
    - fewer than 10 samples -> identity (`a=1, b=0`);
    - only one label class -> identity (logistic regression has no finite
      MLE slope);
    - otherwise fits
      `LogisticRegression(penalty=None, max_iter=1000)` on a single
      feature `[[score]]`, then stores
      `a = coef_[0][0]`, `b = intercept_[0]`.
    - returns `self`.
  - `predict(score) -> float` computes `sigmoid(a*score + b)` and clamps to
    `[0, 1]`.
  - `brier(scores, labels) -> float` validates equal lengths and returns
    `mean((predict(score) - label)^2)`; returns `0.0` for empty inputs
    (matches the `app/metrics.py` convention of returning `0.0` for empty
    inputs rather than raising).

### Regularization choice (SUPERSEDED — see fix report below)

> **Superseded.** The `penalty=None` choice described in this section was
> replaced with `C=5.0` after review; the fix report at the end of this
> file is authoritative.

With scikit-learn's default `C=1.0`, the brief's
`test_brier_is_lower_than_raw` data (`scores=[0.4,0.6]*20`,
`labels=[0,1]*20`) gives `a=1.8178`, `b=-0.9086`,
`p(0.4)=0.4548`, and Brier `0.2067`, which is worse than the raw `0.16`
and fails the assertion. Regularized logistic regression shrinks the
slope too much for this tiny two-point dataset.

I therefore used `penalty=None` (unregularized MLE), which satisfies the
brief's requirement ("fit ... using `sklearn.linear_model.LogisticRegression`")
and the test:

| setting | `a` | `b` | `p(0.4)` | Brier |
| --- | --- | --- | --- | --- |
| default `C=1.0` | 1.8178 | -0.9086 | 0.4548 | 0.2067 (fails) |
| `C=1e3` | 44.8932 | -22.4483 | 0.0111 | 0.000123 |
| `C=1e6` | 75.0556 | -37.6512 | 0.00049 | 3.11e-7 |
| `penalty=None` | 75.2428 | -37.7476 | 0.00048 | 3.00e-7 |

`penalty=None` is supported by scikit-learn >= 1.2 and the project pins
`scikit-learn>=1.4`, so this adds no dependency or version risk.

## Tests run and output

1. Step 2, failing test before implementation (expected failure):

```
$ python -m pytest tests/test_calibration.py -v
...
tests\test_calibration.py:2: in <module>
    from app.learning.calibration import PlattCalibrator
E   ModuleNotFoundError: No module named 'app.learning.calibration'
1 error in 1.14s
```

2. Step 4, focused tests after implementation:

```
$ python -m pytest tests/test_calibration.py -v
tests/test_calibration.py::test_calibration_is_monotonic_and_bounded PASSED [ 50%]
tests/test_calibration.py::test_brier_is_lower_than_raw PASSED           [100%]
2 passed in 0.06s
```

3. Step 5, full suite:

```
$ python -m pytest tests/ -q
224 passed in 18.61s
```

The previous suite size (Task 16 report) was 222 tests; the two new tests
bring it to 224 with no regressions.

## Manual verification of uncovered behavior

Run with `python -W error` so any `ConvergenceWarning` or other warning
would fail:

- **Identity below 10 samples.** `fit([0.1,0.9]*4, [0,1]*4)` leaves
  `(a, b) == (1.0, 0.0)` and `predict(s) == 1/(1+exp(-s))` to float
  precision.
- **Exactly 10 samples.** Fits (`a=17.70`, `b=-8.65` for
  `[0,1]*5`/`[0,1]*5`), confirming the `< 10` boundary is strict.
- **Single label class.** 20 `(0.1, 0)` samples fall back to identity
  instead of raising sklearn's "needs at least 2 classes" `ValueError`.
- **Bounds.** `predict(-1e9) == 0.0`, `predict(1e9) == 1.0`.
- **Brier formula.** Matches a hand-computed mean squared error on the
  identity path; `brier([], []) == 0.0`.
- **Length mismatch.** Both `fit` and `brier` raise
  `ValueError("scores and labels must have equal length")`.
- **Monotonicity.** `predict` over `0.00..1.00` in steps of 0.01 is
  non-decreasing for the brief's first-test data.
- **Return value.** `fit` returns the same instance (`self`).
- **No warnings** under `-W error` for the brief's datasets; the
  unregularized fits converged within `max_iter=1000`.
- **Style.** No line exceeds 79 characters in either changed file.

## Self-review findings

1. **Default regularization fails the brief's test.** Fixed by using
   `penalty=None`; documented above and in the module docstring. This is
   the one place where the brief's wording could not be followed with
   sklearn defaults.
2. **Single-class labels.** The brief only specifies the `< 10` fallback,
   but `LogisticRegression` raises on one-class data, which can legitimately
   occur for small deployments (e.g. every observed rating `< 4`). I added
   an identity fallback for that case rather than letting `fit` crash.
   It is consistent with the existing `AcceptanceModel` convention of
   staying on a neutral fallback when there is no separable signal.
3. **Empty `brier`.** Returns `0.0`, following `app/metrics.py` (e.g.
   `hr_at_k`/`ndcg_at_k` return `0.0` for empty inputs) instead of
   raising `ZeroDivisionError`.
4. **Length validation.** Silently truncating via `zip` would hide caller
   bugs; both methods raise `ValueError` for mismatched lengths.
5. **Numerical stability.** The sigmoid uses a sign branch, so
   `predict(±1e9)` stays finite even with large fitted slopes.
6. **No ground-truth reads.** The module imports only `math` and sklearn;
   labels are supplied by the caller. No store or label file is touched.
7. **Line length / style.** Verified <= 79 characters; follows the
   `from __future__ import annotations` and clamp-helper style used in
   `app/learning/acceptance.py`.

## Concerns

1. **Unregularized slopes can saturate.** For perfectly separable or
   tiny datasets the fitted slope is large (e.g. `a ~ 26` on the brief's
   first-test data), so probabilities are near 0/1 and reliability bins
   in Task 20 will be sparse at the extremes. This is the direct
   consequence of `penalty=None`, which the brief's Brier test requires.
   If Task 20's reliability analysis needs softer probabilities, a
   bounded `C` (e.g. `C=1e3`, Brier `0.00012`, still far below raw) is the
   knob to revisit, but that would change this task's fit slightly.
2. **Task 20 integration is unverified.** No current code imports
   `PlattCalibrator`; the intended consumer is the strict-eval report.
   The public surface matches the brief (`fit`, `predict`, `brier`) and
   exposes `a`/`b`, so integration should be direct.
3. **Test file keeps the brief's unused `import pytest`.** The brief's
   test source includes it verbatim; I did not remove it to stay exact.

---

# Fix Report (post-review): bounded `C=5.0` regularization

This section supersedes the earlier "Regularization choice" subsection and
the earlier test counts. The reviewer found that unregularized MLE at the
10-sample floor produced fitted slopes from -5.75 to +731 across noisy
datasets (sign inversion and step-function saturation), which the
in-sample Brier test cannot detect.

## What changed

- `app/learning/calibration.py`
  - Replaced `LogisticRegression(penalty=None, max_iter=1000)` with
    `LogisticRegression(fit_intercept=True, C=5.0, max_iter=1000)`.
    `penalty=None` is no longer used anywhere.
  - Module and class docstrings now state that calibration at `n ~ 10` is
    uncertain, that an unregularized fit at that floor can invert or
    saturate the slope, and that `C=5.0` is a deliberate bounded choice
    that keeps predictions interior to `(0, 1)`.
  - The `< 10` identity fallback (`a=1, b=0`), single-class fallback,
    length validation, clamping, and Brier formula are unchanged.
- `tests/test_calibration.py`
  - Kept both mandated tests from the brief verbatim.
  - Added `_noisy_scores_and_labels()`: a deterministic 100-sample noisy
    dataset (interleaved scores 0.35 and 0.65, with 10% of labels flipped
    at each score so both classes appear at both scores).
  - Added `test_held_out_brier_beats_raw_without_saturation`: fit on the
    first 80% (80 samples), evaluate `brier` on the held-out last 20%
    (20 samples), assert calibrated Brier <= raw-score Brier, and assert
    every prediction is strictly `0.0 < p < 1.0` (not pinned at the
    extremes).
  - Added `test_identity_fallback_below_ten_samples`: 9 samples leave
    `a == 1.0`, `b == 0.0`; every `predict(score)` equals the clamped
    `sigmoid(1*score + 0)` and lies in `[0, 1]`.
  - `import pytest` is now used (by the new tests).

## Covering test details and measured values

- Mandated `test_brier_is_lower_than_raw` under `C=5.0`:
  `a=6.748079`, `b=-3.374047`, `predict(0.4)=0.337420`,
  `predict(0.6)=0.662577`, calibrated Brier `0.113853` <= raw `0.16`.
  This matches the reviewer's expected `a ~ 6.75` and Brier ~ `0.114`.
- `test_held_out_brier_beats_raw_without_saturation`: fitted
  `a=7.957477`, `b=-3.978745`; held-out calibrated Brier `0.107586` <=
  raw `0.152500`; held-out predictions range `0.232611..0.767387`, so
  none is pinned at 0 or 1.
- `test_identity_fallback_below_ten_samples`: 9 samples give
  `a=1.0`, `b=0.0`, so `predict(score) = sigmoid(score)`. Note that the
  identity mapping is in logit space (`a=1, b=0` in
  `P = sigmoid(a*score + b)`), per the brief's formula; it is **not** a
  raw-score passthrough.

## Commands and output

1. Focused calibration tests:

```
$ python -m pytest tests/test_calibration.py -v
tests/test_calibration.py::test_calibration_is_monotonic_and_bounded PASSED [ 25%]
tests/test_calibration.py::test_brier_is_lower_than_raw PASSED           [ 50%]
tests/test_calibration.py::test_held_out_brier_beats_raw_without_saturation PASSED [ 75%]
tests/test_calibration.py::test_identity_fallback_below_ten_samples PASSED [100%]
4 passed in 0.06s
```

2. Full suite:

```
$ python -m pytest tests/ -q
226 passed in 18.70s
```

The pre-fix suite at this task was 224 tests; the two added covering tests
bring it to 226 with no regressions.

3. Manual verification under `python -W error` (any warning would fail):
   the mandated fit produced `a=6.748079`, `b=-3.374047`, Brier
   `0.113853`; the held-out fit produced `a=7.957477`, Brier `0.107586`
   vs raw `0.152500`, predictions in `[0.232611, 0.767387]`; single-class
   and `< 10` inputs returned identity `(1.0, 0.0)`; no convergence or
   other warnings were emitted.

## Self-review findings (fix)

1. **Regularization replaced as instructed.** `penalty=None` is gone;
   `fit_intercept=True`, `C=5.0`, `max_iter=1000` are passed explicitly.
2. **Bounded slope confirmed.** On the mandated data `C=5.0` keeps the
   slope at ~6.75 instead of ~75 under unregularized MLE, so probabilities
   stay away from 0/1 while still beating raw Brier.
3. **Held-out coverage added.** The new test measures generalization on
   unseen noisy samples, which the mandated in-sample test cannot.
4. **Saturation guard added.** Every held-out prediction is asserted
   strictly within `(0, 1)`.
5. **Identity coverage added.** `a`/`b` and `sigmoid(score)` predictions
   are checked below the 10-sample floor.
6. **Documentation updated.** Both the module docstring and the class
   docstring call out `n ~ 10` uncertainty and the bounded `C=5.0`
   choice.
7. **No regressions or warnings.** Full suite passes; `-W error` manual
   run is clean; no line exceeds 79 characters.
8. **Scope.** Only `app/learning/calibration.py` and
   `tests/test_calibration.py` were modified by this fix (plus this
   report). No git commands were run.

## Concerns (fix)

1. **`C=5.0` intentionally shrinks the slope.** It bounds the calibration
   instability but is not the maximum-likelihood fit; very confident
   score/rating relationships will be under-confident (e.g. `p(0.4)` is
   ~0.337 rather than ~0). This is the intended trade-off from the
   review.
2. **Calibration at `n ~ 10` remains uncertain.** The regularization
   bounds variance but does not make ten observations informative; Task
   20 should interpret Brier/reliability on tiny samples cautiously.
3. **The held-out test uses a deterministic synthetic distribution.**
   It guards against sign inversion and extreme pinning, not against
   every possible data distribution.
