# Task 13 Report: `load` and `customer_preference` Upgrades plus Service Wiring

Status: DONE_WITH_CONCERNS (all tests green; two interpretation notes below)

## What was implemented

### `app/preference/customer.py`
- `DEFAULT_ATTRIBUTE_WEIGHTS` is now exactly:
  `{reputation: 0.30, expertise: 0.20, speed: 0.15, communication: 0.10, price: 0.10, collaboration: 0.10, deadline_fit: 0.05}` (sums to 1.0).

### `app/features.py`
- `load_score(worker, task, now=None, recent_impressions=0)`:
  - `capacity_score = clamp((capacity - current_load - task_hours) / capacity)`, `0.0` when capacity `<= 0`;
  - `deadline_feasibility = time_fit_score(worker, task, now=now)`;
  - `exposure_fairness = exp(-max(0, recent_impressions) / 20)`;
  - returns `clamp(0.6*capacity + 0.25*deadline + 0.15*exposure)`.
- `customer_preference_score(...)` now accepts keyword-only `pay_fit`, `deadline_feasibility`, `collaboration`, `communication`:
  - confident profile (`confidence >= 0.2`): merges profile weights over `DEFAULT_ATTRIBUTE_WEIGHTS`, fills missing keys from defaults, normalizes by the merged weight sum, and scores reputation, expertise, speed (`on_time/completed`, else `0.5`), communication, price=`pay_fit`, collaboration=`min(1, count/3)` (design §8.7), deadline_fit=`deadline_feasibility`;
  - no confident profile: `0.4*reputation + 0.3*expertise + 0.15*load + 0.15*pay_fit`.
- `candidate_features(...)` signature extended with `p_accept=None`, `recent_impressions=0`, plus keyword-only `pay_fit`, `communication`, `collaboration`:
  - forwards `semantic_similarity` into `expertise_score`, `p_accept` and `now` into `preference_score`, `now`/`recent_impressions` into `load_score`, and the supplied values into `customer_preference_score`;
  - computes `pay_fit` and `communication` when not supplied.
  - All seven keys unchanged and bounded to `[0,1]`.

### `app/service.py`
- `RecommendationService.__init__(..., semantic_matcher=None, acceptance_model=None)`.
- Both recommendation methods now compute, once per call:
  - `recent = store.recent_impression_counts(reference_time)`;
  - an accept/reject count index over `store.events` (skipped entirely when no acceptance model is injected);
  - a `(customer_id, worker_id) -> prior completed count` index built with one pass over assignments (same predicate and cutoff as `Store.prior_collaboration_count`, so semantics are identical).
- Per candidate: `communication` from `worker.communication_ratings`, `pay_fit_score`, `semantic_matcher.similarity(build_task_text, build_worker_text)` (0.5 when no matcher), `region_match` (1.0 / 0.8 / 0.3), `historical_accept_rate = (accepted+1)/(accepted+rejected+2)` or 0.5, and `p_accept = acceptance_model.predict(accept_features(...))` only when the model is fitted.
- All values are passed into `candidate_features`.

### `app/main.py`
- `_build_semantic_matcher(store)` fits one `build_matcher()` over all worker texts and task texts; returns `None` when fit fails or the matcher is unfitted.
- `_build_acceptance_model(store)` fits one global `AcceptanceModel` from worker accept/reject events, using `accept_features` (skill, pay fit, region match, historical accept rate); returns `None` when unfitted.
- `create_app` builds both once, stores them on `app.state`, and passes them to every `RecommendationService` construction (node candidate helper, metrics compare, both recommend routes, chain plan, chain replan).
- Default dataset store now uses train-only data: `dataset.train_feedback`, `dataset.train_events`, `dataset.train_impressions`.

### Tests
- `tests/test_features_v2.py`: appended `test_load_formula_with_exposure` and `test_customer_attribute_weights_sum_to_one_and_include_new_keys`.
- `tests/test_preference_profiles.py`: added `test_default_attribute_weights_cover_all_attributes_and_sum_to_one` asserting the exact new dict.
- `tests/test_recommend.py`: added `test_service_wires_new_feature_inputs`.

## Tests run and output

New tests confirmed failing before implementation:
- `test_customer_attribute_weights_sum_to_one_and_include_new_keys` FAILED (keys absent);
- `test_load_formula_with_exposure` FAILED (`TypeError`, unexpected `recent_impressions`);
- `test_default_attribute_weights_cover_all_attributes_and_sum_to_one` FAILED (old weights).

Focused suite after implementation:
```
python -m pytest tests/test_features_v2.py tests/test_preference_profiles.py tests/test_recommend.py -v
...
28 passed in 1.09s
```

Full suite:
```
python -m pytest tests/ -q
215 passed in 18.72s
```
Baseline before this task was 211 passed in 14.64s (4 added tests).

Sanity check of the live default app: `/recommend/workers` and `/recommend/tasks` return 200, all seven breakdown values in `[0,1]` and no NaN.

## Files changed
- `app/features.py`
- `app/preference/customer.py`
- `app/service.py`
- `app/main.py`
- `tests/test_features_v2.py`
- `tests/test_preference_profiles.py`
- `tests/test_recommend.py`
- `.superpowers/sdd/recommendation-improvement/task-13-report.md` (this report)

## Self-review findings
1. **Performance fix:** the first implementation called `Store.prior_collaboration_count` per candidate and scanned `store.events` and impressions per recommendation. That made `/metrics/compare` take ~62s (full suite 77s). Collaboration is now indexed once per call from assignments and accept counts are skipped when no model is injected. `/metrics/compare` is back to ~3.7s and the full suite to ~18.7s. The index reproduces `Store.prior_collaboration_count` exactly (completed status, timestamp `< reference_time`).
2. **Signature addition:** the brief's printed `candidate_features` signature omits `pay_fit`/`communication`/`collaboration`, yet Step 3 says to "compute `pay_fit` and `communication` if not supplied" and to pass all service-computed values (including collaboration, which cannot be derived without the store) into it. I kept the documented parameters intact and added those three as optional keyword-only extras, so all existing call sites remain compatible.
3. **Store-derived values:** `collaboration` is passed raw and normalized to `min(1, count/3)` inside `customer_preference_score`, matching design §8.7 and keeping attribute values bounded.
4. **Leakage:** the default dataset store now excludes test feedback/events/impressions, so the semantic corpus and acceptance model never see held-out data. Explicitly injected stores are used as-is.

## Concerns
- ~~The fallback branch of `customer_preference_score` calls `load_score` without `now`, leaving the 15% load term wall-clock dependent.~~ Resolved: the updated brief adds `now` to `customer_preference_score`, the fallback now forwards it, and `test_customer_preference_fallback_uses_supplied_now` covers it (see the fix report below).
- `create_app` now fits the semantic matcher and acceptance model at startup (~1.5s on the default 100-worker/500-task dataset), adding ~4s to the full suite (dominated by two default-app tests). This is expected from the task's wiring requirement.
- `_build_semantic_matcher`/`_build_acceptance_model` swallow broad exceptions and fall back to `None` per "pass `None` if it cannot fit"; this is intentional degradation but would also hide programming errors in those builders.

---

# Fix Report: Reproducible `customer_preference_score` Fallback

Status: FIXED

## Change
The updated brief adds `now: datetime | None = None` to `customer_preference_score`. Implemented:

- `app/features.py`:
  - `customer_preference_score(..., now: datetime | None = None)`;
  - the no-profile fallback now calls `load_score(worker, task, now=now)` so its load term uses the data-relative reference instead of the wall clock;
  - `candidate_features` forwards its existing `now` into `customer_preference_score` (`preference_score` already received it).
- `tests/test_features_v2.py`: added `test_customer_preference_fallback_uses_supplied_now`, which uses a fixed `now` (2020-01-01) and a `CustomerPreferenceProfile` with `confidence=0.1` (below the 0.2 threshold). It asserts:
  - the value equals the fallback formula computed with `load_score(..., now=now)`;
  - the wall-clock load differs from the supplied-`now` load, and the returned value differs from the wall-clock fallback value, proving the supplied `now` is used.

No other files changed for this fix; the accepted extensions (keyword-only `pay_fit`/`communication`/`collaboration`), startup fit, and per-call collaboration index remain as-is.

## Commands and output
```
python -m pytest tests/test_features_v2.py::test_customer_preference_fallback_uses_supplied_now -v
tests/test_features_v2.py::test_customer_preference_fallback_uses_supplied_now PASSED
1 passed in 0.05s

python -m pytest tests/test_features_v2.py tests/test_preference_profiles.py tests/test_recommend.py -q
29 passed in 1.14s

python -m pytest tests/ -q
216 passed in 18.57s
```
(The new test passed; before this fix the returned value would have matched the wall-clock fallback, failing the final two assertions.)

## Remaining concerns
- None for this fix. The fallback load term is now data-relative whenever a caller supplies `now` (the service and `candidate_features` do). Callers that omit `now` still get the previous wall-clock behavior by design.
