# SDD ledger — plan: plans/2026-11-13-task-recommender-phase1.md

## Setup
- Workspace: in-place at task-recommender (workspace is not a git repo; worktree unavailable).
- Ruling: proceed in-place, no commits — user chose Native and the plan prohibits commits — cost if wrong: no commit history; tests and this ledger are the record.
- Spec: specs/2026-11-13-task-assignment-recommender-design.md
- Pre-flight: no shared-interface conflicts found; interfaces align (create_app, Store, RecommendationService, SubTask/TaskChain, load_templates, decompose, plan_chain).
Task 1: complete (tests: python -m pytest tests/ -q → 1 passed)
Task 2: complete (tests: python -m pytest tests/ -q → 2 passed)
Task 3: complete (tests: python -m pytest tests/ -q → 3 passed)
Task 3: Ruling: use 40 skill names instead of 30 and generate each task from a feasible seed worker — needed to cover all template skills and guarantee eligible candidates; cost if wrong: synthetic skill distribution is slightly denser than planned.
Task 4: complete (tests: python -m pytest tests/ -q → 5 passed)
Task 5: complete (tests: python -m pytest tests/ -q → 8 passed)
Task 6: complete (tests: python -m pytest tests/ -q → 13 passed)
Task 7: complete (tests: python -m pytest tests/ -q → 17 passed)
Task 8: complete (tests: python -m pytest tests/ -q → 20 passed)
Task 8: Ruling: keep template_category and coverage_fallbacks as internal dynamic attributes on DecompositionDraft rather than extending the shared dataclass — avoids changing the Task 2 model; cost if wrong: these diagnostics are not serialized.
Task 9: complete (tests: python -m pytest tests/ -q → 23 passed)
Task 9: Ruling: add w_full (all skills, capacity 200) to conftest so the software template is plannable — the original small_store lacked backend/frontend/qa/devops skills; cost if wrong: test fixture is richer than the plan described.
Task 10: complete (tests: python -m pytest tests/ -q → 24 passed)
Task 11: complete (tests: python -m pytest tests/ -q → 27 passed; scripts/evaluate.py → task_to_workers_hr=0.915, task_to_workers_ndcg=0.778, worker_to_tasks_hr=0.665, worker_to_tasks_ndcg=0.344, decompose_success_rate=1.0, mean_coverage=0.34, mean_quality=0.7485, mean_plan_coverage=0.9767, acyclic_rate=1.0)
Task 12: complete (tests: python -m pytest tests/ -q → 29 passed; scripts/evaluate.py → reports/phase1_metrics.json; live server smoke on PORT=8011 → /health 200, /recommend/workers 200, /chains/decompose 200, /chains/plan 200)
Task 12: Ruling: create_app() now generates the default synthetic store when none is injected — required for the uvicorn factory demo; cost if wrong: create_app() is slower (~0.5s) when called without a store.
Task 12: Ruling: run_demo honors the PORT environment variable (default 8000) because port 8000 was occupied during verification; cost if wrong: none, port remains configurable.
Final: fresh review dispatched (general-purpose, fable) against the working tree; git-based review-package unavailable because the workspace is not a git repo.

## Final review fixes (Critical/Important)

- Final: fixed recent-breach recency — added Store.reference_time and threaded it through is_eligible, reputation_score, candidate_features; test_recent_breach_uses_data_reference_time RED→GREEN; suite 41/41.
- Final: fixed already-assigned hard constraint — service now rejects workers with a prior assignment to the same task; test_worker_already_assigned_to_task_is_excluded RED→GREEN; suite 41/41.
- Final: fixed degenerate candidate pools — worker skills 10–18, task requirements 1–2, lower proficiency/level, capacity 30–50/load 0–15; test_generated_dataset_has_meaningful_candidate_pool RED→GREEN; median eligible candidates 12; suite 41/41.
- Final: fixed evaluation leakage — train-only worker aggregates + skip train-overlap and ineligible positives; test_worker_aggregates_are_train_only and test_evaluate_recommender_skips_ineligible_positives RED→GREEN; suite 41/41.
- Final: fixed template DAG validation — load_templates rejects missing/duplicate deps and cycles; decompose raises on unknown dependency; /chains/decompose maps ValueError to 422; tests RED→GREEN; suite 41/41.
- Final: strengthened Review-Focus tests — results-level constraints, warm/cold CF, API 404/empty paths; suite 41/41.
- Final: reran evaluation — task_to_workers_hr=0.665, task_to_workers_ndcg=0.334, worker_to_tasks_hr=0.080, worker_to_tasks_ndcg=0.027, decompose_success_rate=1.0, mean_coverage=0.34, mean_quality=0.752, mean_plan_coverage=1.0, acyclic_rate=1.0.
- Final: live smoke on PORT=8012 — health 200; recommend workers/tasks 200; chains decompose/plan 200.
- Final: Ruling: reviewer's Critical/Important findings are addressed with RED→GREEN tests; no second review pass per executing-plans — cost if wrong: a fresh reviewer might find a residual issue not covered by the 41 tests.

## Deferred minors (not fixed)

- Final: minor (deferred): optional node without include_if is excluded; unsupported include_if does not append an issue.
- Final: minor (deferred): max_nodes truncation removes trailing non-delivery nodes instead of lowest-priority optional first.
- Final: minor (deferred): coverage_matrix returns only one matching node per requirement (interface says list of keys).
- Final: minor (deferred): API-facing detail/reason strings remain English.
- Final: minor (deferred): explain=false and unknown mode/variant are accepted but ignored.
- Final: minor (deferred): customer_preference_score ignores Customer.preference_weights.
- Final: minor (deferred): ItemCF norm uses summed interaction weights instead of interaction count.
- Final: minor (deferred): app.state.chains/drafts grow without eviction.
- Final: minor (deferred): PORT parsing raises ValueError on non-numeric input.
- Final: minor (deferred): synthetic breach rate ~1.4% rather than the planned ~3%.
- Final: minor (deferred): empty-DAG guards missing in critical_path/compute_slack.
- Final: minor (deferred): tests load templates via CWD-relative paths.

## Declined-to-judge rulings

- Final: Ruling: accepted the reviewer's declined items as Phase 1 out-of-scope: larger 70/15/15 scale, latent-variable DGP/ground truth/calibration/fidelity, dynamic weights/versioning/rollback/learning curves, feedback/personalization APIs, full preference/propensity/IPS models, per-category reputation and decayed historical breaches, breach warning/debug reasons, spec-only entity fields, LLM/multi-template/Beam/MILP/replanning, empty-candidate status 400 vs plan 200, full chain makespan/cost/risk schema, deadline/budget gates, auth/DB/frontend — cost if wrong: these must be revisited in Phase 2/3.
