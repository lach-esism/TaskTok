"""Large-benchmark SQLite/JSONL storage and sampled evaluation.

Ground truth (``labels``) is written to its own table and read only by
:func:`evaluate_large`. :func:`load_large_sqlite` returns a model-safe dataset
with an empty ``labels`` mapping so feature/training code cannot read gold
answers.

The evaluator wires a real :class:`app.models.itemcf.ItemCF`:
- the item-item similarity graph is built from **train-split accepted**
  assignments only, and
- the worker history used for scoring is also **train-split only**, so neither
  a held-out test task nor its outcomes can enter a candidate's score. Held-out
  tasks are cold-start items for ItemCF under this strict protocol.

Collaborative scores are normalized across each candidate pool (divide by the
pool maximum) before being combined with the other six features, which closes
the Task 14 deferral ("pass an ItemCF built from benchmark interactions").
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from pathlib import Path

import numpy as np

from app.benchmark.features import FEATURE_KEYS
from app.data.large_synthetic import LargeDataset
from app.learning_simulation import SIM_INITIAL_WEIGHTS
from app.models.itemcf import ItemCF
from app.nlp.classifier import extract_fields, rule_scores
from sklearn.feature_extraction.text import TfidfVectorizer

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    preferred_categories TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    resume_text TEXT NOT NULL,
    skills TEXT NOT NULL,
    specialties TEXT NOT NULL,
    level INTEGER NOT NULL,
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
    task_text TEXT NOT NULL,
    budget REAL NOT NULL,
    deadline TEXT NOT NULL,
    region TEXT NOT NULL,
    remote_ok INTEGER NOT NULL,
    split TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS splits (
    task_id TEXT PRIMARY KEY,
    split TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
    assignment_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    on_time INTEGER,
    rating REAL,
    rework INTEGER,
    created_at TEXT NOT NULL,
    split TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    task_id TEXT PRIMARY KEY,
    gold_worker_id TEXT NOT NULL,
    split TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignments_task ON assignments(task_id);
CREATE INDEX IF NOT EXISTS idx_assignments_worker ON assignments(worker_id);
CREATE INDEX IF NOT EXISTS idx_assignments_split ON assignments(split);
"""


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _redact_test_outcomes(
    assignments: list[dict], include_test_outcomes: bool = False
) -> list[dict]:
    """Return model-facing assignment rows.

    Test-split outcomes are evaluator-only: by default their status/rating/
    on-time/rework fields are redacted. Train-split rows are returned intact.
    The assignment identity, task id, worker id, customer id and split stay
    visible so the row can still act as an exposure/history record.
    """
    rows: list[dict] = []
    for assignment in assignments:
        row = dict(assignment)
        if not include_test_outcomes and row.get("split") == "test":
            row["status"] = "unknown"
            row["on_time"] = None
            row["rating"] = None
            row["rework"] = None
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# SQLite / JSONL storage.
# ---------------------------------------------------------------------------
def build_large_sqlite(dataset: LargeDataset, path: Path | str) -> str:
    """Write the large benchmark to SQLite; labels live in their own table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(SCHEMA)
        for key, value in dataset.metadata.items():
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        for key, value in dataset.stats.items():
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                (f"stat:{key}", json.dumps(value, ensure_ascii=False)),
            )
        connection.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?)",
            [
                (
                    customer["customer_id"],
                    customer["name"],
                    customer["region"],
                    json.dumps(customer["preferred_categories"], ensure_ascii=False),
                )
                for customer in dataset.customers
            ],
        )
        connection.executemany(
            "INSERT INTO workers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    worker["worker_id"],
                    worker["name"],
                    worker["resume_text"],
                    json.dumps(worker["skills"], ensure_ascii=False),
                    json.dumps(worker["specialties"], ensure_ascii=False),
                    worker["level"],
                    worker["rating"],
                    worker["completed"],
                    worker["on_time_rate"],
                    worker["rework_rate"],
                    worker["capacity_hours"],
                    worker["current_load_hours"],
                    worker["region"],
                    worker["remote_ok"],
                    json.dumps(worker["preferred_categories"], ensure_ascii=False),
                )
                for worker in dataset.workers
            ],
        )
        connection.executemany(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    task["task_id"],
                    task["customer_id"],
                    task["title"],
                    task["task_text"],
                    task["budget"],
                    task["deadline"],
                    task["region"],
                    task["remote_ok"],
                    task["split"],
                )
                for task in dataset.tasks
            ],
        )
        connection.executemany(
            "INSERT INTO splits VALUES (?, ?)",
            [(task_id, split) for task_id, split in dataset.splits.items()],
        )
        connection.executemany(
            "INSERT INTO assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    assignment["assignment_id"],
                    assignment["task_id"],
                    assignment["worker_id"],
                    assignment["customer_id"],
                    assignment["status"],
                    assignment["on_time"],
                    assignment["rating"],
                    assignment["rework"],
                    assignment["created_at"],
                    assignment["split"],
                )
                for assignment in dataset.assignments
            ],
        )
        connection.executemany(
            "INSERT INTO labels VALUES (?, ?, ?)",
            [
                (
                    task_id,
                    label["gold_worker_id"],
                    label["split"],
                )
                for task_id, label in dataset.labels.items()
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return str(path)


def load_large_sqlite(
    path: Path | str, include_test_outcomes: bool = False
) -> LargeDataset:
    """Load model-safe tables; labels and build-time stats are not returned.

    Test-split assignment outcomes are redacted unless
    ``include_test_outcomes=True``. The raw SQLite database is the evaluator
    artifact; this loader is the model-facing view.
    """
    path = Path(path)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        metadata_rows = connection.execute(
            "SELECT key, value FROM metadata"
        ).fetchall()
        metadata: dict = {}
        for row in metadata_rows:
            if row["key"].startswith("stat:"):
                # Build-time statistics include all-split assignment outcomes.
                # They are report/evaluator material, not model-facing input.
                continue
            try:
                metadata[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                metadata[row["key"]] = row["value"]

        customers = [
            {
                **dict(row),
                "preferred_categories": json.loads(row["preferred_categories"]),
            }
            for row in connection.execute("SELECT * FROM customers").fetchall()
        ]
        workers = [
            {
                **dict(row),
                "skills": json.loads(row["skills"]),
                "specialties": json.loads(row["specialties"]),
                "preferred_categories": json.loads(row["preferred_categories"]),
            }
            for row in connection.execute("SELECT * FROM workers").fetchall()
        ]
        tasks = [dict(row) for row in connection.execute("SELECT * FROM tasks").fetchall()]
        assignments = _redact_test_outcomes(
            [
                dict(row)
                for row in connection.execute("SELECT * FROM assignments").fetchall()
            ],
            include_test_outcomes=include_test_outcomes,
        )
        splits = {
            row["task_id"]: row["split"]
            for row in connection.execute("SELECT * FROM splits").fetchall()
        }
    finally:
        connection.close()
    return LargeDataset(
        workers=workers,
        tasks=tasks,
        customers=customers,
        assignments=assignments,
        splits=splits,
        metadata=metadata,
        stats={},
        labels={},
    )


def export_large_jsonl(
    dataset: LargeDataset,
    path: Path | str,
    include_test_outcomes: bool = False,
) -> str:
    """Export model-safe records as newline-delimited JSON.

    No labels are written. Test-split assignment outcomes are redacted unless
    ``include_test_outcomes=True``; build-time statistics (which aggregate
    test outcomes) are not written to the model-facing JSONL. The stats report
    is written separately by the build script.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    assignments = _redact_test_outcomes(
        dataset.assignments, include_test_outcomes=include_test_outcomes
    )
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "meta",
                    "metadata": dataset.metadata,
                    "outcome_policy": {
                        "test_split": (
                            "included" if include_test_outcomes else "redacted"
                        ),
                        "train_split": "full",
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        for worker in dataset.workers:
            handle.write(json.dumps({"type": "worker", **worker}, ensure_ascii=False) + "\n")
        for task in dataset.tasks:
            handle.write(json.dumps({"type": "task", **task}, ensure_ascii=False) + "\n")
        for customer in dataset.customers:
            handle.write(json.dumps({"type": "customer", **customer}, ensure_ascii=False) + "\n")
        for assignment in assignments:
            handle.write(json.dumps({"type": "assignment", **assignment}, ensure_ascii=False) + "\n")
        for task_id, split in dataset.splits.items():
            handle.write(
                json.dumps(
                    {"type": "split", "task_id": task_id, "split": split},
                    ensure_ascii=False,
                )
                + "\n"
            )
    return str(path)


# ---------------------------------------------------------------------------
# Evaluator-only label access (never used by feature/training code).
# ---------------------------------------------------------------------------
class LargeRepository:
    """Reads model-safe tables and (evaluator-only) labels separately."""

    def __init__(self, db_path: Path | str) -> None:
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
                "specialties": json.loads(row["specialties"]),
                "preferred_categories": json.loads(row["preferred_categories"]),
            }
            for row in rows
        ]

    def load_tasks(self) -> list[dict]:
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM tasks").fetchall()
            ]

    def load_customers(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM customers").fetchall()
        return [
            {
                **dict(row),
                "preferred_categories": json.loads(row["preferred_categories"]),
            }
            for row in rows
        ]

    def load_assignments(self) -> list[dict]:
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM assignments").fetchall()
            ]

    def load_splits(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT task_id, split FROM splits").fetchall()
        return {row["task_id"]: row["split"] for row in rows}

    def load_labels(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT task_id, gold_worker_id FROM labels"
            ).fetchall()
        return {row["task_id"]: row["gold_worker_id"] for row in rows}

    def load_metadata(self) -> dict:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        metadata: dict = {}
        for row in rows:
            try:
                metadata[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                metadata[row["key"]] = row["value"]
        return metadata


# ---------------------------------------------------------------------------
# ItemCF wiring (Task 14 deferral closure).
# ---------------------------------------------------------------------------
def build_itemcf(assignments: list[dict], split: str | None = None) -> ItemCF:
    """Build a real ItemCF from accepted assignments (optionally one split)."""
    interactions: list[tuple[str, str, float]] = []
    for assignment in assignments:
        if assignment["status"] != "accepted":
            continue
        if split is not None and assignment["split"] != split:
            continue
        weight = float(assignment["rating"]) if assignment["rating"] is not None else 1.0
        interactions.append(
            (assignment["worker_id"], assignment["task_id"], weight)
        )
    return ItemCF(interactions)


def item_similarity(itemcf: ItemCF, task_a: str, task_b: str) -> float:
    """Cosine-with-shrinkage similarity between two tasks (ItemCF math)."""
    users_a = itemcf.item_users.get(task_a, {})
    users_b = itemcf.item_users.get(task_b, {})
    common = set(users_a) & set(users_b)
    if not common:
        return 0.0
    cooc = sum(users_a[user] * users_b[user] for user in common)
    norm_a = sum(users_a.values())
    norm_b = sum(users_b.values())
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return cooc / (math.sqrt(norm_a * norm_b) + itemcf.shrinkage)


def pool_normalize(raw: dict[str, float]) -> dict[str, float]:
    """Normalize raw scores across a candidate pool by the pool maximum."""
    if not raw:
        return {}
    maximum = max(raw.values())
    if maximum <= 0:
        return {key: 0.0 for key in raw}
    return {key: max(0.0, value) / maximum for key, value in raw.items()}


def collaborative_scores(
    sim_itemcf: ItemCF,
    history_itemcf: ItemCF,
    task_id: str,
    worker_ids: list[str],
) -> dict[str, float]:
    """ItemCF score per worker using train-only history, then raw scores.

    ``sim_itemcf`` provides the task-task similarity graph; ``history_itemcf``
    provides each worker's train-only interaction history.
    """
    scores: dict[str, float] = {}
    for worker_id in worker_ids:
        history = history_itemcf.user_items.get(worker_id, {})
        if not history:
            scores[worker_id] = 0.0
            continue
        numerator = 0.0
        denominator = 0.0
        for other_task, weight in history.items():
            similarity = item_similarity(sim_itemcf, task_id, other_task)
            numerator += similarity * weight
            denominator += abs(similarity)
        scores[worker_id] = max(0.0, numerator / max(1.0, denominator))
    return scores


# ---------------------------------------------------------------------------
# Feature builder (mirrors app.benchmark.features without a growing cache).
# ---------------------------------------------------------------------------
class LargeFeatureBuilder:
    """Seven observable features for one task-worker pair.

    When ``train_task_ids`` is supplied the TF-IDF vectorizer is fit on worker
    resumes plus **train-split task text only**; test task text is transformed
    with the frozen vocabulary. This is the strict protocol used by
    :func:`evaluate_large`. Passing ``train_task_ids=None`` retains the old
    transductive behaviour (fit on train + test text) and is documented as
    such for callers that explicitly want it.
    """

    def __init__(
        self,
        workers: list[dict],
        tasks: list[dict],
        customers: list[dict],
        train_task_ids: list[str] | None = None,
    ) -> None:
        self.workers = workers
        self.tasks = tasks
        self.worker_index = {
            worker["worker_id"]: index for index, worker in enumerate(workers)
        }
        self.task_index = {
            task["task_id"]: index for index, task in enumerate(tasks)
        }
        self.customer_by_id = {
            customer["customer_id"]: customer for customer in customers
        }
        self.train_task_ids = (
            set(train_task_ids) if train_task_ids is not None else None
        )
        self.transductive = train_task_ids is None
        if self.train_task_ids is None:
            fit_texts = [worker["resume_text"] for worker in workers] + [
                task["task_text"] for task in tasks
            ]
        else:
            fit_texts = [worker["resume_text"] for worker in workers] + [
                task["task_text"]
                for task in tasks
                if task["task_id"] in self.train_task_ids
            ]
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=1,
            sublinear_tf=True,
        )
        self.vectorizer.fit(fit_texts)
        self.worker_matrix = self.vectorizer.transform(
            [worker["resume_text"] for worker in workers]
        )
        self.task_matrix = self.vectorizer.transform(
            [task["task_text"] for task in tasks]
        )
        self.similarity = (
            self.task_matrix @ self.worker_matrix.T
        ).toarray().astype(np.float32)

        self.task_categories: dict[str, str] = {}
        self.task_skills: dict[str, set[str]] = {}
        for task in tasks:
            scores = rule_scores(task["task_text"])
            self.task_categories[task["task_id"]] = max(scores, key=scores.get)
            self.task_skills[task["task_id"]] = set(
                extract_fields(task["task_text"])["skills"]
            )

    def features(self, task_id: str, worker_id: str) -> dict[str, float]:
        task_index = self.task_index[task_id]
        worker_index = self.worker_index[worker_id]
        task = self.tasks[task_index]
        worker = self.workers[worker_index]
        category = self.task_categories[task_id]

        task_skills = self.task_skills[task_id]
        worker_skills = worker["skills"]
        if task_skills:
            skill = sum(
                min(worker_skills.get(name, 0), 4) / 4.0
                for name in task_skills
            ) / len(task_skills)
        else:
            skill = 0.4

        capacity = max(float(worker["capacity_hours"]), 1.0)
        load = 1.0 - float(worker["current_load_hours"]) / capacity
        preference = float(
            worker.get("preferred_categories", {}).get(category, 0.2)
        )
        customer = self.customer_by_id.get(task["customer_id"], {})
        customer_preference = float(
            customer.get("preferred_categories", {}).get(category, 0.2)
        )

        return {
            "reputation": _clamp(
                0.7 * float(worker["rating"]) / 5.0
                + 0.3 * float(worker["on_time_rate"])
            ),
            "skill": _clamp(skill),
            "expertise": _clamp(float(self.similarity[task_index, worker_index])),
            "collaborative": 0.0,
            "preference": _clamp(preference),
            "load": _clamp(load),
            "customer_preference": _clamp(customer_preference),
        }


# ---------------------------------------------------------------------------
# Sampled evaluation.
# ---------------------------------------------------------------------------
def _metric_for_rank(rank: int) -> tuple[float, float, float, float]:
    top1 = 1.0 if rank == 0 else 0.0
    top5 = 1.0 if rank < 5 else 0.0
    mrr = 1.0 / (rank + 1)
    ndcg = 1.0 / math.log2(rank + 2) if rank < 5 else 0.0
    return top1, top5, mrr, ndcg


def _collaborative_matrix(
    sim_itemcf: ItemCF,
    history_itemcf: ItemCF,
    test_task_ids: list[str],
    train_task_ids: list[str],
    worker_index: dict[str, int],
) -> np.ndarray:
    """Raw ItemCF scores for test tasks x workers, computed with numpy.

    Worker history is train-only; the similarity graph is ``sim_itemcf``.
    """
    n_workers = len(worker_index)
    n_train = len(train_task_ids)
    train_task_index = {
        task_id: index for index, task_id in enumerate(train_task_ids)
    }

    user_items = history_itemcf.user_items
    history_matrix = np.zeros((n_workers, n_train), dtype=np.float32)
    for worker_id, history in user_items.items():
        row = worker_index.get(worker_id)
        if row is None:
            continue
        for other_task, weight in history.items():
            column = train_task_index.get(other_task)
            if column is not None:
                history_matrix[row, column] = weight

    similarity_matrix = np.zeros((len(test_task_ids), n_train), dtype=np.float32)
    cache: dict[tuple[str, str], float] = {}
    for test_row, test_task in enumerate(test_task_ids):
        for user in sim_itemcf.item_users.get(test_task, {}):
            for other_task in user_items.get(user, {}):
                if other_task not in train_task_index:
                    continue
                key = (test_task, other_task)
                if key not in cache:
                    cache[key] = item_similarity(sim_itemcf, test_task, other_task)
                column = train_task_index[other_task]
                similarity_matrix[test_row, column] = cache[key]

    numerator = similarity_matrix @ history_matrix.T
    denominator = np.abs(similarity_matrix) @ (history_matrix > 0).astype(
        np.float32
    ).T
    denominator = np.maximum(denominator, 1.0)
    return np.maximum(numerator, 0.0) / denominator


def _interaction_splits(assignments: list[dict], itemcf: ItemCF) -> list[str]:
    """Derive the split set actually represented in an ItemCF graph.

    The ItemCF object stores only weights, so map each (worker, task) edge back
    to its assignment row. This keeps ``history_is_train_only`` an observed
    property of the data rather than a hard-coded claim.
    """
    accepted_splits = {
        (row["worker_id"], row["task_id"]): row["split"]
        for row in assignments
        if row["status"] == "accepted"
    }
    splits: set[str] = set()
    for worker_id, history in itemcf.user_items.items():
        for task_id in history:
            split = accepted_splits.get((worker_id, task_id))
            if split is not None:
                splits.add(split)
    return sorted(splits)


def _mean_std(values: list[float]) -> dict:
    return {
        "mean": round(float(np.mean(values)), 4),
        "std": round(float(np.std(values)), 4),
    }


def evaluate_large(
    path: Path | str,
    test_tasks: int = 500,
    candidates: int = 200,
    seeds: tuple[int, ...] = (42, 43, 44, 45, 46),
) -> dict:
    """Sampled evaluation of the large benchmark under a strict protocol.

    ``test_tasks`` test tasks are sampled; each is ranked against a candidate
    pool of ``candidates`` workers (always including the gold worker). The
    ItemCF similarity graph and worker history are **train-split only**, so a
    held-out task is a cold-start item and its outcomes cannot enter any score.
    Collaborative scores are normalized across the candidate pool.

    A feature-only baseline (the same scoring without the collaborative term)
    and an analytical uniform-random baseline are reported alongside the main
    metrics.
    """
    repository = LargeRepository(path)
    workers = repository.load_workers()
    tasks = repository.load_tasks()
    customers = repository.load_customers()
    assignments = repository.load_assignments()
    splits = repository.load_splits()
    labels = repository.load_labels()
    metadata = repository.load_metadata()

    test_task_ids = [
        task["task_id"] for task in tasks if splits.get(task["task_id"]) == "test"
    ]
    task_rng = random.Random(42)
    sampled_tasks = sorted(
        task_rng.sample(test_task_ids, k=min(test_tasks, len(test_task_ids)))
    )
    train_task_ids = [
        task["task_id"] for task in tasks if splits.get(task["task_id"]) == "train"
    ]

    sim_itemcf = build_itemcf(assignments, split="train")
    history_itemcf = build_itemcf(assignments, split="train")
    worker_index = {worker["worker_id"]: i for i, worker in enumerate(workers)}

    similarity_splits = _interaction_splits(assignments, sim_itemcf)
    history_splits = _interaction_splits(assignments, history_itemcf)
    accepted_total = sum(1 for row in assignments if row["status"] == "accepted")
    test_accepted = sum(
        1
        for row in assignments
        if row["status"] == "accepted" and row["split"] == "test"
    )

    collaborative = _collaborative_matrix(
        sim_itemcf,
        history_itemcf,
        sampled_tasks,
        train_task_ids,
        worker_index,
    )
    sampled_index = {task_id: i for i, task_id in enumerate(sampled_tasks)}

    builder = LargeFeatureBuilder(
        workers, tasks, customers, train_task_ids=train_task_ids
    )
    weights = dict(SIM_INITIAL_WEIGHTS)
    metric_names = ("top1", "top5", "mrr", "ndcg")

    per_seed: list[dict] = []
    aggregate = {name: [] for name in metric_names}
    baseline_aggregate = {name: [] for name in metric_names}
    nonzero_collaborative = 0
    total_candidates = 0

    for seed in seeds:
        rng = random.Random(seed)
        full_sums = {name: 0.0 for name in metric_names}
        baseline_sums = {name: 0.0 for name in metric_names}
        for task_id in sampled_tasks:
            gold = labels[task_id]
            distractors = [w for w in worker_index if w != gold]
            pool = [gold] + rng.sample(
                distractors, k=min(candidates - 1, len(distractors))
            )
            collab_row = collaborative[sampled_index[task_id]]
            raw_collab = {
                worker_id: float(collab_row[worker_index[worker_id]])
                for worker_id in pool
            }
            collab_norm = pool_normalize(raw_collab)
            for worker_id in raw_collab:
                if raw_collab[worker_id] > 0:
                    nonzero_collaborative += 1
            total_candidates += len(pool)

            full_scored: list[tuple[str, float]] = []
            baseline_scored: list[tuple[str, float]] = []
            for worker_id in pool:
                features = builder.features(task_id, worker_id)
                features["collaborative"] = collab_norm.get(worker_id, 0.0)
                full_score = sum(
                    weights[key] * features.get(key, 0.0)
                    for key in FEATURE_KEYS
                )
                baseline_score = sum(
                    weights[key] * features.get(key, 0.0)
                    for key in FEATURE_KEYS
                    if key != "collaborative"
                )
                full_scored.append((worker_id, full_score))
                baseline_scored.append((worker_id, baseline_score))

            full_scored.sort(key=lambda item: (-item[1], item[0]))
            baseline_scored.sort(key=lambda item: (-item[1], item[0]))
            full_rank = [worker_id for worker_id, _ in full_scored].index(gold)
            baseline_rank = [
                worker_id for worker_id, _ in baseline_scored
            ].index(gold)
            for name, value in zip(metric_names, _metric_for_rank(full_rank)):
                full_sums[name] += value
            for name, value in zip(
                metric_names, _metric_for_rank(baseline_rank)
            ):
                baseline_sums[name] += value

        total = len(sampled_tasks)
        seed_metrics = {
            name: round(full_sums[name] / total, 4) for name in metric_names
        }
        seed_baseline = {
            name: round(baseline_sums[name] / total, 4)
            for name in metric_names
        }
        per_seed.append({"seed": seed, **seed_metrics})
        for name in metric_names:
            aggregate[name].append(seed_metrics[name])
            baseline_aggregate[name].append(seed_baseline[name])

    metrics = {name: _mean_std(values) for name, values in aggregate.items()}
    feature_only = {
        name: _mean_std(values) for name, values in baseline_aggregate.items()
    }
    exposure_pool_size = (
        len(assignments) // len(tasks) if tasks else 0
    )
    if "stat:exposure_pool_size" in metadata:
        exposure_pool_size = int(metadata["stat:exposure_pool_size"])

    return {
        "db_path": str(path),
        "n_workers": len(workers),
        "n_tasks": len(tasks),
        "n_test_tasks_available": len(test_task_ids),
        "sampled_test_tasks": len(sampled_tasks),
        "candidates": candidates,
        "seeds": list(seeds),
        "metrics": metrics,
        "per_seed": per_seed,
        "baselines": {
            "feature_only": feature_only,
            "random": {
                "top1": round(1.0 / candidates, 6),
                "top5": round(min(5, candidates) / candidates, 6),
                "note": "analytical uniform ranking over the candidate pool",
            },
        },
        "protocol": {
            "eval_split": "test",
            "similarity_graph": "train-split accepted assignments only",
            "worker_history": "train-split accepted assignments only",
            "candidate_pool": f"gold + {candidates - 1} random workers",
            "gold_definition": "latent-best worker in the exposure pool",
            "exposure_pool_size": exposure_pool_size,
            "feature_weights": "SIM_INITIAL_WEIGHTS",
        },
        "itemcf": {
            "similarity_interactions": sum(
                len(history) for history in sim_itemcf.user_items.values()
            ),
            "history_interactions": sum(
                len(history) for history in history_itemcf.user_items.values()
            ),
            "similarity_splits": similarity_splits,
            "history_splits": history_splits,
            "similarity_is_train_only": similarity_splits == ["train"],
            "history_is_train_only": history_splits == ["train"],
            "accepted_interactions_total": accepted_total,
            "excluded_test_accepted_interactions": test_accepted,
            "pool_normalized": True,
        },
        "collaborative_nonzero_rate": round(
            nonzero_collaborative / max(1, total_candidates), 4
        ),
    }
