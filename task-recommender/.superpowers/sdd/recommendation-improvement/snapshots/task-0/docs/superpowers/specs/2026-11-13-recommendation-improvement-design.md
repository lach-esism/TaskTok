# 推荐机制改进设计

- 日期：2026-11-13
- 状态：设计定稿，待评审
- 项目位置：`generated/task-recommender/`
- 范围：主推荐链路（任务→人、人→任务）、反馈学习、离线评估、任务链节点推荐复用
- 原则：**保留七维线性排序器**，不新增第八维，不换 GBDT/神经排序器，不引入生成式 LLM，不破坏现有 API

---

## 1. 背景与问题

当前主链路：

```text
硬约束过滤
  → ItemCF 协同分
  → 七维特征
  → 全局/个人权重线性融合
  → Top-N
  → ε-greedy
  → 采纳 / 客户评分
  → 在线权重与画像更新
```

现有实现与报告暴露的主要问题：

1. **排序表达力不足，学习收益接近停滞。** Phase 2 学习前后 NDCG 0.1345→0.1437、HR 0.282→0.302；新用户学习曲线 NDCG 0.9536→0.9535。七维权重的强约束（`reputation` 必须在 0.25–0.40 且最大）进一步限制了可学习空间。
2. **人→任务方向很弱。** `HR@10=0.080`、`NDCG@10=0.027`；worker 偏好只有类别与难度，没有报酬、截止、接受概率，也没有拒绝/放弃信号。
3. **反馈信号单一。** 只有完成后的客户评分；缺少曝光→点击→申请→接受/拒绝漏斗。ItemCF 只使用 `completed` 分配，冷启动与选择偏差无法纠正。
4. **特征覆盖不足。** `skill` 只看达标比例；`expertise` 只有专长/5；`customer_preference` 的 `communication`/`price` 是常量；`load` 没有截止时间与曝光公平；`required_specialty` 未校验；基准链路的 `collaborative` 实际是地域/远程匹配，不是协同过滤。
5. **探索机制实际失效。** 路由每次请求都 `ExplorationPolicy(seed=42)` 重建，`Random(42).random()` 首次为 0.639 > ε=0.10，因此永远不会探索；propensity 只是粗略近似，IPS/SNIPS 不可信。
6. **自然语言任务没有进入主推荐。** `/classify` 只返回类别与字段，仍需显式创建 `Task`；主推荐不使用任务文本。
7. **工程上每次请求重建 `RecommendationService` 与 ItemCF**，候选全量扫描；规模上去会先撞性能墙。

---

## 2. 目标与非目标

### 2.1 目标

1. 在**严格评估协议**下，提升任务→人与**人→任务**两个方向的排序准确率。
2. 建立可学习、可审计的反馈闭环：曝光、点击、申请、接受、拒绝、忽略、评分。
3. 在不更换排序器的前提下，提升七维特征的区分度与覆盖面。
4. 用语义相似度补足规则技能匹配的不足，同时保留无新增依赖的离线兜底。
5. 让“学习后变准”有统计证据：多 seed、置信区间、显著性检验、校准报告。

### 2.2 非目标

- 不实现 GBDT、LambdaMART、神经排序器或生成式 LLM 解释层；可选语义 embedding provider 只提供相似度特征，不参与排序器结构。
- 不新增第八个打分维度；新信号折叠进现有七维。
- 不做自动最终分配；仍由人确认 Top-N。
- 不做真实数据库、鉴权、多租户。
- 不保证真实业务分布；当前仍以合成数据与可复现模拟为主。

---

## 3. 成功标准与评估协议

### 3.1 主指标

- **任务→人**：`HR@5/10/20`、`NDCG@10`、`MRR`、`MAP@10`
- **人→任务**：同上，分开报告
- **冷启动子集**：无历史 worker 的 `HR@10`、无历史客户的 `HR@10`
- 不再像 `evaluate_two_runs` 那样把两个方向平均成一个数。

### 3.2 目标

- 相对严格基线，`NDCG@10` 提升 ≥10%（相对值），`HR@10` 提升 ≥5pp。
- 5 个数据 seed（42–46）的均值 ± 95% 置信区间不跨 0。
- 任务→人与人→任务至少一个方向达标，另一个方向不劣化。

### 3.3 护栏

- 硬约束违规数 = 0。
- 冷启动子集 `HR@10` 不劣于基线。
- 1000 任务对答案基准 Top-1 不下降（同一轮次、同一协议比较）。
- 推荐接口 p95 延迟不超过基线 2 倍。
- 训练/特征代码不得读取 `ground_truth.csv` 或 benchmark `labels`。

### 3.4 严格评估协议

新增 `app/evaluation_strict.py` 与 `scripts/evaluate_strict.py`。

- **时间切分**：按 `Assignment.created_at` 排序，70% 训练、15% 验证、15% 测试；不打乱。
- **候选集**：
  - 正样本 = 测试分配中的实际 worker / task。
  - 负样本 = 同一次曝光中未被选中的候选（真实曝光负样本）+ 100 个随机合法候选（随机负样本）。
  - 两种候选集分别报告，避免只评估“容易的负样本”。
- **多 seed**：数据生成 seed 42–46；每个 seed 内对测试查询做 bootstrap 重采样，报告差异的 95% CI 与 paired bootstrap p 值。
- **基线**：random、content-only（skill+expertise+reputation）、CF-only、固定 AHP 先验、当前学习版本。
- **校准**：对 `P(rating≥4)` 报告 Brier score 与 reliability bins；校准不参与排序。
- **泄漏检查**：`evaluation_strict.py` 是唯一读取 `ground_truth.csv` / `labels` 的模块；新增测试断言特征与训练模块不导入/不读取这些文件。
- **报告**：`reports/strict_eval.json`、`reports/strict_eval.md`、`reports/strict_eval_queries.csv`。

运行方式：

```bash
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10
```

### 3.5 评估数据装配与泄漏边界

- 训练与特征只使用 `Dataset.train` 及其对应的 `train_feedback`；`test` 与 `test_feedback` 只用于评估。
- 当前 `create_app` 把 `dataset.feedback` 全量传入 `Store`，存在测试期反馈进入 ItemCF 与画像的风险。改为按 `train_assignment_ids` 过滤；新增 `Dataset.train_feedback` / `test_feedback`（或等价的过滤辅助）。
- `ground_truth.csv`、benchmark `labels` 只允许严格评估脚本与 benchmark evaluator 读取；特征、训练、推荐服务不得读取。
- 现有 `learning_curve` 使用 oracle `_true_match` 生成训练信号，只作为旧诊断保留，不得作为新严格评估的学习证据；新学习证据必须来自事件日志。
- benchmark 的 `labels` 只用于 benchmark 的训练/评估，不得迁移到主服务。
- 修改 `benchmark/features.py` 后必须重新跑 10 轮基线，不能直接与历史 0.731 比较。

---

## 4. 总体架构

保留 `RecommendationService` 作为唯一排序入口，新增四个可替换组件：

```text
请求
  → 硬约束过滤
  → 候选池 + ItemCF
  → 语义匹配器（缓存 embedding / TF-IDF-SVD）
  → 七维特征（语义、截止、报价、接受概率、合作历史）
  → 全局/分群/个人权重
  → 线性融合
  → 精确 ε-greedy + propensity
  → Top-N + request_id
  → 曝光事件
  → 点击/申请/接受/拒绝事件
  → 选择学习（pairwise/listwise）+ 评分学习
  → 权重版本 / 校准 / 回滚
```

新增组件：

| 组件 | 文件 | 职责 |
|---|---|---|
| 事件日志 | `app/events.py` | `Impression` / `RecommendationEvent` 的写入、查询、漏斗指标 |
| 语义匹配 | `app/semantic.py` | 统一 `similarity(task_text, worker_text)`，缓存，兜底 |
| 选择学习 | `app/learning/choice.py` | pairwise / listwise 学习七维权重 |
| 严格评估 | `app/evaluation_strict.py` | 时间切分、负样本、多 seed、CI、泄漏检查 |
| 校准 | `app/learning/calibration.py` | Platt 校准、Brier/reliability |

---

## 5. 数据模型

所有新增字段必须有默认值，保证现有构造与测试不破坏。

### 5.1 新增 `Impression`

```python
@dataclass
class Impression:
    request_id: str
    query_id: str
    candidate_ids: list[str]
    propensities: dict[str, float]
    policy: str                  # "epsilon_greedy_topk" | "synthetic_weighted"
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)  # e.g. assignment_id for synthetic correlation
```

### 5.2 新增 `RecommendationEvent`

```python
@dataclass
class RecommendationEvent:
    event_id: str
    request_id: str
    user_id: str | None          # 请求方：客户或 worker
    role: str                    # "customer" | "worker"
    task_id: str
    candidate_id: str
    candidate_type: str          # "worker" | "task"
    rank: int
    score: float
    propensity: float
    weights_version: str
    action: str                  # impression/click/apply/accept/reject/ignore
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)
```

### 5.3 扩展 `Worker`

```python
expected_pay: float = 0.0
certifications: dict[str, float] = field(default_factory=dict)   # category -> 0..1
communication_ratings: list[float] = field(default_factory=list) # 1..5
```

### 5.4 扩展 `Task`

```python
required_skill_weights: dict[str, float] = field(default_factory=dict)
```

### 5.5 扩展 `Store` 与 `Dataset`

- `Store.__init__` 新增可选参数 `events: list[RecommendationEvent] | None = None`、`impressions: list[Impression] | None = None`。
- `Dataset` 新增 `events: list[RecommendationEvent] = field(default_factory=list)`、`impressions: list[Impression] = field(default_factory=list)`。
- `Store` 新增：
  - `events_for(request_id)`
  - `events_for_user(user_id)`
  - `recent_impression_counts(now, days=30)`
  - `prior_collaboration_count(customer_id, worker_id)`

### 5.6 持久化

- 事件写 JSONL：`data/events/events.jsonl`、`data/events/impressions.jsonl`。
- 复用 `FeedbackService._persist` 的追加写模式；达到 1,000,000 行时轮转。
- 语义缓存：`data/embeddings/<provider>/<model_hash>/`。
- 严格评估报告：`reports/strict_eval.*`。
- 权重约束 binding 报告：`reports/weight_binding.json`。

---

## 6. 事件与反馈闭环

### 6.1 推荐接口

- `/recommend/workers` 与 `/recommend/tasks` 响应新增 `request_id`。
- 返回的每个候选保留 `propensity`。
- 服务端写入 `Impression`，并写 `action="impression"` 事件（服务端内部事件；客户端 `POST /events` 不接受 `impression`，只接受 click/apply/accept/reject/ignore）。
- 本期不自动把 `/classify` 的结果落库为 `Task`；语义匹配只对已存在的 `Task` 生效。

### 6.2 新增接口

```http
POST /events
{
  "events": [
    {
      "request_id": "r_...",
      "task_id": "t0001",
      "candidate_id": "w0001",
      "candidate_type": "worker",
      "user_id": "c0001",
      "role": "customer",
      "action": "click"
    }
  ]
}
```

- 合法 `action`：`click`、`apply`、`accept`、`reject`、`ignore`。
- 重复 `(request_id, candidate_id, action)` 返回 409。
- 未知 `request_id` / `candidate_id` 返回 404。
- 非法 `action` 返回 422。

```http
GET /events/metrics
```

返回曝光、点击、申请、接受、拒绝、忽略的计数与转化率，按 rank 分桶、按类别分桶。

### 6.3 `POST /assignments` 联动

- 若请求带 `recommendation_context.request_id`，自动写一条 `accept` 事件。
- 现有 `POST /assignments` 与 `POST /feedback` 契约不变。

### 6.4 选择学习信号

- 正动作：`click`、`apply`、`accept`。
- 负动作：`reject`、`ignore`。
- 同一 `request_id` 内，正动作候选与负动作候选组成 pairwise 样本。
- 客户侧：任务→人，正样本为被采纳的 worker。
- Worker 侧：人→任务，正样本为被接受/申请的 task；负样本来自同一 worker 曝光过但未选择的 task。

### 6.5 模拟数据

在 `app/data/synthetic.py` 中：

1. 生成每条分配时，记录当时的合法候选集 `candidates`。
2. logging policy 使用现有 `weight(worker)`（技能、专长、负载、可靠性），归一化为 propensity。
3. 用 `rng.choices` 选中 worker；写 `Impression`。
4. 选中的 worker 写 `action="accept"`；未选中的候选按最多 20 条抽样写 `action="ignore"`，其中 10% 写 `action="reject"`。
5. Worker→任务的负样本从同一批 impression 反推：某 worker 在候选集中但未被选中，则对应 task 是该 worker 的负样本；被选中的 task 是正样本。
6. 不把 `reliability` 写入事件；训练只能看到选择行为与 propensity。
7. 新字段的合成方式：
   - `expected_pay`：取 worker 专长类别的预算中位数 × `uniform(0.7, 1.3)`。
   - `certifications`：每个专长类别以 0.3 概率取 0.8、0.4 概率取 0.5、其余 0。
   - `communication_ratings`：生成反馈时以 0.5 概率追加 `clip(quality*5 + noise, 1, 5)`。
   - `required_skill_weights`：默认等权；可选为一个技能生成 `[0.5, 2.0]` 的重要性权重。
8. `Store.reference_time` 改为 `max(assignments, events, impressions)` 的时间，保证曝光与反馈的时间语义一致。

### 6.6 基准链路

- 1000 任务对答案基准保持独立，仍用 `labels` 训练/评估。
- 将 `app/benchmark/features.py` 中的 `collaborative` 从地域/远程匹配改为真正的 ItemCF；冷启动为 0。
- 可选：用同一候选集生成 choice log，用于验证 pairwise 学习；不替代 `labels` 评估。

---

## 7. 探索与 propensity

### 7.1 修复

- 路由不再每次请求 `ExplorationPolicy(seed=42)`。
- 生产使用系统熵初始化 RNG；测试/演示通过显式 `--seed` 注入。
- 每个 app 持有一个 `ExplorationPolicy` 实例，或每次请求传入唯一 seed；不得在每次请求中重置为固定 seed。

### 7.2 精确 propensity

设合法候选数为 `N`，返回 `K = min(top_n, N)`，探索率 `ε`：

```text
N <= K:            p_i = 1
i ∈ top-(K-1):     p_i = 1
i = 第 K 名:       p_i = (1 - ε) + ε / (N - K + 1)
i ∉ top-K:         p_i = ε / (N - K + 1)
```

- 所有 `p_i` 截断到 `[1e-6, 1]`。
- 将 `p_i` 写入 `Impression.propensities` 与每条事件的 `propensity`。
- 新增测试：模拟 100,000 次曝光，经验频率与理论值误差 < 0.01。

### 7.3 IPS / SNIPS

- `app/learning/exploration.py` 保留 `ips_score` / `snips_score`，但输入必须使用上述精确 propensity。
- 训练样本权重使用 `min(1, 1/propensity)` 并截断到 `[0.1, 10]`，避免极端权重。

---

## 8. 七维特征升级

保持七个 key 不变：`reputation`、`skill`、`expertise`、`collaborative`、`preference`、`load`、`customer_preference`。所有值输出 `[0,1]`，禁止 NaN。

### 8.1 `reputation`

保持现有公式：

```text
bayesian_rating = (sum(ratings) + 10 * 4.2) / (len(ratings) + 10) / 5
reputation = 0.4*bayesian_rating + 0.2*completion + 0.2*on_time
           + 0.1*rework + 0.1*breach_penalty
```

- 分领域信誉继续向全局收缩。
- 沟通分不进入信誉，进入 `customer_preference`。

### 8.2 `skill`

```text
w_s = task.required_skill_weights.get(s, 1.0)
skill = Σ_s w_s * min(worker.skills.get(s, 0) / max(required_s, 1), 1) / Σ_s w_s
```

- 无 `required_skills` 时，不再返回 1.0；改为 `0.5 * expertise + 0.5 * category_history`。
- 新增可选硬约束 `required_specialty`（若 `Task` 有该字段）：worker 专长等级必须达标；当前 `Task` 没有该字段，本期只加 `Task.required_skill_weights`，`required_specialty` 放入后续。

### 8.3 `expertise`

```text
specialty        = worker.specialties.get(category, 0) / 5
certification    = clamp(worker.certifications.get(category, 0.0), 0, 1)
global_rating    = compute_reputation(worker).rating   # 0..5 的贝叶斯评分
category_history = (n * mean(category_ratings)/5 + m * global_rating/5) / (n + m)
                   m = 10；n = 0 时取 global_rating/5
semantic         = semantic_matcher.similarity(task, worker)  # 0..1；不可用时 0.5

expertise = 0.35*specialty + 0.15*certification
          + 0.25*category_history + 0.25*semantic
```

### 8.4 `collaborative`

- 主服务保留 ItemCF，`shrinkage=5.0`。
- `normalize` 从 query 内 min-max 改为除以 `max_score`：

```text
if max(raw.values()) <= 0: return 0 for all
normalized = max(0, raw) / max(raw)
```

- 基准链路用同一 ItemCF 逻辑替换地域/远程代理特征。

### 8.5 `preference`

```text
declared   = 0.6*category_preference + 0.4*difficulty_fit
pay_fit    = 1 - |task.budget - worker.expected_pay| / max(task.budget, worker.expected_pay, 1)
             expected_pay == 0 时取 0.5
time_fit   = clamp(1 - task.estimated_hours / max(available_hours, 1), 0, 1)
             available_hours = max(0, hours_until_deadline - worker.current_load_hours)
p_accept   = sigmoid(θ · φ)
             φ = [category_match, skill_match, pay_fit, load_ratio,
                  region_match, historical_accept_rate, 1]
             category_match = worker.preferred_categories.get(task.category, 0.0)
             skill_match    = skill
             load_ratio     = clamp((current_load + task_hours) / capacity, 0, 1)
             region_match   = 1.0 同区域；0.8 双方可远程；否则 0.3
             historical_accept_rate = (accepted + 1) / (accepted + rejected + 2)
preference = 0.4*p_accept + 0.3*declared + 0.15*pay_fit + 0.15*time_fit
```

- `p_accept` 模型：每个 worker 至少 20 条接受/拒绝事件时使用个人逻辑回归；不足时使用全局模型 + worker 声明偏好；仍不足时 `p_accept = declared`。
- 模型权重带 L2，向全局先验收缩；只读事件，不读 `ground_truth`。

### 8.6 `load`

```text
capacity_score       = (capacity - current_load - task_hours) / capacity
deadline_feasibility = time_fit
exposure_fairness    = exp(-recent_impressions / 20)   # 近 30 天；无事件时 1.0
load = 0.6*capacity_score + 0.25*deadline_feasibility + 0.15*exposure_fairness
```

- `recent_impressions` 来自 `Store.recent_impression_counts`。
- `capacity <= 0` 时 `capacity_score=0`。

### 8.7 `customer_preference`

属性值：

```text
reputation     = reputation
expertise      = expertise
speed          = on_time / completed（无数据 0.5）
communication  = mean(worker.communication_ratings) / 5（无数据 0.5）
price          = pay_fit
collaboration  = min(1, prior_completed_pairs(customer, worker) / 3)
                 prior_completed_pairs 只统计查询时间之前、status=completed 的分配
deadline_fit   = deadline_feasibility
```

默认属性权重：

```text
reputation 0.30, expertise 0.20, speed 0.15, communication 0.10,
price 0.10, collaboration 0.10, deadline_fit 0.05
```

- 客户画像 `confidence >= 0.2` 时，用画像的 `attribute_weights` 覆盖已有属性，并按总和归一化；缺失属性用默认权重补齐。
- 客户画像不足时，回退：

```text
0.4*reputation + 0.3*expertise + 0.15*load + 0.15*pay_fit
```

- 删除 `communication=0.7`、`price=0.5` 常量。

---

## 9. 语义匹配

### 9.1 接口

```python
class SemanticMatcher:
    def similarity(self, task_text: str, worker_text: str) -> float: ...
```

### 9.2 Provider

- **默认 `tfidf_svd`**：`TfidfVectorizer(analyzer="char", ngram_range=(2,4), min_df=2, sublinear_tf=True)` + `TruncatedSVD(n_components=128, random_state=42)`；余弦相似度直接作为 `[0,1]` 分数。
- **可选 `sentence_transformer`**：懒加载 `sentence-transformers`；默认模型 `BAAI/bge-small-zh-v1.5`；`normalize_embeddings=True`；余弦相似度映射到 `[0,1]`。
- **`disabled`**：返回 0.5。

配置：

```text
SEMANTIC_PROVIDER = tfidf_svd | sentence_transformer | disabled   # 默认 tfidf_svd
SEMANTIC_MODEL = BAAI/bge-small-zh-v1.5                          # 仅 sentence_transformer
SEMANTIC_WEIGHT = 0.25                                           # 进入 expertise
SEMANTIC_CACHE_DIR = data/embeddings
```

### 9.3 文本构造

- Task 文本：`title + description + requirements + category`。
- Worker 文本：复用 `app/resume.py` 的简历表面字段（职位、技能标签、项目、证书、城市），不暴露平台内部分数。
- 预计算所有 worker/task 向量并缓存；新增 worker/task 时增量计算。
- 缓存 key：`sha256(provider + model + text)`；缓存文件按 provider/model 分目录。

### 9.4 集成

- `candidate_features` 新增可选参数 `semantic_similarity: float = 0.5`。
- `RecommendationService` 可选注入 `SemanticMatcher`；未注入时语义分 0.5，行为与旧版一致。
- `BenchmarkFeatureBuilder` 可选注入 `SemanticMatcher`；未注入时保留原 char TF-IDF 相似度，保证基准可复现。

---

## 10. 学习与校准

### 10.1 保持线性排序

```text
score = Σ_i w_i * x_i
```

七维权重仍满足：

- 和为 1
- `reputation ∈ [0.25, 0.40]`
- `skill + expertise >= 0.25`
- 每维 `>= 0.02`
- `reputation` 为最大权重

不新增维度；新信号通过特征公式进入七维。

### 10.2 Pairwise 选择学习

新增 `app/learning/choice.py`：

```text
pair = (x_pos, x_neg, weight)
X = x_pos - x_neg
y = 1
weight = time_decay * clamp(1 / propensity, 0.1, 10)
LogisticRegression(fit_intercept=False, C=1/l2, solver="lbfgs", max_iter=1000)
w = coef_
w = project_weights(w)
```

- 时间衰减：`exp(-Δt/30 天)`。
- 正样本：`click`、`apply`、`accept`；负样本：`reject`、`ignore`。
- 同一 `request_id` 内配对；不同请求之间不配对，避免上下文混淆。
- 每个 worker / customer 的事件数足够时，个人模型优先；否则全局模型 + 收缩。

### 10.3 Listwise 选择学习

- 对每个 impression 的候选集做 softmax；chosen 为 one-hot。
- 梯度：`Σ_i (p_i - y_i) * x_i`，样本权重为 `1/propensity` 截断。
- 复用 `BenchmarkRecommender.learn` 的实现，泛化到主服务。

### 10.4 与评分学习融合

`POST /weights/recompute`：

```text
L = L_rating + λ * L_choice + μ * ||w - prior||²
λ = 1.0, μ = 0.1
```

- `L_rating`：现有 `OnlineWeightLearner.batch_fit`。
- `L_choice`：pairwise 或 listwise。
- 两者都只使用训练时间段的数据；测试时间段的事件/反馈不得参与拟合。
- 两者都经过 `project_weights`。
- `update_pair` 接入 `/events` 的 accept/reject；保留 `n/(n+n0)` 收缩。

### 10.5 校准

新增 `app/learning/calibration.py`：

```text
P(rating >= 4) = sigmoid(a * score + b)
```

- 在训练集反馈上拟合 `a, b`；输出 Brier score、reliability bins。
- 校准概率不参与排序；用于置信度展示、IPS 报告、阈值决策。

### 10.6 约束 binding 报告

- 新增 `project_weights_with_report`，返回 `(weights, binding_info)`。
- 记录每次更新中触达上下限的维度与次数，写入 `reports/weight_binding.json`。
- 若某维度 binding 率 > 20%，在 Phase 3 结束后单独评估是否放宽上下限；本期不自动放宽。

---

## 11. API 变更

### 11.1 新增

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/events` | 批量写入点击/申请/接受/拒绝/忽略事件 |
| GET | `/events/metrics` | 漏斗计数与转化率 |
| GET | `/evaluation/strict` | 最近一次严格评估报告 |
| GET | `/config/semantic` | 语义 provider/model/状态 |

### 11.2 修改

- `/recommend/workers`、`/recommend/tasks` 响应新增 `request_id`；候选仍返回 `propensity`。
- `/weights/recompute` 支持 `include_events=true`（默认 true）。
- `/assignments` 若带 `recommendation_context.request_id`，自动写 `accept` 事件。
- 现有 `/recommend/*`、`/assignments`、`/feedback`、`/weights/*` 契约保持兼容。

### 11.3 错误码

| 状态码 | 场景 |
|---|---|
| 404 | request_id / candidate_id / task_id 不存在 |
| 409 | 重复事件 |
| 422 | 非法 action、字段缺失、评分越界 |
| 400 | 无合法候选（返回排除原因汇总） |

---

## 12. 工程结构与文件变更

### 12.1 新增

```text
app/events.py                    # Impression / RecommendationEvent / EventService
app/semantic.py                  # SemanticMatcher + TF-IDF-SVD / sentence-transformers
app/learning/choice.py           # PairwiseChoiceLearner / ListwiseChoiceLearner
app/learning/calibration.py      # PlattCalibrator
app/evaluation_strict.py         # 严格评估协议
scripts/evaluate_strict.py       # CLI
scripts/simulate_events.py       # 从合成数据生成曝光/选择日志
tests/test_events.py
tests/test_propensity.py
tests/test_semantic.py
tests/test_features_v2.py
tests/test_pairwise_learning.py
tests/test_strict_eval.py
tests/test_api_events.py
tests/test_weight_binding.py
```

### 12.2 修改

```text
app/domain.py                    # 新 dataclass + Worker/Task 字段
app/data/store.py                # events/impressions + 查询辅助
app/data/synthetic.py            # 生成 impression/event；新 Worker 字段
app/features.py                  # 七维公式升级；semantic_similarity 入参
app/service.py                   # 注入 SemanticMatcher；缓存友好的构造
app/main.py                      # /events、request_id、严格评估路由；单例 service
app/schemas.py                   # 事件请求/响应
app/config.py                    # 语义、探索、评估配置
app/learning/exploration.py      # 精确 propensity；可注入 RNG
app/learning/weights.py          # project_weights_with_report
app/preference/customer.py       # 默认属性权重扩展
app/benchmark/features.py        # 真 ItemCF；语义可选
app/benchmark/recommender.py     # listwise 选择学习泛化
app/evaluation_phase2.py         # 分开报告两个方向；保留旧接口
README.md                        # 新接口与运行方式
docs/recommendation-flow.md      # 新链路图与边界
```

### 12.3 性能

- `RecommendationService` 与 `ItemCF` 在 `app.state` 中缓存；在新增 assignment/event/权重重算后失效重建。
- 语义向量启动时预计算；100 workers × 1000 tasks 规模下内存 < 100MB。
- 事件写入使用追加 JSONL；查询漏斗使用内存聚合与按需重算。
- 候选仍全量扫描（当前 100 workers）；未来候选池超过 10,000 时再引入 ANN/倒排，不在本期范围。

---

## 13. 测试计划

### 13.1 现有测试

- 现有 150 个测试必须全部通过。
- 仅允许因新增默认字段或特征公式变化而更新少量断言；不得删除测试。

### 13.2 新增测试

| 文件 | 覆盖 |
|---|---|
| `test_events.py` | 事件写入、重复 409、未知 404、漏斗指标、JSONL 持久化 |
| `test_propensity.py` | 精确 ε-greedy propensity；经验频率误差 < 0.01；`N<=K` 全 1 |
| `test_semantic.py` | TF-IDF-SVD 兜底、余弦范围、缓存确定性、无 NaN、sentence-transformers 未安装时的回退 |
| `test_features_v2.py` | 七维均在 `[0,1]`；无技能要求回退；报价/截止/沟通/合作/曝光公平；缺失数据回退 |
| `test_pairwise_learning.py` | 玩具偏好可恢复；chosen 排在 rejected 前；权重仍满足单纯形与上下限 |
| `test_strict_eval.py` | 时间切分；候选采样；多 seed；CI；泄漏检查 |
| `test_api_events.py` | `/events`、`/events/metrics`、`/recommend/*` 的 `request_id` |
| `test_weight_binding.py` | binding 报告结构；约束仍满足 |

### 13.3 属性测试

- 任意合法输入下，硬约束违规 = 0。
- 任意事件序列后，七维权重仍合法。
- 任意特征输入下，输出无 NaN、无越界。

### 13.4 泄漏测试

- 静态断言：`app/features.py`、`app/semantic.py`、`app/learning/choice.py` 不导入 `app.data.ground_truth`，不读取 `ground_truth.csv` / `labels`。
- 运行时：在特征构建期间 monkeypatch `ground_truth` loader，若被调用则测试失败。
- 训练隔离：构造一个测试，向 `test_feedback` 注入极端评分，确认训练期 ItemCF、画像与权重不受影响；推荐结果只应随 `train_feedback` 变化。
- 事件隔离：断言 `Dataset.test` 对应的 impression/event 不进入训练；训练只使用 `train` 时间段的事件。

---

## 14. 实施阶段

| 阶段 | 内容 | 交付物 | 验收 |
|---|---|---|---|
| Phase 1 | 严格评估 + 事件日志 + impression 生成 + propensity 修复 + service 缓存 | `reports/strict_eval.*` 基线；`/events` API；现有测试全过 | 基线可复现；无泄漏；探索经验频率匹配理论值 |
| Phase 2 | 七维特征升级 + 语义匹配 + 新字段 + 合成数据更新 | 严格评估对比报告；语义 provider 可切换 | 任务→人 NDCG/HR 提升；冷启动不劣化；无 NaN |
| Phase 3 | pairwise/listwise 选择学习 + 校准 + 个人权重接入 + binding 报告 | 学习曲线（多 seed + CI）；benchmark 回归 | NDCG@10 +10%、HR@10 +5pp 至少一个方向达标；CI 不跨 0 |
| Phase 4 | API 文档、README、`docs/recommendation-flow.md`、演示脚本、性能检查 | 更新文档与演示 | p95 延迟 ≤ 2× 基线；演示可一键跑通 |

每个阶段结束都运行：

```bash
python -m pytest tests/ -q
python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10
```

---

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 语义模型依赖/离线安装失败 | 默认 TF-IDF+SVD；sentence-transformers 懒加载、可选；缓存 |
| 合成事件泄漏潜在可靠性 | 事件只记录候选、propensity、动作；不写 `reliability` / `ground_truth`；泄漏测试 |
| 事件量膨胀 | 每条 impression 最多 20 条负样本；JSONL 轮转；可按需降采样 |
| 线性模型到顶 | 本期不换模型；Phase 3 后若仍不达标，另立 GBDT/神经排序器设计 |
| 权重上下限 binding | 记录 binding 率；>20% 时单独评估；本期不自动放宽 |
| IPS 权重爆炸 | `min(1, 1/propensity)` 截断到 `[0.1, 10]`；报告有效样本量 |
| 评估过拟合 | 时间切分；5 seeds；测试集不调参；paired bootstrap |
| 语义相似度不可解释 | 语义只占 `expertise` 的 0.25；保留专长/认证/历史质量；解释中可拆分 |
| 新增字段破坏旧测试 | 所有新字段带默认值；仅更新必要的断言 |
| 基准与主服务口径不一致 | 严格评估分开报告；benchmark 保持独立；文档写清边界 |

---

## 16. 明确不做

- 不实现 GBDT、LambdaMART、神经排序器。
- 不新增第八个打分维度。
- 不引入生成式 LLM 或提示词层。
- 不做自动最终分配、实时点击流、真实数据库、鉴权、多租户。
- 不在本期放宽 `reputation` 权重上下限。
- 不删除或重写现有 150 个测试；只增量扩展。

---

## 17. 默认决策（已确定）

| 问题 | 本期默认 |
|---|---|
| 语义 provider | `tfidf_svd`；`sentence_transformer` 可选 |
| 负样本数量 | 每条 impression 最多 20 条；严格评估额外 100 条随机负样本 |
| Worker→任务负样本 | 从同一批 impression 反推 |
| 事件保留 | JSONL 追加；1,000,000 行轮转 |
| 权重上下限 | 保持不变；只记录 binding |
| 严格评估 seed | 42–46，共 5 个 |
| 主指标 | 任务→人与人→任务分别报告；NDCG@10 与 HR@10 |
| 候选池 | 保持全量合法候选；>10,000 时再引入 ANN |
| 演示 RNG | 显式 seed；生产系统熵 |
