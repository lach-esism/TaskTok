# Task 20 Report: End-to-End Strict Evaluation, Benchmark Re-Baseline, and Docs

## Status

DONE_WITH_CONCERNS — implementation and documentation are complete and all tests
pass, but the accuracy target is **NOT MET** under the conservative conjunctive
reading. No success is claimed.

## What was implemented

1. **Docs test** — created `tests/test_docs.py` with the two mandated checks
   (`/events` / `evaluate_strict.py` / `strict_eval` in README;
   `RecommendationEvent` / `propensity` / `strict` in the flow doc).
2. **Calibration wired into the strict report** (`app/evaluation_strict.py`):
   - `evaluate_strict()` now collects candidate-weight scores for every train
     assignment with feedback and every test assignment with feedback.
   - Scores use the same serving-parity `RecommendationService.features_for`
     path as the recommender, fused with the candidate weights; the store is
     train-only and test feedback is used only as labels.
   - `PlattCalibrator` is fit on pooled train `(score, rating>=4)` pairs.
   - The test side reports Brier (calibrated), Brier (raw score), the fitted
     Platt `a`/`b`, and five equal-width reliability bins.
   - Unavailable calibration (fewer than 10 train pairs, one train class, or
     no test pairs) sets `available: false` with a reason and leaves Brier, bins,
     and coefficients as `null`/empty instead of fabricating values.
3. **Report rendering** (`scripts/evaluate_strict.py`):
   - Calibration section with Brier and reliability bins.
   - Cold start now reports `measured` and `cold queries`; a zero-query subset
     is rendered as `n/a (cold-start subset not measured)`, never as a pass.
   - Automated target check for the NDCG relative / HR pp thresholds, 95% CIs,
     constraint violations, cold-start status, calibration, and benchmark
     pointer. A gap line is emitted when the target is not met.
4. **Documentation**:
   - `README.md`: new “推荐机制改进” section covering `/events`,
     `/events/metrics`, exact propensity, choice learning estimating only the
     seven linear weights, `scripts/evaluate_strict.py`, strict metrics,
     cold-start availability, calibration, and the benchmark `collaborative`
     deferral. Added API rows and the exact five-seed command.
   - `docs/recommendation-flow.md`: new flow block, `RecommendationEvent` /
     impression / exact propensity section, strict-evaluation section,
     calibration note, benchmark deferral note, and code index entries.

## Tests / CLI output

Focused tests:

```text
$ python -m pytest tests/test_docs.py tests/test_strict_eval.py tests/test_calibration.py -q
18 passed
```

Full suite:

```text
$ python -m pytest tests/ -q
244 passed in 21.00s
```

Strict evaluation:

```bash
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 \
  --candidate-weights data/weights/weights_v0007.json
```

Candidate source `override`; `baseline_equals_candidate: false`; candidate
weights = `data/weights/weights_v0007.json` (sum 1.0). Reports written to
`reports/strict_eval.json` and `reports/strict_eval.md`.

Benchmark re-baseline:

```bash
python scripts/run_benchmark_rounds.py --rounds 10
```

Reports written to `reports/benchmark_rounds.json` and
`reports/benchmark_rounds.md`.

## Measured strict deltas and CIs (k=10, 5 seeds, baseline=DEFAULT_WEIGHTS, candidate=v0007)

| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |
|---|---|---|---|---|
| task_to_workers | HR | 0.6717 | 0.6700 | -0.0017 [-0.0060, +0.0030] p=0.5140 |
| task_to_workers | NDCG | 0.3555 | 0.3559 | +0.0004 [-0.0013, +0.0021] p=0.5920 |
| task_to_workers | MRR | 0.2593 | 0.2602 | +0.0009 [-0.0004, +0.0025] p=0.1980 |
| task_to_workers_exposed | HR | 0.6903 | 0.6887 | -0.0017 [-0.0060, +0.0030] p=0.5140 |
| task_to_workers_exposed | NDCG | 0.3623 | 0.3627 | +0.0004 [-0.0013, +0.0021] p=0.5920 |
| task_to_workers_exposed | MRR | 0.2627 | 0.2636 | +0.0009 [-0.0004, +0.0025] p=0.1980 |
| worker_to_tasks | HR | 0.0800 | 0.1220 | +0.0420 [+0.0350, +0.0493] p=0.0000 |
| worker_to_tasks | NDCG | 0.0322 | 0.0506 | +0.0184 [+0.0159, +0.0211] p=0.0000 |
| worker_to_tasks | MRR | 0.0183 | 0.0296 | +0.0113 [+0.0096, +0.0132] p=0.0000 |
| worker_to_tasks_exposed | HR | 0.4997 | 0.5003 | +0.0007 [-0.0043, +0.0053] p=0.8260 |
| worker_to_tasks_exposed | NDCG | 0.2307 | 0.2338 | +0.0031 [+0.0011, +0.0052] p=0.0040 |
| worker_to_tasks_exposed | MRR | 0.1506 | 0.1544 | +0.0037 [+0.0018, +0.0057] p=0.0000 |

Other guardrails: constraint violations = 0; latency p50/p95 =
14.5694 / 30.2530 ms.

### Target result: NOT MET

- task_to_workers: NDCG +0.11% relative, HR -0.17pp; both CIs cross 0.
- worker_to_tasks: NDCG +57.12% relative with CI [+0.0159, +0.0211] (>0) and
  HR +4.20pp (below the alternative 5pp threshold).
- The strict conjunctive reading (“other direction does not deteriorate”)
  fails because task_to_workers HR is -0.17pp, even though its NDCG is +0.11%.
  `reports/strict_eval.md` records `status: NOT MET` and a gap line.
- A relative NDCG gain on a low absolute baseline (0.0322 -> 0.0506) is not
  treated as success by itself.

## Cold-start availability

- `cold_start.available`: **false**
- reason: `no workers without train assignments in the evaluated seeds`
- `cold_start.measured`: **false**, cold queries = **0**
- All cold-start deltas are rendered `n/a (cold-start subset not measured)`;
  the report does not present this as a passed guardrail.

## Calibration results (P(rating>=4), candidate weights)

- available: **true**
- train samples: 8235 (positive rate 0.9719)
- test samples: 2064 (positive rate 0.9666)
- Brier (calibrated): **0.0324**
- Brier (raw score): **0.1043**
- Platt a/b: 12.3320 / -4.6111
- Reliability bins (test): all 2064 predictions fall in `[0.80, 1.00)`, with
  mean predicted 0.9804 and observed rate 0.9666; the four lower bins are
  empty and rendered `n/a` (not zero-filled).
- Calibration is reported only; it does not affect ranking.

## Benchmark re-baseline

Current code (after Task 3 features and Task 14 benchmark changes), 10 rounds:

| Round | Top-1 | Top-5 | Test Top-1 |
|---|---|---|---|
| 1 (fresh baseline) | 0.3670 | 0.8720 | 0.3650 |
| 5 | 0.5300 | 0.9530 | 0.5450 |
| 10 | 0.5680 | 0.9460 | 0.5800 |

Round 10 Top-1 0.5680 is not worse than the fresh round-1 baseline 0.3670
(+0.2010). Test Top-1 rises 0.3650 -> 0.5800. In absolute terms the current
R10 Top-1 `0.5680` is **lower than the historical R10 `0.7310` (-0.1630)**;
the historical number came from old data/features and is not directly
comparable, and no recovery to the historical level is claimed.

**Deferred ItemCF:** `BenchmarkRecommender` does not pass an `ItemCF` into
`BenchmarkFeatureBuilder`, so the benchmark `collaborative` feature is 0.0 for
every candidate. Its learned weight (0.1000 -> 0.0943) has no effect on
ranking. This is documented in `README.md`, `docs/recommendation-flow.md`, and
the appended note in `reports/benchmark_rounds.md`. Task 21 wires ItemCF and
candidate-pool normalization into the large benchmark.

## Files changed

- `README.md` — new recommendation-improvement section, API rows, updated
  10-round table, benchmark deferral note, test count.
- `docs/recommendation-flow.md` — new flow, events/propensity section, strict
  evaluator section, calibration, benchmark deferral, code index, updated
  benchmark table.
- `app/evaluation_strict.py` — calibration score collection, Platt fit,
  Brier/reliability report, unavailability handling.
- `scripts/evaluate_strict.py` — calibration rendering, cold-start
  measured/queries status, target check and gap line, calibration in CLI JSON.
- `tests/test_docs.py` — new docs contract test.
- `tests/test_strict_eval.py` — calibration available/unavailable tests, CLI
  rendering test, candidate-weight validation test.
- `reports/strict_eval.json`, `reports/strict_eval.md` — regenerated with the
  real `weights_v0007.json` candidate.
- `reports/benchmark_rounds.json`, `reports/benchmark_rounds.md` — regenerated
  10-round re-baseline plus deferral note.

## Self-review findings

- The small test fixture only generates ratings 4–5; the first calibration test
  therefore initially hit the single-class unavailable path (correct behavior).
  The test now forces a deterministic mix (every fourth rating = 3) so both
  the available and unavailable paths are covered.
- `_target_lines` originally indexed an empty “other direction” list if both
  directions qualified; fixed to treat that as met.
- Calibration scores are candidate-mode scores; test feedback is used only as
  labels and never enters the train-only store or features.
- Reliability bins use `None` (rendered `n/a`) for empty bins rather than 0.0.
- The final `strict_eval.md` was re-rendered from the saved JSON after
  report-only string edits; the evaluation result itself was produced by the
  same evaluation logic.
- Cold-start zeros are never shown as a passed guardrail.

## Concerns

1. **Accuracy target unmet.** The only large relative gain is worker→tasks
   NDCG on a low absolute baseline; task→workers HR/NDCG are flat and the HR
   +5pp threshold is not reached. No accuracy improvement claim is made.
2. **Cold-start guardrail not measured** on the default datasets; N/A is
   reported. A dataset with zero-history workers is needed to exercise it.
3. **Calibration is highly imbalanced** (97% of ratings are >=4), so the
   calibrator is near-constant and only one reliability bin is populated.
   Brier is better than raw, but the evidence is narrow.
4. **Benchmark collaborative remains dead** until Task 21; benchmark weight
   changes in that dimension are not meaningful.
5. **Runtime**: the five-seed strict run takes roughly 10 minutes on this
   machine.
6. **Fresh baseline provenance**: the Task 0 ledger recorded the test baseline
   (150 passed) but not a benchmark Top-1; per the brief, the benchmark was
   re-run after the features change and round 1 of this run is used as the
   fresh baseline.

## Unmet target / follow-up

Accuracy target is **not met**. Recommended follow-up (Task 21 scope):
wire ItemCF and candidate-pool normalization into the benchmark; then run a
real weight-learning/selection experiment (using the event/pairwise/listwise
signals) against the same five-seed strict protocol before making an accuracy
claim.

---

# Fix Report (Review Round 1)

## Findings addressed

1. **Exact-propensity docs corrected.** `README.md`, `docs/recommendation-flow.md`
   §2.9, and §2.11 no longer say exploited=0.9 / explored=1/N. They now state
   the implementation's inclusion probabilities:
   `top-(K-1)=1.0`, rank K=`(1-ε)+ε/(N-K+1)`, tail=`ε/(N-K+1)`, and
   `p=1.0` when `N<=K`.
2. **Leakage sentence corrected.** README and the flow doc now state that the
   train-only Store constructs features; test data is used only for scoring
   (ranking/HR/NDCG/MRR) and calibration evaluation labels (`rating>=4`), and
   never for feature construction or weight learning. Test impressions may only
   define the `exposed` candidate set and are not written to the Store.
3. **Actual strict command documented.** Both docs now show
   `python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 \`
   `--candidate-weights data/weights/weights_v0007.json`, with a warning that
   omitting the option can produce an identity report and overwrite the
   published one.
4. **Cold-start machine fields added to JSON.** `app/evaluation_strict.py` now
   returns `cold_start.queries` and `cold_start.measured` in addition to
   `available`/`reason`. `measured` is true only when `available` is true and
   `queries > 0`. The CLI JSON printout and both docs use these fields, and the
   Markdown renders a zero-query subset as N/A.
5. **Benchmark narrative made explicit.** README, the flow doc,
   `reports/benchmark_rounds.md`, and `reports/benchmark_visual.md` now state
   the absolute comparison: current R10 Top-1 `0.5680` is below historical R10
   `0.7310` (-0.1630), in addition to the fresh-baseline comparison
   (R10 0.568 vs R1 0.367). Charts were regenerated with
   `python scripts/plot_benchmark.py`; `benchmark_visual.md` was updated to the
   current 10-round table.
6. **Behavioral tests added** (not only doc substrings):
   - target check `MET`, `NOT MET`, `NOT MET` when the other direction
     deteriorates, and `n/a` for identity weights;
   - cold-start JSON `queries`/`measured` invariant and zero-query Markdown
     rendering as `n/a (cold-start subset not measured)`;
   - seven-key candidate validation rejecting partial, extra-key, negative,
     and non-unit-sum payloads;
   - effective-weight identity (exact, within `1e-9`, and a real 1pp change);
   - docs tests for the exact propensity formula, candidate-weights command,
     and cold-start field names.
7. **End-to-end re-runs after schema/rendering changes.**

## Commands and output

```text
$ python -m pytest tests/test_strict_eval.py tests/test_docs.py -q
22 passed in 3.39s

$ python -m pytest tests/ -q
252 passed in 23.09s

$ python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 \
    --candidate-weights data/weights/weights_v0007.json
# candidate_source=override, baseline_equals_candidate=false,
# constraint_violations=0, latency p50/p95 14.9012/31.0207 ms

$ python scripts/run_benchmark_rounds.py --rounds 10
# R1 top1=0.367, R10 top1=0.568, test R10 top1=0.580
```

## Strict result after re-run (unchanged measured deltas)

- task_to_workers: HR 0.6717 -> 0.6700 (-0.17pp, CI [-0.0060,+0.0030]),
  NDCG 0.3555 -> 0.3559 (+0.11%, CI [-0.0013,+0.0021]).
- worker_to_tasks: HR 0.0800 -> 0.1220 (+4.20pp, CI [+0.0350,+0.0493]),
  NDCG 0.0322 -> 0.0506 (+57.12%, CI [+0.0159,+0.0211]).
- target status: **NOT MET** (conjunctive reading; task_to_workers HR is
  slightly negative and the HR +5pp alternative is not reached). Gap recorded
  in `reports/strict_eval.md`.
- `cold_start`: `available=false`, `reason=no workers without train
  assignments in the evaluated seeds`, `queries=0`, `measured=false` -> N/A.
- calibration: train 8235 (positive 0.9719), test 2064 (positive 0.9666);
  Brier calibrated 0.0324 vs raw 0.1043; all test predictions in the
  [0.80,1.00) bin (mean predicted 0.9804, observed 0.9666).

## Files changed in this fix round

- `README.md`
- `docs/recommendation-flow.md`
- `app/evaluation_strict.py`
- `scripts/evaluate_strict.py`
- `tests/test_docs.py`
- `tests/test_strict_eval.py`
- `reports/strict_eval.json`, `reports/strict_eval.md`
- `reports/benchmark_rounds.json`, `reports/benchmark_rounds.md`
- `reports/benchmark_visual.md`, `reports/benchmark_curve*.png/svg`

## Remaining gaps / parked minors

- Accuracy target remains **NOT MET**; no improvement claim is made.
- Benchmark R10 Top-1 is below the historical R10 (0.568 vs 0.731); the
  historical number is not directly comparable, but no recovery is claimed.
- Cold-start guardrail is unmeasured on the default datasets (0 cold queries).
- Calibration is near-constant because ~97% of ratings are >=4; only one
  reliability bin is populated.
- Benchmark `collaborative` remains 0.0 until Task 21 wires ItemCF.
- Parked minors intentionally not changed: target-check CI asymmetry,
  low-baseline caveat threshold, benchmark Top-1 machine check, mid-module
  test imports.
