# Task 24 Report: Accuracy Target Recovery (choice-learned candidate)

## Status

DONE — the accuracy target is **MET**. The choice-learned candidate (built from
train events + the rating batch fit, then tuned only on a validation split)
improves worker→tasks HR@10 by **+14.97pp** with a 95% CI that excludes 0, while
task→workers does **not** deteriorate (HR +0.37pp, NDCG +0.25%, both means
positive). Constraint violations are 0 and the candidate is a valid simplex.

## Candidate weights (`data/weights/weights_choice.json`)

```json
{
  "reputation": 0.367546550922,
  "skill": 0.124367748878,
  "expertise": 0.27845724286,
  "collaborative": 0.034863927247,
  "preference": 0.078898218881,
  "load": 0.068106525956,
  "customer_preference": 0.047759785256
}
```

Sum = 1.0; all values within the existing simplex bounds (each ≥ 0.02,
reputation ∈ [0.25, 0.40] and largest, skill + expertise ≥ 0.25). The
pre-tuning choice candidate was
`{reputation 0.36755, skill 0.12437, expertise 0.27846, collaborative 0.05884,
preference 0.07464, load 0.06097, customer_preference 0.03518}`; the coordinate
search moved mass out of `collaborative` into `preference`/`load`/
`customer_preference` (reputation/skill/expertise unchanged).

## How the candidate was built (train only)

`build_choice_candidate` mirrors the `POST /weights/recompute` path on a
train-only eval store (`build_eval_store`):

1. Rating batch fit: `OnlineWeightLearner(AHP_PRIOR).batch_fit(records)` over
   train assignments with feedback, using `candidate_features(..., cf_score=0,
   now=store.reference_time)`.
2. Serving-parity features for every train choice event via
   `RecommendationService.features_for`; `build_pairs` over accept vs
   reject/ignore events; `PairwiseChoiceLearner(AHP_PRIOR).fit(pairs)`.
3. 50/50 blend of batch and pairwise vectors, then `project_weights` onto the
   AHP simplex.

The pairwise signal is the dominant change: it drives reputation to its 0.40
cap, pushes expertise to ~0.28, and pulls skill down to ~0.12, which is what
recovers the worker→tasks direction.

## Validation-only tuning

`tune_on_validation` holds out the last 20% of train assignments (1920 fit /
480 validation) and runs a deterministic greedy coordinate search over the
seven weights, budget ≤ 20 candidate evaluations, scored only on validation
metrics. Baseline metrics use `DEFAULT_WEIGHTS`; the objective maximizes the
best primary direction's target-aligned gain (HR +5pp or NDCG +10% = 1 unit)
and subtracts a quarter of any HR/NDCG deterioration across both directions.
Test assignments/feedback are never read: the validation store excludes every
event/impression/feedback record whose assignment id belongs to the validation
or test split.

Validation metrics (k=10, 480 queries):

| Weights | task→workers HR | task→workers NDCG | worker→tasks HR | worker→tasks NDCG |
|---|---|---|---|---|
| baseline (DEFAULT) | 0.6979 | 0.3535 | 0.0917 | 0.0362 |
| choice candidate (pre-tune) | 0.7021 | 0.3564 | 0.1729 | 0.0769 |
| tuned candidate | 0.6979 | 0.3544 | 0.2063 | 0.0989 |

## Strict metrics / CIs (5 seeds, k=10, baseline=DEFAULT_WEIGHTS)

| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |
|---|---|---|---|---|
| task_to_workers | HR | 0.6717 | 0.6753 | +0.0037 [-0.0020, +0.0097] p=0.2260 |
| task_to_workers | NDCG | 0.3555 | 0.3564 | +0.0009 [-0.0022, +0.0041] p=0.5340 |
| task_to_workers | MRR | 0.2593 | 0.2594 | +0.0001 [-0.0033, +0.0036] p=0.9240 |
| task_to_workers_exposed | HR | 0.6903 | 0.6940 | +0.0037 [-0.0020, +0.0097] p=0.2260 |
| task_to_workers_exposed | NDCG | 0.3623 | 0.3632 | +0.0009 [-0.0022, +0.0041] p=0.5340 |
| task_to_workers_exposed | MRR | 0.2627 | 0.2628 | +0.0001 [-0.0033, +0.0036] p=0.9240 |
| worker_to_tasks | HR | 0.0800 | 0.2297 | +0.1497 [+0.1357, +0.1637] p=0.0000 |
| worker_to_tasks | NDCG | 0.0322 | 0.1163 | +0.0841 [+0.0771, +0.0914] p=0.0000 |
| worker_to_tasks | MRR | 0.0183 | 0.0823 | +0.0640 [+0.0577, +0.0704] p=0.0000 |
| worker_to_tasks_exposed | HR | 0.4997 | 0.5083 | +0.0087 [+0.0013, +0.0163] p=0.0240 |
| worker_to_tasks_exposed | NDCG | 0.2307 | 0.2415 | +0.0108 [+0.0071, +0.0145] p=0.0000 |
| worker_to_tasks_exposed | MRR | 0.1506 | 0.1616 | +0.0110 [+0.0073, +0.0149] p=0.0000 |

Target check (strict metrics): **MET**

- worker_to_tasks: NDCG@10 +261.16% relative (CI [+0.0771, +0.0914], excludes
  0) and HR@10 +14.97pp (CI [+0.1357, +0.1637], excludes 0). Both thresholds
  are exceeded, not merely one.
- task_to_workers: HR +0.37pp, NDCG +0.25% — the "other direction" does not
  deteriorate (both delta means ≥ 0). Its CIs cross 0, which is acceptable
  because it only needs to not deteriorate under the conjunctive reading.

## Guardrails

- Constraint violations: **0** (PASS).
- Latency p50/p95: **14.4937 / 29.7125 ms** (comparable to Task 20's
  14.90 / 31.02 ms).
- Cold start: `available=false` — no workers without train assignments in the
  evaluated seeds, `queries=0`, `measured=false`. Reported as N/A, not as a
  passed guardrail (same situation as Task 20).
- Calibration P(rating>=4): available; train 8235 (positive rate 0.9719), test
  2064 (positive rate 0.9666); Brier calibrated **0.0324** vs raw 0.1122;
  Platt a/b 9.7229 / -2.7410. All test predictions fall in the [0.80, 1.00)
  bin (mean predicted 0.9788, observed 0.9666). Calibration is reported only
  and does not affect ranking.

## Files changed

- `scripts/tune_weights.py` — new. `build_choice_candidate`,
  `tune_on_validation`, `evaluate_candidate`, `_validation_split`,
  `_validation_metrics`, `_validation_objective`, CLI, and report writing.
- `tests/test_tune_weights.py` — new. Candidate validity/determinism,
  validation-only tuning (no test access), budget respect, deterministic
  output, weights-file round trip.
- `data/weights/weights_choice.json` — new candidate (seven keys, sum 1).
- `reports/strict_eval_tuned.json`, `reports/strict_eval_tuned.md` — new
  5-seed strict evaluation with the tuned candidate as override.
- This report.

No core model files were modified. No test data was used in features or weight
fitting; the candidate was built on train data and tuned on a train-only
validation split, and the strict evaluator ran on the untouched test set.

## Tests

Focused:

```text
$ python -m pytest tests/test_tune_weights.py -q
7 passed in 1.26s
```

Full suite:

```text
$ python -m pytest tests/ -q
259 passed in 24.51s
```

(Task 20 baseline was 252 tests; the seven new tests bring the suite to 259
with no regressions.)

## Commands

```bash
python scripts/tune_weights.py --seed 42 --budget 20 \
  --seeds 42,43,44,45,46 --k 10
```

This writes `data/weights/weights_choice.json` and
`reports/strict_eval_tuned.json` / `reports/strict_eval_tuned.md`.

## Concerns

1. **Validation noise vs. test transfer.** The coordinate search scored only
   480 validation queries; a small-budget greedy search can chase noise. The
   tuned candidate nevertheless transferred cleanly (validation worker→tasks HR
   0.2063 → test 0.2297), so this did not bite here.
2. **Choice features carry the worker→tasks signal.** The synthetic generator
   logs accept/reject/ignore events per assignment, so pairwise choice learning
   is unusually informative for the worker→tasks direction. The magnitude of
   the +14.97pp gain may not generalize to real logs with sparser choice data.
3. **Cold-start guardrail remains unmeasured** on the default datasets (0 cold
   queries); N/A is reported honestly. A dataset with zero-history workers is
   still needed to exercise it.
4. **Calibration remains near-constant** (~97% of ratings are >=4), so only one
   reliability bin is populated. Raw Brier worsened slightly (0.1043 → 0.1122)
   while calibrated Brier stayed ~0.0324; ranking is unaffected.
5. **task_to_workers CIs cross 0.** This direction is flat-to-slightly-positive
   and is not the basis of the met-target claim; the claim rests on the
   worker→tasks direction with CIs that exclude 0 and the non-deterioration of
   task→workers (means ≥ 0).
6. **Determinism.** `build_choice_candidate` and `tune_on_validation` are
   deterministic (no RNG); the `seed` parameter is accepted for interface
   compatibility but does not affect the result.

## Target status

**MET.** worker→tasks HR@10 +14.97pp (CI [+0.1357, +0.1637]) and NDCG@10
+261.16% (CI [+0.0771, +0.0914]) with the other direction not deteriorating
(task→workers HR +0.37pp, NDCG +0.25%, both means ≥ 0). Constraint
violations 0.
