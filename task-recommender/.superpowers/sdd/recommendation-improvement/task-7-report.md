# Task 7 Report — Strict Evaluation for Worker→Tasks, Multi-Seed, and CLI

## Status

DONE_WITH_CONCERNS (implementation complete and verified; concerns are about
degenerate report inputs, not correctness).

## What was implemented

### `app/evaluation_strict.py` (modified)

- Kept `build_eval_store`, impression resolution, and `task_to_workers_metrics`
  behavior unchanged. The internals of `task_to_workers_metrics` were factored
  into a per-query row helper so the aggregate metrics and the paired deltas
  use the same scoring path. All five pre-existing tests still pass.
- Added `worker_to_tasks_metrics(store, service, test_assignments, k=10,
  candidate_mode="all") -> dict`:
  - groups test assignments by worker;
  - ranks each worker's eligible tasks once with
    `service.recommend_tasks(worker_id, top_n=len(store.tasks))`;
  - evaluates every test assignment of that worker at `k`;
  - returns the same keys as `task_to_workers_metrics`
    (`hr`, `ndcg`, `mrr`, `queries`).
  - `candidate_mode` is validated against `VALID_CANDIDATE_MODES`.
    `"exposed"` is accepted for interface symmetry; because exposure logs are
    task-keyed (they list candidate workers), there is no worker-keyed exposure
    set to restrict to, so it uses the same eligible task ranking. This is
    documented in the docstring.
- Added `paired_bootstrap(deltas, n_boot=1000, seed=42) -> dict`:
  - resamples with replacement `n_boot` times;
  - `mean` is the observed mean (`statistics.fmean`);
  - `low`/`high` are the 2.5/97.5 percentiles of bootstrap means (linear
    interpolation);
  - `p_value = min(1.0, 2 * min(P(mean <= 0), P(mean >= 0)))`;
  - empty input returns all-zero metrics with `p_value=1.0`.
- Added `evaluate_strict(dataset, weights, k=10, seeds=(42,)) -> dict` with the
  required keys plus `k`:
  - for each seed, calls `generate_dataset(seed=seed)`, builds a train-only
    eval store with `build_eval_store`, and scores `DEFAULT_WEIGHTS` (baseline)
    against the supplied candidate `weights`;
  - evaluates task→workers in `"all"` and `"exposed"` modes and worker→tasks
    in `"all"` mode. `"exposed"` receives `dataset.test_impressions` as the
    evaluation-only argument and the store is never mutated;
  - pools per-query deltas across seeds and reports paired-bootstrap mean,
    95% interval, and p-value for HR/NDCG/MRR;
  - reports cold-start subsets for test assignments whose worker has no train
    assignment;
  - counts hard-constraint violations in the candidate top-k using
    `is_eligible`;
  - measures latency for the candidate service over 100 alternating
    task→workers / worker→tasks recommendations (`time.perf_counter`), then
    reports p50/p95 in milliseconds.
  - `dataset` is used only when `seeds` is empty (documented fallback).

### `scripts/evaluate_strict.py` (created)

- `main(argv: list[str] | None = None) -> int`.
- `argparse` options `--seeds` (comma-separated, default `42`), `--k` (default
  `10`), and `--out-dir` (default `reports`).
- Reads the active learned weights from `data/weights/active.json` (read-only)
  as the candidate; falls back to `DEFAULT_WEIGHTS` when missing/malformed.
- Calls `evaluate_strict`, writes `strict_eval.json` and `strict_eval.md`
  (baseline/candidate/delta/cold-start tables, violations, latency), prints a
  JSON summary, and returns `0`.

### `tests/test_strict_eval.py` (modified)

Appended the two tests from the brief verbatim:
- `test_worker_to_tasks_metrics_are_bounded`
- `test_paired_bootstrap_detects_positive_delta`

## Tests run

1. Before implementation, focused run confirmed the expected failure:

```text
$ python -m pytest tests/test_strict_eval.py -v
E   ImportError: cannot import name 'paired_bootstrap' from 'app.evaluation_strict'
============================== 1 error in 1.10s ==============================
```

2. Focused tests after implementation:

```text
$ python -m pytest tests/test_strict_eval.py -v
7 passed in 0.17s
```

3. Full suite after implementation and after the final refactor:

```text
$ python -m pytest tests/ -q
181 passed in 14.48s
```

(179 before this task; +2 new tests.)

4. Extra smoke check of the `seeds=()` fallback on the small fixture
   (20 workers / 60 tasks / 200 assignments): all required keys present,
   cold-start subset non-empty (1 query), 0 violations, no exceptions.

## CLI run

```text
$ python scripts/evaluate_strict.py --seeds 42 --k 5
EXIT=0
```

`reports/strict_eval.json` (4408 bytes) and `reports/strict_eval.md` (2111
bytes) were written. Runtime was about 47 s for one seed.

Key output (seed 42, k=5, 600 queries per direction):

| Direction | HR | NDCG | MRR |
|---|---|---|---|
| task_to_workers | 0.4617 | 0.2899 | 0.2336 |
| task_to_workers_exposed | 0.4667 | 0.2919 | 0.2347 |
| worker_to_tasks | 0.0150 | 0.0068 | 0.0042 |

- `constraint_violations`: 0
- `latency_p50_ms`: 12.5272
- `latency_p95_ms`: 28.7187
- Deltas: all zero with `p_value=1.0`, because the active weight version is
  `v0000`, which is identical to `DEFAULT_WEIGHTS` (the baseline). The
  one-seed report is therefore a plumbing check, not evidence of improvement.
- Cold start: `queries=0` for all directions with the default generated
  dataset (every worker has at least one train assignment).

## Files changed

- `app/evaluation_strict.py` (modified)
- `scripts/evaluate_strict.py` (created)
- `tests/test_strict_eval.py` (modified)
- `reports/strict_eval.json` (generated by the required CLI run)
- `reports/strict_eval.md` (generated by the required CLI run)
- `.superpowers/sdd/recommendation-improvement/task-7-report.md` (this report)

## Self-review findings

- Preserved `task_to_workers_metrics` public output and its 5 existing tests
  after the internal per-query refactor.
- Added a per-service ranking cache shared by the `"all"` and `"exposed"`
  task→workers passes, so exposure filtering does not trigger a second full
  ranking pass.
- Constraint checks use `is_eligible` against the train-only store and returned
  0 for the candidate top-k, as expected because the service only emits
  eligible candidates.
- Fixed a self-referential type alias introduced during the refactor
  (`Row = Row`); the alias now correctly names the row tuple, and the focused
  and full suites were re-run afterwards.
- No code path reads `data/ground_truth.csv` or benchmark `labels`.
  `generate_dataset` is called with its default `with_ground_truth=True` as the
  brief's call signature specifies, but `true_weights` is never accessed by
  the evaluator.
- `_load_candidate_weights` reads `active.json` and its version file without
  creating or modifying weight files.

## Concerns

1. **Degenerate one-seed report.** The CLI's candidate weights come from
   `data/weights/active.json`, currently `v0000`, which equals
   `DEFAULT_WEIGHTS`. All deltas are therefore zero. Task 20 must activate a
   learned weight version (for example via `POST /weights/recompute`) or the
   CLI needs a weights override before the accuracy targets can be evaluated.
2. **Cold-start subset is empty on default data.** With 100 workers and 3000
   assignments every worker has train history, so `cold_start.*.queries` is 0
   and the cold-start guardrail is vacuous. A smaller assignment count or an
   explicit cold-worker cohort would make this measurable.
3. **worker→tasks `"exposed"` is not distinct.** The brief's signature has no
   evaluation-only impressions argument for this direction, and exposure logs
   are task-keyed. The parameter is validated and documented as equivalent to
   `"all"`. A future extension could add `impressions=` for worker→tasks and
   restrict to tasks where the worker was exposed.
4. **Runtime.** About 47 s per seed (roughly 4 minutes for the planned five
   seeds) because both services rank all workers/tasks for every test query.
   Acceptable for a report CLI, but noteworthy for Task 20.
5. **`evaluate_strict` regenerates data per seed.** The passed `dataset` is
   only used when `seeds` is empty; with seeds it is ignored and fresh default
   datasets are generated. This follows the brief but is surprising for
   callers holding a custom dataset. The CLI pays one extra ~0.57 s generation
   for the argument it must pass.
6. **Latency is candidate-only.** The result contains only the candidate
   service's p50/p95; the spec's "≤2× baseline" guardrail needs a baseline
   latency measurement that this brief did not request.

---

# Fix Round 1 (coordinator feedback)

## Fixes applied

### 1. CLI now compares a real candidate to the baseline

- Added `--candidate-weights PATH` (optional JSON object, or a WeightStore
  version file whose payload has a `weights` object). Precedence:
  `--candidate-weights` → active weight version → `DEFAULT_WEIGHTS`.
- The baseline is always `DEFAULT_WEIGHTS`.
- Unknown keys are allowed, but values must be numeric and sum to 1.0
  (within 1e-6) or the CLI exits `2` with a clear message instead of failing
  inside `fuse_scores`.
- `evaluate_strict` now returns `baseline_equals_candidate`. The CLI copies it
  into `strict_eval.json`, prints it in the summary, and writes both a
  `- baseline_equals_candidate: true|false` line and, when true, an explicit
  warning block in `strict_eval.md` stating the zero deltas are by construction
  and not a result. The CLI also records `candidate_source`
  (`override` / `active` / `default`).
- Added a `worker_to_tasks_exposed` direction to the report (uses the new
  evaluation-only impression path), so the JSON/Markdown have four directions.

### 2. worker→tasks `"exposed"` has an evaluation-only impressions path

- `worker_to_tasks_metrics(..., impressions: list[Impression] | None = None)`.
- In `"exposed"` mode, a worker-keyed exposure map is built from the provided
  impressions (or `store.impressions` when `None`):
  `worker_id -> {impression.query_id for impressions listing that worker}`.
  The worker's ranked tasks are then restricted to that set, preserving the
  ranking order. If no exposed task appears for a worker, the full `"all"`
  ranking is used.
- The provided impressions are read only; nothing is written into the store.
- `evaluate_strict` passes `dataset.test_impressions` to both exposed
  directions and shares a ranking cache per service/direction family.
- New test:
  `test_worker_to_tasks_exposed_uses_test_impressions_without_mutation`
  passes `dataset.test_impressions`, asserts `queries == 20`, and asserts the
  store's impression list still equals the train-only list and is disjoint from
  the test request ids.

### 3. Cold start is explicit

- `evaluate_strict` now returns:
  ```json
  "cold_start": {
    "available": false,
    "reason": "no workers without train assignments in the evaluated seeds",
    "baseline": {...},
    "candidate": {...},
    "deltas": {...}
  }
  ```
- `available` is true only if at least one evaluated dataset contains a worker
  with zero train assignments. If cold workers exist but have no test
  assignments, `available` is true and the reason says so. Markdown reports
  both `available` and the reason instead of implying the guardrail passed.
- On the default generated dataset the subset is empty and now explicitly
  reports `available: false`.

## Tests run after fixes

```text
$ python -m pytest tests/test_strict_eval.py -v
8 passed in 0.15s

$ python -m pytest tests/ -q
182 passed in 15.00s
```

## CLI output after fixes

### Default run (no override): explicit identity

```text
$ python scripts/evaluate_strict.py --seeds 42 --k 5
EXIT=0
```

`reports/strict_eval.md` contains:

```text
- Candidate source: active
- baseline_equals_candidate: true

> **baseline_equals_candidate: true** — candidate weights are identical to the
> baseline; the deltas below are shown as n/a because they are zero by
> construction and are not evidence of improvement.
```

The delta cells in the default report render as
`n/a (identical weights)` instead of zero values.

`reports/strict_eval.json`: `baseline_equals_candidate: true`,
`candidate_source: "active"`, `cold_start.available: false`,
`cold_start.reason: "no workers without train assignments in the evaluated
seeds"`, `constraint_violations: 0`, latency p50/p95 12.3842 / 29.1158 ms.

### Override run: real candidate comparison

```text
$ python scripts/evaluate_strict.py --seeds 42 --k 5 \
    --candidate-weights data/weights/weights_v0007.json
CLI_EXIT=0
```

Printed summary (trimmed to the result fields):

```json
{
  "candidate_source": "override",
  "baseline_equals_candidate": false,
  "baselines": {
    "task_to_workers": {"hr": 0.4617, "ndcg": 0.2899, "mrr": 0.2336, "queries": 600},
    "task_to_workers_exposed": {"hr": 0.4667, "ndcg": 0.2919, "mrr": 0.2347, "queries": 600},
    "worker_to_tasks": {"hr": 0.0150, "ndcg": 0.0068, "mrr": 0.0042, "queries": 600},
    "worker_to_tasks_exposed": {"hr": 0.2850, "ndcg": 0.1650, "mrr": 0.1259, "queries": 600}
  },
  "candidate": {
    "task_to_workers": {"hr": 0.4650, "ndcg": 0.2914, "mrr": 0.2346, "queries": 600},
    "task_to_workers_exposed": {"hr": 0.4700, "ndcg": 0.2934, "mrr": 0.2357, "queries": 600},
    "worker_to_tasks": {"hr": 0.0250, "ndcg": 0.0112, "mrr": 0.0068, "queries": 600},
    "worker_to_tasks_exposed": {"hr": 0.2833, "ndcg": 0.1643, "mrr": 0.1255, "queries": 600}
  },
  "deltas": {
    "task_to_workers": {
      "hr": {"mean": 0.0033, "low": -0.0067, "high": 0.0133, "p_value": 0.636},
      "ndcg": {"mean": 0.0015, "low": -0.0025, "high": 0.0054, "p_value": 0.462}
    },
    "worker_to_tasks": {
      "hr": {"mean": 0.0100, "low": 0.0033, "high": 0.0183, "p_value": 0.0},
      "ndcg": {"mean": 0.0043, "low": 0.0015, "high": 0.0077, "p_value": 0.0}
    },
    "worker_to_tasks_exposed": {
      "hr": {"mean": -0.0017, "low": -0.0117, "high": 0.0100, "p_value": 0.906}
    }
  },
  "cold_start": {
    "available": false,
    "reason": "no workers without train assignments in the evaluated seeds"
  },
  "constraint_violations": 0,
  "latency_p50_ms": 12.4588,
  "latency_p95_ms": 27.9508
}
```

The override run produces non-zero deltas: worker→tasks HR +0.0100
(CI [0.0033, 0.0183], p=0.0), NDCG +0.0043 (CI [0.0015, 0.0077], p=0.0),
while task→workers remains within noise. `reports/strict_eval.json` and
`reports/strict_eval.md` now reflect this override run.

## Files changed in fix round

- `app/evaluation_strict.py` (modified: impressions path, worker→tasks exposed
  direction, cold-start availability, `baseline_equals_candidate`)
- `scripts/evaluate_strict.py` (modified: `--candidate-weights`, weight
  validation, explicit identity warning, cold-start reporting, new direction)
- `tests/test_strict_eval.py` (modified: new exposed-path immutability test)

## Remaining concerns after fixes

1. The default CLI run still produces zero deltas because the active version is
   the prior; this is now explicitly flagged as `baseline_equals_candidate:
   true` rather than presented as a result. Task 20 should pass a learned
   weights JSON.
2. The default generated dataset has no cold workers, so `cold_start.available`
   is false. This is explicit, but the cold-start guardrail still cannot be
   exercised with default generation settings.
3. Runtime remains ~47 s per seed; the override run also took this long.
4. `evaluate_strict` still regenerates per non-empty seed and uses the passed
   dataset only when `seeds` is empty (accepted, documented).
5. Latency remains candidate-only; the baseline comparison for the 2× guardrail
   is still not measured.
