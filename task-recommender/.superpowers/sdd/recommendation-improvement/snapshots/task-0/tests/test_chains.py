import json

import pytest

from app.chains.dag import critical_path, topological_order, validate_dag
from app.chains.decompose import decompose
from app.data.templates import load_templates
from app.domain import SubTask


def make_node(key, depends_on, hours=4.0):
    return SubTask(
        subtask_id=f"s_{key}",
        chain_id="c1",
        key=key,
        title=key,
        node_type="task",
        estimated_hours=hours,
        required_skills={},
        depends_on=depends_on,
        acceptance=["ok"],
    )


def test_loads_twelve_templates():
    templates = load_templates("data/chain_templates/common_task_chains.json")
    assert len(templates) == 12
    assert "software_dev" in templates


def test_topological_order_and_critical_path():
    nodes = [
        make_node("a", []),
        make_node("b", ["a"], 6.0),
        make_node("c", ["a"], 2.0),
        make_node("d", ["b", "c"], 4.0),
    ]
    assert topological_order(nodes)[0] == "a"
    path, hours = critical_path(nodes)
    assert path == ["a", "b", "d"]
    assert hours == 14.0


def test_cycle_is_rejected():
    nodes = [make_node("a", ["b"]), make_node("b", ["a"])]
    result = validate_dag(nodes)
    assert not result.valid
    assert any(
        "cycle" in error.lower() or "cyclic" in error.lower()
        for error in result.errors
    )


def test_missing_dependency_is_rejected():
    nodes = [make_node("a", ["missing"])]
    result = validate_dag(nodes)
    assert not result.valid


def test_load_templates_rejects_missing_dependency(tmp_path):
    data = {
        "templates": [
            {
                "template_id": "bad_missing",
                "category": "bad_missing",
                "nodes": [
                    {
                        "key": "a",
                        "title": "A",
                        "type": "task",
                        "hours": 1,
                        "skills": {},
                        "depends_on": ["missing"],
                        "acceptance": ["ok"],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "bad_missing.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="missing dependency"):
        load_templates(path)


def test_load_templates_rejects_cycle(tmp_path):
    data = {
        "templates": [
            {
                "template_id": "bad_cycle",
                "category": "bad_cycle",
                "nodes": [
                    {
                        "key": "a",
                        "title": "A",
                        "type": "task",
                        "hours": 1,
                        "skills": {},
                        "depends_on": ["b"],
                        "acceptance": ["ok"],
                    },
                    {
                        "key": "b",
                        "title": "B",
                        "type": "task",
                        "hours": 1,
                        "skills": {},
                        "depends_on": ["a"],
                        "acceptance": ["ok"],
                    },
                ],
            }
        ]
    }
    path = tmp_path / "bad_cycle.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="cycle"):
        load_templates(path)


def test_decompose_rejects_unknown_dependency(software_task):
    template = {
        "template_id": "bad_dep",
        "category": "software_dev",
        "version": "1.0.0",
        "nodes": [
            {
                "key": "a",
                "title": "A",
                "type": "task",
                "hours": 2,
                "skills": {},
                "depends_on": ["missing"],
                "acceptance": ["ok"],
            }
        ],
    }
    with pytest.raises(ValueError, match="unknown dependency"):
        decompose(software_task, template)
