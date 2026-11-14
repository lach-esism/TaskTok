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

10 轮结果（`reports/benchmark_rounds.md`）：

| 轮次 | Top-1 | Top-5 | 测试 Top-1 |
|---|---|---|---|
| 1 | 0.563 | 0.913 | 0.560 |
| 5 | 0.674 | 0.985 | 0.670 |
| 10 | 0.731 | 1.000 | 0.750 |

脚本：

```bash
python scripts/build_benchmark.py
python scripts/run_benchmark_rounds.py --rounds 10
python scripts/plot_benchmark.py
```

可视化产物：`reports/benchmark_curve.png/svg`（浅色）、`benchmark_curve_dark.png/svg`（深色）、`reports/benchmark_visual.md`。

接口：`GET /benchmark/summary`、`POST /benchmark/run?rounds=5`。前端「对答案学习」标签页可一键跑 5 轮并看曲线。

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
cd generated/task-recommender
python -m pip install -r requirements.txt
python scripts/run_demo.py
```

服务默认监听 `127.0.0.1:8000`。浏览器打开 **`http://127.0.0.1:8000/ui/`** 即可使用前端演示。

## 前端演示

前端是**无构建的静态 SPA**，由 FastAPI 在 `/ui/` 托管，不需要 Node 构建：

- **概览**：Worker/任务数量、当前权重版本、七维权重、进步曲线（200 用户 cohort 的权重恢复 cosine + NDCG）。
- **任务 → 人**：选择任务后先展示真实需求卡片（标题、正文、合作方要求、预算、日期），再给出 Top-N 候选人、分数拆解、推荐理由、propensity → 采纳并提交客户评分。
- **人 → 任务**：选择 Worker → 推荐开放任务，候选卡片显示任务标题、预算与截止日期。
- **人才库**：以真实简历样式展示候选人；技能分、负载、信誉明细默认隐藏，可切换到平台原始数据。
- **反馈与权重**：新用户 onboarding、个人权重、学习曲线、进步曲线、全局权重 diff、重估、回滚、学习日志。
- **任务链**：单模板/多模板组合拆解、节点表、关键路径、计划、计划版本回滚、自动重规划、节点状态锁定。
- **验收闭环**：加载 B2B 调研任务 → 提交合格/缺章节交付物 → 机器校验 → 同行/客户评分 → 接受/返工/驳回 → 查看权重变化和执行者能力。
- **对答案学习**：一键跑 5 轮，查看 Top-1/Top-5/测试集 Top-1 曲线和逐轮权重更新。
- **评委演示**：一键跑通「推荐 → 采纳 → 评分 → 权重 diff → 拆解 → 计划 → 重规划 → 回滚」。
- **新用户成长**：同一任务、同一用户，对比 A/B 初始偏好；再提交与初始选择相反的反馈，观察权重向真实偏好修正。
- **20 轮对照实验**：每轮 50 次客户选择，学习组 vs 不学习组的 Top-1/Top-5 准确率曲线。

前端文件：`frontend/index.html`、`frontend/styles.css`、`frontend/app.js`；根路径 `/` 会 302 到 `/ui/`。

```bash
curl http://127.0.0.1:8000/health
```

## 测试

```bash
cd generated/task-recommender
python -m pytest tests/ -q
```

当前 150 个测试覆盖 Phase 1 + Phase 2 + Phase 3：健康检查、领域模型/Store、合成数据与 ground truth、七维特征、ItemCF、双向推荐与硬约束、任务链、反馈闭环、信誉拆解、权重版本/回滚、AHP/熵权/投影、在线学习、探索与 IPS、画像/分群、三级个性化、双侧偏好、Phase 2/3 评估、组合模板、Beam/MILP、重规划、计划回滚、自然语言任务分类与字段抽取、验收闭环与能力指标、简历视图与原始数据隔离、1000 任务对答案学习基准、前端静态托管、API 冒烟。

## 离线评估

```bash
cd generated/task-recommender
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
| GET | `/acceptance/demo` | B2B 调研验收演示任务 + 标准 + 示例交付物 |
| POST | `/acceptance/demo/learning?rounds=5` | 连续验收并返回权重漂移 + Top-5 排序变化 |
| GET | `/acceptance/metrics` | 平台验收指标 |
| GET | `/benchmark/summary` | 1000 任务基准的元数据与逐轮结果 |
| POST | `/benchmark/run?rounds=5` | 跑对答案学习轮次 |
| GET | `/tasks/{id}/acceptance-spec` | 任务验收标准 |
| POST | `/tasks/{id}/submissions` | 提交交付物并跑机器校验 |
| POST | `/submissions/{id}/review` | 同行/客户评分 |
| POST | `/submissions/{id}/decision` | 接受 / 返工 / 驳回 / 争议 |
| GET | `/tasks/{id}/acceptance-records` | 验收记录 |
| GET | `/workers/{id}/capability` | 执行者能力指标 |
| POST | `/recommend/workers` | 任务 → 候选人 Top-N |
| POST | `/recommend/tasks` | worker → 任务 Top-N |
| POST | `/chains/decompose` | 模板拆解；`mode=compose` 支持多模板组合 |
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

curl -X POST http://127.0.0.1:8000/chains/<chain_id>/plan
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

## 目录

```text
generated/task-recommender/
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
