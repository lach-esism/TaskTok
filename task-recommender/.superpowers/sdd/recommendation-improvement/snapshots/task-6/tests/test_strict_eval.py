from app.evaluation_strict import build_eval_store, task_to_workers_metrics
from app.features import candidate_features  # noqa: F401  (import smoke)
from app.service import RecommendationService


def test_build_eval_store_excludes_test_feedback(dataset):
    store = build_eval_store(dataset)
    test_ids = {item.feedback_id for item in dataset.test_feedback}
    store_ids = {item.feedback_id for item in store.feedback}
    assert test_ids.isdisjoint(store_ids)
    assert len(store.assignments) == len(dataset.train)


def test_task_to_workers_metrics_are_bounded(dataset):
    store = build_eval_store(dataset)
    service = RecommendationService(store)
    metrics = task_to_workers_metrics(
        store, service, dataset.test[:20], k=10, candidate_mode="all",
    )
    assert metrics["queries"] > 0
    assert 0.0 <= metrics["hr"] <= 1.0
    assert 0.0 <= metrics["ndcg"] <= 1.0
    assert 0.0 <= metrics["mrr"] <= 1.0


def test_exposed_mode_resolves_by_assignment_id(dataset):
    """Two impressions sharing query_id/created_at must resolve by assignment_id."""
    from app.domain import Impression

    store = build_eval_store(dataset)
    assignment = dataset.test[0]
    first = Impression(
        request_id="r1", query_id=assignment.task_id, candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": "other"},
    )
    second = Impression(
        request_id="r2", query_id=assignment.task_id, candidate_ids=["w2"],
        propensities={"w2": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": assignment.assignment_id},
    )
    store.impressions = [first, second]
    # The helper should select `second`; assert through the public metrics path.
    metrics = task_to_workers_metrics(
        store, RecommendationService(store), [assignment], k=10,
        candidate_mode="exposed",
    )
    assert metrics["queries"] == 1


def test_exposed_mode_ranks_the_resolved_candidate_set(dataset):
    """The assignment-id match (not the tied impression) defines the candidates."""
    from app.domain import Impression

    store = build_eval_store(dataset)
    assignment = dataset.test[0]
    tied_other = Impression(
        request_id="r1", query_id=assignment.task_id, candidate_ids=["w1"],
        propensities={"w1": 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": "other"},
    )
    tied_ours = Impression(
        request_id="r2", query_id=assignment.task_id,
        candidate_ids=[assignment.worker_id],
        propensities={assignment.worker_id: 1.0}, policy="test",
        created_at=assignment.created_at,
        metadata={"assignment_id": assignment.assignment_id},
    )
    store.impressions = [tied_other, tied_ours]
    metrics = task_to_workers_metrics(
        store, RecommendationService(store), [assignment], k=10,
        candidate_mode="exposed",
    )
    assert metrics["queries"] == 1
    assert metrics["hr"] == 1.0


def test_exposed_mode_accepts_test_impressions_without_store_mutation(dataset):
    """Evaluation-only impressions must not contaminate the train-only store."""
    store = build_eval_store(dataset)
    before = list(store.impressions)
    train_ids = {item.request_id for item in dataset.train_impressions}
    test_ids = {item.request_id for item in dataset.test_impressions}

    metrics = task_to_workers_metrics(
        store, RecommendationService(store), dataset.test, k=10,
        candidate_mode="exposed", impressions=dataset.test_impressions,
    )

    assert metrics["queries"] == len(dataset.test)
    assert metrics["hr"] == 1.0
    assert store.impressions == before
    assert {item.request_id for item in store.impressions} == train_ids
    assert {item.request_id for item in store.impressions}.isdisjoint(
        test_ids
    )
