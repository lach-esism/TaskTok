def test_ineligible_worker_is_excluded(small_store):
    from app.service import is_eligible

    ok, reason = is_eligible(
        small_store.workers["w_bad"], small_store.tasks["t1"], small_store
    )
    assert not ok
    assert "skill" in reason.lower()


def test_recommend_workers_returns_top_n_and_scores(small_store):
    from app.service import RecommendationService

    service = RecommendationService(small_store)
    candidates = service.recommend_workers("t1", top_n=2)
    assert 0 < len(candidates) <= 2
    assert all(0.0 <= candidate.score <= 1.0 for candidate in candidates)
    assert candidates == sorted(candidates, key=lambda c: c.score, reverse=True)


def test_api_missing_task_returns_404(client):
    response = client.post("/recommend/workers", json={"task_id": "nope"})
    assert response.status_code == 404


def test_cold_start_worker_still_ranked_with_zero_cf(small_store):
    from app.service import RecommendationService

    service = RecommendationService(small_store)
    candidates = service.recommend_workers("t1", top_n=10)
    cold = [candidate for candidate in candidates if candidate.cold_start]
    assert cold
    assert all(candidate.breakdown["collaborative"] == 0.0 for candidate in cold)


def test_empty_candidate_set_returns_200_with_reason(client):
    response = client.post("/recommend/workers", json={"task_id": "t_empty"})
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == []
    assert body["reason"]


def test_worker_already_assigned_to_task_is_excluded(small_store):
    from app.domain import Assignment
    from app.service import RecommendationService

    small_store.assignments.append(
        Assignment(
            assignment_id="a_assigned_t1",
            task_id="t1",
            worker_id="w_good",
            customer_id="c1",
            status="completed",
            created_at=small_store.assignments[0].created_at,
        )
    )
    service = RecommendationService(small_store)
    candidate_ids = {
        candidate.candidate_id
        for candidate in service.recommend_workers("t1", top_n=100)
    }
    assert "w_good" not in candidate_ids


def test_hard_constraints_absent_from_results(small_store):
    from app.service import RecommendationService

    candidate_ids = {
        candidate.candidate_id
        for candidate in RecommendationService(small_store).recommend_workers(
            "t1", top_n=100
        )
    }
    assert {"w_bad", "w_overloaded", "w_breach", "w_low"}.isdisjoint(
        candidate_ids
    )


def test_cold_start_cf_zero_while_warm_cf_positive(small_store):
    from app.service import RecommendationService

    candidates = {
        candidate.candidate_id: candidate
        for candidate in RecommendationService(small_store).recommend_workers(
            "t2", top_n=100
        )
    }
    assert candidates["w_cold"].cold_start
    assert candidates["w_cold"].breakdown["collaborative"] == 0.0
    assert candidates["w_warm"].breakdown["collaborative"] > 0.0


def test_api_missing_worker_returns_404(client):
    response = client.post(
        "/recommend/tasks", json={"worker_id": "nope"}
    )
    assert response.status_code == 404


def test_api_empty_task_candidates_returns_200_with_reason(client):
    response = client.post("/recommend/tasks", json={"worker_id": "w_bad"})
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == []
    assert body["reason"]


def test_itemcf_ignores_feedback_outside_store_assignments(small_store):
    from app.domain import Assignment, Feedback
    from app.service import _build_itemcf

    small_store.assignments.append(
        Assignment(
            assignment_id="a_train_t1",
            task_id="t1",
            worker_id="w_good",
            customer_id="c1",
            status="completed",
            created_at=small_store.assignments[0].created_at,
        )
    )
    small_store.feedback.append(
        Feedback(
            feedback_id="f_test_t1",
            assignment_id="a_not_in_store",
            worker_id="w_good",
            task_id="t1",
            overall_rating=5,
            created_at=small_store.assignments[0].created_at,
        )
    )
    itemcf = _build_itemcf(small_store)
    assert itemcf.user_items["w_good"]["t1"] == 0.5


def test_recent_breach_uses_data_reference_time():
    from datetime import timedelta

    from app.data.store import Store
    from app.data.synthetic import generate_dataset
    from app.domain import Task
    from app.service import is_eligible

    dataset = generate_dataset()
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    reference = store.reference_time
    breached = [
        worker
        for worker in dataset.workers
        if worker.capacity_hours - worker.current_load_hours >= 1
        and sum(
            1
            for breach in worker.breach_dates
            if (reference - breach).total_seconds() <= 180 * 86400
        )
        >= 2
    ]
    assert breached, "seed data should contain a recently-breached worker"
    worker = breached[0]
    task = Task(
        task_id="t_recent_breach",
        customer_id="c1",
        title="recent breach check",
        category="software_dev",
        required_skills={},
        required_level=1,
        difficulty=3,
        priority=3,
        estimated_hours=0.5,
        deadline=reference + timedelta(days=7),
        region=worker.region,
        remote_ok=True,
    )
    eligible, reason = is_eligible(worker, task, store)
    assert not eligible
    assert "breach" in reason.lower()
