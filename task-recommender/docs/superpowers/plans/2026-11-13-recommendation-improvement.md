# Recommendation Mechanism Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the task-recommender's accuracy and learning loop while keeping the existing seven-dimension linear ranker, by adding strict evaluation, exposure/rejection event logs, better seven-dimension features, optional semantic matching, and pairwise/listwise choice learning.

**Architecture:** Keep `RecommendationService` as the single ranking entry. Add an event log (`app/events.py`), a semantic matcher (`app/semantic.py`), a choice learner (`app/learning/choice.py`), a strict evaluator (`app/evaluation_strict.py`), and a calibrator (`app/learning/calibration.py`). Extend existing dataclasses with defaulted fields and fold new signals into the existing seven dimensions. No eighth dimension, no GBDT/neural ranker, no generative LLM.

**Tech Stack:** Python 3.13, FastAPI, numpy, pandas, scikit-learn, scipy, pytest, httpx. Optional: `sentence-transformers` (lazy, never a required dependency).

**Spec:** `docs/superpowers/specs/2026-11-13-recommendation-improvement-design.md`

---

## Codebase Orientation

Read these before starting any task:

| File | Why it matters |
|---|---|
| `app/domain.py` | Dataclasses for `Worker`, `Task`, `Assignment`, `Feedback`, `Dataset` |
| `app/data/store.py` | In-memory `Store`; `reference_time`; index helpers |
| `app/data/synthetic.py` | Deterministic synthetic dataset; generates assignments/feedback |
| `app/features.py` | Seven-dimension feature formulas and `fuse_scores` |
| `app/service.py` | `RecommendationService`: hard filters → ItemCF → features → ranking |
| `app/main.py` | FastAPI routes; `create_app`; current recommendation endpoints |
| `app/learning/exploration.py` | Current ε-greedy and IPS/SNIPS helpers |
| `app/learning/online.py` | Current online logistic weight learner |
| `app/learning/weights.py` | AHP prior, entropy weights, `project_weights` |
| `app/benchmark/features.py` | Benchmark feature builder (currently mislabels region match as `collaborative`) |
| `tests/conftest.py` | Fixtures: `small_store`, `software_task`, `client` |
| `requirements.txt` | Runtime dependencies; do not add required ones without updating it |

Run all commands from `task-recommender/`.

## Global Constraints

- Python 3.13; keep the existing dependency set. `sentence-transformers` is optional and must be imported lazily.
- Keep exactly seven feature keys: `reputation`, `skill`, `expertise`, `collaborative`, `preference`, `load`, `customer_preference`.
- Weights must sum to 1.0; `reputation ∈ [0.25, 0.40]`; `skill + expertise ≥ 0.25`; each weight ≥ 0.02; `reputation` is the largest weight.
- All new dataclass fields must have defaults; existing constructors and tests must keep working.
- Existing endpoints `/recommend/*`, `/assignments`, `/feedback`, `/weights/*` keep their request/response contracts; new fields are additive with defaults.
- No generative LLM. No GBDT/neural ranker. No eighth dimension.
- Feature/training code must never read `data/ground_truth.csv` or benchmark `labels`; only the strict evaluator and benchmark evaluator may read them.
- Training uses train-period assignments, feedback, events, and impressions only. Test-period data is evaluation-only.
- **This directory is not a git repository.** Do not run `git` commands. A “checkpoint” means: run `python -m pytest tests/ -q` and confirm all tests pass; save generated reports to `reports/`.
- Use `python -m pytest ...` (not bare `pytest`) so imports resolve from the project root.
- Preserve all existing tests. Update only assertions that the spec explicitly changes (e.g., the old `collaborative` region proxy, the old customer attribute weights).

## Review Focus

These are the failure modes most likely to bite a user and are not fully covered by the spec's happy-path descriptions. Each is pinned to a task below.

1. **Empty or tiny candidate pools (`N=0`, `N=1`, `K>N`):** propensity formulas, metrics, and reranking must not divide by zero or return a candidate count different from `min(K, N)`. Owned by Task 5 and Task 7.
2. **Cold-start workers/tasks with no history, feedback, or events:** every feature must return a sane default in `[0,1]`, and `P(accept)` must fall back to a prior. Owned by Task 10, Task 12, Task 13.
3. **Duplicate, unknown, or out-of-order events:** duplicate events must be rejected, unknown IDs must 404, and time decay must clamp negative Δt. Owned by Task 2, Task 15, Task 18.
4. **Missing optional dependency / missing new fields:** if `sentence-transformers` is unavailable or a new field is absent, features must fall back without an ImportError or NaN. Owned by Task 9 and Task 10.
5. **Test-period leakage:** injecting extreme test feedback or test events must not change training features, ItemCF, or recommendations. Owned by Task 3 and Task 6.

---

## Task 0: Baseline Check

**Files:**
- No code changes.

**Interfaces:**
- Consumes: existing project.
- Produces: recorded baseline test result.

- [ ] **Step 1: Run the existing suite**

```bash
python -m pytest tests/ -q
```

Expected: all existing tests pass. Record the count; the README says ~150.

- [ ] **Step 2: Run the current evaluation scripts once**

```bash
python scripts/evaluate.py
python scripts/evaluate_phase2.py
```

Expected: exit code 0 and files written under `reports/`. Do not edit the reports.

- [ ] **Step 3: Checkpoint**

Record the test count and the current `reports/phase1_metrics.json` / `reports/phase2_metrics.json` values in your working notes. These are the comparison baseline; do not overwrite them until Phase 3.

---

## Task 1: Domain Models, Store Extensions, and Dataset Split Helpers

**Files:**
- Modify: `app/domain.py`
- Modify: `app/data/store.py`
- Test: `tests/test_events.py` (create)

**Interfaces:**
- Consumes: existing dataclasses.
- Produces:
  - `Impression` and `RecommendationEvent` dataclasses (fields exactly as spec §5.1–5.2).
  - `Worker.expected_pay: float = 0.0`, `Worker.certifications: dict[str, float] = field(default_factory=dict)`, `Worker.communication_ratings: list[float] = field(default_factory=list)`.
  - `Task.required_skill_weights: dict[str, float] = field(default_factory=dict)`.
  - `Dataset.events` and `Dataset.impressions` defaulted lists.
  - `Dataset.split_time -> datetime`, `Dataset.train_feedback`, `Dataset.test_feedback`, `Dataset.train_events`, `Dataset.test_events`, `Dataset.train_impressions`, `Dataset.test_impressions`.
  - `Store.__init__(..., events: list[RecommendationEvent] | None = None, impressions: list[Impression] | None = None)`.
  - `Store.events_for(request_id: str) -> list[RecommendationEvent]`.
  - `Store.events_for_user(user_id: str) -> list[RecommendationEvent]`.
  - `Store.recent_impression_counts(now: datetime, days: int = 30) -> dict[str, int]` keyed by candidate ID.
  - `Store.prior_collaboration_count(customer_id: str, worker_id: str, before: datetime | None = None) -> int` counting `status == "completed"` assignments before `before` (default `reference_time`).
  - `Store.reference_time` includes `assignments`, `events`, and `impressions`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_events.py` with:

```python
from datetime import datetime, timedelta, timezone

from app.data.store import Store
from app.domain import (
    Assignment, Customer, Impression, RecommendationEvent, Task, Worker,
)

NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)


def test_impression_fields():
    impression = Impression(
        request_id="r1", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
    )
    assert impression.request_id == "r1"
    assert impression.candidate_ids == ["w1"]


def _worker(worker_id: str = "w1") -> Worker:
    return Worker(
        worker_id=worker_id,
        name=worker_id,
        skills={"python": 4},
        specialties={"software_dev": 3},
        level=3,
        capacity_hours=40,
        current_load_hours=0,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
    )


def test_new_worker_and_task_fields_have_defaults():
    worker = _worker()
    assert worker.expected_pay == 0.0
    assert worker.certifications == {}
    assert worker.communication_ratings == []
    task = Task(
        task_id="t1", customer_id="c1", title="T", category="software_dev",
        required_skills={}, required_level=1, difficulty=3, priority=3,
        estimated_hours=2, deadline=NOW, region="CN", remote_ok=True,
    )
    assert task.required_skill_weights == {}


def test_store_reference_time_includes_events_and_impressions():
    worker = _worker()
    event = RecommendationEvent(
        event_id="e1", request_id="r1", user_id="c1", role="customer",
        task_id="t1", candidate_id="w1", candidate_type="worker",
        rank=1, score=0.9, propensity=0.5, weights_version="v0000",
        action="click", created_at=NOW + timedelta(days=2),
    )
    store = Store(
        workers=[worker], customers=[], tasks=[], assignments=[], feedback=[],
        events=[event],
    )
    assert store.reference_time == event.created_at
    assert store.events_for("r1") == [event]
    assert store.events_for_user("c1") == [event]


def test_recent_impression_counts_window():
    from app.domain import Impression

    worker = _worker()
    old = Impression(
        request_id="r_old", query_id="t1", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW - timedelta(days=60),
    )
    new = Impression(
        request_id="r_new", query_id="t2", candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=NOW - timedelta(days=5),
    )
    store = Store(
        workers=[worker], customers=[], tasks=[], assignments=[], feedback=[],
        impressions=[old, new],
    )
    assert store.recent_impression_counts(NOW, days=30)["w1"] == 1


def test_prior_collaboration_counts_only_completed_before():
    worker = _worker()
    customer = Customer(customer_id="c1", name="C", region="CN")
    old = Assignment(
        assignment_id="a1", task_id="t1", worker_id="w1", customer_id="c1",
        status="completed", created_at=NOW - timedelta(days=10),
    )
    new = Assignment(
        assignment_id="a2", task_id="t2", worker_id="w1", customer_id="c1",
        status="completed", created_at=NOW + timedelta(days=10),
    )
    cancelled = Assignment(
        assignment_id="a3", task_id="t3", worker_id="w1", customer_id="c1",
        status="cancelled", created_at=NOW - timedelta(days=5),
    )
    store = Store(
        workers=[worker], customers=[customer], tasks=[],
        assignments=[old, new, cancelled], feedback=[],
    )
    assert store.prior_collaboration_count("c1", "w1", before=NOW) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_events.py -v`
Expected: collection error importing `Impression` / `RecommendationEvent` (classes not defined yet).

- [ ] **Step 3: Implement the dataclasses and Store extensions**

Add the two dataclasses to `app/domain.py` with the exact fields from spec §5.1–5.2. Add `metadata: dict = field(default_factory=dict)` to `Impression` for assignment correlation (used by synthetic generation). Add the new fields to `Worker`, `Task`, and `Dataset`. Implement the `Dataset` properties using `split_time = max(a.created_at for a in train)` with a fallback to `datetime.now(timezone.utc)` when `train` is empty. Implement the Store methods; `recent_impression_counts` counts candidate IDs from `store.impressions` whose `created_at` is within `days` of `now`. Update `reference_time` to include events/impressions.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. If a dataclass ordering error occurs, move all new fields after existing defaulted fields.

- [ ] **Step 6: Checkpoint**

No git commit (not a git repository). Record that the full suite passes.

---

## Task 2: EventService and Funnel Metrics

**Files:**
- Create: `app/events.py`
- Test: `tests/test_events.py` (extend)

**Interfaces:**
- Consumes: `Store`, `Impression`, `RecommendationEvent`.
- Produces:
  - `ACTIONS = {"click", "apply", "accept", "reject", "ignore"}`
  - `EventService.__init__(self, store: Store, persist_dir: Path | None = None, max_events: int = 1_000_000)`.
  - `EventService.record_impression(self, request_id: str, query_id: str, candidate_ids: list[str], propensities: dict[str, float], policy: str, metadata: dict | None = None) -> Impression`.
  - `EventService.record_event(self, request_id: str, candidate_id: str, action: str, user_id: str | None = None, role: str = "customer", metadata: dict | None = None) -> RecommendationEvent`.
  - `EventService.funnel_metrics(self) -> dict`.
  - JSONL persistence: `persist_dir/impressions.jsonl`, `persist_dir/events.jsonl` when `persist_dir` is set. When a file reaches `max_events` lines, rotate it to `<name>.1.jsonl`, `<name>.2.jsonl`, … and continue with a fresh active file.
  - `weights_version` is stored as `str(...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_events.py`:

```python
import pytest
from app.events import EventService


def test_event_service_records_and_counts(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store, persist_dir=tmp_path)
    service.record_impression(
        "r1", "t1", ["w1", "w2"], {"w1": 0.9, "w2": 0.1}, "test",
    )
    service.record_event("r1", "w1", "click", user_id="c1")
    service.record_event("r1", "w1", "accept", user_id="c1")
    metrics = service.funnel_metrics()
    assert metrics["impressions"] == 1
    assert metrics["candidates"] == 2
    assert metrics["clicks"] == 1
    assert metrics["accepts"] == 1
    assert metrics["click_rate"] == pytest.approx(0.5)
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "impressions.jsonl").exists()


def test_event_service_rejects_duplicates_and_unknowns(tmp_path):
    store = Store(workers=[_worker()], customers=[], tasks=[], assignments=[], feedback=[])
    service = EventService(store)
    service.record_impression("r1", "t1", ["w1"], {"w1": 1.0}, "test")
    service.record_event("r1", "w1", "click")
    with pytest.raises(ValueError):
        service.record_event("r1", "w1", "click")
    with pytest.raises(KeyError):
        service.record_event("r_missing", "w1", "click")
    with pytest.raises(KeyError):
        service.record_event("r1", "w_missing", "click")
    with pytest.raises(ValueError):
        service.record_event("r1", "w1", "invalid_action")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_events.py::test_event_service_records_and_counts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.events'`.

- [ ] **Step 3: Implement `EventService`**

`record_impression` appends to `store.impressions` and writes one JSONL line. `record_event` looks up the impression by `request_id`, validates `candidate_id` is in `impression.candidate_ids`, rejects duplicate `(request_id, candidate_id, action)` with `ValueError`, rejects unknown IDs with `KeyError`, and appends a `RecommendationEvent` with `rank = candidate_ids.index(candidate_id) + 1`, `score = 0.0` (unless provided in metadata), `propensity = impression.propensities[candidate_id]`, and `weights_version = str(metadata.get("weights_version", "v0000"))`. `funnel_metrics` returns counts plus rates:

Add `test_event_service_rotates_jsonl` with `max_events=2`: record three events, assert `events.1.jsonl` exists and the active `events.jsonl` contains the remainder. Add a focused non-click funnel test covering `apply_rate`/`accept_rate`/`reject_rate`/`ignore_rate`, and parse one persisted JSONL line to assert its fields.

```text
click_rate  = clicks  / max(1, candidates)
apply_rate  = applies / max(1, clicks)
accept_rate = accepts / max(1, applies)
reject_rate = rejects / max(1, candidates)
ignore_rate = ignores / max(1, candidates)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit. Record the focused test result.

---

## Task 3: Synthetic New Fields and Train/Test Feedback Split

**Files:**
- Modify: `app/data/synthetic.py`
- Test: `tests/test_synthetic.py` (extend)

**Interfaces:**
- Consumes: `Dataset.train_feedback` / `test_feedback` from Task 1.
- Produces: `generate_dataset(...)` populates `expected_pay`, `certifications`, `communication_ratings`, and `required_skill_weights`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthetic.py`:

```python
from app.data.synthetic import generate_dataset


def test_synthetic_new_fields_are_populated():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    assert all(worker.expected_pay > 0 for worker in dataset.workers)
    assert any(worker.certifications for worker in dataset.workers)
    assert any(worker.communication_ratings for worker in dataset.workers)
    for task in dataset.tasks:
        assert set(task.required_skill_weights) == set(task.required_skills)


def test_train_and_test_feedback_are_disjoint():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    train_ids = {item.feedback_id for item in dataset.train_feedback}
    test_ids = {item.feedback_id for item in dataset.test_feedback}
    assert train_ids.isdisjoint(test_ids)
    assert len(train_ids) + len(test_ids) == len(dataset.feedback)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_synthetic.py::test_synthetic_new_fields_are_populated -v`
Expected: FAIL because fields are still empty/default.

- [ ] **Step 3: Implement the synthetic fields**

In `generate_dataset`:
- Add a shared helper `_sample_pay_and_certifications(rng, specialties) -> tuple[float, dict[str, float]]` and use it in both the main worker loop and the new-user loop (do not duplicate the logic):
  - `expected_pay = round(median_budget_of_specialty * rng.uniform(0.7, 1.3), 2)`; use the `TASK_PROFILES[category]["budget"]` midpoint for the worker's first specialty. If no specialty, use `rng.uniform(2000, 12000)`.
  - For each `category` in `specialties`, draw `r = rng.random()` **once** and set `0.8 if r < 0.3 else 0.5 if r < 0.7 else 0.0`. This yields exactly P(0.8)=0.3, P(0.5)=0.4, P(0)=0.3. Do not use two sequential draws.
- When generating feedback, with probability 0.5 append `communication_rating = int(round(clamp(quality * 5 + rng.uniform(-0.5, 0.5), 1, 5)))` to the `Feedback` and to `worker.communication_ratings` as a `float`.
- In the post-generation reset block (where `worker.ratings`, `completed`, etc. are cleared), also clear `worker.communication_ratings = []`, then repopulate only from `train` feedback.
- Set `Task.required_skill_weights = {skill: 1.0 for skill in required_skills}`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_synthetic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 4: Synthetic Impressions and Events

**Files:**
- Modify: `app/data/synthetic.py`
- Test: `tests/test_synthetic.py` (extend)

**Interfaces:**
- Consumes: `Impression`, `RecommendationEvent`, `Dataset` split helpers.
- Produces: `generate_dataset(...)` returns non-empty `impressions` and `events`; each assignment has one impression.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthetic.py`:

```python
def test_synthetic_events_cover_assignments():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    assert len(dataset.impressions) == len(dataset.assignments)
    for impression in dataset.impressions:
        assert impression.candidate_ids
        assert abs(sum(impression.propensities.values()) - 1.0) < 1e-6
    accepts = [event for event in dataset.events if event.action == "accept"]
    assert len(accepts) == len(dataset.assignments)
    train_ids = {event.event_id for event in dataset.train_events}
    test_ids = {event.event_id for event in dataset.test_events}
    assert train_ids.isdisjoint(test_ids)
    assert len(train_ids) + len(test_ids) == len(dataset.events)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_synthetic.py::test_synthetic_events_cover_assignments -v`
Expected: FAIL because `events` / `impressions` are empty.

- [ ] **Step 3: Implement synthetic events**

Inside the assignment loop, after the chosen `worker` is determined:
- Compute the logging weights for every candidate using the existing local `weight(worker)` function; normalize to propensities.
- Create an `Impression(request_id=f"r{len(impressions)+1:06d}", query_id=task.task_id, candidate_ids=[...], propensities={...}, policy="synthetic_weighted", created_at=assignment_time, metadata={"assignment_id": assignment.assignment_id})`.
- Create one `accept` event for the chosen worker; set `metadata={"assignment_id": assignment.assignment_id}` on it and on every negative event.
- Sample at most 20 unchosen candidates uniformly; for each, create an `ignore` event, except 10% become `reject` (use `rng.random() < 0.1`).
- Use `event_id=f"e{len(events)+1:06d}"`; `rank` is the candidate's position in `candidate_ids`; `score` is the logging weight; `propensity` from the impression; `weights_version="v0000"`.
- After building all assignments, sort events by `created_at`; the `Dataset.train_events` / `test_events` properties partition by `split_time`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_synthetic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. If existing synthetic tests assert exact counts of assignments/feedback, they should still pass; do not change those counts.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 5: Exact ε-Greedy Propensities

**Files:**
- Modify: `app/learning/exploration.py`
- Test: `tests/test_propensity.py` (create)

**Interfaces:**
- Consumes: existing `ScoredCandidate`-like objects with `candidate_id`.
- Produces:
  - `epsilon_greedy_propensities(candidate_ids: list[str], k: int, epsilon: float) -> dict[str, float]`.
  - `ExplorationPolicy.__init__(self, epsilon: float = 0.10, seed: int | None = None)`.
  - `ExplorationPolicy.rerank(self, candidates: list, k: int) -> list`.
  - `ExplorationPolicy.propensity_for(self, candidate_id: str) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_propensity.py`:

```python
import pytest
from app.learning.exploration import ExplorationPolicy, epsilon_greedy_propensities


def test_exact_epsilon_greedy_propensities():
    props = epsilon_greedy_propensities(["a", "b", "c", "d", "e"], k=3, epsilon=0.1)
    assert props["a"] == 1.0
    assert props["b"] == 1.0
    assert props["c"] == pytest.approx(0.9 + 0.1 / 3)
    assert props["d"] == pytest.approx(0.1 / 3)
    assert props["e"] == pytest.approx(0.1 / 3)
    assert sum(props.values()) == pytest.approx(3.0)


def test_k_ge_n_returns_ones():
    props = epsilon_greedy_propensities(["a", "b"], k=5, epsilon=0.1)
    assert props == {"a": 1.0, "b": 1.0}


def test_forced_exploration_replaces_last_and_uses_exact_propensity():
    from app.service import ScoredCandidate

    candidates = [
        ScoredCandidate(
            candidate_id=f"c{i}", score=1.0 - i * 0.01,
            breakdown={}, reasons=[], cold_start=False,
        )
        for i in range(10)
    ]
    policy = ExplorationPolicy(epsilon=1.0, seed=42)
    result = policy.rerank(candidates, k=3)
    assert len(result) == 3
    pool_ids = {candidate.candidate_id for candidate in candidates[2:]}
    assert result[-1].candidate_id in pool_ids
    for item in result:
        assert item.propensity == pytest.approx(policy.propensity_for(item.candidate_id))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_propensity.py -v`
Expected: FAIL with `ImportError: cannot import name 'epsilon_greedy_propensities'`.

- [ ] **Step 3: Implement the exact formula**

Implement:

```text
N = len(candidate_ids), K = min(k, N)
if N == 0: return {}
if N <= K: return {cid: 1.0 for cid in candidate_ids}
for i, cid in enumerate(candidate_ids):
    if i < K - 1: p = 1.0
    elif i == K - 1: p = (1 - epsilon) + epsilon / (N - K + 1)
    else: p = epsilon / (N - K + 1)
    clamp p to [1e-6, 1.0]
```

`ExplorationPolicy.rerank` builds candidates as objects with `candidate_id`; use `epsilon_greedy_propensities` on the original ranked IDs whenever the RNG draw is below `epsilon`, sample uniformly from `candidates[K-1:]` — the K-th item plus the tail, size N-K+1. If the sampled item is the K-th, keep the Top-K unchanged; otherwise replace the last item with the sampled tail item. `seed=None` uses `random.Random()`; `seed=int` is for tests. Store the exact propensities in `_propensities` and return `replace(item, propensity=p)`.

Add an empirical test: run `rerank` 100,000 times with N=5, K=3, ε=0.1 and count inclusion; each candidate's empirical inclusion frequency must match `epsilon_greedy_propensities` within 0.01. This is the test that catches a pool/formula mismatch.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_propensity.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. Existing tests that only check `len(result)` and `propensity` in `(0,1]` should still pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

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

## Task 8: `project_weights_with_report`

**Files:**
- Modify: `app/learning/weights.py`
- Test: `tests/test_weight_binding.py` (create)

**Interfaces:**
- Consumes: existing `project_weights`.
- Produces:
  - `WeightBindingReport` dataclass with `reputation_hit_low: int`, `reputation_hit_high: int`, `min_hits: dict[str, int]`, `iterations: int`.
  - `project_weights_with_report(weights: dict[str, float]) -> tuple[dict[str, float], WeightBindingReport]`.
  - `project_weights(weights) -> dict[str, float]` delegates and returns only the weights.

- [ ] **Step 1: Write the failing test**

Create `tests/test_weight_binding.py`:

```python
from app.config import DEFAULT_WEIGHTS
from app.learning.weights import project_weights_with_report


def test_projection_reports_reputation_high_bound():
    weights = dict(DEFAULT_WEIGHTS)
    weights["reputation"] = 0.9
    projected, report = project_weights_with_report(weights)
    assert projected["reputation"] <= 0.40 + 1e-9
    assert report.reputation_hit_high == 1
    assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_projection_reports_min_weight_hits():
    weights = dict(DEFAULT_WEIGHTS)
    weights["customer_preference"] = 0.0
    projected, report = project_weights_with_report(weights)
    assert projected["customer_preference"] >= 0.02 - 1e-9
    assert report.min_hits.get("customer_preference", 0) >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_weight_binding.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the report**

Refactor `project_weights` into `project_weights_with_report`; keep the existing projection logic and add counters when:
- `reputation` is clamped to `REPUTATION_MIN` / `REPUTATION_MAX`;
- any dimension is allocated at `MIN_WEIGHT`.
Increment `iterations` once per call. `project_weights` returns `project_weights_with_report(weights)[0]`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_weight_binding.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 9: SemanticMatcher

**Files:**
- Create: `app/semantic.py`
- Test: `tests/test_semantic.py` (create)

**Interfaces:**
- Consumes: scikit-learn `TfidfVectorizer`, `TruncatedSVD`.
- Produces:
  - `SemanticMatcher(provider: str = "tfidf_svd", model: str | None = None, cache_dir: Path | None = None, random_state: int = 42)`.
  - `SemanticMatcher.fit(worker_texts: list[str], task_texts: list[str]) -> "SemanticMatcher"`.
  - `SemanticMatcher.similarity(task_text: str, worker_text: str) -> float`.
  - `SemanticMatcher.similarity_batch(task_text: str, worker_texts: list[str]) -> list[float]`.
  - `SemanticMatcher.provider -> str`; `SemanticMatcher.fit_count -> int`.
  - `build_matcher(provider: str | None = None) -> SemanticMatcher`.
  - `build_worker_text(worker: Worker) -> str` — concatenate resume-surface fields (headline, skills, projects, certifications); never internal scores. Cache by `worker_id` so repeated candidate scoring does not rebuild the resume.
  - `build_task_text(task: Task) -> str` — `title + description + requirements + category`, joined with `"。"`. Cache by `task_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_semantic.py`:

```python
import pytest
from app.semantic import SemanticMatcher, build_matcher


def test_tfidf_svd_similarity_is_bounded_and_deterministic():
    matcher = SemanticMatcher(provider="tfidf_svd").fit(
        ["Python 后端开发，支付系统", "品牌 VI 与包装设计", "数据分析与报表"],
        ["需要 Python 后端工程师开发支付接口", "需要品牌设计师做 VI 包装", "需要数据分析师"],
    )
    sim = matcher.similarity(
        "需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统",
    )
    assert 0.0 <= sim <= 1.0
    assert sim == pytest.approx(
        matcher.similarity("需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统")
    )
    assert matcher.fit_count == 1


def test_disabled_provider_returns_half():
    matcher = SemanticMatcher(provider="disabled")
    assert matcher.similarity("a", "b") == 0.5


def test_sentence_transformer_falls_back_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    matcher = build_matcher("sentence_transformer")
    assert matcher.provider == "tfidf_svd"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_semantic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.semantic'`.

- [ ] **Step 3: Implement the matcher**

- `tfidf_svd`: fit `TfidfVectorizer(analyzer="char", ngram_range=(2,4), min_df=2, sublinear_tf=True)` on the union of worker/task texts, then `TruncatedSVD(n_components=min(128, max(2, n_docs - 1)), random_state=random_state)`. Transform texts, L2-normalize, cosine = dot product; clamp to `[0,1]`.
- `disabled`: `similarity` returns 0.5.
- `sentence_transformer`: lazy `from sentence_transformers import SentenceTransformer`; on ImportError, fall back to `tfidf_svd` and set `provider = "tfidf_svd"`. Encode with `normalize_embeddings=True`; cosine mapped to `[0,1]`.
- Cache: `_cache: dict[tuple[str,str], float]`; keyed by text pair; `fit_count` increments only in `fit`.
- `build_matcher(provider)`: read config defaults if `None`; return `SemanticMatcher(provider=provider or "tfidf_svd")`.
- `build_worker_text`: call `app.resume.build_resume(worker)` and concatenate the visible surface fields (`headline`, `skills`, `projects`, `certifications`, `city`); do not include `platform_data`. Cache by `worker_id`.
- `build_task_text`: join `title`, `description`, `requirements`, and `category` with `"。".join(...)`; cache by `task_id`.
- Persistent sha256 disk embedding cache (design §9.3) is deferred; the in-memory pair cache is sufficient for the 100-worker/1,000-task scale. Record this as a performance follow-up.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_semantic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 10: `skill` and `expertise` Upgrades

**Files:**
- Modify: `app/features.py`
- Test: `tests/test_features_v2.py` (create)

**Interfaces:**
- Consumes: `Worker.certifications`, `Worker.category_ratings`, `Task.required_skill_weights`.
- Produces:
  - `category_history_score(worker: Worker) -> float`.
  - `skill_score(worker: Worker, task: Task) -> float` (updated).
  - `expertise_score(worker: Worker, task: Task, semantic_similarity: float | None = None) -> float` (updated).
  - `candidate_features(..., semantic_similarity: float = 0.5) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_features_v2.py`; copy the `make_worker` / `make_task` helpers from `tests/test_features.py` and add:

```python
import pytest
from app.features import category_history_score, expertise_score, skill_score


def test_skill_uses_required_skill_weights():
    task = make_task(
        required_skills={"python": 3, "writing": 3},
        required_skill_weights={"python": 3.0, "writing": 1.0},
    )
    worker = make_worker(skills={"python": 3, "writing": 1})
    expected = (3.0 * 1.0 + 1.0 * (1 / 3)) / 4.0
    assert skill_score(worker, task) == pytest.approx(expected)


def test_no_required_skills_does_not_return_one():
    worker = make_worker()
    task = make_task(required_skills={})
    expected = 0.5 * expertise_score(worker, task) + 0.5 * category_history_score(worker)
    assert skill_score(worker, task) == pytest.approx(expected)
    assert skill_score(worker, task) != 1.0


def test_expertise_uses_certification_and_semantic():
    worker = make_worker(certifications={"software_dev": 1.0}, ratings=[], completed=0)
    task = make_task()
    value = expertise_score(worker, task, semantic_similarity=1.0)
    expected = 0.35 * 0.6 + 0.15 * 1.0 + 0.25 * (4.2 / 5) + 0.25 * 1.0
    assert value == pytest.approx(expected, abs=1e-6)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_features_v2.py -v`
Expected: FAIL because `category_history_score` is missing / formulas are old.

- [ ] **Step 3: Implement the formulas**

Implement spec §8.2–8.3 exactly:
- `category_history_score`: `global_rating = compute_reputation(worker).rating` is already normalized to **0–1** in this codebase; `category_values = worker.category_ratings.get(category, [])`; `n`, `mean`; `(n*mean/5 + 10*global_rating) / (n+10)`; if `n == 0`, `global_rating`. Do not divide `global_rating` by 5 again.
- `skill_score`: weighted average using `task.required_skill_weights.get(skill, 1.0)`; no required skills → `0.5 * expertise_score(worker, task) + 0.5 * category_history_score(worker)`.
- `expertise_score`: `0.35*specialty + 0.15*certification + 0.25*category_history + 0.25*semantic`, with `specialty = worker.specialties.get(task.category, 0)/5`, `certification = clamp(worker.certifications.get(task.category, 0.0))`, `semantic = semantic_similarity if provided else 0.5`. Clamp to `[0,1]`.
- `candidate_features` passes `semantic_similarity` through.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_features_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. The existing `test_features.py` should still pass because it uses required skills and expects `skill_score` 1.0/0.0.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 11: `preference` Pay/Time Fit

**Files:**
- Modify: `app/features.py`
- Test: `tests/test_features_v2.py` (extend)

**Interfaces:**
- Consumes: `Worker.expected_pay`, `Task.budget`, `Task.deadline`, `Task.estimated_hours`, `Worker.current_load_hours`.
- Produces:
  - `pay_fit_score(worker: Worker, task: Task) -> float`.
  - `time_fit_score(worker: Worker, task: Task, now: datetime | None = None) -> float`.
  - `preference_score(worker: Worker, task: Task, profile: WorkerPreferenceProfile | None = None, p_accept: float | None = None, now: datetime | None = None) -> float`.
  - `candidate_features(..., now=None)` must forward its `now` into `preference_score` so the time term uses the data-relative reference, not the wall clock.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features_v2.py`:

```python
from datetime import datetime, timedelta, timezone
from app.features import pay_fit_score, preference_score, time_fit_score


def test_pay_fit_exact_match_and_missing():
    worker = make_worker(expected_pay=1000)
    assert pay_fit_score(worker, make_task(budget=1000)) == pytest.approx(1.0)
    assert pay_fit_score(worker, make_task(budget=2000)) == pytest.approx(1 - 1000 / 2000)
    assert pay_fit_score(make_worker(expected_pay=0), make_task(budget=1000)) == pytest.approx(0.5)


def test_time_fit_exact_value():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(current_load_hours=0)
    task = make_task(estimated_hours=5, deadline=now + timedelta(hours=10))
    assert time_fit_score(worker, task, now=now) == pytest.approx(0.5)


def test_preference_weighted_formula():
    worker = make_worker()
    task = make_task()
    value = preference_score(worker, task, p_accept=0.8)
    declared = 0.6 * 0.8 + 0.4 * 1.0  # category 0.8, difficulty midpoint 3 = task difficulty 3
    pay = pay_fit_score(worker, task)
    time_fit = time_fit_score(worker, task)
    expected = 0.4 * 0.8 + 0.3 * declared + 0.15 * pay + 0.15 * time_fit
    assert value == pytest.approx(expected)
```

Adjust the `declared` expectation to the actual `make_task` difficulty (3) and `make_worker` preferred difficulty `(2, 4)` midpoint 3, so `difficulty_fit = 1.0`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_features_v2.py::test_pay_fit_exact_match_and_missing -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

- `pay_fit_score`: `1 - |task.budget - worker.expected_pay| / max(task.budget, worker.expected_pay, 1)`; if `expected_pay == 0`, 0.5; clamp.
- `time_fit_score`: `now = now or datetime.now(timezone.utc)` **exactly** (no minute truncation); `hours_until = max(0, (deadline - now).total_seconds()/3600)`; `available = max(0, hours_until - worker.current_load_hours)`; `1 - clamp(task.estimated_hours / max(available, 1), 0, 1)`.
- `preference_score`: keep the existing profile/declared logic for `declared`; use `p_accept if provided else declared`; pass `now` to `time_fit_score`; return `0.4*p_accept + 0.3*declared + 0.15*pay_fit + 0.15*time_fit`, clamped. `candidate_features` forwards its `now` here.
- Update `tests/test_preference_profiles.py`'s wall-clock equality assertion to `pytest.approx` (or pass a fixed `now`); this file is in scope for this task because the spec changes `preference_score`'s inputs.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_features_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. Existing preference tests should still pass; if they assert the old formula, update only those assertions to the new formula.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 12: AcceptanceModel (`P(accept)`)

**Files:**
- Create: `app/learning/acceptance.py`
- Modify: `app/features.py` (accept `p_accept` in `candidate_features`; already added in Task 11)
- Test: `tests/test_acceptance_model.py` (create)

**Interfaces:**
- Consumes: event features.
- Produces:
  - `AcceptanceModel(prior: float = 0.5, l2: float = 0.1)`.
  - `AcceptanceModel.fit(samples: list[tuple[dict[str, float], int]], sample_weight: list[float] | None = None) -> "AcceptanceModel"`.
  - `AcceptanceModel.predict(features: dict[str, float]) -> float`.
  - `AcceptanceModel.is_fitted -> bool`.
  - `accept_features(worker, task, skill, pay_fit, region_match, historical_accept_rate) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_acceptance_model.py`:

```python
import pytest
from app.learning.acceptance import AcceptanceModel


def test_acceptance_model_learns_direction():
    positive = {"skill_match": 1.0, "pay_fit": 0.9, "category_match": 1.0, "load_ratio": 0.1, "region_match": 1.0, "historical_accept_rate": 0.9}
    negative = {"skill_match": 0.1, "pay_fit": 0.1, "category_match": 0.0, "load_ratio": 0.9, "region_match": 0.3, "historical_accept_rate": 0.1}
    samples = [(positive, 1)] * 30 + [(negative, 0)] * 30
    model = AcceptanceModel().fit(samples)
    assert model.is_fitted
    assert model.predict(positive) > model.predict(negative)
    assert 0.0 <= model.predict(positive) <= 1.0


def test_cold_start_returns_prior():
    model = AcceptanceModel(prior=0.42)
    assert model.predict({"skill_match": 1.0}) == pytest.approx(0.42)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_acceptance_model.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Use `sklearn.linear_model.LogisticRegression(fit_intercept=True, C=1/l2, max_iter=1000)`. Fit on the ordered feature keys; use a fixed order `["category_match","skill_match","pay_fit","load_ratio","region_match","historical_accept_rate"]`; missing keys default to 0.0. If fewer than 20 samples, remain unfitted and return `prior`. `accept_features` returns the six keys with:
- `category_match = worker.preferred_categories.get(task.category, 0.0)`
- `skill_match = skill`
- `pay_fit = pay_fit`
- `load_ratio = clamp((worker.current_load_hours + task.estimated_hours) / max(worker.capacity_hours, 1), 0, 1)`
- `region_match = 1.0` same region; `0.8` both remote; else `0.3`
- `historical_accept_rate = (accepted + 1) / (accepted + rejected + 2)`

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_acceptance_model.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 13: `load` and `customer_preference` Upgrades

**Files:**
- Modify: `app/features.py`
- Modify: `app/preference/customer.py`
- Modify: `app/service.py` (wire the new feature inputs)
- Test: `tests/test_features_v2.py`, `tests/test_preference_profiles.py` (update), `tests/test_recommend.py` (extend)

**Interfaces:**
- Produces:
  - `load_score(worker: Worker, task: Task, now: datetime | None = None, recent_impressions: int = 0) -> float`.
  - `customer_preference_score(customer, worker, task, reputation, expertise, profile=None, *, pay_fit=0.5, deadline_feasibility=0.5, collaboration=0.0, communication=0.5, now: datetime | None = None) -> float`. The no-profile fallback must call `load_score(worker, task, now=now)` so the load term uses the data-relative reference.
  - Final `candidate_features` signature:
    ```python
    def candidate_features(
        worker, task, customer, cf_score=0.0, now=None,
        worker_profile=None, customer_profile=None,
        semantic_similarity=0.5, p_accept=None, recent_impressions=0,
    ) -> dict[str, float]
    ```
  - `RecommendationService.__init__(..., semantic_matcher: SemanticMatcher | None = None, acceptance_model: AcceptanceModel | None = None)`.
  - `DEFAULT_ATTRIBUTE_WEIGHTS` extended with `collaboration: 0.10`, `deadline_fit: 0.05`, and adjusted existing values to sum to 1.0.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features_v2.py`:

```python
from app.features import load_score
from app.preference.customer import DEFAULT_ATTRIBUTE_WEIGHTS


def test_load_formula_with_exposure():
    import math
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(capacity_hours=40, current_load_hours=10)
    task = make_task(estimated_hours=10, deadline=now + timedelta(hours=20))
    value = load_score(worker, task, now=now, recent_impressions=100)
    capacity_score = (40 - 10 - 10) / 40
    deadline_feasibility = time_fit_score(worker, task, now=now)
    exposure_fairness = math.exp(-100 / 20)
    expected = 0.6 * capacity_score + 0.25 * deadline_feasibility + 0.15 * exposure_fairness
    assert value == pytest.approx(expected, abs=1e-9)


def test_customer_attribute_weights_sum_to_one_and_include_new_keys():
    assert set(DEFAULT_ATTRIBUTE_WEIGHTS) == {
        "reputation", "expertise", "speed", "communication",
        "price", "collaboration", "deadline_fit",
    }
    assert sum(DEFAULT_ATTRIBUTE_WEIGHTS.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_features_v2.py::test_customer_attribute_weights_sum_to_one_and_include_new_keys -v`
Expected: FAIL because the new keys are absent.

- [ ] **Step 3: Implement**

- `load_score`: `capacity_score` as before; `deadline_feasibility = time_fit_score(...)`; `exposure_fairness = exp(-recent_impressions / 20)`; return `0.6*capacity + 0.25*deadline + 0.15*exposure`, clamped.
- `DEFAULT_ATTRIBUTE_WEIGHTS`: exactly `{"reputation":0.30, "expertise":0.20, "speed":0.15, "communication":0.10, "price":0.10, "collaboration":0.10, "deadline_fit":0.05}`.
- `customer_preference_score`: use the profile weights when `confidence >= 0.2`; for missing attributes, fill from `DEFAULT_ATTRIBUTE_WEIGHTS`; compute values: reputation, expertise, speed (`on_time/completed` or 0.5), communication, price=pay_fit, collaboration, deadline_fit=deadline_feasibility; normalize by the sum of weights. If no profile, use the fallback `0.4*reputation + 0.3*expertise + 0.15*load + 0.15*pay_fit`.
- `candidate_features`: pass `semantic_similarity`, `p_accept`, and `recent_impressions` into `expertise_score`, `preference_score`, and `load_score`; compute `pay_fit` and `communication` if not supplied; forward `now` into `preference_score` and `customer_preference_score` so the fallback load term is data-relative.
- `RecommendationService`: in both `recommend_workers_for_task` and `recommend_tasks`, before scoring each candidate:
  - `recent = self.store.recent_impression_counts(self.reference_time)`;
  - `communication = mean(worker.communication_ratings)/5 if worker.communication_ratings else 0.5`;
  - `collaboration = self.store.prior_collaboration_count(customer.customer_id, worker.worker_id)`;
  - `pay_fit = pay_fit_score(worker, task)`;
  - `semantic = self.semantic_matcher.similarity(build_task_text(task), build_worker_text(worker)) if self.semantic_matcher else 0.5`;
  - `p_accept = self.acceptance_model.predict(accept_features(...)) if self.acceptance_model and self.acceptance_model.is_fitted else None`. Compute the two passthrough inputs: `region_match = 1.0` same region, `0.8` both remote, else `0.3`; `historical_accept_rate = (accepted + 1) / (accepted + rejected + 2)` from the worker's accept/reject events, or `0.5` when no events exist;
  - pass all values to `candidate_features`.
- `create_app`: build one `SemanticMatcher` from all worker/task texts and one global `AcceptanceModel` from `store.events`; pass both to `RecommendationService`. If the matcher cannot fit (too few texts), pass `None`.
- Update `tests/test_preference_profiles.py` expected `DEFAULT_ATTRIBUTE_WEIGHTS` to the new dict.
- Add to `tests/test_recommend.py`:
  ```python
  def test_service_wires_new_feature_inputs(small_store):
      service = RecommendationService(small_store)
      candidates = service.recommend_workers("t1", top_n=3)
      assert candidates
      assert set(candidates[0].breakdown) == {
          "reputation", "skill", "expertise", "collaborative",
          "preference", "load", "customer_preference",
      }
  ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_features_v2.py tests/test_preference_profiles.py tests/test_recommend.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 14: ItemCF Normalization and Benchmark `collaborative` Fix

**Files:**
- Modify: `app/models/itemcf.py`
- Modify: `app/benchmark/features.py`
- Test: `tests/test_itemcf.py`, `tests/test_benchmark.py` (update)

**Interfaces:**
- Produces:
  - `ItemCF.normalize(raw) -> dict` divides by the maximum positive score; all-zero input returns zeros.
  - `BenchmarkFeatureBuilder.__init__(workers, tasks, customers, itemcf: ItemCF | None = None)`.
  - `BenchmarkFeatureBuilder.features(...)["collaborative"]` uses the normalized ItemCF score, not region/remote matching.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_itemcf.py`:

```python
from app.models.itemcf import ItemCF


def test_normalize_divides_by_max():
    cf = ItemCF([])
    result = cf.normalize({("w1", "t1"): 0.2, ("w2", "t2"): 0.4})
    assert result[("w1", "t1")] == 0.5
    assert result[("w2", "t2")] == 1.0


def test_normalize_all_zero_returns_zero():
    cf = ItemCF([])
    result = cf.normalize({("w1", "t1"): 0.0, ("w2", "t2"): 0.0})
    assert result == {("w1", "t1"): 0.0, ("w2", "t2"): 0.0}
```

Append to `tests/test_benchmark.py`:

```python
def test_benchmark_collaborative_uses_itemcf_not_region():
    # Build a tiny builder with one worker who completed a similar task.
    from app.benchmark.features import BenchmarkFeatureBuilder
    from app.models.itemcf import ItemCF

    workers = [{"worker_id": "w1", "resume_text": "Python 后端", "skills": {"python": 4},
                "capacity_hours": 40, "current_load_hours": 0, "region": "CN",
                "remote_ok": True, "rating": 4.5, "on_time_rate": 0.9,
                "preferred_categories": {"software_dev": 0.8}}]
    tasks = [
        {"task_id": "t1", "task_text": "Python 后端开发", "region": "CN", "remote_ok": True,
         "customer_id": "c1", "required_skills": {"python": 4}},
        {"task_id": "t2", "task_text": "Python 后端开发", "region": "US", "remote_ok": False,
         "customer_id": "c1", "required_skills": {"python": 4}},
    ]
    customers = [{"customer_id": "c1", "preferred_categories": {"software_dev": 0.8}}]
    cf = ItemCF([("w1", "t1", 1.0)])
    builder = BenchmarkFeatureBuilder(workers, tasks, customers, itemcf=cf)
    assert builder.features("t1", "w1")["collaborative"] > 0.0
    assert builder.features("t2", "w1")["collaborative"] >= 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_itemcf.py::test_normalize_divides_by_max -v`
Expected: FAIL because the current normalization is min-max.

- [ ] **Step 3: Implement**

- `ItemCF.normalize`: `maximum = max(raw.values())`; if `maximum <= 0`, return zeros; else `max(0, value) / maximum`.
- `BenchmarkFeatureBuilder`: accept `itemcf`; in `features`, set `collaborative = itemcf.normalize({(worker_id, task_id): itemcf.score(worker_id, task_id)})[...]` if `itemcf` is not None, else 0.0. Remove the region/remote assignment to `collaborative`.
- Update existing benchmark tests that assert the old region behavior; keep the `preference`/`customer_preference` fields unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_itemcf.py tests/test_benchmark.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 15: Pairwise Choice Learner and Pair Builder

**Files:**
- Create: `app/learning/choice.py`
- Test: `tests/test_pairwise_learning.py` (create)

**Interfaces:**
- Consumes: `RecommendationEvent`, `Impression`, seven-dim feature dicts, `project_weights`.
- Produces:
  - `ChoicePair(chosen: dict[str, float], rejected: dict[str, float], weight: float = 1.0)`.
  - `PairwiseChoiceLearner(prior: dict[str, float], l2: float = 0.1)`.
  - `PairwiseChoiceLearner.fit(pairs: list[ChoicePair]) -> dict[str, float]`.
  - `PairwiseChoiceLearner.update_online(chosen, rejected, learning_rate: float = 0.05) -> dict[str, float]`.
  - `build_pairs(events, feature_lookup, time_decay_tau_days: float = 30.0) -> list[ChoicePair]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pairwise_learning.py`:

```python
import pytest
from app.config import DEFAULT_WEIGHTS
from app.learning.choice import ChoicePair, PairwiseChoiceLearner, build_pairs


def _features(**overrides):
    base = {key: 0.5 for key in DEFAULT_WEIGHTS}
    base.update(overrides)
    return base


def test_pairwise_learner_increases_chosen_dimension():
    prior = dict(DEFAULT_WEIGHTS)
    pairs = [
        ChoicePair(chosen=_features(skill=1.0), rejected=_features(skill=0.0), weight=1.0)
        for _ in range(50)
    ]
    weights = PairwiseChoiceLearner(prior).fit(pairs)
    assert weights["skill"] >= prior["skill"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_propensity_clipping():
    learner = PairwiseChoiceLearner(dict(DEFAULT_WEIGHTS))
    pair = ChoicePair(chosen=_features(skill=1.0), rejected=_features(skill=0.0), weight=20.0)
    weights = learner.fit([pair])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pairwise_learning.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

- `PairwiseChoiceLearner.fit`: build `X = chosen - rejected` in a fixed key order (use `list(prior.keys())`); `y=1`; `sample_weight = [clamp(pair.weight, 0.1, 10)]`; fit `LogisticRegression(fit_intercept=False, C=1/l2, max_iter=1000)`; take `coef_[0]`; `project_weights`; if no pairs, return `prior`.
- `update_online`: reuse the existing `OnlineWeightLearner.update_pair` logic or implement the same gradient; `project_weights`.
- `build_pairs`: group events by `request_id`; positives = actions in `{"click","apply","accept"}`, negatives = `{"reject","ignore"}`; for each positive-negative combination, create a `ChoicePair` with `weight = exp(-Δt/30) * clamp(1/propensity, 0.1, 10)`, where `Δt` is the absolute seconds between event times (clamp negative to 0); use `feature_lookup(event)` to get the seven-dim vector.
- `feature_lookup` is `Callable[[RecommendationEvent], dict[str, float]]`; the caller supplies it (Task 19).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pairwise_learning.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 16: Listwise Choice Learner

**Files:**
- Modify: `app/learning/choice.py`
- Test: `tests/test_pairwise_learning.py` (extend)

**Interfaces:**
- Produces:
  - `ListwiseChoiceLearner(prior: dict[str, float], l2: float = 0.1, learning_rate: float = 0.05)`.
  - `ListwiseChoiceLearner.learn(candidate_features: list[dict[str, float]], chosen_index: int, sample_weight: float = 1.0) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pairwise_learning.py`:

```python
from app.learning.choice import ListwiseChoiceLearner


def test_listwise_learner_prefers_chosen_candidate():
    prior = dict(DEFAULT_WEIGHTS)
    learner = ListwiseChoiceLearner(prior, learning_rate=0.5)
    candidates = [
        _features(skill=1.0, reputation=1.0),
        _features(skill=0.1, reputation=0.1),
        _features(skill=0.2, reputation=0.2),
    ]
    weights = prior
    for _ in range(20):
        weights = learner.learn(candidates, chosen_index=0, sample_weight=1.0)
    score = lambda f: sum(weights[k] * f[k] for k in weights)
    assert score(candidates[0]) > score(candidates[1])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pairwise_learning.py::test_listwise_learner_prefers_chosen_candidate -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Use the softmax gradient from `app/benchmark/recommender.py::BenchmarkRecommender.learn`: `p = softmax(scores)`, `gradient[key] = Σ (p_i - y_i) * x_i[key] * sample_weight`, then `weights -= learning_rate * gradient` (gradient descent; the reference uses a minus sign), then `project_weights`. Include L2 toward the prior: subtract `l2 * (weights[key] - prior[key])`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pairwise_learning.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 17: Platt Calibration

**Files:**
- Create: `app/learning/calibration.py`
- Test: `tests/test_calibration.py` (create)

**Interfaces:**
- Produces:
  - `PlattCalibrator.fit(scores: list[float], labels: list[int]) -> "PlattCalibrator"`.
  - `PlattCalibrator.predict(score: float) -> float`.
  - `PlattCalibrator.brier(scores: list[float], labels: list[int]) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_calibration.py`:

```python
import pytest
from app.learning.calibration import PlattCalibrator


def test_calibration_is_monotonic_and_bounded():
    scores = [0.1, 0.2, 0.8, 0.9] * 10
    labels = [0, 0, 1, 1] * 10
    calibrator = PlattCalibrator().fit(scores, labels)
    assert 0.0 <= calibrator.predict(0.1) <= 1.0
    assert calibrator.predict(0.9) > calibrator.predict(0.1)


def test_brier_is_lower_than_raw():
    scores = [0.4, 0.6] * 20
    labels = [0, 1] * 20
    calibrator = PlattCalibrator().fit(scores, labels)
    raw = sum((s - y) ** 2 for s, y in zip(scores, labels)) / len(scores)
    assert calibrator.brier(scores, labels) <= raw + 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_calibration.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Fit `P = sigmoid(a*score + b)` using `sklearn.linear_model.LogisticRegression(fit_intercept=True, C=5.0, max_iter=1000)` with a single feature `[[score]]`; store `a = coef_[0][0]`, `b = intercept_[0]`. **Do not use `penalty=None`**: unregularized MLE at the 10-sample floor can invert or saturate the slope. `C=5.0` bounds the slope and still passes the mandated Brier check. `predict` clamps to `[0,1]`. `brier` returns `mean((predict(score) - label)^2)`. If fewer than 10 samples, use `a=1,b=0` (identity). Add a held-out noisy test: fit on 80%, evaluate Brier on 20%, assert `brier <= raw` and no probability is pinned at exactly 0/1; add an identity-fallback test for `<10` samples. Document that calibration at n≈10 is uncertain.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_calibration.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 18: `/events` API, `request_id`, and Auto-Accept

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Modify: `app/events.py` (event `task_id` precedence)
- Modify: `tests/conftest.py`
- Modify: `tests/test_phase2_api.py` (rollback test exposure-state reset)
- Test: `tests/test_api_events.py` (create)

**Interfaces:**
- Consumes: `EventService`, `ExplorationPolicy`.
- Produces:
  - Pydantic `EventItem` (`request_id`, `candidate_id`, `candidate_type` default `"worker"`, `action`, `task_id`, `user_id`, `role`, `metadata`).
  - `EventsRequest(events: list[EventItem])`.
  - `EventsResponse(accepted: int, rejected: list[dict])`.
  - `RecommendResponse.request_id: str = ""`.
  - `RecommendationContext.request_id: str = ""`.
  - `create_app(..., events_dir: Path | None = None, exploration_seed: int | None = None)` sets `app.state.events = EventService(store, persist_dir=events_dir or Path(...)/"data"/"events")` and `app.state.exploration = ExplorationPolicy(epsilon=0.10, seed=exploration_seed)`.
  - Update `tests/conftest.py` `client` fixture to pass `events_dir=tmp_path / "events"` and `exploration_seed=42` so tests do not write into the repository data directory and remain deterministic.
  - `/recommend/workers` and `/recommend/tasks` create a `request_id`, record an impression, and return it.
  - **Ruling from pre-flight scan:** replace the per-request `ExplorationPolicy(epsilon=0.10, seed=42)` constructions in both routes with `app.state.exploration.rerank(...)`. Production uses `exploration_seed=None` (system entropy); tests/demos inject a seed. Without this, the Task 5 propensity fix never takes effect.
  - `POST /events`, `GET /events/metrics`.
  - `/assignments` auto-records `accept` when `recommendation_context.request_id` is non-empty.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_events.py`:

```python
def test_recommend_returns_request_id_and_events_flow(client):
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    candidate = body["candidates"][0]["candidate_id"]
    event = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": candidate,
            "action": "click",
            "task_id": "t1",
            "user_id": "c1",
            "role": "customer",
        }]},
    )
    assert event.status_code == 200
    metrics = client.get("/events/metrics").json()
    assert metrics["clicks"] >= 1


def test_events_reject_duplicates_and_invalid_actions(client):
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 1})
    body = response.json()
    candidate = body["candidates"][0]["candidate_id"]
    payload = {"events": [{
        "request_id": body["request_id"], "candidate_id": candidate,
        "action": "click", "task_id": "t1",
    }]}
    assert client.post("/events", json=payload).status_code == 200
    assert client.post("/events", json=payload).status_code == 409
    bad = {"events": [{
        "request_id": body["request_id"], "candidate_id": candidate,
        "action": "nope", "task_id": "t1",
    }]}
    assert client.post("/events", json=bad).status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_api_events.py -v`
Expected: FAIL because `request_id` is absent / `/events` is 404.

- [ ] **Step 3: Implement**

- Add the Pydantic models and the `request_id` field to `RecommendResponse` / `RecommendationContext`.
- Add `events_dir: Path | None = None` and `exploration_seed: int | None = None` to `create_app`; create `EventService(require_store(), persist_dir=events_dir or Path(__file__).resolve().parent.parent / "data" / "events")`; create `app.state.exploration = ExplorationPolicy(epsilon=0.10, seed=exploration_seed)`; store both on `app.state`.
- Update `tests/conftest.py` `client` fixture to `TestClient(create_app(small_store, weights_dir=tmp_path, events_dir=tmp_path / "events", exploration_seed=42))`.
- In the recommendation routes, replace the per-request `ExplorationPolicy(epsilon=0.10, seed=42)` with `app.state.exploration.rerank(...)`; generate `request_id = uuid.uuid4().hex`; after `rerank`, call `events.record_impression(request_id, query_id, [c.candidate_id for c in candidates], {c.candidate_id: c.propensity for c in candidates}, "epsilon_greedy_topk")`; pass `request_id` to the response.
- `POST /events`: validate actions (Pydantic `Literal` or a manual check returning 422); call `record_event` with `metadata={"candidate_type": item.candidate_type, "task_id": item.task_id, "weights_version": ...}`; map `KeyError`→404, `ValueError`→409; return `EventsResponse`. The `/recommend/tasks` flow sends `candidate_type="task"` and `task_id=candidate_id`; `/recommend/workers` sends `"worker"` and the impression query_id is the task.
- **Server-side event labeling:** `EventService.record_event` must fall back to the impression's `metadata` for `candidate_type` and `task_id` when the event omits them. For `candidate_type="task"`, the event `task_id` is the candidate task. Add a test where the client omits both fields on a `/recommend/tasks` request and the stored event is still labeled correctly.
- **Skip empty impressions:** do not record an `Impression` when the recommendation returns zero candidates; otherwise `funnel_metrics()["impressions"]` is inflated.
- **Event `task_id` must be correct for both directions.** `EventService.record_event` should use `metadata["task_id"]` when provided, else `impression.query_id`. For worker→tasks, the event's `task_id` is the candidate task, not the worker query id. Add a test asserting this.
- **Use the shared exploration policy everywhere.** Pass `app.state.exploration` into `_node_candidates` (chain node recommendation); do not construct a new fixed-seed policy there. The two main routes and chain-node recommendation must all use the shared policy.
- **Update the pre-existing rollback test.** `tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores` now sees stateful exposure counts from impression logging. Expand the allowed edit set to include that file: snapshot/clear `store.impressions` between baseline, learned, and restored calls (or use a fresh store per call), and create its client with `events_dir=tmp_path / "events", exploration_seed=42`. Do not weaken the rollback assertion; the comparison must be under identical exposure state.
- `GET /events/metrics`: return `app.state.events.funnel_metrics()`.
- `/assignments`: if `recommendation_context.request_id`, call `record_event(..., action="accept", user_id=customer_id, role="customer", metadata={"weights_version": app.state.weight_store.active().version})`; catch **both** `KeyError` and `ValueError` so an unknown request or a duplicate accept never turns a successful assignment into a 500. Add a test that posts an `accept` event first, then assigns with the same `request_id`, and asserts 200 (not 500).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_api_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. Existing API tests should still pass because the new response field has a default.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 19: Wire Choice Learning into Weight Recompute and Personalization

**Files:**
- Modify: `app/main.py`
- Modify: `app/service.py` (add `features_for`)
- Modify: `app/personalization/user_weights.py` (use `update_pair` from events if not already wired)
- Test: `tests/test_api_events.py`, `tests/test_pairwise_learning.py` (extend)

**Interfaces:**
- Produces:
  - `RecommendationService.features_for(task_id: str, worker_id: str) -> dict[str, float]`.
  - `POST /weights/recompute?include_events=true` uses `PairwiseChoiceLearner` on train events; response includes `weights`, `version`, `updates`, and `binding`.
  - `GET /weights/binding` returns the latest `WeightBindingReport` as JSON.
  - `POST /events` for `accept`/`reject` calls `personalizer.update_pair` for the request's user when both chosen and rejected features are available.
  - **Ruling from pre-flight scan:** add `CHOICE_LEARNING_MODE` config (`"pairwise"` default, `"listwise"` optional). `include_events=true` uses `PairwiseChoiceLearner` by default; when `CHOICE_LEARNING_MODE="listwise"`, use `ListwiseChoiceLearner` over each impression's candidate set. The benchmark's existing `BenchmarkRecommender.learn` remains the listwise reference.
  - **Auto-accept candidate type:** `/assignments` must choose the event candidate from the impression metadata. If the impression's `candidate_type == "task"`, use `request.task_id` as `candidate_id`; otherwise use `request.worker_id`. This fixes task-direction accepts being silently dropped. Add a test that assigns from a `/recommend/tasks` request and asserts the accept event is recorded.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_events.py`:

```python
def test_recompute_with_events_changes_weights(client):
    before = client.get("/weights").json()["weights"]
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 2})
    body = response.json()
    chosen = body["candidates"][0]["candidate_id"]
    rejected = body["candidates"][1]["candidate_id"]
    client.post("/events", json={"events": [
        {"request_id": body["request_id"], "candidate_id": chosen, "action": "accept", "task_id": "t1", "user_id": "c1"},
        {"request_id": body["request_id"], "candidate_id": rejected, "action": "reject", "task_id": "t1", "user_id": "c1"},
    ]})
    recomputed = client.post("/weights/recompute?include_events=true")
    assert recomputed.status_code == 200
    payload = recomputed.json()
    assert payload["weights"]
    assert payload.get("updates", 0) > 0
    assert payload["weights"] != before
    assert abs(sum(payload["weights"].values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_api_events.py::test_recompute_with_events_changes_weights -v`
Expected: FAIL because `include_events` is not supported.

- [ ] **Step 3: Implement**

- `RecommendationService.features_for`: **must be feature-parity with serving.** Reuse the same feature-building path/kwargs used by `recommend_workers_for_task`/`recommend_tasks`: normalized ItemCF score (not raw), semantic matcher similarity (0.5 only when no matcher), `p_accept` when the acceptance model is fitted, `recent_impressions`, `collaboration`, `communication`, `pay_fit`, profiles, and the same `now`. Add a test asserting `features_for(task_id, worker_id)` equals the serving feature breakdown for the same pair. Raise `KeyError` for unknown IDs.
- `POST /weights/recompute`: parse `include_events` (default true) and `mode` (from `CHOICE_LEARNING_MODE`, default `"pairwise"`). Build `ChoicePair`s from `dataset.train_events`/`store.events` using `features_for` as the lookup; call `PairwiseChoiceLearner(prior=current_weights).fit(pairs)`. When `mode="listwise"`, use `ListwiseChoiceLearner` over each impression's candidate features instead. Merge with the existing rating-based batch fit (e.g., average the two weight vectors, then `project_weights`); save a new version via the existing `WeightStore`; include `updates` and `binding` in the response.
- `GET /weights/binding`: return the last `WeightBindingReport` recorded during recompute; **persist it to `reports/weight_binding.json`** after projection and have `GET` fall back to reading that file when `app.state.last_binding` is None; if neither exists, return `{"available": False}`.
- Personalization: in `POST /events`, after recording an accept/reject, pair against **both** the current payload and prior `store.events` for the same `request_id` (split batches must work). Maintain a learned-request set so re-posts do not double-update. Call `app.state.personalizer.update_pair(user_id, chosen_features, rejected_features)` when both sides are available; guard with `try/except KeyError` so event ingestion never fails because personalization is unavailable. Add tests for split accept/reject batches and `source == "online_pair"`.
- Recompute tests: assert `source`/`mode` on the response so the tests fail if the purpose-built choice learner branch is dead. Binding test: assert specific keys plus the persisted `reports/weight_binding.json`.
- Do not construct `RecommendationService` on `/events` payloads that have no accept+reject group; filter first.
- `/assignments` auto-accept: look up the impression for `recommendation_context.request_id`; if its `metadata["candidate_type"] == "task"`, record the accept with `candidate_id=request.task_id`, else `candidate_id=request.worker_id`. Add a test that assigns from a `/recommend/tasks` request and asserts the event is recorded.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_api_events.py::test_recompute_with_events_changes_weights -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

## Task 20: End-to-End Strict Evaluation, Benchmark Re-Baseline, and Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/recommendation-flow.md`
- Test: `tests/test_docs.py` (create)
- Reports: `reports/strict_eval.json`, `reports/strict_eval.md`, `reports/benchmark_rounds.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a final strict-eval report, a benchmark re-baseline, and updated docs.

- [ ] **Step 1: Write the failing docs test**

Create `tests/test_docs.py`:

```python
from pathlib import Path


def test_readme_documents_events_and_strict_eval():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "/events" in text
    assert "evaluate_strict.py" in text
    assert "strict_eval" in text


def test_flow_doc_documents_events_and_propensity():
    text = Path("docs/recommendation-flow.md").read_text(encoding="utf-8")
    assert "RecommendationEvent" in text
    assert "propensity" in text
    assert "strict" in text.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_docs.py -v`
Expected: FAIL because the docs do not mention the new flow.

- [ ] **Step 3: Update the docs**

Add to `README.md`:
- A short “推荐机制改进” section listing `/events`, `/events/metrics`, `scripts/evaluate_strict.py`, and the strict metrics.
- A note that the ranker remains seven-dimension linear and that choice learning only estimates weights.
- The exact command `python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10`.

Update `docs/recommendation-flow.md` with the new flow:
```text
请求 → 硬约束 → 候选 + ItemCF → 语义/七维特征 → 权重 → 精确 ε-greedy
→ Top-N + request_id → impression → click/apply/accept/reject/ignore
→ pairwise/listwise 选择学习 → 权重版本 / 校准 / 回滚
```
Mention `RecommendationEvent`, exact propensity, and the strict evaluator.

- [ ] **Step 4: Run the tests and the end-to-end evaluation**

```bash
python -m pytest tests/ -q
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 --candidate-weights data/weights/weights_v0007.json
python scripts/run_benchmark_rounds.py --rounds 10
```

Expected: all tests pass; the strict report and benchmark report are written. Check the strict report against the targets:
- `NDCG@10` relative improvement ≥10% or `HR@10` ≥5pp in at least one direction, and the other direction does not deteriorate.
- 95% CI does not cross 0.
- Constraint violations = 0.
- Cold-start counts as measured only when `cold_start.available` is true **and** `cold_start.queries > 0`; otherwise report N/A, never "passed".
- Benchmark Top-1 not worse than the fresh baseline you recorded in Task 0 (re-run after the `benchmark/features.py` change; do not compare to the historical 0.731 without re-running).
- `reports/strict_eval.md` includes Brier score and reliability bins for the calibrated `P(rating>=4)`; calibration is reported even though it does not affect ranking.
- Use `--candidate-weights` with a real learned weights JSON. Do not pass an empty/zero-key dict; `baseline_equals_candidate` must reflect the effective weights. If candidate == baseline, the report must say identity and no improvement claim is allowed.
- **Document the exact propensity formula, not `0.9` / `1/候选数`.** README and `docs/recommendation-flow.md` must state: top-(K-1)=1.0, rank K=`(1-ε)+ε/(N-K+1)`, tail=`ε/(N-K+1)`.
- **Correct the leakage sentence.** Test data is used for scoring and calibration labels, not for feature construction. State that boundary.
- **Add `cold_start.queries` and `cold_start.measured` to the JSON** so machine consumers do not have to parse Markdown; docs must match.
- **Benchmark narrative:** report the absolute R10 vs prior historical R10 (e.g., 0.568 vs 0.731) explicitly, in addition to the fresh-baseline comparison; regenerate `reports/benchmark_visual.md` or label it historical.
- **Tests:** cover target `MET`/`NOT MET`/`n/a`, cold-start `n/a`, seven-key candidate validation, and effective-weight identity. Do not only test substrings in docs.

If a target is not met, do not claim success. Record the gap in `reports/strict_eval.md` and create a follow-up task; the implementation is still complete, but the accuracy goal is not. Do not present a zero-query cold-start subset or an identity candidate as a passed guardrail.

- [ ] **Step 5: Final full-suite run**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint and report**

No git commit. Update `reports/strict_eval.md` and `reports/benchmark_rounds.md`; summarize the measured deltas, confidence intervals, and any unmet target in the final handoff.

---

## Task 24: Accuracy Target Recovery (choice-learned candidate)

**Goal:** The Task 20 strict run did not meet the target on task→workers (HR −0.17pp, NDCG +0.11%, CIs cross 0) while worker→tasks improved (HR +4.20pp, NDCG +57.1%). Build a candidate weight vector from the **new choice-learning path**, tune only on a validation split, and re-run the 5-seed strict evaluation on the untouched test set. If the target is still unmet, record the gap; do not tune on test and do not claim success.

**Files:**
- Create: `scripts/tune_weights.py`, `tests/test_tune_weights.py`
- Outputs: `data/weights/weights_choice.json`, `reports/strict_eval_tuned.json`, `reports/strict_eval_tuned.md`
- Do not modify the core model; this task only produces/evaluates a candidate.

**Interfaces:**
- `build_choice_candidate(dataset, seed=42) -> dict[str, float]` — build the train-only eval store, compute serving features, build pairs from train events, fit `PairwiseChoiceLearner`, blend with the rating batch fit, project to the simplex.
- `tune_on_validation(dataset, base_weights, budget=20) -> dict[str, float]` — hold out the last 20% of train assignments as validation; coordinate search only on validation; never read test assignments.
- `evaluate_candidate(candidate, seeds=(42,43,44,45,46)) -> dict` — run the existing strict evaluator with `DEFAULT_WEIGHTS` as baseline and the candidate as override.

**Tasks:**
- 24a: build the choice-learned candidate from train events + rating batch.
- 24b: validation-only coordinate search within the existing simplex bounds and a fixed evaluation budget.
- 24c: 5-seed strict eval on test; report NDCG/HR, CIs, constraint violations, cold-start availability, latency, and calibration.
- 24d: update `reports/strict_eval_tuned.md` with either a met-target claim or the remaining gap; never tune on test.

**Acceptance:** target met (NDCG +10% or HR +5pp in at least one direction, other not deteriorating, CI excludes 0) or the gap is explicitly recorded; weights valid; no test leakage; strict report regenerated.

---

## Task 23: Natural Language Processing Enhancement

**Goal:** Improve classification, field extraction, skill/resume parsing, keyword extraction, calibration, and explainability **without an LLM**. Execution order: after Task 20, before Task 21/22 (both reuse this layer).

**Files:**
- Create: `app/nlp/normalize.py`, `app/nlp/tokenizer.py`, `app/nlp/sections.py`, `scripts/evaluate_nlp.py`, `tests/test_nlp_normalize.py`, `tests/test_nlp_extract.py`, `tests/test_nlp_sections.py`, `tests/test_nlp_eval.py`
- Modify: `app/nlp/classifier.py`, `app/nlp/lexicon.py`, `app/main.py` (only `/classify` response fields), `frontend/app.js` (confidence/correction display), `requirements.txt` (document optional `jieba`/`sklearn-crfsuite`)
- Data: `data/lexicon/skills.txt`, `roles.txt`, `industries.txt`, `aliases.txt`, `stopwords.txt`, `jieba_userdict.txt`

**Interfaces:**
- `normalize_text(text: str) -> str` — NFKC, full/half width, whitespace, punctuation.
- `tokenize(text) -> list[str]`, `content_words(text) -> list[str]`, `keywords(text, top_k=10) -> list[str]` — optional jieba with custom dictionary; fallback to char n-grams when unavailable.
- `extract_fields_v2(text) -> dict` — budget/duration/date/remote/count/experience/language/skills, each with value, confidence, and evidence span; post-validate min≤max, deadline>now, skills in taxonomy.
- `parse_resume_sections(text) -> dict` — education/work/projects/skills/certificates/languages; extract titles, companies, dates, experience years.
- `classify_task(text) -> dict` — existing top-3 + confidence + `needs_clarification`; add calibrated probabilities.
- `evaluate_nlp(records) -> dict` — per-field P/R/F1, category top-1/top-3/macro-F1, ECE/Brier, clarification rate, wrong-confident rate, paraphrase/typo slices.

**Tasks:**
- 23a: normalization + alias/synonym lexicon + optional jieba tokenizer with char-ngram fallback.
- 23b: field extraction v2 with evidence spans and validation.
- 23c: hybrid char+word classifier features, Platt/isotonic calibration, per-category thresholds, confidence gating.
- 23d: resume section parser + skill/experience extraction (dictionary + optional char-BIO CRF).
- 23e: NLP evaluation script and report; include a hand-written/paraphrased holdout **and a hard category slice where the discriminating lexicon keyword is removed or replaced while the meaning is kept**. Report easy vs hard slices separately. Do not claim category targets from the easy slice alone. If the hard slice does not support the target, mark it NOT DEMONSTRATED.
- 23f: integrate into `/classify` and Task 22 upload/resume analysis; frontend shows per-field confidence and allows correction.

**Acceptance:** no new required dependencies (`jieba`, `sklearn-crfsuite` optional with fallback); budget/duration/date/remote F1 on a labeled holdout ≥ 0.90; category top-1 ≥ baseline + 3pp and top-3 ≥ 0.95 **on the hard slice**, macro-F1 ≥ 0.80 **on the hard slice**; ECE ≤ 0.10 only when a fitted calibrator is used — if a fixed prior fallback is used, mark it "met numerically only / not demonstrated"; clarification rate ≤ 15% with wrong-confident rate < 5%. If a hard-slice target is unmet, report NOT DEMONSTRATED rather than claiming success.

---

## Task 21: Large Natural-Language Benchmark (scheme E)

**Goal:** Generate 10,000 realistic natural-language tasks and 1,000 natural-language worker resumes with no exact or near duplicates, plus 100,000 historical assignments, 80/20 split, SQLite + JSONL, and a sampled evaluation report.

**Scheme E:** A (template slots + sentence variants) for 80–90% of records, B (latent DGP) for assignments/accept/rating/ground truth, C (optional LLM seed JSON) off by default, D (real corpus) not required.

**Files:**
- Create: `app/data/large_synthetic.py`, `scripts/build_large_benchmark.py`, `app/benchmark/large.py`
- Test: `tests/test_large_synthetic.py`, `tests/test_large_benchmark.py`
- Outputs: `data/benchmark/task_benchmark_large.sqlite`, `data/benchmark/task_benchmark_large.jsonl`, `reports/large_benchmark_stats.md`, `reports/large_benchmark_eval.md`

**Interfaces:**
- `generate_large_dataset(n_workers=1000, n_tasks=10000, n_assignments=100000, seed=42) -> Dataset` with `task_text` and `resume_text` natural-language fields.
- `normalized_text_hash(text) -> str`, `simhash64(text) -> int`, `is_near_duplicate(a: str, b: str, max_hamming: int = 3) -> bool`.
- `build_large_sqlite(dataset, path) -> None`, `load_large_sqlite(path) -> Dataset`.
- `evaluate_large(path, test_tasks=500, candidates=200, seeds=(42,43,44,45,46)) -> dict`.

**Tasks:**
- 21a: natural-language task/resume generator (A) with unique titles, sentence variants, category/industry quotas, and a `--llm-seeds PATH` optional JSON hook (C, default off).
- 21b: latent DGP (B) for assignments, accept/reject, ratings, and ground truth; 80/20 task split; train-only worker history.
- 21c: dedup (exact hash + unique title + simhash near-duplicate) and SQLite/JSONL export with a stats report (duplicate rate, category/industry/budget/duration distributions, text lengths, resume completeness).
- 21d: sampled evaluation (500 test tasks × 200 candidates × 5 seeds) and report; wire ItemCF into the large benchmark and normalize collaborative scores across the candidate pool. **The ItemCF similarity graph must be built from train-split accepted assignments only; test-task co-occurrences must not enter it.** Add a leakage regression test asserting a test-split assignment cannot change `item_users`/`item_similarity` or a test-task score. Model-facing loaders/JSONL must expose only train-split outcomes; test outcomes are evaluator-only. Document the gold definition (latent-best in a 10-worker exposure pool), its acceptance rate, and add a feature-only/exposure-pool baseline; qualify any random-baseline comparison. Resume project results and certificates must be category-consistent, with a coherence test.

**Acceptance:** 10,000 unique task texts, 1,000 unique resume texts, exact-duplicate rate = 0, near-duplicate rate < 0.5%, all natural-language fields non-empty, 100,000 assignments, 80/20 split, sampled evaluation report with Top-1/Top-5/MRR/NDCG and a data-quality section.

---

## Task 22: Bidirectional Upload/Analysis — Task → Workers and Resume → Tasks

**Goal:** Support both directions: upload/paste a task document → semantic analysis → Top-N workers; upload/paste a resume → semantic analysis → Top-N open tasks. No auto-write; the user confirms a draft.

**Files:**
- Create: `app/upload/extract.py`, `app/upload/analyze.py`, `tests/test_upload.py`, `tests/test_upload_api.py`
- Modify: `app/main.py`, `app/schemas.py`, `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `requirements.txt` (document optional PDF/DOCX extras)
- No persistence of the uploaded file.

**Interfaces:**
- `extract_text(filename: str, content: bytes) -> str` — `.txt`/`.md` native; `.pdf` via optional `pypdf`, `.docx` via optional `python-docx`; unsupported/oversized → 422 with a clear message.
- `analyze_task_text(text: str) -> dict` — `TaskTextClassifier.predict` + `extract_fields`; returns category, confidence, top-3 categories, budget/days/skills/remote/requirements.
- `analyze_resume_text(text: str) -> dict` — skill/category lexicon + `extract_fields`; returns detected skills, inferred categories, experience years, region/remote preference, expected pay if mentioned, and a draft `Worker` payload. No auto-write.
- `POST /upload/task` multipart — file → analysis + Top-N workers (semantic similarity + seven-dim scores) + a draft task payload.
- `POST /upload/resume` multipart — file → analysis + Top-N open tasks using a temporary `Worker` profile and `RecommendationService.recommend_tasks`; include a draft `Worker` payload.
- `POST /resume/analyze` JSON `{"text": "..."}` — paste-text path for the resume side (same analyzer, no file).
- Both upload endpoints never write to the store.

**Tasks:**
- 22a: text extraction layer with 10 MB limit, MIME/extension whitelist, in-memory parsing, no execution. **Enforce the limit in a pure ASGI middleware before multipart parsing**: reject an over-limit `Content-Length` and count streamed bytes for chunked bodies; set the Starlette `MultiPartParser` spool threshold so accepted files stay in RAM; cap `max_files`/`max_fields`; apply the same body cap to `/resume/analyze`. Pre-check ZIP entries (total/per-entry uncompressed size and compression ratio) before `docx.Document`. **PDF pre-scan must resolve `/Filter` aliases (`/Fl`, `/FlateDecode`), indirect filter references, and arbitrary dictionary-to-stream gaps; for Flate streams, decode with `zlib.decompressobj` and a hard `max_length` before `extract_text`, rejecting output over the bound. Traverse the reachable object graph iteratively (page `/Contents`, `/Resources`, `/Annots`, nested Form XObjects via `/Resources`/`/XObject`, and **`/Parent`-inherited resources** to mirror pypdf's `get_inherited` form-resource lookup) with a visited set and fail-closed node/stream caps; do not use a depth cap below pypdf's Form XObject traversal (which reaches thousands). Reject unsupported filters (or isolate them in a subprocess with a hard timeout/RSS limit).** Cap PDF pages/characters with an early break.
- 22b: task analysis + `POST /upload/task` recommendation response; reuse `RecommendationService`/`candidate_features`; include a draft `Task` payload.
- 22c: resume analysis + `POST /upload/resume` and `POST /resume/analyze`; build a temporary `Worker` profile from extracted skills/experience; return Top-N tasks with reasons; include a draft `Worker` payload. **Do not use monthly/hourly expected pay directly as per-task pay**: if the period is 月/小时 — including label forms `月薪`, `时薪`, `期望月薪`, `期望时薪` — set `Worker.expected_pay=0.0` (unknown per-task) or convert to a per-task/day rate, and keep the raw figure only in the analysis payload.
- 22d: frontend with two cards/tabs ("上传任务书" and "输入/上传简历"), text preview, extracted fields/profile, Top-N results, and confirm-to-create.
- 22e: unit + API tests; document optional PDF/DOCX dependencies and the no-persistence rule.

**Acceptance:** `.txt`/`.md` work without optional deps; `.pdf`/`.docx` work when extras are installed and return a clear 422 otherwise; the 10 MB limit is enforced **before form parsing** (ASGI Content-Length + streamed-byte count, no oversized temp-file spool); ZIP/PDF expansion is bounded before full parse; no auto-write; task upload returns Top-N workers; resume paste/upload returns Top-N tasks; monthly pay is not used as per-task pay; tests pass. `python-multipart` is required for FastAPI uploads and must be added to `requirements.txt`.

---

## Self-Review Checklist

Before handing off the plan, verify:

- [x] **Spec coverage:** every spec section maps to at least one task:
  - §3 strict evaluation → Tasks 6–7, 20
  - §5 data model → Task 1
  - §6 events → Tasks 2–4, 18
  - §7 propensity → Task 5
  - §8 seven-dim features → Tasks 10–14
  - §9 semantic → Task 9
  - §10 learning/calibration → Tasks 15–17
  - §11 API → Task 18
  - §12 engineering → Tasks 1–19
  - §13 tests → every task
  - §14 phases → task order
  - §15 risks → Review Focus + leakage tests
  - §16 non-goals → Global Constraints
  - §17 defaults → task values
- [x] **Step scan:** each step names one action with a checkable result.
- [x] **Type consistency:** `Impression`, `RecommendationEvent`, `EventService`, `SemanticMatcher`, `PairwiseChoiceLearner`, `ListwiseChoiceLearner`, `PlattCalibrator`, `WeightBindingReport` names are used consistently across tasks.
- [x] **Review Focus:** the five failure modes have owning tests:
  - tiny pools → Task 5/7
  - cold start → Task 10/12/13
  - duplicate/out-of-order events → Task 2/15/18
  - missing dependency/fields → Task 9/10
  - test leakage → Task 3/6
- [x] **Proportion:** this plan describes interfaces, tests, and exact values; it does not paste full implementations.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-13-recommendation-improvement.md`.

This directory is not a git repository, so there is no branch to create and no commit steps. The executor should treat each task’s full-suite run as the checkpoint.

Recommended execution: **subagent-driven** — the tasks depend on each other’s interfaces (`Impression`/`RecommendationEvent`/features/choice learner), and a fresh reviewer per task catches interface drift before it compounds. If the user prefers speed, native execution is acceptable, but the interface-heavy Tasks 1, 15, and 18 should still be reviewed carefully.
