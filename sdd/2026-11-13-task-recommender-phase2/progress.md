# SDD ledger — plan: plans/2026-11-13-task-recommender-phase2.md

## Setup
- Workspace: in-place at task-recommender (not a git repo; no worktree/commits).
- Ruling: proceed in-place, no commits — user chose Native and the plan prohibits commits — cost if wrong: no commit history; tests and this ledger are the record.
- Spec: specs/2026-11-13-task-assignment-recommender-design.md
- Pre-flight: shared interfaces checked:
  - Task 1 extends Feedback/Assignment consumed by Tasks 2, 8, 11, 12 — compatible; defaults keep Phase 1 tests green.
  - Task 4 weight math consumed by Tasks 5, 8, 11 — AHP_PRIOR reuses DEFAULT_WEIGHTS.
  - Task 5 learner consumed by Task 8 — stable `update`/`batch_fit`/`weights`.
  - Task 7 profiles consumed by Task 8 — `UserProfile`/`Segment` defined before use.
  - Task 8 personalization consumed by Tasks 11, 12 — `RecommendationService` optional `user_id` will be added.
  - Task 10 ground truth consumed by Task 11 — evaluation-only; no feature imports.
  - Known planned conflict: APP_VERSION 0.1.0→0.2.0 in Task 12 also updates tests/test_api.py::test_health.
Task 1: complete (tests: python -m pytest tests/ -q → 46 passed)
Task 2: complete (tests: python -m pytest tests/ -q → 49 passed)
Task 3: complete (tests: python -m pytest tests/ -q → 53 passed)
Task 4: complete (tests: python -m pytest tests/ -q → 56 passed)
Task 5: complete (tests: python -m pytest tests/ -q → 59 passed)
Task 6: complete (tests: python -m pytest tests/ -q → 63 passed)
Task 7: complete (tests: python -m pytest tests/ -q → 65 passed)
Task 8: complete (tests: python -m pytest tests/ -q → 67 passed)
Task 9: complete (tests: python -m pytest tests/ -q → 70 passed)
Task 10: complete (tests: python -m pytest tests/ -q → 71 passed)
Task 10: Ruling: new users live in Dataset.new_users rather than being appended to Dataset.workers — preserves Phase 1 worker counts and keeps ground-truth rows at base_workers × tasks; cost if wrong: callers must merge new_users explicitly for recommendation pools.
Task 11: complete (tests: python -m pytest tests/ -q → 73 passed; scripts/evaluate_phase2.py → reports/phase2_metrics.json, phase2_compare.md, phase2_learning_curve.md, phase2_queries.csv; demo_judges.py → v0000→v0001 diff→rollback v0000)
Task 12: complete (tests: python -m pytest tests/ -q → 76 passed; scripts/evaluate_phase2.py → reports/phase2_metrics.json, phase2_compare.md, phase2_learning_curve.md, phase2_queries.csv; live smoke PORT=8014 → health 0.2.0, onboarding 200, weight-profile sum 1.0, recommend with user_id 200, weights/rollback 200, assignment/feedback/reputation 200, metrics/compare 200)
Task 12: Ruling: metrics endpoints read reports/phase2_metrics.json and return {"available": false} when absent — keeps the API usable before evaluation runs; cost if wrong: callers must run evaluate_phase2.py first for real numbers.
Task 12: Ruling: APP_VERSION bumped to 0.2.0 and tests/test_api.py::test_health updated in the same change — cost if wrong: clients pinned to 0.1.0 must update.

## Final review fixes (Critical/Important)

- Final: fixed active weight version wiring — recommend/chain endpoints now use weight_store.active().weights and exploration pool; test_active_weight_version_changes_and_rollback_restores RED→GREEN; suite 85/85.
- Final: fixed feedback-driven personalization — /feedback updates per-user weights, worker/customer preference profiles, and learning snapshots; test_feedback_updates_personal_weights_and_snapshot RED→GREEN; suite 85/85.
- Final: fixed evaluation honesty — RMSE/Gini return null, breach rate is test-set, constraint violations are checked; test_two_run_metrics_do_not_fabricate_rmse_or_gini RED→GREEN; suite 85/85.
- Final: fixed new-user profile correlation — new-user fields derive from latent true weights plus noise; test_new_user_profiles_correlate_with_latent_weights RED→GREEN; suite 85/85.
- Final: wired exploration and propensity into APIs — recommendations return real propensities; test_recommendations_include_propensity RED→GREEN; suite 85/85.
- Final: fixed segment shrinkage — Segmenter.fit accepts global weights and shrinks n/(n+50); test_segment_weights_shrink_toward_global RED→GREEN; suite 85/85.
- Final: fixed per-user anchor — UserWeightProfile.initial_weights preserved and used for shrinkage; test_personalization_preserves_initial_weights_anchor RED→GREEN; suite 85/85.
- Final: replaced fabricated demo evidence — demo_judges.py learns from train feedback, compares baseline/learned Top-N, rolls back, re-queries, restores.
- Final: strengthened Review-Focus tests — active-version/rollback, feedback learning, floors over 100 updates, ground-truth isolation, segment shrink, anchor; suite 85/85.
- Final: reran evaluation — baseline_ndcg=0.1363, learned_ndcg=0.1439, baseline_hr=0.2865, learned_hr=0.3060, breach_rate=0.01, constraint_violations=0, baseline_rmse/learned_rmse/gini=null; learning curve cosine 0.7496→0.7955.
- Final: Ruling: Critical/Important findings addressed with RED→GREEN tests; no second review pass per executing-plans — cost if wrong: residual untested issues may remain.

## Deferred minors (not fixed)

- Final: minor (deferred): source label says "profile" even when weights came from a segment.
- Final: minor (deferred): /workers/{id}/reputation returns arithmetic mean, not the Bayesian rating used in scoring, and lacks explicit status.
- Final: minor (deferred): feedback never appends worker.category_ratings, so category_reputation is effectively dead.
- Final: minor (deferred): duplicate assignments for same task+worker return 200 rather than 409.
- Final: minor (deferred): recommendation_context is unvalidated; bad numeric fields can raise 500.
- Final: minor (deferred): WeightStore.create does not validate simplex/floors; writes are not atomic; active.json pointing at a missing file yields 500.
- Final: minor (deferred): project_weights is not idempotent (small drift) and does not enforce "reputation largest" beyond the 0.25–0.40 bound.
- Final: minor (deferred): decay_weight, entropy_weights, combine_weights, and category_reputation are implemented but not wired into online/batch flow.
- Final: minor (deferred): create_app uses train assignments but full feedback for ItemCF; test-period feedback for a train pair can mark it rated.
- Final: minor (deferred): default client fixture uses real data/weights instead of tmp_path.
- Final: minor (deferred): /metrics/compare ignores run_a/run_b and returns the whole report.
- Final: minor (deferred): evaluate_phase2 uses 20 new users, one seed, no CI/bootstrap.
- Final: minor (deferred): build_ground_truth is not called by a script, so data/ground_truth.csv is not produced outside tests.
- Final: minor (deferred): synthetic imports true_weight_simplex from the evaluation-only ground_truth module.

## Declined-to-judge rulings

- Final: Ruling: accepted the reviewer's declined items as out of Phase 2 scope: task-chain internals, APIs outside Task 12, LLM/multi-template/Beam/MILP/replanning, full spec metric suite, calibration/fidelity/multi-seed, 70/15/15 and 800/4000/30000 scale, task-already-assigned 409, feedback response fields, spec-only model fields, persistence defaults, explain/debug fields, category_reputation wiring, audit timestamps, declared_preferences fields, /metrics/compare run params, auth/DB/frontend — cost if wrong: revisit in Phase 3.
