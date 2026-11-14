from app.chains.compose import compose_templates
from app.data.templates import _validate_template_nodes, load_templates


def test_compose_software_and_content_is_acyclic(software_task):
    templates = load_templates(
        "data/chain_templates/common_task_chains.json"
    )
    composed = compose_templates(
        software_task,
        templates,
        ["software_dev", "content_writing"],
    )
    keys = [node["key"] for node in composed["nodes"]]
    assert len(keys) == len(set(keys))
    assert "requirements" in keys
    assert "delivery" in keys
    assert "software_dev:testing" in keys
    _validate_template_nodes(composed)


def test_compose_preserves_shared_node_skills(software_task):
    templates = load_templates(
        "data/chain_templates/common_task_chains.json"
    )
    composed = compose_templates(
        software_task,
        templates,
        ["software_dev", "data_annotation"],
    )
    by_key = {node["key"]: node for node in composed["nodes"]}
    assert by_key["requirements"]["skills"].get("requirements", 0) >= 3
    assert by_key["delivery"]["skills"].get("data_labeling", 0) >= 2
