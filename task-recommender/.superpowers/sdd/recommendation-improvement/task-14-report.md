# Task 14 Report: ItemCF Normalization and Benchmark `collaborative` Fix

## Status: DONE_WITH_CONCERNS

## What was implemented

1. **`app/models/itemcf.py` — `ItemCF.normalize`**
   - Replaced query-local min-max normalization with divide-by-max:
     - empty input returns `{}`
     - if `max(raw.values()) <= 0`, every key is mapped to `0.0`
     - otherwise every key maps to `max(0.0, value) / maximum` (negative values clamp to 0).
   - Output remains in `[0, 1]`, so existing callers in `app/service.py`
     (lines ~291 and ~362) require no changes.

2. **`app/benchmark/features.py` — `BenchmarkFeatureBuilder`**
   - `__init__` now accepts `itemcf: ItemCF | None = None` and stores it as
     `self.itemcf`. Existing positional callers (benchmark `db.py`,
     `recommender.py`) remain source-compatible.
   - Removed the region/remote proxy (`1.0` / `0.8` / `0.3`) from
     `features()`.
   - `collaborative` is now `0.0` when no `itemcf` is supplied; otherwise it is
     the normalized ItemCF score for the `(worker_id, task_id)` pair:
     `itemcf.normalize({(worker_id, task_id): itemcf.score(worker_id, task_id)})[pair]`.
   - The seven feature keys and all other feature computations
     (`reputation`, `skill`, `expertise`, `preference`, `load`,
     `customer_preference`) are unchanged.

3. **Tests**
   - Appended `test_normalize_divides_by_max` and
     `test_normalize_all_zero_returns_zero` to `tests/test_itemcf.py`.
   - Appended `test_benchmark_collaborative_uses_itemcf_not_region` to
     `tests/test_benchmark.py`.
   - No pre-existing benchmark assertion encoded the old region behavior
     (searched `tests/` for `BenchmarkFeatureBuilder`, `collaborative`,
     `remote_ok`, `region`), so no existing assertions needed updating.
     The `preference`/`customer_preference` assertions are untouched.

## TDD evidence

Step 2 — new tests before implementation:

```
tests/test_itemcf.py::test_normalize_divides_by_max FAILED
  assert 0.0 == 0.5
tests/test_itemcf.py::test_normalize_all_zero_returns_zero PASSED
tests/test_benchmark.py::test_benchmark_collaborative_uses_itemcf_not_region FAILED
  TypeError: BenchmarkFeatureBuilder.__init__() got an unexpected keyword argument 'itemcf'
2 failed, 1 passed
```

`test_normalize_all_zero_returns_zero` already passed under min-max (all-equal
input produced zeros), as expected; the two behavior-changing tests failed.

Step 4 — focused tests after implementation:

```
tests/test_itemcf.py::test_cold_start_is_zero PASSED
tests/test_itemcf.py::test_similar_tasks_give_positive_score PASSED
tests/test_itemcf.py::test_normalize_bounds PASSED
tests/test_itemcf.py::test_normalize_divides_by_max PASSED
tests/test_itemcf.py::test_normalize_all_zero_returns_zero PASSED
tests/test_benchmark.py::test_benchmark_db_has_natural_language_rows_and_hidden_labels PASSED
tests/test_benchmark.py::test_recommender_forgets_predictions_but_keeps_weights PASSED
tests/test_benchmark.py::test_benchmark_endpoints PASSED
tests/test_benchmark.py::test_round_runner_learns_and_recomputes_each_round PASSED
tests/test_benchmark.py::test_benchmark_collaborative_uses_itemcf_not_region PASSED
10 passed in 0.97s
```

Step 5 — full suite:

```
$ python -m pytest tests/ -q
219 passed in 18.88s
```

Baseline before any changes: `216 passed in 18.55s` (216 + 3 new tests = 219).

## Files changed

- `app/models/itemcf.py`
- `app/benchmark/features.py`
- `tests/test_itemcf.py`
- `tests/test_benchmark.py`
- `.superpowers/sdd/recommendation-improvement/task-14-report.md` (this report)

No files outside the permitted set were modified; this directory is not a git
repository and no git commands were run.

## Self-review findings

- Diff reviewed against `.superpowers/sdd/.../snapshots/task-13/`; only the
  four intended files changed and only in the scoped regions.
- Existing `ItemCF.normalize` callers in `app/service.py` consume values as a
  `[0, 1]` feature; divide-by-max preserves that contract.
- The new benchmark test expects `t1` → `> 0.0` and `t2` → `>= 0.0`. Verified
  analytically: `score("w1", "t1") ≈ 1/6` (self-similarity `1/(1+5)`, denominator
  `max(1.0, 0.1667)`) normalizes to `1.0`; `score("w1", "t2") == 0.0` because
  `t2` shares no users with `t1`, and an all-zero single-entry input returns
  `0.0`.
- Negative raw scores are clamped to `0.0` and cannot produce values above
  `1.0`, since the denominator is the maximum positive value.
- `tests/test_itemcf.py` now contains a second `from app.models.itemcf import
  ItemCF` because the brief specifies its test block verbatim; it is redundant
  but harmless and was retained for spec fidelity.

## Concerns

1. **Benchmark integration is not wired.** `BenchmarkRecommender.__init__`
   (`app/benchmark/recommender.py`) and `build_benchmark_db`
   (`app/benchmark/db.py`) construct `BenchmarkFeatureBuilder` without an
   `itemcf`, so in real benchmark rounds `collaborative` is now constantly
   `0.0` instead of the old region/remote proxy. This follows the brief's
   interface (`itemcf: ItemCF | None = None`, else `0.0`) and the file-scope
   constraint (those two files were off-limits), and all benchmark tests still
   pass, but a future task should pass an `ItemCF` built from benchmark
   interactions if the `collaborative` weight is meant to contribute during
   benchmark evaluation.
2. **Behavior change in the service feature distribution.** Divide-by-max
   yields a single positive candidate at `1.0` where min-max would give `0.0`
   for the minimum. This is the intended spec change; downstream weight
   learning/evaluation tests all pass.
