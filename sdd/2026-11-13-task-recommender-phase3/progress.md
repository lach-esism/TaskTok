# SDD ledger — plan: plans/2026-11-13-task-recommender-phase3.md

## Setup
- Workspace: in-place at task-recommender (not a git repo; no worktree/commits).
- Ruling: proceed in-place, no commits — user instructed “其他做” with no LLM — cost if wrong: no commit history; tests and ledger are the record.
- Spec: specs/2026-11-13-task-assignment-recommender-design.md
- Pre-flight: Phase 3 tasks consume existing chain/service/weight interfaces; no blocking conflicts. MILP uses scipy.optimize.milp (available). No LLM modules will be added.
Task 1: complete (tests: python -m pytest tests/ -q → 89 passed)
Task 2: complete (tests: python -m pytest tests/ -q → 94 passed)
Task 2: correction — actual suite count 93 passed.
Task 3: complete (tests: python -m pytest tests/ -q → 93 passed; scripts/build_ground_truth.py → data/ground_truth.csv)
Task 4: complete (tests: python -m pytest tests/ -q → 94 passed)
Task 5: complete (tests: python -m pytest tests/ -q → 95 passed)
Task 6: complete (tests: python -m pytest tests/ -q → 96 passed)
Task 7: complete (tests: python -m pytest tests/ -q → 97 passed)
Task 8: complete (tests: python -m pytest tests/ -q → 99 passed)
Task 9: complete (tests: python -m pytest tests/ -q → 101 passed)
Task 10: complete (tests: python -m pytest tests/ -q → 102 passed; scripts/evaluate_chains.py → reports/phase3_chain_metrics.json/md)
Task 11: complete (tests: python -m pytest tests/ -q → 103 passed; evaluate_phase2.py → 200-user learning curve; metrics/compare?run_a/run_b wired)
Task 12: complete (tests: python -m pytest tests/ -q → 103 passed; scripts/evaluate_chains.py → reports/phase3_chain_metrics.json/md; live smoke PORT=8016 → compose/plan/replan/plans/rollback 200; PORT=8017 metrics compare 200 in 0.38s, unknown version 404; health 0.3.0)
Task 12: Ruling: MILP is limited to <=20 nodes and falls back to Beam Search; cost if wrong: larger chains use Beam only.
Task 12: Ruling: /metrics/compare?run_a&run_b evaluates the last 50 assignments for latency; cost if wrong: comparison is a sample, not the full test set.
Task 12: Ruling: learning curve uses 200 new users but one seed; confidence intervals/multi-seed remain deferred — cost if wrong: no variance estimate.

## Final review fixes (Critical/Important)

- Final: fixed projection allocation — correct water-filling, immediate shares for non-capped keys, idempotence and reputation-largest; tests test_projection_reviewer_repro_is_stable + fuzz RED→GREEN; suite 111/111.
- Final: fixed replan capacity — Beam seeded with locked assignments and their hours; test_replan_locked_capacity_is_respected RED→GREEN; suite 111/111.
- Final: fixed /metrics/compare zeros — create_app retains held-out test assignments; successful compare uses them and returns available:false without held-out; test_metrics_compare_success_with_heldout RED→GREEN; live baseline_hr=0.3469.
- Final: fixed compose truncation — decompose receives template max_nodes; compose raises above cap; test asserts content_writing:draft survives and 3 categories return 422.
- Final: fixed replan scope — uses BreachImpact.affected_nodes, locks unaffected nodes, honors requires_replan, returns affected/replanned metadata.
- Final: fixed auto-lock — node status endpoint + completed/in_progress nodes unioned into locked set; test_replan_auto_locks_completed_node RED→GREEN.
- Final: fixed blocked propagation — greedy/Beam/MILP mark downstream of blocked nodes; test_blocked_dependency_blocks_downstream RED→GREEN.
- Final: fixed category reputation — category_reputation now used by reputation_score and synthetic train category ratings; test_category_reputation_changes_feature_score RED→GREEN.
- Final: fixed scipy declaration/planner visibility — scipy>=1.11, ChainPlan.planner, milp/beam_fallback; test asserts planner values.
- Final: fixed shared-node composition — requirements/delivery merge skills and acceptance; test_compose_preserves_shared_node_skills RED→GREEN.
- Final: added discriminating tests — projection fuzz, replan lock capacity, status auto-lock, blocked propagation, successful metrics compare, shared skills; suite 111/111.
- Final: reran evaluations — Phase 2 baseline_ndcg=0.1345, learned_ndcg=0.1437, baseline_hr=0.2820, learned_hr=0.3016; Phase 3 greedy/beam/milp plan_coverage=1.0, blocked=0.0; README updated.
- Final: live smoke PORT=8018 — compose 14 nodes with content_writing:draft, 3-category compose 422, plan/replan/status/rollback 200, metrics compare 200 (baseline_hr=0.3469), duplicate assignment 409, bad context 422.

## Deferred minors (not fixed)

- Final: minor (deferred): plan score semantics differ (greedy mean vs Beam/MILP sum).
- Final: minor (deferred): validate_weights still accepts extra keys and non-finite values.
- Final: minor (deferred): some API detail strings remain English.
- Final: minor (deferred): propagate_breach severity for non-critical delays and normalization is not fully specified.
- Final: minor (deferred): evaluate_planners lacks a constraint_violations metric.
- Final: minor (deferred): test_health creates the default app with the real data/weights directory.
- Final: minor (deferred): unsupported decompose modes silently fall through to template mode.
- Final: minor (deferred): learning curve remains one seed without confidence intervals.
- Final: minor (deferred): composition treats `review` as template-specific rather than a shared node (see ruling).

## Rulings / declined-to-judge

- Final: Ruling: composition keeps `review` per category instead of merging it into one shared review node — reviews are template-specific; cost if wrong: one shared review could reduce node count.
- Final: Ruling: accepted the reviewer's declined items as out of Phase 3 scope: LLM, multi-chain global scheduling, full ChainPlan scheduling fields, chain approval/status transitions beyond the added status endpoint, calibration/fidelity/TSTR/IPS/Gini/RMSE, full held-out compare rather than 50-sample, customer authorization, decompose variants/coverage quality, exploration in chain planners, concurrency, deterministic tie-breaking, weight rollback response fields, report regeneration equality, wording — cost if wrong: revisit in Phase 4.

## Frontend demo

- Frontend: complete — static SPA at frontend/{index.html,styles.css,app.js}, served by FastAPI at /ui/, root redirects to /ui/; integrates recommend/adopt/feedback/weights/onboarding/learning-curve/chain/plan/replan/plan-rollback/status APIs; test_frontend_served; suite 112/112; node --check OK; live smoke PORT=8020.
- Frontend: Ruling: no Node build/framework; static SPA served by FastAPI — cost if wrong: less component structure and no client-side router.
- Frontend: Ruling: demo uses existing APIs only; no new business logic — cost if wrong: future frontend-specific endpoints need backend work.
- Frontend: minor (deferred): no automated browser E2E; verification is JS syntax + static serving + API smoke.

## Frontend judge-demo fix

- Fixed runDemo step() returning display strings instead of objects: step now returns the raw result and takes a display formatter; decompose/plan/replan/rollbacks now keep chain_id and plan objects.
- Added personal weight-profile display, global /weights/recompute, and a non-empty v0000→current diff in the demo flow.
- Added planner to /chains/{id}/plan response; demo logs planner (greedy/beam/milp).
- Verified API-equivalent flow: assignment → feedback u0001 → personal n=1 → recompute v0002 → 7-dim diff → chain 6 nodes → plan v1 greedy → replan v2 affected 4 → plan rollback v1 → weights rollback v0000; suite 112/112; node --check OK.

## Cleanup + progress visualization

- Removed the remaining empty original `demos/task-recommender` directory after the generated copy moved to `task-recommender`.
- Added a responsive SVG progress chart to the frontend (overview + feedback tabs): 200-user learning curve, weight-recovery cosine (left axis) and NDCG@10 (right axis), with hover titles and n=0/5/10/20/50 labels.
- Added test_learning_curve_endpoint and frontend assertions for progress-chart/renderProgressChart; suite 113/113; node --check OK; live `/metrics/learning-curve` returns the series.

## New-user growth demo

- Added onboarding `preferences` + `reset` and a profile-to-weight bias map (quality/speed/specialty/flexibility); tests for preference bias and reset.
- Added frontend growth panel: same user/task, A/B initial choices, weight and Top-N comparison with auto-selection of a preference-sensitive task; then 12 feedback ratings and a corrected weight/ranking view.
- Verified: quality vs speed initial weights (reputation 0.40 vs 0.32, load 0.042 vs 0.093); t0003 Top-N differs; 12 feedback → personal sample 12, cosine to target 0.9787→0.9897, learning snapshots 12; suite 115/115; node --check OK.

## 20-round learning vs no-learning experiment

- Added `app/learning_simulation.py`: 20 customers, 20 rounds, 50 choices/round, 20 candidate workers; customer choice driven by a fixed quality-heavy true vector; learning arm does pairwise hard-negative updates after each round; control keeps the deliberately wrong speed-heavy initial vector.
- Added `scripts/simulate_learning_rounds.py`, `reports/learning_rounds.json`, `reports/learning_rounds.md`, `/metrics/learning-rounds`, and a frontend comparison chart (Top-1/Top-5 learning vs control).
- Result: round 1 both 0.628 Top-1; final learning 0.723 vs control 0.615; Top-5 0.981 vs 0.958; cosine 0.923 vs 0.852.
- Added test_learning_simulation and learning-rounds endpoint test; suite 117/117; JS syntax OK; live endpoint returns 20 rounds.
- Ruling: controlled simulation uses fixed true/initial weight vectors and a single seed; cost if wrong: it demonstrates the mechanism, not production population variance.

## Realistic task postings

- Replaced generic `{category} task {i}` titles with 12 per-category title pools and real briefs: description, natural-language requirements, budget range, publish/deadline dates; `Task` gained `requirements`, `budget_min`, `budget_max`.
- Frontend task pickers now show title + budget + deadline (no category/skill tags); task→worker tab adds a posting preview card; worker→task candidate cards show task title, budget and deadline.
- Added synthetic-data tests for profile coverage, realistic fields, budget ordering, dates, unique titles and no double punctuation; suite 119/119; JS syntax OK; live API verified on port 8021.
- Ruling: keep internal `category`/`required_skills` for matching and chain templates but never render them as tags; cost if wrong: the demo shows fewer matching explanations, but the user-facing posting stays realistic.

## Non-LLM natural-language task classification

- Added `app/nlp/` with a weighted category lexicon, a char 2–4 gram TF-IDF + logistic-regression model, and a blended classifier (`0.6 ML + 0.4 rules`); low-margin predictions return top-3 plus `needs_clarification` instead of forcing a label.
- Added structured extraction for budget ranges (including 万 and shared units), duration (days/weeks and Chinese numerals), dates, remote/onsite, requirement sentences, and internal skill tags.
- Added `POST /classify` and a "需求分类" frontend tab with sample input, top-3 confidence bars, and extracted fields.
- Added `scripts/evaluate_text_classifier.py` + `reports/text_classifier.md`; hand-written unseen phrasings 12/12 top-1. Grouped CV is 1.0 on the synthetic templates, which overstates real-world accuracy.
- Tests: 16 new classifier/extraction/endpoint tests; suite 135/135; JS syntax OK; live endpoint and UI verified on port 8021.
- Ruling: train the default demo classifier on synthetic postings rather than the injected small store; cost if wrong: the demo model reflects synthetic vocabulary, and a production deployment must retrain on labeled real postings.

## Acceptance loop P0 (B2B research wedge)

- Added `AcceptanceCriterion` / `AcceptanceSpec` / `Submission` / `AcceptanceRecord` domain models and `app/acceptance/` with the 10-criterion B2B research spec, deterministic machine checks, human review, final decision, capability metrics, and platform metrics.
- Decision rules: hard gates block acceptance; rejecting without a failed criterion converts to `disputed`; disputed records do not feed learning.
- Acceptance outcomes map criterion dimensions to 7 scoring dimensions and nudge the customer's personal weights (`PersonalizationService.nudge_weights`); frontend shows before/after and top up/down dimensions.
- Added API: `/acceptance/demo`, `/acceptance/metrics`, task spec/submission/records, submission review/decision, worker capability.
- Added "验收闭环" frontend tab: load demo, submit good/bad artifacts, machine results, review, accept/rework/reject, weight deltas, capability.
- Tests: 7 new acceptance tests; suite 142/142; JS syntax OK; live good/bad submissions and decision verified on port 8021.
- Ruling: acceptance v1 supports only `consulting_research`; other categories return 422 instead of a fake generic spec. Cost if wrong: demo scope is narrower than the 12-category recommender.

## Acceptance learning demo for the pitch

- Added `POST /acceptance/demo/learning?rounds=5`: accepts five B2B research tasks for one customer, accumulates acceptance signals, then finds a target task whose Top-5 ordering moves.
- Added `decide(..., learn=False)` and a customer override on `_learn_from_acceptance` so the demo can accumulate one customer's preference instead of scattering signals across five different task customers.
- Live result: 5 samples, expertise +0.048, collaborative -0.041; target task Top-5 moved w0099 from #4 to #2, first-pass rate 1.0.
- Added frontend "连续验收 5 次看学习" with weight delta table, ranking change table, and per-round scores.
- Tests: suite 143/143; JS syntax OK; live endpoint verified on port 8021.
- Ruling: the demo attributes all five acceptances to a chosen demo customer even though the underlying tasks have different customer_ids; cost if wrong: it demonstrates the learning mechanism, not a real multi-customer causal estimate.

## Resume view: surface skills as a human CV

- Added `app/resume.py`: deterministic synthetic resumes (name, headline, city, experience, education, summary, stats, work/projects, Chinese skill tags, certifications) and a hidden `platform_data` payload (raw skill scores, level, load, ratings, breaches, category ratings).
- Added `GET /resumes?limit=30` (surface only) and `GET /workers/{id}/resume` (surface + platform data).
- Added "人才库" frontend tab: CV-style sheet by default, with a "查看平台原始数据" toggle for internal scores/load/reputation.
- Filtered surface skill tags to category-relevant skills so random worker skills do not show up as unrelated resume tags.
- Tests: 3 new resume tests; suite 146/146; JS syntax OK; live `/resumes` and resume detail verified on port 8021.
- Ruling: resumes are generated at read time rather than persisted; cost if wrong: edits to a resume are not stored, but the demo remains deterministic and schema-free.

## 1000-task answer-key benchmark

- Added `app/benchmark/` + `data/benchmark/task_benchmark.sqlite`: 1,000 natural-language tasks, 100 natural-language resumes, 800/200 train/test, labels isolated in a `labels` table.
- Round protocol: reset recommendation cache → recommend → score against labels → listwise softmax learn on train only → next round. The recommender never reads labels.
- Added `scripts/build_benchmark.py`, `scripts/run_benchmark_rounds.py`, `reports/benchmark_rounds.json/md`, API `/benchmark/summary` and `/benchmark/run`, and a "对答案学习" frontend tab with curve/table.
- Selected truth noise 0.003 after finding 0.05 made labels near-random (true-weight Top-1 only 0.08). Listwise learning at lr 0.05 is stable; pairwise updates and lr 1.0 oscillated.
- 10-round result: Top-1 0.563→0.731, Top-5 0.913→1.000, test Top-1 0.560→0.750; cache cleared each round; suite 150/150.
- Ruling: same 1,000 tasks are used for evaluation every round, but learning only uses the 800-task train split and the recommendation cache is cleared; cost if wrong: global weights still see the same task collection, so this measures weight recovery, not unseen-task generalization.

## Recommendation flow document

- Added `task-recommender/docs/recommendation-flow.md`: main recommendation pipeline, hard constraints, 7-dim features/formulas, global vs personal weights, epsilon-greedy/IPS, feedback/recompute, acceptance learning, benchmark protocol, boundaries, and code index.
- Linked it from the README top section.
