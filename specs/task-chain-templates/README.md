# 常见任务链模板库

本目录存放「客户发布一个任务 → 拆解为子任务 DAG → 分配给不同 worker」的模板文件。

## 文件

| 文件 | 用途 |
|---|---|
| `common_task_chains.json` | 机器可读模板库，覆盖 12 类常见任务 |
| `README.md` | 字段规范、接入方式、维护规则 |

## 覆盖的任务类别

| category | 名称 | 典型节点数 |
|---|---|---|
| `software_dev` | 软件开发/网站 | 7 |
| `ui_ux_design` | UI/UX 设计 | 6 |
| `brand_design` | 品牌/平面设计 | 6 |
| `content_writing` | 内容写作 | 6 |
| `video_production` | 短视频/视频制作 | 7 |
| `marketing_campaign` | 市场活动 | 7 |
| `data_annotation` | 数据标注 | 6 |
| `translation_localization` | 翻译/本地化 | 6 |
| `ecommerce_ops` | 电商运营 | 6 |
| `recruitment` | 招聘 | 6 |
| `consulting_research` | 咨询/调研 | 7 |
| `training_course` | 培训课程开发 | 6 |

## 数据结构

```json
{
  "schema_version": "1.0.0",
  "templates": [
    {
      "template_id": "software_dev_v1",
      "category": "software_dev",
      "name": "软件开发/网站",
      "version": "1.0.0",
      "target_hours": [3, 16],
      "max_nodes": 10,
      "nodes": [
        {
          "key": "requirements",
          "title": "需求澄清",
          "type": "task",
          "hours": 4,
          "skills": {"requirements": 3},
          "depends_on": [],
          "acceptance": ["需求文档经客户确认"]
        }
      ]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `template_id` | str | 是 | 全局唯一，建议 `{category}_v{major}` |
| `category` | str | 是 | 任务领域，需与系统 12 类映射一致 |
| `name` | str | 是 | 可读名称 |
| `version` | str | 是 | 语义版本；模板变更必须升版本 |
| `target_hours` | [float, float] | 是 | 节点工时目标区间 |
| `max_nodes` | int | 是 | 单链节点上限 |
| `nodes[].key` | str | 是 | 模板内唯一；依赖用 key 引用 |
| `nodes[].title` | str | 是 | 节点名称 |
| `nodes[].type` | enum | 是 | `task` / `review` / `milestone` / `delivery` |
| `nodes[].hours` | float | 是 | 预计工时，可被实例化规则调整 |
| `nodes[].skills` | dict[str,int] | 是 | 技能 → 最低熟练度（1–5） |
| `nodes[].depends_on` | list[str] | 是 | 前置节点 key；根节点为空 |
| `nodes[].acceptance` | list[str] | 是 | 验收标准，至少 1 条 |

## 接入方式

### 1. 加载

实现时把本文件复制到：

```text
task-recommender/data/chain_templates/common_task_chains.json
```

由 `app/chains/templates.py` 加载为 `DecompositionTemplate` 记录。

### 2. 实例化

```text
template + task.description + task.difficulty + task.deadline + task.budget
  → 节点工时缩放
  → 按 target_hours 合并/拆分
  → 按 max_nodes 截断/合并
  → 生成 SubTask + ChainEdge
```

### 3. 校验（必须全过）

- DAG 无环（拓扑排序成功）
- 每个 `depends_on` 的 key 存在
- 每个需求条目至少映射到一个节点
- 每个节点的必需技能在 worker 池中存在
- 关键路径工时 ≤ 可用时间
- 节点工时在 `target_hours` 内（或记录偏离原因）

### 4. 人工审核

草稿状态必须经客户/管理员批准后才激活；LLM 拆解同样必须过审。

### 5. 版本与回滚

- 模板变更必须升 `version`。
- 已激活的链锁定其模板版本，不随模板更新自动变化。
- 链计划版本化，可回滚到上一版。

## 改进后的拆解机制（v2）

不再「选一个模板 + 简单缩放」，而是走完整流水线：

```text
任务理解 → 模板检索(Top-K) → 变体选择 → 多模板组合 → 实例化
→ 覆盖/缺口 → 依赖/回路校验 → 粒度优化 → 可行性/成本
→ 质量分 → 人工审核/diff → 学习
```

| 步骤 | 做什么 | 输出 |
|---|---|---|
| 0 任务理解 | 抽取需求条目、交付物、约束、预算、截止 | `Requirement[]` |
| 1 模板检索 | 按类别/交付物/技能/历史成功率打分，取 Top-K（默认 3） | 候选模板 |
| 2 变体选择 | simple/standard/complex，按难度/预算/截止选择 | 变体 |
| 3 多模板组合 | 跨类别任务合并模板，去重共享节点 | 组合 DAG |
| 4 实例化 | 可选节点按 `include_if` 展开；并行组转边；工时缩放 | SubTask/Edge |
| 5 覆盖分析 | 需求→节点覆盖矩阵；缺口补齐或标记 | 覆盖率/缺口 |
| 6 依赖校验 | DAG 无环；review-rework 有界；交付节点可达 | 校验报告 |
| 7 粒度优化 | 小于下限合并，大于上限拆分，计入交接成本 | 优化后 DAG |
| 8 可行性/成本 | 技能/容量/截止/预算；不可行时给放宽建议 | feasible/建议 |
| 9 质量分 | 覆盖/粒度/依赖/可行/模板匹配/历史成功 | 0–1 分+问题 |
| 10 人工审核 | diff、增删改、批准/回退 | 激活版本 |
| 11 学习 | 记录人工修改与链结果，更新模板 | 新模板版本 |

### 拆解质量分

```text
Quality = 0.30·Coverage + 0.20·Granularity + 0.15·DependencyValidity
        + 0.15·Feasibility + 0.10·TemplateFit + 0.10·HistoricalSuccess
        - RiskPenalty
```

- `quality < 0.75` → 必须人工复核或 LLM 细化。
- 输出 `top_issues` 与 `suggestions`，例如“增加测试节点”“延长截止”“拆分前端节点”。

### 从人工修改中学习

- 记录 `add / remove / merge / split / edge_change` 及原因。
- 高频修改 → 更新模板变体、默认节点、工时范围。
- 链结果（延期/返工/违约）回写模板的历史成功率。
- 模板版本 A/B，只有显著更优才切换默认。

## 模板 schema v1.1 扩展字段

v1 模板保持向后兼容，新增字段均为可选：

| 字段 | 用途 |
|---|---|
| `variants` | simple / standard / complex 的节点与工时差异 |
| `nodes[].optional` | 是否可选节点 |
| `nodes[].include_if` | 条件表达式（需求/预算/质量档位） |
| `nodes[].parallel_group` | 并行组；实例化时转为无边依赖 |
| `nodes[].hours_range` | `[min, expected, max]` |
| `nodes[].review_of` | 该节点评审哪个节点 |
| `nodes[].rework_of` | 该节点返修哪个节点 |
| `nodes[].max_rework_rounds` | 返修轮次上限 |
| `nodes[].risk_flags` | 风险标记 |
| `handoffs` | 边上交接物：`from, to, artifact, format` |
| `requirements` | 模板覆盖的需求类型 |
| `quality_rules` | 覆盖/粒度/可行性阈值 |
| `changelog` | 模板版本历史 |

高级写法示例见 `examples/software_dev_v2.json`。

**可选节点与返修语义**：

- 可选节点被排除时，按 `optional_policy: bypass` 把前驱直接连到后继。
- `review` 节点通过 `review_of` 指定评审对象。
- `rework` 节点通过 `rework_of` 指定返修对象，并用 `max_rework_rounds` 限制轮次，不形成图环。

## 新增模板的步骤

1. 在 `common_task_chains.json` 的 `templates` 中新增一个对象。
2. `template_id` 唯一，`category` 使用已有类别或先扩展类别映射。
3. 节点 key 唯一，依赖只能引用本模板内的 key。
4. 至少包含一个 `delivery` 节点。
5. 运行校验脚本（实现后提供）：

```bash
python scripts/validate_templates.py --file data/chain_templates/common_task_chains.json
```

6. 补一条模板测试用例（节点数、无环、根节点、交付节点）。

## 设计约束

- 模板是**默认拆解**，不是唯一答案；客户可增删节点、调整依赖。
- 工时是初始估计，实例化时按任务难度/历史数据缩放。
- 技能键使用系统统一技能表；不要写自由文本。
- 复杂任务优先拆到 2–16 小时的节点；过细会增加协调成本。
- 交付前必须有 `review` 或 `delivery` 节点。

## 与主设计文档的关系

- 主设计：`../2026-11-13-task-assignment-recommender-design.md` 第 8 节
- 第 8.3.1 节定义模板库；本目录是其数据文件。
- 第 8.6 节的 `DecompositionTemplate` 对应本文件的模板对象。
