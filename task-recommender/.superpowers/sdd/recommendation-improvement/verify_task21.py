"""Read-only verification of the Task 21 large benchmark artifacts.

Checks the emitted SQLite/JSONL against the acceptance criteria without
regenerating or mutating anything. Exact duplicates use normalized SHA-256;
near duplicates use a 64-bit simhash and an independent 4x16-bit pigeonhole
index (two fingerprints within Hamming distance 3 must share one block).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.benchmark.large import load_large_sqlite  # noqa: E402
from app.data.large_synthetic import (  # noqa: E402
    CATEGORY_CERTS,
    CATEGORY_RESULTS,
    LargeDataset,  # noqa: F401 (import proves module loads)
    simhash64,
)
from app.resume import CATEGORY_PROFILES  # noqa: E402

DB = ROOT / "data" / "benchmark" / "task_benchmark_large.sqlite"
JSONL = ROOT / "data" / "benchmark" / "task_benchmark_large.jsonl"

CJK = re.compile(r"[一-鿿]")
SENTENCE = re.compile(r"[。；，,.;]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def exact_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


class NearDupIndex:
    """Independent 4x16-bit block index; exact for Hamming distance <= 3."""

    def __init__(self) -> None:
        self.blocks = [defaultdict(list) for _ in range(4)]
        self.fingerprints: list[int] = []
        self.collisions = 0
        self.colliding_texts: list[int] = []

    def add(self, text: str, index: int) -> bool:
        fingerprint = simhash64(text)
        for block in range(4):
            value = (fingerprint >> (block * 16)) & 0xFFFF
            for other in self.blocks[block][value]:
                if (fingerprint ^ other).bit_count() <= 3:
                    self.collisions += 1
                    self.colliding_texts.append(index)
                    return False
        for block in range(4):
            value = (fingerprint >> (block * 16)) & 0xFFFF
            self.blocks[block][value].append(fingerprint)
        self.fingerprints.append(fingerprint)
        return True


def text_quality(label: str, texts: list[str]) -> dict:
    lengths = [len(text) for text in texts]
    empty = sum(1 for text in texts if not text.strip())
    no_cjk = sum(1 for text in texts if not CJK.search(text))
    has_sentence = sum(1 for text in texts if SENTENCE.search(text))
    return {
        "count": len(texts),
        "empty": empty,
        "no_cjk": no_cjk,
        "with_sentence_punct": has_sentence,
        "length_min": min(lengths) if lengths else 0,
        "length_mean": round(statistics.mean(lengths), 1) if lengths else 0,
        "length_max": max(lengths) if lengths else 0,
        "label": label,
    }


def near_dup_report(label: str, texts: list[str]) -> dict:
    index = NearDupIndex()
    for position, text in enumerate(texts):
        index.add(text, position)
    n = len(texts)
    return {
        "label": label,
        "count": n,
        "near_dup_collisions": index.collisions,
        "near_dup_rate": round(index.collisions / n, 6) if n else 0.0,
        "distinct_simhashes": len(set(index.fingerprints)),
    }


def main() -> int:
    failures: list[str] = []
    summary: dict = {"db": str(DB), "jsonl": str(JSONL)}

    if not DB.exists() or not JSONL.exists():
        print(json.dumps({"error": "missing artifacts"}, ensure_ascii=False))
        return 1

    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("workers", "tasks", "customers", "assignments", "splits", "labels")
        }
        split_counts = {
            row["split"]: row["n"]
            for row in connection.execute(
                "SELECT split, COUNT(*) AS n FROM splits GROUP BY split"
            )
        }
        assignment_split_counts = {
            row["split"]: row["n"]
            for row in connection.execute(
                "SELECT split, COUNT(*) AS n FROM assignments GROUP BY split"
            )
        }
        status_counts = {
            row["status"]: row["n"]
            for row in connection.execute(
                "SELECT status, COUNT(*) AS n FROM assignments GROUP BY status"
            )
        }
        task_columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
        ]
        worker_columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(workers)")
        ]
        label_columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(labels)")
        ]
        tasks = [dict(row) for row in connection.execute("SELECT * FROM tasks")]
        workers = [dict(row) for row in connection.execute("SELECT * FROM workers")]
        assignments = [
            dict(row)
            for row in connection.execute(
                "SELECT assignment_id, task_id, worker_id, split, status, rating, "
                "on_time, rework FROM assignments"
            )
        ]
        labels = {
            row["task_id"]: row["gold_worker_id"]
            for row in connection.execute("SELECT task_id, gold_worker_id FROM labels")
        }
        label_splits = {
            row["task_id"]: row["split"]
            for row in connection.execute("SELECT task_id, split FROM labels")
        }
        split_map = {
            row["task_id"]: row["split"]
            for row in connection.execute("SELECT task_id, split FROM splits")
        }
        metadata = {}
        for row in connection.execute("SELECT key, value FROM metadata"):
            try:
                metadata[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                metadata[row["key"]] = row["value"]
    finally:
        connection.close()

    # ---- Model-facing loader: train outcomes only ---------------------------
    model_safe = load_large_sqlite(DB)
    model_safe_test_outcome_leaks = 0
    model_safe_train_rows = 0
    for row in model_safe.assignments:
        if row["split"] == "test":
            if (
                row["status"] != "unknown"
                or row["on_time"] is not None
                or row["rating"] is not None
                or row["rework"] is not None
            ):
                model_safe_test_outcome_leaks += 1
        elif row["split"] == "train":
            model_safe_train_rows += 1
            if row["status"] not in {"accepted", "rejected"}:
                model_safe_test_outcome_leaks += 1
    model_safe_stats_metadata = any(
        key.startswith("stat:") for key in model_safe.metadata
    )
    summary["model_safe_loader"] = {
        "labels_empty": model_safe.labels == {},
        "stats_metadata_present": model_safe_stats_metadata,
        "test_outcome_leaks": model_safe_test_outcome_leaks,
        "train_rows": model_safe_train_rows,
        "test_rows": sum(
            1 for row in model_safe.assignments if row["split"] == "test"
        ),
    }
    if not model_safe.labels == {}:
        failures.append("model-safe loader returned labels")
    if model_safe_stats_metadata:
        failures.append("model-safe loader exposed stat: metadata")
    if model_safe_test_outcome_leaks:
        failures.append(
            f"{model_safe_test_outcome_leaks} model-safe test rows expose outcomes"
        )

    # ---- Gold definition check ---------------------------------------------
    status_by_pair = {
        (row["task_id"], row["worker_id"]): row["status"] for row in assignments
    }
    gold_accepted = sum(
        1
        for task_id, gold in labels.items()
        if status_by_pair.get((task_id, gold)) == "accepted"
    )
    gold_acceptance_rate = (
        round(gold_accepted / len(labels), 4) if labels else 0.0
    )

    summary["sqlite_counts"] = counts
    summary["split_counts"] = split_counts
    summary["assignment_split_counts"] = assignment_split_counts
    summary["status_counts"] = status_counts
    summary["schema"] = {
        "tasks": task_columns,
        "workers": worker_columns,
        "labels": label_columns,
    }

    # ---- Scale / split acceptance ------------------------------------------
    if counts["workers"] != 1000:
        failures.append(f"workers={counts['workers']} (expected 1000)")
    if counts["tasks"] != 10000:
        failures.append(f"tasks={counts['tasks']} (expected 10000)")
    if counts["assignments"] != 100000:
        failures.append(f"assignments={counts['assignments']} (expected 100000)")
    if split_counts.get("train") != 8000 or split_counts.get("test") != 2000:
        failures.append(f"split counts {split_counts} (expected 8000/2000)")
    if counts["splits"] != counts["tasks"]:
        failures.append("splits table does not cover every task")
    if counts["labels"] != counts["tasks"]:
        failures.append("labels table does not cover every task")
    if assignment_split_counts.get("train", 0) + assignment_split_counts.get("test", 0) != counts["assignments"]:
        failures.append("assignment split counts do not sum to assignments")

    # ---- Split consistency --------------------------------------------------
    bad_assignment_splits = sum(
        1 for row in assignments if split_map.get(row["task_id"]) != row["split"]
    )
    bad_label_splits = sum(
        1 for task_id, split in label_splits.items() if split_map.get(task_id) != split
    )
    if bad_assignment_splits:
        failures.append(f"{bad_assignment_splits} assignments disagree with task split")
    if bad_label_splits:
        failures.append(f"{bad_label_splits} labels disagree with task split")
    if set(labels) != set(split_map):
        failures.append("label task ids differ from split task ids")

    # ---- Label leakage ------------------------------------------------------
    if "gold_worker_id" in task_columns or "category" in task_columns:
        failures.append("tasks table exposes gold/category columns")
    if "gold_worker_id" not in label_columns:
        failures.append("labels table missing gold_worker_id")
    if "reliability" in worker_columns:
        failures.append("workers table exposes latent reliability")
    for column in ("gold_worker_id", "gold", "label", "is_gold"):
        if column in task_columns:
            failures.append(f"tasks table exposes {column}")
    if not label_columns:
        failures.append("labels table missing")

    # ---- Exact / near duplicates -------------------------------------------
    task_texts = [task["task_text"] for task in tasks]
    resume_texts = [worker["resume_text"] for worker in workers]
    task_titles = [task["title"] for task in tasks]

    task_hashes = [exact_hash(text) for text in task_texts]
    resume_hashes = [exact_hash(text) for text in resume_texts]
    summary["exact_duplicates"] = {
        "tasks": len(task_hashes) - len(set(task_hashes)),
        "resumes": len(resume_hashes) - len(set(resume_hashes)),
        "task_titles": len(task_titles) - len(set(task_titles)),
    }
    if summary["exact_duplicates"]["tasks"] != 0:
        failures.append("task exact duplicates present")
    if summary["exact_duplicates"]["resumes"] != 0:
        failures.append("resume exact duplicates present")
    if summary["exact_duplicates"]["task_titles"] != 0:
        failures.append("task title duplicates present")

    summary["near_duplicates"] = [
        near_dup_report("tasks", task_texts),
        near_dup_report("resumes", resume_texts),
    ]
    for report in summary["near_duplicates"]:
        if report["near_dup_rate"] >= 0.005:
            failures.append(f"{report['label']} near-dup rate >= 0.5%")

    # ---- Natural-language quality ------------------------------------------
    summary["text_quality"] = [
        text_quality("tasks", task_texts),
        text_quality("resumes", resume_texts),
    ]
    for report in summary["text_quality"]:
        if report["empty"] or report["no_cjk"]:
            failures.append(f"{report['label']} has empty or non-CJK texts")

    # ---- Resume category coherence -----------------------------------------
    result_owners: dict[str, set[str]] = defaultdict(set)
    for category, items in CATEGORY_RESULTS.items():
        for item in items:
            result_owners[item].add(category)
    for category, profile in CATEGORY_PROFILES.items():
        for project in profile["projects"]:
            result_owners[project[3]].add(category)
    cert_owners: dict[str, set[str]] = defaultdict(set)
    for category, items in CATEGORY_CERTS.items():
        for item in items:
            cert_owners[item].add(category)
    for category, profile in CATEGORY_PROFILES.items():
        for cert in profile["certifications"]:
            cert_owners[cert].add(category)

    coherence_violations: list[tuple[str, str, str, str]] = []
    for worker in model_safe.workers:
        specialties = worker["specialties"]
        top_category = (
            max(specialties, key=lambda key: (specialties[key], key))
            if specialties
            else "consulting_research"
        )
        text = worker["resume_text"]
        for phrase, owners in result_owners.items():
            if phrase in text and top_category not in owners:
                coherence_violations.append(
                    (worker["worker_id"], top_category, "result", phrase)
                )
        for phrase, owners in cert_owners.items():
            if phrase in text and top_category not in owners:
                coherence_violations.append(
                    (worker["worker_id"], top_category, "cert", phrase)
                )
    summary["resume_coherence"] = {
        "violations": len(coherence_violations),
        "examples": coherence_violations[:5],
    }
    if coherence_violations:
        failures.append(
            f"{len(coherence_violations)} resume category-coherence violations"
        )

    # ---- Assignment quality -------------------------------------------------
    ratings = [row["rating"] for row in assignments if row["rating"] is not None]
    summary["assignments"] = {
        "rated": len(ratings),
        "rating_min": min(ratings) if ratings else None,
        "rating_max": max(ratings) if ratings else None,
        "on_time_rated": sum(1 for row in assignments if row["on_time"] is not None),
        "rework_rated": sum(1 for row in assignments if row["rework"] is not None),
    }
    if ratings and (min(ratings) < 1 or max(ratings) > 5):
        failures.append("ratings outside 1..5")

    # ---- Metadata stats -----------------------------------------------------
    stat_keys = sorted(key for key in metadata if key.startswith("stat:"))
    stats = {
        key[len("stat:"):]: value for key, value in metadata.items() if key.startswith("stat:")
    }
    summary["metadata"] = {
        key: value for key, value in metadata.items() if not key.startswith("stat:")
    }
    summary["stat_keys"] = stat_keys
    summary["distributions"] = {
        "category": stats.get("category_distribution"),
        "industry": stats.get("industry_distribution"),
        "budget": stats.get("budget"),
        "duration_days": stats.get("duration_days"),
        "task_text_length": stats.get("task_text_length"),
        "resume_text_length": stats.get("resume_text_length"),
        "rating_distribution": stats.get("rating_distribution"),
        "on_time_rate": stats.get("on_time_rate"),
        "resume_completeness": stats.get("resume_completeness"),
    }
    summary["recorded_stats"] = {
        key: stats.get(key)
        for key in (
            "n_workers",
            "n_tasks",
            "n_assignments",
            "train_tasks",
            "test_tasks",
            "accepted",
            "rejected",
            "task_exact_duplicates",
            "task_title_duplicates",
            "task_unique_titles",
            "task_near_dup_collisions",
            "task_near_dup_rate",
            "task_near_dup_rejections",
            "resume_exact_duplicates",
            "resume_near_dup_collisions",
            "resume_near_dup_rate",
            "resume_near_dup_rejections",
            "gold_workers",
            "gold_accepted",
            "gold_acceptance_rate",
            "exposure_pool_size",
            "max_gold_share",
            "split_outcomes",
        )
    }

    # ---- JSONL cross-check --------------------------------------------------
    jsonl_counts: Counter = Counter()
    jsonl_bad_label = 0
    jsonl_test_outcome_leaks = 0
    jsonl_meta: dict | None = None
    jsonl_task_texts: list[str] = []
    jsonl_resume_texts: list[str] = []
    with JSONL.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            kind = record.get("type")
            jsonl_counts[kind] += 1
            if kind == "meta":
                jsonl_meta = record
            if "gold_worker_id" in record or "labels" in record:
                jsonl_bad_label += 1
            if kind == "assignment" and record.get("split") == "test":
                if (
                    record.get("status") != "unknown"
                    or record.get("on_time") is not None
                    or record.get("rating") is not None
                    or record.get("rework") is not None
                ):
                    jsonl_test_outcome_leaks += 1
            if kind == "task":
                jsonl_task_texts.append(record.get("task_text", ""))
            elif kind == "worker":
                jsonl_resume_texts.append(record.get("resume_text", ""))
    summary["jsonl_counts"] = dict(jsonl_counts)
    summary["jsonl_bad_label_records"] = jsonl_bad_label
    summary["jsonl_model_safety"] = {
        "meta_has_stats": "stats" in (jsonl_meta or {}),
        "meta_has_stat_keys": any(
            key.startswith("stat:")
            for key in (jsonl_meta or {}).get("metadata", {})
        ),
        "test_outcome_leaks": jsonl_test_outcome_leaks,
        "outcome_policy": (jsonl_meta or {}).get("outcome_policy"),
    }
    if "stats" in (jsonl_meta or {}):
        failures.append("JSONL meta exposes build-time stats")
    if any(
        key.startswith("stat:")
        for key in (jsonl_meta or {}).get("metadata", {})
    ):
        failures.append("JSONL meta exposes stat: keys")
    if jsonl_test_outcome_leaks:
        failures.append(
            f"{jsonl_test_outcome_leaks} JSONL test rows expose outcomes"
        )
    if (jsonl_meta or {}).get("outcome_policy", {}).get("test_split") != "redacted":
        failures.append("JSONL outcome_policy does not redact test outcomes")
    expected_jsonl = {
        "meta": 1,
        "worker": counts["workers"],
        "task": counts["tasks"],
        "customer": counts["customers"],
        "assignment": counts["assignments"],
        "split": counts["splits"],
    }
    if dict(jsonl_counts) != expected_jsonl:
        failures.append(f"JSONL counts {dict(jsonl_counts)} != {expected_jsonl}")
    if jsonl_bad_label:
        failures.append(f"{jsonl_bad_label} JSONL records expose labels")
    if jsonl_task_texts != task_texts:
        failures.append("JSONL task texts differ from SQLite order/content")
    if jsonl_resume_texts != resume_texts:
        failures.append("JSONL resume texts differ from SQLite order/content")

    # ---- Reported stats must match measured counts -------------------------
    task_near = next(
        report for report in summary["near_duplicates"] if report["label"] == "tasks"
    )
    resume_near = next(
        report
        for report in summary["near_duplicates"]
        if report["label"] == "resumes"
    )
    expected_stats = {
        "n_assignments": counts["assignments"],
        "task_exact_duplicates": summary["exact_duplicates"]["tasks"],
        "task_title_duplicates": summary["exact_duplicates"]["task_titles"],
        "task_near_dup_collisions": task_near["near_dup_collisions"],
        "task_near_dup_rate": task_near["near_dup_rate"],
        "resume_exact_duplicates": summary["exact_duplicates"]["resumes"],
        "resume_near_dup_collisions": resume_near["near_dup_collisions"],
        "resume_near_dup_rate": resume_near["near_dup_rate"],
        "gold_accepted": gold_accepted,
        "gold_acceptance_rate": gold_acceptance_rate,
        "exposure_pool_size": (
            counts["assignments"] // counts["tasks"] if counts["tasks"] else 0
        ),
    }
    for key, expected in expected_stats.items():
        if stats.get(key) != expected:
            failures.append(
                f"recorded stat {key}={stats.get(key)!r} != measured {expected!r}"
            )
    split_outcomes = stats.get("split_outcomes") or {}
    for split in ("train", "test"):
        recorded = split_outcomes.get(split, {}).get("assignments")
        if recorded != assignment_split_counts.get(split):
            failures.append(
                f"recorded {split} assignment stat {recorded!r} != "
                f"{assignment_split_counts.get(split)!r}"
            )

    summary["failures"] = failures
    summary["ok"] = not failures
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
