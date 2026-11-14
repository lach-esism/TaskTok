# Task 12 Report: AcceptanceModel (`P(accept)`)

## Status

DONE

## What Was Implemented

### `app/learning/acceptance.py` (new)

- `FEATURE_KEYS`: fixed tuple in the required order:
  `category_match, skill_match, pay_fit, load_ratio, region_match,
  historical_accept_rate`.
- `MIN_SAMPLES = 20`.
- `accept_features(worker, task, skill, pay_fit, region_match,
  historical_accept_rate) -> dict[str, float]`:
  - `category_match = worker.preferred_categories.get(task.category, 0.0)`
  - `skill_match = skill`
  - `pay_fit = pay_fit`
  - `load_ratio = clamp((current_load_hours + estimated_hours) /
    max(capacity_hours, 1), 0, 1)`
  - `region_match` and `historical_accept_rate` are passed through from the
    caller (they depend on assignment/event context that `Worker`/`Task` do
    not carry).
  - Returns the six keys in `FEATURE_KEYS` order.
- `AcceptanceModel(prior: float = 0.5, l2: float = 0.1)`:
  - `prior` stored clamped to `[0, 1]`; `l2` must be positive.
  - `is_fitted` property is `self._model is not None`.
  - `fit(samples, sample_weight=None) -> "AcceptanceModel"`:
    - Fewer than 20 samples -> clears any prior fit, stays unfitted, returns
      `self`.
    - Fewer than two label classes -> same unfitted behavior (sklearn cannot
      fit a single-class target).
    - Otherwise builds
      `LogisticRegression(fit_intercept=True, C=1.0 / l2, max_iter=1000)` on
      rows in `FEATURE_KEYS` order (missing feature keys default to `0.0`,
      extra keys ignored), fits with the optional `sample_weight`, returns
      `self`.
  - `predict(features) -> float`:
    - Unfitted -> returns `float(self.prior)`.
    - Fitted -> returns `predict_proba` for class `1`, clamped to `[0, 1]`.
- No ground-truth or label-file reads: the module imports only
  `sklearn.linear_model.LogisticRegression` and `app.domain.Task/Worker`;
  labels come exclusively from the `samples` passed to `fit`.

### `tests/test_acceptance_model.py` (new)

- The two brief tests, verbatim:
  `test_acceptance_model_learns_direction`,
  `test_cold_start_returns_prior`.
- Seven additional tests covering the implementation contract:
  `<20` samples stays unfitted and returns the prior; single-class events stay
  unfitted; `fit` returns `self` and accepts `sample_weight`; unknown keys are
  ignored and missing keys default to zero; `accept_features` fixed key
  order/values; missing category defaults to `0.0`; `load_ratio` clamps to
  `[0, 1]` including the zero-capacity denominator guard.

## Tests Run and Output

1. After writing the tests but before implementing:

```
$ python -m pytest tests/test_acceptance_model.py -v
...
tests\test_acceptance_model.py:6: in <module>
    from app.learning.acceptance import FEATURE_KEYS, AcceptanceModel, accept_features
E   ModuleNotFoundError: No module named 'app.learning.acceptance'
1 error in 1.35s
```

2. Focused suite after implementing:

```
$ python -m pytest tests/test_acceptance_model.py -v
tests/test_acceptance_model.py::test_acceptance_model_learns_direction PASSED
tests/test_acceptance_model.py::test_cold_start_returns_prior PASSED
tests/test_acceptance_model.py::test_fewer_than_twenty_samples_stays_unfitted PASSED
tests/test_acceptance_model.py::test_single_class_events_stay_unfitted PASSED
tests/test_acceptance_model.py::test_fit_returns_self_and_accepts_sample_weight PASSED
tests/test_acceptance_model.py::test_predict_ignores_unknown_keys_and_defaults_missing_to_zero PASSED
tests/test_acceptance_model.py::test_accept_features_returns_fixed_order_and_values PASSED
tests/test_acceptance_model.py::test_accept_features_defaults_missing_category_to_zero PASSED
tests/test_acceptance_model.py::test_accept_features_clamps_load_ratio PASSED
9 passed in 0.07s
```

3. Full suite:

```
$ python -m pytest tests/ -q
211 passed in 14.57s
```

(The suite had 202 tests before this task; the 9 new tests account for 211.)

## Files Changed

- `app/learning/acceptance.py` (new)
- `tests/test_acceptance_model.py` (new)
- `.superpowers/sdd/recommendation-improvement/task-12-report.md` (this report)

No other files were modified. This directory is not a git repository; no git
commands were run and no commits were created.

## Self-Review Findings

- The sklearn constructor matches the brief exactly:
  `LogisticRegression(fit_intercept=True, C=1.0 / l2, max_iter=1000)`.
- Feature order is a single module-level constant used by both `fit` and
  `predict`, so training/serving order cannot drift; missing keys default to
  `0.0` and unknown keys are ignored (covered by a test).
- `accept_features` formulas match the brief; `load_ratio` uses the mandated
  `max(capacity_hours, 1)` denominator and is clamped, so zero capacity and
  overload produce finite `[0, 1]` values (tested).
- Cold start returns the prior exactly and `is_fitted` is false until a
  successful fit; fewer-than-20 and single-class inputs are both covered.
- No ground-truth/label reads: only event samples passed by the caller are
  used as labels.
- `predict` looks up the probability column by the trained class label (`1`)
  rather than assuming a column position, and clamps its output.

## Concerns

1. **`region_match` / `historical_accept_rate` are caller-supplied.** The
   brief's interface lists them as `accept_features` parameters, while the
   formula bullet describes how `region_match` and the historical rate are
   derived. The function therefore passes them through unchanged; the caller
   (Task 13 / event aggregation) computes the `1.0 / 0.8 / 0.3` region value
   and the `(accepted + 1) / (accepted + rejected + 2)` rate. If downstream
   expects `accept_features` itself to derive `region_match` from
   `worker`/`task`, the signature would need to change.
2. **Single-class guard is an addition beyond the brief.** With 20+ events that
   are all accepts (or all rejects), sklearn's `LogisticRegression` raises
   `ValueError`. The model instead stays unfitted and returns the prior, which
   keeps Task 13's `create_app` global fit safe on degenerate event logs.
3. **Fit is all-or-nothing.** Calling `fit` with fewer than 20 samples (or one
   class) clears a previous fit rather than retaining stale parameters; no
   incremental-refit use case is specified.
4. **Input validation additions.** `l2 <= 0` raises `ValueError` (otherwise
   `C = 1 / l2` would divide by zero), and `prior` is clamped to `[0, 1]`.
   Neither changes behavior for valid inputs in the brief.
5. **Labels are contracted to `0`/`1`.** The brief specifies an int
   accept/reject indicator; other label values are not supported (the
   fallback probability column would be the last trained class, which is
   unreachable for compliant callers).
6. The design document describes L2 as shrinking "toward the global prior",
   but the mandated implementation (`LogisticRegression` with `C = 1/l2`)
   shrinks coefficients toward zero. The implementation follows the brief's
   explicit step; the prior is applied through the cold-start path instead.
