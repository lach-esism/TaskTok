## Task 7: Strict Evaluation for Worker→Tasks, Multi-Seed, and CLI

**Files:**
- Modify: `app/evaluation_strict.py`
- Create: `scripts/evaluate_strict.py`
- Test: `tests/test_strict_eval.py` (extend)

**Interfaces:**
- Consumes: `build_eval_store`, `task_to_workers_metrics`.
- Produces:
  - `worker_to_tasks_metrics(store, service, test_assignments, k=10, candidate_mode="all", impressions: list[Impression] | None = None) -> dict` with the same keys as `task_to_workers_metrics`. `"exposed"` restricts each worker's candidate tasks to tasks where that worker appears in an impression (provided list, else `store.impressions`); `impressions` is evaluation-only and never written to the store.
  - `paired_bootstrap(deltas: list[float], n_boot: int = 1000, seed: int = 42) -> dict` with `{"mean", "low", "high", "p_value"}`.
  - `evaluate_strict(dataset: Dataset, weights: dict[str, float], k: int = 10, seeds: tuple[int, ...] = (42,)) -> dict` with keys `seeds`, `baselines`, `candidate`, `deltas`, `cold_start`, `constraint_violations`, `latency_p50_ms`, `latency_p95_ms`. When `seeds` is non-empty, regenerate a dataset per seed; when empty, use the passed `dataset`. Include `cold_start.available` so an empty subset is explicit rather than vacuous.
  - `scripts/evaluate_strict.py` with `main(argv: list[str] | None = None) -> int`; args `--seeds`, `--k`, `--out-dir`, and `--candidate-weights PATH` (optional JSON dict; default: the active weight version if available, else `DEFAULT_WEIGHTS`). Baseline is always `DEFAULT_WEIGHTS`; candidate is the override. Writes `reports/strict_eval.json` and `reports/strict_eval.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_strict_eval.py`:

```python
from app.evaluation_strict import paired_bootstrap, worker_to_tasks_metrics


def test_worker_to_tasks_metrics_are_bounded(dataset):
    store = build_eval_store(dataset)
    service = RecommendationService(store)
    metrics = worker_to_tasks_metrics(store, service, dataset.test[:20], k=10)
    assert metrics["queries"] > 0
    assert 0.0 <= metrics["hr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0


def test_paired_bootstrap_detects_positive_delta():
    result = paired_bootstrap([0.1] * 50, n_boot=200, seed=42)
    assert result["mean"] == 0.1
    assert result["low"] > 0.0
    assert result["high"] >= result["low"]
    assert 0.0 <= result["p_value"] <= 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_strict_eval.py::test_worker_to_tasks_metrics_are_bounded -v`
Expected: FAIL with `ImportError` or `AttributeError`.

- [ ] **Step 3: Implement worker→tasks metrics and the CLI**

- `worker_to_tasks_metrics`: group test assignments by worker; for each worker, the positive task is the assignment's `task_id`; rank the worker's eligible tasks using `service.recommend_tasks(worker_id, top_n=len(store.tasks))`; compute HR/NDCG/MRR at `k`; average. In `"exposed"` mode, restrict the candidate tasks to those where the worker appears in `impressions if impressions is not None else store.impressions`; if none appear, fall back to `"all"`.
- `paired_bootstrap`: resample `deltas` with replacement `n_boot` times; compute the mean each time; `low/high` are the 2.5/97.5 percentiles; `p_value` = fraction of bootstrap means ≤ 0 (or ≥ 0; use the two-sided convention `2 * min(fraction ≤ 0, fraction ≥ 0)`, capped at 1.0).
- `evaluate_strict`: for each seed, call `generate_dataset(seed=seed)`, build the eval store, evaluate the baseline (`DEFAULT_WEIGHTS`) and candidate weights; collect per-query deltas; aggregate. Include cold-start subsets (workers with no train assignments). Measure latency with `time.perf_counter()` over 100 recommendations.
- `scripts/evaluate_strict.py`: parse `--seeds` (comma-separated), `--k`, `--out-dir`, and `--candidate-weights` (optional JSON path); call `evaluate_strict` with `DEFAULT_WEIGHTS` as baseline and the override (or active weights) as candidate; write JSON and a Markdown summary. Use `argparse`; return 0. If baseline and candidate are identical, the report must say so explicitly rather than presenting zero deltas as a result.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_strict_eval.py -v`
Expected: PASS.

- [ ] **Step 5: Run the CLI on one seed**

Run: `python scripts/evaluate_strict.py --seeds 42 --k 5`
Expected: exit code 0; `reports/strict_eval.json` and `reports/strict_eval.md` exist.

- [ ] **Step 6: Checkpoint**

No git commit. Save the one-seed report; do not treat it as the final result.

---

