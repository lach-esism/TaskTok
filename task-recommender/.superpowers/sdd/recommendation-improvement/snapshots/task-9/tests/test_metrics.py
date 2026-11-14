from app.metrics import hr_at_k, ndcg_at_k


def test_hr_at_k_boundaries():
    assert hr_at_k(["a", "b"], {"b"}, 1) == 0.0
    assert hr_at_k(["a", "b"], {"b"}, 2) == 1.0
    assert hr_at_k([], {"b"}, 10) == 0.0


def test_ndcg_at_k_perfect_and_zero():
    assert ndcg_at_k(["a"], {"a": 1.0}, 10) == 1.0
    assert ndcg_at_k([], {"a": 1.0}, 10) == 0.0


def test_evaluate_chains_returns_bounded_metrics(small_store):
    from app.data.templates import load_templates
    from app.metrics import evaluate_chains

    templates = load_templates("data/chain_templates/common_task_chains.json")
    metrics = evaluate_chains(small_store, templates, n_samples=5)
    assert metrics["acyclic_rate"] == 1.0
    assert 0.0 <= metrics["mean_quality"] <= 1.0


def test_evaluate_recommender_skips_ineligible_positives(small_store):
    from app.data.store import Store
    from app.domain import Assignment
    from app.metrics import evaluate_recommender
    from app.service import RecommendationService

    timestamp = small_store.assignments[0].created_at
    test_store = Store(
        workers=list(small_store.workers.values()),
        customers=list(small_store.customers.values()),
        tasks=list(small_store.tasks.values()),
        assignments=[
            Assignment(
                assignment_id="a_valid",
                task_id="t1",
                worker_id="w_full",
                customer_id="c1",
                status="completed",
                created_at=timestamp,
            ),
            Assignment(
                assignment_id="a_invalid",
                task_id="t_empty",
                worker_id="w_good",
                customer_id="c1",
                status="completed",
                created_at=timestamp,
            ),
        ],
        feedback=[],
    )
    service = RecommendationService(small_store)
    metrics = evaluate_recommender(test_store, service, k=10)
    assert metrics["task_to_workers_hr"] == 1.0
