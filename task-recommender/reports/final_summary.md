# 推荐机制改进 — 最终汇总

- 日期：2026-11-14
- 范围：`task-recommender/`
- 状态：**全部任务 0–24 完成；392 个测试通过；无未解决的 Critical/Important**
- 关机：**用户明确要求不关机；未执行关机**
- 模型：`opus` 因 API 402 余额不足，最终阶段改用 `sonnet`
- 版本控制：目录不是 git 仓库；用快照 + 统一 diff + ledger 作为审计轨迹，未初始化 git

---

## 1. 最终指标

### 1.1 主推荐（serving-parity，5 seeds，k=10）

| 方向 | 指标 | 基线 | 候选 | 变化 | 95% CI |
|---|---|---|---|---|---|
| worker→tasks | HR@10 | 0.0637 | 0.2070 | **+14.33pp** | [+0.1307, +0.1563] |
| worker→tasks | NDCG@10 | 0.0258 | 0.0991 | **+283.55%** | [+0.0671, +0.0796] |
| task→workers | HR@10 | — | — | +0.60pp | 未恶化 |
| task→workers | NDCG@10 | — | — | +0.21% | 未恶化 |

- **目标状态：MET**（至少一个方向达到 HR +5pp / NDCG +10%，另一方向不劣化）
- 约束违规：0
- 冷启动：`available=false, queries=0`，标记 N/A，不声称通过
- 校准：Brier 0.0323（raw 0.1186）；仅一个 reliability bin 有样本
- 延迟：in-process scoring p50/p95 = 9.53/19.86 ms；**HTTP endpoint latency = N/A**
- 激活权重：`data/weights/active.json` → **v0008**
- 证据：`reports/strict_eval_tuned.json/.md`（canonical）；`reports/strict_eval.json/.md`（v0007，NOT MET，已被 tuned 结果取代）

> 早先 v0007 的严格报告是 `NOT MET`（task→workers HR −0.17pp、NDCG +0.11%，CI 跨 0）；serving-parity 调优后的 v0008 才是最终结论。

### 1.2 大样本自然语言基准（严格 train-only）

- 规模：1,000 workers / 10,000 tasks / 100,000 assignments / 500 customers
- 划分：8,000 train / 2,000 test tasks（80,000 / 20,000 assignments）
- 去重：0 exact duplicates（task/resume/title）；0 near-duplicates（4×16-bit simhash）
- 文本：全部非空、CJK；简历 section 完整率 100%；coherence violations 0
- 严格评估（500 test tasks × 200 candidates × 5 seeds）：
  - Top-1 0.0660 ± 0.0070
  - Top-5 0.2704 ± 0.0092
  - MRR 0.1795 ± 0.0060
  - NDCG@5 0.1672 ± 0.0068
- ItemCF：仅 train-split accepted（49,323 interactions）；12,308 test interactions 被排除；held-out 任务 cold-start，collaborative nonzero rate = 0.00%
- 模型侧导出：test outcomes 已 redact；labels 只给 evaluator
- 证据：`reports/large_benchmark_stats.md`、`reports/large_benchmark_eval.md`、`data/benchmark/task_benchmark_large.sqlite/.jsonl`

### 1.3 NLP 增强

| 项目 | 结果 |
|---|---|
| budget/duration/date/remote F1 | 1.00（目标 ≥0.90，PASS） |
| skills F1 | 0.76（micro；标签未按 taxonomy 校订，作为下界） |
| category easy top-1/top-3/macro-F1 | 1.00 / 1.00 / 1.00 |
| category hard top-1 | 0.75（baseline 0.75，**+0pp，NOT DEMONSTRATED**） |
| category hard top-3 | 0.9583（PASS ≥0.95） |
| category hard macro-F1 | 0.7167（**NOT DEMONSTRATED** <0.80） |
| 校准 | 固定先验 ECE 0.1334 / Brier 0.1322（**NOT DEMONSTRATED**） |
| clarification / wrong-confident | 0.169 / 0.058（**NOT DEMONSTRATED**） |
| CRF | dormant（未安装/无模型 artifact） |

- 证据：`reports/nlp_eval.json/.md`、`data/lexicon/nlp_holdout.jsonl`（71 records，含 24 hard）
- 结论：字段抽取达标；类别泛化、校准、gating 未达演示标准，已如实记录。

### 1.4 上传/分析

- `POST /upload/task`：任务文档 → 分类/字段抽取 → Top-N workers + draft Task
- `POST /upload/resume`：简历文件 → 解析/画像 → Top-N tasks + draft Worker
- `POST /resume/analyze`：粘贴文本 → 同一简历分析/推荐
- 限制：10 MB 在 ASGI 层、form 解析前拒绝；扩展名/MIME 白名单；内存解析；不留文件；不自动写入 store
- 可选依赖：`pypdf` / `python-docx` 缺失时返回清晰 422；`python-multipart` 已加入 requirements
- PDF 解压：迭代对象图扫描、`/Fl` / 间接 `/Filter` / `/Parent` 继承资源、24 层嵌套 Form XObject、`zlib.max_length`、32 MB/64 MB 上限、fail-closed caps；C1 已关闭
- 证据：`tests/test_upload.py`、`tests/test_upload_api.py`、`README.md`、`docs/recommendation-flow.md`

### 1.5 1,000-task 对答案基准（20 轮）

| 轮次 | Top-1 | Top-5 | 测试 Top-1 |
|---|---|---|---|
| 1 | 0.367 | 0.872 | 0.365 |
| 5 | 0.530 | 0.953 | 0.545 |
| 10 | 0.568 | 0.946 | 0.580 |
| 15 | 0.564 | 0.936 | 0.580 |
| 20 | 0.562 | 0.935 | 0.580 |

- 曲线在 R10 `0.568` 后基本饱和，R20 `0.562` 轻微回落；Top-5 从 R10 `0.946` 降到 R20 `0.935`。
- R20 绝对值低于历史 R10 `0.731`（约 -0.169）；历史数字来自旧数据/旧特征，不可直接比较。
- 1,000-task benchmark 的 `collaborative` 仍为 0；10k 大基准是独立的 strict train-only ItemCF。
- 证据：`reports/benchmark_rounds.md`、`reports/benchmark_curve.png/svg`、`reports/benchmark_visual.md`。

---

## 2. 已完成的主要系统能力

- 严格评估：HR/NDCG/MRR、冷启动、校准、paired bootstrap、目标状态、identity 检测
- 事件闭环：`Impression`/`RecommendationEvent`、`/events`、`request_id`、auto-accept、精确 ε-greedy propensity、IPS/SNIPS
- 七维特征升级：语义、报酬/时间、P(accept)、截止/公平、客户偏好、真实沟通分
- 选择学习：pairwise/listwise、Platt 校准、weight binding、`/weights/recompute`、个人化
- 大样本基准：1k/10k/100k、自然语言、去重、严格 train-only ItemCF、抽样评估
- NLP：规范化、可选 jieba、字段抽取 v2、简历分段、校准/置信度门控、NLP 评估
- 上传：双向上传/粘贴、语义分析、Top-N、草稿确认、安全限制
- 文档：README、flow 文档、评估/大样本/NLP/上传说明

---

## 3. Rulings I made

1. 项目不是 git 仓库且计划禁止 git 命令；不初始化 git，用文件快照 + 统一 diff + ledger 代替 commit。代价：没有 git history/bisect；快照保留在 `.superpowers/sdd/recommendation-improvement/snapshots/`。
2. Review package 排除 `docs/superpowers/` 过程文档；它们不是代码审查对象。代价：设计文档修改不出现在代码 diff，单独审查。
3. Task 4 计划要求所有合成事件带 `metadata={"assignment_id": ...}`，让 Task 1 的 ID-based split 正确分类。代价：否则回退 timestamp，tie leakage 仍在。
4. 计划的 certification 两段随机数写法有误；改为单次抽样（`r<0.3→0.8`、`r<0.7→0.5`、否则 0）并抽共享 helper。代价：否则 certification 偏低、扭曲 expertise。
5. Task 6 的 `"exposed"` 模式先按 `metadata["assignment_id"]` 解析 impression，再回退 `(query_id, created_at)`。代价：timestamp tie 时可能用错候选集。
6. Spec 的 propensity 公式为约束：探索池 = `candidates[K-1:]`（K-th + tail，N-K+1）；抽到 K-th 时 Top-K 不变，否则替换最后一名；加 100k 经验频率测试。代价：否则 IPS/SNIPS 无效。
7. `task_to_workers_metrics` 增加 evaluation-only `impressions` 参数；`"exposed"` 用它，不写入 store、不进入 feature/training。代价：否则测试曝光可能污染特征。
8. Strict CLI 增加 `--candidate-weights`；baseline 固定 `DEFAULT_WEIGHTS`，candidate 为 override/active；相同则 `baseline_equals_candidate: true`，不呈现零 delta。代价：否则无候选时会被误读为“无提升”。
9. `worker_to_tasks_metrics` 同样增加 evaluation-only `impressions` 参数。代价：否则 task exposure 可能污染特征。
10. `cold_start.available` 显式化；默认数据无零历史 worker 时报告 unavailable。代价：冷启动 guardrail 在该数据集上无法验证。
11. 延迟 guardrail 仅测 candidate（baseline/candidate 共享 scoring 路径）；最终审查可要求 baseline timing。代价：baseline 路径延迟回归不可见。
12. Task 20 仅在 `available=true` 且 `queries>0` 时声称冷启动已测；必须传真实 candidate weights JSON；identity 按 effective weights。代价：否则可能声称未测的 guardrail。
13. `build_task_text` 包含 `category`；worker/task 文本按 ID 缓存。代价：否则语义特征偏弱、重复构造简历。
14. 持久化 sha256 磁盘 embedding cache 延后；当前规模内存 pair cache 足够。代价：重启后重算，不是正确性问题。
15. `SEMANTIC_*` 配置通过 `getattr` 默认值可接受，直到 Task 13/18 集中到 config。代价：配置暂不显式可见。
16. `category_history` 直接用 `compute_reputation(worker).rating`（已是 0–1）：`(n*mean/5 + m*global_rating)/(n+m)`。代价：否则重复除以 5 扭曲 expertise。
17. 曾接受 implicit `now` 分钟截断；**复审后推翻**，改为原始 `datetime.now(timezone.utc)` 并更新 equality test。代价：分钟截断会隐藏 wall-clock 不稳定。
18. Task 13 必须计算 `region_match`（1.0/0.8/0.3）与 `historical_accept_rate`（Beta 平滑，无事件 0.5）后再调 `accept_features`。代价：否则 acceptance model 输入错误。
19. 允许额外 keyword-only `pay_fit`/`communication`/`collaboration` 输入；它们是 service plumbing，不是新维度。代价：签名比 brief 印刷版宽，但现有调用兼容。
20. 启动时拟合 semantic matcher/acceptance model 可接受。代价：~1.5s 冷启动，无请求路径回归。
21. Task 14 的 benchmark `collaborative` 失效与单 pair 归一化退化，延后到 Task 21 大 benchmark（真实历史）修复；主服务 ItemCF 不受影响。代价：1,000-task benchmark 的 collaborative 仍为 0，Task 20 需记录。
22. 不写重复的内部 `action="impression"` 事件；`Impression` 就是曝光日志，funnel 从 `store.impressions` 推导。代价：期望 impression event rows 的消费者看不到，但曝光计数在。
23. Task 2 的 `candidate_type` 默认 `"worker"`；task 方向由 Task 18 处理。代价：Task 18 前 task-candidate events 会标错。
24. Task 2 的 minors（共享 `_persist`、写失败原子性、O(n) 扫描、重复 `request_id`、unknown-action bucket）留到最终审查。代价：Phase 1 低量行为。
25. Task 24 验证集 worker aggregates 包含 validation slice（轻 look-ahead）；test data 未触碰，strict test 结果不受影响；接受为文档化限制。代价：验证侧略乐观；重调时用 fit slice 重建。
26. 不与 Task 3 之前的 Task 0 报告比较 strict 指标；Task 3 新 RNG 改变固定 seed 数据集；Task 6/7 在同一新数据上算 baseline/candidate，Task 20 重跑 benchmark baseline。
27. **保留 SDD workspace 作为审计轨迹**（没有 git history，不删除 ledger/reviews/snapshots）。代价：`.superpowers` 目录保留，略占空间。
28. **不关机**（用户明确要求）；机器保持开机。

> Ledger 中另有若干“parked minors / accepted limitations”，未逐条列为 ruling；见第 4 节。

---

## 4. 已知限制 / 延后项

- **PDF parser/xref 构造**仍无 subprocess timeout/RSS 隔离；page/XObject 可达的 Flate 流已 bounded，但 `/ObjStm`/`/XRef` 在 `PdfReader` 构造期仍有残余 CPU/RSS 风险；建议后续用 subprocess 隔离。
- **端点延迟**未测（只有 in-process scoring p50/p95 9.53/19.86 ms）；2× guardrail 标 N/A。
- **冷启动**在默认合成数据上无零历史 worker；N/A。
- **1,000-task 基准 `collaborative`** 仍为 0；10k 大基准已改为严格 train-only，held-out 任务 cold-start（collaborative 0）。
- **持久化事件日志 audit-only**；启动不加载回内存。
- **NLP**：hard top-1 +0pp、macro-F1 0.7167、calibration/gating NOT DEMONSTRATED；CRF dormant；holdout 71 records。
- **benchmark 绝对回归**：20 轮 R20 Top-1 0.562（R10 0.568 后饱和/轻微回落），低于历史 R10 0.731（约 -0.169）；已文档化。
- **校准**：~97% 评分 ≥4，只有一个 populated reliability bin。
- **parked minors**：funnel 分母/rank buckets、`GET /evaluation/strict`/`/config/semantic`、`scripts/simulate_events.py`、`strict_eval_queries.csv`、80/20 vs 70/15/15、exposure fairness saturation、semantic text staleness after feedback、CRF pickle safety、event score null coercion、upload sections volume/CPU、413 vs 422、upload request_id without impression、global MultiPartParser mutation、binding per-update counts/unguarded write、leakage static/runtime tests、test events_dir cleanup、docs token-only checks、frontend no JS-executing test、client-side confirm-only、real PDF fixture missing、heuristic level/remote/city defaults、frontend upper clamp、duplicate response helper、python-multipart required、dead `COMPANY_POOL`/`CATEGORY_RESULTS`/comment/counter mismatch, duplicated feature/scoring logic, no stats-only CLI, `main.py` growth/wiring helpers, `CHOICE_LEARNING_MODE` import-time, `WeightVersion.sample_count` semantics, duplicate impression lookup, binding write unguarded, non-discriminating parity test.

---

## 5. 关键产物

| 产物 | 路径 |
|---|---|
| 设计 spec | `docs/superpowers/specs/2026-11-13-recommendation-improvement-design.md` |
| 实现计划 | `docs/superpowers/plans/2026-11-13-recommendation-improvement.md` |
| SDD ledger / 全部 ruling | `.superpowers/sdd/recommendation-improvement/progress.md` |
| 最终审查 | `.superpowers/sdd/recommendation-improvement/review-final.diff` + ledger |
| 最终修复报告 | `.superpowers/sdd/recommendation-improvement/final-fix-report.md` |
| 主 strict 评估 | `reports/strict_eval_tuned.json/.md`（canonical）、`reports/strict_eval.json/.md`（v0007） |
| 权重 binding | `reports/weight_binding.json` |
| 1,000-task benchmark | `reports/benchmark_rounds.json/.md`、`reports/benchmark_visual.md` |
| 10k 大基准 | `reports/large_benchmark_stats.md`、`reports/large_benchmark_eval.md`、`data/benchmark/task_benchmark_large.sqlite/.jsonl` |
| NLP | `reports/nlp_eval.json/.md`、`data/lexicon/nlp_holdout.jsonl` |
| 上传 | `app/upload/`、`tests/test_upload*.py` |
| 激活权重 | `data/weights/active.json` → `v0008`；`data/weights/weights_v0008.json` |

---

## 6. 验证命令

```bash
cd task-recommender
python -m pytest tests/ -q                     # 392 passed
python scripts/tune_weights.py                 # 生成 weights_choice + tuned strict eval
python scripts/activate_weights.py             # 创建并激活 v0008
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 \
  --candidate-weights data/weights/weights_v0008.json
python scripts/run_benchmark_rounds.py --rounds 20
python scripts/plot_benchmark.py
python scripts/evaluate_nlp.py
python scripts/build_large_benchmark.py --workers 1000 --tasks 10000 --assignments 100000 --seed 42
```

> 注意：`README.md` / `docs/recommendation-flow.md` 已更新；`reports/strict_eval_tuned.*` 是 canonical 的 MET 证据，`reports/strict_eval.*` 是 v0007 的 NOT MET 历史证据。

---

## 7. 结论

- 核心目标：**MET**（serving-parity tuned weights v0008）。
- 主推荐：worker→tasks 显著提升，task→workers 不劣化；0 约束违规。
- 大样本、NLP、上传、事件闭环均已实现并有测试/报告。
- 剩余项是明确记录的限制和 parked minors，不是未解决的 Critical/Important。
- **未关机**；机器保持开机，屏幕/睡眠超时已设为 0。
