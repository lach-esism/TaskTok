# Task Assignment Recommender — Phase 3 Implementation Plan (No LLM)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the non-LLM roadmap: multi-template composition, Beam Search and MILP chain planning, automatic replanning with plan versions/rollback, and the Phase 2 governance/cleanup items.

**Architecture:** Extend the existing `app/chains/` package with composition, beam/MILP planners, a plan-version store, and replanning. Harden Phase 2 services (feedback validation, weight store, projection, ItemCF). No LLM calls or LLM dependencies are added.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, numpy, scipy (`scipy.optimize.milp`), pytest.

**Spec:** `specs/2026-11-13-task-assignment-recommender-design.md`

## Global Constraints

- **No LLM**: do not add an LLM client, prompt, token accounting, or LLM-based decomposition.
- Work only inside `task-recommender/`.
- No new heavy dependencies; `scipy` is already available.
- Every chain plan must satisfy hard constraints (skills, capacity, dependencies, breach tier).
- MILP is limited to `<= 20` nodes and falls back to Beam Search on failure or when scipy is unavailable.
- Plan versions are immutable; rollback only changes the active pointer.
- The workspace is not a git repository: do not run `git commit`; end tasks with test checkpoints.
- All API-facing text added in Phase 3 is Chinese.

## Review Focus

1. **Composition DAG**: composing multiple templates must dedupe shared roots/sinks and keep a valid acyclic DAG.
2. **Planner feasibility**: Beam/MILP plans must never violate dependencies, capacity, skills, or breach exclusion.
3. **Replanning isolation**: replanning must lock completed/in-progress nodes and never rewrite their worker assignments; rollback restores the exact prior plan.
4. **Feedback validation**: duplicate task+worker assignment → 409; malformed recommendation context → 422, not 500.
5. **Weight store integrity**: invalid simplex/floors are rejected; writes are atomic; projection is idempotent and preserves the reputation-largest rule.

---

## Task 1: Phase 2 Cleanup A — Feedback, Reputation, Preferences

**Files:**
- Modify: `app/feedback.py`
- Modify: `app/main.py`
- Modify: `app/schemas.py`
- Modify: `app/personalization/user_weights.py`
- Modify: `app/features.py` (category_ratings use)
- Create/modify tests: `tests/test_feedback.py`, `tests/test_personalization_weights.py`

**Interfaces:**
- `RecommendationContext(BaseModel)`: `score: float = 0.0`, `rank: int = 0`, `propensity: float = Field(1.0, ge=0, le=1)`, `weights_version: str = "v0000"`.
- `CreateAssignmentRequest.recommendation_context: RecommendationContext | None`.
- `FeedbackService.record_assignment` raises `ValueError("task already assigned to worker")` for a duplicate task+worker pair; `main` maps to 409.
- `FeedbackService.record_feedback` appends the rating to `worker.category_ratings[task.category]`.
- `FeedbackService.reputation` returns `rating` = Bayesian normalized rating (0–1), `status` = `active`/`warning`/`excluded`.
- `PersonalizationService.weights_for` source is one of `profile`, `segment`, `global`; use `segment` when segment weights exist and profile completeness ≥ 0.6.

- [ ] **Step 1: Write failing tests**

```python
def test_duplicate_assignment_returns_409(client):
    first = client.post("/assignments", json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1"})
    assert first.status_code == 200
    second = client.post("/assignments", json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1"})
    assert second.status_code == 409


def test_bad_recommendation_context_returns_422(client):
    response = client.post(
        "/assignments",
        json={"task_id": "t1", "worker_id": "w_good", "customer_id": "c1", "recommendation_context": {"score": "bad"}},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_feedback.py -v`
Expected: duplicate assignment returns 200 / bad context raises 500.

- [ ] **Step 3: Implement the validation and reputation changes**

Use the Pydantic `RecommendationContext`; `record_assignment` checks existing assignments; `record_feedback` updates `category_ratings`; `reputation` uses `compute_reputation(...).rating` normalized and status. Set `source="segment"` in `weights_for` when `initial_weights` used segment weights.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_feedback.py tests/test_personalization_weights.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 2: Phase 2 Cleanup B — Weight Store, Projection, ItemCF

**Files:**
- Modify: `app/versioning.py`
- Modify: `app/learning/weights.py`
- Modify: `app/service.py`
- Create/modify tests: `tests/test_weight_math.py`, `tests/test_versioning.py`, `tests/test_recommend.py`

**Interfaces:**
- `validate_weights(weights: dict[str,float]) -> None` raises `ValueError` unless sum is 1 ± 1e-6, reputation in `[0.25,0.40]`, skill+expertise ≥ 0.25, every weight ≥ 0.02.
- `WeightStore.create` calls `validate_weights`; writes to a temporary file then `os.replace`.
- `project_weights` becomes idempotent (`project_weights(project_weights(x)) ≈ project_weights(x)`) and keeps reputation `>=` every other dimension.
- `_build_itemcf(store)` only uses feedback whose `assignment_id` is in `store.assignments`.

- [ ] **Step 1: Write failing tests**

```python
def test_invalid_weights_are_rejected(tmp_path):
    from app.versioning import WeightStore
    store = WeightStore(tmp_path, prior={"reputation": 0.32, "skill": 0.68})
    with pytest.raises(ValueError):
        store.create({"reputation": 0.10, "skill": 0.90}, 1, "bad")


def test_projection_is_idempotent():
    from app.learning.weights import project_weights
    once = project_weights({"reputation": 0.01, "skill": 0.8, "expertise": 0.01, "collaborative": 0.1, "preference": 0.03, "load": 0.03, "customer_preference": 0.02})
    twice = project_weights(once)
    assert twice == pytest.approx(once, abs=1e-9)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_weight_math.py tests/test_versioning.py -v`
Expected: invalid weights accepted / projection drift.

- [ ] **Step 3: Implement validation, atomic writes, idempotent projection, ItemCF filter**

Use `tempfile.NamedTemporaryFile(delete=False)` + `os.replace`. For projection idempotence, apply the allocation to normalized inputs and round-trip until stable; cap every non-reputation dimension at `max(reputation, 0.02)` and redistribute excess to the smallest dimensions. Filter `rated_pairs` by assignment IDs in `store.assignments`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_weight_math.py tests/test_versioning.py tests/test_recommend.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 3: Shared Latent Module, Ground-Truth Script, Test Isolation

**Files:**
- Create: `app/data/latent.py`
- Modify: `app/data/ground_truth.py`
- Modify: `app/data/synthetic.py`
- Create: `scripts/build_ground_truth.py`
- Modify: `tests/conftest.py` (client uses `tmp_path`)
- Create/modify tests: `tests/test_ground_truth.py`

**Interfaces:**
- `true_weight_simplex(rng: random.Random) -> dict[str,float]` lives in `app/data/latent.py`; `ground_truth.py` re-exports it for compatibility.
- `scripts/build_ground_truth.py` generates a dataset and writes `data/ground_truth.csv`.
- `client` fixture: `TestClient(create_app(small_store, weights_dir=tmp_path))`.

- [ ] **Step 1: Write failing tests**

```python
def test_ground_truth_script_creates_artifact():
    from app.data.ground_truth import build_ground_truth
    from app.data.synthetic import generate_dataset
    dataset = generate_dataset(n_workers=10, n_tasks=12, n_assignments=50, n_new_users=0)
    path = build_ground_truth(dataset, Path("data") / "ground_truth_test.csv")
    assert path.exists()
    path.unlink()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ground_truth.py -v`
Expected: import/path failure.

- [ ] **Step 3: Implement the shared module and script**

Move `true_weight_simplex`; update imports; update `conftest.client` to use `tmp_path`; add the script.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ground_truth.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 4: Multi-Template Composition

**Files:**
- Create: `app/chains/compose.py`
- Create: `tests/test_composition.py`

**Interfaces:**
- `compose_templates(task: Task, templates: dict[str,dict], categories: list[str], max_nodes: int = 15) -> dict`
- Composition rules:
  - Merge template nodes; shared keys `requirements`, `review`, `delivery` appear once.
  - Other node keys are prefixed with the category (`f"{category}:{key}"`).
  - Each template's root nodes depend on the shared `requirements` node (create it if absent).
  - Each template's leaf nodes feed the shared `delivery` node (create it if absent).
  - Preserve acceptance/skills; merge duplicates; validate DAG.
  - `template_id = "composed_" + "_".join(sorted(categories))`; `category = task.category`.

- [ ] **Step 1: Write the failing test**

```python
def test_compose_software_and_content_is_acyclic():
    from app.chains.compose import compose_templates
    from app.data.templates import load_templates
    templates = load_templates("data/chain_templates/common_task_chains.json")
    composed = compose_templates(
        software_task, templates, ["software_dev", "content_writing"]
    )
    keys = [node["key"] for node in composed["nodes"]]
    assert len(keys) == len(set(keys))
    assert "requirements" in keys
    assert "delivery" in keys
    assert any(node["key"] == "software_dev:testing" for node in composed["nodes"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_composition.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement composition and DAG validation**

Use the existing `load_templates` output; build nodes/edges; call `validate_dag` on the composed `SubTask` view (or a shared raw validator).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_composition.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 5: Compose Mode in Decompose/API

**Files:**
- Modify: `app/chains/decompose.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- `DecomposeRequest.categories: list[str] | None`
- `decompose(..., template: dict, ...)` unchanged; add `compose_templates` usage in the `/chains/decompose` endpoint when `mode == "compose"`.
- Unknown category → 422 with a Chinese message.

- [ ] **Step 1: Write the failing test**

```python
def test_compose_mode_api(client):
    response = client.post(
        "/chains/decompose",
        json={"task_id": "t1", "mode": "compose", "categories": ["software_dev", "content_writing"]},
    )
    assert response.status_code == 200
    assert response.json()["nodes"]
    assert response.json()["critical_path"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_compose_mode_api -v`
Expected: 200 with only one template or 422.

- [ ] **Step 3: Implement compose mode**

In the decompose endpoint, when `mode == "compose"`, resolve the category templates and call `compose_templates`; catch unknown categories and `ValueError` → 422.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 6: Beam Search Planner

**Files:**
- Modify: `app/chains/planner.py`
- Create: `tests/test_beam_planner.py`

**Interfaces:**
- `plan_chain_beam(chain: TaskChain, service: RecommendationService, beam_width: int = 5, top_n_per_node: int = 3) -> ChainPlan`
- Process nodes in topological order; each beam state tracks assigned workers, hours per worker, score, handoffs; expand each ready node with top candidates; keep the best `beam_width` by partial score; return the best complete state.
- Respect dependencies, eligibility, capacity; blocked nodes remain `None`.

- [ ] **Step 1: Write the failing test**

```python
def test_beam_plan_covers_nodes_and_respects_capacity(software_task, small_store):
    from app.chains.compose import compose_templates  # or load_templates
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain_beam
    from app.data.templates import load_templates
    from app.service import RecommendationService
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    plan = plan_chain_beam(draft.chain, RecommendationService(small_store), beam_width=3)
    assert len(plan.nodes) == len(draft.chain.nodes)
    assert all(node.worker_id is not None for node in plan.nodes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_beam_planner.py -v`
Expected: FAIL with missing function.

- [ ] **Step 3: Implement Beam Search**

Reuse planner candidate scoring; state is a dict `node_key -> worker_id`; track cumulative hours per worker; partial score = sum node scores - 0.05 * handoffs; prune to beam width.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_beam_planner.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 7: MILP Planner

**Files:**
- Modify: `app/chains/planner.py`
- Create: `tests/test_milp_planner.py`

**Interfaces:**
- `plan_chain_milp(chain: TaskChain, service: RecommendationService, max_nodes: int = 20) -> ChainPlan`
- Binary `x[node, worker]` for eligible pairs; constraints: each node exactly one worker; per-worker total hours ≤ remaining capacity; objective maximize Σ `alpha_node * node_score * x`; use `scipy.optimize.milp` with `LinearConstraint`, `Bounds`, `integrality=1`.
- If scipy is unavailable, nodes > `max_nodes`, or the solver fails, fall back to `plan_chain_beam`.

- [ ] **Step 1: Write the failing test**

```python
def test_milp_plan_is_feasible(software_task, small_store):
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain_milp
    from app.data.templates import load_templates
    from app.service import RecommendationService
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    plan = plan_chain_milp(draft.chain, RecommendationService(small_store))
    assert len(plan.nodes) == len(draft.chain.nodes)
    assert all(node.worker_id is not None for node in plan.nodes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_milp_planner.py -v`
Expected: FAIL with missing function.

- [ ] **Step 3: Implement MILP**

Precompute candidate scores via `service.recommend_workers_for_task` for each node; build the constraint matrix; solve; map variables back to workers; mark blocked if no eligible candidate.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_milp_planner.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 8: Plan Version Store and Rollback

**Files:**
- Create: `app/chains/plan_store.py`
- Modify: `app/main.py`
- Create: `tests/test_plan_store.py`

**Interfaces:**
- `ChainPlanStore`: `save(plan) -> int`, `active(chain_id) -> ChainPlan`, `rollback(chain_id, version: int) -> ChainPlan`, `versions(chain_id) -> list[ChainPlan]`.
- Plan versions are integers starting at 1; rollback only changes the active pointer.
- API: `GET /chains/{id}/plans`, `POST /chains/{id}/plan/rollback` body `{version: int}`.

- [ ] **Step 1: Write the failing test**

```python
def test_plan_store_versions_and_rollback():
    from app.chains.plan_store import ChainPlanStore
    from app.domain import ChainPlan
    store = ChainPlanStore()
    first = ChainPlan(plan_id="p1", chain_id="c1", score=0.5, nodes=[])
    second = ChainPlan(plan_id="p2", chain_id="c1", score=0.7, nodes=[])
    assert store.save(first) == 1
    assert store.save(second) == 2
    assert store.active("c1").plan_id == "p2"
    assert store.rollback("c1", 1).plan_id == "p1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plan_store.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement the store and API**

Keep versions in memory keyed by chain_id; active index; API serializes `asdict(plan)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_store.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 9: Automatic Replanning

**Files:**
- Modify: `app/chains/planner.py`
- Modify: `app/main.py`
- Modify: `app/schemas.py`
- Create: `tests/test_replanning.py`

**Interfaces:**
- `replan_chain(chain: TaskChain, service: RecommendationService, failed_node_key: str, delay_hours: float, locked_nodes: set[str], beam_width: int = 5) -> ChainPlan`
- Call `propagate_breach`; lock completed/in-progress node workers by copying their assignments; replan only unlocked nodes; save a new plan version; return the new plan with `blocked`/`replanned` metadata.
- API: `POST /chains/{id}/replan` body `{failed_node: str, delay_hours: float, locked_nodes: list[str]}`.

- [ ] **Step 1: Write the failing test**

```python
def test_replan_locks_completed_nodes_and_versions_plan(software_task, small_store):
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain, replan_chain
    from app.data.templates import load_templates
    from app.service import RecommendationService
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    service = RecommendationService(small_store)
    plan = plan_chain(draft.chain, service)
    locked = {draft.chain.nodes[0].key}
    replanned = replan_chain(
        draft.chain, service, draft.chain.critical_path[1], 4.0, locked
    )
    assert replanned.plan_id != plan.plan_id
    first_original = next(n for n in plan.nodes if n.subtask_id == draft.chain.nodes[0].subtask_id)
    first_replanned = next(n for n in replanned.nodes if n.subtask_id == draft.chain.nodes[0].subtask_id)
    assert first_replanned.worker_id == first_original.worker_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replanning.py -v`
Expected: FAIL with missing function.

- [ ] **Step 3: Implement replanning**

Compute affected nodes; preserve locked assignments; rerun Beam/greedy on unlocked nodes; save a new plan in `ChainPlanStore`; expose via API.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_replanning.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 10: Chain Evaluation and Reports

**Files:**
- Modify: `app/metrics.py` or create `app/evaluation_chains.py`
- Create: `scripts/evaluate_chains.py`
- Create: `tests/test_chain_evaluation.py`

**Interfaces:**
- `evaluate_planners(store, templates, planner_names=("greedy","beam","milp"), n_samples=30) -> dict[str, dict[str,float]]`
  - keys per planner: `plan_coverage`, `blocked_rate`, `mean_node_score`, `handoff_count`, `acyclic_rate`.
- Script writes `reports/phase3_chain_metrics.json` and `reports/phase3_chain_metrics.md`.

- [ ] **Step 1: Write the failing test**

```python
def test_evaluate_planners_returns_metrics(small_store):
    from app.data.templates import load_templates
    from app.evaluation_chains import evaluate_planners
    templates = load_templates("data/chain_templates/common_task_chains.json")
    metrics = evaluate_planners(small_store, templates, n_samples=3)
    assert "greedy" in metrics and "beam" in metrics
    assert 0.0 <= metrics["greedy"]["plan_coverage"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chain_evaluation.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement evaluation and script**

Reuse decompose/quality/planners; aggregate metrics; write reports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chain_evaluation.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 11: Metrics Compare Params and Learning-Curve Cohort

**Files:**
- Modify: `app/main.py`
- Modify: `scripts/evaluate_phase2.py`
- Create/modify tests: `tests/test_phase2_api.py`, `tests/test_evaluation_phase2.py`

**Interfaces:**
- `GET /metrics/compare?run_a=v0000&run_b=v0001` returns `{run_a, run_b, metrics}` computed from the weight versions; absent versions → 404.
- `learning_curve` script uses up to 200 new users (configurable) and reports mean ± standard deviation over 3 seeds for weight cosine; write `phase2_learning_curve.md` with the cohort size and seed count.

- [ ] **Step 1: Write the failing test**

```python
def test_metrics_compare_rejects_unknown_version(client):
    response = client.get("/metrics/compare?run_a=v0000&run_b=v9999")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_api.py::test_metrics_compare_rejects_unknown_version -v`
Expected: 200 with file contents.

- [ ] **Step 3: Implement the params and cohort report**

Resolve versions through `WeightStore`; compute two-run metrics with the existing evaluation function; catch unknown versions. Update the script to use `n_users=200` and 3 seeds for cosine aggregation.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_phase2_api.py tests/test_evaluation_phase2.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 12: README, Docs, and Final Verification

**Files:**
- Modify: `task-recommender/README.md`
- Create: `plans/2026-11-13-task-recommender-phase3.md` (this file)
- Create: `reports/phase3_chain_metrics.json`, `reports/phase3_chain_metrics.md`

- [ ] **Step 1: Update README**

Add Phase 3 section: composition, Beam/MILP, replanning, plan rollback, Phase 2 cleanup; remove any claim that LLM is implemented; document `scripts/evaluate_chains.py`.

- [ ] **Step 2: Run full verification**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

Run: `python scripts/evaluate_phase2.py`
Expected: Phase 2 reports regenerated.

Run: `python scripts/evaluate_chains.py`
Expected: Phase 3 chain reports written.

Run: `PORT=8016 python scripts/run_demo.py`
Then: `curl http://127.0.0.1:8016/health`
Expected: `{"status":"ok","version":"0.3.0"}`.

- [ ] **Step 3: Final checkpoint**

Confirm:
- `pytest` exits 0.
- `reports/phase3_chain_metrics.json` exists.
- Compose mode, beam/MILP plan, replan, and plan rollback endpoints respond.
- Duplicate assignment → 409; bad recommendation context → 422.
- No LLM import or prompt exists: `grep -R "openai\|anthropic\|llm" app scripts` returns no LLM client usage.
- No commit (workspace is not a git repo).
