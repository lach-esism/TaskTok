"""Loader for the common task-chain template library."""

from __future__ import annotations

import json
from pathlib import Path


def _validate_template_nodes(template: dict) -> None:
    nodes = template["nodes"]
    keys = [node.get("key") for node in nodes]
    if any(key is None for key in keys):
        raise ValueError(
            f"template {template['template_id']} has a node without a key"
        )
    if len(keys) != len(set(keys)):
        raise ValueError(
            f"template {template['template_id']} has duplicate node keys"
        )

    key_set = set(keys)
    indegree = {key: 0 for key in keys}
    adjacency: dict[str, list[str]] = {key: [] for key in keys}
    for node in nodes:
        for dependency in node.get("depends_on", []):
            if dependency not in key_set:
                raise ValueError(
                    f"missing dependency: {dependency} in template "
                    f"{template['template_id']}"
                )
            adjacency[dependency].append(node["key"])
            indegree[node["key"]] += 1

    ready = [key for key, degree in indegree.items() if degree == 0]
    seen = 0
    while ready:
        key = ready.pop()
        seen += 1
        for successor in adjacency[key]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
    if seen != len(keys):
        raise ValueError(
            f"cycle detected in template {template['template_id']}"
        )


def load_templates(path: str | Path) -> dict[str, dict]:
    """Load templates, validate their DAGs, and index by category."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    templates = data.get("templates")
    if not isinstance(templates, list):
        raise ValueError("template file must contain a 'templates' list")

    result: dict[str, dict] = {}
    for template in templates:
        for field in ("template_id", "category", "nodes"):
            if field not in template:
                raise ValueError(f"template missing required field: {field}")
        if not template["nodes"]:
            raise ValueError(f"template {template['template_id']} has no nodes")
        _validate_template_nodes(template)
        result[template["category"]] = template
    return result
