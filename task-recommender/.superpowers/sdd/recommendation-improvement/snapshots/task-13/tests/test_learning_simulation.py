def test_simulation_returns_round_series():
    from app.data.store import Store
    from app.data.synthetic import generate_dataset
    from app.learning_simulation import simulate_learning_rounds

    dataset = generate_dataset(
        n_workers=20,
        n_tasks=50,
        n_assignments=100,
        n_new_users=2,
    )
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    customer_ids = [
        customer.customer_id for customer in dataset.customers[:2]
    ]
    result = simulate_learning_rounds(
        store,
        customer_ids,
        rounds=3,
        selections_per_round=5,
        candidate_pool=5,
        seed=42,
    )
    assert len(result["rounds"]) == 3
    assert len(result["learning_top1"]) == 3
    assert len(result["baseline_top1"]) == 3
    assert all(
        0.0 <= value <= 1.0
        for key in (
            "learning_top1",
            "learning_top5",
            "baseline_top1",
            "baseline_top5",
        )
        for value in result[key]
    )
    assert result["meta"]["selections_per_round"] == 5
