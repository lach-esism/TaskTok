# 任务分配推荐系统 — Phase 1 + Phase 2 + Phase 3

Phase 1 实现一个可运行、可测试的纵切：

```text
合成数据 → 七维打分 → 双向 Top-N 推荐 API → 任务链模板拆解 → 链级规划 → 离线指标
```

Phase 2 在此基础上加入反馈闭环、动态权重、三级个性化与回滚：

```text
客户评分 → 信誉/偏好更新 → 全局/分群/个人权重 → 权重版本与回滚 → 学习曲线
```

默认数据规模：100 名 worker、500 个任务、3000 条历史分配，另加 200 名无历史新用户；固定 `seed=42`。任务按真实外包需求生成：标题、正文、合作方要求、服务报酬区间、发布日期与截止日期；内部类别/技能只用于匹配，不在前端作为标签展示。

> **推荐机制完整流程**：见 [`docs/recommendation-flow.md`](docs/recommendation-flow.md)，覆盖主推荐、验收学习、1000 任务对答案基准三条链路。

## Phase 2 新能力

- `POST /assignments`：采纳推荐，记录推荐上下文与 propensity。
- `POST /feedback`：客户评分；重复反馈 409，未知分配 404。
- `GET /workers/{id}/reputation`：信誉聚合与近期违约状态。
- `GET /weights`、`/weights/diff`、`POST /weights/rollback`、`POST /weights/recompute`、`GET /learning/changelog`。
- `POST /workers/{id}/onboarding`、`GET /workers/{id}/weight-profile`、`GET /workers/{id}/learning-curve`。
- 客户侧 onboarding 与权重画像。
- 推荐接口支持可选 `user_id`，使用个人权重。
- Phase 2 评估脚本：`scripts/evaluate_phase2.py`；评委演示：`scripts/demo_judges.py`。

## Phase 3 新增能力（无 LLM）

- **多模板组合**：`mode="compose"` 合并多个领域模板，共享需求/交付节点，去重并校验 DAG。
- **Beam Search / MILP 规划**：`plan_chain_beam`、`plan_chain_milp`；MILP 限制 ≤20 节点，失败时回退 Beam。
- **计划版本与回滚**：`GET /chains/{id}/plans`、`POST /chains/{id}/plan/rollback`。
- **自动重规划**：`POST /chains/{id}/replan` 锁定已完成节点，只重算受影响部分，并生成新计划版本。
- **Phase 2 清理**：重复分配 409、上下文校验 422、权重版本校验/原子写、投影幂等与信誉最大、分领域评分写入、ItemCF 反馈过滤、ground-truth 脚本。
- **明确不做 LLM**：没有 LLM 客户端、提示词或 token 依赖。

## 推荐机制改进（事件、选择学习、严格评估）

- **事件采集**：`POST /events` 记录 `click` / `apply` / `accept` / `reject` / `ignore`，事件写入 `RecommendationEvent`；`GET /events/metrics` 返回曝光、点击、申请、接受、拒绝、忽略与漏斗转化率。推荐接口返回 `request_id`，事件必须能回溯到对应 `Impression`，重复事件返回 409。
- **精确 propensity**：`Impression` 保存每个候选的 logging **包含概率**（inclusion probability），不是“是否被探索”的标记。设候选池大小为 `N`、返回 `K = min(k, N)`、探索率为 `ε`、探索池大小为 `N-K+1`：top-(K-1) 的 `p=1.0`；第 K 名 `p=(1-ε)+ε/(N-K+1)`；第 K 名之后（tail）`p=ε/(N-K+1)`。当 `N<=K` 时全部为 `1.0`。事件和采纳记录都带上该 propensity，供 IPS/SNIPS 评估。
- **选择学习**：pairwise / listwise 选择学习只估计七维线性权重，不训练新的排序模型；排序器仍然是七维线性加权融合（`score = Σ weight_i × feature_i`），没有黑盒模型。
- **严格评估（serving-parity）**：`scripts/evaluate_strict.py` 用 train-only Store 构造特征，并在每个 seed 内拟合与 `create_app` 相同的 `SemanticMatcher`（worker/task 文本）和 `AcceptanceModel`（train accept/reject 事件），注入 baseline、candidate 与验证服务；报告 JSON 的 `serving_features.parity="serving"`。test 数据只用于评分（给 test 查询排序、计算 HR/NDCG/MRR）和校准评估标签（`rating>=4`），不参与特征构造或权重学习。报告 `HR@k`、`NDCG@k`、`MRR@k`、配对 bootstrap 95% CI、约束违规数、冷启动可用性、校准后的 `P(rating>=4)` Brier 分数与可靠性分箱。延迟字段 `scoring_latency_p50_ms/p95_ms` 是**进程内打分时间**，不是 HTTP 端点延迟；`endpoint_latency.guardrail` 明确标记为 `N/A`，不冒充 2× 端点护栏。
- **离线泄漏隔离**：`candidate_mode="exposed"` 只使用 test impressions 定义候选集；test impressions 不写入 Store，也不进入特征/训练代码。train-only Store 负责所有特征与 ItemCF 输入。

**规范（canonical）调优证据**：先跑 `scripts/tune_weights.py`（验证集调参 + 5 seed 严格测试），再把 `weights_choice.json` 激活为 WeightStore 版本：

```bash
python scripts/tune_weights.py --seeds 42,43,44,45,46 --k 10
python scripts/activate_weights.py --input data/weights/weights_choice.json
```

调优结果写入 `reports/strict_eval_tuned.json` / `reports/strict_eval_tuned.md`，这是准确率目标的规范证据；`data/weights/active.json` 指向被激活的 tuned 版本。通用严格评估仍可显式传入候选权重：

```bash
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 \
  --candidate-weights data/weights/weights_choice.json
```

不传 `--candidate-weights` 时脚本会使用 active 权重；若 active 与 baseline 相同，会得到 identity 报告（`baseline_equals_candidate: true`），且不宣称提升。JSON 中冷启动字段为 `cold_start.available`、`cold_start.reason`、`cold_start.queries`、`cold_start.measured`；只有 `available` 为 true 且 `queries > 0` 时 `measured` 才为 true，否则报告中标记 N/A。

> 基准边界：**1,000 任务对答案基准**的 `collaborative` 维度仍恒为 0（`BenchmarkRecommender` 没有接入 ItemCF），不能据此判断协同效果。**Task 21 的 10,000 任务大规模基准**（1,000 workers / 100,000 assignments，80/20 时间切分）单独接入 strict train-only ItemCF：它只使用训练期分配，测试任务在 ItemCF 中冷启动，因此报告中的 strict Top-1 低于旧的非严格数字；两者不可混用。见 `reports/large_benchmark_eval.md`。

## 验收闭环（B2B 调研 P0）

第一版只支持 `consulting_research` 任务，把“什么算完成”写成 10 条可执行标准：

| 标准 | 层 | 硬门槛 | 权重 |
|---|---|---|---|
| 市场规模 / 客户细分 / 竞争格局 / 进入建议章节 | 机器 | 是 | 各 0.08 |
| 至少 8 个来源，含 URL 与日期 | 机器 | 是 | 0.15 |
| 数据表含市场/规模/CAGR/来源 | 机器 | 是 | 0.10 |
| TAM ≥ SAM ≥ SOM | 机器 | 是 | 0.08 |
| 洞察与决策价值 | 客户 | 否 | 0.20 |
| 引用与结论一致 | 同行 | 否 | 0.10 |
| 截止时间前提交 | 机器 | 是 | 0.05 |

流程：`提交交付物 → 机器校验 → 同行/客户评分 → 接受/返工/驳回 → 写验收记录`。

- 硬门槛失败时不能“接受”；客户驳回但指不出失败标准，自动转为 `disputed`。
- 验收记录聚合为执行者能力：一次通过率、返工率、争议率、平均验收分、按时率。
- 验收结果按维度（完整性/准确性/证据/洞察/格式/时效）转成学习信号，更新客户个人权重；争议记录不进入学习。
- 前端「验收闭环」标签页可完整演示：合格提交、缺章节提交、评分、接受/返工/驳回、权重变化。
- 「连续验收 5 次看学习」会用 5 个 B2B 调研任务累积验收信号，展示权重漂移和同一任务 Top-5 排序变化（实测可出现第 4 名升到第 2 名）。

接口：`GET /acceptance/demo`、`GET /acceptance/metrics`、`GET /tasks/{id}/acceptance-spec`、`POST /tasks/{id}/submissions`、`POST /submissions/{id}/review`、`POST /submissions/{id}/decision`、`GET /tasks/{id}/acceptance-records`、`GET /workers/{id}/capability`。

## 1000 任务对答案学习基准（SQLite）

`data/benchmark/task_benchmark.sqlite` 是一个严格的轮次基准：

- **1,000 条自然语言任务**：标题、正文、要求、预算、截止日期；800 条训练、200 条测试。
- **100 份自然语言简历**：姓名、职位、经历、项目、技能标签。
- **标签独立存放**：`labels` 表保存 `task_id → gold_worker_id`；`tasks` 表没有 gold 字段。推荐器只读 `workers` / `tasks` / `customers`，评分和学习阶段才读 `labels`。
- **每轮协议**：清空上一轮推荐缓存 → 重新推荐 → 对答案算 Top-1/Top-5/MRR/NDCG → 只用训练集做 listwise 学习 → 下一轮。
- **遗忘答案**：只清推荐缓存，不清学到的权重；因此下一轮必须靠泛化，不能靠记住上一轮答案。

20 轮结果（`reports/benchmark_rounds.md`，2026-11-14 重新基线）：

| 轮次 | Top-1 | Top-5 | 测试 Top-1 |
|---|---|---|---|
| 1 | 0.367 | 0.872 | 0.365 |
| 5 | 0.530 | 0.953 | 0.545 |
| 10 | 0.568 | 0.946 | 0.580 |
| 15 | 0.564 | 0.936 | 0.580 |
| 20 | 0.562 | 0.935 | 0.580 |

> 这是 Task 3 新特征与 Task 14 基准特征改动后的新基线。第 1 轮 Top-1 `0.367` 是 fresh baseline，第 20 轮 `0.562` 仍明显高于它；但 20 轮不是线性上升：R10 `0.568` 后基本饱和，R20 `0.562` 轻微回落，Top-5 也从 R10 的 `0.946` 降到 `0.935`。R20 绝对值 `0.562` **低于历史 R10 的 `0.731`（约 -0.169）**，历史数字来自旧数据/旧特征，不能与本次直接比较，也不应宣称已恢复到历史水平。**1,000 任务基准的 `collaborative` 仍恒为 0**（`BenchmarkRecommender` 没有接入 ItemCF），因此本轮权重变化中的 `collaborative` 不代表协同特征有效。Task 21 新增的 **10,000 任务大规模基准**单独接入 strict train-only ItemCF（测试任务冷启动，collab=0），见 `reports/large_benchmark_eval.md`；它不替代本节的 1,000 任务对答案基准。

脚本：

```bash
python scripts/build_benchmark.py
python scripts/run_benchmark_rounds.py --rounds 20
python scripts/plot_benchmark.py
```

可视化产物：`reports/benchmark_curve.png/svg`（浅色）、`benchmark_curve_dark.png/svg`（深色）、`reports/benchmark_visual.md`。

接口：`GET /benchmark/summary`、`POST /benchmark/run?rounds=20`（默认 20）。前端「对答案学习」标签页可一键跑 20 轮并看曲线。

## 10,000 任务大规模基准（strict train-only ItemCF）

`scripts/build_large_benchmark.py` 生成 1,000 名 workers、10,000 个自然语言任务、100,000 条历史分配与 500 个客户，80/20 时间切分，写入 SQLite + JSONL。评估严格只使用训练期分配：ItemCF 图不包含测试交互，测试任务在协同维度上冷启动（`collaborative=0`），因此 Top-1 低于旧的非严格数字属于预期，不应与 1,000 任务基准混用。

```bash
python scripts/build_large_benchmark.py
python scripts/evaluate_large_benchmark.py
```

报告：`reports/large_benchmark_stats.md`、`reports/large_benchmark_eval.md`。规模统计会校验无完全重复任务、resume 结构完整与 train/test 交互隔离。

## 调优权重（choice-tuned）

`scripts/tune_weights.py` 只在 train 的最后 20% 验证集上做坐标搜索，严格测试集只用于最终评分；候选权重结合评分 batch fit 与 pairwise choice learning，并投影回七维权重约束。`scripts/activate_weights.py` 将 `data/weights/weights_choice.json` 写成 WeightStore 版本并激活；当前激活版本为 `v0008`（choice-tuned），`data/weights/active.json` 指向它。规范证据是 `reports/strict_eval_tuned.md`（不是旧的 `strict_eval.md`）；若 5 seed 严格测试未达目标，报告必须写 **NOT MET**，不得把 identity 报告或单次点估计当作成功。

2026-11-14 serving-parity 复跑（5 seeds，`reports/strict_eval_tuned.md`）：worker→tasks HR@10 `0.0637 → 0.2070`（+14.33pp，95% CI `[+0.1307, +0.1563]`），NDCG@10 `0.0258 → 0.0991`（+283.55%，CI `[+0.0671, +0.0796]`）；task→workers HR +0.60pp / NDCG +0.21%（均值不劣化）；约束违规 0；校准 Brier 0.0323（raw 0.1186）；冷启动 N/A（无冷启动查询）。**目标 MET**。HTTP 端点延迟未测量，报告标记 N/A；进程内打分 p50/p95 为 9.53/19.86 ms，不能当作端点延迟。此前基于 `weights_v0007.json` 的 **NOT MET** 报告已被本次 tuned 证据取代。

## 文档上传（任务文档 / 简历）

`POST /upload/task`、`POST /upload/resume` 与 `POST /resume/analyze`（粘贴文本）把上传内容解析成 draft，只做语义分析与 Top-N，不写入 Store。支持 `.txt` / `.md` / `.pdf` / `.docx`，上传体在 multipart 解析前由 ASGI 中间件限制为 10 MB；PDF/DOCX 在交给可选解析器前先做解压边界检查：ZIP 条目/压缩比；PDF 通过 pypdf 对象模型迭代扫描 page `/Contents`、`/Resources`、字体与 `/Annots`，解析 `/Fl`/间接 `/Filter`/长字典间隔，并递归到任意深度的嵌套 Form XObject，对 Flate 流按 32 MB/总计 64 MB 上限解码；不支持或多重过滤器返回 422。缺少 `pypdf` / `python-docx` 时返回清晰的 422，不影响文本格式。

## 简历视图：把技能数据包装成真实候选人

`app/resume.py` 把内部 `Worker` 记录转成一份可展示的简历，所有姓名、公司、项目均为合成数据：

- **表面**：姓名、职位标题、城市、经验年限、学历、个人简介、完成项目数、客户评分、按时交付率、工作经历、项目经历、技能标签、证书。
- **隐藏**：内部技能分、等级、容量/负载、专长分、评分明细、返工/违约、分类评分。默认折叠，前端「人才库」页点“查看平台原始数据”才展开。
- 简历按 `worker_id` 确定性生成，同一 worker 每次内容一致。
- 表面技能标签使用中文业务标签（如“市场进入”“竞品分析”），不暴露内部 key（如 `research`）。

接口：`GET /resumes?limit=30&offset=0`（仅表面简历列表）、`GET /workers/{id}/resume`（表面 + `platform_data`）。

## 自然语言任务分类（无 LLM）

`POST /classify` 把一段自由文本变成结构化任务，再交给现有推荐和任务链模块：

1. **规范化与分句**：NFKC、全半角统一、按 `。！？；` 和换行切句。
2. **规则抽取**：预算区间（支持 `万`）、交付周期（天/周，含中文数字）、日期、远程/现场、合作方要求、内部技能标签。
3. **分类**：加权类别词典 + 字符 2–4 gram TF-IDF + 逻辑回归，按 `0.6 * ML + 0.4 * 词典` 融合。中文不需要分词。
4. **置信度**：top1 与 top2 差值 `< 0.08` 或 top1 `< 0.18` 时标记 `needs_clarification`，返回 top-3 让用户确认，而不是硬分类。
5. **下游**：`suggested_template` 就是任务链模板 key；抽取出的技能/预算/周期可直接填充 `Task`。

```bash
curl -X POST http://127.0.0.1:8000/classify \
  -H 'Content-Type: application/json' \
  -d '{"text":"招聘一名电池工艺工程师，要求 3 年以上经验，预算 8000 元。","top_k":3}'
```

评估脚本：`scripts/evaluate_text_classifier.py`，报告写入 `reports/text_classifier.md`。按标题模板分组做 5 折交叉验证，并用手写未见句式做补充验证；合成数据的模板化程度较高，真实业务需要重新标注和评估。

## 快速开始

```bash
cd task-recommender
python -m pip install -r requirements.txt
python scripts/run_demo.py
```

服务默认监听 `127.0.0.1:8000`。浏览器打开 **`http://127.0.0.1:8000/app/`** 使用完整前端（`frontend/`，走 `/market/*` 接口），`/ui/` 是旧演示页。

业务数据存在 SQLite：默认 `data/tasktok.sqlite`，首次启动自动播种，删掉即重置。`TASKTOK_DB=<路径>` 换库，`TASKTOK_DB=`（空）走纯内存。接口清单见 [docs/db-integration-progress.md](../docs/db-integration-progress.md)。

## 前端演示

前端是**无构建的静态 SPA**，由 FastAPI 在 `/ui/` 托管，不需要 Node 构建：

- **概览**：Worker/任务数量、当前权重版本、七维权重、进步曲线（200 用户 cohort 的权重恢复 cosine + NDCG）。
- **任务 → 人**：选择任务后先展示真实需求卡片（标题、正文、合作方要求、预算、日期），再给出 Top-N 候选人、分数拆解、推荐理由、propensity → 点击/申请/不感兴趣事件上报，采纳时把 `request_id` 写入 `recommendation_context`（服务端据此记录 accept）→ 提交客户评分。
- **人 → 任务**：选择 Worker → 推荐开放任务，候选卡片显示任务标题、预算与截止日期；同样复用 `request_id` 与 `/events` 漏斗。
- **人才库**：以真实简历样式展示候选人；技能分、负载、信誉明细默认隐藏，可切换到平台原始数据。
- **反馈与权重**：新用户 onboarding、个人权重、学习曲线、进步曲线、全局权重 diff、重估、回滚、学习日志。
- **任务链**：单模板/多模板组合拆解、动态拆分（`split=true`，按需求/模块/批次把大工作拆成 1–12 个可独立派单的小工作）、草稿确认后物化为独立 Task、父任务退出推荐、撤回物化、节点表、关键路径、计划、计划版本回滚、自动重规划、节点状态锁定。
- **验收闭环**：加载 B2B 调研任务 → 提交合格/缺章节交付物 → 机器校验 → 同行/客户评分 → 接受/返工/驳回 → 查看权重变化和执行者能力。
- **对答案学习**：一键跑 20 轮，查看 Top-1/Top-5/测试集 Top-1 曲线和逐轮权重更新。
- **评委演示**：一键跑通「推荐 → 采纳 → 评分 → 权重 diff → 拆解 → 计划 → 重规划 → 回滚」。
- **新用户成长**：同一任务、同一用户，对比 A/B 初始偏好；再提交与初始选择相反的反馈，观察权重向真实偏好修正。
- **20 轮对照实验**：每轮 50 次客户选择，学习组 vs 不学习组的 Top-1/Top-5 准确率曲线。
- **学习过程（独立页）**：`frontend/learning-demo.html`，双击即可打开，无需启动后端。同一场景下左右并排展示「接单端刷到的单子」和「任务端收到的工人推荐」，逐轮播放双方的 5 张卡片、七维权重、画像数据和命中率/cosine 曲线；顶部可切换 27 个「领域标签 × worker/customer 偏好标签」场景，并显示标签对首轮排名的偏置。
- **案例墙**：8 个跨领域任务 × worker 案例（视频、电商、UI/UX、咨询、写作、标注、培训、品牌），每个展示首轮 → 末轮真实答案排名和命中率迷你曲线。
- **自定义案例**：在演示页底部输入任务或 worker 画像，逐轮点选候选；`POST /demo/custom/step` 用真实特征与 `OnlineWeightLearner` 返回下一轮 Top-5。需要启动后端，输入只发到本机、不落库，且没有 ground truth，因此不显示命中率。
- **简历推送演示（独立页，抖音式单条刷屏）**：`frontend/resume-feed.html`，粘贴自然语言简历 → `/resume/analyze` 解析出 worker 画像 → 一屏一个任务，上滑/滚轮/方向键切换，接单或跳过自动切下一条；简历、我的任务、能力评价收在顶部抽屉里。**右侧常驻调试数据栏**实时显示当前请求（request_id/refresh/queue/seen/pending）、当前任务（id/rank/score/propensity/features/自动完成度/原始 JSON）、七维权重与 delta、个人权重来源/分群/置信度、事件漏斗。演示使用**独立的 2,000 任务市场**（200 workers / 12,000 assignments，全部任务有 ItemCF 历史），走完整推荐链路：`is_eligible` 硬约束（状态/等级/容量/违约/已分配）→ 语义匹配 + 接受概率模型 → `recommend_tasks` → ε-greedy 探索（返回 propensity）→ 记录 Impression；接单/跳过写入 accept/reject 事件，顶部显示曝光/接单/跳过/池/召回。**技能要求按软匹配处理**（技能仍是七维特征），以保证刷屏连续性。首次请求需拟合语义/接受模型，约 6–8 秒；之后约 0.2–0.5 秒。任务池大小可用 `RESUME_DEMO_WORKERS/TASKS/ASSIGNMENTS` 调整。
- 页面同时展示**能力评价**：静态简历能力画像（技能广度/领域专业度/经验/聚焦度/完整度）+ 已评价任务的模拟履约评价（一次通过/验收分/按时/返工/争议），合成总分与 A–D 等级。
- **接单保存与提交评价**：接单后任务进入「我的任务」并保存在浏览器 `localStorage`；任务卡和能力面板不再立即评价。点「提交与评价」打开独立弹窗，填写交付说明/链接、查看完成度自动初评（需求覆盖/交付质量/时效/完整度/沟通）、用滑块手动调整后「提交并评价」；只有已评价任务进入能力评价。刷新页面会恢复简历、任务和评价状态，「清空已保存数据」可重置。需要启动后端，输入不落库。
- 重新生成学习演示页用 `python scripts/build_learning_demo.py`。

前端文件：`frontend/index.html`、`frontend/styles.css`、`frontend/app.js`、`frontend/learning-demo.html`、`frontend/resume-feed.html`；根路径 `/` 会 302 到 `/ui/`。

```bash
curl http://127.0.0.1:8000/health
```

## 测试

```bash
cd task-recommender
python -m pytest tests/ -q
```

当前 463 个测试覆盖 Phase 1 + Phase 2 + Phase 3：健康检查、领域模型/Store、合成数据与 ground truth、七维特征、ItemCF、双向推荐与硬约束、任务链、反馈闭环、信誉拆解、权重版本/回滚、AHP/熵权/投影、在线学习、探索与 IPS、画像/分群、三级个性化、双侧偏好、Phase 2/3 评估、组合模板、Beam/MILP、重规划、计划回滚、自然语言任务分类与字段抽取、文档上传与解压边界（含 PDF `/Fl`、间接 `/Filter`、长字典间隔、嵌套 Form XObject 与 `/Parent` 继承资源对象模型扫描）、验收闭环与能力指标、简历视图与原始数据隔离、1000 任务对答案学习基准、10,000 任务大规模 strict 基准、事件/曝光/漏斗（标签派生、批量/体积上限）、选择学习与权重绑定、serving-parity 严格评估与校准、调优权重激活、文档约定、前端静态托管、学习过程演示数据与变量、案例墙、自定义模拟接口、简历推送页面与接口、简历推送 serving-parity（eligibility、探索 propensity、impression/事件、个人权重）、静态+模拟履约能力评价、任务完成度自动初评与手动调整、API 冒烟。

## 离线评估

```bash
cd task-recommender
python scripts/evaluate.py
```

结果写入 `reports/phase1_metrics.json`。本次运行（seed=42）：

| 指标 | 数值 |
|---|---|
| task→workers HR@10 | 0.665 |
| task→workers NDCG@10 | 0.334 |
| worker→tasks HR@10 | 0.080 |
| worker→tasks NDCG@10 | 0.027 |
| 任务链拆解成功率 | 1.000 |
| 平均需求覆盖率 | 0.340 |
| 平均拆解质量分 | 0.752 |
| 平均链计划覆盖率 | 1.000 |
| DAG 无环率 | 1.000 |

> 这些数字来自修复后的评估协议：跳过训练集泄漏对、跳过不合法（技能/等级/容量/违约）正样本，并使用 train-only 的 worker 聚合特征。平均需求覆盖率偏低是 Phase 1 的已知限制：需求抽取只做简单的标点切分与 2 字符匹配，复杂描述的覆盖需要后续语义抽取。worker→tasks 指标偏低，因为偏好模型仍是启发式，个性化排序是 Phase 2 的重点。

## Phase 2 离线评估

```bash
python scripts/evaluate_phase2.py
python scripts/demo_judges.py
```

结果写入 `reports/phase2_metrics.json`、`phase2_compare.md`、`phase2_learning_curve.md`、`phase2_queries.csv`。本次运行（seed=42）：

| 指标 | 基线 v0000 | 学习后 |
|---|---|---|
| NDCG | 0.1345 | 0.1437 |
| HR | 0.2820 | 0.3016 |
| 测试集违约率（两版相同） | 0.0100 | 0.0100 |
| 约束违规（已检查） | 0 | 0 |

新用户学习曲线（200 个新用户，n=0→50，单 seed）：

| n | NDCG@10 | HR@10 | 权重 cosine |
|---|---|---|---|
| 0 | 0.9536 | 0.9750 | 0.7443 |
| 5 | 0.9537 | 0.9750 | 0.7481 |
| 10 | 0.9537 | 0.9750 | 0.7515 |
| 20 | 0.9538 | 0.9750 | 0.7583 |
| 50 | 0.9536 | 0.9750 | 0.7760 |

> `baseline_rmse`、`learned_rmse`、`gini` 当前未实现，报告中为 `null`，不冒充测量值。学习曲线的 NDCG/HR 接近 1 是因为模拟候选集较小且 oracle 由同一组真实权重排序；权重 cosine 从 0.744 上升到 0.776，说明个性化权重在向真实偏好收敛。新用户画像已与潜在真实权重相关；置信区间与多 seed 仍是后续工作。

## 20 轮学习 vs 不学习对照实验

```bash
python scripts/simulate_learning_rounds.py
```

设置：20 个客户、每轮 50 次选择、20 个候选人、共 20 轮。学习组在每轮结束后用客户选择做 pairwise hard-negative 更新；对照组固定初始权重。

| 指标 | 学习组 | 对照组 |
|---|---|---|
| 第 1 轮 Top-1 | 0.628 | 0.628 |
| 最终 Top-1 | 0.723 | 0.615 |
| 最终 Top-5 | 0.981 | 0.958 |
| 最终权重 cosine | 0.923 | 0.852 |

报告：`reports/learning_rounds.json`、`reports/learning_rounds.md`；前端「评委演示」页会绘制对比曲线。

## Phase 3 链规划评估

```bash
python scripts/evaluate_chains.py
```

结果写入 `reports/phase3_chain_metrics.json` 与 `phase3_chain_metrics.md`：

| 规划器 | 计划覆盖率 | blocked 率 | 平均节点分 | 交接次数 | 无环率 |
|---|---|---|---|---|---|
| greedy | 1.0000 | 0.0000 | 0.7678 | 3.57 | 1.0000 |
| beam | 1.0000 | 0.0000 | 0.7661 | 2.87 | 1.0000 |
| milp | 1.0000 | 0.0000 | 0.7685 | 3.63 | 1.0000 |

> Beam 的交接次数最低，MILP 的平均节点分略高；三者在当前小链上均无 blocked、无环。<br>
> 其他脚本：`scripts/build_ground_truth.py` 生成 `data/ground_truth.csv`。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/workers` | worker 列表 |
| GET | `/workers/{id}` | worker 详情 |
| GET | `/resumes` | 简历列表（仅表面信息） |
| GET | `/workers/{id}/resume` | 简历 + 平台原始数据 |
| GET | `/tasks` | 任务列表 |
| GET | `/tasks/{id}` | 任务详情 |
| POST | `/classify` | 自然语言任务分类 + 字段抽取（无 LLM） |
| POST | `/upload/task` | 任务文档上传 → 语义分析 → draft + Top-N workers（不落库） |
| POST | `/upload/resume` | 简历文档上传 → 画像 draft + Top-N tasks（不落库） |
| POST | `/resume/analyze` | 粘贴简历文本 → 画像 draft + Top-N tasks（不落库） |
| POST | `/events` | 记录曝光后的 click/apply/accept/reject/ignore 事件 |
| GET | `/events/metrics` | 事件漏斗指标（曝光、点击、接受、拒绝、忽略） |
| GET | `/acceptance/demo` | B2B 调研验收演示任务 + 标准 + 示例交付物 |
| POST | `/acceptance/demo/learning?rounds=5` | 连续验收并返回权重漂移 + Top-5 排序变化 |
| GET | `/acceptance/metrics` | 平台验收指标 |
| POST | `/demo/custom/step` | 自定义任务/worker 逐轮模拟：真实特征 + pairwise 权重更新（无状态、不落库） |
| POST | `/demo/resume/refresh` | 自然语言简历解析后的推送 feed：seen 去重、接单更新权重、池耗尽提示（无状态、不落库） |
| GET | `/benchmark/summary` | 1000 任务基准的元数据与逐轮结果 |
| POST | `/benchmark/run?rounds=20` | 跑对答案学习轮次（默认 20） |
| GET | `/tasks/{id}/acceptance-spec` | 任务验收标准 |
| POST | `/tasks/{id}/submissions` | 提交交付物并跑机器校验 |
| POST | `/submissions/{id}/review` | 同行/客户评分 |
| POST | `/submissions/{id}/decision` | 接受 / 返工 / 驳回 / 争议 |
| GET | `/tasks/{id}/acceptance-records` | 验收记录 |
| GET | `/workers/{id}/capability` | 执行者能力指标 |
| POST | `/recommend/workers` | 任务 → 候选人 Top-N |
| POST | `/recommend/tasks` | worker → 任务 Top-N |
| POST | `/chains/decompose` | 模板拆解；`mode=compose` 支持多模板组合；`split=true` 启用动态拆分与 `policy` |
| GET | `/chains/drafts/{id}` | 查看拆分草稿（节点、拆分原因、质量、是否已物化） |
| POST | `/chains/drafts/{id}/materialize` | 物化草稿：创建子任务并把父任务置为 `split` |
| POST | `/chains/drafts/{id}/materialize/rollback` | 撤回物化（子任务已接单时返回 409） |
| GET | `/chains/{id}` | 任务链详情（节点/边/关键路径） |
| POST | `/chains/{id}/plan` | 链级贪心分配计划（保存版本） |
| GET | `/chains/{id}/plans` | 计划版本列表 |
| POST | `/chains/{id}/plan/rollback` | 回滚到指定计划版本 |
| POST | `/chains/{id}/replan` | 违约/延期后自动重规划 |
| POST | `/chains/{id}/nodes/{node_id}/recommend` | 单节点候选人 Top-N |
| POST | `/assignments` | 采纳推荐，创建分配记录 |
| POST | `/feedback` | 客户评分（重复 409，未知分配 404） |
| GET | `/workers/{id}/reputation` | 信誉聚合与违约状态 |
| GET | `/weights` | 当前激活权重版本 |
| GET | `/weights/diff?from=v0000&to=v0001` | 权重逐维差异 |
| POST | `/weights/rollback` | 回滚到指定版本 |
| POST | `/weights/recompute` | 用反馈批量重估全局权重 |
| GET | `/learning/changelog` | 权重/回滚事件日志 |
| POST | `/workers/{id}/onboarding` | 新 worker 画像 → 初始权重 |
| GET | `/workers/{id}/weight-profile` | 个人权重画像 |
| GET | `/workers/{id}/learning-curve` | 个人学习快照 |
| POST | `/customers/{id}/onboarding` | 新客户画像 → 初始权重 |
| GET | `/customers/{id}/weight-profile` | 客户权重画像 |
| GET | `/metrics/compare` | Phase 2 两次运行报告 |
| GET | `/metrics/learning-curve` | Phase 2 学习曲线报告 |

### 示例

```bash
curl -X POST http://127.0.0.1:8000/recommend/workers \
  -H "Content-Type: application/json" \
  -d '{"task_id":"t0001","top_n":5,"explain":true}'
```

```bash
curl -X POST http://127.0.0.1:8000/recommend/tasks \
  -H "Content-Type: application/json" \
  -d '{"worker_id":"w0001","top_n":5}'
```

```bash
curl -X POST http://127.0.0.1:8000/chains/decompose \
  -H "Content-Type: application/json" \
  -d '{"task_id":"t0001","mode":"template","variant":"standard"}'

# 动态拆分：按需求/模块/批次拆成可独立派单的小工作
curl -X POST http://127.0.0.1:8000/chains/decompose \
  -H "Content-Type: application/json" \
  -d '{"task_id":"t0001","split":true,"policy":{"target_hours":8}}'

curl -X POST http://127.0.0.1:8000/chains/<chain_id>/plan

# 确认草稿后物化；父任务状态变为 split，子任务进入推荐与接单链路
curl -X POST http://127.0.0.1:8000/chains/drafts/<draft_id>/materialize
```

## 任务链模板

模板文件：`data/chain_templates/common_task_chains.json`，覆盖 12 类常见任务：

- 软件开发/网站、UI/UX 设计、品牌/平面设计、内容写作
- 短视频制作、市场活动、数据标注、翻译/本地化
- 电商运营、招聘、咨询/调研、培训课程

模板定义节点、工时、技能要求、依赖关系与验收标准。`decompose` 支持：
- 模板变体 `simple/standard/complex`
- 可选节点与 `include_if` 条件
- 可选节点排除后的依赖 bypass
- `hours_range` 工时区间（存在时取 expected）
- 关键路径自动重算
- `split=true` 动态拆分：按描述中的需求/模块/批次拆分、缩小过大节点、合并过小节点、按总工时/预算/工期分配资源；结果先落在草稿，确认后物化

拆分后的父任务 `status="split"`，不再进入推荐；子任务复用现有推荐、接单和验收链路。统计任务数时必须排除 `status="split"`，避免父子重复计数。

离线评估：`python scripts/evaluate_chain_split.py`，读取 `dev_data/chains/split_cases.jsonl`，输出 `reports/chain_split_eval.json/.md`，包含覆盖率增益、可派单率、粒度分布、重复派单数和确定性检查。

## 目录

```text
task-recommender/
├── app/
│   ├── main.py              # FastAPI 路由
│   ├── schemas.py           # 请求/响应模型
│   ├── domain.py            # 领域实体
│   ├── config.py            # 权重与默认参数
│   ├── features.py          # 七维特征
│   ├── service.py           # 硬约束 + 推荐编排
│   ├── metrics.py           # HR/NDCG/链评估
│   ├── data/                # 合成数据、Store、模板加载
│   ├── models/              # ItemCF
│   └── chains/              # DAG、拆解、规划、违约传播
├── frontend/                # 无构建静态 SPA（/ui/）
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/                 # 启动、评估
├── data/chain_templates/    # 12 类模板
├── tests/                   # pytest
└── reports/                 # 评估结果（运行时生成）
```

## Phase 1 明确未实现

- 反馈驱动的动态权重学习、个人权重版本、回滚
- 完整的 worker/customer 偏好模型（当前为启发式）
- LLM 拆解、多模板组合、Beam Search/MILP、自动重规划
- 完整数据校准与保真度报告
- 前端、数据库、鉴权、多租户

这些属于 Phase 2/3。Phase 1 的违约只做传播计算，不自动重规划。

## 说明

当前工作目录不是 git 仓库，Phase 1 不产生 commit；测试结果与评估报告是验收依据。
