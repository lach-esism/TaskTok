"""Split policy for dynamic task-chain splitting."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

from app.chains.dag import critical_path, topological_order, validate_dag
from app.chains.materialize import build_subtask_task
from app.chains.split_rules import ModuleRule, batch_rule_for, rules_for
from app.data.store import Store
from app.domain import (
    ChainEdge,
    DecompositionDraft,
    DecompositionQuality,
    SubTask,
    Task,
)

_FLOAT_FIELDS = ("target_hours", "min_hours", "max_hours")
_INT_FIELDS = ("max_pieces", "min_batch_size", "default_batch_size")


@dataclass(frozen=True)
class SplitPolicy:
    """Thresholds governing when and how a task chain is split."""

    target_hours: float = 8.0
    min_hours: float = 1.0
    max_hours: float = 16.0
    max_pieces: int = 12
    min_batch_size: int = 50
    default_batch_size: int = 500


def _as_float(raw: object, field: str) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def _as_int(raw: object, field: str) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def parse_split_policy(raw: dict | None) -> SplitPolicy:
    """Build a validated SplitPolicy from a raw mapping or defaults."""
    values: dict[str, float | int] = {}
    for field in _FLOAT_FIELDS:
        values[field] = _as_float(
            (raw or {}).get(field, getattr(SplitPolicy, field)), field
        )
    for field in _INT_FIELDS:
        values[field] = _as_int(
            (raw or {}).get(field, getattr(SplitPolicy, field)), field
        )

    for field in (*_FLOAT_FIELDS, "min_batch_size", "default_batch_size"):
        if values[field] <= 0:
            raise ValueError(f"{field} must be greater than 0")
    if values["max_pieces"] < 1:
        raise ValueError("max_pieces must be at least 1")
    if values["target_hours"] < values["min_hours"]:
        raise ValueError(
            f"min_hours ({values['min_hours']}) must not exceed "
            f"target_hours ({values['target_hours']})"
        )
    if values["target_hours"] > values["max_hours"]:
        raise ValueError(
            f"target_hours ({values['target_hours']}) must not exceed "
            f"max_hours ({values['max_hours']})"
        )
    return SplitPolicy(**values)  # type: ignore[arg-type]


_LIST_MARKER = re.compile(
    r"^\s*(\d+[.、)]|[一二三四五六七八九十]+、|[-*•])\s*"
)
_SENTENCE_SPLIT = re.compile(r"[。；;\n]+")
_QUANTITY = re.compile(
    r"(\d[\d,]*)\s*(条|个|篇|页|张|字|词|章|节|款|套|人|单|段)"
)


@dataclass(frozen=True)
class RequirementItem:
    """One structured requirement extracted from a task description."""

    text: str
    module_key: str | None
    quantity: int | None
    unit: str | None = None


def _split_description(description: str) -> list[str]:
    parts: list[str] = []
    for chunk in _SENTENCE_SPLIT.split(description):
        text = _LIST_MARKER.sub("", chunk).strip()
        if text:
            parts.append(text)
    return parts


def _match_module(
    text: str, rules: tuple[ModuleRule, ...]
) -> str | None:
    lowered = text.lower()
    for rule in rules:
        if any(keyword.lower() in lowered for keyword in rule.keywords):
            return rule.key
    return None


def _quantity_match(text: str) -> tuple[int, str] | None:
    match = _QUANTITY.search(text)
    if match is None:
        return None
    return int(match.group(1).replace(",", "")), match.group(2)


def extract_quantity(text: str) -> int | None:
    """Return the first batch quantity in ``text``, or ``None``."""
    match = _quantity_match(text)
    return match[0] if match else None


def extract_structured_requirements(task: Task) -> list[RequirementItem]:
    """Extract ordered, de-duplicated requirements with module and batch."""
    rules = rules_for(task.category)
    parts = _split_description(task.description)
    if not parts:
        return [RequirementItem(task.title, None, None)]

    items: list[RequirementItem] = []
    seen: set[str] = set()
    for text in parts:
        if text in seen:
            continue
        seen.add(text)
        quantity_match = _quantity_match(text)
        items.append(
            RequirementItem(
                text=text,
                module_key=_match_module(text, rules),
                quantity=quantity_match[0] if quantity_match else None,
                unit=quantity_match[1] if quantity_match else None,
            )
        )
    return items


def _copy_node(node: SubTask) -> SubTask:
    return replace(
        node,
        required_skills=dict(node.required_skills),
        depends_on=list(node.depends_on),
        acceptance=list(node.acceptance),
        risk_flags=list(node.risk_flags),
    )


def _terminals(nodes: list[SubTask]) -> set[str]:
    keys = {node.key for node in nodes}
    for node in nodes:
        for dependency in node.depends_on:
            keys.discard(dependency)
    return keys


def _add_module_nodes(
    nodes: list[SubTask],
    items: list[RequirementItem],
    rules: tuple[ModuleRule, ...],
    policy: SplitPolicy,
) -> list[SubTask]:
    by_key = {rule.key: rule for rule in rules}
    pending: dict[str, list[str]] = {}
    for item in items:
        if item.module_key is None:
            continue
        rule = by_key.get(item.module_key)
        if rule is None:
            continue
        covered = any(
            node.key == rule.key or rule.label in node.title for node in nodes
        )
        if not covered:
            pending.setdefault(rule.key, []).append(item.text)
    if not pending:
        return nodes

    chain_id = nodes[0].chain_id if nodes else ""
    root = topological_order(nodes)[0]
    terminals = _terminals(nodes)
    used = {node.key for node in nodes}
    created: list[SubTask] = []
    for module_key, texts in pending.items():
        rule = by_key[module_key]
        key = f"module_{module_key}"
        while key in used:
            key = f"{key}_x"
        used.add(key)
        created.append(
            SubTask(
                subtask_id=f"{chain_id}_{key}",
                chain_id=chain_id,
                key=key,
                title=rule.label,
                node_type="task",
                estimated_hours=policy.target_hours,
                required_skills=dict(rule.skills),
                depends_on=[root],
                acceptance=list(texts),
                split_source="module",
                split_reason="；".join(texts),
                confidence=0.7,
            )
        )
    for node in nodes:
        if node.key in terminals:
            node.depends_on = [
                *node.depends_on,
                *(created_node.key for created_node in created),
            ]
    return [*nodes, *created]


def _accumulate_quantities(
    nodes: list[SubTask],
    items: list[RequirementItem],
    rules: tuple[ModuleRule, ...],
) -> dict[str, tuple[int, str | None]]:
    by_key = {rule.key: rule for rule in rules}
    node_by_key = {node.key: node for node in nodes}
    quantities: dict[str, tuple[int, str | None]] = {}
    for item in items:
        if item.quantity is None:
            continue
        rule = by_key.get(item.module_key) if item.module_key else None
        target: SubTask | None = None
        if rule is not None:
            target = node_by_key.get(rule.key) or next(
                (node for node in nodes if rule.label in node.title), None
            )
            if target is None:
                target = node_by_key.get(f"module_{rule.key}")
        if target is None:
            candidates = [
                node for node in nodes if node.node_type != "delivery"
            ]
            if not candidates:
                continue
            target = sorted(
                candidates, key=lambda node: (-node.estimated_hours, node.key)
            )[0]
        total, unit = quantities.get(
            target.key, (0, item.unit)
        )
        quantities[target.key] = (
            total + item.quantity,
            unit or item.unit,
        )
    return quantities


def _scale_hours(nodes: list[SubTask], target_hours: float) -> None:
    total = sum(node.estimated_hours for node in nodes)
    if target_hours <= 0 or total <= 0:
        return
    factor = target_hours / total
    for node in nodes:
        node.estimated_hours = round(node.estimated_hours * factor, 4)
    difference = target_hours - sum(
        node.estimated_hours for node in nodes
    )
    for node in reversed(nodes):
        if node.node_type != "delivery":
            node.estimated_hours = round(
                node.estimated_hours + difference, 4
            )
            break


def _split_count(
    node: SubTask,
    quantity: tuple[int, str | None] | None,
    policy: SplitPolicy,
    target_hours: float,
    category: str | None,
) -> tuple[int, str, str]:
    if quantity is not None and quantity[0] >= 2 * policy.min_batch_size:
        batch_size = batch_rule_for(category).default_batch_size
        count = min(
            math.ceil(quantity[0] / batch_size), policy.max_pieces
        )
        if count >= 2:
            per_batch = math.ceil(quantity[0] / count)
            return (
                count,
                f"{quantity[0]} {quantity[1] or ''}，每批 "
                f"{per_batch} {quantity[1] or ''}".strip(),
                "batch",
            )
    if (
        node.node_type in {"review", "delivery"}
        or node.estimated_hours <= policy.max_hours
    ):
        return 1, "", node.split_source
    count = min(
        max(2, math.ceil(node.estimated_hours / target_hours)),
        policy.max_pieces,
    )
    return (
        count,
        f"{node.estimated_hours:.1f} 小时超过 {policy.max_hours:.1f}，"
        f"按 {target_hours:.1f} 小时拆分",
        node.split_source,
    )


def _split_pass(
    nodes: list[SubTask],
    quantities: dict[str, tuple[int, str | None]],
    policy: SplitPolicy,
    target_hours: float,
    category: str | None,
) -> list[SubTask]:
    order = topological_order(nodes)
    by_key = {node.key: node for node in nodes}
    used = {node.key for node in nodes}
    replacements: dict[str, list[SubTask]] = {}
    result: list[SubTask] = []
    for key in order:
        node = by_key[key]
        count, reason, source = _split_count(
            node, quantities.get(key), policy, target_hours, category
        )
        count = min(count, policy.max_pieces)
        if count <= 1:
            result.append(node)
            continue
        children: list[SubTask] = []
        remaining = node.estimated_hours
        for index in range(1, count + 1):
            if index < count:
                hours = round(node.estimated_hours / count, 4)
            else:
                hours = round(remaining, 4)
            remaining = round(remaining - hours, 4)
            child_key = f"{node.key}_{index}"
            while child_key in used:
                child_key = f"{child_key}_x"
            used.add(child_key)
            children.append(
                SubTask(
                    subtask_id=f"{node.chain_id}_{child_key}",
                    chain_id=node.chain_id,
                    key=child_key,
                    title=f"{node.title}（{index}/{count}）",
                    node_type=node.node_type,
                    estimated_hours=hours,
                    required_skills=dict(node.required_skills),
                    depends_on=list(node.depends_on),
                    acceptance=[
                        *node.acceptance,
                        f"第 {index}/{count} 批",
                    ],
                    optional=node.optional,
                    parallel_group=node.key,
                    risk_flags=list(node.risk_flags),
                    budget=node.budget,
                    deadline=node.deadline,
                    split_source=source,
                    split_reason=reason,
                    confidence=node.confidence,
                    parent_key=node.key,
                )
            )
        replacements[node.key] = children
        result.extend(children)

    for node in result:
        rewritten: list[str] = []
        for dependency in node.depends_on:
            children = replacements.get(dependency)
            if children:
                rewritten.extend(child.key for child in children)
            else:
                rewritten.append(dependency)
        node.depends_on = rewritten
    return result


def _merge_tiny(nodes: list[SubTask], policy: SplitPolicy) -> list[SubTask]:
    changed = True
    while changed:
        changed = False
        order = topological_order(nodes)
        by_key = {node.key: node for node in nodes}
        for key in order:
            node = by_key.get(key)
            if (
                node is None
                or node.estimated_hours >= policy.min_hours
                or node.node_type == "delivery"
            ):
                continue
            predecessors = [
                item for item in nodes if item.key in node.depends_on
            ]
            if len(predecessors) != 1:
                continue
            predecessor = predecessors[0]
            if predecessor.node_type != node.node_type:
                continue
            successors = [
                item for item in nodes if predecessor.key in item.depends_on
            ]
            if [item.key for item in successors] != [node.key]:
                continue
            if (
                predecessor.estimated_hours + node.estimated_hours
                > policy.max_hours
            ):
                continue
            predecessor.estimated_hours = round(
                predecessor.estimated_hours + node.estimated_hours, 4
            )
            predecessor.acceptance = list(
                dict.fromkeys([*predecessor.acceptance, *node.acceptance])
            )
            for item in nodes:
                if node.key in item.depends_on:
                    item.depends_on = [
                        predecessor.key if dependency == node.key
                        else dependency
                        for dependency in item.depends_on
                    ]
            nodes.remove(node)
            changed = True
            break
    return nodes


def _build_nodes(
    base_nodes: list[SubTask],
    quantities: dict[str, tuple[int, str | None]],
    policy: SplitPolicy,
    category: str | None,
) -> list[SubTask]:
    for attempt in range(4):
        target_hours = policy.target_hours * (1.25 ** attempt)
        nodes = [_copy_node(node) for node in base_nodes]
        nodes = _split_pass(
            nodes, quantities, policy, target_hours, category
        )
        nodes = _merge_tiny(nodes, policy)
        if len(nodes) <= policy.max_pieces:
            return nodes

    nodes = [_copy_node(node) for node in base_nodes]
    nodes = _split_pass(
        nodes, quantities, policy, policy.target_hours, category
    )
    nodes = _merge_tiny(nodes, policy)
    while len(nodes) > policy.max_pieces:
        removable = [
            node
            for node in nodes
            if node.split_source in {"requirement", "module"}
        ]
        if not removable:
            raise ValueError("unable to split within max_pieces")
        victim = min(
            removable, key=lambda node: (node.confidence, node.key)
        )
        nodes.remove(victim)
        for node in nodes:
            if victim.key in node.depends_on:
                node.depends_on = [
                    dependency
                    for dependency in node.depends_on
                    if dependency != victim.key
                ]
    return nodes


def _tokens(text: str) -> list[str]:
    lowered = text.lower().strip()
    tokens = [
        lowered[index:index + 2]
        for index in range(max(0, len(lowered) - 1))
        if lowered[index:index + 2].strip()
    ]
    return tokens or ([lowered] if lowered else [])


def _allocate_budget(nodes: list[SubTask], total_budget: float) -> None:
    total_hours = sum(node.estimated_hours for node in nodes)
    if total_budget <= 0 or total_hours <= 0:
        for node in nodes:
            node.budget = 0.0
        return
    order = topological_order(nodes)
    by_key = {node.key: node for node in nodes}
    allocated = 0.0
    for index, key in enumerate(order):
        node = by_key[key]
        if index == len(order) - 1:
            node.budget = round(max(0.0, total_budget - allocated), 2)
        else:
            node.budget = round(
                total_budget * node.estimated_hours / total_hours, 2
            )
            allocated = round(allocated + node.budget, 2)


def _as_aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value
    )


def _assign_deadlines(
    nodes: list[SubTask], parent_deadline: datetime
) -> None:
    deadline = _as_aware(parent_deadline)
    order = topological_order(nodes)
    by_key = {node.key: node for node in nodes}
    successors: dict[str, list[str]] = {key: [] for key in by_key}
    for node in nodes:
        for dependency in node.depends_on:
            successors[dependency].append(node.key)
    after_hours: dict[str, float] = {}
    for key in reversed(order):
        after_hours[key] = max(
            (
                by_key[successor].estimated_hours
                + after_hours[successor]
                for successor in successors[key]
            ),
            default=0.0,
        )
    for key in order:
        by_key[key].deadline = deadline - timedelta(
            hours=after_hours[key]
        )


def _coverage(
    nodes: list[SubTask], items: list[RequirementItem]
) -> tuple[dict[str, list[str]], list[str]]:
    coverage: dict[str, list[str]] = {}
    uncovered: list[str] = []
    for item in items:
        tokens = _tokens(item.text)
        matches = [
            node.key
            for node in nodes
            if any(
                token
                in f"{node.title} {' '.join(node.acceptance)}".lower()
                for token in tokens
            )
        ]
        coverage[item.text] = matches
        if not matches:
            uncovered.append(item.text)
    return coverage, uncovered


def apply_split(
    draft: DecompositionDraft,
    task: Task,
    policy: SplitPolicy,
) -> DecompositionDraft:
    """Split a template draft into independently dispatchable subtasks."""
    items = extract_structured_requirements(task)
    rules = rules_for(task.category)
    nodes = [_copy_node(node) for node in draft.chain.nodes]
    nodes = _add_module_nodes(nodes, items, rules, policy)
    quantities = _accumulate_quantities(nodes, items, rules)
    _scale_hours(nodes, task.estimated_hours)
    nodes = _build_nodes(nodes, quantities, policy, task.category)
    has_evidence = any(
        item.module_key is not None for item in items
    ) or bool(quantities)
    if not has_evidence:
        for node in nodes:
            node.confidence = min(node.confidence, 0.8)
            if not node.split_reason:
                node.split_reason = "无结构化需求，使用模板"
    _allocate_budget(nodes, task.budget)
    _assign_deadlines(nodes, task.deadline)

    chain_id = draft.chain.chain_id
    edges = [
        ChainEdge(
            chain_id=chain_id,
            from_node=dependency,
            to_node=node.key,
        )
        for node in nodes
        for dependency in node.depends_on
    ]
    draft.chain.nodes = nodes
    draft.chain.edges = edges
    validation = validate_dag(nodes)
    if not validation.valid:
        raise ValueError(
            "invalid chain after split: " + "; ".join(validation.errors)
        )
    path, _ = critical_path(nodes)
    draft.chain.critical_path = path

    coverage, uncovered = _coverage(nodes, items)
    draft.requirements = [item.text for item in items]
    draft.coverage = coverage
    draft.uncovered_requirements = uncovered
    draft.split_policy = asdict(policy)
    draft.split_count = len(nodes)
    return draft


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def split_quality_score(
    draft: DecompositionDraft,
    task: Task,
    store: Store,
    policy: SplitPolicy,
) -> DecompositionQuality:
    """Score a split draft with the v2 split-specific rubric."""
    nodes = draft.chain.nodes
    requirements = draft.requirements
    covered = sum(
        1
        for requirement in requirements
        if draft.coverage.get(requirement)
        and requirement not in draft.uncovered_requirements
    )
    coverage = covered / max(1, len(requirements))

    non_delivery = [
        node for node in nodes if node.node_type != "delivery"
    ]
    granularity = (
        sum(
            1
            for node in non_delivery
            if policy.min_hours <= node.estimated_hours <= policy.max_hours
        )
        / max(1, len(non_delivery))
    )
    dependency = 1.0 if validate_dag(nodes).valid else 0.0

    workers = list(store.workers.values())
    feasible = sum(
        1
        for node in nodes
        if any(
            worker.status == "active"
            and all(
                worker.skills.get(skill, 0) >= minimum
                for skill, minimum in node.required_skills.items()
            )
            and worker.current_load_hours + node.estimated_hours
            <= worker.capacity_hours
            for worker in workers
        )
    )
    feasibility = feasible / max(1, len(nodes))

    total_hours = sum(node.estimated_hours for node in nodes)
    total_budget = sum(node.budget for node in nodes)
    effective_hours = (
        task.estimated_hours
        if task.estimated_hours > 0
        else total_hours
    )
    hours_dev = abs(total_hours - effective_hours) / max(
        effective_hours, 1
    )
    budget_dev = abs(total_budget - task.budget) / max(task.budget, 1)
    parent_deadline = _as_aware(task.deadline)
    deadlines = [
        _as_aware(node.deadline)
        for node in nodes
        if node.deadline is not None
    ]
    latest = max(deadlines, default=parent_deadline)
    deadline_dev = max(
        0.0, (latest - parent_deadline).total_seconds() / 3600
    ) / max(effective_hours, 1)
    split_fidelity = 1.0 - _clamp(
        (hours_dev + budget_dev + deadline_dev) / 3.0
    )

    now = datetime.now(timezone.utc)
    materializable = 0
    for node in nodes:
        try:
            built = build_subtask_task(
                task, node, draft.chain, draft.draft_id
            )
        except (TypeError, ValueError):
            continue
        if (
            built.estimated_hours > 0
            and built.budget >= 0
            and built.required_level >= 1
            and built.required_skills
            and _as_aware(built.deadline) <= parent_deadline
            and _as_aware(built.deadline) >= now
        ):
            materializable += 1
    materializability = materializable / max(1, len(nodes))

    template_category = getattr(
        draft, "template_category", ""
    )
    template_fit = 1.0 if template_category == task.category else 0.5
    historical_success = 0.5
    risk_penalty = min(
        0.20, 0.05 * sum(len(node.risk_flags) for node in nodes)
    )
    total = _clamp(
        0.28 * coverage
        + 0.18 * granularity
        + 0.12 * split_fidelity
        + 0.12 * dependency
        + 0.14 * feasibility
        + 0.08 * materializability
        + 0.05 * template_fit
        + 0.03 * historical_success
        - risk_penalty
    )

    issues: list[str] = []
    if coverage < 1.0:
        issues.append(
            "uncovered requirements: "
            + (", ".join(draft.uncovered_requirements) or "unknown")
        )
    if dependency < 1.0:
        issues.append("invalid DAG")
    if feasibility < 1.0:
        issues.append("not every node has a feasible worker")
    if materializability < 1.0:
        issues.append("not every node can be materialized")
    if split_fidelity < 0.95:
        issues.append("split totals deviate from the parent task")

    return DecompositionQuality(
        coverage=coverage,
        granularity=granularity,
        dependency=dependency,
        feasibility=feasibility,
        template_fit=template_fit,
        historical_success=historical_success,
        risk_penalty=risk_penalty,
        total=total,
        issues=issues,
        split_fidelity=split_fidelity,
        materializability=materializability,
        quality_version="v2-split",
    )
