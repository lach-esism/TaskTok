"""DAG utilities for task chains."""

from __future__ import annotations

from app.domain import SubTask, ValidationResult


def topological_order(nodes: list[SubTask]) -> list[str]:
    """Return node keys in deterministic topological order."""
    keys = [node.key for node in nodes]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate node key")
    dependencies = {node.key: list(node.depends_on) for node in nodes}
    for key, deps in dependencies.items():
        for dependency in deps:
            if dependency not in dependencies:
                raise ValueError(f"missing dependency: {dependency}")

    indegree = {key: len(deps) for key, deps in dependencies.items()}
    adjacency: dict[str, list[str]] = {key: [] for key in dependencies}
    for key, deps in dependencies.items():
        for dependency in deps:
            adjacency[dependency].append(key)

    ready = sorted(key for key, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for successor in sorted(adjacency[key]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
        ready.sort()

    if len(order) != len(dependencies):
        raise ValueError("cycle detected in task chain")
    return order


def validate_dag(nodes: list[SubTask]) -> ValidationResult:
    try:
        order = topological_order(nodes)
    except ValueError as error:
        return ValidationResult(valid=False, errors=[str(error)], order=[])
    return ValidationResult(valid=True, errors=[], order=order)


def _earliest_finish(
    nodes: list[SubTask], order: list[str]
) -> tuple[dict[str, float], dict[str, str | None]]:
    by_key = {node.key: node for node in nodes}
    earliest: dict[str, float] = {}
    predecessor: dict[str, str | None] = {}
    for key in order:
        node = by_key[key]
        if not node.depends_on:
            earliest[key] = node.estimated_hours
            predecessor[key] = None
            continue
        best = sorted(
            node.depends_on, key=lambda dependency: (-earliest[dependency], dependency)
        )[0]
        earliest[key] = earliest[best] + node.estimated_hours
        predecessor[key] = best
    return earliest, predecessor


def critical_path(nodes: list[SubTask]) -> tuple[list[str], float]:
    order = topological_order(nodes)
    earliest, predecessor = _earliest_finish(nodes, order)
    end = sorted(earliest, key=lambda key: (-earliest[key], key))[0]
    path: list[str] = []
    current: str | None = end
    while current is not None:
        path.append(current)
        current = predecessor[current]
    path.reverse()
    return path, earliest[end]


def compute_slack(nodes: list[SubTask]) -> dict[str, float]:
    order = topological_order(nodes)
    earliest, _ = _earliest_finish(nodes, order)
    by_key = {node.key: node for node in nodes}
    project_finish = max(earliest.values())

    successors: dict[str, list[str]] = {node.key: [] for node in nodes}
    for node in nodes:
        for dependency in node.depends_on:
            successors[dependency].append(node.key)

    latest: dict[str, float] = {}
    for key in reversed(order):
        if not successors[key]:
            latest[key] = project_finish
        else:
            latest[key] = min(
                latest[successor] - by_key[successor].estimated_hours
                for successor in successors[key]
            )

    return {
        key: max(0.0, latest[key] - earliest[key])
        for key in by_key
    }
