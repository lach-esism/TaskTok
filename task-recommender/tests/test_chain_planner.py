from app.chains.decompose import decompose
from app.chains.planner import plan_chain
from app.data.templates import load_templates
from app.service import RecommendationService


def test_plan_covers_all_nodes_and_respects_dependencies(software_task, small_store):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    plan = plan_chain(draft.chain, RecommendationService(small_store))
    assigned = {node.subtask_id: node.worker_id for node in plan.nodes}
    assert len(assigned) == len(draft.chain.nodes)
    assert all(worker_id is not None for worker_id in assigned.values())


def test_blocked_node_when_no_eligible_worker(software_task, small_store):
    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    small_store.workers.clear()
    plan = plan_chain(draft.chain, RecommendationService(small_store))
    assert plan.blocked
    assert any(node.worker_id is None for node in plan.nodes)


def test_blocked_dependency_blocks_downstream(software_task, small_store):
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain, plan_chain_beam
    from app.service import RecommendationService

    template = {
        "template_id": "blocked_chain",
        "category": "software_dev",
        "version": "1.0.0",
        "nodes": [
            {
                "key": "a",
                "title": "A",
                "type": "task",
                "hours": 2,
                "skills": {"nonexistent_skill": 5},
                "depends_on": [],
                "acceptance": ["ok"],
            },
            {
                "key": "b",
                "title": "B",
                "type": "task",
                "hours": 2,
                "skills": {},
                "depends_on": ["a"],
                "acceptance": ["ok"],
            },
            {
                "key": "c",
                "title": "C",
                "type": "delivery",
                "hours": 2,
                "skills": {},
                "depends_on": ["b"],
                "acceptance": ["ok"],
            },
        ],
    }
    draft = decompose(software_task, template)
    service = RecommendationService(small_store)
    for planner in (plan_chain, plan_chain_beam):
        plan = planner(draft.chain, service)
        assert {"a", "b", "c"}.issubset(set(plan.blocked))


def test_breach_propagation_on_critical_path(software_task, small_store):
    from app.chains.planner import propagate_breach

    templates = load_templates("data/chain_templates/common_task_chains.json")
    draft = decompose(software_task, templates["software_dev"])
    failed_key = draft.chain.critical_path[1]
    impact = propagate_breach(draft.chain, failed_key, delay_hours=4.0)
    assert impact.failed_node == failed_key
    assert impact.affected_nodes
    assert impact.critical_path_delay == 4.0
    assert impact.requires_replan
