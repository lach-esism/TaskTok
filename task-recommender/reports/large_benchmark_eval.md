# Large Benchmark — Sampled Evaluation

| item | value |
| --- | --- |
| sampled test tasks | 500 |
| candidates per task | 200 |
| seeds | 42, 43, 44, 45, 46 |
| workers | 1000 |
| tasks | 10000 |

## Protocol

| item | value |
| --- | --- |
| eval split | test |
| similarity graph | train-split accepted assignments only |
| worker history | train-split accepted assignments only |
| candidate pool | gold + 199 random workers |
| gold definition | latent-best worker in the exposure pool |
| exposure pool size | 10 |
| feature weights | SIM_INITIAL_WEIGHTS |

Gold is the latent-best worker (argmax of the DGP true-match score) inside the task's exposure pool, not an accepted-only label. 7681 / 10000 gold workers (76.81%) accepted their task. Each 200-candidate pool is the gold worker plus 199 uniformly sampled workers.

## Metrics (mean ± std across seeds)

| item | value |
| --- | --- |
| TOP1 | 0.0660 ± 0.0070 |
| TOP5 | 0.2704 ± 0.0092 |
| MRR | 0.1795 ± 0.0060 |
| NDCG | 0.1672 ± 0.0068 |

## Baselines

| baseline | Top-1 | Top-5 | MRR | NDCG |
| --- | --- | --- | --- | --- |
| feature-only (no collaborative) | 0.0660 ± 0.0070 | 0.2704 ± 0.0092 | 0.1795 ± 0.0060 | 0.1672 ± 0.0068 |
| uniform random (analytical) | 0.0050 | 0.0250 | n/a | n/a |

The feature-only baseline uses the same six observable features and weights with the collaborative term removed. The analytical random baseline is 1/200 Top-1 and 5/200 Top-5. Random is only a scale reference, not a fair model comparison: gold is latent-best inside a 10-worker exposure pool and the 199 distractors are uniformly random, so most distractors are not plausible candidates. The feature-only baseline is the meaningful reference for the ItemCF contribution.

## Per-seed metrics

| seed | top1 | top5 | mrr | ndcg |
| --- | --- | --- | --- | --- |
| 42 | 0.054 | 0.266 | 0.1705 | 0.1598 |
| 43 | 0.064 | 0.256 | 0.1755 | 0.1592 |
| 44 | 0.066 | 0.272 | 0.1797 | 0.169 |
| 45 | 0.072 | 0.274 | 0.1846 | 0.1712 |
| 46 | 0.074 | 0.284 | 0.187 | 0.1769 |

## ItemCF wiring (strict train-only graph)

| item | value |
| --- | --- |
| similarity interactions (train accepted) | 49323 |
| history interactions (train accepted) | 49323 |
| similarity splits | ["train"] |
| history splits | ["train"] |
| similarity is train-only | True |
| history is train-only | True |
| accepted interactions total | 61631 |
| excluded test accepted interactions | 12308 |
| collaborative pool-normalized | True |
| collaborative nonzero rate | 0.00% |

The similarity graph and the worker history are both built from train-split accepted assignments only. A held-out test task therefore has no ItemCF co-occurrence edges and is a cold-start item, so the collaborative term is zero for every test-task candidate under this protocol. This is the strict, leak-free result; the pre-fix graph used test-task co-occurrences and was optimistic.

## Data quality

| item | value |
| --- | --- |
| task exact / title / near duplicates | 0 / 0 / 0 |
| resume exact / near duplicates | 0 / 0 |
| task near-dup rate | 0.0000% |
| resume near-dup rate | 0.0000% |
| task unique titles | 10000 / 10000 |
| task_text mean length | 210.8 |
| resume_text mean length | 393.0 |
