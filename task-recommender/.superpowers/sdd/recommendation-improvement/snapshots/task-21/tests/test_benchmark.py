import sqlite3

from fastapi.testclient import TestClient

from app.benchmark.db import BenchmarkRepository, build_benchmark_db
from app.main import create_app
from app.benchmark.runner import BenchmarkRoundRunner
from app.benchmark.recommender import BenchmarkRecommender
from app.learning_simulation import SIM_INITIAL_WEIGHTS


def build_small(tmp_path):
    db_path = tmp_path / "benchmark.sqlite"
    summary = build_benchmark_db(
        db_path,
        n_tasks=40,
        n_workers=8,
        seed=7,
        truth_noise=0.003,
    )
    return db_path, summary


def test_benchmark_db_has_natural_language_rows_and_hidden_labels(tmp_path):
    db_path, summary = build_small(tmp_path)
    assert summary["tasks"] == 40
    assert summary["workers"] == 8
    assert summary["train"] + summary["test"] == 40

    connection = sqlite3.connect(db_path)
    try:
        task_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(tasks)")
        }
        assert "gold_worker_id" not in task_columns
        assert "task_text" in task_columns
        resume = connection.execute(
            "SELECT resume_text FROM workers LIMIT 1"
        ).fetchone()[0]
        task_text = connection.execute(
            "SELECT task_text FROM tasks LIMIT 1"
        ).fetchone()[0]
    finally:
        connection.close()
    assert len(resume) > 100
    assert len(task_text) > 40

    repo = BenchmarkRepository(db_path)
    workers = repo.load_workers()
    tasks = repo.load_tasks()
    labels = repo.load_labels()
    worker_ids = {worker["worker_id"] for worker in workers}
    assert len(labels) == len(tasks)
    assert set(labels.values()).issubset(worker_ids)
    assert all("skills" in worker for worker in workers)
    assert all("resume_text" in worker for worker in workers)


def test_recommender_forgets_predictions_but_keeps_weights(tmp_path):
    db_path, _ = build_small(tmp_path)
    repo = BenchmarkRepository(db_path)
    recommender = BenchmarkRecommender(
        repo.load_workers(),
        repo.load_tasks(),
        repo.load_customers(),
        SIM_INITIAL_WEIGHTS,
    )

    predictions = recommender.recommend_all(
        repo.load_tasks()[:5], top_k=5
    )
    assert predictions
    assert recommender.last_recommendations
    weights_before = dict(recommender.weights)

    recommender.reset()

    assert recommender.last_recommendations == {}
    assert recommender.weights == weights_before
    assert recommender.reset_count == 1
    assert not hasattr(recommender, "labels")


def test_benchmark_endpoints(tmp_path, small_store):
    db_path, _ = build_small(tmp_path)
    client = TestClient(
        create_app(
            small_store,
            weights_dir=tmp_path / "weights",
            benchmark_db=db_path,
        )
    )

    summary = client.get("/benchmark/summary")
    assert summary.status_code == 200
    assert summary.json()["tasks"] == 40
    assert summary.json()["rounds"] == []

    run = client.post("/benchmark/run?rounds=2")
    assert run.status_code == 200
    payload = run.json()
    assert len(payload["results"]) == 2
    assert payload["results"][0]["forgot_previous_answers"] is True
    assert len(payload["rounds"]) == 2


def test_round_runner_learns_and_recomputes_each_round(tmp_path):
    db_path, _ = build_small(tmp_path)
    runner = BenchmarkRoundRunner(db_path, learning_rate=0.05)
    results = runner.run(rounds=3)

    assert len(results) == 3
    assert all(item["forgot_previous_answers"] for item in results)
    assert all(item["updates"] == len(runner.train_task_ids) for item in results)
    assert results[0]["weights_before"] != results[-1]["weights_after"]
    assert results[0]["metrics"]["top1"] >= 0.0
    assert results[-1]["metrics"]["top5"] >= results[0]["metrics"]["top5"]
    assert "test_top1" in results[-1]["metrics"]

    stored = runner.repo.load_rounds()
    assert len(stored) == 3
    assert stored[-1]["round"] == 3


def test_benchmark_collaborative_uses_itemcf_not_region():
    # Build a tiny builder with one worker who completed a similar task.
    from app.benchmark.features import BenchmarkFeatureBuilder
    from app.models.itemcf import ItemCF

    workers = [{"worker_id": "w1", "resume_text": "Python 后端", "skills": {"python": 4},
                "capacity_hours": 40, "current_load_hours": 0, "region": "CN",
                "remote_ok": True, "rating": 4.5, "on_time_rate": 0.9,
                "preferred_categories": {"software_dev": 0.8}}]
    tasks = [
        {"task_id": "t1", "task_text": "Python 后端开发", "region": "CN", "remote_ok": True,
         "customer_id": "c1", "required_skills": {"python": 4}},
        {"task_id": "t2", "task_text": "Python 后端开发", "region": "US", "remote_ok": False,
         "customer_id": "c1", "required_skills": {"python": 4}},
    ]
    customers = [{"customer_id": "c1", "preferred_categories": {"software_dev": 0.8}}]
    cf = ItemCF([("w1", "t1", 1.0)])
    builder = BenchmarkFeatureBuilder(workers, tasks, customers, itemcf=cf)
    assert builder.features("t1", "w1")["collaborative"] > 0.0
    assert builder.features("t2", "w1")["collaborative"] >= 0.0
