# Task Chain Dynamic Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把一个大工作按需求/模块、工作量、模板节点拆成若干可独立派单的小工作，确认后物化为独立 `Task`。

**Architecture:** 保留 12 个类目模板作为骨架；新增 `split_rules.py` 提供模块/批次规则，`split.py` 负责需求抽取、节点拆分合并、工时预算截止分配和质量评分；`decompose()` 在 `split=True` 时调用；`materialize.py` 把 SubTask 转成 Task；HTTP 层新增草稿查询、物化和撤回接口。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、pytest；无 LLM、无新依赖。

**Spec:** `docs/superpowers/specs/2026-11-14-chain-split-design.md`

## Global Constraints

- `split` 默认 `false`；为 `false` 时现有字段含义和行为不变，新增字段以默认值出现。
- 默认策略：`target_hours=8.0`、`min_hours=1.0`、`max_hours=16.0`、`max_pieces=12`、`min_batch_size=50`、`default_batch_size=500`。
- 无 LLM、无网络、无新依赖；所有结果确定可复现。
- 子任务数 1–12；工时和与父任务偏差 ≤5%；预算和等于父预算；所有截止不晚于父截止。
- 物化后父任务 `status="split"`，退出推荐；子任务 `status="open"` 进入现有链路。
- 物化任务只在内存，另写 `data/chains/materialized.jsonl` 审计，不跨重启恢复。
- 所有新增 dataclass 字段必须带默认值，避免破坏现有构造调用。

## Review Focus

1. **无结构描述**：没有标点、编号或模块关键词时，不得臆造模块；回退模板并降低 `confidence`，`split_reason` 说明原因。
2. **数量写法**：`1,200 条` 应解析为 1200；`一千字` 等中文数字应返回 `None`，不触发批次拆分。
3. **零值输入**：`estimated_hours=0` 或 `budget=0` 时不得除零，工时/预算不变量仍成立。
4. **截止时间异常**：父截止已过或为 naive datetime 时不得崩溃；物化必须返回 422。
5. **节点数收敛**：模块/批次很多时必须在 4 次收敛内 ≤12 个节点，否则 422；同输入结果必须一致。

---

### Task 1: 拆分策略与类目规则表

**Files:**
- Create: `app/chains/split_rules.py`
- Create: `app/chains/split.py`
- Test: `tests/test_chain_split.py`

**Interfaces:**
- Produces:
  - `SplitPolicy(target_hours: float = 8.0, min_hours: float = 1.0, max_hours: float = 16.0, max_pieces: int = 12, min_batch_size: int = 50, default_batch_size: int = 500)`
  - `parse_split_policy(raw: dict | None) -> SplitPolicy`（非法值抛 `ValueError`）
  - `ModuleRule(key: str, label: str, keywords: tuple[str, ...], skills: dict[str, int])`
  - `BatchRule(units: tuple[str, ...], default_batch_size: int)`
  - `rules_for(category: str | None) -> tuple[ModuleRule, ...]`
  - `batch_rule_for(category: str | None) -> BatchRule`

- [ ] **Step 1: 写失败测试**

```python
import pytest

from app.chains.split import SplitPolicy, parse_split_policy
from app.chains.split_rules import batch_rule_for, rules_for


def test_split_policy_defaults():
    assert parse_split_policy(None) == SplitPolicy(8.0, 1.0, 16.0, 12, 50, 500)


def test_split_policy_accepts_overrides():
    policy = parse_split_policy({"target_hours": 4, "max_pieces": 6})
    assert policy.target_hours == 4.0
    assert policy.max_pieces == 6


def test_split_policy_rejects_inverted_band():
    with pytest.raises(ValueError, match="min_hours"):
        parse_split_policy({"min_hours": 10, "target_hours": 8})


def test_rules_for_unknown_category_is_empty():
    assert rules_for("unknown") == ()


def test_batch_rule_defaults_by_category():
    assert batch_rule_for("data_annotation").default_batch_size == 500
    assert batch_rule_for("translation_localization").default_batch_size == 2000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split.py -q`
Expected: FAIL，`ModuleNotFoundError: app.chains.split`

- [ ] **Step 3: 实现策略与规则表**

`split_rules.py` 至少包含：

```python
MODULE_RULES = {
    "software_dev": (
        ModuleRule("backend", "后端", ("后端", "服务端", "接口", "API", "数据库"), {"backend": 4}),
        ModuleRule("frontend", "前端", ("前端", "页面", "UI", "小程序", "App"), {"frontend": 4}),
        ModuleRule("integration", "联调", ("联调", "集成", "接口对接"), {"frontend": 3, "backend": 3}),
        ModuleRule("dashboard", "数据看板", ("数据看板", "报表", "看板"), {"backend": 3}),
        ModuleRule("payment", "支付", ("支付", "结算"), {"backend": 4}),
        ModuleRule("membership", "会员", ("会员", "账户"), {"backend": 3}),
    ),
    "data_annotation": (
        ModuleRule("batch_annotation", "标注", ("标注", "打标"), {"annotation": 3}),
        ModuleRule("qa", "质检", ("质检", "验收"), {"qa": 3}),
    ),
    "translation_localization": (
        ModuleRule("translation", "翻译", ("翻译", "本地化"), {"translation": 3}),
        ModuleRule("review", "校对", ("校对", "审校"), {"proofreading": 3}),
    ),
    "content_writing": (
        ModuleRule("draft", "撰写", ("撰写", "章节", "稿件", "正文"), {"writing": 3}),
        ModuleRule("edit", "编辑", ("编辑", "润色"), {"editing": 3}),
    ),
    "video_production": (
        ModuleRule("storyboard", "分镜", ("分镜", "脚本"), {"storyboard": 3}),
        ModuleRule("shoot", "拍摄", ("拍摄", "摄影"), {"videography": 3}),
        ModuleRule("edit", "剪辑", ("剪辑", "后期"), {"video_editing": 3}),
    ),
}
BATCH_RULES = {
    "data_annotation": BatchRule(("条", "个", "张", "段"), 500),
    "translation_localization": BatchRule(("字", "词", "页", "章"), 2000),
    "content_writing": BatchRule(("字", "章", "篇", "节"), 3000),
}
DEFAULT_BATCH_RULE = BatchRule(("条", "个", "页", "张", "篇", "章", "节"), 500)
```

`split.py` 实现 `SplitPolicy`、`parse_split_policy`，校验：所有值 > 0，`min_hours <= target_hours <= max_hours`，`max_pieces >= 1`；错误信息包含具体字段名。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_split.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add app/chains/split_rules.py app/chains/split.py tests/test_chain_split.py
git commit -m "feat: add chain split policy and category rules"
```

---

### Task 2: 需求、模块与数量抽取

**Files:**
- Modify: `app/chains/split.py`
- Modify: `tests/conftest.py`（新增 `split_task_factory`）
- Test: `tests/test_chain_split.py`

**Interfaces:**
- Consumes: `rules_for(category)`、`BatchRule`（Task 1）
- Produces:
  - `RequirementItem(text: str, module_key: str | None, quantity: int | None, unit: str | None = None)`
  - `extract_structured_requirements(task: Task) -> list[RequirementItem]`
  - `extract_quantity(text: str) -> int | None`

- [ ] **Step 1: 写失败测试**

在 `tests/conftest.py` 增加：

```python
@pytest.fixture
def split_task_factory():
    def make(
        description: str,
        category: str = "software_dev",
        estimated_hours: float = 40,
        budget: float = 20000,
        **overrides,
    ):
        values = dict(
            task_id="t_split",
            customer_id="c1",
            title="测试任务",
            description=description,
            category=category,
            required_skills={"backend": 3},
            required_level=2,
            difficulty=3,
            priority=3,
            estimated_hours=estimated_hours,
            deadline=datetime.now(timezone.utc) + timedelta(days=14),
            region="CN",
            remote_ok=True,
            budget=budget,
        )
        values.update(overrides)
        return Task(**values)

    return make
```

在 `tests/test_chain_split.py` 增加：

```python
from app.chains.split import (
    RequirementItem,
    extract_quantity,
    extract_structured_requirements,
)


def test_extracts_numbered_requirements_and_modules(split_task_factory):
    items = extract_structured_requirements(
        split_task_factory("1. 后端接口开发；2. 前端页面；3. 联调测试。")
    )
    assert [item.text for item in items] == [
        "后端接口开发", "前端页面", "联调测试",
    ]
    assert [item.module_key for item in items] == [
        "backend", "frontend", "integration",
    ]


def test_parses_quantity_with_commas():
    assert extract_quantity("共 1,200 条数据") == 1200


def test_chinese_numeral_quantity_is_none():
    assert extract_quantity("约一千字") is None


def test_empty_description_falls_back_to_title(split_task_factory):
    items = extract_structured_requirements(split_task_factory(""))
    assert items == [RequirementItem("测试任务", None, None)]


def test_duplicate_requirements_are_removed(split_task_factory):
    items = extract_structured_requirements(
        split_task_factory("后端接口；后端接口；前端页面")
    )
    assert [item.text for item in items] == ["后端接口", "前端页面"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split.py -q`
Expected: FAIL，`ImportError: cannot import name 'extract_structured_requirements'`

- [ ] **Step 3: 实现抽取**

规则：
- 先按编号/列表标记切分（`^\s*(\d+[.、)]|[一二三四五六七八九十]+、|[-*•])\s*`），再按 `。；;\n` 切分；去空白、去重、保留顺序。
- 每个条目匹配 `rules_for(task.category)` 的第一个关键词命中项，得到 `module_key`；无命中为 `None`。
- 数量正则 `(\d[\d,]*)\s*(条|个|篇|页|张|字|词|章|节|款|套|人|单|段)`，去掉逗号转 int；`extract_quantity` 只返回数字，`extract_structured_requirements` 内部同时保留单位到 `RequirementItem.unit`。中文数字不解析，返回 `None`。
- 描述为空时返回 `[RequirementItem(task.title, None, None)]`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_split.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add app/chains/split.py tests/test_chain_split.py tests/conftest.py
git commit -m "feat: extract structured chain requirements and quantities"
```

---

### Task 3: 工时缩放、节点拆分与合并

**Files:**
- Modify: `app/chains/split.py`
- Modify: `tests/conftest.py`（新增 `split_draft_factory`）
- Test: `tests/test_chain_split.py`
- Test: `tests/test_chain_split_invariants.py`

**Interfaces:**
- Consumes: Task 1/2 的 `SplitPolicy`、`RequirementItem`、`extract_structured_requirements`
- Produces: `apply_split(draft: DecompositionDraft, task: Task, policy: SplitPolicy) -> DecompositionDraft`

- [ ] **Step 1: 写失败测试**

在 `tests/conftest.py` 增加：

```python
@pytest.fixture
def split_draft_factory():
    from app.chains.decompose import decompose
    from app.data.templates import load_templates

    templates = load_templates("data/chain_templates/common_task_chains.json")

    def make(task):
        return decompose(task, templates[task.category])

    return make
```

在 `tests/test_chain_split.py` 增加：

```python
from app.chains.split import SplitPolicy, apply_split


def test_scales_template_hours_to_task_hours(split_task_factory, split_draft_factory):
    task = split_task_factory("后端接口开发；前端页面；联调测试", estimated_hours=48)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    total = sum(node.estimated_hours for node in draft.chain.nodes)
    assert abs(total - 48) <= 48 * 0.05


def test_splits_nodes_over_max_hours(split_task_factory, split_draft_factory):
    task = split_task_factory("后端接口开发；前端页面；联调测试", estimated_hours=64)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    task_nodes = [node for node in draft.chain.nodes if node.node_type == "task"]
    assert task_nodes
    assert all(node.estimated_hours <= 16.0 + 0.01 for node in task_nodes)
    assert len(draft.chain.nodes) <= 12


def test_batch_quantity_splits_annotation_node(split_task_factory, split_draft_factory):
    task = split_task_factory(
        "标注 2500 条数据", category="data_annotation"
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    batches = [n for n in draft.chain.nodes if n.key.startswith("batch_annotation_")]
    assert len(batches) == 5
    assert all("500 条" in node.split_reason for node in batches)


def test_no_evidence_falls_back_to_template(split_task_factory, split_draft_factory):
    task = split_task_factory("完成这个项目", estimated_hours=40)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert all(node.split_source == "template" for node in draft.chain.nodes)
    assert draft.split_count == len(draft.chain.nodes)


def test_many_modules_converge_or_raise(split_task_factory, split_draft_factory):
    task = split_task_factory(
        "后端；前端；数据看板；支付；会员；联调；测试；部署",
        estimated_hours=120,
    )
    try:
        draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    except ValueError as error:
        assert "max_pieces" in str(error)
    else:
        assert len(draft.chain.nodes) <= 12


def test_same_input_produces_same_split(split_task_factory, split_draft_factory):
    task = split_task_factory("后端接口开发；前端页面；联调测试", estimated_hours=64)
    first = apply_split(split_draft_factory(task), task, SplitPolicy())
    second = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert [(n.key, round(n.estimated_hours, 4)) for n in first.chain.nodes] == [
        (n.key, round(n.estimated_hours, 4)) for n in second.chain.nodes
    ]
```

在 `tests/test_chain_split_invariants.py` 增加：

```python
from app.chains.dag import validate_dag
from app.chains.split import SplitPolicy, apply_split


def test_split_invariants_hold(split_task_factory, split_draft_factory):
    task = split_task_factory(
        "后端接口开发；前端页面；数据看板；支付模块", estimated_hours=72
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert 1 <= len(draft.chain.nodes) <= 12
    assert validate_dag(draft.chain.nodes).valid
    assert abs(sum(n.estimated_hours for n in draft.chain.nodes) - 72) <= 72 * 0.05
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split.py tests/test_chain_split_invariants.py -q`
Expected: FAIL，`ImportError: cannot import name 'apply_split'`

- [ ] **Step 3: 实现 `apply_split`**

按以下顺序实现（内部函数用 `_` 前缀）：

1. `items = extract_structured_requirements(task)`。
2. 对每个 `item.module_key`，若没有节点满足 `node.key == module_key` 或 `rule.label in node.title`，创建模块节点：
   - key `f"module_{module_key}"`；title 用 `rule.label`；`node_type="task"`；`estimated_hours=policy.target_hours`；`required_skills=rule.skills`；`depends_on=[拓扑第一个节点 key]`；`acceptance=[item.text]`；`split_source="module"`；`split_reason=item.text`；`confidence=0.7`。
   - 所有终止节点（无后继）追加对模块节点的依赖。
3. 用局部字典 `quantities[node.key] = (total_quantity, unit)` 累加需求数量：优先 `node.key == module_key`，否则标题包含 `rule.label`；找不到时加到当前最大工时的非交付节点（工时相同按 key 排序）。
4. 缩放到 `H = task.estimated_hours`；`H <= 0` 时使用当前工时和，不缩放。舍入误差补到最后一个非交付节点。
5. 按拓扑顺序拆分：
   - 数量触发：`quantity >= 2 * policy.min_batch_size` 时，令 `batch_size = batch_rule_for(task.category).default_batch_size`，`k = ceil(quantity / batch_size)`，`k >= 2` 时拆；`split_reason = f"{quantity} {unit}，每批 {ceil(quantity/k)} {unit}"`。
   - 工时触发：`node.estimated_hours > policy.max_hours` 且 `node_type not in {"review", "delivery"}`，`k = ceil(hours / target_hours)`。
   - `k = min(k, policy.max_pieces)`；子节点 key `f"{node.key}_{i}"`，i 从 1 开始；子节点继承依赖/技能/类型/验收（验收追加 `第 i/k 批`）；`parallel_group=node.key`；工时均分，余数给最后一块；后继依赖改为全部子节点。
6. 合并：工时 `< min_hours` 且类型非 delivery，若唯一前驱类型相同且前驱只有这一个后继，合并进前驱（保留前驱 key），追加验收并去重。
7. 收敛：节点数 > `max_pieces` 时 `target_hours *= 1.25` 回到步骤 5，最多 4 次；仍超限则按 `confidence` 升序移除 `split_source in {"requirement", "module"}` 的节点；仍超限抛 `ValueError("unable to split within max_pieces")`。
8. 每次节点变化后从 `depends_on` 重建 `ChainEdge`，最后 `validate_dag`；非法时抛 `ValueError`。
9. 设置 `draft.requirements = [item.text for item in items]`、`draft.chain.nodes/edges/critical_path`、`draft.split_policy=asdict(policy)`、`draft.split_count`、`draft.uncovered_requirements`（无匹配节点且非模块的需求文本）；返回 `draft`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_split.py tests/test_chain_split_invariants.py -q`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add app/chains/split.py tests/test_chain_split.py tests/test_chain_split_invariants.py tests/conftest.py
git commit -m "feat: split and merge chain nodes by hours and batches"
```

---

### Task 4: 预算与截止分配

**Files:**
- Modify: `app/chains/split.py`
- Test: `tests/test_chain_split_invariants.py`

**Interfaces:**
- Produces: `apply_split` 为每个节点填充 `budget` 与 `deadline`。

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime

from app.chains.split import SplitPolicy, apply_split


def test_budget_sums_to_parent_budget(split_task_factory, split_draft_factory):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=48, budget=24000
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert abs(sum(node.budget for node in draft.chain.nodes) - 24000) <= 0.01


def test_deadlines_do_not_exceed_parent(split_task_factory, split_draft_factory):
    task = split_task_factory("后端接口开发；前端页面；联调测试", estimated_hours=48)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert all(node.deadline <= task.deadline for node in draft.chain.nodes)


def test_zero_budget_and_zero_hours_do_not_divide_by_zero(
    split_task_factory, split_draft_factory
):
    task = split_task_factory("后端接口开发；前端页面", estimated_hours=0, budget=0)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert all(node.budget == 0 for node in draft.chain.nodes)
    assert all(node.estimated_hours > 0 for node in draft.chain.nodes)


def test_naive_parent_deadline_is_supported(split_task_factory, split_draft_factory):
    task = split_task_factory("后端接口开发", estimated_hours=16)
    task.deadline = datetime(2026, 12, 31)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    assert draft.chain.nodes
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split_invariants.py -q`
Expected: FAIL，预算/截止仍为默认值

- [ ] **Step 3: 实现分配**

- 预算：`budget_i = round(task.budget * hours_i / H, 2)`，最后一块拿余数；`task.budget <= 0` 或 `H <= 0` 时全部为 0。
- 截止：按逆拓扑 DP 计算 `after_hours(node) = max(successor.estimated_hours + after_hours(successor), 0)`；`deadline = task.deadline - timedelta(hours=after_hours(node))`；naive datetime 先按 UTC 处理；所有截止不晚于父截止。
- 分配发生在拆分、合并、收敛全部完成之后。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_split_invariants.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/chains/split.py tests/test_chain_split_invariants.py
git commit -m "feat: allocate split budget and deadlines"
```

---

### Task 5: 领域字段、decompose 集成与请求参数

**Files:**
- Modify: `app/domain.py`（`SubTask`、`Task`、`DecompositionDraft`）
- Modify: `app/chains/decompose.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Test: `tests/test_chain_split.py`

**Interfaces:**
- Consumes: `apply_split`、`parse_split_policy`
- Produces:
  - `decompose(task, template, variant="standard", max_nodes=10, *, split=False, policy=None) -> DecompositionDraft`
  - `DecomposeRequest.split: bool = False`、`DecomposeRequest.policy: SplitPolicyRequest | None = None`
  - 草稿字段 `split_policy / split_count / uncovered_requirements`

- [ ] **Step 1: 写失败测试**

```python
from app.chains.decompose import decompose
from app.data.templates import load_templates


def test_decompose_split_flag_sets_draft_fields(split_task_factory):
    task = split_task_factory("后端接口开发；前端页面；联调测试", estimated_hours=48)
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(
        task, templates["software_dev"], split=True, policy={"target_hours": 4}
    )
    assert draft.split_policy is not None
    assert draft.split_count == len(draft.chain.nodes)
    assert all(hasattr(node, "budget") for node in draft.chain.nodes)


def test_decompose_without_split_keeps_template_nodes(
    split_task_factory, split_draft_factory
):
    task = split_task_factory("后端接口开发；前端页面", estimated_hours=48)
    draft = split_draft_factory(task)
    assert draft.split_policy is None
    assert draft.split_count == 0


def test_api_rejects_invalid_split_policy(client):
    response = client.post(
        "/chains/decompose",
        json={
            "task_id": "t1",
            "split": True,
            "policy": {"min_hours": 10, "target_hours": 8},
        },
    )
    assert response.status_code == 422


def test_api_split_returns_nodes(client):
    response = client.post("/chains/decompose", json={"task_id": "t1", "split": True})
    assert response.status_code == 200
    assert response.json()["nodes"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split.py -q`
Expected: FAIL，`decompose() got an unexpected keyword argument 'split'`

- [ ] **Step 3: 实现**

- `SubTask` 末尾追加：`budget=0.0`、`deadline=None`、`split_source="template"`、`split_reason=""`、`confidence=1.0`、`parent_key=None`。
- `Task` 末尾追加：`parent_task_id=None`、`chain_id=None`、`subtask_key=None`、`split_source=None`。
- `DecompositionDraft` 追加：`split_policy=None`、`split_count=0`、`uncovered_requirements=field(default_factory=list)`。
- `decompose()` 增加 keyword-only 参数；`split=True` 时解析策略、调用 `apply_split`，并在返回前重新计算 `critical_path`。
- `schemas.py` 增加 `SplitPolicyRequest`（字段与默认值同 Task 1，`gt=0`、`max_pieces ge=1 le=50`）和 `DecomposeRequest.split/policy`。
- `main.py` 的 `/chains/decompose` 把 `policy.model_dump()` 传给 `decompose`；`ValueError` 继续映射为 422。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_split.py tests/test_chains.py tests/test_api.py -q`
Expected: PASS；split=false 的旧测试无回归

- [ ] **Step 5: 提交**

```bash
git add app/domain.py app/chains/decompose.py app/schemas.py app/main.py tests/test_chain_split.py
git commit -m "feat: wire dynamic splitting into decompose and API"
```

---

### Task 6: SubTask 到 Task 的物化构造与校验

**Files:**
- Create: `app/chains/materialize.py`
- Modify: `tests/conftest.py`（新增 `make_draft`）
- Test: `tests/test_chain_materialize.py`

**Interfaces:**
- Produces:
  - `build_subtask_task(parent: Task, node: SubTask, chain: TaskChain, draft_id: str) -> Task`
  - `validate_materialization(draft: DecompositionDraft, parent: Task, planned: list[Task], has_parent_assignment: bool) -> list[str]`
  - `MATERIALIZATION_LOG: Path`

- [ ] **Step 1: 写失败测试**

在 `tests/conftest.py` 增加：

```python
@pytest.fixture
def make_draft():
    from app.domain import DecompositionDraft, TaskChain

    def make(nodes):
        chain = TaskChain(
            chain_id="ch_make",
            root_task_id="t1",
            customer_id="c1",
            deadline=NOW + timedelta(days=7),
            budget=10000,
            nodes=list(nodes),
        )
        return DecompositionDraft(
            draft_id="d_make",
            task_id="t1",
            template_id="make",
            variant="standard",
            chain=chain,
            requirements=[],
            coverage={},
        )

    return make
```

在 `tests/test_chain_materialize.py` 增加：

```python
from app.chains.materialize import build_subtask_task, validate_materialization
from app.domain import SubTask, TaskChain


def test_build_subtask_task_inherits_parent_fields(small_store):
    parent = small_store.tasks["t1"]
    node = SubTask(
        subtask_id="s1", chain_id="ch1", key="backend_dev",
        title="后端开发", node_type="task", estimated_hours=8.0,
        required_skills={"backend": 3}, depends_on=[], acceptance=["接口可用"],
        budget=4000.0, deadline=parent.deadline, split_source="module",
        split_reason="后端模块", confidence=0.9,
    )
    chain = TaskChain(
        chain_id="ch1", root_task_id=parent.task_id, customer_id=parent.customer_id,
        deadline=parent.deadline, budget=parent.budget, nodes=[node],
    )
    task = build_subtask_task(parent, node, chain, "draft1")
    assert task.task_id.startswith("sub_")
    assert task.parent_task_id == parent.task_id
    assert task.chain_id == "ch1"
    assert task.subtask_key == "backend_dev"
    assert task.status == "open"
    assert task.budget == 4000.0
    assert task.deadline == parent.deadline


def test_validate_materialization_reports_empty_plan(small_store, make_draft):
    errors = validate_materialization(
        make_draft([]), small_store.tasks["t1"], [], False
    )
    assert any("no subtasks" in error for error in errors)


def test_validate_materialization_rejects_past_deadline(small_store):
    parent = small_store.tasks["t_past"]
    parent.status = "open"
    node = SubTask(
        subtask_id="s_past", chain_id="ch1", key="backend_dev",
        title="后端开发", node_type="task", estimated_hours=8.0,
        required_skills={"backend": 3}, depends_on=[], acceptance=["ok"],
        budget=1000.0, deadline=parent.deadline, split_source="template",
    )
    from app.chains.materialize import build_subtask_task
    from app.domain import DecompositionDraft, TaskChain

    chain = TaskChain(
        chain_id="ch1", root_task_id=parent.task_id, customer_id=parent.customer_id,
        deadline=parent.deadline, budget=parent.budget, nodes=[node],
    )
    draft = DecompositionDraft(
        draft_id="d1", task_id=parent.task_id, template_id="t",
        variant="standard", chain=chain, requirements=[], coverage={},
    )
    planned = [build_subtask_task(parent, node, chain, "d1")]
    errors = validate_materialization(draft, parent, planned, False)
    assert any("deadline" in error for error in errors)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_materialize.py -q`
Expected: FAIL，`ModuleNotFoundError: app.chains.materialize`

- [ ] **Step 3: 实现**

`build_subtask_task`：
- `task_id = "sub_" + uuid.uuid4().hex`
- `title = f"{parent.title}｜{node.title}"`
- `required_skills = node.required_skills or parent.required_skills`
- `required_level = parent.required_level`
- `difficulty = int(round(min(5, max(1, 1 + 4 * node.estimated_hours / max(H, 1)))))`，`H` 为父任务 `estimated_hours`
- `estimated_hours = node.estimated_hours`
- `deadline = node.deadline or parent.deadline`
- `budget = budget_min = budget_max = node.budget`
- `description = f"{node.title}\n验收：{'；'.join(node.acceptance)}\n拆分依据：{node.split_reason}\n任务链：{chain.chain_id}\n草稿：{draft_id}"`
- `requirements = list(node.acceptance)`
- `status = "open"`，继承 `region/remote_ok/customer_id/category`
- 新字段 `parent_task_id/chain_id/subtask_key/split_source`

`validate_materialization` 返回错误列表：空计划、DAG 非法、工时偏差 >5%（父工时为 0 时对比有效 H）、预算超父预算、截止晚于父截止或已过、父任务已有 assignment、任一 Task 字段非法（技能/等级/工时/预算）。

`MATERIALIZATION_LOG = Path(__file__).resolve().parent.parent.parent / "data" / "chains" / "materialized.jsonl"`

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_materialize.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/chains/materialize.py tests/test_chain_materialize.py tests/conftest.py
git commit -m "feat: build and validate materialized subtasks"
```

---

### Task 7: 拆分质量评分 v2

**Files:**
- Modify: `app/domain.py`（`DecompositionQuality`）
- Modify: `app/chains/split.py`
- Modify: `app/main.py`
- Test: `tests/test_chain_split_quality.py`

**Interfaces:**
- Consumes: `apply_split`、`build_subtask_task`、`validate_materialization`（Task 6）
- Produces:
  - `DecompositionQuality` 新增 `split_fidelity: float = 1.0`、`materializability: float = 1.0`、`quality_version: str = "v1"`
  - `split_quality_score(draft: DecompositionDraft, task: Task, store: Store, policy: SplitPolicy) -> DecompositionQuality`

- [ ] **Step 1: 写失败测试**

```python
from app.chains.split import SplitPolicy, apply_split, split_quality_score


def test_split_quality_version_and_range(
    small_store, split_task_factory, split_draft_factory
):
    task = split_task_factory("后端接口开发；前端页面；联调测试", estimated_hours=48)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    quality = split_quality_score(draft, task, small_store, SplitPolicy())
    assert quality.quality_version == "v2-split"
    assert 0.0 <= quality.total <= 1.0
    assert quality.split_fidelity > 0.99
    assert quality.dependency == 1.0


def test_uncovered_requirement_lowers_coverage(
    small_store, split_task_factory, split_draft_factory
):
    task = split_task_factory("完全无关的一件事", estimated_hours=16)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    quality = split_quality_score(draft, task, small_store, SplitPolicy())
    assert quality.coverage < 1.0
    assert draft.uncovered_requirements
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split_quality.py -q`
Expected: FAIL，`ImportError: cannot import name 'split_quality_score'`

- [ ] **Step 3: 实现**

- 覆盖率：`covered / max(1, len(draft.requirements))`，只统计 `draft.coverage` 中非空且不在 `uncovered_requirements` 的需求。
- 粒度：非交付节点中 `min_hours <= hours <= max_hours` 的比例。
- 拆分保真：`1 - clamp(mean([hours_dev, budget_dev, deadline_dev]))`；`hours_dev = abs(sum_hours - H) / max(H, 1)`；`budget_dev` 同理；`deadline_dev = max(0, (max_deadline - parent.deadline) 小时数) / max(H, 1)`。
- 可派单性：复用 `decompose.quality_score` 的 worker 检查逻辑，按节点计算比例。
- 可物化性：对每个节点调用 `build_subtask_task`，再用 `validate_materialization` 的字段规则逐项检查，通过比例。
- 总分权重：0.28 / 0.18 / 0.12 / 0.12 / 0.14 / 0.08 / 0.05 / 0.03，风险扣分 `min(0.20, 0.05 × 风险标记数)`。
- `main.py`：`split=True` 时调用 `split_quality_score(draft, task, current, policy)`，否则继续用 `quality_score(draft, current)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_split_quality.py tests/test_chain_evaluation.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/domain.py app/chains/split.py app/main.py tests/test_chain_split_quality.py
git commit -m "feat: add split-mode decomposition quality score"
```

---

### Task 8: 草稿查询、物化与撤回接口

**Files:**
- Modify: `app/main.py`
- Modify: `app/chains/materialize.py`（审计写入）
- Modify: `tests/conftest.py`（`client` 传入临时审计路径）
- Test: `tests/test_chain_materialize.py`

**Interfaces:**
- Consumes: `build_subtask_task`、`validate_materialization`
- Produces:
  - `create_app(..., materialization_log: Path | None = None)`
  - `app.state.materializations: dict[str, dict]`
  - `GET /chains/drafts/{draft_id}`
  - `POST /chains/drafts/{draft_id}/materialize`
  - `POST /chains/drafts/{draft_id}/materialize/rollback`

- [ ] **Step 1: 写失败测试**

```python
def _split_draft(client):
    body = client.post("/chains/decompose", json={"task_id": "t1", "split": True}).json()
    return body["draft_id"], body


def test_materialize_creates_tasks_and_splits_parent(client):
    draft_id, body = _split_draft(client)
    response = client.post(f"/chains/drafts/{draft_id}/materialize")
    assert response.status_code == 200
    data = response.json()
    assert data["parent_status"] == "split"
    store = client.app.state.store
    assert store.tasks["t1"].status == "split"
    assert data["task_ids"]
    assert all(store.tasks[tid].parent_task_id == "t1" for tid in data["task_ids"])


def test_materialize_is_idempotent(client):
    draft_id, _ = _split_draft(client)
    assert client.post(f"/chains/drafts/{draft_id}/materialize").status_code == 200
    assert client.post(f"/chains/drafts/{draft_id}/materialize").status_code == 409


def test_parent_is_not_eligible_but_subtasks_are(client):
    from app.service import is_eligible
    from app.domain import Worker

    draft_id, _ = _split_draft(client)
    data = client.post(f"/chains/drafts/{draft_id}/materialize").json()
    store = client.app.state.store
    worker = Worker(
        worker_id="w_split", name="w_split", skills={"backend": 5, "frontend": 5, "requirements": 5, "architecture": 5},
        specialties={"software_dev": 4}, level=4, capacity_hours=80, current_load_hours=0,
        preferred_categories={"software_dev": 0.8}, preferred_difficulty=(2, 4),
        region="CN", remote_ok=True,
    )
    assert not is_eligible(store.tasks["t1"], worker, store)[0]
    assert any(is_eligible(store.tasks[tid], worker, store)[0] for tid in data["task_ids"])


def test_rollback_restores_parent(client):
    draft_id, _ = _split_draft(client)
    data = client.post(f"/chains/drafts/{draft_id}/materialize").json()
    response = client.post(f"/chains/drafts/{draft_id}/materialize/rollback")
    assert response.status_code == 200
    assert client.app.state.store.tasks["t1"].status == "open"
    assert all(tid not in client.app.state.store.tasks for tid in data["task_ids"])


def test_rollback_rejected_when_subtask_assigned(client):
    from app.domain import Assignment
    from datetime import datetime, timezone

    draft_id, _ = _split_draft(client)
    data = client.post(f"/chains/drafts/{draft_id}/materialize").json()
    client.app.state.store.assignments.append(
        Assignment(assignment_id="a1", task_id=data["task_ids"][0], worker_id="w_good",
                   customer_id="c1", status="assigned", created_at=datetime.now(timezone.utc))
    )
    assert client.post(f"/chains/drafts/{draft_id}/materialize/rollback").status_code == 409
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_materialize.py -q`
Expected: FAIL，404（接口不存在）

- [ ] **Step 3: 实现**

- `create_app` 增加 `materialization_log: Path | None = None`，初始化 `app.state.materialization_log = materialization_log or MATERIALIZATION_LOG` 和 `app.state.materializations = {}`。
- `tests/conftest.py` 的 `client` fixture 传入 `materialization_log=tmp_path / "materialized.jsonl"`，避免测试写仓库数据目录。
- `GET /chains/drafts/{draft_id}`：404 或返回草稿字段、质量、节点、`materialized` 布尔值。
- `POST .../materialize`：
  1. 校验草稿存在（404）且未物化（409）。
  2. 取父任务，`has_parent_assignment = any(a.task_id == parent.task_id for a in store.assignments)`。
  3. `planned = [build_subtask_task(...)]`；`errors = validate_materialization(...)`；非空返回 422。
  4. 写入 `store.tasks`；父任务 `status="split"`；记录 `app.state.materializations[draft_id]`；`invalidate_service()`。
  5. 向 `MATERIALIZATION_LOG` 追加 `{"event":"materialize","draft_id":...,"chain_id":...,"parent_task_id":...,"task_ids":[...],"created_at":...}`；返回 spec 6.3 的结构。
- `POST .../rollback`：无记录 404；任一子任务有 assignment 则 409 并列出；删除子任务、父任务恢复 `open`、删除记录、`invalidate_service()`、写 `undo` 审计；返回 `{"draft_id", "task_ids", "parent_status": "open"}`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_chain_materialize.py tests/test_api.py tests/test_chains.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/main.py app/chains/materialize.py tests/test_chain_materialize.py tests/conftest.py
git commit -m "feat: add chain draft materialization and rollback API"
```

---

### Task 9: 离线评估、golden set 与文档

**Files:**
- Create: `dev_data/chains/split_cases.jsonl`
- Create: `scripts/evaluate_chain_split.py`
- Create: `tests/test_chain_split_eval.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `reports/chain_split_eval.json` 和 `reports/chain_split_eval.md`

- [ ] **Step 1: 写失败测试**

```python
def test_split_eval_script_outputs_metrics(tmp_path):
    import json
    import subprocess
    import sys

    output = tmp_path / "chain_split_eval.json"
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_chain_split.py", "--output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["cases"] >= 10
    assert 0.0 <= data["dispatchable_rate"] <= 1.0
    assert data["duplicate_dispatch"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_chain_split_eval.py -q`
Expected: FAIL，脚本不存在

- [ ] **Step 3: 实现**

- `dev_data/chains/split_cases.jsonl`：12 条，覆盖 12 个类目；每条字段：

```json
{"task_id":"g01","category":"software_dev","title":"会员小程序开发","description":"1. 后端接口；2. 前端页面；3. 数据看板；4. 联调测试。","estimated_hours":64,"budget":30000,"deadline_days":30,"required_skills":{"backend":3}}
```

至少包含：software_dev、ui_ux_design、brand_design、content_writing、video_production、marketing_campaign、data_annotation、translation_localization、ecommerce_ops、recruitment、consulting_research、training_course 各一条。

- `scripts/evaluate_chain_split.py`：
  - 参数 `--templates`、`--golden`、`--output`，默认值指向仓库内路径。
  - 对每条 case 构造 `Task`，`decompose(..., split=True)`，应用 `apply_split` 和 `split_quality_score(draft, task, store, policy)`。
  - 用 `generate_dataset(n_workers=200, n_tasks=50, n_assignments=0, seed=42)` 构造评估用 `Store`，只为 worker 池提供技能/容量。
  - 输出 JSON：`cases`、`coverage_gain`（拆分后覆盖率 − 纯模板覆盖率）、`dispatchable_rate`（每个子任务在该 store 中至少有一个 eligible worker 的比例）、`granularity_p50/p95`、`in_band_rate`、`duplicate_dispatch=0`、`deterministic=true`。
  - 同时写 markdown 表格到同目录 `.md`。
- `tests/test_chain_split_eval.py` 用 `subprocess` 跑脚本，断言上述字段。
- `README.md` 增加：拆分开关、三个新端点、`data/chains/materialized.jsonl`、评估脚本命令，并说明统计任务数时必须排除 `status="split"` 的父任务，避免父子重复计数；测试数量说明不写死具体数字。

- [ ] **Step 4: 运行测试与全量回归**

Run: `python -m pytest tests/test_chain_split_eval.py -q`
Expected: PASS

Run: `python -m pytest tests/ -q`
Expected: PASS，现有 423 个测试无回归

- [ ] **Step 5: 提交**

```bash
git add dev_data/chains/split_cases.jsonl scripts/evaluate_chain_split.py tests/test_chain_split_eval.py README.md
git commit -m "feat: add chain split offline evaluation and docs"
```

---

## 完成标准

- 所有任务的测试通过，`python -m pytest tests/ -q` 全绿。
- `split=false` 时旧行为不变；`split=true` 满足全部不变量。
- 物化、撤回、父任务退出推荐、子任务可接单均有测试覆盖。
- 规格文档 `docs/superpowers/specs/2026-11-14-chain-split-design.md` 的 10 节均有对应实现。
