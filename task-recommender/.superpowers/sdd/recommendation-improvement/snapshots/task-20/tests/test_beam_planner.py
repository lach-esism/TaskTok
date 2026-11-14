def test_beam_plan_covers_nodes_and_respects_capacity(
    software_task, small_store
):
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain_beam
    from app.data.templates import load_templates
    from app.service import RecommendationService

    templates = load_templates(
        "data/chain_templates/common_task_chains.json"
    )
    draft = decompose(software_task, templates["software_dev"])
    plan = plan_chain_beam(
        draft.chain,
        RecommendationService(small_store),
        beam_width=3,
    )
    assert len(plan.nodes) == len(draft.chain.nodes)
    assert all(node.worker_id is not None for node in plan.nodes)
    assert not plan.blocked
