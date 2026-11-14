def test_milp_plan_is_feasible(software_task, small_store):
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain_milp
    from app.data.templates import load_templates
    from app.service import RecommendationService

    templates = load_templates(
        "data/chain_templates/common_task_chains.json"
    )
    draft = decompose(software_task, templates["software_dev"])
    plan = plan_chain_milp(
        draft.chain, RecommendationService(small_store)
    )
    assert len(plan.nodes) == len(draft.chain.nodes)
    assert all(node.worker_id is not None for node in plan.nodes)
    assert plan.planner == "milp"
    fallback = plan_chain_milp(
        draft.chain, RecommendationService(small_store), max_nodes=1
    )
    assert fallback.planner == "beam_fallback"
