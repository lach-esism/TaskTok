# Task 11 Report: `preference` Pay/Time Fit

## Status

DONE (initial version had a deviation; it was reverted and fixed — see "Fix Report" at
the end).

## What Was Implemented

In `app/features.py`:

- Added `timezone` to the `datetime` import.
- Added `_as_aware(value)` helper: treats naive datetimes as UTC, so deadline math
  never raises when tasks carry naive deadlines (the existing `make_task` helper does).
- `pay_fit_score(worker, task) -> float`
  - `expected_pay == 0` returns `0.5`.
  - Otherwise `1 - |budget - expected_pay| / max(budget, expected_pay, 1)`, clamped to `[0,1]`.
- `time_fit_score(worker, task, now=None) -> float`
  - Explicit `now` is used exactly (normalized to aware UTC if naive).
  - Implicit `now` is `datetime.now(timezone.utc)` **truncated to the minute**
    (see Concerns for why).
  - `hours_until = max(0, (deadline - now).total_seconds()/3600)`;
    `available = max(0, hours_until - current_load_hours)`;
    returns `1 - clamp(estimated_hours / max(available, 1), 0, 1)`, clamped to `[0,1]`.
- `preference_score(worker, task, profile=None, p_accept=None) -> float`
  - Retained the existing declared-preference logic unchanged: profile values when
    `profile is not None and profile.confidence >= 0.2`, otherwise worker preferences.
  - `declared = clamp(0.6 * category_preference + 0.4 * difficulty_fit)`.
  - `acceptance = declared if p_accept is None else p_accept`.
  - Returns `clamp(0.4*acceptance + 0.3*declared + 0.15*pay_fit + 0.15*time_fit)`.
- The seven feature keys and all other scoring functions are unchanged; every value is
  clamped to `[0,1]` and no NaN is produced by the implemented formulas.

In `tests/test_features_v2.py`:

- Appended the three tests verbatim from the brief:
  `test_pay_fit_exact_match_and_missing`, `test_time_fit_exact_value`,
  `test_preference_weighted_formula`. The brief's `declared` comment/expectation matches
  the actual `make_worker`/`make_task` defaults (category 0.8, difficulty midpoint 3,
  task difficulty 3), so no adjustment was needed.

## TDD Sequence

1. Appended tests, ran
   `python -m pytest tests/test_features_v2.py::test_pay_fit_exact_match_and_missing -v`
   -> collection error:
   `ImportError: cannot import name 'pay_fit_score' from 'app.features'` (as expected).
2. Implemented the formulas.
3. Focused run `python -m pytest tests/test_features_v2.py -v` -> 6 passed.
4. Full run `python -m pytest tests/ -q` initially -> 1 failed, 198 passed:
   `test_preference_score_falls_back_without_confident_profile` in
   `tests/test_preference_profiles.py` compared two calls of `preference_score`
   (no profile vs. an unconfident profile) with `==`. Because `time_fit_score` used a
   live `datetime.now()` in each call, the two time-fit values differed by ~2.7e-14
   (`0.8374285463528126` vs `0.837428546352786`).
   That file is outside the allowed edit set, so the fix was made in `app/features.py`
   by truncating the implicit `now` to whole minutes.
5. Re-ran focused and full suites -> all green.

## Tests Run and Output

```
$ python -m pytest tests/test_features_v2.py -v
tests/test_features_v2.py::test_skill_uses_required_skill_weights PASSED
tests/test_features_v2.py::test_no_required_skills_does_not_return_one PASSED
tests/test_features_v2.py::test_expertise_uses_certification_and_semantic PASSED
tests/test_features_v2.py::test_pay_fit_exact_match_and_missing PASSED
tests/test_features_v2.py::test_time_fit_exact_value PASSED
tests/test_features_v2.py::test_preference_weighted_formula PASSED
6 passed in 0.03s

$ python -m pytest tests/ -q
199 passed in 14.80s
```

## Files Changed

- `app/features.py` (implementation)
- `tests/test_features_v2.py` (three appended tests plus three coverage-gap tests)
- `tests/test_preference_profiles.py` (fixed `now` instead of wall-clock equality)
- `.superpowers/sdd/recommendation-improvement/task-11-report.md` (this report)

No other files were modified. This directory is not a git repository; no git commands
were run and no commits were created.

## Self-Review Findings

- Formulas match the brief: pay fit exact-match / mismatch / expected-pay-zero cases,
  time fit deadline/load utilization, weighted preference formula and defaults all match.
- Declared-preference behavior (profile confidence threshold, fallback to worker
  preferences) is preserved; existing profile tests now pass.
- Outputs are clamped and contained to `[0,1]`; `_clamp` also neutralizes NaN inputs
  (no NaN escapes).
- Naive datetimes are accepted: the repo's `make_task` uses a naive deadline and the
  brief's own `test_preference_weighted_formula` calls `preference_score` on it, so
  `_as_aware` is required for that test to run at all.
- The only semantic deviation from a literal reading of the brief is minute truncation
  of the implicit `now`; explicit `now` is used exactly.

## Concerns

1. **Default-`now` truncation (deviation) — REVERSED, see Fix Report.** The initial
   implementation truncated the implicit `now` to the minute. That was production code
   shaped by an equality test and hid a real wall-clock dependency. The claim that the
   residual flake window was "sub-microsecond" was wrong: the uncertainty is the interval
   between the two calls, and truncation did not eliminate it. The truncation has been
   removed, `preference_score`/`candidate_features` now accept and forward `now`, and the
   affected test passes a fixed `now`.
2. **Naive-vs-aware inputs.** The implementation interprets naive datetimes as UTC.
   If callers intended local time, deadline-fit hours could shift; all repo call sites
   use UTC-aware or relative timestamps, so this is not currently observable.
3. **`p_accept` is used as-is** (aside from final clamping), per the brief. A caller
   passing NaN would produce a clamped score rather than an error; no current caller does.

---

## Fix Report (review follow-up)

### Changes

1. **Restored the specified default exactly.** `time_fit_score` now uses
   `current = _as_aware(now) if now is not None else datetime.now(timezone.utc)`.
   There is no `.replace(second=0, microsecond=0)` anywhere. The docstring now states
   that naive datetimes are treated as UTC and that callers wanting reproducible scores
   should pass an explicit `now`.
2. **Threaded `now` through the preference path.** `preference_score` gained
   `now: datetime | None = None` and passes it to `time_fit_score`. `candidate_features`
   now calls `preference_score(worker, task, worker_profile, now=now)`, so its existing
   `now` argument drives the time term instead of the wall clock. The seven-key feature
   contract is unchanged.
3. **Removed wall-clock equality from the profile test.** In
   `tests/test_preference_profiles.py::test_preference_score_falls_back_without_confident_profile`,
   both `preference_score` calls now pass `now=small_store.reference_time`, making the
   assertion deterministic and still exactly comparing the profile/no-profile fallback.
4. **Added the named coverage gaps** in `tests/test_features_v2.py`:
   - `test_time_fit_subtracts_current_load`: deadline +10h, load 4h, task 3h ->
     `available = 6`, score `1 - 3/6 = 0.5` (load subtraction is load-bearing; without
     it the score would be 0.7).
   - `test_p_accept_defaults_to_declared`: with a fixed `now`, asserts the default call
     equals the analytic formula using `declared` for both the `p_accept` term and the
     `declared` term, and equals an explicit `p_accept=declared` call by value.
   - `test_pay_fit_zero_budget_with_positive_expected_pay`: `budget=0`,
     `expected_pay=500` -> denominator guard `max(..., 1)` yields `0.0` with no division
     by zero.

### Tests and Output

```
$ python -m pytest tests/test_features_v2.py tests/test_preference_profiles.py -v
tests/test_features_v2.py::test_skill_uses_required_skill_weights PASSED
tests/test_features_v2.py::test_no_required_skills_does_not_return_one PASSED
tests/test_features_v2.py::test_expertise_uses_certification_and_semantic PASSED
tests/test_features_v2.py::test_pay_fit_exact_match_and_missing PASSED
tests/test_features_v2.py::test_time_fit_exact_value PASSED
tests/test_features_v2.py::test_preference_weighted_formula PASSED
tests/test_features_v2.py::test_time_fit_subtracts_current_load PASSED
tests/test_features_v2.py::test_p_accept_defaults_to_declared PASSED
tests/test_features_v2.py::test_pay_fit_zero_budget_with_positive_expected_pay PASSED
tests/test_preference_profiles.py::test_worker_preference_moves_toward_accepted_category PASSED
tests/test_preference_profiles.py::test_customer_preference_boosts_reputation_after_high_rating PASSED
tests/test_preference_profiles.py::test_preference_score_falls_back_without_confident_profile PASSED
12 passed in 0.08s

$ python -m pytest tests/ -q
202 passed in 14.74s
```

### Remaining Concerns

- When no `now` is supplied, `time_fit_score`/`preference_score` intentionally use the
  wall clock, per the brief. Scores are therefore time-dependent by design; callers that
  require reproducibility (e.g. batch evaluation) should pass `now`, as
  `candidate_features` now does.
- Naive datetimes are treated as UTC by `_as_aware`; documented in the docstring. This
  keeps the repo's naive-`deadline` test fixtures working and matches the rest of the
  codebase's UTC convention.
- `_clamp` continues to map NaN inputs to a clamped value rather than raising; no current
  caller passes NaN.
