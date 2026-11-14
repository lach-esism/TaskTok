"""Template-based task-chain decomposition and quality scoring."""

from __future__ import annotations

import re
import uuid

from app.chains.dag import critical_path as compute_critical_path
from app.chains.dag import validate_dag
from app.data.store import Store
from app.domain import (
    ChainEdge,
    DecompositionDraft,
    DecompositionQuality,
    SubTask,
    Task,
    TaskChain,
)

SPLIT_PATTERN = re.compile(r"[。；;\n]")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def extract_requirements(task: Task) -> list[str]:
    parts = [part.strip() for part in SPLIT_PATTERN.split(task.description)]
    requirements = [part for part in parts if part]
    return requirements or [task.title]


def _condition_true(expression: str, task: Task) -> bool:
    text = expression.strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    match = re.fullmatch(r"([\w.]+)\s*==\s*'?([^']+)'?", text)
    if not match:
        return False
    key, expected = match.group(1), match.group(2).strip().lower()
    if "." in key:
        return False
    actual = getattr(task, key, None)
    return str(actual).lower() == expected


def _node_hours(node_def: dict, multiplier: float) -> float:
    hours_range = node_def.get("hours_range")
    if isinstance(hours_range, list) and len(hours_range) >= 2:
        raw = hours_range[1]
    else:
        raw = node_def.get("hours", 4.0)
    return _clamp(float(raw) * multiplier, 0.5, 40.0)


def _resolve_dependencies(
    dependency: str,
    included: set[str],
    excluded: set[str],
    raw_by_key: dict[str, dict],
    seen: set[str] | None = None,
) -> list[str]:
    if dependency in included:
        return [dependency]
    if dependency not in excluded:
        raise ValueError(f"unknown dependency: {dependency}")
    seen = seen or set()
    if dependency in seen:
        return []
    seen.add(dependency)
    resolved: list[str] = []
    for parent in raw_by_key[dependency].get("depends_on", []):
        for key in _resolve_dependencies(parent, included, excluded, raw_by_key, seen):
            if key not in resolved:
                resolved.append(key)
    return resolved


def decompose(
    task: Task,
    template: dict,
    variant: str = "standard",
    max_nodes: int = 10,
) -> DecompositionDraft:
    variant_config = template.get("variants", {}).get(variant, {})
    multiplier = float(variant_config.get("hours_multiplier", 1.0))
    effective_max = min(
        max_nodes,
        int(variant_config.get("max_nodes", template.get("max_nodes", max_nodes))),
    )

    raw_nodes = template.get("nodes", [])
    raw_by_key = {node["key"]: node for node in raw_nodes}
    excluded: set[str] = set(variant_config.get("exclude", []))
    forced_include: set[str] = set(variant_config.get("include", []))

    included_order: list[str] = []
    for node_def in raw_nodes:
        key = node_def["key"]
        if key in excluded:
            continue
        optional = bool(node_def.get("optional", False))
        if optional:
            if key in forced_include:
                included_order.append(key)
            elif "include_if" in node_def:
                if _condition_true(str(node_def["include_if"]), task):
                    included_order.append(key)
                else:
                    excluded.add(key)
            else:
                excluded.add(key)
        else:
            included_order.append(key)

    if len(included_order) > effective_max:
        removable = [
            key
            for key in reversed(included_order)
            if raw_by_key[key].get("type") != "delivery"
        ]
        for key in removable:
            if len(included_order) <= effective_max:
                break
            included_order.remove(key)
            excluded.add(key)

    included = set(included_order)
    chain_id = uuid.uuid4().hex
    nodes: list[SubTask] = []
    edges: list[ChainEdge] = []
    for key in included_order:
        node_def = raw_by_key[key]
        resolved_dependencies: list[str] = []
        for dependency in node_def.get("depends_on", []):
            for resolved in _resolve_dependencies(
                dependency, included, excluded, raw_by_key
            ):
                if resolved not in resolved_dependencies:
                    resolved_dependencies.append(resolved)
        node = SubTask(
            subtask_id=f"{chain_id}_{key}",
            chain_id=chain_id,
            key=key,
            title=node_def.get("title", key),
            node_type=node_def.get("type", "task"),
            estimated_hours=_node_hours(node_def, multiplier),
            required_skills=dict(node_def.get("skills", {})),
            depends_on=resolved_dependencies,
            acceptance=list(node_def.get("acceptance", [])),
            optional=bool(node_def.get("optional", False)),
            parallel_group=node_def.get("parallel_group"),
            risk_flags=list(node_def.get("risk_flags", [])),
        )
        nodes.append(node)
        for dependency in resolved_dependencies:
            edges.append(
                ChainEdge(
                    chain_id=chain_id,
                    from_node=dependency,
                    to_node=key,
                )
            )

    path, _ = compute_critical_path(nodes) if nodes else ([], 0.0)
    chain = TaskChain(
        chain_id=chain_id,
        root_task_id=task.task_id,
        customer_id=task.customer_id,
        deadline=task.deadline,
        budget=task.budget,
        nodes=nodes,
        edges=edges,
        critical_path=path,
    )
    draft = DecompositionDraft(
        draft_id=uuid.uuid4().hex,
        task_id=task.task_id,
        template_id=template.get("template_id", "unknown"),
        variant=variant,
        chain=chain,
        requirements=extract_requirements(task),
        coverage={},
    )
    draft.template_category = template.get("category", "")
    draft.coverage = coverage_matrix(draft)
    return draft


def _tokens(text: str) -> list[str]:
    lowered = text.lower().strip()
    tokens = [
        lowered[index:index + 2]
        for index in range(max(0, len(lowered) - 1))
        if lowered[index:index + 2].strip()
    ]
    return tokens or ([lowered] if lowered else [])


def coverage_matrix(draft: DecompositionDraft) -> dict[str, list[str]]:
    nodes = draft.chain.nodes
    fallbacks: list[str] = []
    coverage: dict[str, list[str]] = {}
    delivery = next(
        (node.key for node in nodes if node.node_type == "delivery"), None
    )
    for requirement in draft.requirements:
        tokens = _tokens(requirement)
        matches = [
            node.key
            for node in nodes
            if any(token in node.title.lower() for token in tokens)
        ]
        if matches:
            coverage[requirement] = matches[:1]
        else:
            coverage[requirement] = [delivery] if delivery else []
            fallbacks.append(requirement)
    draft.coverage_fallbacks = fallbacks
    return coverage


def quality_score(
    draft: DecompositionDraft, store: Store
) -> DecompositionQuality:
    nodes = draft.chain.nodes
    requirements = draft.requirements
    fallbacks = set(getattr(draft, "coverage_fallbacks", []))
    covered = sum(
        1
        for requirement in requirements
        if draft.coverage.get(requirement) and requirement not in fallbacks
    )
    coverage = covered / max(1, len(requirements))

    granularity = (
        sum(1 for node in nodes if 2.0 <= node.estimated_hours <= 16.0)
        / max(1, len(nodes))
    )
    dependency = 1.0 if validate_dag(nodes).valid else 0.0

    workers = list(store.workers.values())
    feasible_nodes = 0
    for node in nodes:
        if any(
            worker.status == "active"
            and all(
                worker.skills.get(skill, 0) >= minimum
                for skill, minimum in node.required_skills.items()
            )
            and worker.current_load_hours + node.estimated_hours
            <= worker.capacity_hours
            for worker in workers
        ):
            feasible_nodes += 1
    feasibility = feasible_nodes / max(1, len(nodes))

    task = store.tasks.get(draft.chain.root_task_id)
    template_category = getattr(
        draft, "template_category", draft.template_id.split("_v")[0]
    )
    template_fit = (
        1.0
        if task is not None and template_category == task.category
        else 0.5
    )
    historical_success = 0.5
    risk_penalty = min(
        0.3, 0.05 * sum(len(node.risk_flags) for node in nodes)
    )

    total = (
        0.30 * coverage
        + 0.20 * granularity
        + 0.15 * dependency
        + 0.15 * feasibility
        + 0.10 * template_fit
        + 0.10 * historical_success
        - risk_penalty
    )
    total = _clamp(total, 0.0, 1.0)

    issues: list[str] = []
    if coverage < 1.0:
        issues.append(
            f"uncovered requirements: {', '.join(fallbacks) or 'unknown'}"
        )
    if dependency < 1.0:
        issues.append("invalid DAG")
    if feasibility < 1.0:
        issues.append("not every node has a feasible worker")
    if risk_penalty > 0:
        issues.append("risk flags present")

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
    )
