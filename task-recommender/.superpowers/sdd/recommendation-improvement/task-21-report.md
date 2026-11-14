# Task 21 Report — Large Natural-Language Benchmark (scheme E)

**Status:** DONE_WITH_CONCERNS (all review findings addressed; remaining notes in §17)
**Date:** 2026-11-14
**Artifacts:** `data/benchmark/task_benchmark_large.sqlite` (25 MB), `data/benchmark/task_benchmark_large.jsonl` (35 MB)
**Reports:** `reports/large_benchmark_stats.md`, `reports/large_benchmark_eval.md`

---

## 0. Review fix log (round 1)

The first version of this report and the evaluation were wrong about test leakage.
The reviewer found that the ItemCF similarity graph was built from **all** accepted
assignments, including 12,308 accepted test-split interactions, so a worker's own
test acceptance could enter the score. This round fixed all five findings and
regenerated the artifacts and reports.

### Critical — train-only ItemCF (fixed)

- `evaluate_large()` now builds **both** the similarity graph and the worker
  history with `build_itemcf(assignments, split="train")`. No test-task
  co-occurrence can enter either graph.
- `similarity_splits` and `history_splits` are derived from the actual
  `(worker_id, task_id)` edges in each ItemCF object mapped back to assignment
  rows; the report reads the derived values instead of a hard-coded flag.
- A held-out test task is therefore a **cold-start item** for ItemCF: the
  collaborative term is 0 for every test-task candidate under the strict
  protocol (`collaborative_nonzero_rate = 0.00%`). This is the correct,
  leak-free result. The feature-only baseline and the strict full result
  coincide for that reason.
- Regression tests added:
  - `test_test_split_assignments_cannot_affect_itemcf_or_scores` asserts
    `item_users`, `item_similarity` and held-out-task scores are unchanged when
    test-split accepted rows are added.
  - `test_mutating_test_assignments_does_not_change_evaluation` flips a stored
    test assignment to rejected and asserts evaluation metrics and all
    train-only ItemCF counts are identical.
  - `test_evaluate_large_is_train_only_and_reports_baselines` asserts
    `similarity_splits == ["train"]`, `history_splits == ["train"]`, both
    train-only flags, and the excluded-test count.

### Important — model-facing exports (fixed)

- `load_large_sqlite(path, include_test_outcomes=False)` redacts test-split
  `status`/`on_time`/`rating`/`rework` (`status="unknown"`, outcomes `None`) and
  drops `stat:*` metadata (build-time stats aggregate test outcomes). Train
  rows are returned intact.
- `export_large_jsonl(..., include_test_outcomes=False)` applies the same
  redaction, writes an `outcome_policy` block, and no longer writes the
  build-time `stats` object.
- The raw SQLite database remains the evaluator artifact and is read by
  `LargeRepository`; evaluator-only label access is unchanged.
- Verifier now asserts 0 test-outcome leaks in both the model-safe loader and
  the JSONL, and that the JSONL meta has no `stats`/`stat:*` keys.

### Important — gold/baseline documentation (fixed)

- The eval report now states that gold is the **latent-best worker (argmax of
  the DGP true-match score) inside the task's exposure pool**, not an
  accepted-only label; the exposure pool is 10 workers; 7,681 / 10,000
  (76.81%) gold workers accepted their task; each 200-candidate pool is gold +
  199 uniformly sampled workers.
- Added a **feature-only baseline** (same six observable features, no
  collaborative term) and an analytical uniform-random baseline (Top-1 0.005,
  Top-5 0.025). The report qualifies the random comparison: gold is latent-best
  in a 10-worker exposure pool and 199 distractors are random, so random is
  only a scale reference, not a fair model comparison.

### Important — resume coherence (fixed)

- Project roles, bullets and results are now sampled as **one category project
  template** (profile project name + role + bullet + result together), so a
  video resume cannot show an API-latency result and a video worker cannot get
  an AWS certificate. Companies and certificates are category-specific too.
- Resume regeneration produced 0 category-coherence violations in the
  independent verifier and a dedicated test
  (`test_resume_results_and_certs_are_category_consistent`).
- New coherent samples are in §8.

### Minors (fixed)

- Duplicate statistics are now **computed from the emitted corpus** (normalized
  SHA-256 exact count, normalized title count, fresh simhash near-dup index);
  exact/title/near counters are separate from generator resample counters.
- The TF-IDF vectorizer in `LargeFeatureBuilder` is fit on **worker resumes +
  train-split task text only**; test task text is transformed with the frozen
  vocabulary. `transductive=False` is recorded; the old behavior is available
  only by explicitly passing `train_task_ids=None`.
- Duplicated feature/scoring logic between `app/benchmark/features.py` and
  `app/benchmark/large.py` is **parked** (documented, not refactored in this
  task).

### Strict-vs-pre-fix metrics

| metric | pre-fix (leaky, old report) | strict train-only |
| --- | --- | --- |
| Top-1 | 0.0812 ± 0.0068 | **0.0660 ± 0.0070** |
| Top-5 | 0.3276 ± 0.0137 | **0.2704 ± 0.0092** |
| MRR | 0.2129 ± 0.0051 | **0.1795 ± 0.0060** |
| NDCG@5 | 0.2053 ± 0.0080 | **0.1672 ± 0.0068** |

The strict drop is expected and correct. The reviewer's partial-removal numbers
(0.0524 / 0.1960) came from a different partial fix; this implementation removes
**all** test-task co-occurrences, so the collaborative feature is cold-start
(zero) for held-out tasks and the strict result equals the feature-only
baseline. The pre-fix and strict runs also differ slightly in resume text and
vectorizer fitting, so the delta is directional rather than a controlled A/B.

---

## 1. Generated counts (verified from SQLite)

| item | value |
| --- | --- |
| workers | 1,000 |
| tasks | 10,000 |
| customers | 500 |
| assignments | 100,000 |
| splits rows | 10,000 |
| labels rows | 10,000 |
| accepted assignments | 61,631 |
| rejected assignments | 38,369 |
| seed / scheme | 42 / E |

JSONL cross-check: 1 meta, 1,000 workers, 10,000 tasks, 500 customers, 100,000
assignments, 10,000 split records. Task/resume texts are byte-identical to the
SQLite rows in the same order.

---

## 2. Duplicate and near-duplicate statistics (computed from data)

| check | result |
| --- | --- |
| task exact duplicates (normalized SHA-256) | 0 |
| task title duplicates (normalized title) | 0 |
| task near-duplicate collisions (simhash Hamming ≤ 3) | 0 / 10,000 (0.0000%) |
| distinct task simhashes | 10,000 / 10,000 |
| resume exact duplicates | 0 |
| resume near-duplicate collisions | 0 / 1,000 (0.0000%) |
| distinct resume simhashes | 1,000 / 1,000 |
| generator resamples (tasks / resumes) | 651 / 1,641 |

**Exact-duplicate rate = 0; near-duplicate rate = 0.0000% < 0.5%.** ✅
Counters are recomputed from the emitted texts; the independent verifier used a
separate 4×16-bit pigeonhole index and reproduced 0 collisions.

---

## 3. Distributions

### Category (12, near-uniform quota)

brand_design 834 · consulting_research 833 · content_writing 834 ·
data_annotation 833 · ecommerce_ops 833 · marketing_campaign 833 ·
recruitment 833 · software_dev 834 · training_course 833 ·
translation_localization 833 · ui_ux_design 834 · video_production 833

### Industry (20, 500 each)

人力资源, 企业服务, 农业, 制造业, 医疗健康, 半导体, 宠物, 家居, 教育, 文旅,
新能源, 新能源汽车, 游戏, 物流, 美妆, 跨境电商, 连锁餐饮, 酒旅, 金融科技, 零售.

### Budget / duration / text lengths

| item | min | mean | max |
| --- | --- | --- | --- |
| budget midpoint (CNY) | 3,850 | 13,075 | 28,800 |
| duration (days) | 3 | 20.1 | 60 |
| `task_text` chars | 167 | 210.8 | 280 |
| `resume_text` chars | 356 | 393.0 | 449 |

All 10,000 task texts and 1,000 resume texts are non-empty and contain CJK text
and sentence punctuation. Resume completeness is 100% for name, city, skills,
projects, certifications and experience.

### Assignment outcomes

| item | value |
| --- | --- |
| rating distribution | 1: 2,421 · 2: 14,218 · 3: 14,554 · 4: 18,356 · 5: 12,082 |
| on-time rate (accepted) | 59.50% |
| gold accepted the task | 7,681 / 10,000 (76.81%) |
| distinct gold workers | 964 |
| max gold share | 0.58% |

---

## 4. Split statistics

| split | tasks | assignments | accepted | rejected | mean rating | on-time |
| --- | --- | --- | --- | --- | --- | --- |
| train | 8,000 | 80,000 | 49,323 | 30,677 | 3.381 | 59.41% |
| test | 2,000 | 20,000 | 12,308 | 7,692 | 3.378 | 59.90% |

Every assignment's split equals its task's split; every label's split equals its
task's split; label task ids equal split task ids.

---

## 5. Gold definition and candidate pool

- **Gold:** the latent-best worker, i.e. `argmax` of the DGP true-match score,
  inside the task's **10-worker exposure pool**. It is not an accepted-only
  label; 76.81% of gold workers accepted their task.
- **Candidate pool:** 200 workers = the gold worker + 199 uniformly sampled
  workers from the other 999.
- **Strict evaluation:** 500 test tasks × 200 candidates × 5 seeds
  (42–46), deterministic sampling, fixed `SIM_INITIAL_WEIGHTS`.
- **Baselines:** feature-only (same six observable features, collaborative
  removed) and analytical uniform random (Top-1 0.005, Top-5 0.025). Because
  the strict ItemCF is cold-start on all held-out tasks, strict full and
  feature-only are identical. Random is only a scale reference; it is not a
  fair model comparison because gold is latent-best in a 10-worker pool and the
  199 distractors are uniformly random.

---

## 6. Strict sampled evaluation

### Headline metrics (mean ± std across 5 seeds)

| metric | value |
| --- | --- |
| Top-1 | **0.0660 ± 0.0070** |
| Top-5 | **0.2704 ± 0.0092** |
| MRR | **0.1795 ± 0.0060** |
| NDCG@5 | **0.1672 ± 0.0068** |

### Per seed

| seed | Top-1 | Top-5 | MRR | NDCG |
| --- | --- | --- | --- | --- |
| 42 | 0.054 | 0.266 | 0.1705 | 0.1598 |
| 43 | 0.064 | 0.256 | 0.1755 | 0.1592 |
| 44 | 0.066 | 0.272 | 0.1797 | 0.1690 |
| 45 | 0.072 | 0.274 | 0.1846 | 0.1712 |
| 46 | 0.074 | 0.284 | 0.1870 | 0.1769 |

### Baselines

| baseline | Top-1 | Top-5 | MRR | NDCG |
| --- | --- | --- | --- | --- |
| feature-only (no collaborative) | 0.0660 ± 0.0070 | 0.2704 ± 0.0092 | 0.1795 ± 0.0060 | 0.1672 ± 0.0068 |
| uniform random (analytical) | 0.0050 | 0.0250 | n/a | n/a |

Re-running `evaluate_large(...)` against the final DB reproduced these numbers
exactly.

---

## 7. ItemCF wiring (strict train-only graph; Task 14 deferral closure)

| item | value |
| --- | --- |
| similarity interactions (train accepted) | 49,323 |
| history interactions (train accepted) | 49,323 |
| similarity splits / history splits | `["train"]` / `["train"]` |
| similarity is train-only / history is train-only | True / True |
| accepted interactions total | 61,631 |
| excluded test accepted interactions | 12,308 |
| collaborative pool-normalized | True |
| collaborative nonzero rate (test tasks) | 0.00% |

The similarity graph and the worker history are both built from train-split
accepted assignments only. A held-out test task therefore has no ItemCF
co-occurrence edges and is a cold-start item, so its collaborative term is 0
for every candidate. This is the leak-free strict result; the pre-fix graph
used test-task co-occurrences and was optimistic. Pool normalization (divide by
the candidate-pool maximum) is still applied, closing the Task 14 deferral; the
focus test `test_itemcf_wiring_and_pool_normalization` covers the math and
`test_evaluate_large_wires_real_itemcf` covers the wiring.

---

## 8. Sample texts (final, category-coherent)

**t00001 (train, 宠物用品电商门店带教体系搭建（多语言版）)**

> 宠物用品电商门店带教体系搭建（多语言版）。品类消费频次高，客户希望通过内容与运营提升复购，因此客户希望借助外部团队完成门店带教体系搭建。我们希望找到符合以下条件的合作方：有企业培训或课程开发经验并能提供课程案例；能设计练习、考试与效果评估；能根据反馈迭代课程内容；具备现场或线上授课能力；需要熟悉课件开发、人力资源。主要交付物包括课程大纲、课件与练习、讲师手册、考试/评估方案。本项目报酬 5,000–25,000 元，交付周期 11 天，支持远程协作，按里程碑同步进度。

**t02500 (test, 电竞平台黑五促销策划（重构）)**

> 电竞平台黑五促销策划（重构）。用户增长竞争激烈，客户需要持续的内容与活动供给，客户决定启动黑五促销策划项目并期待尽快见效。我们希望找到符合以下条件的合作方：能跟踪核心指标并输出复盘；能完成策略、创意、渠道与预算规划；有相关行业资源优先；对转化与声量目标负责；要求掌握数据分析、创意策划。需要交付渠道排期、创意与物料、复盘报告、活动策略、执行方案。预算 5,300–31,500 元，期望 23 天内完成，需要与美国团队线下协作，按里程碑验收。

**w0001 — 唐子欣 (video production, US)**

> 唐子欣，现居旧金山，视频制作方向。UC Berkeley · 数字媒体艺术学士。10 年经验，聚焦视频制作方向，完成 80 个项目，客户评分 3.6/5。技能：配音与音频、剪辑后期、行业研究、界面设计、视频制作、视觉设计、部署运维、测试与质量。工作经历：曾在光年影像担任资深剪辑师（2023 至今），负责关键指标跟踪与周期性复盘；此前在野火视频担任内容制作负责人（2016 至 2023），参与方案评审并推动落地。项目经历：代表项目《618 家电品牌信息流短视频》，担任导演/剪辑，完成 6 条 30 秒竖屏素材，投放 CTR 高于行业均值 35%；代表项目《新能源汽车功能介绍视频》，担任视频负责人，脚本、拍摄与三维演示整合，用于发布会与门店循环播放。专业认证：DaVinci Resolve 认证、Adobe 认证剪辑师。本周可投入 41 小时，支持远程协作，期望报酬 ¥1,574–2,283/天。

**w0002 — 程明舒 (recruitment, CN)**

> 程明舒，现居广州，招聘方向。上海交通大学 · 人力资源管理硕士。10 年经验，聚焦招聘方向，完成 35 个项目，客户评分 2.9/5。熟练领域：排版发布、编辑审校、人力资源、人才寻访、内容写作、面试评估、招聘、行业研究。工作经历：曾在远航人才担任猎头顾问（2023 至今），负责关键指标跟踪与周期性复盘；此前在伯乐猎聘担任招聘负责人（2016 至 2023），参与方案评审并推动落地。项目经历：代表项目《新能源电池厂工艺工程师招聘》，担任项目顾问，完成 18 个关键岗位寻访，到岗率 83%，试用期留存 90%；代表项目《AI 创业公司算法团队搭建》，担任招聘负责人，搭建 12 人算法团队，平均到岗周期 38 天。持有证书：领英人才解决方案认证、SHL 测评认证。本周可投入 31 小时，支持远程协作，期望报酬 ¥1,984–2,598/天。

**w0003 — 程若然 (UI/UX design, CN)**

> 程若然，现居上海，UI/UX 设计方向。复旦大学 · 数字媒体硕士。从事UI/UX 设计工作 13 年，交付 60 个项目，平均评分 3.7/5，按时交付率 55%。擅长：视觉设计、排版发布、行业研究、内容写作、编辑审校、界面设计、用户体验、Figma。工作经历：曾在体验实验室担任UI/UX 设计师（2023 至今），参与方案评审并推动落地；此前在木棉设计担任高级体验设计师（2013 至 2023），负责关键流程的用户研究、信息架构与高保真设计。项目经历：代表项目《SaaS 数据看板改版》，担任主设计师，重构信息架构与 6 个核心看板，上线后关键任务完成率提升 28%；代表项目《医疗预约小程序体验优化》，担任体验设计，重做挂号与支付流程，输出可点击原型，用户投诉率下降 40%。证书：Figma 专业认证、NN/g UX 认证。本周可投入 31 小时，需线下协作，期望报酬 ¥2,055–2,634/天。

---

## 9. Runtime

| operation | wall time |
| --- | --- |
| full in-memory generation (1k/10k/100k, seed 42, including recomputed duplicate stats) | **33.1 s** |
| `evaluate_large` (500 tasks × 200 candidates × 5 seeds) | **16.4 s** |
| full CLI end-to-end (generate + SQLite + JSONL + stats + strict eval) | **53.9 s** |

No optimization was needed; the scale is unchanged (1,000 / 10,000 / 100,000).

---

## 10. Reproducibility

Regenerating in memory with `generate_large_dataset(1000, 10000, 100000, seed=42)`
matched the final artifact exactly for task texts, resume texts, splits, gold
labels and all 100,000 assignment rows (id, task, worker, status, on_time,
rating, rework, created_at, split). Only the wall-clock `generated_at` metadata
field is non-deterministic.

---

## 11. Label leakage / model-facing boundary

- `labels(task_id, gold_worker_id, split)` is a separate table. `tasks` has no
  `gold_worker_id` and no `category`; `workers` has no latent `reliability`.
- `load_large_sqlite()` returns `labels={}` and drops `stat:*` metadata; test
  assignment outcomes are redacted by default. `include_test_outcomes=True` is
  the explicit evaluator/experimental opt-in.
- JSONL writes no labels, no build-time stats, and redacts test outcomes; it
  carries an `outcome_policy` block (`test_split: redacted`, `train_split:
  full`).
- `LargeFeatureBuilder` reads only workers/tasks/customers and infers category
  from task text; it never reads the labels table.
- `LargeRepository.load_labels()` is evaluator-only; `LargeRepository` reads the
  raw SQLite database (the evaluator artifact).
- Resume aggregates (`rating`, `completed`, `on_time_rate`, `rework_rate`) are
  derived from train-split accepted assignments only.
- The independent verifier found 0 test-outcome leaks in both the model-safe
  loader and the JSONL, and 0 `stat:*` keys in either.

---

## 12. Files changed (this fix round)

- `app/data/large_synthetic.py` — category-consistent project templates,
  certificates and companies; data-derived exact/title/near duplicate stats;
  split outcomes, gold acceptance and exposure-pool stats.
- `app/benchmark/large.py` — train-only ItemCF graph + history; derived split
  flags; feature-only/random baselines; train-only TF-IDF fitting; model-facing
  redaction for the loader and JSONL.
- `scripts/build_large_benchmark.py` — strict-protocol, baseline, gold and
  duplicate detail in the two reports.
- `tests/test_large_synthetic.py` — redaction, computed stats, resume-coherence
  tests.
- `tests/test_large_benchmark.py` — ItemCF leakage regression, test-assignment
  mutation regression, train-only flags/baselines, JSONL model-safety, train-only
  vectorizer tests.
- Outputs regenerated: `data/benchmark/task_benchmark_large.sqlite`,
  `data/benchmark/task_benchmark_large.jsonl`,
  `reports/large_benchmark_stats.md`, `reports/large_benchmark_eval.md`.
- Verification scratch updated: `.superpowers/sdd/recommendation-improvement/`
  `verify_task21.py`, `verify_task21_output.json`, `run_task21_eval.py`,
  `task21_eval_output.json`, `reproduce_task21.py`,
  `task21_build_summary.json`.

---

## 13. Tests

| command | result |
| --- | --- |
| `python -m pytest tests/test_large_synthetic.py tests/test_large_benchmark.py -q` | **19 passed** |
| `python -m pytest -q` (full suite) | **312 passed in 39.2 s** |

---

## 14. Remaining concerns

1. **ItemCF is cold-start on held-out tasks.** The strict graph contains no
   test-task edges, so the collaborative term is zero for all test candidates
   and the strict result equals the feature-only baseline. This is the correct
   leak-free behavior, but it means the sampled eval does not measure ItemCF's
   value on held-out tasks. A content-neighbour bridge (map the test task to
   train items via text similarity) would give ItemCF a legitimate cold-start
   signal; it was not added because the review explicitly required a train-only
   co-occurrence graph.
2. **Resume variety vs. coherence.** Project name/role/bullet/result are now
   paired and category-consistent, but fixing the project templates reduced
   project-name variety; the generator needed 1,641 resume resamples for 1,000
   emitted resumes (still zero exact/near duplicates).
3. **Feature weights.** Evaluation uses `SIM_INITIAL_WEIGHTS`, not the Task 24
   tuned weights; the strict metrics are a reproducible baseline, not the tuned
   production ranking.
4. **Duplicate feature/scoring logic** between `app/benchmark/features.py` and
   `app/benchmark/large.py` is parked (documented) rather than refactored.
5. **No standalone stats-only CLI mode.** The CLI always regenerates;
   `--skip-eval` only skips evaluation. Verification therefore uses a read-only
   script, and the full CLI was run to temporary scratch paths.
6. **Gold is latent-best, not accepted-only.** 23.19% of gold workers did not
   accept their task. This is a valid latent-relevance benchmark but differs
   from an accepted-only label definition.
