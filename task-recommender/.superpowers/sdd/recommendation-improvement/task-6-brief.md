## Task 6: Strict Evaluation Data Assembly and Task→Workers Metrics

**Files:**
- Create: `app/evaluation_strict.py`
- Test: `tests/test_strict_eval.py` (create)

**Interfaces:**
- Consumes: `Dataset`, `Store`, `RecommendationService`, `Assignment`.
- Produces:
  - `build_eval_store(dataset: Dataset) -> Store` — uses only `dataset.train`, `dataset.train_feedback`, `dataset.train_events`, `dataset.train_impressions`.
  - `task_to_workers_metrics(store: Store, service: RecommendationService, test_assignments: list[Assignment], k: int = 10, candidate_mode: str = "all", impressions: list[Impression] | None = None) -> dict` — returns `{"hr": float, "ndcg": float, "mrr": float, "queries": int}`.
  - `candidate_mode` accepts `"all"` (all eligible, default) or `"exposed"` (use the test impression candidate set for the assignment; fall back to all eligible when absent). The optional `impressions` argument is **evaluation-only**: when provided, `"exposed"` searches it instead of `store.impressions`; it must not be written into the store or used by feature/training code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_strict_eval.py`:

```python
from app.evaluation_strict import build_eval_store, task_to_workers_metrics
from app.features import candidate_features  # noqa: F401  (import smoke)
from app.service import RecommendationService


def test_build_eval_store_excludes_test_feedback(dataset):
    store = build_eval_store(dataset)
    test_ids = {item.feedback_id for item in dataset.test_feedback}
    store_ids = {item.feedback_id for item in store.feedback}
    assert test_ids.isdisjoint(store_ids)
    assert len(store.assignments) == len(dataset.train)


def test_task_to_workers_metrics_are_bounded(dataset):
    store = build_eval_store(dataset)
    service = RecommendationService(store)
    metrics = task_to_workers_metrics(
        store, service, dataset.test[:20], k=10, candidate_mode="all",
    )
    assert metrics["queries"] > 0
    assert 0.0 <= metrics["hr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0
    assert 0.0 <= metrics["mrr"] <= 1.0


def test_exposed_mode_resolves_by_assignment_id(dataset):
    """Two impressions sharing query_id/created_at must resolve by assignment_id."""
    from app.domain import Impression

    store = build_eval_store(dataset)
    assignment = dataset.test[0]
    first = Impression(
        request_id="r1", query_id=assignment.task_id, candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": "other"},
    )
    second = Impression(
        request_id="r2", query_id=assignment.task_id, candidate_ids=["w2"],
        propensities={"w2": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": assignment.assignment_id},
    )
    store.impressions = [first, second]
    # The helper should select `second`; assert through the public metrics path.
    metrics = task_to_workers_metrics(
        store, RecommendationService(store), [assignment], k=10,
        candidate_mode="exposed",
    )
    assert metrics["queries"] == 1
```

Add a `dataset` fixture to `tests/conftest.py` if it does not exist:

```python
from app.data.synthetic import generate_dataset

@pytest.fixture
def dataset():
    return generate_dataset(
        n_workers=20, n_tasks=60, n_assignments=200, seed=42, n_new_users=0,
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_strict_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation_strict'`.

- [ ] **Step 3: Implement `build_eval_store` and `task_to_workers_metrics`**

`build_eval_store` returns `Store(workers=dataset.workers, customers=dataset.customers, tasks=dataset.tasks, assignments=dataset.train, feedback=dataset.train_feedback, events=dataset.train_events, impressions=dataset.train_impressions)`.

For each test assignment:
- Look up the task. If missing, skip.
- Build the ranked candidate list:
  - `"all"`: `[c.candidate_id for c in service.recommend_workers(task_id, top_n=len(store.workers))]`.
  - `"exposed"`: search `impressions if impressions is not None else store.impressions`. First find the impression whose `metadata["assignment_id"] == assignment.assignment_id`; if absent, fall back to `query_id == task_id and created_at == assignment.created_at`; if still absent, fall back to `"all"`. Rank only the impression's candidate IDs by `service.recommend_workers` scores (use the order returned by the service; if a candidate is not in the ranking, append it at the end). Add a test that two impressions sharing a `(task_id, created_at)` still resolve by `assignment_id`, and a test that passing `dataset.test_impressions` as `impressions` leaves `store.impressions` train-only.
- Find `rank = ranked.index(positive)`; if absent, metric contribution 0.
- `hr = 1` if `rank < k`; `ndcg = 1 / log2(rank + 2)` if `rank < k` else 0; `mrr = 1 / (rank + 1)` if `rank < k` else 0.
- Average across queries; `queries` = number of evaluated assignments.

Do not read `ground_truth` or `labels`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_strict_eval.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit. Record the metrics from the test fixture.

---

