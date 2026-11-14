# Task Assignment Recommender — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable Phase 1 MVP: deterministic synthetic data → seven-dimension candidate scoring → bidirectional Top-N FastAPI endpoints → template-based task-chain decomposition and per-node planning → basic offline metrics and tests.

**Architecture:** A FastAPI service over an in-memory store. `app/domain.py` holds dataclasses; `app/data/synthetic.py` generates a deterministic dataset; `app/features.py` + `app/models/itemcf.py` produce normalized scores; `app/service.py` applies hard constraints and ranks; `app/chains/` loads templates, validates DAGs, decomposes tasks, and plans nodes; `app/metrics.py` computes HR/NDCG.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, uvicorn, numpy, pandas, scikit-learn, pytest, httpx.

**Spec:** `specs/2026-11-13-task-assignment-recommender-design.md`

## Global Constraints

- Work only inside `task-recommender/`.
- Python 3.13; do not add heavy dependencies beyond `requirements.txt`.
- Every score exposed by feature functions is normalized to `[0, 1]`; fusion weights sum to `1.0`.
- Synthetic data is deterministic: default `seed=42`.
- Hard constraints (skills, level, capacity, status, breach tier) must produce zero violations.
- The workspace is **not a git repository**: do not run `git commit`. Each task ends with a test checkpoint instead.
- Code identifiers and docstrings in English; README and API-facing text in Chinese.
- **Phase 1 simplifications (intentional):** `Worker.specialties` is `dict[str, int]`; `Customer.preference_weights` is a plain dict; no feedback-driven weight learning, no per-user weight versions, no rollback, no LLM, no Beam Search/MILP, no multi-template composition. Breach propagation is calculated but does not trigger automatic replanning. These are Phase 2/3.
- Phase 1 default data scale: 100 workers, 500 tasks, 3,000 assignments. Full-scale 800/4,000/30,000 is Phase 2.

## Review Focus

These are the failure modes most likely to bite a user; each must be pinned by a test in the task that owns the code.

1. **Cold-start worker/task**: no history must still return eligible candidates, with collaborative score `0.0`.
2. **Hard constraints**: ineligible workers (skill, level, capacity, recent breach) must never appear in results.
3. **Empty candidate set**: must return HTTP 200 with an empty list plus a reason, not a 500 or KeyError.
4. **Chain optional nodes**: excluding an optional node must bypass its dependency edges without breaking the DAG.
5. **DAG cycle or missing dependency**: validation must reject the chain with a clear error, never hang or recurse forever.

---

## Task 1: Project Skeleton and Health Endpoint

**Files:**
- Create: `task-recommender/requirements.txt`
- Create: `task-recommender/app/__init__.py`
- Create: `task-recommender/app/config.py`
- Create: `task-recommender/app/main.py`
- Create: `task-recommender/tests/test_api.py`

**Interfaces:**
- `app.main.create_app() -> FastAPI`
- `GET /health -> {"status": "ok", "version": "0.1.0"}`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from app.main import create_app


def test_health():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_api.py::test_health -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or `create_app` missing.

- [ ] **Step 3: Implement the skeleton**

`requirements.txt`:

```text
fastapi>=0.115
uvicorn>=0.30
numpy>=1.26
pandas>=2.2
scikit-learn>=1.4
pytest>=8.0
httpx>=0.27
```

`app/config.py` defines `APP_VERSION = "0.1.0"` and the default fusion weights (reputation `0.32`, skill `0.20`, expertise `0.15`, collaborative `0.13`, preference `0.10`, load `0.06`, customer_preference `0.04`).

`app/main.py` defines `create_app() -> FastAPI`, initializes `app.state.store = None` and `app.state.templates = {}`, and adds the `/health` route. Do not load synthetic data or templates yet; those arrive in Tasks 3 and 10.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_api.py::test_health -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass. Do not commit (workspace is not a git repo).

---

## Task 2: Domain Models and In-Memory Store

**Files:**
- Create: `task-recommender/app/domain.py`
- Create: `task-recommender/app/data/__init__.py`
- Create: `task-recommender/app/data/store.py`
- Create: `task-recommender/tests/test_store.py`

**Interfaces:**
- Dataclasses: `Worker`, `Customer`, `Task`, `Assignment`, `Feedback`, `Dataset`, `SubTask`, `ChainEdge`, `TaskChain`, `ChainPlan`, `ChainPlanNode`, `DecompositionDraft`, `DecompositionQuality`, `ValidationResult`, `BreachImpact`.
- `Store(workers: list[Worker], customers: list[Customer], tasks: list[Task], assignments: list[Assignment], feedback: list[Feedback], templates: dict[str, dict] | None = None, chains: dict[str, TaskChain] | None = None)`
- Store attributes: `.workers`, `.customers`, `.tasks` are `dict[str, Entity]`; `.assignments`, `.feedback` are lists; `.templates` and `.chains` are dicts.
- `Store.worker_ratings(worker_id: str) -> list[float]`
- `Store.worker_assignments(worker_id: str) -> list[Assignment]`

Worker fields: `worker_id, name, skills: dict[str,int], specialties: dict[str,int], level: int, capacity_hours: float, current_load_hours: float, preferred_categories: dict[str,float], preferred_difficulty: tuple[int,int], region: str, remote_ok: bool, status: str = "active", ratings: list[float] = [], completed: int = 0, on_time: int = 0, rework_count: int = 0, breach_dates: list[datetime] = []`.

Task fields: `task_id, customer_id, title, description, category, required_skills: dict[str,int], required_level: int, difficulty: int, priority: int, estimated_hours: float, deadline: datetime, region, remote_ok, status: str = "open", budget: float = 0.0, created_at: datetime`.

`Dataset` fields: `workers: list[Worker], customers: list[Customer], tasks: list[Task], assignments: list[Assignment], feedback: list[Feedback], train: list[Assignment], test: list[Assignment]`.

SubTask fields: `subtask_id, chain_id, key, title, node_type, estimated_hours, required_skills, depends_on: list[str], acceptance: list[str], optional: bool = False, parallel_group: str | None = None, risk_flags: list[str] = [], status: str = "pending", assigned_worker_id: str | None = None`.

`ChainEdge` fields: `chain_id, from_node, to_node, edge_type`.
`TaskChain` fields: `chain_id, root_task_id, customer_id, status, deadline, budget, nodes: list[SubTask], edges: list[ChainEdge], critical_path: list[str]`.

`BreachImpact` fields: `failed_node: str, affected_nodes: list[str], critical_path_delay: float, chain_slack: float, severity: float, requires_replan: bool`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime
from app.domain import Worker
from app.data.store import Store


def test_store_indexes_workers_and_computes_ratings():
    worker = Worker(
        worker_id="w1", name="A", skills={"python": 4},
        specialties={"software_dev": 3}, level=3,
        capacity_hours=40, current_load_hours=0,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4), region="CN", remote_ok=True,
        ratings=[5.0, 4.0],
    )
    store = Store(workers=[worker], customers=[], tasks=[], assignments=[], feedback=[])
    assert store.workers["w1"] is worker
    assert store.worker_ratings("w1") == [5.0, 4.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing `Store`.

- [ ] **Step 3: Implement `app/domain.py` and `app/data/store.py`**

Use `@dataclass` for domain entities and `datetime`/`field(default_factory=list)` for mutable defaults. The store indexes lists into dicts by ID and returns empty lists for unknown IDs.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 3: Deterministic Synthetic Dataset

**Files:**
- Create: `task-recommender/app/data/synthetic.py`
- Create: `task-recommender/tests/test_synthetic.py`

**Interfaces:**
- `generate_dataset(n_workers: int = 100, n_tasks: int = 500, n_assignments: int = 3000, seed: int = 42) -> Dataset`
- `Dataset` contains `.workers`, `.customers`, `.tasks`, `.assignments`, `.feedback`, `.train`, `.test`.
- Categories: exactly the 12 keys used in `data/chain_templates/common_task_chains.json`.
- Time split: sort assignments by `created_at`; first 80% train, last 20% test.

- [ ] **Step 1: Write the failing test**

```python
from app.data.synthetic import generate_dataset


def test_generate_dataset_is_deterministic_and_split():
    a = generate_dataset(seed=42)
    b = generate_dataset(seed=42)
    assert [w.worker_id for w in a.workers] == [w.worker_id for w in b.workers]
    assert len(a.assignments) == 3000
    assert len(a.train) + len(a.test) == 3000
    assert len(a.workers) == 100
    assert len(a.tasks) == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_synthetic.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement the generator**

Use `random.Random(seed)` (stdlib) for reproducibility. Generate:
- 100 workers with 3–8 skills drawn from 30 skill names, proficiency 1–5, 1–3 specialties, level 1–5, capacity 20–40h, load 0–20h, preferred categories, preferred difficulty, reliability latent.
- 500 tasks across 12 categories, 1–3 required skills, required level, difficulty 1–5, hours 2–24, deadlines over 12 months, status `open`.
- 3,000 assignments: pick a worker with probability proportional to `0.4*skill_match + 0.3*specialty + 0.2*(1-load_ratio) + 0.1*reliability`; skip pairs that violate hard skill/capacity constraints.
- Outcomes: on-time and quality depend on match + reliability; breach rate about 3%; ratings for 70% of completed assignments, 1–5.
- Sort by `created_at`, split 80/20.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_synthetic.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 4: Feature Scoring and Fusion

**Files:**
- Create: `task-recommender/app/features.py`
- Create: `task-recommender/tests/test_features.py`

**Interfaces:**
- `skill_score(worker: Worker, task: Task) -> float`
- `expertise_score(worker: Worker, task: Task) -> float`
- `reputation_score(worker: Worker, category: str | None = None) -> float`
- `preference_score(worker: Worker, task: Task) -> float`
- `load_score(worker: Worker, task: Task) -> float`
- `customer_preference_score(customer: Customer, worker: Worker, task: Task, reputation: float, expertise: float) -> float`
- `candidate_features(worker: Worker, task: Task, customer: Customer, cf_score: float = 0.0) -> dict[str, float]` returns keys `reputation, skill, expertise, collaborative, preference, load, customer_preference`.
- `fuse_scores(features: dict[str, float], weights: dict[str, float]) -> float`

Formulas (Phase 1):
- `skill_score = mean(min(worker.skills[s] / task.required_skills[s], 1.0) for required s)`, or `1.0` when the task has no required skills.
- `expertise_score = worker.specialties.get(task.category, 0) / 5.0`.
- `reputation_score`: Bayesian rating `(sum(ratings) + 10*4.2) / (len(ratings) + 10) / 5`, then `0.4*rating + 0.2*completion_rate + 0.2*on_time_rate + 0.1*rework_score + 0.1*breach_penalty`; `breach_penalty` is `1.0` for 0 recent breaches, `0.5` for 1, `0.0` for >=2. Recent window = 180 days.
- `preference_score = 0.6*preferred_categories.get(category, 0) + 0.4*difficulty_fit`, where `difficulty_fit = 1 - abs(difficulty - midpoint(preferred_difficulty)) / 4`.
- `load_score = max(0.0, 1.0 - (current_load_hours + task.estimated_hours) / capacity_hours)`.
- `customer_preference_score = 0.5*reputation + 0.3*expertise + 0.2*load`.
- `fuse_scores` is a weighted sum; raise `ValueError` if weights do not sum to `1.0 ± 1e-6`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta
from app.domain import Customer, Task, Worker
from app.features import candidate_features, fuse_scores, skill_score


def make_worker(**overrides):
    data = dict(
        worker_id="w1", name="A", skills={"python": 4},
        specialties={"software_dev": 3}, level=3,
        capacity_hours=40, current_load_hours=10,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4), region="CN", remote_ok=True,
        ratings=[5.0, 4.0], completed=2, on_time=2, rework_count=0,
    )
    data.update(overrides)
    return Worker(**data)


def make_task(**overrides):
    data = dict(
        task_id="t1", customer_id="c1", title="Build API",
        description="", category="software_dev",
        required_skills={"python": 3}, required_level=2,
        difficulty=3, priority=3, estimated_hours=8,
        deadline=datetime.now() + timedelta(days=7),
        region="CN", remote_ok=True,
    )
    data.update(overrides)
    return Task(**data)


def test_skill_score_full_match_and_missing_skill():
    assert skill_score(make_worker(), make_task()) == 1.0
    assert skill_score(make_worker(skills={}), make_task()) == 0.0


def test_features_are_normalized_and_fusion_sums_to_score():
    features = candidate_features(make_worker(), make_task(), Customer(customer_id="c1", name="C", region="CN"))
    assert all(0.0 <= v <= 1.0 for v in features.values())
    weights = {"reputation": 0.32, "skill": 0.20, "expertise": 0.15,
               "collaborative": 0.13, "preference": 0.10, "load": 0.06,
               "customer_preference": 0.04}
    score = fuse_scores(features, weights)
    assert 0.0 <= score <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_features.py -v`
Expected: FAIL with missing `app.features`.

- [ ] **Step 3: Implement the feature functions**

Clamp every returned value to `[0, 1]`. Use `datetime.now()` only in tests; feature functions take no current time. `recent_breach_count` compares `breach_dates` with `datetime.utcnow() - timedelta(days=180)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_features.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 5: ItemCF Collaborative Score

**Files:**
- Create: `task-recommender/app/models/__init__.py`
- Create: `task-recommender/app/models/itemcf.py`
- Create: `task-recommender/tests/test_itemcf.py`

**Interfaces:**
- `ItemCF(interactions: list[tuple[str, str, float]], shrinkage: float = 5.0)`
  - `interactions` are `(worker_id, task_id, weight)`.
- `ItemCF.score(worker_id: str, task_id: str) -> float` returns a raw non-negative score; unknown worker/task returns `0.0`.
- `ItemCF.normalize(raw: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]` min-max normalizes to `[0, 1]`; an all-zero or empty input returns zeros.

- [ ] **Step 1: Write the failing test**

```python
from app.models.itemcf import ItemCF


def test_cold_start_is_zero():
    cf = ItemCF([])
    assert cf.score("w1", "t1") == 0.0


def test_similar_tasks_give_positive_score():
    cf = ItemCF([("w1", "t1", 1.0), ("w1", "t2", 1.0)])
    assert cf.score("w1", "t2") > 0.0


def test_normalize_bounds():
    cf = ItemCF([])
    assert cf.normalize({}) == {}
    assert cf.normalize({("w1", "t1"): 0.0}) == {("w1", "t1"): 0.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_itemcf.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement ItemCF**

Build `item_users: dict[task_id, dict[worker_id, weight]]`. Cosine similarity with shrinkage: `cooc / (sqrt(n_i * n_j) + shrinkage)`. Score for `(u, i)` = `sum(sim(i, j) * x_uj for j in user's tasks) / max(1, sum(abs(sim)))`. Use `math.sqrt`; no numpy required.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_itemcf.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 6: Recommendation Service and Bidirectional API

**Files:**
- Create: `task-recommender/app/service.py`
- Create: `task-recommender/app/schemas.py`
- Modify: `task-recommender/app/main.py`
- Create: `task-recommender/tests/test_recommend.py`
- Create: `task-recommender/tests/conftest.py`

**Interfaces:**
- `is_eligible(worker: Worker, task: Task, store: Store, now: datetime | None = None) -> tuple[bool, str]`
- `ScoredCandidate` dataclass: `candidate_id: str, score: float, breakdown: dict[str,float], reasons: list[str], cold_start: bool`
- `RecommendationService(store: Store, weights: dict[str,float] | None = None)`
  - `.recommend_workers(task_id: str, top_n: int = 10) -> list[ScoredCandidate]`
  - `.recommend_workers_for_task(task: Task, top_n: int = 10) -> list[ScoredCandidate]`
  - `.recommend_tasks(worker_id: str, top_n: int = 10) -> list[ScoredCandidate]`
- Extend `app.main.create_app(store: Store | None = None) -> FastAPI` so tests can inject a small store.
- API:
  - `POST /recommend/workers` body `{task_id, top_n, explain}` → `{query_id, candidates, reason: str | None}`
  - `POST /recommend/tasks` body `{worker_id, top_n, explain}` → `{query_id, candidates, reason: str | None}`
  - `GET /workers`, `GET /workers/{id}`, `GET /tasks`, `GET /tasks/{id}`
- Missing task/worker → HTTP 404. Empty eligible set → HTTP 200 with `candidates: []` and `reason`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ineligible_worker_is_excluded(small_store):
    # task requires skill "python"; worker w_bad does not have it
    from app.service import is_eligible
    ok, reason = is_eligible(small_store.workers["w_bad"], small_store.tasks["t1"], small_store)
    assert not ok
    assert "skill" in reason.lower()
```

```python
def test_recommend_workers_returns_top_n_and_scores(small_store):
    from app.service import RecommendationService
    service = RecommendationService(small_store)
    candidates = service.recommend_workers("t1", top_n=2)
    assert 0 < len(candidates) <= 2
    assert all(0.0 <= c.score <= 1.0 for c in candidates)
    assert candidates == sorted(candidates, key=lambda c: c.score, reverse=True)
```

```python
def test_api_missing_task_returns_404(client):
    response = client.post("/recommend/workers", json={"task_id": "nope"})
    assert response.status_code == 404
```

```python
def test_cold_start_worker_still_ranked_with_zero_cf(small_store):
    from app.service import RecommendationService
    service = RecommendationService(small_store)
    candidates = service.recommend_workers("t1", top_n=10)
    cold = [c for c in candidates if c.cold_start]
    assert cold
    assert all(c.breakdown["collaborative"] == 0.0 for c in cold)
```

```python
def test_empty_candidate_set_returns_200_with_reason(client):
    response = client.post("/recommend/workers", json={"task_id": "t_empty"})
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == []
    assert body["reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_recommend.py -v`
Expected: FAIL with missing module/endpoints.

- [ ] **Step 3: Implement eligibility, scoring orchestration, and endpoints**

Eligibility order: task exists and is `open`; worker exists and `active`; all required skills met; `level >= required_level`; `current_load_hours + estimated_hours <= capacity_hours`; recent breaches `< 2`. Return `(False, "<reason>")` at the first failure.

Scoring: build ItemCF from `store.assignments` with weight `1.0` for completed assignments, `0.5` for completed without rating, `0.0` for failed. For each eligible candidate compute `candidate_features` with the normalized CF score, then `fuse_scores`. Cold start = worker has no assignments (CF score `0.0`). Sort descending, tie-break by `candidate_id`.

`tests/conftest.py` builds a small deterministic store with at least: `t1` (requires `python>=3`), `t_empty` (requires a skill no worker has), `w_good` (python 4, capacity 40, load 0), `w_new` (python 4, capacity 40, load 0, no assignments), `w_bad` (no python), `w_overloaded` (load 40/40), `w_breach` (2 recent breach dates). It also exposes a `software_task` fixture and a `client` fixture built with `TestClient(create_app(small_store))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_recommend.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 7: Chain Template Loader and DAG Utilities

**Files:**
- Copy: `specs/task-chain-templates/common_task_chains.json` → `task-recommender/data/chain_templates/common_task_chains.json`
- Create: `task-recommender/app/data/templates.py`
- Create: `task-recommender/app/chains/__init__.py`
- Create: `task-recommender/app/chains/dag.py`
- Create: `task-recommender/tests/test_chains.py`

**Interfaces:**
- `load_templates(path: str | Path) -> dict[str, dict]` returns `{category: template}`.
- `validate_dag(nodes: list[SubTask]) -> ValidationResult` where `ValidationResult(valid: bool, errors: list[str], order: list[str])`.
- `topological_order(nodes: list[SubTask]) -> list[str]` returns node keys; raises `ValueError` on cycle or missing dependency.
- `critical_path(nodes: list[SubTask]) -> tuple[list[str], float]` returns the longest path keys and total hours.
- `compute_slack(nodes: list[SubTask]) -> dict[str, float]` returns `latest_finish - earliest_finish` per node.

- [ ] **Step 1: Write the failing tests**

```python
from app.chains.dag import critical_path, topological_order, validate_dag
from app.data.templates import load_templates
from app.domain import SubTask


def make_node(key, depends_on, hours=4.0):
    return SubTask(subtask_id=f"s_{key}", chain_id="c1", key=key, title=key,
                   node_type="task", estimated_hours=hours,
                   required_skills={}, depends_on=depends_on, acceptance=["ok"])


def test_loads_twelve_templates():
    templates = load_templates("data/chain_templates/common_task_chains.json")
    assert len(templates) == 12
    assert "software_dev" in templates


def test_topological_order_and_critical_path():
    nodes = [make_node("a", []), make_node("b", ["a"], 6.0), make_node("c", ["a"], 2.0),
             make_node("d", ["b", "c"], 4.0)]
    assert topological_order(nodes)[0] == "a"
    path, hours = critical_path(nodes)
    assert path == ["a", "b", "d"]
    assert hours == 14.0


def test_cycle_is_rejected():
    nodes = [make_node("a", ["b"]), make_node("b", ["a"])]
    result = validate_dag(nodes)
    assert not result.valid
    assert any("cycle" in e.lower() or "cyclic" in e.lower() for e in result.errors)


def test_missing_dependency_is_rejected():
    nodes = [make_node("a", ["missing"])]
    result = validate_dag(nodes)
    assert not result.valid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_chains.py -v`
Expected: FAIL with missing modules.

- [ ] **Step 3: Implement loader and DAG utilities**

`load_templates` validates that each template has `template_id` and `nodes`, and indexes by `category`. DAG functions operate on `SubTask.key` and `depends_on`. `critical_path` computes earliest finish with hours; deterministic tie-break by key. `compute_slack` uses the project finish time from the critical path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_chains.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 8: Decomposition and Quality Score

**Files:**
- Create: `task-recommender/app/chains/decompose.py`
- Create: `task-recommender/tests/test_decomposition.py`

**Interfaces:**
- `extract_requirements(task: Task) -> list[str]` splits `task.description` on `。；;\n`, trims, drops empties; if empty, returns `[task.title]`.
- `decompose(task: Task, template: dict, variant: str = "standard", max_nodes: int = 10) -> DecompositionDraft`
- `coverage_matrix(draft: DecompositionDraft) -> dict[str, list[str]]` maps requirement text → covered node keys.
- `quality_score(draft: DecompositionDraft, store: Store) -> DecompositionQuality`
- `DecompositionDraft` fields: `draft_id, task_id, template_id, variant, chain, requirements, coverage, quality`.
- `DecompositionQuality` fields: `coverage, granularity, dependency, feasibility, template_fit, historical_success, risk_penalty, total, issues` (all floats except `issues: list[str]`).

Decomposition rules:
- Apply `template["variants"][variant]` if present: `hours_multiplier`, `max_nodes`, `exclude`, `include`.
- Include a node unless `optional` is true and `include_if` evaluates false. Phase 1 condition support: `true`, `false`, and `key == 'value'` where `key` is looked up in `task.__dict__`; unsupported expressions evaluate false and add an issue.
- Excluded optional nodes are bypassed: for each excluded node, connect its predecessors directly to its successors.
- Node `estimated_hours` = template `hours` × multiplier, clipped to `[0.5, 40]`.
- `max_nodes` truncates by removing the lowest-priority optional nodes first; never remove `delivery` nodes.
- `critical_path` is recomputed after instantiation.

Quality score:
```text
coverage        = covered requirements / total requirements
granularity     = fraction of nodes whose hours are within [2, 16]
dependency      = 1.0 if DAG valid else 0.0
feasibility     = 1.0 if every node has at least one worker with required skills and capacity, else 0.0
template_fit    = 1.0 if template.category == task.category else 0.5
historical_success = 0.5 (Phase 1 constant)
risk_penalty    = min(0.3, 0.05 * number of risk_flags)
total = 0.30*coverage + 0.20*granularity + 0.15*dependency
      + 0.15*feasibility + 0.10*template_fit + 0.10*historical_success
      - risk_penalty
```

- [ ] **Step 1: Write the failing tests**

```python
from app.chains.decompose import coverage_matrix, decompose, quality_score
from app.data.templates import load_templates


def test_decompose_software_template_has_valid_dag(software_task):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    assert draft.chain.nodes
    assert draft.chain.critical_path
    assert coverage_matrix(draft)


def test_optional_node_exclusion_bypasses_edges(software_task):
    template = {
        "template_id": "tiny_v1", "category": "software_dev", "version": "1.0.0",
        "target_hours": [1, 8], "max_nodes": 5,
        "nodes": [
            {"key": "a", "title": "需求", "type": "task", "hours": 2,
             "skills": {}, "depends_on": [], "acceptance": ["ok"]},
            {"key": "b", "title": "可选评审", "type": "review", "hours": 2,
             "skills": {}, "depends_on": ["a"], "acceptance": ["ok"],
             "optional": True, "include_if": "false"},
            {"key": "c", "title": "交付", "type": "delivery", "hours": 2,
             "skills": {}, "depends_on": ["b"], "acceptance": ["ok"]},
        ],
    }
    draft = decompose(software_task, template)
    by_key = {n.key: n for n in draft.chain.nodes}
    assert "b" not in by_key
    assert by_key["c"].depends_on == ["a"]


def test_quality_score_is_bounded(software_task, small_store):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    quality = quality_score(draft, small_store)
    assert 0.0 <= quality.total <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_decomposition.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement decomposition and quality score**

Use `uuid.uuid4().hex` for `draft_id` and node IDs. Build a `TaskChain` with `deadline=task.deadline`, `budget=task.budget`, nodes, and edges. Node hours: use `hours_range[1]` when present, else `hours`; apply the variant multiplier and clamp to `[0.5, 40]`. Preserve `parallel_group` and `risk_flags` on `SubTask`. `extract_requirements` uses the split characters. `coverage_matrix` uses case-insensitive substring overlap: a requirement is covered by a node if any 2-character token of the requirement appears in the node title; if none match, fall back to the first `delivery` node and record a coverage issue. Keep this simple; full NLP is Phase 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_decomposition.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 9: Chain Planner

**Files:**
- Create: `task-recommender/app/chains/planner.py`
- Create: `task-recommender/tests/test_chain_planner.py`

**Interfaces:**
- `plan_chain(chain: TaskChain, service: RecommendationService, top_n_per_node: int = 3) -> ChainPlan`
- `ChainPlan` fields: `plan_id, chain_id, score, nodes: list[ChainPlanNode], blocked: list[str]`.
- `ChainPlanNode` fields: `subtask_id, worker_id: str | None, rank: int, node_score: float`.
- `propagate_breach(chain: TaskChain, failed_node_key: str, delay_hours: float) -> BreachImpact` computes downstream affected nodes, critical-path delay, slack, severity, and whether replanning is required.

Planning rules:
- Process nodes in topological order.
- For each node, construct a temporary `Task` from `SubTask` (`task_id=subtask_id`, `category` from the root task, `required_skills`, `estimated_hours`, `deadline` from the chain).
- Call `service.recommend_workers_for_task(task, top_n=top_n_per_node)`.
- Skip a candidate if assigning this node would exceed the worker's capacity across the chain (track `assigned_hours[worker_id]`).
- Choose the top remaining candidate; if none, add the node key to `blocked` and leave `worker_id=None`.
- `score` = mean node score of assigned nodes minus `0.05 * handoffs` (count adjacent dependent nodes assigned to different workers).

Breach propagation rules (Phase 1, calculation only — no automatic replanning):
- `affected_nodes` = all descendants of the failed node in the DAG.
- `critical_path_delay` = `delay_hours` if the failed node is on the critical path, else 0.
- `chain_slack` = project finish slack from `compute_slack`.
- `severity = max(0.0, critical_path_delay - chain_slack) / max(chain_slack, 1.0)`.
- `requires_replan = severity > 0 or failed_node_key in critical_path`.

- [ ] **Step 1: Write the failing tests**

```python
from app.chains.decompose import decompose
from app.chains.planner import plan_chain
from app.data.templates import load_templates
from app.service import RecommendationService


def test_plan_covers_all_nodes_and_respects_dependencies(software_task, small_store):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    plan = plan_chain(draft.chain, RecommendationService(small_store))
    assigned = {n.subtask_id: n.worker_id for n in plan.nodes}
    assert len(assigned) == len(draft.chain.nodes)
    assert all(w is not None for w in assigned.values())


def test_blocked_node_when_no_eligible_worker(software_task, small_store):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    small_store.workers.clear()
    plan = plan_chain(draft.chain, RecommendationService(small_store))
    assert plan.blocked
    assert any(n.worker_id is None for n in plan.nodes)


def test_breach_propagation_on_critical_path(software_task, small_store):
    from app.chains.planner import propagate_breach
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    failed_key = draft.chain.critical_path[1]
    impact = propagate_breach(draft.chain, failed_key, delay_hours=4.0)
    assert impact.failed_node == failed_key
    assert impact.affected_nodes
    assert impact.critical_path_delay == 4.0
    assert impact.requires_replan
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_chain_planner.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement planner**

Use `topological_order` from `app.chains.dag`. For capacity tracking, start with each worker's `current_load_hours` and add assigned node hours. Build reasons from the candidate breakdown for the plan response. Implement `propagate_breach` by reverse-reachability from the failed node; use `critical_path` and `compute_slack` for the delay and severity fields.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_chain_planner.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 10: Chain API Endpoints

**Files:**
- Modify: `task-recommender/app/main.py`
- Modify: `task-recommender/app/schemas.py`
- Modify: `task-recommender/tests/test_api.py`

**Interfaces:**
- `POST /chains/decompose` body `{task_id, mode="template", variant="standard"}` → `{draft_id, chain_id, quality, nodes, critical_path}`.
- `GET /chains/{chain_id}` → chain detail with nodes and edges.
- `POST /chains/{chain_id}/plan` → `{plan_id, chain_id, score, nodes, blocked}`.
- `POST /chains/{chain_id}/nodes/{node_id}/recommend` body `{top_n}` → candidates for that node.
- Missing chain/node → 404; unknown template category → 422 with a clear message.

- [ ] **Step 1: Write the failing test**

```python
def test_chain_api_flow(client):
    decompose = client.post("/chains/decompose", json={"task_id": "t1", "mode": "template"})
    assert decompose.status_code == 200
    body = decompose.json()
    assert body["nodes"]
    assert body["critical_path"]
    chain_id = body["chain_id"]

    detail = client.get(f"/chains/{chain_id}")
    assert detail.status_code == 200

    plan = client.post(f"/chains/{chain_id}/plan")
    assert plan.status_code == 200
    assert len(plan.json()["nodes"]) == len(body["nodes"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_api.py::test_chain_api_flow -v`
Expected: FAIL with 404/405 or missing route.

- [ ] **Step 3: Implement endpoints and schemas**

Store drafts and chains in `app.state.chains` keyed by `chain_id`. In this task, `create_app` must load templates from `data/chain_templates/common_task_chains.json`; if the file is missing, raise `RuntimeError` with a clear message. Use `app.state.store` for the dataset. Earlier tasks leave `app.state.templates = {}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 11: Offline Metrics and Evaluation Script

**Files:**
- Create: `task-recommender/app/metrics.py`
- Create: `task-recommender/scripts/evaluate.py`
- Create: `task-recommender/tests/test_metrics.py`

**Interfaces:**
- `hr_at_k(recommended: list[str], relevant: set[str], k: int) -> float`
- `ndcg_at_k(recommended: list[str], relevance: dict[str, float], k: int) -> float`
- `evaluate_recommender(store: Store, service: RecommendationService, k: int = 10) -> dict[str, float]` returns keys `task_to_workers_hr`, `task_to_workers_ndcg`, `worker_to_tasks_hr`, `worker_to_tasks_ndcg`.
- `evaluate_chains(store: Store, templates: dict[str, dict], n_samples: int = 50) -> dict[str, float]` returns keys `decompose_success_rate`, `mean_coverage`, `mean_quality`, `mean_plan_coverage`, `acyclic_rate`.
- `scripts/evaluate.py` prints JSON and writes `reports/phase1_metrics.json`.

Evaluation protocol:
- Use `store.test` assignments only.
- Task→workers: for each test assignment, relevant set is the assigned worker; call `service.recommend_workers(task_id, k)`.
- Worker→tasks: for each test assignment, relevant set is the assigned task; call `service.recommend_tasks(worker_id, k)`.
- Skip test items whose task/worker is missing from the store.

- [ ] **Step 1: Write the failing tests**

```python
from app.metrics import hr_at_k, ndcg_at_k


def test_hr_at_k_boundaries():
    assert hr_at_k(["a", "b"], {"b"}, 1) == 0.0
    assert hr_at_k(["a", "b"], {"b"}, 2) == 1.0
    assert hr_at_k([], {"b"}, 10) == 0.0


def test_ndcg_at_k_perfect_and_zero():
    assert ndcg_at_k(["a"], {"a": 1.0}, 10) == 1.0
    assert ndcg_at_k([], {"a": 1.0}, 10) == 0.0


def test_evaluate_chains_returns_bounded_metrics(small_store):
    from app.data.templates import load_templates
    from app.metrics import evaluate_chains
    templates = load_templates("data/chain_templates/common_task_chains.json")
    metrics = evaluate_chains(small_store, templates, n_samples=5)
    assert metrics["acyclic_rate"] == 1.0
    assert 0.0 <= metrics["mean_quality"] <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_metrics.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement metrics and script**

`hr_at_k` = `1.0` if any of the first `k` is relevant, else `0.0`. `ndcg_at_k` uses `relevance.get(item_id, 0.0)` as gain, `DCG = sum(gain / log2(i+2))`, `IDCG` from the ideal ordering of relevance values; return `0.0` when `IDCG == 0`. `evaluate_chains` loops up to `n_samples` tasks with a matching template, decomposes, scores quality, plans, and averages coverage/quality/plan coverage; any decomposition exception counts as a failure. The script builds the dataset from `generate_dataset`, a `Store`, and `RecommendationService`, then prints and writes JSON including both recommender and chain metrics.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Run evaluation**

Run: `cd task-recommender && python scripts/evaluate.py`
Expected: prints a JSON object with the four recommender metrics plus `decompose_success_rate`, `mean_coverage`, `mean_quality`, `mean_plan_coverage`, `acyclic_rate`; writes `reports/phase1_metrics.json`.

- [ ] **Step 6: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 12: README, Demo Script, and Final Verification

**Files:**
- Create: `task-recommender/README.md`
- Create: `task-recommender/scripts/run_demo.py`
- Create: `task-recommender/tests/test_smoke.py`

**Interfaces:**
- `scripts/run_demo.py` starts uvicorn at `127.0.0.1:8000` using `app.main:create_app` via factory.
- README documents install, run, test, endpoints, and Phase 1 limitations.

- [ ] **Step 1: Write the smoke test**

```python
def test_smoke_flow(client):
    assert client.get("/health").status_code == 200
    assert client.get("/workers").status_code == 200
    assert client.get("/tasks").status_code == 200
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 3})
    assert response.status_code == 200
```

- [ ] **Step 2: Run smoke test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_smoke.py -v`
Expected: FAIL if any route or fixture is missing.

- [ ] **Step 3: Write README and demo script**

README sections: 项目简介、Phase 1 范围、安装、运行、测试、API 示例（curl）、任务链模板、Phase 2/3 未实现项。Demo script: `uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)`.

- [ ] **Step 4: Run full verification**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

Run: `cd task-recommender && python scripts/evaluate.py`
Expected: JSON metrics printed and `reports/phase1_metrics.json` written.

Run: `cd task-recommender && python scripts/run_demo.py` (in a separate terminal)
Then: `curl http://127.0.0.1:8000/health`
Expected: `{"status":"ok","version":"0.1.0"}`.
Stop the server after verification.

- [ ] **Step 5: Final checkpoint**

Confirm:
- `pytest` exits 0.
- `reports/phase1_metrics.json` exists.
- `/health`, `/recommend/workers`, `/recommend/tasks`, `/chains/decompose`, `/chains/{id}/plan` all respond.
- No hard-constraint violations in tests.
- Plan and spec are consistent on file paths and interfaces.

Do not commit (workspace is not a git repo).
