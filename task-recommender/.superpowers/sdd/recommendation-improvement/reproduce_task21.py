"""Regenerate the Task 21 dataset in memory and compare it to the artifact.

Generates at the full required scale with seed 42 and compares task texts,
resume texts, split assignment, assignment statuses and gold labels against the
existing SQLite file. Writes nothing, mutates no source.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.data.large_synthetic import generate_large_dataset  # noqa: E402

DB = ROOT / "data" / "benchmark" / "task_benchmark_large.sqlite"


def digest(values: list[str]) -> str:
    hasher = hashlib.sha256()
    for value in values:
        hasher.update(value.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def main() -> int:
    started = time.perf_counter()
    dataset = generate_large_dataset(
        n_workers=1000, n_tasks=10000, n_assignments=100000, seed=42
    )
    generation_seconds = time.perf_counter() - started

    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        db_tasks = [
            dict(row) for row in connection.execute("SELECT * FROM tasks ORDER BY task_id")
        ]
        db_workers = [
            dict(row) for row in connection.execute("SELECT * FROM workers ORDER BY worker_id")
        ]
        db_assignments = [
            dict(row)
            for row in connection.execute(
                "SELECT assignment_id, task_id, worker_id, status, on_time, rating, "
                "rework, created_at, split FROM assignments ORDER BY assignment_id"
            )
        ]
        db_labels = {
            row["task_id"]: row["gold_worker_id"]
            for row in connection.execute("SELECT task_id, gold_worker_id FROM labels")
        }
        db_splits = {
            row["task_id"]: row["split"]
            for row in connection.execute("SELECT task_id, split FROM splits")
        }
    finally:
        connection.close()

    gen_task_texts = [task["task_text"] for task in dataset.tasks]
    gen_resume_texts = [worker["resume_text"] for worker in dataset.workers]
    db_task_texts = [task["task_text"] for task in db_tasks]
    db_resume_texts = [worker["resume_text"] for worker in db_workers]

    comparisons = {
        "task_text_digest_equal": digest(gen_task_texts) == digest(db_task_texts),
        "resume_text_digest_equal": digest(gen_resume_texts) == digest(db_resume_texts),
        "task_texts_equal": gen_task_texts == db_task_texts,
        "resume_texts_equal": gen_resume_texts == db_resume_texts,
        "splits_equal": dataset.splits == db_splits,
        "labels_equal": {
            task_id: label["gold_worker_id"] for task_id, label in dataset.labels.items()
        }
        == db_labels,
        "assignment_rows_equal": sorted(
            (
                row["assignment_id"],
                row["task_id"],
                row["worker_id"],
                row["status"],
                row["on_time"],
                row["rating"],
                row["rework"],
                row["created_at"],
                row["split"],
            )
            for row in dataset.assignments
        )
        == [
            (
                row["assignment_id"],
                row["task_id"],
                row["worker_id"],
                row["status"],
                row["on_time"],
                row["rating"],
                row["rework"],
                row["created_at"],
                row["split"],
            )
            for row in db_assignments
        ],
        "counts": {
            "workers": (len(dataset.workers), len(db_workers)),
            "tasks": (len(dataset.tasks), len(db_tasks)),
            "assignments": (len(dataset.assignments), len(db_assignments)),
        },
    }
    comparisons["all_equal"] = all(
        value
        for key, value in comparisons.items()
        if key not in ("counts",)
    )
    print(
        json.dumps(
            {
                "generation_seconds": round(generation_seconds, 3),
                "comparisons": comparisons,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if comparisons["all_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
