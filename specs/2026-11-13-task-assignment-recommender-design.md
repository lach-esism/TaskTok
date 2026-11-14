# 任务分配推荐系统 — 设计文档

- 日期：2026-11-13
- 状态：设计定稿（待补充任务链拆解章节）
- 项目位置：`task-recommender/`
- 技术栈：Python 3.13 + FastAPI + numpy + pandas + scikit-learn + pytest
- 数据基础：暂无真实数据，先用可复现的模拟数据验证机制

---

## 1. 背景与目标

本系统用于「任务分配」场景：在任务与执行者之间做双向推荐，并利用客户对交付内容的评分形成反馈闭环，持续动态调整推荐权重。

### 1.1 目标

1. **双向 Top-N 推荐**
   - 任务 → 候选人：输入任务，输出最合适的执行者排序。
   - 人 → 任务：输入执行者，输出最适合其接取的开放任务排序。
2. **多维度打分**：技能匹配、领域专长、信誉/履约、协同偏好、偏好匹配、负载/公平、客户偏好/优先级。
3. **信誉优先**：信誉/履约是权重最大的维度；违约采用分档处理。
4. **反馈驱动**：客户评分与行为反馈用于在线更新权重，权重版本化、可回滚。
5. **双侧偏好**：同时建模 worker 对任务的偏好与客户对服务者的偏好。
6. **可验证**：在模拟数据上完成离线评估，并支持在线指标查询。
7. **任务链**：把客户发布的一个复杂任务拆解为带依赖的子任务 DAG，并分配给不同 worker。

### 1.2 非目标

- 不做自动最终分配（只做 Top-N 推荐，由人确认）。
- 不做在线学习平台、复杂前端、鉴权与多租户。
- 不接入真实数据库；数据落 CSV / 内存，权重落 JSON。
- MVP 只做模板化拆解与链级分配；LLM 自动拆解、全局多链优化放在后续阶段（见第 8.10 节）。

---

## 2. 术语

| 术语 | 含义 |
|---|---|
| Worker / 用户 | 任务执行者 |
| Customer / 客户 | 任务发布方与验收方 |
| Task / 任务 | 待分配的工作单元 |
| Assignment / 分配 | 一次任务与 worker 的绑定记录 |
| Feedback / 反馈 | 客户对交付内容的评分与可选评语 |
| Reputation / 信誉 | 由评分、完成率、按时率、违约与返工共同计算的履约可信度 |
| Specialty / 领域专长 | Worker 在某一任务领域内「擅长」的程度 |
| Preference / 偏好 | 主观意愿：worker 想不想接某任务；客户想不想要某服务者 |
| Breach / 违约 | 未按时交付、接单后取消、验收不通过 |
| Propensity | 某候选被推荐给用户的概率，用于离策略评估 |
| Run A / Run B | 两次对比：Run A 为 `v0000` 先验基线，Run B 为学习后的版本 |
| 学习证据 | 权重 diff、偏好画像、信誉变化、规则/参数变更、同查询反事实对比 |
| 回滚 | 将 active 权重版本切回历史版本（包括第一次运行之前的 `v0000`） |
| 画像先验 | 由用户画像/分群得到的初始个人权重 |
| 个人权重 | 每个用户一套七维权重，随反馈在线更新 |
| 学习曲线 | 新用户推荐指标随反馈数变化的曲线 |
| Oracle | 模拟中的潜在真实权重与最优排序，仅评估用，不参与训练 |
| Task Chain / 任务链 | 由带依赖的子任务组成的有向无环图（DAG） |
| Critical Path / 关键路径 | DAG 中最长路径，决定链的最短可能工期 |
| Handoff / 交接 | 相邻节点由不同 worker 执行产生的上下文切换成本 |

**关键区分**：偏好（想不想做）、能力（能不能做好）、信誉（会不会守约）必须分开建模，不能合并成单一分数。

---

## 3. 总体架构

```text
新用户画像 / onboarding ──► 分群 / 画像模型 ──► 初始个人权重 w_u(0)
                                                    │
客户评分 / 行为信号 ──► Feedback Store ──► 个人权重在线更新 w_u(t)
                                                    │
                                                    ▼
推荐打分 ◄── 三级权重：全局 γ / 分群 w_s / 个人 w_u
        │
        ▼
   新分配结果 ──► 新的客户评分/行为信号（闭环）
```

### 3.1 推荐请求处理流程

```text
请求（task_id 或 worker_id）
  → 加载数据与三级权重（全局/分群/个人）
  → 新用户？画像 → 初始个人权重 w_u(0)
  → 硬约束过滤（技能/容量/等级/专长/违约/状态）
  → 候选生成
  → 七维打分（归一化到 [0,1]）
  → 权重融合（w_u > w_s > γ，含探索扰动）
  → Top-N 排序
  → 生成解释、冷启动标记、权重来源与置信度
  → 记录 propensity 与权重版本
  → 返回结果
```

### 3.2 反馈处理流程

```text
客户评分 / 分配结果
  → 写入 Feedback / Assignment
  → 更新信誉聚合与偏好统计
  → 更新个人权重 w_u 与分群权重 w_s
  → 全局权重在线增量更新（带单纯形约束）
  → 生成新权重版本（或标记待批量重估）
  → 记录学习曲线快照
  → 更新在线指标
```

---

## 4. 数据模型

### 4.1 Worker

| 字段 | 类型 | 说明 |
|---|---|---|
| `worker_id` | str | 主键 |
| `name` | str | 名称 |
| `skills` | dict[str, int] | 技能 → 熟练度（1–5） |
| `specialties` | dict[str, Specialty] | 任务领域 → 专长 |
| `level` | int | 综合等级（1–5） |
| `capacity_hours` | float | 周期可用工时 |
| `current_load_hours` | float | 当前已占用工时 |
| `preferred_categories` | dict[str, float] | 声明偏好（0–1） |
| `preferred_difficulty` | [int, int] | 偏好难度区间（1–5） |
| `preferred_time_window` | list | 偏好时段 |
| `remote_ok` | bool | 是否接受远程 |
| `region` | str | 所在区域 |
| `status` | enum | active / inactive / needs_review |
| `created_at` | datetime | 创建时间 |

**Specialty**：
- `level`：1–5
- `source`：self_declared / certified / verified
- `evidence_count`：可验证的历史完成次数

### 4.2 Customer

| 字段 | 类型 | 说明 |
|---|---|---|
| `customer_id` | str | 主键 |
| `name` | str | 名称 |
| `industry` | str | 行业 |
| `preference_weights` | dict[str, float] | 显式偏好：质量/专长/速度/价格/沟通/合作历史 |
| `budget_range` | [float, float] | 预算区间 |
| `quality_requirement` | int | 质量要求（1–5） |
| `created_at` | datetime | 创建时间 |

### 4.3 Task

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | str | 主键 |
| `customer_id` | str | 发布客户 |
| `title` | str | 标题 |
| `description` | str | 描述 |
| `category_id` | str | 任务领域（12 类之一） |
| `required_skills` | dict[str, int] | 必需技能 → 最低熟练度 |
| `required_specialty` | dict[str, int] | 可选：领域 → 最低专长等级 |
| `required_level` | int | 最低 worker 等级（1–5，默认 1） |
| `difficulty` | int | 难度（1–5） |
| `priority` | int | 优先级（1–5） |
| `estimated_hours` | float | 预计工时 |
| `deadline` | datetime | 截止时间 |
| `remote_ok` | bool | 是否可远程 |
| `region` | str | 任务区域 |
| `budget` | float | 预算 |
| `status` | enum | open / assigned / in_progress / completed / cancelled |
| `created_at` | datetime | 创建时间 |

### 4.4 Assignment

| 字段 | 类型 | 说明 |
|---|---|---|
| `assignment_id` | str | 主键 |
| `task_id` | str | 任务 |
| `worker_id` | str | 执行者 |
| `customer_id` | str | 客户 |
| `recommended_at` | datetime | 被推荐时间 |
| `assigned_at` | datetime | 确认分配时间 |
| `recommendation_score` | float | 推荐分 |
| `recommendation_rank` | int | 推荐排名 |
| `propensity` | float | 被推荐概率（用于 IPS） |
| `weights_version` | str | 使用的权重版本 |
| `status` | enum | accepted / in_progress / completed / failed / cancelled |
| `completed_at` | datetime | 完成时间 |
| `on_time` | bool | 是否按时 |
| `rework_count` | int | 返工次数 |
| `breach_type` | enum | none / late / cancel_after_accept / acceptance_failed |
| `created_at` | datetime | 创建时间 |

### 4.5 Feedback

| 字段 | 类型 | 说明 |
|---|---|---|
| `feedback_id` | str | 主键 |
| `assignment_id` | str | 对应分配 |
| `customer_id` | str | 评分客户 |
| `worker_id` | str | 被执行者 |
| `task_id` | str | 任务 |
| `overall_rating` | int | 总分 1–5（必填） |
| `quality_rating` | int? | 质量子项 1–5（可选） |
| `timeliness_rating` | int? | 时效子项 1–5（可选） |
| `communication_rating` | int? | 沟通子项 1–5（可选） |
| `comment` | str? | 评语 |
| `propensity` | float | 该分配被推荐的概率 |
| `created_at` | datetime | 创建时间 |

### 4.6 WeightVersion

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | str | 如 `v0007` |
| `weights` | dict[str, float] | 七维权重，和为 1 |
| `prior` | dict[str, float] | AHP 先验 |
| `sample_count` | int | 参与学习的反馈数 |
| `source` | enum | prior / online / batch / blended |
| `metrics_snapshot` | dict | 更新时的验证集指标 |
| `updated_at` | datetime | 更新时间 |

### 4.7 PreferenceProfile

| 字段 | 类型 | 说明 |
|---|---|---|
| `entity_type` | enum | worker / customer |
| `entity_id` | str | 主体 ID |
| `vector` | dict[str, float] | 偏好分布 |
| `confidence` | float | 置信度（由样本量决定） |
| `sample_count` | int | 有效样本数 |
| `updated_at` | datetime | 更新时间 |

### 4.8 UserProfile

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | str | worker 或 customer |
| `entity_type` | enum | worker / customer |
| `role` | str | 角色/职业 |
| `industry` | str | 行业 |
| `experience_years` | float | 经验年限 |
| `skills` | dict[str, int] | 技能（worker） |
| `specialties` | dict[str, int] | 擅长领域（worker） |
| `region` | str | 区域 |
| `language` | list[str] | 语言 |
| `availability` | dict | 可用时段 |
| `declared_preferences` | dict | 声明偏好（类别/难度/报酬/模式） |
| `profile_completeness` | float | 画像完整度 0–1 |
| `segment_id` | str | 分群 ID |
| `created_at` | datetime | 创建时间 |

### 4.9 UserWeightProfile

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | str | 用户 |
| `weights` | dict[str, float] | 当前个人七维权重 |
| `source` | enum | global / segment / profile / online / blended |
| `segment_id` | str | 所属分群 |
| `sample_count` | int | 该用户有效反馈数 |
| `confidence` | float | 权重置信度 0–1 |
| `version` | str | 个人权重版本 |
| `updated_at` | datetime | 更新时间 |

### 4.10 Segment

| 字段 | 类型 | 说明 |
|---|---|---|
| `segment_id` | str | 分群 ID |
| `name` | str | 可读名称 |
| `centroid` | dict | 画像特征中心/规则 |
| `weights` | dict[str, float] | 分群七维权重 |
| `member_count` | int | 成员数 |
| `updated_at` | datetime | 更新时间 |

### 4.11 LearningSnapshot

| 字段 | 类型 | 说明 |
|---|---|---|
| `snapshot_id` | str | 主键 |
| `user_id` | str | 用户 |
| `n_feedback` | int | 当时累计反馈数 |
| `weights` | dict[str, float] | 当时个人权重 |
| `ndcg_at_10` | float | 当时验证集 NDCG@10 |
| `hr_at_10` | float | 当时 HR@10 |
| `regret` | float | 与 oracle 的差距 |
| `created_at` | datetime | 快照时间 |

### 4.12 TaskChain 与 SubTask

| 实体 | 关键字段 |
|---|---|
| `TaskChain` | `chain_id, root_task_id, customer_id, status, deadline, budget, critical_path, plan_version, created_at` |
| `SubTask` | `subtask_id, chain_id, title, category, required_skills, estimated_hours, node_type, acceptance_criteria, status, assigned_worker_id` |
| `ChainEdge` | `chain_id, from_node, to_node, edge_type` |
| `ChainPlan` | `plan_id, chain_id, version, score, makespan, cost, risk, handoff_count, status, created_at` |
| `ChainPlanNode` | `plan_id, subtask_id, worker_id, rank, node_score, start_at, end_at` |
| `ChainFeedback` | `chain_id, plan_id, node_id, overall_rating, node_rating, on_time, rework_count, breach_type, created_at` |
| `DecompositionTemplate` | `template_id, category, version, dag_json, default_hours, required_skills, variants, quality_rules, changelog` |

> 完整字段与约束见第 8.6 节。

---

## 5. 模拟数据设计

### 5.1 规模

| 项 | 数量 |
|---|---|
| Worker | 800 |
| Task | 4000 |
| Assignment 历史 | 30000 |
| 有客户评分的分配 | 约 70% |
| 技能 | 30（Zipf 分布） |
| 任务领域 | 12 |
| 冷启动 worker | 15%（<5 条历史） |
| 冷启动 task | 15%（<3 次完成） |

### 5.2 生成规则

1. **技能**：按 Zipf 分布抽样；每个 worker 拥有 3–8 项技能，熟练度 1–5。
2. **专长**：每个 worker 有 1–3 个擅长领域；生成真实潜在专长向量，再叠加自报噪声。
3. **任务**：每任务 1–4 项必需技能；领域从 12 类中按类别热度抽样；难度、优先级、工时、预算服从合理分布。
4. **偏好**：为每个 worker 生成潜在类别偏好向量；为每个 customer 生成潜在服务者属性偏好向量。
5. **行为**：按「技能 × 专长 × 信誉 × 偏好」生成接受/拒绝概率；被接受的分配再生成完成质量、是否按时、是否返工。
6. **违约**：基准违约率约 3%；低可靠性 worker 更高。违约类型按比例抽样。
7. **评分**：`rating = f(真实匹配度) + 客户宽松度偏差 + 噪声`，裁剪到 1–5；约 70% 分配产生反馈。
8. **时间漂移**：在时间轴 60% 处改变类别热度、偏好分布与可靠性分布，模拟业务漂移，用于验证权重自适应能力。
9. **可复现**：所有随机过程使用固定 seed，支持 `--seed` 覆盖。
10. **新用户批次**：模拟 200 名新用户在时间轴上陆续加入；每人有潜在真实七维权重 `w_u*`，画像特征与潜在权重相关；加入时只有画像、无历史反馈，用于学习曲线评估。

### 5.3 时间划分

- 按事件时间排序：前 70% 训练、15% 验证、15% 测试。
- 评估必须严格使用未来数据，禁止随机打乱。

### 5.4 结构化潜变量生成模型（DGP）

不用独立随机标签，所有行为由潜变量和行为方程生成。

**潜变量**：

| 主体 | 潜变量 |
|---|---|
| Worker | 能力向量、专长向量、可靠性、偏好向量、可用工时、响应倾向、潜在真实七维权重 `w_u*` |
| Customer | 评分宽松度、偏好权重（质量/速度/价格/沟通）、选择严格度、预算敏感度、潜在真实七维权重 `w_u*` |
| Task | 类别、技能要求、难度、紧急度、预算、截止时间 |

**行为方程**（系数可配置，初始值由目标统计校准）：

```text
P(accept)   = σ(β·[匹配度, 报酬, 时段, 偏好, 距离])
quality     = clip(q0 + γ1·能力匹配 + γ2·专长匹配 + γ3·可靠性
                      - γ4·负载 - γ5·难度 + ε, 0, 1)
P(on_time)  = σ(δ·[可靠性, 负载, 截止紧迫度, 难度])
P(breach)   = σ(φ·[可靠性, 过载, 截止紧迫度])       # 不允许均匀随机
satisfaction = η0 + η1·quality + η2·timeliness
              + η3·communication + leniency_c + ε
rating      = ordinal_probit(satisfaction)          # 映射到 1–5
```

**潜在结果（只给评估用）**：

- 为所有 `(worker, task)` 对生成真实匹配度 `q*_ui` 与真实成功概率。
- 为每个用户生成潜在真实权重 `w_u*`，用于 oracle NDCG 与权重恢复检验。
- 只观测被分配的对；`q*` 与 `w_u*` 单独写入 `data/ground_truth.csv`。
- 训练、特征、推荐模型**禁止读取** `ground_truth.csv`；仅 `scripts/evaluate.py` 可读。
- 用途：计算真实 NDCG / regret，验证学到的权重是否接近生成时的潜在权重。

**曝光机制**：

- 模拟推荐策略与 `propensity`，记录哪些候选被看到，复现选择偏差。
- 未曝光样本进入负样本时需带 propensity 或降权。

**时间模式**：

- 任务到达用 Poisson 过程，叠加工作日/时段季节性与 60% 处的业务漂移。

### 5.5 目标统计与参数校准

**目标统计量**（初始值，真实数据可用时替换）：

| 统计量 | 初始目标 | 容差 |
|---|---|---|
| 分配密度 | ~0.94% | ±0.1pp |
| 每 worker 分配数中位数 | ~35 | ±20% |
| 每 task 分配数中位数 | ~7 | ±20% |
| 评分均值 / 标准差 | 4.2 / 0.8 | ±0.2 / ±0.15 |
| 接受率 | 55% | ±10pp |
| 完成率 / 按时率 | 90% / 85% | ±5pp |
| 违约率 | 3% | ±1pp |
| 冷启动 worker / task 比例 | 15% / 15% | ±3pp |
| 类别分布 | Zipf α≈1.2 | KS p > 0.05 |
| 技能分布 | Zipf α≈1.5 | KS p > 0.05 |
| 曝光 Gini | 0.5–0.6 | ±0.1 |

**校准目标**：

```text
θ* = argmin_θ Σ_k ω_k·|s_k(θ) - t_k| / scale_k
```

- 用 `scipy.optimize.differential_evolution` 或随机搜索；固定 seed、限定预算。
- 校准集 / 验证集 / 测试集分开，禁止在测试集上调参。
- 输出 `reports/data_calibration.md`：目标值、生成值、容差、是否达标。

### 5.6 数据保真度与可用性验证

| 检查 | 方法 | 通过标准 |
|---|---|---|
| 边际分布 | KS 检验（数值）、卡方（类别） | p > 0.05 |
| 相关性 | 相关矩阵、互信息 | 与目标差异在容差内 |
| 时间模式 | 自相关、周期性、漂移检测 | 峰值时段与漂移点可识别 |
| 真实权重恢复 | 学到权重 vs 潜在权重（Spearman） | > 0.7 |
| 个人权重恢复 | `cosine(w_u(t), w_u*)` | 随反馈数上升 |
| 学习曲线 | 新用户 NDCG vs 反馈数 | 单调上升并收敛 |
| 冷启动提升 | `NDCG(0)` vs 全局先验 | 画像初始化更优 |
| 排序真值 | 用 `q*` 计算真实 NDCG/regret，与观测反馈 NDCG 对比 | 趋势一致 |
| 敏感性 | 关键参数 ±20% 重跑 | 排序结论稳定 |
| 多 seed | 5 个 seed | 报告均值±标准差，方差可接受 |
| 真实数据（如有） | TSTR、对抗验证 AUC | AUC 接近 0.5 |

- 输出 `reports/data_fidelity.md`。
- 若后续接入真实数据，用真实样本拟合边际与相关性，或采用 copula/对抗验证做域适配。

### 5.7 防坑清单

1. 不用独立同分布随机标签；行为必须条件于潜变量。
2. 违约不能均匀随机；必须与可靠性、负载、截止紧迫度相关。
3. 评分不能独立于质量；要由质量/时效/沟通 + 客户宽松度生成。
4. 不能忽略曝光/选择偏差；必须记录 propensity。
5. 不能让 `ground_truth.csv` 泄漏进特征或训练。
6. 不能在测试集上校准参数。
7. 不能只校准边际分布，必须检查相关性与时间模式。
8. 不能只用一个 seed 下结论；至少 5 个 seed 报告方差。

---

## 6. 推荐算法

### 6.1 硬约束（一票否决）

候选必须同时满足：

1. 所有必需技能熟练度 ≥ 最低要求。
2. `current_load_hours + estimated_hours ≤ capacity_hours`。
3. `worker.level ≥ task.required_level`（若任务设置）。
4. 任务设置了 `required_specialty` 时，专长等级达标。
5. 未被分配、未完成过该任务。
6. `worker.status = active`。
7. 违约分档：近 180 天内违约 ≥2 次 → 排除；恰好 1 次 → 保留但标记 `warning` 并重罚。

硬约束不计入加权，违规数在评估中必须为 0。

### 6.2 七维打分

所有维度输出归一化到 `[0,1]`。

| 维度 | 符号 | 权重 |
|---|---|---|
| 信誉/履约 | `R` | 0.32 |
| 技能匹配 | `S` | 0.20 |
| 领域专长 | `E` | 0.15 |
| 协同偏好 | `CF` | 0.13 |
| 偏好匹配 | `P` | 0.10 |
| 负载/公平 | `L` | 0.06 |
| 客户偏好/优先级 | `Q` | 0.04 |
| 合计 | | 1.00 |

#### 6.2.1 信誉 `R`

```text
R_rating = (Σ r_i + m·μ0) / (n + m)          # 贝叶斯平滑，m=10，μ0=全局均值
R = 0.40·R_rating
  + 0.20·completion_rate
  + 0.20·on_time_rate
  + 0.10·rework_score                        # rework_score = 1 - min(rework_rate, 1)
  + 0.10·breach_penalty
```

- `breach_penalty = max(0, 1 - 0.5·recent_breach_count - 0.2·decayed_historical_breach_count)`
- 近 180 天 1 次违约 → `recent_breach_count=1`，信誉显著下降并标记 `warning`。
- 按任务领域维护分领域信誉，并用全局信誉做收缩：

```text
R_c = (n_c·R_c_raw + m·R) / (n_c + m)
```

#### 6.2.2 技能匹配 `S`

```text
S = Σ_s w_s·min(proficiency_u(s) / min_required_i(s), 1) / Σ_s w_s
```

- `w_s` 默认 1，可按任务要求的重要性配置。
- 无技能要求时，`S` 取该领域的专长/历史匹配分，避免虚高。

#### 6.2.3 领域专长 `E`

```text
E = 0.4·(specialty_level / 5)
  + 0.3·certification_score
  + 0.3·category_history_quality
```

- `certification_score`：认证=1.0，有证据的自报=0.6，纯自报=0.3，无=0。
- `category_history_quality`：该领域历史评分的贝叶斯均值（0–1）。
- 无该领域专长时，仅保留历史质量，默认分较低。

#### 6.2.4 协同偏好 `CF`（ItemCF）

```text
CF(u,i) = Σ_{j∈I_u} sim(i,j)·x_uj / Σ_{j∈I_u} |sim(i,j)|
```

- `x_uj`：完成且高质量=1，完成无评分=0.5，失败=0。
- `sim(i,j)`：任务列向量余弦相似度，带收缩 `cooc/(sqrt(n_i·n_j)+λ)`，`λ=5`。
- 候选集内 min-max 归一化；冷启动置 0。
- 双向复用同一打分矩阵：任务找人按固定任务排序 worker，人找任务按固定 worker 排序任务。

#### 6.2.5 偏好匹配 `P`

```text
P = 0.5·P_accept + 0.3·category_preference + 0.2·context_match
P_accept = σ(θ_p·φ)
context_match = 0.5·difficulty_fit + 0.5·time_fit
```

- `P_accept`：worker 接受该任务的预测概率（见 6.4）。
- `category_preference`：worker 偏好向量在任务类别上的值。
- `difficulty_fit`、`time_fit`：难度、时段与偏好的匹配度。

#### 6.2.6 负载/公平 `L`

```text
load_ratio = current_load_hours / capacity_hours
L = 0.7·(1 - clamp(load_ratio, 0, 1)) + 0.3·exp(-recent_exposure / κ)
```

- `κ=20`，`recent_exposure` 为近 30 天被推荐次数。
- 过载时 `L→0`。

#### 6.2.7 客户偏好/优先级 `Q`

```text
Q = 0.6·Cust + 0.4·deadline_fit
```

- `Cust`：客户对该 worker 的偏好匹配分（见 6.5）。
- `deadline_fit`：按剩余工时与截止时间计算的可行性，越紧张越低。

### 6.3 融合与排序

```text
Score(u,i) = w_R·R + w_S·S + w_E·E + w_CF·CF + w_P·P + w_L·L + w_Q·Q
```

- 权重选择优先级：个人 `w_u` → 分群 `w_s` → 全局 `γ`；均满足第 6.6.6 节约束。
- 新用户冷启动使用画像先验 `w_u(0)`，详见 6.8。
- 排序后取 Top-N；可选 MMR-lite 做列表多样性重排（默认关闭）。
- 输出解释：每个维度贡献、命中/未命中的硬约束、违约警告、冷启动标记、权重来源与置信度。

### 6.4 Worker 偏好模型（人 → 任务）

**信号**：

| 类型 | 数据 |
|---|---|
| 声明 | 入驻问卷：偏好类别、难度、时段、地点/远程、期望报酬 |
| 行为 | 浏览/点击、申请、接受/拒绝（含理由）、放弃、完成质量 |
| 协同 | 相似 worker 的接受任务分布 |

**偏好向量**：

```text
pref_u(c) = softmax(α·explicit_u(c) + β·implicit_u(c) + γ·cf_u(c))
implicit_u(c) = Σ_{i∈I_u} decay(Δt_i)·outcome_i·1[category_i = c]
decay(Δt) = exp(-Δt/τ)，τ=30 天
```

- `α=0.4, β=0.4, γ=0.2`（可配置）。
- `outcome`：接受=+1，高质量完成=+1.2，拒绝/放弃=-1，返工=-0.5。

**接受概率**：

```text
P_accept = σ(θ_p·φ)
φ = [类别匹配, 技能匹配, 报酬匹配, 时段匹配, 距离, 历史接受率, 相似 worker 接受率]
```

- 负样本（拒绝/曝光未点击）参与训练，并记录 propensity 做偏差校正。
- 冷启动：声明偏好 + 角色/技能先验 + 约 10% 探索流量。
- 更新：在线计数/向量更新 + 定期重拟合；时间衰减应对偏好漂移。

### 6.5 Customer 偏好模型（任务 → 人）

**信号**：

| 类型 | 数据 |
|---|---|
| 声明 | 客户画像：更看重质量/专长/速度/价格/沟通/合作历史；预算与交付要求 |
| 行为 | 历史选择/驳回的候选人、重复合作、评分与投诉、验收/返工 |
| 协同 | 相似客户的候选人选择倾向 |

**偏好模型**：

```text
Cust(c,u,i) = σ(θ_c·φ_c)
φ_c = [worker 信誉, 专长匹配, 历史合作, 价格, 响应速度, 沟通评分, 按时率]
```

- 客户反馈少时，`θ_c` 向全局 `θ_global` 做层次收缩：

```text
θ_c = (n_c·θ_c_raw + n0c·θ_global) / (n_c + n0c)，n0c=30
```

- 冷启动：显式 `preference_weights` 或行业先验。
- 输出归一化到 `[0,1]`，进入第 6.2.7 节的 `Q` 维度。

### 6.6 动态权重学习

**四层机制**：先验 → 熵权修正 → 在线增量 → 定期重估；辅以探索。

#### 6.6.1 AHP 先验

- 七维权重由 AHP 成对比较矩阵导出，要求一致性比率 `CR < 0.1`。
- 先验 `γ = [0.32, 0.20, 0.15, 0.13, 0.10, 0.06, 0.04]`。
- 成对比较矩阵与导出过程放在 `app/config.py`，可审计。

#### 6.6.2 熵权修正

对候选集第 `j` 维分数：

```text
p_ij = x_ij / Σ_i x_ij
e_j = -1/ln(n)·Σ_i p_ij·ln(p_ij)          # 0·ln0 视为 0
δ_j = (1 - e_j) / Σ_k (1 - e_k)
w_j ∝ γ_j·δ_j
```

- 若某维在候选集上全为 0（`Σ_i x_ij = 0`），该维熵权取其余维均值，避免除零。
- 最终归一化为和为 1 的权重。

#### 6.6.3 在线增量

- 标签：`y=1` 若客户评分 ≥4，否则 `y=0`；回归版本可用 `y=(rating-1)/4`。
- 打分模型：`p = σ(Σ_j w_j·x_j - b)`，`w` 使用 softmax 参数化 `w=softmax(θ)`，天然满足 `w_j≥0, Σw_j=1`。
- 损失：`L = -[y·ln p + (1-y)·ln(1-p)] + λ·||w-γ||²`，`λ` 可配置。
- 每条反馈做一次 SGD 更新，学习率指数衰减。

#### 6.6.4 样本量收缩

```text
w_final = (n/(n+n0))·w_learned + (n0/(n+n0))·γ，n0=50
```

- 反馈不足时自动退回先验，保证冷启动稳定。

#### 6.6.5 时间衰减与定期重估

- 旧反馈按时间衰减：样本权重 `exp(-Δt/τ_w)`，`τ_w=30 天`（或半衰期 500 条反馈）。
- 每日批量重拟合（逻辑回归；可选 Random Forest 的 Information Gain 复估先验）。
- 在线权重与批量权重按验证集表现平滑融合，生成新版本。
- 版本写入 `data/weights/weights_vNNNN.json`，支持回滚。

#### 6.6.6 权重约束

- `w_reputation ∈ [0.25, 0.40]`（信誉始终最大）。
- `w_skill + w_expertise ≥ 0.25`。
- 所有 `w_j ≥ 0.02`。
- 和为 1。
- 个人权重与分群权重同样适用；个性化不得突破信誉下限。
- 违反约束时做投影，并记录告警。

#### 6.6.7 探索与离策略评估

- 约 10% 推荐位使用 ε-greedy 或 Thompson 探索。
- 每次推荐记录 `propensity`。
- 使用 IPS/SNIPS 校正曝光偏差，评估新权重策略。
- 探索比例、衰减参数均可配置。

### 6.7 违约分档策略

| 情况 | 处理 |
|---|---|
| 近 180 天无违约 | 正常候选 |
| 近 180 天首次违约 | 标记 `warning` + 信誉重罚降权，仍可进入候选 |
| 近 180 天 ≥2 次违约 | 直接排除出候选 |
| 历史违约（>180 天） | 按时间衰减计入 `breach_penalty` |
| 信誉低于阈值（如 0.4） | 标记 `needs_review`，不进入自动推荐 |

**违约定义**：

- `late`：超过截止时间交付。
- `cancel_after_accept`：接单后取消。
- `acceptance_failed`：验收不通过（质量不达标）。

所有违约记录、排除原因写入审计日志；推荐接口在 `debug=true` 时返回 `excluded_reason`。

### 6.8 新用户冷启动与画像驱动的个性化权重

#### 6.8.1 目标

- 新用户没有历史反馈，全局权重对他们不精准。
- 从**画像先验** `w_u(0)` 起步，随反馈逐步收敛到个人最优 `w_u*`。
- 同时适用于 worker（人→任务）与 customer（任务→人）。

#### 6.8.2 三级权重体系

| 层级 | 符号 | 来源 | 更新方式 |
|---|---|---|---|
| 全局 | `γ` | AHP 先验 | 全量反馈批量/在线更新 |
| 分群 | `w_s` | 画像分群 | 分群内反馈，向 `γ` 收缩 |
| 个人 | `w_u` | 画像先验/分群 | 个人反馈，向 `w_s` 收缩 |

```text
w_s     = (n_s/(n_s+n0_s))·w_s^learned + (n0_s/(n_s+n0_s))·γ
w_u(0)  = profile_model(profile_u) 或 w_s           # 冷启动回退 γ
w_u(t)  = (n_u/(n_u+n0_u))·w_u^learned + (n0_u/(n_u+n0_u))·w_u(0)
```

- `n0_s=50`，`n0_u=20`。
- `n0_u` 按画像完整度调整：完整度高 → 更信任画像（如 10）；完整度低 → 更保守（如 40）。
- 所有层级满足 6.6.6 的上下限与单纯形约束。

#### 6.8.3 用户画像特征

| 类别 | 特征 |
|---|---|
| 静态 | 角色、行业、经验年限、技能、擅长领域、区域、语言、可用时段 |
| 声明偏好 | 任务类别、难度、报酬、时段、工作模式 |
| 行为（如有） | 接受、完成、评分、违约 |
| 完整度 | `profile_completeness`，决定初始置信度、`n0_u` 与探索率 |

#### 6.8.4 画像 → 初始权重

1. **分群**：K-prototypes / Gower 距离（混合数值与类别特征）；或按行业/角色/经验规则分群，`K=8–12`。
2. **分群权重**：分群内已有用户个人权重的均值，向全局先验收缩。
3. **画像回归**：softmax/GBDT 从画像预测七维权重，训练于反馈充足的用户。
4. **冷启动选择**：画像回归置信度高 → 用回归结果；否则用分群权重；再回退全局。
5. **Onboarding**：5–10 个偏好问题补齐关键画像，输出 `w_u(0)`、`segment_id`、`confidence`、`source`。

#### 6.8.5 在线个性化

- 每次反馈更新个人权重：带单纯形约束的在线逻辑回归，L2 同时向 `w_u(0)` 与 `w_s`。
- 学习率随 `n_u` 衰减；个人层面同样做时间衰减。
- 探索率随反馈数下降：

```text
ε_u(n) = ε_min + (ε_0 - ε_min)·exp(-n/τ_e)
ε_0=0.30, ε_min=0.05, τ_e=20
```

- 冷启动推荐在画像先验与全局权重之间混合；随 `n_u` 增长逐步转向个人权重。
- 客户侧同样维护个人权重（质量/速度/价格/专长偏好）。

#### 6.8.6 从「不精准」到「精确」的度量

- **Oracle**：模拟中每个用户有潜在真实权重 `w_u*`；用其排序得到 oracle NDCG。
- **学习曲线**：`n ∈ {0,5,10,20,50,100}`，记录：
  - NDCG@10、HR@10；
  - `regret = NDCG_oracle - NDCG(n)`；
  - 权重恢复 `cosine(w_u(t), w_u*)`。
- **收敛步数**：NDCG 首次达到 oracle 95%（差距 ≤5%）时的反馈数。
- **冷启动提升**：`NDCG(0)` vs 全局先验 `γ`。
- **基线**：global prior / segment-only / profile-init / **profile+online**。
- 报告 mean ± 95% CI；至少 5 个 seed。

#### 6.8.7 演示流程

1. 新建一个用户，只填写画像与偏好问卷。
2. 展示初始权重 `w_u(0)` 与初始推荐（标注 `source=profile`）。
3. 依次提交 `n=5/10/20/50` 条反馈，展示个人权重轨迹与 NDCG 上升。
4. 展示与 oracle 的差距缩小，以及权重恢复 cosine 上升。
5. 回滚到 `w_u(0)`（个人权重版本），再恢复，演示可逆性。

---

## 7. API 设计

无鉴权，仅本地/内网使用。所有时间使用 ISO 8601。

### 7.1 推荐接口

#### `POST /recommend/workers`

请求：

```json
{
  "task_id": "t_0001",
  "top_n": 10,
  "explain": true,
  "debug": false
}
```

响应：

```json
{
  "task_id": "t_0001",
  "weights_version": "v0007",
  "candidates": [
    {
      "worker_id": "w_0123",
      "score": 0.87,
      "breakdown": {
        "reputation": 0.91,
        "skill": 0.95,
        "expertise": 0.80,
        "collaborative": 0.72,
        "preference": 0.66,
        "load": 0.75,
        "customer_preference": 0.83
      },
      "reasons": [
        "技能 3/3 达标",
        "客户历史评分均值 4.7",
        "近 180 天无违约",
        "当前负载 40%"
      ],
      "cold_start": false,
      "warning": false
    }
  ],
  "excluded_count": 12
}
```

#### `POST /recommend/tasks`

请求：

```json
{
  "worker_id": "w_0123",
  "top_n": 10,
  "explain": true
}
```

响应结构与上面类似，`candidates` 中为任务。

### 7.2 数据与反馈接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/workers` | 人员列表（支持分页/过滤） |
| GET | `/workers/{id}` | 人员详情 |
| GET | `/workers/{id}/reputation` | 信誉聚合与违约记录 |
| GET | `/workers/{id}/preference-profile` | worker 偏好画像 |
| PUT | `/workers/{id}/preferences` | 更新声明偏好 |
| POST | `/workers/{id}/onboarding` | 新用户画像/偏好问卷 → 初始个人权重 |
| GET | `/workers/{id}/weight-profile` | 个人权重、来源、样本量、置信度 |
| GET | `/workers/{id}/learning-curve` | 个人学习曲线快照 |
| GET | `/customers/{id}` | 客户详情 |
| GET | `/customers/{id}/preference-profile` | 客户偏好画像 |
| PUT | `/customers/{id}/preferences` | 更新客户显式偏好 |
| POST | `/customers/{id}/onboarding` | 新客户画像/偏好问卷 → 初始权重 |
| GET | `/customers/{id}/weight-profile` | 客户个人权重与置信度 |
| GET | `/customers/{id}/learning-curve` | 客户个人学习曲线 |
| GET | `/tasks` | 任务列表（支持 `status=open`） |
| GET | `/tasks/{id}` | 任务详情 |
| POST | `/assignments` | 采纳推荐，创建分配记录 |
| POST | `/feedback` | 提交客户评分 |
| GET | `/weights` | 当前权重、版本、样本量 |
| POST | `/weights/recompute` | 手动触发批量重估 |
| GET | `/weights/diff?from=v0000&to=v0007` | 两个权重版本的逐维差异 |
| POST | `/weights/rollback` | 回滚到指定版本（含 `v0000`） |
| GET | `/learning/changelog` | 学习事件与规则/参数变更日志 |
| GET | `/metrics/compare?run_a=v0000&run_b=v0007` | 两次运行指标对比 |
| GET | `/metrics/learning-curve` | 新用户 cohort 学习曲线 |
| GET | `/segments` | 画像分群与分群权重 |
| POST | `/chains/decompose` | 任务链拆解草稿（template/llm/manual） |
| POST | `/chains/{id}/approve` | 审核通过并激活任务链 |
| GET | `/chains/{id}` | 链详情、DAG、关键路径 |
| POST | `/chains/{id}/plan` | 生成完整链级分配计划 |
| POST | `/chains/{id}/replan` | 违约/延期后重规划 |
| POST | `/chains/{id}/rollback` | 回滚到上一版链计划 |
| POST | `/recommend/chains` | 给 worker 推荐适合的链/节点 |
| GET | `/metrics/chain` | 链级评估指标 |
| GET | `/metrics/offline` | 最近一次离线评估结果 |
| GET | `/metrics/online` | 在线反馈指标 |

#### `POST /assignments`

```json
{
  "task_id": "t_0001",
  "worker_id": "w_0123",
  "recommendation_context": {
    "score": 0.87,
    "rank": 1,
    "propensity": 0.42,
    "weights_version": "v0007"
  }
}
```

#### `POST /feedback`

```json
{
  "assignment_id": "a_10001",
  "overall_rating": 5,
  "quality_rating": 5,
  "timeliness_rating": 4,
  "communication_rating": 5,
  "comment": "交付质量很好，沟通顺畅"
}
```

响应返回 `feedback_id`、是否触发权重更新、新权重版本号（如有）。

### 7.3 错误处理

| 状态码 | 场景 |
|---|---|
| 404 | task/worker/assignment 不存在 |
| 409 | 任务已被分配、重复反馈 |
| 422 | 参数校验失败（评分越界等） |
| 400 | 硬约束导致无候选（可返回排除原因汇总） |

---

## 8. 任务链拆解

### 8.1 目标与范围

把客户发布的**一个任务**拆成带依赖的子任务 DAG，再为每个子任务分配**不同 worker**，最后合成一个整体交付；并在链级别优化工期、成本、违约风险与交接成本。

**业务场景**：客户只发布一个任务；系统拆解后按依赖关系把子任务分给多个 worker；客户审核拆解与分配，最终验收一个整体交付。

**角色与视角**：

| 角色 | 看到什么 | 做什么 |
|---|---|---|
| 客户 | 原始任务、拆解后的子任务 DAG、整体进度 | 发布任务、审核拆解、确认分配、整体验收、评分 |
| Worker | 自己被推荐/分配的节点任务、依赖与交接上下文 | 接受/拒绝节点、交付、接收节点反馈 |
| 平台/管理员 | 全链 DAG、关键路径、风险与重规划 | 审核拆解、处理 blocked 节点、批准重规划 |
| 系统 | 拆解、校验、匹配、跟踪、学习 | 自动拆解、逐节点推荐、违约传播、权重更新 |

**端到端流程**：

```text
客户发布任务
  → 系统拆解为子任务 DAG
  → 客户审核拆解（可增删节点/改依赖）
  → 按拓扑序逐节点推荐不同 worker
  → 客户确认分配（或系统生成链计划）
  → worker 执行各自节点，依赖满足后解锁下游
  → 节点交付/交接 → 客户整体验收
  → 节点评分 + 链评分 → 信誉/偏好/权重学习
```

**与「单人整包」的区别**：

| 维度 | 单人整包 | 任务链拆解 |
|---|---|---|
| 分配对象 | 一个 worker | 多个 worker，每人一个/多个节点 |
| 依赖 | 无 | DAG 依赖与交接 |
| 风险 | 单点风险高 | 可分散，但有协调成本 |
| 评价 | 整单评分 | 节点评分 + 链评分 |
| 适用 | 简单任务 | 复杂、多技能、长周期任务 |

**MVP 范围**：
- 模板化拆解 + 人工审核；
- DAG 校验（无环、覆盖、可分配、截止可行）；
- 链级贪心分配（带前瞻）；
- 违约传播与受限重规划。

**非本阶段范围**：
- 无人工审核的全自动 LLM 拆解；
- 多项目/多链全局调度；
- 自动修改客户需求。

### 8.2 概念模型

| 概念 | 定义 |
|---|---|
| TaskChain | 一条任务链：根任务、客户、截止时间、预算、状态、版本 |
| SubTask | 链上的节点：类别、技能要求、预计工时、验收标准、状态 |
| ChainEdge | 依赖边 `from → to`；`to` 必须在 `from` 完成后开始 |
| DAG | 有向无环图；必须有拓扑序，禁止环 |
| Critical Path | 最长路径；决定链的最短可能工期 |
| Slack | 非关键路径节点可延迟而不影响总工期的余量 |
| Handoff | 相邻节点由不同 worker 执行产生的交接成本 |
| Chain Breach | 任一关键路径节点违约导致链级延期或验收失败 |

### 8.3 拆解方法

#### 8.3.1 模板库（MVP 默认）

按 12 个任务领域维护 WBS 模板。模板定义节点类型、典型工时、技能要求、依赖关系与验收标准。

| 领域 | 模板示例 |
|---|---|
| 设计 | 需求澄清 → 草图 → 初稿 → 内部评审 → 修改 → 交付 |
| 软件开发 | 需求 → 方案 → 开发 → 测试 → 验收 → 上线 |
| 内容 | 选题 → 资料 → 初稿 → 编辑 → 审核 → 发布 |
| 运营活动 | 目标 → 方案 → 物料 → 执行 → 复盘 |
| 数据标注 | 规范 → 试标 → 批量标注 → 质检 → 交付 |

**模板文件**：
- 数据：`specs/task-chain-templates/common_task_chains.json`（12 类，已校验唯一 key、依赖存在、无环、有根节点）。
- 规范：`specs/task-chain-templates/README.md`。
- 实现时复制到：`task-recommender/data/chain_templates/`。

节点类型：`task`（生产）、`review`（评审/质检）、`milestone`（里程碑）、`delivery`（交付）。

#### 8.3.2 实例化与粒度控制

```text
输入：task.description, category, difficulty, deadline, budget, required_skills
输出：SubTask 列表 + ChainEdge 列表
```

规则：
1. 选择类别模板；无模板时退化为「单人整包」。
2. 按 `target_hours`（默认 2–16h）拆分/合并节点。
3. 节点数上限 `max_nodes`（默认 10）；超出则合并低风险节点。
4. 默认顺序依赖；只有明确无依赖的节点才并行。
5. 交付前必须有 `review` 或 `delivery` 节点。
6. **覆盖校验**：每个需求条目至少映射到一个节点；无归属节点删除。

#### 8.3.3 校验（通过才允许进入分配）

| 校验 | 规则 |
|---|---|
| 无环 | 拓扑排序成功 |
| 覆盖 | 需求覆盖矩阵无空洞 |
| 可分配 | 每个节点的必需技能在 worker 池中存在 |
| 截止可行 | 关键路径工时 ≤ 可用时间 |
| 预算可行 | 预计成本 ≤ 预算 |
| 粒度合理 | 节点工时在 `[min_hours, max_hours]` |
| 人工审核 | 草稿状态必须经人工批准才激活 |

#### 8.3.4 可选 LLM 辅助拆解

- 模式 `llm`：输入任务描述 + 模板 + 约束，输出 JSON DAG。
- **模板接地**：LLM 只做模板骨架上的填充/适配，必须给出「生成节点 → 模板节点」的映射；不允许完全自由生成整链。
- 必须经过：JSON schema 校验 → 无环校验 → 覆盖校验 → 质量分检查 → 人工审核。
- 任何校验失败或质量分低于阈值 → 回退模板拆解，不自动激活。
- 记录 `model`、`prompt_version`、`prompt_tokens`、`completion_tokens`、`total_tokens`，用于成本对比。
- 默认不启用；无 LLM 时系统仍可运行。

#### 8.3.5 从历史链学习模板

- 按类别挖掘历史链的频繁子图/DAG 模式，更新模板版本。
- 需要足够链历史；冷启动使用默认模板。
- 模板版本化，A/B 比较拆解质量与链级指标。

#### 8.3.6 改进后的拆解流水线（v2）

```text
任务理解 → 模板检索(Top-K) → 变体选择 → 多模板组合 → 实例化
→ 覆盖/缺口 → 依赖/回路校验 → 粒度优化 → 可行性/成本
→ 质量分 → 人工审核/diff → 学习
```

| 步骤 | 做什么 | 输出 |
|---|---|---|
| 0 任务理解 | 抽取需求条目、交付物、约束、预算、截止时间 | `Requirement[]` |
| 1 模板检索 | 按类别/交付物/技能/历史成功率打分，取 Top-K | 候选模板 |
| 2 变体选择 | simple/standard/complex，按难度/预算/截止选择 | 变体 |
| 3 多模板组合 | 跨类别任务合并模板，去重共享节点 | 组合 DAG |
| 4 实例化 | 可选节点按 `include_if` 展开；并行组转边；工时缩放 | SubTask/Edge |
| 5 覆盖分析 | 需求→节点覆盖矩阵；缺口补齐或标记 | 覆盖率/缺口 |
| 6 依赖校验 | DAG 无环；review-rework 有界；交付节点可达 | 校验报告 |
| 7 粒度优化 | 小于下限合并，大于上限拆分，计入交接成本 | 优化后 DAG |
| 8 可行性/成本 | 技能/容量/截止/预算；不可行时给放宽建议 | feasible/建议 |
| 9 质量分 | 覆盖/粒度/依赖/可行/模板匹配/历史成功 | 0–1 分 + 问题列表 |
| 10 人工审核 | diff、增删改、批准/回退 | 激活版本 |
| 11 学习 | 记录人工修改与链结果，更新模板 | 新模板版本 |

**关键改进点**：

1. **不是只选一个模板**：Top-K 检索 + 多模板组合，适配跨类别任务。
2. **模板有变体**：同一模板支持 simple/standard/complex，避免「一刀切」。
3. **可选节点与条件展开**：按需求/预算/质量档位决定是否包含某节点。
4. **需求覆盖矩阵**：每个需求必须映射到节点，禁止漏项。
5. **有界 review-rework**：评审失败触发返修节点，但不形成图环。
6. **质量分闸门**：低分拆解必须人工复核或 LLM 细化。
7. **人工修改即学习信号**：模板随编辑和链结果迭代。

#### 8.3.7 拆解质量分与置信度

```text
Quality = 0.30·Coverage
        + 0.20·Granularity
        + 0.15·DependencyValidity
        + 0.15·Feasibility
        + 0.10·TemplateFit
        + 0.10·HistoricalSuccess
        - RiskPenalty
```

| 项 | 定义 |
|---|---|
| Coverage | 被节点覆盖的需求条目比例 |
| Granularity | 节点工时落在目标区间的比例 |
| DependencyValidity | 无环、依赖存在、交付可达 |
| Feasibility | 技能、容量、截止、预算均可满足 |
| TemplateFit | 模板与任务类别/交付物的匹配度 |
| HistoricalSuccess | 相似模板历史链的成功率 |
| RiskPenalty | 单点依赖、关键路径过紧、需求不确定 |

- `quality < threshold`（默认 0.75）→ 必须人工复核或 LLM 细化。
- 输出 `top_issues` 与 `suggestions`（如“增加测试节点”“延长截止”“拆分前端节点”）。

#### 8.3.8 模板 schema v1.1

在 v1 基础上新增可选字段，旧模板保持向后兼容：

| 字段 | 用途 |
|---|---|
| `variants` | simple / standard / complex 的节点与工时差异 |
| `nodes[].optional` | 是否可选节点 |
| `nodes[].include_if` | 条件表达式（需求/预算/质量档位） |
| `nodes[].parallel_group` | 并行组；实例化时转为无边依赖 |
| `nodes[].hours_range` | `[min, expected, max]`，替代单一工时 |
| `nodes[].review_of` | 该节点评审哪个节点 |
| `nodes[].rework_of` | 该节点返修哪个节点 |
| `nodes[].max_rework_rounds` | 返修轮次上限，防止无限循环 |
| `nodes[].risk_flags` | 风险标记（单点/高不确定/强依赖） |
| `handoffs` | 边上交接物：`from, to, artifact, format` |
| `requirements` | 模板覆盖的需求类型 |
| `quality_rules` | 覆盖/粒度/可行性阈值 |
| `changelog` | 模板版本历史 |

- 可选节点被排除时，按 `optional_policy: bypass` 将前驱直接连到后继。
- `review` 节点用 `review_of` 指定评审对象；`rework` 节点用 `rework_of` 指定返修对象，并用 `max_rework_rounds` 限制轮次，不形成图环。
- 缺省字段使用系统默认值；v1 模板无需一次性迁移。
- 模板变更必须升 `version`；已激活的链锁定模板版本。

#### 8.3.9 从人工修改与链结果中学习

- 记录 `DecompositionEdit`：`add / remove / merge / split / edge_change`、原因、操作者。
- 统计高频修改 → 更新模板变体、默认节点与工时范围。
- 链结果（延期、返工、违约）回写模板的 `HistoricalSuccess`。
- 模板版本 A/B；只有显著优于旧版才切换默认。
- 人工修改距离（edit distance）作为拆解质量与模板改进的指标。

### 8.4 链级分配

#### 8.4.1 节点级打分

每个节点复用第 6 章的七维打分（信誉、技能、专长、协同、偏好、负载、客户偏好），并叠加链级上下文特征。

#### 8.4.2 链级特征

| 特征 | 含义 | 方向 |
|---|---|---|
| Handoff Continuity | 相邻依赖节点是否同一 worker/同风格 | 越高越好 |
| Schedule Feasibility | 节点排期是否能在截止前完成 | 越高越好 |
| Chain Reputation | worker 在相似链/节点类型上的历史履约 | 越高越好 |
| Critical Path Risk | 关键路径节点的违约风险向下游传播 | 越低越好 |
| Skill Complementarity | 链上技能覆盖是否过度依赖单人 | 越高越好 |
| Chain Load | 单个 worker 在整条链上的总工时占比 | 适中最好 |

#### 8.4.3 链级目标

```text
ChainPlanScore = Σ_{v∈V} α_v·NodeScore(u_v, v)
               + λ_cont·Continuity
               + λ_sched·ScheduleFeasibility
               + λ_chain·ChainReputation
               - λ_risk·BreachPropagationRisk
```

- 关键路径节点 `α_v=1.2`，其余 `1.0`（可配置）。
- `Continuity = 1 - handoffs / max(1, |V|-1)`。
- `ScheduleFeasibility` 由每个节点的可用窗口与链 slack 计算。
- `BreachPropagationRisk = Σ_{v∈critical_path} breach_risk(u_v,v)·downstream_impact(v)`。

**硬约束**：依赖顺序、技能、容量、可用时间、违约分档、节点验收标准。

#### 8.4.4 分配算法

| 阶段 | 算法 | 说明 |
|---|---|---|
| MVP | 拓扑序贪心 + 1 步前瞻 | 每个就绪节点选边际链分最高的 worker |
| 增强 | Beam Search（宽度 5–10） | 小链（≤20 节点）上近似全局最优 |
| 可选 | MILP | 节点数少、约束线性时求最优；否则不用 |

- 无可行 worker → 节点标记 `blocked`，返回可放宽项（技能/截止/预算）供人工决策。
- 已开始/已完成节点在重规划中锁定，不参与重选。

#### 8.4.5 输出

- **面向客户**：一条整体交付 + 拆解/分配审批视图（节点、依赖、每个节点推荐谁）。
- **面向 worker**：只展示其被分配的节点任务、前置依赖、交接说明、验收标准。
- **面向平台**：blocked 节点、关键路径风险、重规划建议。
- 完整链计划：每个节点一个推荐 worker + 备选 Top-N。
- 链级指标：预计工期、关键路径、成本、交接次数、违约风险、worker 利用率。
- 解释：为什么这样拆、为什么选这个 worker、关键路径风险在哪。

### 8.5 违约传播与重规划

**传播规则**：

1. 节点违约（延期/取消/验收失败）→ 沿出边把延迟传给下游节点。
2. 只累计**关键路径**上的延迟；非关键路径延迟先消耗 slack。
3. 链级违约严重度：

```text
chain_delay = max(0, critical_path_delay - chain_slack)
severity = chain_delay / chain_slack      # 或按截止时间归一化
```

4. worker 的链级信誉按严重度扣分；下游节点候选的 `Critical Path Risk` 上调。

**重规划触发**：

- 节点违约、预计延期超过阈值、worker 不可用、客户改需求。
- 只重算受影响节点及其下游；已完成/进行中节点锁定。
- 新计划版本化，需人工确认后生效；支持回滚到上一版计划。

### 8.6 数据模型

| 实体 | 关键字段 |
|---|---|
| `TaskChain` | `chain_id, root_task_id, customer_id, status, deadline, budget, critical_path, plan_version, created_at` |
| `SubTask` | `subtask_id, chain_id, title, category, required_skills, estimated_hours, node_type, acceptance_criteria, status, assigned_worker_id` |
| `ChainEdge` | `chain_id, from_node, to_node, edge_type` |
| `ChainPlan` | `plan_id, chain_id, version, score, makespan, cost, risk, handoff_count, status, created_at` |
| `ChainPlanNode` | `plan_id, subtask_id, worker_id, rank, node_score, start_at, end_at` |
| `ChainFeedback` | `chain_id, plan_id, node_id, overall_rating, node_rating, on_time, rework_count, breach_type, created_at` |
| `DecompositionTemplate` | `template_id, category, version, dag_json, default_hours, required_skills, variants, quality_rules, changelog` |
| `ChainSnapshot` | `chain_id, plan_id, n_feedback, ndcg_at_10, makespan, breach_rate, created_at` |
| `Requirement` | `requirement_id, task_id, text, priority, covered_by_node` |
| `DecompositionDraft` | `draft_id, chain_id, template_id, variant, status, quality_score, diff_from` |
| `DecompositionQuality` | `draft_id, coverage, granularity, dependency, feasibility, template_fit, historical_success, risk_penalty, total, issues` |
| `DecompositionEdit` | `edit_id, draft_id, action, node_key, reason, operator, created_at` |

### 8.7 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/chains/decompose` | 输入 task_id + mode → 链草稿 + 质量分 + 候选模板 + 覆盖矩阵 |
| POST | `/chains/decompose/refine` | 按质量分/人工意见细化草稿 |
| GET | `/chains/{id}/decomposition/diff` | 草稿与模板/上一版的差异 |
| POST | `/chains/{id}/decomposition/rollback` | 回滚拆解版本 |
| POST | `/chains/{id}/approve` | 人工审核通过，激活链 |
| GET | `/chains/{id}` | 链详情、DAG、关键路径 |
| POST | `/chains/{id}/plan` | 生成完整链级分配计划 |
| POST | `/chains/{id}/nodes/{node_id}/recommend` | 单节点 Top-N 候选人 |
| POST | `/chains/{id}/nodes/{node_id}/assign` | 确认该节点分配给指定 worker |
| POST | `/chains/{id}/nodes/{node_id}/feedback` | 节点级客户评分 |
| POST | `/subtasks/{id}/accept` | worker 接受节点任务 |
| POST | `/subtasks/{id}/deliver` | worker 提交节点交付 |
| GET | `/workers/{id}/subtasks` | worker 的节点任务列表 |
| POST | `/recommend/chains` | 给 worker 推荐适合的链/节点 |
| POST | `/chains/{id}/replan` | 违约/延期后重规划 |
| POST | `/chains/{id}/rollback` | 回滚到上一版链计划 |
| GET | `/metrics/chain` | 链级评估指标 |

### 8.8 评估

#### 8.8.1 拆解质量

| 指标 | 定义 | 目标 |
|---|---|---|
| 需求覆盖率 | 被节点覆盖的需求条目比例 | 100% |
| 无环率 | 拓扑排序成功的链比例 | 100% |
| 粒度合理性 | 节点工时在目标区间的比例 | ≥90% |
| 依赖密度 | 边数 / 节点数 | 在模板范围内 |
| 人工通过率 | 审核通过的草稿比例 | ≥80% |
| 模板命中率 | 使用现有模板的比例 | 可观测 |
| 拆解质量分 | 8.3.7 的 Quality | ≥0.75 |
| 人工修改距离 | 编辑距离 / 节点数 | 越低越好 |
| 模板检索命中 | 正确模板在 Top-K | Top-1 ≥70%，Top-3 ≥90% |

#### 8.8.2 分配质量

| 指标 | 定义 | 目标 |
|---|---|---|
| 链工期 | 关键路径完成时间 | 越短越好 |
| 按时率 | 链在截止前完成的比例 | 高于基线 |
| 违约率 | 链级违约数 / 链数 | ≤2% |
| 交接次数 | 相邻节点换人次数 | 越低越好 |
| 关键路径延迟 | 关键路径实际 vs 计划 | ≤阈值 |
| 计划稳定性 | 重规划前后 Top-N Jaccard | 越高越好 |
| 节点 NDCG@10 | 节点级推荐准确率 | 高于基线 |
| 新用户链学习曲线 | 节点 NDCG vs 反馈数 | 上升并收敛 |

#### 8.8.3 基线

- 单人整包（不拆解）；
- 模板 + 随机分配；
- 模板 + 节点贪心（无链级特征）；
- **模板 + 链级贪心/Beam Search**；
- LLM 拆解 + 人工审核（可选）。

**验收**：链级分配相对单人整包，工期或违约率至少一项改善 ≥10%，且依赖违规为 0；人工通过率 ≥80%；拆解质量分 ≥0.75；模板检索 Top-1 ≥70% 或 Top-3 ≥90%；人工修改距离较上一版下降。

### 8.9 模拟数据

- 生成 300 条任务链，覆盖 12 个类别，每链 3–10 个节点。
- 节点带真实工时、技能要求、依赖关系；按模板生成 DAG。
- 模拟节点完成质量、延期、违约，并沿关键路径传播。
- 70% 链产生反馈；包含冷启动 worker/task 与时间漂移。
- 为新用户 cohort 生成链上节点级反馈，用于学习曲线。

### 8.10 实施阶段

| 阶段 | 内容 |
|---|---|
| Phase 1（MVP） | 模板拆解、DAG 校验、链级贪心、违约传播、API、测试 |
| Phase 2 | 历史链学习模板、Beam Search/MILP、动态重规划 |
| Phase 3 | LLM 辅助拆解（人工审核）、多链全局调度、链级个性化权重 |

### 8.11 风险与缓解

| 风险 | 缓解 |
|---|---|
| 过度拆解导致协调成本 | 节点上限、目标工时、交接惩罚 |
| 拆解不足导致单点风险 | 关键路径/单点依赖检查 |
| 依赖关系错误 | 人工审核 + DAG 校验 |
| LLM 幻觉/漏项 | schema/覆盖/无环校验 + 人工闸门 + 模板回退 |
| 组合优化复杂 | 限制节点数、贪心/Beam、必要时 MILP |
| 历史链稀疏 | 默认模板 + 先验，不强行学习 |
| 需求变更 | 版本化计划、重规划、回滚 |
| 交接成本高 | Continuity 项、同 worker 优先 |

### 8.12 论文依据

- CrowdForge（Kittur et al., UIST 2011）：复杂众包任务的 map-reduce 式拆解。
- Turkomatic（Kulkarni et al., CSCW 2012）：Price-Divide-Solve 的众包拆解流程。
- Data Centric Workflows for Crowdsourcing（Hélouët et al., 2020）：复杂众包工作流与子任务精化。
- DAG 调度与关键路径（HEFT/CPOP）：关键路径优先、makespan 优化。
- DynTaskMAS（ICAPS/AAAI）：动态任务图驱动的多智能体异步并行执行。
- AdaptOrch（arXiv 2602.16873）：按 DAG 结构选择并行/串行/层次/混合编排。

---

## 9. 评估方案

### 9.1 离线评估

**数据划分**：按时间 70% 训练 / 15% 验证 / 15% 测试。

**排序评估**：

- 留一法：每个 worker 的最后一次接受任务作为正样本；每个 task 的实际选择 worker 作为正样本。
- 候选集 = 全部合法候选 + 100 个采样负样本。
- 相关性：二元（接受/选择=1）；NDCG 可用评分作为增益。
- 指标：`HR@5/10/20`、`NDCG@10`、`MRR`、`MAP@10`，双向分别报告。

**评分预测**：

- `RMSE`、`MAE`（预测评分 vs 客户实际评分，时间留出集）。

**偏好评估**：

- `AUC`、`LogLoss`、校准曲线（P(accept)/P(select) vs 实际）。
- 负偏好识别：拒绝任务的 Precision/Recall。

**公平与覆盖**：

- 任务覆盖率、人员覆盖率。
- 人员曝光 Gini、模拟分配后负载 Gini。
- 冷启动子集 `HR@10`。

**业务与合规**：

- 违约率（目标 ≤2%）、约束违规率（必须为 0）。
- 信誉校准度（预测可靠性 vs 实际违约，Brier score）。
- 专长匹配 `NDCG@10`。
- 权重下限合规性。

**离策略评估**：

- IPS / SNIPS，使用日志中的 propensity，估计新权重策略效果。
- 报告有效样本量与置信区间。

**基线**：

| 基线 | 说明 |
|---|---|
| Random | 合法候选中随机 |
| Content-only | 仅技能+专长+信誉 |
| CF-only | 仅协同过滤 |
| Fixed AHP | 固定七维先验权重 |
| Online-only | 仅在线增量 |
| **Online + Batch** | 本设计推荐方案 |

### 9.2 在线指标

`GET /metrics/online` 返回滚动窗口指标：

- 平均客户评分、评分分布。
- 接受率、按时率、返工率、违约率。
- 推荐点击/采纳率。
- 当前权重版本、样本量、最近更新时间。
- 与上一版本的指标对比。

### 9.3 验收标准

1. `Online + Batch` 在测试集 `NDCG@10` 上相对 `Fixed AHP` 提升 ≥5%。
2. `RMSE` 低于 `Fixed AHP`。
3. 违约率不高于 `Fixed AHP`，且 ≤2%。
4. 冷启动子集 `HR@10` 不劣于先验/内容基线。
5. 硬约束违规数为 0。
6. 所有权重版本满足第 6.6.6 节约束。
7. 模拟漂移后，权重在预定窗口内恢复（如 30 天）。
8. 新用户：`profile+online` 在 n=50 时 NDCG@10 与权重恢复优于 global/segment-only；收敛步数 ≤50。

### 9.4 两次运行对比协议（评委演示）

**定义**：

- **Run A（基线）**：使用 `v0000`，即 AHP 先验，未学习任何反馈。
- **Run B（学习后）**：使用 `vNNNN`，由训练/验证期反馈学习得到。
- 两次运行使用**同一测试集、同一候选集、同一随机种子**，仅权重版本不同。
- 严禁使用测试期反馈训练 Run B；学习只使用训练/验证期数据。

**对比指标表**：

| 类别 | 指标 | 计算方式 | Run A | Run B | 期望方向 |
|---|---|---|---|---|---|
| 正确率 | NDCG@10 | 测试期留一法排序 | `evaluate.py` 输出 | `evaluate.py` 输出 | B > A |
| 正确率 | HR@10 | 命中率 | `evaluate.py` 输出 | `evaluate.py` 输出 | B > A |
| 正确率 | MRR | 首个命中倒数排名 | `evaluate.py` 输出 | `evaluate.py` 输出 | B > A |
| 质量预测 | RMSE / MAE | 预测评分 vs 客户评分 | `evaluate.py` 输出 | `evaluate.py` 输出 | B < A |
| 用时 | 响应延迟 p50/p95 | 单次推荐 API 耗时 | `evaluate.py` 输出 | `evaluate.py` 输出 | B 不明显变差 |
| Token 消耗 | tokens/请求 | 当前架构无 LLM 调用，记 0；若增加 LLM 解释层则记录 | 0 | 0 | 不适用/不增加 |
| 重复犯错 | 重复推荐违规/低信誉 worker 次数 | 测试查询 Top-N 命中历史违约或客户驳回 worker 的次数 | `evaluate.py` 输出 | `evaluate.py` 输出 | B < A |
| 动作成功率 | 推荐采纳率 | 被接受或选择的推荐数 / 推荐数 | `evaluate.py` 输出 | `evaluate.py` 输出 | B > A |
| 履约 | 违约率 | 违约分配数 / 分配数 | `evaluate.py` 输出 | `evaluate.py` 输出 | B ≤ A，且 ≤2% |
| 合规 | 硬约束违规次数 | 违反技能/容量/等级/违约分档的候选数 | 0 | 0 | 均为 0 |
| 公平 | 曝光 Gini | 人员曝光分布 | `evaluate.py` 输出 | `evaluate.py` 输出 | B ≤ A 或可接受 |
| 覆盖 | 任务/人员覆盖率 | Top-N 中出现过的比例 | `evaluate.py` 输出 | `evaluate.py` 输出 | 不明显下降 |

- 表中数值必须由 `scripts/evaluate.py --compare --run-a v0000 --run-b vNNNN` 生成，**禁止手填或编造**。
- 报告同时给出测试样本量、bootstrap 置信区间，以及 paired bootstrap 显著性检验。
- 当前系统不调用 LLM，token 消耗恒为 0；若后续增加 LLM 解释/对话层，则在 `metrics.online` 中记录 `prompt_tokens / completion_tokens / total_tokens`。

### 9.5 学习证据（评委可检查）

不要只输出「它变聪明了」，必须导出可核对的证据：

1. **权重差异**：`GET /weights/diff?from=v0000&to=vNNNN`
   - 每维 before/after、绝对变化、相对变化、是否触碰上下限。
   - 示例：`reputation 0.320 → 0.344 (+0.024)`。
2. **偏好画像变化**：`GET /learning/changelog?type=preference`
   - 新增/更新的 worker 偏好向量、customer 偏好向量、置信度、样本量。
3. **信誉与履约变化**
   - 贝叶斯均分、完成率、按时率、违约次数、返工率的变化。
4. **规则/参数变化**
   - 配置 diff：违约窗口、排除阈值、`n0`、探索比例、学习率等。
   - 每次变更记录：触发原因、样本量、验证集指标、操作者/系统。
5. **同查询反事实对比**
   - 固定 100 个测试查询，导出 Run A / Run B 的 Top-10 与排名变化。
   - 文件：`reports/compare_queries.csv`，评委可抽查。
6. **学习事件日志**：`GET /learning/changelog`
   - 时间、事件类型（online_update / batch_refit / rollback / rule_change）、版本、样本数、指标、是否采纳。

### 9.6 版本回滚与现场演示

**版本存储**：

```text
data/weights/
├── active.json              # {"active_version": "v0007"}
├── weights_v0000.json       # AHP 先验（第一次运行之前）
├── weights_v0001.json
└── ...
```

**回滚语义**：

- 可回滚到任意历史版本，包括 `v0000`（第一次运行之前的基线）。
- 回滚只切换 `active.json` 指针，不删除任何版本或反馈数据。
- 回滚后推荐结果必须与当时该版本的结果一致（同一数据、同一 seed、无缓存串扰）。
- 每次回滚写入审计日志，包含操作原因与操作者。

**API**：

```http
POST /weights/rollback
{"to_version": "v0000", "reason": "评委演示：退回第一次运行之前"}
```

响应：

```json
{"previous_version": "v0007", "active_version": "v0000", "rolled_back_at": "2026-11-13T12:00:00Z"}
```

**现场演示脚本** `scripts/demo_judges.py`（约 5 分钟）：

1. 展示当前版本与两次对比：`GET /weights`、`GET /metrics/compare?run_a=v0000&run_b=v0007`。
2. 展示学习证据：`GET /weights/diff?...`、`GET /learning/changelog`、`reports/compare_queries.csv`。
3. 选一个固定任务，记录 Run B 的 Top-10。
4. 执行回滚到 `v0000`。
5. 用同一任务、同一候选集再次推荐，展示结果回到基线（附 diff）。
6. 再切回 `v0007`，展示恢复。
7. 展示审计日志中的 rollback 记录。

**确定性保障**：

- 固定 seed、固定候选顺序、版本化缓存 key（`cache_key = f"{query_hash}:{weights_version}"`）。
- 回滚前后对比脚本自动校验 Top-N 是否与历史快照一致。

### 9.7 新用户学习曲线验收（从不准到准）

| 指标 | 定义 | 目标 |
|---|---|---|
| `NDCG@10(0)` | 仅画像先验时的推荐 | 高于全局先验基线 |
| `NDCG@10(n)` | n 条反馈后的推荐 | 随 n 单调上升 |
| 收敛步数 | NDCG 达到 oracle 95% 的 n | ≤50 |
| `Regret(n)` | `NDCG_oracle - NDCG(n)` | 随 n 下降 |
| 权重恢复 | `cosine(w_u(t), w_u*)` | 随 n 上升；n=50 时 ≥0.8 |
| 冷启动提升 | `NDCG(0) - NDCG_global` | >0 |
| 用户收敛覆盖率 | 新用户中达到收敛的比例 | ≥80% |

- 基线：global prior / segment-only / profile-init / **profile+online**。
- 报告 mean ± 95% CI；至少 5 个 seed。
- 验收：`profile+online` 在 n=50 时 NDCG 与权重恢复均优于 global/segment-only；不存在持续下降的用户组。
- 输出 `reports/learning_curve.md` 与学习曲线图。

---

## 10. 工程结构

```text
task-recommender/
├── README.md
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI 应用与路由
│   ├── schemas.py                  # Pydantic 请求/响应模型
│   ├── config.py                   # 权重先验、约束、参数、seed
│   ├── data/
│   │   ├── __init__.py
│   │   ├── synthetic.py            # 结构化潜变量 DGP
│   │   ├── ground_truth.py         # 潜在结果生成（仅评估可读）
│   │   └── store.py                # 内存数据仓库/CSV 加载
│   ├── features.py                 # 七维特征计算
│   ├── reputation.py               # 信誉聚合与违约分档
│   ├── feedback.py                 # 反馈落库与触发更新
│   ├── preference/
│   │   ├── __init__.py
│   │   ├── worker.py               # worker 偏好模型
│   │   └── customer.py             # customer 偏好模型
│   ├── personalization/
│   │   ├── __init__.py
│   │   ├── profile.py              # 画像特征与完整度
│   │   ├── segments.py             # 画像分群与分群权重
│   │   └── user_weights.py         # 个人权重初始化/更新/收缩
│   ├── chains/
│   │   ├── __init__.py
│   │   ├── templates.py            # WBS 模板与实例化
│   │   ├── dag.py                  # 拓扑排序/无环/关键路径/slack
│   │   ├── decompose.py            # 模板/LLM 拆解入口与校验
│   │   ├── planner.py              # 链级贪心/Beam/MILP
│   │   └── propagation.py          # 违约传播与重规划
│   ├── learning/
│   │   ├── __init__.py
│   │   ├── weights.py              # AHP 先验、熵权、约束投影
│   │   ├── online.py               # 在线增量学习
│   │   └── preference.py           # 偏好特征学习
│   ├── models/
│   │   ├── __init__.py
│   │   ├── itemcf.py               # ItemCF 相似度与打分
│   │   └── hybrid.py               # 融合、Top-N、解释生成
│   ├── service.py                  # 编排：过滤→召回→排序→解释
│   ├── versioning.py               # 权重版本、diff、回滚、审计
│   └── metrics.py                  # 离线/在线指标
├── scripts/
│   ├── generate_data.py
│   ├── calibrate_data.py           # 目标统计矩匹配
│   ├── validate_data.py            # 保真度报告
│   ├── simulate_feedback.py
│   ├── evaluate.py
│   ├── learning_curve.py           # 新用户学习曲线评估
│   ├── chain_demo.py               # 拆解→链级分配→违约传播演示
│   ├── validate_templates.py       # 模板 JSON/DAG 校验
│   ├── demo_judges.py              # 两次对比 + 学习证据 + 回滚演示
│   ├── rollback.py                 # CLI 回滚
│   └── run_demo.py
├── data/
│   ├── *.csv                       # 生成的数据
│   ├── ground_truth.csv            # 潜在结果（仅评估可读）
│   ├── target_stats.json           # 目标统计量
│   ├── chain_templates/            # 12 类任务链模板 JSON
│   └── weights/                    # active.json + weights_vNNNN.json
├── reports/                        # compare_queries.csv、data_calibration.md、data_fidelity.md、learning_curve.md 等
└── tests/
    ├── test_synthetic.py
    ├── test_data_calibration.py
    ├── test_features.py
    ├── test_reputation.py
    ├── test_preference.py
    ├── test_personalization.py
    ├── test_chains.py
    ├── test_decomposition.py
    ├── test_itemcf.py
    ├── test_weights.py
    ├── test_versioning.py
    ├── test_hybrid.py
    └── test_api.py
```

---

## 11. 配置项

| 配置 | 默认值 | 说明 |
|---|---|---|
| `weights.prior` | 0.32/0.20/0.15/0.13/0.10/0.06/0.04 | 七维 AHP 先验 |
| `weights.versions_dir` | `data/weights` | 权重版本目录 |
| `weights.active_version` | `v0000` | 初始激活版本（第一次运行之前） |
| `demo.compare_queries` | 100 | 反事实对比查询数 |
| `demo.report_dir` | `reports/` | 对比报告输出目录 |
| `weights.reputation_bounds` | [0.25, 0.40] | 信誉权重上下限 |
| `weights.skill_expertise_min` | 0.25 | 技能+专长下限 |
| `weights.min_each` | 0.02 | 单维下限 |
| `weights.shrink_n0` | 50 | 样本量收缩参数 |
| `weights.l2_lambda` | 0.1 | 向先验正则强度 |
| `weights.decay_tau_days` | 30 | 时间衰减 |
| `weights.exploration_epsilon` | 0.10 | 探索比例 |
| `breach.window_days` | 180 | 违约观察窗口 |
| `breach.exclude_threshold` | 2 | 排除阈值 |
| `breach.review_threshold` | 0.40 | 信誉复核阈值 |
| `preference.alpha/beta/gamma` | 0.4/0.4/0.2 | worker 偏好信号融合 |
| `preference.customer_n0` | 30 | 客户偏好层次收缩 |
| `personalization.n_segments` | 10 | 画像分群数 |
| `personalization.n0_segment` | 50 | 分群权重收缩强度 |
| `personalization.n0_user` | 20 | 个人权重收缩强度 |
| `personalization.profile_model` | softmax_regression | 画像→权重模型 |
| `personalization.exploration_eps0` | 0.30 | 新用户初始探索率 |
| `personalization.exploration_eps_min` | 0.05 | 最低探索率 |
| `personalization.exploration_tau` | 20 | 探索衰减尺度 |
| `personalization.convergence_tolerance` | 0.05 | 收敛判定阈值 |
| `personalization.new_user_cohort` | 200 | 模拟新用户数 |
| `chain.target_hours` | [2, 16] | 节点目标工时区间 |
| `chain.max_nodes` | 10 | 单链节点上限 |
| `chain.critical_path_alpha` | 1.2 | 关键路径节点权重 |
| `chain.lambda_continuity` | 0.15 | 交接连续性权重 |
| `chain.lambda_schedule` | 0.20 | 排期可行性权重 |
| `chain.lambda_chain_rep` | 0.15 | 链级信誉权重 |
| `chain.lambda_risk` | 0.20 | 违约传播风险权重 |
| `chain.beam_width` | 5 | Beam Search 宽度 |
| `chain.replan_threshold_days` | 1 | 触发重规划的延期阈值 |
| `chain.llm_mode_enabled` | false | 是否启用 LLM 拆解 |
| `decompose.top_k_templates` | 3 | 模板检索返回数 |
| `decompose.quality_threshold` | 0.75 | 质量分闸门 |
| `decompose.enable_composition` | true | 是否允许跨模板组合 |
| `decompose.max_variants` | 3 | 每模板变体数 |
| `decompose.max_rework_rounds` | 2 | review→rework 轮次上限 |
| `decompose.handoff_penalty` | 0.10 | 交接成本权重 |
| `decompose.llm_grounded` | true | LLM 必须输出模板节点映射 |
| `recommend.top_k_default` | 10 | 默认 Top-N |
| `recommend.candidate_limit` | 500 | 单次候选上限 |
| `data.seed` | 42 | 随机种子 |
| `data.n_workers` | 800 | 模拟人数 |
| `data.n_tasks` | 4000 | 模拟任务数 |
| `data.n_assignments` | 30000 | 模拟历史分配数 |
| `data.target_stats` | `data/target_stats.json` | 目标统计量配置 |
| `data.calibration_budget` | 200 | 校准迭代预算 |
| `data.n_seeds` | 5 | 多 seed 保真度验证 |
| `data.ground_truth_path` | `data/ground_truth.csv` | 仅评估可读的潜在结果 |

---

## 12. 测试计划

### 12.1 单元测试

- `test_synthetic.py`：固定 seed 可复现；规模、冷启动比例、评分范围符合设定。
- `test_data_calibration.py`：目标统计量在容差内；多 seed 方差可接受；`ground_truth.csv` 不被特征/训练代码读取。
- `test_features.py`：七维分数均在 `[0,1]`；技能/专长公式正确。
- `test_reputation.py`：贝叶斯平滑、按时率、返工、违约分档（1 次警告 / 2 次排除）。
- `test_preference.py`：偏好向量归一化；冷启动回退；接受概率在 `[0,1]`。
- `test_personalization.py`：画像→初始权重；分群/个人收缩；个人权重约束；学习曲线单调性；回滚到 `w_u(0)`。
- `test_chains.py`：模板实例化；DAG 无环/覆盖/截止校验；关键路径与 slack；链级分配硬约束；违约传播；重规划与回滚。
- `test_decomposition.py`：需求抽取与覆盖矩阵；变体选择；多模板组合去重；可选节点/并行组；review-rework 有界；质量分闸门；拆解 diff 与学习日志。
- `test_itemcf.py`：玩具矩阵上的相似度与打分正确；冷启动为 0。
- `test_weights.py`：AHP 先验和为 1；熵权计算；单纯形投影；权重上下限；收缩公式。
- `test_versioning.py`：版本创建/激活/回滚；权重 diff；回滚后 Top-N 与历史快照一致；审计日志完整。
- `test_hybrid.py`：融合分范围；排序稳定；解释字段完整。
- `test_api.py`：健康检查、两个推荐接口、分配、反馈、权重查询、错误码。

### 12.2 集成测试

```text
generate_data → 训练/加载 → 推荐 → 创建分配 → 提交评分 → 权重更新 → 再次推荐
```

- 验证权重版本递增、样本量增加、指标可查询。
- 验证模拟漂移后权重方向变化符合预期。
- 验证回滚到 `v0000` 后，同查询 Top-N 与基线快照一致；再切回学习版本可恢复。

### 12.3 属性测试

- 任意合法输入下，硬约束违规为 0。
- 任意反馈序列后，权重仍为合法单纯形且满足上下限。

---

## 13. 风险与假设

### 13.1 假设

1. 模拟数据用于验证机制；真实数据接入时替换 loader 与字段映射。
2. 暂无前端，客户评分通过 `/feedback` API 提交。
3. 数据放内存 + CSV，权重放 JSON；不引入数据库。
4. 代码标识符用英文，README 与接口说明用中文。
5. 当前目录不是 git 仓库，不产生 commit。
6. 任务链拆解暂不实现（见第 8 节）。

### 13.2 风险与缓解

| 风险 | 缓解 |
|---|---|
| 反馈回路导致强者恒强 | 10% 探索 + propensity 记录 + IPS 评估 |
| 客户评分偏差/宽松度不同 | 贝叶斯平滑 + 客户级校准 + 子维度评分 |
| 刷分/恶意评分 | 异常检测、评分一致性检查、审计日志（后续） |
| 偏好漂移 | 时间衰减 + 定期重拟合 + 漂移监控 |
| 冷启动效果差 | 声明偏好/画像先验 + 探索 + 内容兜底 |
| 权重被反馈学偏 | 权重上下限 + 向先验正则 + 版本回滚 |
| 模拟与真实分布差距 | 保留配置化数据生成，真实数据接入后重跑评估 |
| 公平性问题 | 曝光 Gini、覆盖率、负载约束；必要时 FairTop-k |

---

## 14. 论文参考

| 主题 | 文献 |
|---|---|
| 任务推荐多维度特征与特征重要性 | TasRec, ACM 2020 — [链接](https://dl.acm.org/doi/pdf/10.1145/3372787.3390435) |
| AHP 多准则众包任务匹配 | Improving Satisfaction in Crowdsourcing Platforms — [链接](https://userweb.cs.txstate.edu/~xc10/papers/crowdsourcing-AHP.pdf) |
| 多属性任务分配与稳定性 | Multi-Attribute Crowdsourcing Task Assignment — [链接](https://ieeexplore.ieee.org/document/8834775) |
| 技能负载与多目标推荐 | Crowdsourcing Multi-Objective Recommendation System — [链接](https://dlnext.acm.org/doi/fullHtml/10.1145/3184558.3191579) |
| 公平性与任务覆盖 | AdaTaskRec, ACM 2023 — [链接](https://dl.acm.org/doi/fullHtml/10.1145/3593582) |
| 自适应加权混合推荐 | SL-ARec, PeerJ CS 2025 — [链接](https://peerj.com/articles/cs-3856/) |
| 质量感知的任务/服务者推荐 | QADM, Journal of Information Science — [链接](https://journals.sagepub.com/doi/full/10.1177/01655515221136232) |
| AHP + 熵权组合赋权 | AHP-Entropy 组合赋权方法 — [链接](https://assets-eu.researchsquare.com/files/rs-7404325/v1_covered_cef2f79c-b984-4756-b6c6-4de2424989b4.pdf) |
| 信任/信誉驱动任务分配 | Trust-Based Task Allocation Framework — [链接](https://ieeexplore.ieee.org/abstract/document/11519622/references) |
| 能力匹配 + 负载 + 信誉 | Multi-agent Task Allocation — [链接](https://browse-export.arxiv.org/pdf/2509.16736) |
| 复杂任务拆解与众包工作流 | CrowdForge (Kittur et al., UIST 2011)；Turkomatic (Kulkarni et al., CSCW 2012) |
| 数据驱动的众包工作流 | Data Centric Workflows for Crowdsourcing (Hélouët et al., 2020) — [链接](https://people.rennes.inria.fr/Loic.Helouet/Papers/compwork2020.pdf) |
| 众包工作流综述 | Dretelny PhD dissertation (Stanford, 2017) — [链接](https://hci.stanford.edu/publications/2017/dissertations/dretelny-dissertation-final-double-sided-submitted-augmented.pdf) |
| DAG 调度的关键路径方法 | HEFT/CPOP；关键路径任务调度 — [链接](https://ir.nwpu.edu.cn/bitstream/39AN3IGR/381118/1/Zhu-2024-A%20critical%20path%20task%20scheduling%20algor.pdf) |
| 动态任务图多智能体 | DynTaskMAS (ICAPS/AAAI) — [链接](https://ojs.aaai.org/index.php/ICAPS/article/download/36130/38284/40203) |
| DAG 结构驱动的编排 | AdaptOrch — [链接](https://arxiv.org/html/2602.16873v1) |

---

## 15. 后续迭代（非本轮范围）

1. 任务链 Phase 2/3：历史链学习模板、Beam Search/MILP、LLM 自动拆解、多链全局调度。
2. 自动分配与公平性优化（FairTop-k、稳定匹配）。
3. 违约风险预测模型。
4. 更细粒度的个人权重（按任务类别/时段分别个性化）与 meta-learning。
5. 在线 A/B 实验与真实流量验证。
6. 数据库与特征存储、实时特征更新。
