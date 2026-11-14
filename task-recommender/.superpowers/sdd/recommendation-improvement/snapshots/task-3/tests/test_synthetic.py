from app.data.synthetic import CATEGORIES, TASK_PROFILES, generate_dataset


def test_generate_dataset_is_deterministic_and_split():
    a = generate_dataset(seed=42)
    b = generate_dataset(seed=42)
    assert [w.worker_id for w in a.workers] == [w.worker_id for w in b.workers]
    assert len(a.assignments) == 3000
    assert len(a.train) + len(a.test) == 3000
    assert len(a.workers) == 100
    assert len(a.tasks) == 500


def test_generated_dataset_has_meaningful_candidate_pool():
    from app.data.store import Store
    from app.service import RecommendationService

    dataset = generate_dataset(n_workers=100, n_tasks=100, n_assignments=500)
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    service = RecommendationService(store)
    sizes = [
        len(service.recommend_workers(task.task_id, top_n=100))
        for task in list(store.tasks.values())[:20]
    ]
    assert sorted(sizes)[len(sizes) // 2] >= 10


def test_every_category_has_a_realistic_posting_profile():
    assert set(TASK_PROFILES) == set(CATEGORIES)
    for profile in TASK_PROFILES.values():
        assert len(profile["titles"]) >= 5
        assert len(profile["requirements"]) >= 3
        assert profile["deliverables"]
        assert profile["budget"][0] > 0
        assert profile["budget"][1] > profile["budget"][0]


def test_tasks_look_like_real_postings():
    dataset = generate_dataset()

    for task in dataset.tasks:
        assert task.title
        assert task.category not in task.title
        assert not task.title.endswith(" task")
        assert len(task.description) >= 20
        assert "。。" not in task.description
        assert task.description.endswith("。")
        assert task.requirements and len(task.requirements) >= 3
        assert all(len(item) >= 6 for item in task.requirements)
        assert task.budget_min > 0
        assert task.budget_max > task.budget_min
        assert task.budget_min <= task.budget <= task.budget_max
        assert task.created_at < task.deadline

    titles = {task.title for task in dataset.tasks}
    assert len(titles) >= 150


def test_worker_aggregates_are_train_only():
    dataset = generate_dataset()
    train_completed: dict[str, int] = {}
    for assignment in dataset.train:
        if assignment.status == "completed":
            train_completed[assignment.worker_id] = (
                train_completed.get(assignment.worker_id, 0) + 1
            )
    for worker in dataset.workers:
        assert worker.completed == train_completed.get(worker.worker_id, 0)


from app.data.synthetic import generate_dataset


def test_synthetic_new_fields_are_populated():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    assert all(worker.expected_pay > 0 for worker in dataset.workers)
    assert any(worker.certifications for worker in dataset.workers)
    assert any(worker.communication_ratings for worker in dataset.workers)
    for task in dataset.tasks:
        assert set(task.required_skill_weights) == set(task.required_skills)


def test_train_and_test_feedback_are_disjoint():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    train_ids = {item.feedback_id for item in dataset.train_feedback}
    test_ids = {item.feedback_id for item in dataset.test_feedback}
    assert train_ids.isdisjoint(test_ids)
    assert len(train_ids) + len(test_ids) == len(dataset.feedback)


def test_certification_values_are_limited_to_expected_levels():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    allowed = {0.0, 0.5, 0.8}
    for worker in dataset.workers:
        assert set(worker.certifications) == set(worker.specialties)
        assert set(worker.certifications.values()) <= allowed


def test_expected_pay_matches_specialty_budget_formula():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    for worker in dataset.workers:
        first_specialty = next(iter(worker.specialties))
        budget_min, budget_max = TASK_PROFILES[first_specialty]["budget"]
        midpoint = (budget_min + budget_max) / 2
        assert midpoint * 0.7 <= worker.expected_pay <= midpoint * 1.3
        assert worker.expected_pay == round(worker.expected_pay, 2)


def test_communication_ratings_are_train_only():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    expected: dict[str, list[float]] = {}
    for item in dataset.train_feedback:
        if item.communication_rating is not None:
            expected.setdefault(item.worker_id, []).append(
                float(item.communication_rating)
            )
    for worker in dataset.workers:
        assert sorted(worker.communication_ratings) == sorted(
            expected.get(worker.worker_id, [])
        )
