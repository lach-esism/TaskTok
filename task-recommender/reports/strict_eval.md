# Strict Evaluation

- Seeds: 42, 43, 44, 45, 46
- k: 10
- Candidate source: override
- Candidate weights: {"collaborative": 0.034023777334, "customer_preference": 0.045612047514, "expertise": 0.277518489448, "load": 0.04893876013, "preference": 0.057919218554, "reputation": 0.36767264253, "skill": 0.168315064489}
- baseline_equals_candidate: false
- Constraint violations: 0
- In-process scoring p50/p95 (NOT HTTP endpoint latency): 9.5273 / 19.8627 ms
- HTTP endpoint latency guardrail: N/A (the strict evaluator calls the in-process ranking service; HTTP endpoint latency is not measured)

## Baseline vs candidate (HR@10, NDCG@10, MRR@10)

| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |
|---|---|---|---|---|
| task_to_workers | hr | 0.6737 | 0.6797 | +0.0060 [+0.0007, +0.0123] p=0.0380 |
| task_to_workers | ndcg | 0.3569 | 0.3577 | +0.0008 [-0.0021, +0.0038] p=0.6120 |
| task_to_workers | mrr | 0.2605 | 0.2598 | -0.0007 [-0.0040, +0.0025] p=0.6760 |
| task_to_workers_exposed | hr | 0.6923 | 0.6983 | +0.0060 [+0.0007, +0.0123] p=0.0380 |
| task_to_workers_exposed | ndcg | 0.3637 | 0.3645 | +0.0008 [-0.0021, +0.0038] p=0.6120 |
| task_to_workers_exposed | mrr | 0.2639 | 0.2632 | -0.0007 [-0.0040, +0.0025] p=0.6760 |
| worker_to_tasks | hr | 0.0637 | 0.2070 | +0.1433 [+0.1307, +0.1563] p=0.0000 |
| worker_to_tasks | ndcg | 0.0258 | 0.0991 | +0.0733 [+0.0671, +0.0796] p=0.0000 |
| worker_to_tasks | mrr | 0.0148 | 0.0669 | +0.0521 [+0.0468, +0.0577] p=0.0000 |
| worker_to_tasks_exposed | hr | 0.4950 | 0.5077 | +0.0127 [+0.0040, +0.0204] p=0.0080 |
| worker_to_tasks_exposed | ndcg | 0.2273 | 0.2417 | +0.0145 [+0.0106, +0.0182] p=0.0000 |
| worker_to_tasks_exposed | mrr | 0.1476 | 0.1623 | +0.0148 [+0.0107, +0.0187] p=0.0000 |

## Cold start (workers with no train assignments)

- available: false
- reason: no workers without train assignments in the evaluated seeds
- queries: 0
- measured: false

| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |
|---|---|---|---|---|
| task_to_workers | hr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| task_to_workers | ndcg | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| task_to_workers | mrr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| task_to_workers_exposed | hr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| task_to_workers_exposed | ndcg | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| task_to_workers_exposed | mrr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| worker_to_tasks | hr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| worker_to_tasks | ndcg | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| worker_to_tasks | mrr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| worker_to_tasks_exposed | hr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| worker_to_tasks_exposed | ndcg | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |
| worker_to_tasks_exposed | mrr | 0.0000 | 0.0000 | n/a (cold-start subset not measured) |

## Calibration: P(rating>=4)

> Calibration is reported for interpretability only. It does not affect ranking.

- available: true
- reason: n/a
- label: rating>=4
- train samples: 8235 (positive rate 0.9719)
- test samples: 2064 (positive rate 0.9666)
- Brier (calibrated): 0.0323
- Brier (raw score): 0.1186
- Platt a/b: 10.9652 / -3.5031

Reliability bins (test):

| Bin | Count | Mean predicted | Observed rate |
|---|---|---|---|
| [0.00, 0.20) | 0 | n/a | n/a |
| [0.20, 0.40) | 0 | n/a | n/a |
| [0.40, 0.60) | 0 | n/a | n/a |
| [0.60, 0.80) | 0 | n/a | n/a |
| [0.80, 1.00) | 2064 | 0.9778 | 0.9666 |

## Target check (strict metrics)

Accuracy target: NDCG@10 relative improvement ≥10% or HR@10 ≥5pp in at least one primary direction, and the other primary direction does not deteriorate.

| Direction | NDCG@10 rel | HR@10 pp | NDCG CI | HR CI |
|---|---|---|---|---|
| task_to_workers | +0.21% | +0.60 | [-0.0021, +0.0038] | [+0.0007, +0.0123] |
| worker_to_tasks | +283.55% | +14.33 | [+0.0671, +0.0796] | [+0.1307, +0.1563] |

- status: MET
- Constraint violations: 0 (PASS)
- Cold start: N/A (not measured) (queries=0)
- Calibration: reported above (ranking unaffected)
- Latency guardrail: N/A (the strict evaluator calls the in-process ranking service; HTTP endpoint latency is not measured)
- Benchmark re-baseline: see reports/benchmark_rounds.md
