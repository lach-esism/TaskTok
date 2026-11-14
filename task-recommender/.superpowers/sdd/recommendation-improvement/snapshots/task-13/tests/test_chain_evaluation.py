def test_evaluate_planners_returns_metrics(small_store):
    from app.data.templates import load_templates
    from app.evaluation_chains import evaluate_planners

    templates = load_templates(
        "data/chain_templates/common_task_chains.json"
    )
    metrics = evaluate_planners(
        small_store, templates, n_samples=3
    )
    assert "greedy" in metrics
    assert "beam" in metrics
    assert 0.0 <= metrics["greedy"]["plan_coverage"] <= 1.0
    assert 0.0 <= metrics["beam"]["mean_node_score"] <= 1.0
