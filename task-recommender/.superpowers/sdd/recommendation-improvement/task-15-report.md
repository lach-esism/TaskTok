# Task 15 Report: Pairwise Choice Learner and Pair Builder

## Status

DONE_WITH_CONCERNS

## Files changed

- Created `app/learning/choice.py`
- Created `tests/test_pairwise_learning.py`
- Created this report (`.superpowers/sdd/recommendation-improvement/task-15-report.md`)

No other source or test file was modified (verified by diffing `app/` and
`tests/` against `snapshots/task-14`: only the two new files differ, aside
from `__pycache__`).

## What was implemented

`app/learning/choice.py`:

- `ChoicePair` — frozen dataclass with `chosen: dict[str, float]`,
  `rejected: dict[str, float]`, `weight: float = 1.0`.
- `PairwiseChoiceLearner(prior, l2=0.1)`:
  - Keeps `prior`, a fixed key order from `list(prior.keys())`, and an
    internal projected `weights` vector.
  - `fit(pairs)`:
    - Returns `dict(prior)` unchanged when `pairs` is empty.
    - Builds `X = chosen - rejected` in `list(prior.keys())` order and
      `y = 1` for every pair.
    - `sample_weight = clamp(pair.weight, 0.1, 10.0)`.
    - Fits `LogisticRegression(fit_intercept=False, C=1/l2, max_iter=1000)`,
      takes `coef_[0]`, and passes it through `project_weights`.
    - Stores the projected vector on `self.weights` before returning it.
  - `update_online(chosen, rejected, learning_rate=0.05)`:
    - Applies the same gradient as `OnlineWeightLearner.update_pair`
      (`error * (chosen - rejected) / ||chosen - rejected|| - l2 * (w - prior)`)
      and then `project_weights`.
    - Returns the current projected vector for a zero difference vector.
- `build_pairs(events, feature_lookup, time_decay_tau_days=30.0)`:
  - Groups events by `request_id`.
  - Positives: `{"click", "apply", "accept"}`; negatives:
    `{"reject", "ignore"}`.
  - Emits one `ChoicePair` per positive-negative combination in a request.
  - Weight: `exp(-Δt_days / tau_days) * clamp(1 / propensity, 0.1, 10.0)`,
    with `Δt_seconds = abs(positive.created_at - negative.created_at)`,
    `Δt_days = max(Δt_seconds, 0) / 86400`, and naive datetimes normalized
    to UTC.
  - `feature_lookup(event)` is called once per relevant event, and its
    result is copied into the pair.

`tests/test_pairwise_learning.py` contains exactly the two tests from the
task brief, verbatim.

## Tests run and output

1. Before implementation:

```
$ python -m pytest tests/test_pairwise_learning.py -v
...
tests\test_pairwise_learning.py:3: in <module>
    from app.learning.choice import ChoicePair, PairwiseChoiceLearner, build_pairs
E   ModuleNotFoundError: No module named 'app.learning.choice'
1 error in 1.14s
```

2. After implementation, focused tests:

```
$ python -m pytest tests/test_pairwise_learning.py -v
tests/test_pairwise_learning.py::test_pairwise_learner_increases_chosen_dimension PASSED [ 50%]
tests/test_pairwise_learning.py::test_propensity_clipping PASSED         [100%]
2 passed in 0.04s
```

3. Full suite:

```
$ python -m pytest tests/ -q
221 passed in 18.88s
```

The previous suite size was 219 tests; the two new tests bring it to 221
with no regressions.

## Manual verification of uncovered behavior

The brief's test file does not cover `build_pairs` or `update_online`, so
both were exercised with throwaway inline scripts (no test files added,
since the brief specifies the test file verbatim):

- Same-request `accept` (propensity 0.5) vs `reject` 30 days later
  (propensity 0.1) produced `weight = 2 * exp(-1) = 0.735758...`; the
  same-time pair with propensity 0.001 was clipped to `10.0`. A request
  with only positives produced no pairs.
- `fit([])` returns the prior dict unchanged.
- 50 online updates on a +1 skill difference moved `skill` from 0.20 to
  0.32 and kept the sum at 1.0.
- A zero-difference pair returns a valid projected simplex vector
  (sum 1.0).
- On the synthetic dataset (`n_workers=20`, `n_tasks=60`,
  `n_assignments=200`, seed 42): 538 pairs from 698 train events, weights
  in `[1.779, 10.0]`, and `fit` returned a valid projected vector.
- Line lengths in the new module are <= 79 characters. The two long lines
  in the test file are the brief's verbatim code.

## Self-review findings

1. **sklearn rejects the brief's literal target.** `LogisticRegression`
   (scikit-learn 1.7.2) raises
   `ValueError: This solver needs samples of at least 2 classes in the data,
   but the data contains only one class: np.int64(1)` when `y` is all ones.
   The brief mandates `y=1` for every pair, so the exact literal call cannot
   run. `fit` therefore appends one neutral row (all-zero features, label 0,
   `sample_weight=1e-6`). For an intercept-free linear model that row has an
   identically zero gradient (`error * 0`), so it adds only a constant to the
   loss and leaves the fitted coefficients of the pairwise objective
   unchanged. The real pairs still use `X = chosen - rejected`, `y=1`, and
   the clamped sample weights exactly as specified.
2. **No pairs returns the prior.** `fit([])` returns `dict(self.prior)`
   exactly (not projected), per the brief, while resetting the internal
   state to `project_weights(prior)`.
3. **`l2=0` is guarded.** `C = 1 / max(l2, 1e-12)` avoids a division by
   zero; the default `l2=0.1` gives `C=10` as specified.
4. **Timezone safety.** `created_at` values are normalized to UTC before
   subtraction, matching `app.domain._as_utc`, so naive/aware mixes do not
   raise.
5. **Zero difference online update.** `update_online` returns the current
   weights, mirroring `OnlineWeightLearner.update_pair`'s norm guard.
6. **Diff scope.** Only the two allowed files were added; `app/main.py`,
   `app/service.py`, and the API were not touched.

## Concerns

1. **Propensity source is ambiguous in the brief.** `build_pairs` weights
   each pair by `1 / positive.propensity` (the chosen/positive event's
   propensity), because the choice probability under the logging policy is
   the positive item's propensity. The brief only says "1/propensity". If
   the intended source was the negative event or an `Impression` lookup, the
   pair weights would change; no `Impression` input is available in the
   specified signature.
2. **Time decay units.** The brief says `exp(-Δt/30)` and calls `Δt`
   "absolute seconds", but also names the parameter `time_decay_tau_days`
   and the formula "30 days". Treating `Δt` literally as seconds would make
   any pair more than a few minutes apart decay to ~0. The implementation
   converts seconds to days before applying `exp(-Δt_days / tau_days)`;
   with the synthetic data (same timestamp per request) decay is 1.0.
3. **The single-class workaround is an implementation detail not in the
   brief.** It is documented inline and mathematically neutral, but a
   reviewer may prefer a custom one-class solver or a `try/except` fallback.
4. **`build_pairs` and `update_online` have no automated tests in this
   task.** The brief specifies the test file verbatim and Task 19 extends
   it; coverage was verified manually and on synthetic data as described
   above. If automated coverage is required before Task 19, two small tests
   could be appended (not done to keep the brief's test file exact).
5. **`fit` is degenerate by construction.** With a constant label on the
   difference vector, coefficients are driven by the L2 penalty (and
   saturate under `project_weights`); this is inherent to the specified
   objective, not a bug in the implementation.
