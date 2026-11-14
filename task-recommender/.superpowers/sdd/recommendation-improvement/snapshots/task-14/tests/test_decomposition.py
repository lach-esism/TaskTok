from app.chains.decompose import coverage_matrix, decompose, quality_score
from app.data.templates import load_templates


def test_decompose_software_template_has_valid_dag(software_task):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    assert draft.chain.nodes
    assert draft.chain.critical_path
    assert coverage_matrix(draft)


def test_optional_node_exclusion_bypasses_edges(software_task):
    template = {
        "template_id": "tiny_v1",
        "category": "software_dev",
        "version": "1.0.0",
        "target_hours": [1, 8],
        "max_nodes": 5,
        "nodes": [
            {
                "key": "a",
                "title": "需求",
                "type": "task",
                "hours": 2,
                "skills": {},
                "depends_on": [],
                "acceptance": ["ok"],
            },
            {
                "key": "b",
                "title": "可选评审",
                "type": "review",
                "hours": 2,
                "skills": {},
                "depends_on": ["a"],
                "acceptance": ["ok"],
                "optional": True,
                "include_if": "false",
            },
            {
                "key": "c",
                "title": "交付",
                "type": "delivery",
                "hours": 2,
                "skills": {},
                "depends_on": ["b"],
                "acceptance": ["ok"],
            },
        ],
    }
    draft = decompose(software_task, template)
    by_key = {node.key: node for node in draft.chain.nodes}
    assert "b" not in by_key
    assert by_key["c"].depends_on == ["a"]


def test_quality_score_is_bounded(software_task, small_store):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    quality = quality_score(draft, small_store)
    assert 0.0 <= quality.total <= 1.0
