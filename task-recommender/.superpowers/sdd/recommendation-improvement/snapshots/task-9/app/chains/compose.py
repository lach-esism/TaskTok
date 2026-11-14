"""Compose multiple task-chain templates into one DAG."""

from __future__ import annotations

from app.data.templates import _validate_template_nodes
from app.domain import Task

SHARED_KEYS = {"requirements", "delivery"}


def compose_templates(
    task: Task,
    templates: dict[str, dict],
    categories: list[str],
    max_nodes: int = 15,
) -> dict:
    selected_categories = list(dict.fromkeys(categories))
    if not selected_categories:
        raise ValueError("至少需要一个模板类别")
    missing = [
        category
        for category in selected_categories
        if category not in templates
    ]
    if missing:
        raise ValueError(f"未知模板类别: {', '.join(missing)}")

    requirements = {
        "key": "requirements",
        "title": "统一需求澄清",
        "type": "task",
        "hours": 3,
        "skills": {},
        "depends_on": [],
        "acceptance": ["合并后的需求经客户确认"],
    }
    delivery = {
        "key": "delivery",
        "title": "统一交付",
        "type": "delivery",
        "hours": 3,
        "skills": {},
        "depends_on": [],
        "acceptance": ["整体交付验收通过"],
    }

    nodes: list[dict] = [requirements, delivery]
    for category in selected_categories:
        for node in templates[category]["nodes"]:
            if node["key"] == "requirements":
                for skill, level in node.get("skills", {}).items():
                    requirements["skills"][skill] = max(
                        requirements["skills"].get(skill, 0), level
                    )
                for criterion in node.get("acceptance", []):
                    if criterion not in requirements["acceptance"]:
                        requirements["acceptance"].append(criterion)
            elif node["key"] == "delivery":
                for skill, level in node.get("skills", {}).items():
                    delivery["skills"][skill] = max(
                        delivery["skills"].get(skill, 0), level
                    )
                for criterion in node.get("acceptance", []):
                    if criterion not in delivery["acceptance"]:
                        delivery["acceptance"].append(criterion)

    for category in selected_categories:
        template = templates[category]
        raw_nodes = template["nodes"]
        prefixed = {
            node["key"]: f"{category}:{node['key']}"
            for node in raw_nodes
            if node["key"] not in SHARED_KEYS
        }
        successors = {
            dependency
            for node in raw_nodes
            for dependency in node.get("depends_on", [])
        }
        leaves = [
            node["key"]
            for node in raw_nodes
            if node["key"] not in SHARED_KEYS
            and node["key"] not in successors
        ]

        for node in raw_nodes:
            key = node["key"]
            if key in SHARED_KEYS:
                continue
            dependencies: list[str] = []
            for dependency in node.get("depends_on", []):
                if dependency == "requirements":
                    dependencies.append("requirements")
                elif dependency in prefixed:
                    dependencies.append(prefixed[dependency])
                elif dependency in templates:
                    dependencies.append(dependency)
            if not node.get("depends_on") or "requirements" in node.get(
                "depends_on", []
            ):
                dependencies.append("requirements")
            copied = dict(node)
            copied["key"] = prefixed[key]
            copied["depends_on"] = list(dict.fromkeys(dependencies))
            nodes.append(copied)

        delivery["depends_on"].extend(
            prefixed[leaf] for leaf in leaves
        )

    delivery["depends_on"] = list(dict.fromkeys(delivery["depends_on"]))
    if len(nodes) > max_nodes:
        raise ValueError(
            f"组合后节点数 {len(nodes)} 超过上限 {max_nodes}，"
            "请减少模板类别或提高上限"
        )
    composed = {
        "template_id": "composed_" + "_".join(sorted(selected_categories)),
        "category": task.category,
        "name": "组合任务链",
        "version": "1.0.0",
        "target_hours": [2, 24],
        "max_nodes": max_nodes,
        "nodes": nodes,
    }
    _validate_template_nodes(composed)
    return composed
