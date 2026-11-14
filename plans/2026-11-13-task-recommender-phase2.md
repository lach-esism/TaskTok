# Task Assignment Recommender — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 1 static MVP into a feedback-driven, per-user personalized recommender: customer ratings update reputation and weights, new users start from profile-derived weights, and every recommendation can be rolled back to a known version.

**Architecture:** Extend the existing FastAPI service with a feedback service, a JSON-backed weight-version store, a three-level personalization layer (global → segment → individual), and a ground-truth evaluation layer. Phase 1's `RecommendationService` keeps its hard constraints and seven-dimension scoring; Phase 2 injects user-specific weights and learns them from feedback.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, numpy, pandas, scikit-learn, pytest, httpx.

**Spec:** `specs/2026-11-13-task-assignment-recommender-design.md`

## Global Constraints

- Work only inside `task-recommender/`.
- Use the existing dependencies; no new heavy packages.
- Every weight vector is a simplex (`w_j >= 0`, `sum(w) = 1`) and must satisfy the spec floors:
  `w_reputation ∈ [0.25, 0.40]`, `w_skill + w_expertise >= 0.25`, `w_j >= 0.02`.
- Deterministic behavior: default seed `42`; no wall-clock dependence in data or weights.
- The workspace is **not a git repository**: do not run `git commit`. Each task ends with a test checkpoint.
- Phase 2 scope only: feedback, dynamic global weights, personalization, learning curve, rollback, ground truth. **Not** LLM decomposition, multi-template composition, Beam Search/MILP, automatic replanning, or frontend/DB/auth.
- Ground truth files are evaluation-only. No feature, learner, or API path may read them.
- API-facing text should be Chinese where the plan specifies it; existing English strings are not in scope to refactor.

## Review Focus

1. **Duplicate/unknown feedback**: unknown assignment → 404; duplicate feedback → 409; reputation must not be updated twice.
2. **Rollback determinism**: after `POST /weights/rollback` to `v0000`, the same query must return the baseline Top-N and `/weights` must report `v0000`.
3. **Cold-start user**: a user with no profile history must fall back to global weights, never crash, and never return a non-simplex weight vector.
4. **Weight floors after learning**: online updates and batch refits must preserve reputation `[0.25, 0.40]`, skill+expertise `>= 0.25`, and every weight `>= 0.02`.
5. **Ground-truth isolation**: `ground_truth.csv` must never be read by feature code, learners, or recommendation endpoints; only evaluation scripts may read it.

---

## Task 1: Feedback Loop and Reputation Updates

**Files:**
- Modify: `task-recommender/app/domain.py` (extend `Feedback`, `Assignment`; add `LearningEvent`)
- Create: `task-recommender/app/feedback.py`
- Modify: `task-recommender/app/schemas.py`
- Modify: `task-recommender/app/main.py`
- Create: `task-recommender/tests/test_feedback.py`

**Interfaces:**
- Extend `Feedback` with `quality_rating: int | None = None`, `timeliness_rating: int | None = None`, `communication_rating: int | None = None`, `comment: str = ""`, `propensity: float = 1.0`.
- Extend `Assignment` with `recommended_at: datetime | None = None`, `recommendation_score: float = 0.0`, `recommendation_rank: int = 0`, `propensity: float = 1.0`, `weights_version: str = "v0000"`.
- `FeedbackService(store: Store, persist_dir: Path | None = None)`
  - `record_assignment(task_id: str, worker_id: str, customer_id: str, recommendation_context: dict | None = None) -> Assignment`
  - `record_feedback(assignment_id: str, overall_rating: int, quality_rating: int | None = None, timeliness_rating: int | None = None, communication_rating: int | None = None, comment: str = "") -> Feedback`
  - `reputation(worker_id: str) -> dict[str, float | int | str]`
- API: `POST /assignments`, `POST /feedback`, `GET /workers/{id}/reputation`.
- Persistence: when `persist_dir` is set, append JSON Lines to `assignments.jsonl` and `feedback.jsonl`.

- [ ] **Step 1: Write the failing tests**

```python
def test_record_feedback_updates_worker_rating_once(small_store):
    from app.feedback import FeedbackService

    service = FeedbackService(small_store)
    assignment = service.record_assignment("t1", "w_good", "c1")
    first = service.record_feedback(assignment.assignment_id, 5, quality_rating=5)
    assert first.overall_rating == 5
    assert small_store.workers["w_good"].ratings[-1] == 5.0
    with pytest.raises(ValueError):
        service.record_feedback(assignment.assignment_id, 4)
    assert len(small_store.workers["w_good"].ratings) == 3


def test_unknown_assignment_feedback_raises_keyerror(small_store):
    from app.feedback import FeedbackService

    with pytest.raises(KeyError):
        FeedbackService(small_store).record_feedback("missing", 5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_feedback.py -v`
Expected: FAIL with missing `app.feedback`.

- [ ] **Step 3: Implement feedback service and endpoints**

`record_assignment` creates an `Assignment` with status `assigned`, appends it to the store, and returns it. `record_feedback` looks up the assignment, rejects duplicates, appends a `Feedback`, appends the rating to the worker, and marks the assignment `completed`. Add the three API routes with 404 for unknown IDs and 409 for duplicate feedback. `reputation` returns the current Bayesian rating, completion count, on-time count, recent breach count, and status.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_feedback.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass. Do not commit.

---

## Task 2: Reputation Breakdown and Category Shrinkage

**Files:**
- Create: `task-recommender/app/reputation.py`
- Modify: `task-recommender/app/features.py` (delegate reputation to the new module)
- Create: `task-recommender/tests/test_reputation.py`

**Interfaces:**
- `ReputationBreakdown` dataclass: `rating: float, completion: float, on_time: float, rework: float, breach_penalty: float, total: float, recent_breaches: int, warning: bool, excluded: bool`.
- `compute_reputation(worker: Worker, now: datetime | None = None) -> ReputationBreakdown`
- `category_reputation(worker: Worker, category: str, m: int = 10) -> float`
- `features.reputation_score(worker, category=None, now=None)` delegates to `compute_reputation(...).total` (signature unchanged).

Rules:
- Bayesian rating `(sum(ratings) + 10*4.2) / (len(ratings) + 10) / 5`.
- One recent breach → `warning=True`, penalty `0.5`; two or more → `excluded=True`, penalty `0.0`.
- Category reputation: if the worker has no category evidence, return the global total; otherwise shrink the category mean toward the global total with `n/(n+m)`.

- [ ] **Step 1: Write the failing test**

```python
def test_one_recent_breach_is_warning_not_excluded(small_store):
    from app.reputation import compute_reputation

    worker = small_store.workers["w_breach"]
    breakdown = compute_reputation(worker, now=small_store.reference_time)
    assert breakdown.recent_breaches == 2
    assert breakdown.excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_reputation.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement reputation module**

Extract the Phase 1 reputation formula into `app/reputation.py`, add `warning`/`excluded`, and make `features.reputation_score` delegate. Use `_recent_breach_count` logic with the data-relative `now`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_reputation.py tests/test_features.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 3: Weight Version Store, Diff, and Rollback

**Files:**
- Create: `task-recommender/app/versioning.py`
- Create: `task-recommender/tests/test_versioning.py`
- Modify: `task-recommender/app/main.py`
- Modify: `task-recommender/app/schemas.py`
- Data: `task-recommender/data/weights/`

**Interfaces:**
- `WeightStore(directory: Path, prior: dict[str, float])`
  - `create(weights: dict[str, float], sample_count: int, source: str, metrics: dict | None = None) -> WeightVersion`
  - `active() -> WeightVersion`
  - `rollback(to_version: str, reason: str = "") -> WeightVersion`
  - `diff(from_version: str, to_version: str) -> dict[str, dict[str, float]]`
  - `changelog() -> list[dict]`
- `WeightVersion` dataclass: `version, weights, prior, sample_count, source, metrics, updated_at`.
- Files: `active.json` stores `{"active_version": "v0000"}`; each version is `weights_vNNNN.json`.
- API: `GET /weights`, `GET /weights/diff?from=v0000&to=v0001`, `POST /weights/rollback`, `GET /learning/changelog`.

- [ ] **Step 1: Write the failing tests**

```python
def test_weight_store_creates_and_rolls_back(tmp_path):
    from app.versioning import WeightStore

    store = WeightStore(tmp_path, prior={"reputation": 0.32, "skill": 0.68})
    first = store.create({"reputation": 0.32, "skill": 0.68}, 0, "prior")
    second = store.create({"reputation": 0.34, "skill": 0.66}, 10, "online")
    assert store.active().version == second.version
    rolled = store.rollback(first.version, "test")
    assert rolled.version == first.version
    assert store.active().version == first.version
    assert store.diff(first.version, second.version)["reputation"]["delta"] == pytest.approx(0.02)


def test_rollback_restores_exact_baseline_weights(tmp_path):
    from app.versioning import WeightStore

    store = WeightStore(tmp_path, prior={"reputation": 0.32, "skill": 0.68})
    baseline = store.create({"reputation": 0.32, "skill": 0.68}, 0, "prior")
    store.create({"reputation": 0.40, "skill": 0.60}, 20, "online")
    store.rollback(baseline.version, "restore")
    assert store.active().weights == baseline.weights
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_versioning.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement versioning**

Use `json.dump`/`json.loads` with UTF-8. Version IDs are `v0000`, `v0001`, ... Create the prior version on first use. Rollback only switches `active.json`; never deletes versions. Append rollback events to `changelog.jsonl`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_versioning.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 4: AHP Prior, Entropy Weights, and Floors

**Files:**
- Create: `task-recommender/app/learning/__init__.py`
- Create: `task-recommender/app/learning/weights.py`
- Create: `task-recommender/tests/test_weight_math.py`

**Interfaces:**
- `AHP_PRIOR` reuses `DEFAULT_WEIGHTS` from `app.config` (values: reputation `0.32`, skill `0.20`, expertise `0.15`, collaborative `0.13`, preference `0.10`, load `0.06`, customer_preference `0.04`).
- `entropy_weights(rows: list[dict[str, float]]) -> dict[str, float]`
- `combine_weights(prior: dict[str, float], entropy: dict[str, float]) -> dict[str, float]`
- `project_weights(weights: dict[str, float]) -> dict[str, float]` enforces the simplex and spec floors.
- `WEIGHT_FLOORS = {reputation: (0.25, 0.40), skill+expertise: 0.25, each: 0.02}`

Rules:
- Entropy: `p_ij = x_ij / sum_i x_ij`; `e_j = -1/ln(n) * sum_i p_ij ln p_ij`; `delta_j = (1-e_j)/sum_k(1-e_k)`; if a column is all zero, use the mean of the other delta values.
- Combined: `w_j ∝ prior_j * delta_j`, normalized.
- Projection algorithm: normalize → clamp each to `[0.02, 1]` → clamp reputation to `[0.25, 0.40]` → if `skill+expertise < 0.25`, transfer from `load`, then `customer_preference`, then `preference`, then `collaborative` (never below `0.02`) → renormalize → repeat twice → adjust the largest unconstrained dimension so the sum is exactly `1.0`.

- [ ] **Step 1: Write the failing tests**

```python
def test_entropy_and_combine_sum_to_one():
    from app.learning.weights import AHP_PRIOR, combine_weights, entropy_weights

    rows = [
        {"reputation": 0.9, "skill": 0.4, "expertise": 0.2, "collaborative": 0.1, "preference": 0.5, "load": 0.8, "customer_preference": 0.6},
        {"reputation": 0.3, "skill": 0.8, "expertise": 0.7, "collaborative": 0.4, "preference": 0.2, "load": 0.5, "customer_preference": 0.3},
    ]
    entropy = entropy_weights(rows)
    combined = combine_weights(AHP_PRIOR, entropy)
    assert set(combined) == set(AHP_PRIOR)
    assert sum(combined.values()) == pytest.approx(1.0)
```

```python
def test_projection_preserves_floors():
    from app.learning.weights import project_weights

    projected = project_weights({"reputation": 0.01, "skill": 0.40, "expertise": 0.10, "collaborative": 0.20, "preference": 0.10, "load": 0.10, "customer_preference": 0.09})
    assert 0.25 <= projected["reputation"] <= 0.40
    assert projected["skill"] + projected["expertise"] >= 0.25
    assert min(projected.values()) >= 0.02 - 1e-9
    assert sum(projected.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_weight_math.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement weight math**

Use `math.log`; no numpy required. Document the zero-column guard in a docstring. The projection is the only place allowed to change weights outside online learning.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_weight_math.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 5: Online Weight Learning, Shrinkage, and Batch Refit

**Files:**
- Create: `task-recommender/app/learning/online.py`
- Create: `task-recommender/tests/test_online_learning.py`

**Interfaces:**
- `OnlineWeightLearner(prior: dict[str, float], weights: dict[str, float] | None = None, l2_lambda: float = 0.1, learning_rate: float = 0.05)`
  - `update(features: dict[str, float], rating: int) -> dict[str, float]`
  - `batch_fit(records: list[tuple[dict[str, float], int]], epochs: int = 1) -> dict[str, float]`
  - `weights` property returns the current simplex vector.
- `shrink_weights(learned: dict[str, float], prior: dict[str, float], sample_count: int, n0: int = 50) -> dict[str, float]`
- `decay_weight(delta_days: float, tau_days: float = 30.0) -> float`

Rules:
- Label `y=1` when `rating >= 4`, else `0`.
- `p = sigmoid(sum_j w_j * x_j - b)`; use a bias initialized to `0.0`.
- Gradient step on the scoring weights: `w += lr * (y - p) * x`; then L2 pull toward prior; then `project_weights`.
- Batch fit averages gradients over records for `epochs`.
- Shrinkage: `w = n/(n+n0) * learned + n0/(n+n0) * prior`, then project.

- [ ] **Step 1: Write the failing tests**

```python
def test_learning_increases_reputation_weight_when_it_predicts_high_ratings():
    from app.learning.online import OnlineWeightLearner

    prior = {"reputation": 0.25, "skill": 0.20, "expertise": 0.15, "collaborative": 0.13, "preference": 0.10, "load": 0.06, "customer_preference": 0.11}
    learner = OnlineWeightLearner(prior, learning_rate=0.05)
    before = learner.weights["reputation"]
    for _ in range(200):
        learner.update({"reputation": 1.0, "skill": 0.0, "expertise": 0.0, "collaborative": 0.0, "preference": 0.0, "load": 0.0, "customer_preference": 0.0}, 5)
    assert learner.weights["reputation"] > before
    assert sum(learner.weights.values()) == pytest.approx(1.0)
```

```python
def test_shrinkage_returns_prior_for_zero_samples():
    from app.learning.online import shrink_weights

    prior = {"reputation": 0.32, "skill": 0.20, "expertise": 0.15, "collaborative": 0.13, "preference": 0.10, "load": 0.06, "customer_preference": 0.04}
    learned = {"reputation": 0.40, "skill": 0.15, "expertise": 0.15, "collaborative": 0.10, "preference": 0.10, "load": 0.05, "customer_preference": 0.05}
    assert shrink_weights(learned, prior, 0) == pytest.approx(prior)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_online_learning.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement online learner**

Keep the learner pure (no I/O). `update` mutates internal weights and returns a copy. Use `app.learning.weights.project_weights` after every step. The test's expected direction is the only required behavior; do not tune for a specific numeric value.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_online_learning.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 6: Exploration, Propensity, and IPS

**Files:**
- Create: `task-recommender/app/learning/exploration.py`
- Modify: `task-recommender/app/service.py` (add `propensity` to `ScoredCandidate` and log it)
- Modify: `task-recommender/app/schemas.py` (response `propensity`)
- Create: `task-recommender/tests/test_exploration.py`

**Interfaces:**
- `ScoredCandidate` gains `propensity: float = 1.0`.
- `ExplorationPolicy(epsilon: float = 0.10, seed: int = 42)`
  - `rerank(candidates: list[ScoredCandidate], k: int) -> list[ScoredCandidate]`
  - `propensity_for(candidate_id: str) -> float`
- `ips_score(rewards: list[float], propensities: list[float], policy_probs: list[float]) -> float`
- `snips_score(...) -> float`

Rules:
- With probability `epsilon`, replace the last slot with a uniformly chosen candidate not already in the list; log propensity `1/len(candidates)` for explored items and `1-epsilon` for exploited items.
- IPS: `mean(reward * policy_prob / propensity)`; SNIPS: `sum(reward * policy_prob / propensity) / sum(policy_prob / propensity)`.
- Clamp propensities to `[1e-6, 1]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ips_perfect_policy_matches_mean_reward():
    from app.learning.exploration import ips_score

    assert ips_score([1.0, 0.0], [1.0, 1.0], [1.0, 1.0]) == pytest.approx(0.5)


def test_exploration_is_deterministic_with_seed(small_store):
    from app.learning.exploration import ExplorationPolicy
    from app.service import RecommendationService

    candidates = RecommendationService(small_store).recommend_workers("t1", top_n=5)
    first = ExplorationPolicy(seed=42).rerank(candidates, k=5)
    second = ExplorationPolicy(seed=42).rerank(candidates, k=5)
    assert [c.candidate_id for c in first] == [c.candidate_id for c in second]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_exploration.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement exploration and IPS**

Use `random.Random(seed)`. Do not explore when there are fewer than `k+1` candidates or `epsilon == 0`. The service sets `propensity` on returned candidates; API responses include it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_exploration.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 7: User Profiles, Segments, and Initial Weights

**Files:**
- Modify: `task-recommender/app/domain.py` (add `UserProfile`, `Segment`)
- Create: `task-recommender/app/personalization/__init__.py`
- Create: `task-recommender/app/personalization/profile.py`
- Create: `task-recommender/app/personalization/segments.py`
- Create: `task-recommender/tests/test_personalization_profile.py`

**Interfaces:**
- `UserProfile` fields: `user_id, entity_type, role, industry, experience_years, skills, specialties, region, preferred_categories, profile_completeness, segment_id, created_at`.
- `build_profile(user, entity_type: str, declared: dict | None = None) -> UserProfile`
- `profile_completeness(profile: UserProfile) -> float`
- `Segmenter(seed: int = 42)`
  - `fit(profiles: list[UserProfile], weights_by_user: dict[str, dict[str, float]]) -> list[Segment]`
  - `assign(profile: UserProfile) -> str`
  - `segment_weights(segment_id: str) -> dict[str, float]`
- `initial_weights(profile: UserProfile, segmenter: Segmenter, global_weights: dict[str, float]) -> tuple[dict[str, float], str]`

Rules:
- Phase 2 uses deterministic rule-based segments: `f"{role}:{experience_bucket}"`, where bucket is `junior` (<3 years), `mid` (3–7), `senior` (>=7).
- Segment weights are the mean of member weights, shrunk toward global with `n/(n+20)`.
- Initial weights: if `profile_completeness >= 0.6` and the segment has weights, use segment weights; otherwise global. Always `project_weights`.

- [ ] **Step 1: Write the failing test**

```python
def test_segment_and_initial_weights_are_deterministic(small_store):
    from app.learning.weights import AHP_PRIOR
    from app.personalization.profile import build_profile
    from app.personalization.segments import Segmenter, initial_weights

    profile = build_profile(small_store.workers["w_good"], "worker", {"role": "engineer", "industry": "software", "experience_years": 5})
    segmenter = Segmenter()
    segmenter.fit([profile], {"w_good": AHP_PRIOR})
    weights, segment_id = initial_weights(profile, segmenter, AHP_PRIOR)
    assert segment_id == "engineer:mid"
    assert sum(weights.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_personalization_profile.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement profiles and segments**

`build_profile` copies declared fields, defaults `region` from the user, computes completeness as non-empty required fields / total required fields, and assigns a segment. `Segmenter.fit` builds segment weights from supplied per-user weights. Keep it rule-based and deterministic; no clustering library in Phase 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_personalization_profile.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 8: Three-Level Personalization and Learning Snapshots

**Files:**
- Modify: `task-recommender/app/domain.py` (add `UserWeightProfile`, `LearningSnapshot`)
- Create: `task-recommender/app/personalization/user_weights.py`
- Modify: `task-recommender/app/service.py` (accept `user_weights` / user_id)
- Create: `task-recommender/tests/test_personalization_weights.py`

**Interfaces:**
- `UserWeightProfile` fields: `user_id, weights, source, segment_id, sample_count, confidence, version, updated_at`.
- `LearningSnapshot` fields: `user_id, n_feedback, weights, ndcg_at_10, hr_at_10, regret, created_at`.
- `Store` gains `profiles: dict[str, UserProfile]`, `user_weight_profiles: dict[str, UserWeightProfile]`, and `learning_snapshots: list[LearningSnapshot]`.
- `PersonalizationService(store: Store, segmenter: Segmenter, global_weights: dict[str, float])`
  - `ensure_profile(user_id: str, entity_type: str, declared: dict | None = None) -> UserProfile`
  - `weights_for(user_id: str) -> UserWeightProfile` (creates from profile/segment if absent)
  - `update(user_id: str, features: dict[str, float], rating: int) -> UserWeightProfile`
  - `snapshot(user_id: str, ndcg_at_10: float, hr_at_10: float, regret: float) -> LearningSnapshot`
- `RecommendationService.recommend_workers(task_id, top_n, user_id: str | None = None)` and `recommend_tasks(worker_id, top_n, user_id: str | None = None)` use the user's weights when provided; otherwise global.

Rules:
- Per-user weights: `w_u = n/(n+n0) * learned + n0/(n+n0) * w_u0`, `n0=20` adjusted by profile completeness (`n0 = 10 + 30*(1-completeness)`).
- Every update runs `project_weights`.
- `weights_for` returns source `profile` or `segment` or `global`; confidence = `n/(n+20)`.

- [ ] **Step 1: Write the failing test**

```python
def test_personalization_shrinks_toward_prior_for_new_user(small_store):
    from app.learning.weights import AHP_PRIOR
    from app.personalization.segments import Segmenter
    from app.personalization.user_weights import PersonalizationService

    personalizer = PersonalizationService(small_store, Segmenter(), AHP_PRIOR)
    profile = personalizer.ensure_profile("w_new", "worker", {"role": "engineer", "industry": "software", "experience_years": 2})
    weights = personalizer.weights_for("w_new")
    assert weights.source in {"profile", "segment", "global"}
    assert sum(weights.weights.values()) == pytest.approx(1.0)
    updated = personalizer.update("w_new", {"reputation": 1.0, "skill": 0.0, "expertise": 0.0, "collaborative": 0.0, "preference": 0.0, "load": 0.0, "customer_preference": 0.0}, 5)
    assert updated.sample_count == 1
    assert sum(updated.weights.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_personalization_weights.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement personalization**

Reuse `OnlineWeightLearner` for per-user updates. Store profiles and weight profiles in `app.state`/`Store` dictionaries keyed by user ID. `RecommendationService` gains optional `user_weights: dict[str, float] | None` per call; when absent it uses global weights.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_personalization_weights.py tests/test_recommend.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 9: Worker and Customer Preference Profiles

**Files:**
- Create: `task-recommender/app/preference/__init__.py`
- Create: `task-recommender/app/preference/worker.py`
- Create: `task-recommender/app/preference/customer.py`
- Modify: `task-recommender/app/features.py` (use profiles when present)
- Create: `task-recommender/tests/test_preference_profiles.py`

**Interfaces:**
- `WorkerPreferenceProfile` fields: `worker_id, category_preferences: dict[str,float], difficulty_preference: tuple[int,int], confidence: float`.
- `update_worker_preferences(profile, task: Task, accepted: bool, rating: int | None, now: datetime, tau_days: float = 30.0) -> WorkerPreferenceProfile`
- `CustomerPreferenceProfile` fields: `customer_id, attribute_weights: dict[str,float], confidence: float`.
- `update_customer_preferences(profile, worker: Worker, task: Task, rating: int) -> CustomerPreferenceProfile`.
- `preference_score(worker, task, profile: WorkerPreferenceProfile | None = None) -> float`
- `customer_preference_score(customer, worker, task, reputation: float, expertise: float, profile: CustomerPreferenceProfile | None = None) -> float`
- `candidate_features(worker, task, customer, cf_score=0.0, now=None, worker_profile=None, customer_profile=None) -> dict[str, float]`
- Profiles with insufficient confidence fall back to Phase 1 heuristics.

Rules:
- Worker preference update: accepted/high rating increases `category_preferences[task.category]`; declined/low rating decreases it; decay old values with `exp(-delta_days/tau_days)`; normalize to `[0,1]`.
- Customer preference update: a high rating increases weights for reputation/expertise/speed; low rating increases price/communication weight; normalize to sum 1.
- Cold start: profiles with `confidence < 0.2` use Phase 1 heuristics.

- [ ] **Step 1: Write the failing test**

```python
def test_worker_preference_moves_toward_accepted_category(small_store, software_task):
    from app.preference.worker import WorkerPreferenceProfile, update_worker_preferences

    profile = WorkerPreferenceProfile(worker_id="w_new", category_preferences={"software_dev": 0.5}, difficulty_preference=(2, 4), confidence=0.0)
    updated = update_worker_preferences(profile, software_task, accepted=True, rating=5, now=small_store.reference_time)
    assert updated.category_preferences["software_dev"] > 0.5
    assert 0.0 <= updated.confidence <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_preference_profiles.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement preference profiles**

Keep the profiles in `Store` dictionaries. Feature functions consult profiles only when confidence is sufficient; otherwise use the Phase 1 formulas unchanged. Do not implement full logistic accept/select models in Phase 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd task-recommender && python -m pytest tests/test_preference_profiles.py tests/test_features.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 10: Ground Truth, Latent Weights, and New-User Cohort

**Files:**
- Create: `task-recommender/app/data/ground_truth.py`
- Modify: `task-recommender/app/data/synthetic.py`
- Modify: `task-recommender/app/domain.py` (add `Dataset.true_weights` and `Dataset.new_users`)
- Create: `task-recommender/tests/test_ground_truth.py`

**Interfaces:**
- `generate_dataset(..., n_new_users: int = 200, with_ground_truth: bool = True) -> Dataset`
- `Dataset.true_weights: dict[str, dict[str, float]]` (worker/customer latent weights).
- `Dataset.new_users: list[Worker]` (no assignments; profiles correlated with latent weights).
- `build_ground_truth(dataset: Dataset, path: Path, seed: int = 42) -> Path` writes `ground_truth.csv` with `worker_id, task_id, true_match`.
- `compute_target_stats(dataset: Dataset) -> dict[str, float]` and `validate_targets(stats, targets, tolerances) -> dict[str, bool]`.

Rules:
- True weights are generated once per worker/customer from a Dirichlet-like simplex (use `random.Random(seed)`).
- `true_match = sum(true_weights[worker] * features)` for every worker-task pair; store the full matrix in the CSV.
- New users have `ratings=[]`, `completed=0`, no assignments, and a profile built from their latent weights plus noise.
- Append new users to `workers` **after** assignment generation and exclude them from assignment sampling; they must have zero assignments.
- Ground truth is written under `data/ground_truth.csv`; no training/feature path reads it.

- [ ] **Step 1: Write the failing tests**

```python
def test_generate_dataset_includes_new_users_and_ground_truth(tmp_path):
    from app.data.ground_truth import build_ground_truth
    from app.data.synthetic import generate_dataset

    dataset = generate_dataset(n_workers=20, n_tasks=30, n_assignments=100, n_new_users=5)
    assert len(dataset.new_users) == 5
    assert all(not worker.ratings for worker in dataset.new_users)
    path = build_ground_truth(dataset, tmp_path / "ground_truth.csv")
    assert path.exists()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 20 * 30 + 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd task-recommender && python -m pytest tests/test_ground_truth.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement ground truth**

Keep generation deterministic. Do not import the ground-truth module from `features.py`, `service.py`, or `main.py`. The CSV is read only by evaluation scripts.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_ground_truth.py tests/test_synthetic.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 11: Phase 2 Evaluation and Learning Curve

**Files:**
- Create: `task-recommender/app/evaluation_phase2.py`
- Create: `task-recommender/scripts/evaluate_phase2.py`
- Create: `task-recommender/scripts/demo_judges.py`
- Create: `task-recommender/tests/test_evaluation_phase2.py`

**Interfaces:**
- `evaluate_two_runs(store, service, baseline_weights, learned_weights, k=10) -> dict[str,float]`
  - keys: `baseline_ndcg`, `learned_ndcg`, `baseline_hr`, `learned_hr`, `baseline_rmse`, `learned_rmse`, `breach_rate`, `constraint_violations`, `gini`.
- `learning_curve(store, personalizer, user_ids: list[str], steps=(0,5,10,20,50,100)) -> dict[str, list[float]]`
  - keys: `n`, `ndcg`, `hr`, `regret`, `weight_cosine`.
- `weight_recovery(learned: dict[str,float], truth: dict[str,float]) -> float` (cosine).
- `compare_queries(store, service_a, service_b, queries: list[dict], k=10) -> list[dict]` writes rank changes.
- Scripts write `reports/phase2_compare.md`, `reports/phase2_queries.csv`, `reports/phase2_learning_curve.md`.
- `demo_judges.py` prints: current weights, weights diff, learning changelog, one query's baseline vs learned Top-N, rollback to `v0000`, re-query, restore.

Evaluation protocol:
- Use the same test set for both runs; no test feedback in weights.
- Learning curve: simulate feedback for new users in chronological order; record NDCG/HR/regret/cosine at each step.
- `constraint_violations` must be 0.

- [ ] **Step 1: Write the failing tests**

```python
def test_weight_recovery_perfect_and_orthogonal():
    from app.evaluation_phase2 import weight_recovery

    weights = {"reputation": 0.32, "skill": 0.20, "expertise": 0.15, "collaborative": 0.13, "preference": 0.10, "load": 0.06, "customer_preference": 0.04}
    assert weight_recovery(weights, weights) == pytest.approx(1.0)
    orthogonal = {key: 0.0 for key in weights}
    orthogonal["reputation"] = 1.0
    assert weight_recovery(weights, orthogonal) < 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_evaluation_phase2.py -v`
Expected: FAIL with missing module.

- [ ] **Step 3: Implement evaluation and demo**

Reuse Phase 1 metrics (`hr_at_k`, `ndcg_at_k`) and the Phase 1 evaluation filters (train-overlap and ineligible positives). Write deterministic reports with `json.dumps` and `csv.writer`. The demo script must not mutate the active version except through the documented rollback/restore calls.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd task-recommender && python -m pytest tests/test_evaluation_phase2.py -v`
Expected: PASS.

- [ ] **Step 5: Run evaluation**

Run: `cd task-recommender && python scripts/evaluate_phase2.py`
Expected: reports written and metrics printed.

- [ ] **Step 6: Checkpoint**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

---

## Task 12: Phase 2 APIs, README, and Final Verification

**Files:**
- Modify: `task-recommender/app/main.py`
- Modify: `task-recommender/app/schemas.py`
- Modify: `task-recommender/app/config.py` (`APP_VERSION = "0.2.0"`)
- Modify: `task-recommender/tests/test_api.py` (health expects `0.2.0`)
- Modify: `task-recommender/README.md`
- Create: `task-recommender/tests/test_phase2_api.py`

**Interfaces:**
- `create_app(store: Store | None = None, weights_dir: Path | None = None) -> FastAPI`; Phase 2 tests pass `tmp_path` so rollback state does not leak between tests.
- `POST /workers/{id}/onboarding` body `{role, industry, experience_years, declared_preferences}` → initial weight profile.
- `GET /workers/{id}/weight-profile`
- `GET /workers/{id}/learning-curve`
- `POST /customers/{id}/onboarding`
- `GET /customers/{id}/weight-profile`
- `GET /weights`, `GET /weights/diff`, `POST /weights/rollback`, `POST /weights/recompute`, `GET /learning/changelog`
- `GET /metrics/compare`, `GET /metrics/learning-curve`
- `POST /recommend/workers` and `POST /recommend/tasks` accept optional `user_id`.

- [ ] **Step 1: Write the failing test**

```python
def test_phase2_api_flow(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    onboarding = client.post("/workers/w_new/onboarding", json={"role": "engineer", "industry": "software", "experience_years": 2})
    assert onboarding.status_code == 200
    weights = client.get("/workers/w_new/weight-profile")
    assert weights.status_code == 200
    assert sum(weights.json()["weights"].values()) == pytest.approx(1.0)
    rollback = client.post("/weights/rollback", json={"to_version": "v0000", "reason": "test"})
    assert rollback.status_code == 200
    assert client.get("/weights").json()["version"] == "v0000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd task-recommender && python -m pytest tests/test_phase2_api.py -v`
Expected: FAIL with 404/405.

- [ ] **Step 3: Implement endpoints and README**

Bump `APP_VERSION` to `"0.2.0"` in `app/config.py`. Wire the existing Phase 2 services into `create_app`. Keep the Phase 1 endpoints intact. README adds: Phase 2 scope, feedback/weights/personalization API examples, learning curve, rollback demo, and the Phase 2 metrics table.

- [ ] **Step 4: Run full verification**

Run: `cd task-recommender && python -m pytest tests/ -q`
Expected: all tests pass.

Run: `cd task-recommender && python scripts/evaluate_phase2.py`
Expected: Phase 2 reports written.

Run: `cd task-recommender && PORT=8013 python scripts/run_demo.py` (separate terminal)
Then: `curl http://127.0.0.1:8013/health`
Expected: `{"status":"ok","version":"0.2.0"}`.

- [ ] **Step 5: Final checkpoint**

Confirm:
- `pytest` exits 0.
- `reports/phase2_compare.md`, `reports/phase2_queries.csv`, `reports/phase2_learning_curve.md` exist.
- `/weights/rollback` to `v0000` restores baseline recommendations.
- 41+ Phase 1 tests still pass, plus Phase 2 tests.
- No ground-truth leakage: `grep -R "ground_truth" app/` returns only the generator/evaluation modules, never `features.py`, `service.py`, or `main.py` recommendation paths.

Do not commit (workspace is not a git repo).
