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
