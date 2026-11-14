"""SQLite benchmark schema, seeding, and label-isolated repository."""

from __future__ import annotations

import json
import math
import random
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

from app.benchmark.features import BenchmarkFeatureBuilder, FEATURE_KEYS
from app.data.synthetic import CATEGORIES, generate_dataset
from app.learning_simulation import SIM_INITIAL_WEIGHTS, SIM_TRUE_WEIGHTS
from app.resume import build_resume

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    preferred_categories TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    headline TEXT NOT NULL,
    resume_text TEXT NOT NULL,
    skills TEXT NOT NULL,
    categories TEXT NOT NULL,
    rating REAL NOT NULL,
    completed INTEGER NOT NULL,
    on_time_rate REAL NOT NULL,
    rework_rate REAL NOT NULL,
    capacity_hours REAL NOT NULL,
    current_load_hours REAL NOT NULL,
    region TEXT NOT NULL,
    remote_ok INTEGER NOT NULL,
    preferred_categories TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    requirements TEXT NOT NULL,
    task_text TEXT NOT NULL,
    budget REAL NOT NULL,
    deadline TEXT NOT NULL,
    region TEXT NOT NULL,
    remote_ok INTEGER NOT NULL,
    split TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    task_id TEXT PRIMARY KEY,
    gold_worker_id TEXT NOT NULL,
    split TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
    round INTEGER PRIMARY KEY,
    top1 REAL NOT NULL,
    top5 REAL NOT NULL,
    mrr REAL NOT NULL,
    ndcg REAL NOT NULL,
    train_top1 REAL NOT NULL,
    train_top5 REAL NOT NULL,
    test_top1 REAL NOT NULL,
    test_top5 REAL NOT NULL,
    weights TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendations (
    round INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (round, task_id, rank)
);
"""


def _task_text(task) -> str:
    return "。".join(
        [
            task.title,
            task.description,
            "要求：" + "；".join(task.requirements),
        ]
    )


def _resume_text(resume: dict) -> str:
    parts = [
        resume["name"],
        resume["headline"],
        resume["summary"],
        "技能：" + "、".join(resume["skills"]),
    ]
    for job in resume["work_experience"]:
        parts.append(
            f"{job['company']} {job['title']} {job['period']}。"
            + "；".join(job["bullets"])
        )
    for project in resume["projects"]:
        parts.append(
            f"项目：{project['name']}，{project['role']}。"
            + "；".join(project["bullets"])
        )
    parts.append("证书：" + "、".join(resume["certifications"]))
    return "。".join(parts)


def _gumbel(rng: random.Random) -> float:
    value = max(rng.random(), 1e-12)
    return -math.log(-math.log(value))


def build_benchmark_db(
    db_path: Path,
    n_tasks: int = 1000,
    n_workers: int = 100,
    seed: int = 42,
    truth_noise: float = 0.05,
) -> dict:
    """Create a SQLite benchmark with hidden gold labels.

    The model sees tasks and resumes. Gold answers live only in ``labels``.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    dataset = generate_dataset(
        n_workers=n_workers,
        n_tasks=n_tasks,
        n_assignments=max(1000, n_tasks * 3),
        seed=seed,
        n_new_users=0,
    )

    customer_rng = random.Random(seed + 7)
    customers = []
    for customer in dataset.customers:
        preferred = customer_rng.sample(CATEGORIES, k=2)
        customers.append(
            {
                "customer_id": customer.customer_id,
                "name": customer.name,
                "preferred_categories": {
                    category: round(customer_rng.uniform(0.6, 0.95), 3)
                    for category in preferred
                },
            }
        )

    workers = []
    for worker in dataset.workers:
        resume = build_resume(worker)["resume"]
        rating = (
            statistics.mean(worker.ratings) if worker.ratings else 4.5
        )
        workers.append(
            {
                "worker_id": worker.worker_id,
                "name": resume["name"],
                "headline": resume["headline"],
                "resume_text": _resume_text(resume),
                "skills": dict(worker.skills),
                "categories": dict(worker.specialties),
                "rating": round(rating, 3),
                "completed": worker.completed,
                "on_time_rate": (
                    round(worker.on_time / worker.completed, 4)
                    if worker.completed
                    else 0.9
                ),
                "rework_rate": (
                    round(worker.rework_count / worker.completed, 4)
                    if worker.completed
                    else 0.0
                ),
                "capacity_hours": float(worker.capacity_hours),
                "current_load_hours": float(worker.current_load_hours),
                "region": worker.region,
                "remote_ok": int(worker.remote_ok),
                "preferred_categories": dict(
                    worker.preferred_categories
                ),
            }
        )

    split_rng = random.Random(seed + 11)
    order = list(range(len(dataset.tasks)))
    split_rng.shuffle(order)
    test_count = max(1, len(order) // 5)
    test_indices = set(order[:test_count])

    tasks = []
    for index, task in enumerate(dataset.tasks):
        tasks.append(
            {
                "task_id": task.task_id,
                "customer_id": task.customer_id,
                "title": task.title,
                "description": task.description,
                "requirements": list(task.requirements),
                "task_text": _task_text(task),
                "budget": float(task.budget),
                "deadline": task.deadline.isoformat(),
                "region": task.region,
                "remote_ok": int(task.remote_ok),
                "split": "test" if index in test_indices else "train",
            }
        )

    builder = BenchmarkFeatureBuilder(workers, tasks, customers)
    gold_rng = random.Random(seed + 101)
    labels = {}
    for task in tasks:
        best_worker = None
        best_score = float("-inf")
        for worker in workers:
            features = builder.features(
                task["task_id"], worker["worker_id"]
            )
            score = sum(
                SIM_TRUE_WEIGHTS[key] * features[key]
                for key in FEATURE_KEYS
            )
            score += truth_noise * _gumbel(gold_rng)
            if score > best_score:
                best_score = score
                best_worker = worker["worker_id"]
        labels[task["task_id"]] = {
            "gold_worker_id": best_worker,
            "split": task["split"],
        }

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("seed", str(seed)),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("n_tasks", str(len(tasks))),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("n_workers", str(len(workers))),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("truth_noise", str(truth_noise)),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("true_weights", json.dumps(SIM_TRUE_WEIGHTS)),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("initial_weights", json.dumps(SIM_INITIAL_WEIGHTS)),
        )
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            ("created_at", datetime.now(timezone.utc).isoformat()),
        )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [
                (
                    customer["customer_id"],
                    customer["name"],
                    json.dumps(customer["preferred_categories"]),
                )
                for customer in customers
            ],
        )
        conn.executemany(
            "INSERT INTO workers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    worker["worker_id"],
                    worker["name"],
                    worker["headline"],
                    worker["resume_text"],
                    json.dumps(worker["skills"]),
                    json.dumps(worker["categories"]),
                    worker["rating"],
                    worker["completed"],
                    worker["on_time_rate"],
                    worker["rework_rate"],
                    worker["capacity_hours"],
                    worker["current_load_hours"],
                    worker["region"],
                    worker["remote_ok"],
                    json.dumps(worker["preferred_categories"]),
                )
                for worker in workers
            ],
        )
        conn.executemany(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    task["task_id"],
                    task["customer_id"],
                    task["title"],
                    task["description"],
                    json.dumps(task["requirements"], ensure_ascii=False),
                    task["task_text"],
                    task["budget"],
                    task["deadline"],
                    task["region"],
                    task["remote_ok"],
                    task["split"],
                )
                for task in tasks
            ],
        )
        conn.executemany(
            "INSERT INTO labels VALUES (?, ?, ?)",
            [
                (
                    task_id,
                    label["gold_worker_id"],
                    label["split"],
                )
                for task_id, label in labels.items()
            ],
        )
        conn.commit()
    finally:
        conn.close()

    distribution: dict[str, int] = {}
    for label in labels.values():
        distribution[label["gold_worker_id"]] = (
            distribution.get(label["gold_worker_id"], 0) + 1
        )
    return {
        "db_path": str(db_path),
        "tasks": len(tasks),
        "workers": len(workers),
        "train": sum(1 for task in tasks if task["split"] == "train"),
        "test": sum(1 for task in tasks if task["split"] == "test"),
        "gold_workers": len(distribution),
        "max_gold_share": round(
            max(distribution.values()) / len(tasks), 4
        ),
    }


class BenchmarkRepository:
    """Reads model-safe tables separately from the label table."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def load_workers(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM workers").fetchall()
        return [
            {
                **dict(row),
                "skills": json.loads(row["skills"]),
                "categories": json.loads(row["categories"]),
                "preferred_categories": json.loads(
                    row["preferred_categories"]
                ),
            }
            for row in rows
        ]

    def load_customers(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM customers").fetchall()
        return [
            {
                **dict(row),
                "preferred_categories": json.loads(
                    row["preferred_categories"]
                ),
            }
            for row in rows
        ]

    def load_tasks(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, customer_id, title, description, "
                "requirements, task_text, budget, deadline, region, "
                "remote_ok, split FROM tasks"
            ).fetchall()
        return [
            {
                **dict(row),
                "requirements": json.loads(row["requirements"]),
            }
            for row in rows
        ]

    def load_metadata(self) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM metadata"
            ).fetchall()
        metadata = {}
        for row in rows:
            value = row["value"]
            try:
                metadata[row["key"]] = json.loads(value)
            except (TypeError, ValueError):
                metadata[row["key"]] = value
        return metadata

    def load_labels(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, gold_worker_id FROM labels"
            ).fetchall()
        return {
            row["task_id"]: row["gold_worker_id"] for row in rows
        }

    def load_splits(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, split FROM labels"
            ).fetchall()
        return {row["task_id"]: row["split"] for row in rows}

    def clear_rounds(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM rounds")
            connection.execute("DELETE FROM recommendations")

    def save_round(
        self,
        round_no: int,
        metrics: dict,
        weights: dict,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO rounds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    round_no,
                    metrics["top1"],
                    metrics["top5"],
                    metrics["mrr"],
                    metrics["ndcg"],
                    metrics["train_top1"],
                    metrics["train_top5"],
                    metrics["test_top1"],
                    metrics["test_top5"],
                    json.dumps(weights),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def save_recommendations(
        self,
        round_no: int,
        predictions: dict[str, list[str]],
        scores: dict[str, dict[str, float]],
        top_k: int = 5,
    ) -> None:
        rows = []
        for task_id, workers in predictions.items():
            for rank, worker_id in enumerate(workers[:top_k], start=1):
                rows.append(
                    (
                        round_no,
                        task_id,
                        worker_id,
                        rank,
                        scores[task_id].get(worker_id, 0.0),
                    )
                )
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM recommendations WHERE round = ?", (round_no,)
            )
            connection.executemany(
                "INSERT INTO recommendations VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def load_rounds(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rounds ORDER BY round"
            ).fetchall()
        return [
            {**dict(row), "weights": json.loads(row["weights"])}
            for row in rows
        ]
