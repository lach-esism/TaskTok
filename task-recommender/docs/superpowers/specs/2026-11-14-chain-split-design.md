# 任务链动态拆分设计

> 日期：2026-11-14
> 状态：设计已确认，待实现计划
> 范围：`task-recommender/app/chains/`、`app/domain.py`、`app/schemas.py`、`app/main.py`

## 1. 背景与目标

当前任务链拆分是纯模板选择：12 个类目模板，每个固定 6–7 个节点，`variants` 为空，`decompose()` 只做节点包含/排除。任务描述中的模块、批次和章节不会被识别，模板节点也不能继续细分为可独立派单的小工作。

目标：

1. 把一个大工作按**需求/模块、工作量、模板节点**拆成若干可独立派单的小工作。
2. 每个小工作有独立工时、预算、截止、技能和验收标准。
3. 拆分结果先作为草稿，确认后物化为独立 `Task`，复用现有推荐、接单、验收链路。
4. 保持确定性、可解释、可回归；不引入 LLM。

非目标：

- 不做人工拖拽式编辑器。
- 不改变现有推荐算法和验收规则。
- 不做跨重启的任务持久化（与现有 assignments 的 audit-only 模式一致）。
- 不自动物化，必须显式确认。

## 2. 关键决策

| 决策 | 选择 |
|---|---|
| 拆分用途 | 独立派单与撮合 |
| 拆分依据 | 需求/模块 + 工作量/预算/工期 + 模板节点细分 |
| 派单集成 | 草稿确认后物化为独立 `Task` |
| 实现方式 | 纯规则 + 现有 NLP |
| 实现路线 | 模板骨架 + 需求驱动动态拆解（方案 B） |

## 3. 模块划分

```text
app/chains/
  split_rules.py   # 类目模块关键词、批次单位、可拆节点类型
  split.py         # 需求抽取、模块映射、节点拆分/合并、工时预算截止分配
  decompose.py     # 保留模板拆分；split=True 时调用 split.py
  materialize.py   # SubTask -> Task 构造、校验、撤回
```

职责边界：

- `decompose.py` 负责“选模板、实例化节点、算覆盖”。它不关心物化。
- `split.py` 只做“在已有 DAG 上拆分节点并分配资源”，不访问 HTTP 或 store 以外的业务状态。
- `materialize.py` 只做“草稿到 Task”的纯转换和校验，不写 HTTP 状态。

## 4. 拆分流水线

### 4.1 输入

`POST /chains/decompose` 新增字段：

```json
{
  "task_id": "t0158",
  "mode": "template",
  "variant": "standard",
  "split": true,
  "policy": {
    "target_hours": 8,
    "min_hours": 1,
    "max_hours": 16,
    "max_pieces": 12,
    "min_batch_size": 50,
    "default_batch_size": 500
  }
}
```

- `split` 默认 `false`；为 `false` 时行为与当前版本完全一致。
- `policy` 缺省使用上表默认值；所有值必须为正数，`min_hours <= target_hours <= max_hours`，否则 422。
- `default_batch_size` 可被类目配置覆盖：数据标注默认 500 条，翻译默认 2,000 字，其他类目默认 500。`min_batch_size` 用于判断描述中的数量是否足以触发批次拆分。

### 4.2 步骤

```text
1. 抽取需求/模块
2. 选模板并实例化节点（复用现有 decompose 逻辑）
3. 按任务总工时缩放节点工时
4. 拆分超大节点/批次节点
5. 合并过小串行节点
6. 收敛到 max_pieces
7. 校验 DAG
8. 分配预算与截止
9. 计算拆分质量
```

### 4.3 需求与模块抽取

- 复用 `extract_requirements`：按 `。；;\n` 切分，去空、去重。
- 识别编号/列表项：`^\s*(\d+[.、)]|[一二三四五六七八九十]+、|[-*•])\s*`，每个条目作为需求候选。
- 模块关键词表放在 `split_rules.py`，按类目配置。首版覆盖：

| 类目 | 模块信号示例 |
|---|---|
| software_dev | 后端、前端、小程序、App、接口、数据库、支付、会员、订单、数据看板 |
| ui_ux_design | 用户研究、信息架构、线框图、视觉稿、原型、设计规范、走查 |
| data_annotation | 批次、条数、类别、标注、质检、返工 |
| translation_localization | 语言对、章节、字数、术语表、校对 |
| content_writing | 章节、稿件、平台、字数 |
| video_production | 脚本、分镜、拍摄、剪辑、字幕、渠道 |
| 其他类目 | 仅使用模板节点 + 编号列表 |

- 一条需求只有在命中模块关键词或编号列表时才生成模块节点。
- 未命中任何节点的需求记为 `uncovered`，不再默认兜底到交付节点。
- 没有拆分证据时不臆造模块，回退模板节点，`confidence` 降低，`split_reason` 写明“无结构化需求，使用模板”。

### 4.4 工时缩放

- `H = task.estimated_hours`；若 `H <= 0`，使用模板节点工时之和。
- 若模板工时之和 `T > 0` 且 `H > 0`，先统一乘以 `H / T`，使节点工时之和等于 `H`。
- 每个节点工时保留 1 位小数，舍入误差加到最后一个非交付节点。

### 4.5 拆分规则

节点满足任一条件才拆：

- `estimated_hours > max_hours`，且节点类型不是 `review` 或 `delivery`；
- 节点是批次型，且描述中数量 ≥ `2 × min_batch_size`。

拆分份数：

```text
按数量：k = ceil(quantity / batch_size)，batch_size 默认 500（标注）、2000（翻译字数）等，按类目配置
按工时：k = ceil(node.estimated_hours / target_hours)
```

约束：

- `k` 至少为 2，且 `k <= max_pieces`。
- 子节点 key 为 `{原key}_{序号}`，序号从 1 开始，冲突时继续递增。
- 子节点继承原节点的 `depends_on`、`required_skills`、`node_type`，`acceptance` 追加“第 i/k 批”。
- 所有子节点进入同一 `parallel_group`；原节点的后继改为依赖全部子节点。
- 交付节点永不拆分。

### 4.6 合并规则

- `estimated_hours < min_hours` 的串行节点可与相邻同类型节点合并。
- 合并后工时不得超过 `max_hours`；不合并 `delivery`。
- 合并保留前一个节点的 key，验收标准合并去重。

### 4.7 收敛到 max_pieces

1. 若节点数 > `max_pieces`，`target_hours *= 1.25` 后重新拆分。
2. 最多重复 4 次。
3. 仍超限时，按 `confidence` 从低到高移除非模板必需的生成模块节点（`node_type == "task"` 且 `split_source` 为 `requirement` 或 `module`）。
4. 交付节点、review 节点和模板必需节点不删除。
5. 最终仍超限则返回 422，说明无法在约束内完成拆分。

### 4.8 预算与截止

- 子任务预算按工时比例分配：`budget_i = round(parent.budget * hours_i / H, 2)`，余数给最后一块。
- 父预算 ≤ 0 时全部子任务预算为 0，并在质量问题中提示。
- 截止时间按关键路径倒推：

```text
after_hours(node) = 从该节点结束到任一终止节点的最长工时和
deadline(node) = parent.deadline - after_hours(node)
```

- 并行节点共享同一截止；所有截止不得晚于父截止。
- 父截止已过时保留父截止，并标记 `deadline_passed` 风险。

## 5. 数据契约

### 5.1 SubTask 新增字段（均带默认值）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `budget` | float | 0 | 子任务预算 |
| `deadline` | datetime \| None | None | 关键路径倒推的截止 |
| `split_source` | str | `"template"` | `template / requirement / module / batch` |
| `split_reason` | str | `""` | 拆分依据，如“5000 条，每批 500” |
| `confidence` | float | 1.0 | 拆分依据可信度，0–1 |
| `parent_key` | str \| None | None | 被拆分的原节点 key |

### 5.2 Task 新增字段（均带默认值）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `parent_task_id` | str \| None | None | 父任务 |
| `chain_id` | str \| None | None | 所属任务链 |
| `subtask_key` | str \| None | None | 对应 SubTask key |
| `split_source` | str \| None | None | 来源标记 |

### 5.3 父任务状态

物化后父任务 `status` 置为 `"split"`。`is_eligible()` 已要求 `status == "open"`，因此父任务自动退出推荐和接单。

### 5.4 草稿

`DecompositionDraft` 增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `split_policy` | dict \| None | 实际生效的策略 |
| `split_count` | int | 子任务数 |
| `uncovered_requirements` | list[str] | 未覆盖需求 |

物化状态保存在 `app.state.materializations[draft_id]`，包含 `task_ids / chain_id / materialized_at`。

## 6. 物化

### 6.1 构造规则

```text
task_id         = "sub_" + uuid4().hex
title           = f"{父标题}｜{子任务标题}"
customer_id     = 父任务客户
category        = 父任务类目
required_skills = 子任务技能；为空则继承父任务
required_level  = 父任务等级
difficulty      = clamp(1 + 4 * 子任务工时 / H, 1, 5) 后取整
estimated_hours = 子任务工时
deadline        = 子任务截止（缺失则父截止）
region          = 父任务地区
remote_ok       = 父任务 remote_ok
budget          = 子任务预算
budget_min      = 子任务预算
budget_max      = 子任务预算
description     = 子任务标题 + 验收标准 + split_reason + chain_id
requirements    = 子任务 acceptance
status          = "open"
```

### 6.2 校验

物化前必须全部通过：

1. 草稿存在且未被物化。
2. 节点数 ≥ 1，DAG 合法。
3. 子任务工时之和 > 0；若父任务 `estimated_hours > 0`，与它偏差 ≤ 5%；若父工时为 0，则与模板缩放后的有效工时 H 比较。
4. 子任务预算之和 ≤ 父预算 + 0.01。
5. 所有截止不晚于父截止。
6. 每个子任务能构造出合法的 `Task`（技能、等级、工时、预算字段在范围内）。
7. 父任务存在、`status == "open"`，且没有任何 assignment 记录（已接单的任务不可再拆）。

失败返回 422 和错误列表；`draft_id` 重复物化返回 409；草稿或父任务不存在返回 404。

### 6.3 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/chains/drafts/{draft_id}` | 查看草稿：节点、拆分来源、质量、是否已物化 |
| POST | `/chains/drafts/{draft_id}/materialize` | 物化草稿 |
| POST | `/chains/drafts/{draft_id}/materialize/rollback` | 撤回物化 |

物化响应：

```json
{
  "draft_id": "...",
  "chain_id": "...",
  "parent_task_id": "t0158",
  "parent_status": "split",
  "task_ids": ["sub_...", "sub_..."],
  "materialized_at": "2026-11-14T10:00:00Z"
}
```

### 6.4 撤回物化

- 仅当本次创建的子任务都没有 assignment 时允许。
- 删除子任务，父任务恢复 `open`，删除 `app.state.materializations` 记录。
- 写一条 `undo` 审计事件。
- 清空推荐服务缓存。
- 有 assignment 时返回 409，列出占用的任务。

### 6.5 持久化

- 子任务写入内存 `store.tasks`。
- 追加审计记录到 `data/chains/materialized.jsonl`：

```json
{"event":"materialize","draft_id":"...","chain_id":"...","parent_task_id":"t0158","task_ids":["sub_..."],"created_at":"..."}
{"event":"undo","draft_id":"...","task_ids":["sub_..."],"created_at":"..."}
```

- 与现有 assignments 一致，启动时不自动恢复。

## 7. 质量评估

### 7.1 拆分模式质量（v2-split）

仅在 `split=true` 时使用，`split=false` 保持现有 `quality_score` 不变。

| 维度 | 权重 | 计算 |
|---|---|---|
| 需求覆盖 | 0.28 | 映射到真实子任务的需求比例；兜底不算覆盖 |
| 粒度合理性 | 0.18 | 工时落在 `[min_hours, max_hours]` 的节点比例 |
| 拆分保真 | 0.12 | 工时和、预算和、截止三项偏差的 1 − 归一化误差 |
| 依赖合法 | 0.12 | `validate_dag` 通过为 1 |
| 可派单性 | 0.14 | 每个子任务至少有一个满足技能/等级/容量的 worker |
| 可物化性 | 0.08 | 通过 6.2 校验的节点比例 |
| 模板契合 | 0.05 | 类目与模板一致 |
| 历史成功率 | 0.03 | 暂用 0.5 |
| 风险扣分 | ≤ 0.20 | `0.05 × 风险标记数`，封顶 0.20 |

报告字段：`quality_version="v2-split"`、`split_count`、`total_hours`、`total_budget`、`uncovered_requirements`、`issues`。

### 7.2 离线效果报告

脚本：`scripts/evaluate_chain_split.py`
输出：`reports/chain_split_eval.md` / `.json`

| 指标 | 定义 |
|---|---|
| 覆盖率增益 | 同一批任务，动态拆分 vs 纯模板的需求覆盖率差值 |
| 可派单率 | 子任务中 Top-10 推荐非空且有 eligible worker 的比例 |
| 粒度分布 | 子任务工时 p50/p95，落在 2–16 小时的比例 |
| 重复派单数 | 父任务与子任务同时出现在推荐中的次数，必须为 0 |
| 稳定性 | 同输入重复拆分，节点集合/工时/预算一致 |

golden set：`dev_data/chains/split_cases.jsonl`，12–15 个跨类目任务，记录期望块数范围、模块关键词和资源不变量。它是回归基准，不是业务标签。

## 8. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_chain_split.py` | 模块/批次抽取、编号列表、条数解析、超大节点拆分、小节点合并、`max_pieces` 收敛、无证据回退、策略参数校验 |
| `tests/test_chain_split_invariants.py` | 1–12 块、工时和 ±5%、预算和精确、截止不超父截止、DAG 合法、同输入确定性 |
| `tests/test_chain_materialize.py` | 草稿查询、物化、父任务退出推荐、子任务可推荐、重复物化 409、撤回、有接单拒绝撤回、422 校验 |
| `tests/test_chain_split_quality.py` | v2 指标、兜底不算覆盖、可派单/可物化统计 |

边界用例：

- `estimated_hours=0`、`budget=0`、父截止已过
- 无结构化需求、未知类目、类目模板缺失
- 拆分 key 冲突
- 重复物化、并发物化
- 父任务已有 assignment

回归标准：

- `split=false` 时现有 423 个测试零回归。
- 新增测试 30–40 个全部通过。
- golden set 上块数、模块、工时预算不变量稳定。

## 9. 兼容性与风险

- `split` 默认关闭，旧请求的字段含义和行为不变；新增字段以默认值出现在响应中，属于向后兼容的附加字段，现有精确匹配响应的测试可能需要补字段。
- 物化任务只在内存，重启丢失；审计日志保留。
- 父任务状态 `split` 会影响统计任务数的代码；分析时必须排除该状态，避免父子重复计数。
- 拆分质量受关键词表限制；没有证据时回退模板，不臆造模块。
- 任务链和物化状态都在进程内，多 worker 部署不共享。

## 10. 验收标准

1. `split=false` 与现状完全一致。
2. `split=true` 能把跨类目任务拆成 1–12 个带预算/截止/技能的子任务。
3. 工时、预算、截止三项不变量全部成立。
4. 物化后父任务不再被推荐，子任务能进入 `/recommend/tasks` 并接单。
5. 撤回物化可恢复父任务，有接单时拒绝撤回。
6. 同一输入重复拆分结果确定。
7. 新增测试全部通过，现有测试零回归。
