# Task 6 Report: Strict Evaluation Data Assembly and Task→Workers Metrics

## Status

DONE_WITH_CONCERNS (behavior matches the brief; one interface-level caveat documented below).

## What was implemented

### `tests/conftest.py`

Added the shared `dataset` fixture specified by the brief:

```python
@pytest.fixture
def dataset():
    return generate_dataset(
        n_workers=20, n_tasks=60, n_assignments=200, seed=42, n_new_users=0,
    )
```

`generate_dataset` is imported alongside the existing `SKILLS` import. No existing fixture was changed.

### `tests/test_strict_eval.py` (new)

Contains the three tests from the brief verbatim:

- `test_build_eval_store_excludes_test_feedback`
- `test_task_to_workers_metrics_are_bounded`
- `test_exposed_mode_resolves_by_assignment_id`

Plus one supplementary test, `test_exposed_mode_ranks_the_resolved_candidate_set`. The brief's tie test only asserts `queries == 1`, which does not prove which tied impression was selected. The extra test puts the positive worker in the assignment-id-matched impression and asserts `hr == 1.0`; when the mismatched ("other") impression is supplied alone, the same path returns `hr == 0.0`, so the test discriminates resolution by `assignment_id`.

### `app/evaluation_strict.py` (new)

- `build_eval_store(dataset)`: returns a `Store` built from `dataset.workers`, `customers`, `tasks`, and train-only `train`, `train_feedback`, `train_events`, `train_impressions`. It does not read `dataset.test*`, `ground_truth`, or benchmark `labels`.
- `task_to_workers_metrics(store, service, test_assignments, k=10, candidate_mode="all")`:
  - Skips assignments whose task is absent from `store.tasks`; otherwise counts the assignment as a query (including assignments whose positive is not in the ranking, which contribute zero, per the brief).
  - `"all"`: ranks every eligible worker via `service.recommend_workers(task_id, top_n=len(store.workers))`.
  - `"exposed"`: resolves the impression by `metadata["assignment_id"]` first; if none matches, falls back to `(query_id, created_at)` for impressions with no assignment metadata; if still unresolved, falls back to `"all"`. The impression's candidate IDs are filtered out of the service ranking in service order, and any candidate absent from the ranking is appended at the end (impression order, de-duplicated).
  - Metrics: `hr = 1` when `rank < k`; `ndcg = 1 / log2(rank + 2)`; `mrr = 1 / (rank + 1)`; all zero when the positive is missing or `rank >= k`. Averages over evaluated queries and returns `{"hr": float, "ndcg": float, "mrr": float, "queries": int}`.
  - Unknown `candidate_mode` raises `ValueError`.

No new dependencies. No git commands were run.

## Tests run and output

1. Baseline before changes: `python -m pytest tests/ -q` → `174 passed in 14.43s`.
2. Failing first: `python -m pytest tests/test_strict_eval.py -v` → collection error, exit 2:
   `ModuleNotFoundError: No module named 'app.evaluation_strict'` (as expected).
3. Focused after implementation: `python -m pytest tests/test_strict_eval.py -v` → `4 passed in 0.18s`.
   - `test_build_eval_store_excludes_test_feedback` PASSED
   - `test_task_to_workers_metrics_are_bounded` PASSED
   - `test_exposed_mode_resolves_by_assignment_id` PASSED
   - `test_exposed_mode_ranks_the_resolved_candidate_set` PASSED
4. Full suite: `python -m pytest tests/ -q` → `178 passed in 14.60s`.

## Fixture metrics recorded at the checkpoint

Dataset (seed=42, 20 workers, 60 tasks, 200 assignments, 0 new users): 160 train / 40 test assignments; 113 train / 25 test feedback rows; 160 train / 40 test impressions.

`task_to_workers_metrics` on the fixture:

| mode | k | hr | ndcg | mrr | queries |
|---|---|---|---|---|---|
| all | 5 | 0.9250 | 0.7304 | 0.6646 | 40 |
| all | 10 | 0.9500 | 0.7393 | 0.6688 | 40 |
| exposed (train impressions in eval store) | 10 | 0.9500 | 0.7393 | 0.6688 | 40 |
| exposed (genuine `dataset.test_impressions` injected) | 10 | 1.0000 | 0.7615 | 0.6821 | 40 |
| all, first 20 test assignments | 10 | 0.9000 | 0.8031 | 0.7708 | 20 |

The `exposed` row using the plain eval store equals `all` because `build_eval_store` intentionally holds train-only impressions (see Concern 1).

Additional ad-hoc verification:

- Train/test isolation: assignment, feedback, event, and impression ID sets in the eval store are all disjoint from the corresponding test splits.
- Negative resolution check: only the mismatched tied impression in the store → `hr=0.0`, `ndcg=0.0`, `mrr=0.0`, `queries=1`.
- Legacy timestamp fallback: an impression with empty `metadata` matching `(query_id, created_at)` → `hr=1.0`, `ndcg=1.0`, `mrr=1.0`, `queries=1`.

## Files changed

- `app/evaluation_strict.py` (created)
- `tests/test_strict_eval.py` (created)
- `tests/conftest.py` (added `dataset` fixture and `generate_dataset` import)
- `.superpowers/sdd/recommendation-improvement/task-6-report.md` (this report)

## Self-review findings

1. The brief's tie test does not distinguish assignment-id resolution from timestamp resolution; added a supplementary discriminating test (verified it fails on the wrong tied impression).
2. Fixed one line over the project's 79-column style in `app/evaluation_strict.py`.
3. Verified `build_eval_store` passes only train splits, and no ground-truth/label imports exist.
4. Verified the `"all"` path does not consult impressions at all.
5. Confirmed deduplication and stable ordering when merging impression candidates with the service ranking.
6. Checked `k <= 0` behaves as "no hits" (rank is never negative, so nothing qualifies).

## Concerns

1. **RESOLVED in fix round 1 (see below).** `"exposed"` mode originally only searched `store.impressions`, which is train-only after `build_eval_store`, so it always fell back to `"all"` without a caller-side store swap. The new evaluation-only `impressions` parameter lets callers pass `dataset.test_impressions` directly without mutating the store.
2. **Timestamp fallback is restricted to metadata-less impressions**, per the ledger ruling that fallback happens "only when metadata is absent". An impression stamped for a different `assignment_id` is never selected on a `(query_id, created_at)` tie. This is the intended isolation behavior.
3. `candidate_mode` validation is stricter than the brief (unknown values raise `ValueError` rather than silently defaulting).
4. `_as_utc` duplicates the same helper in `app/domain.py` / `app/data/store.py`; duplication is a known deferred cleanup in the ledger.
5. Assignments whose accepted worker is absent from the candidate set still count in `queries` (with zero metric contribution), as the brief specifies; consumers comparing `queries` to HR denominators should be aware.

## Fix round 1: evaluation-only `impressions` parameter

Reviewer feedback: `"exposed"` must work end-to-end without contaminating the train-only store. Implemented the updated brief.

### Changes

- `app/evaluation_strict.py`
  - `task_to_workers_metrics(..., impressions: list[Impression] | None = None)`.
  - `"exposed"` searches `impressions` when provided, otherwise `store.impressions`.
  - The provided impressions are read-only: they are never assigned to the store and never reach `RecommendationService`, feature code, or training code. `"all"` mode ignores them entirely.
  - Resolution order unchanged: `metadata["assignment_id"]` first, then `(query_id, created_at)` for metadata-less impressions, then fall back to `"all"`. A stamped impression for another assignment still cannot win a timestamp tie.
  - `_ranked_candidates` takes the impression source as an explicit argument.
- `tests/test_strict_eval.py`
  - Added `test_exposed_mode_accepts_test_impressions_without_store_mutation`: passes `dataset.test_impressions` directly, asserts `queries == len(dataset.test)`, `hr == 1.0` (exposed restriction, vs 0.95 for `"all"`), `store.impressions` is unchanged, its request IDs equal the train-impression set, and they are disjoint from `dataset.test_impressions`.
  - Kept the supplementary tie test from the initial round.

### Covering tests and output

Command: `python -m pytest tests/test_strict_eval.py -v`

```
tests/test_strict_eval.py::test_build_eval_store_excludes_test_feedback PASSED
tests/test_strict_eval.py::test_task_to_workers_metrics_are_bounded PASSED
tests/test_strict_eval.py::test_exposed_mode_resolves_by_assignment_id PASSED
tests/test_strict_eval.py::test_exposed_mode_ranks_the_resolved_candidate_set PASSED
tests/test_strict_eval.py::test_exposed_mode_accepts_test_impressions_without_store_mutation PASSED
5 passed in 0.19s
```

Command: `python -m pytest tests/ -q`

```
179 passed in 14.55s
```

### End-to-end fixture metrics with the new parameter

| mode | k | hr | ndcg | mrr | queries |
|---|---|---|---|---|---|
| all | 5 | 0.9250 | 0.7304 | 0.6646 | 40 |
| exposed (`impressions=dataset.test_impressions`) | 5 | 0.9750 | 0.7526 | 0.6779 | 40 |
| all | 10 | 0.9500 | 0.7393 | 0.6688 | 40 |
| exposed (`impressions=dataset.test_impressions`) | 10 | 1.0000 | 0.7615 | 0.6821 | 40 |

`store.impressions` request IDs were verified unchanged after the exposed runs.

### Remaining concerns

- Timestamp fallback remains restricted to metadata-less impressions (intended isolation, per the ruling).
- Unknown `candidate_mode` still raises `ValueError`.
- `_as_utc` remains duplicated with `app/domain.py` / `app/data/store.py` (deferred cleanup).
