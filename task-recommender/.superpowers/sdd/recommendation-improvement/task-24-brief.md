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

