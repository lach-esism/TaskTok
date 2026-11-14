"""Re-run the Task 21 sampled evaluation against the existing SQLite artifact.

Read-only with respect to the database; refreshes the two Markdown reports so
they are derived from the current artifact and metadata. Prints the evaluation
result, a metric comparison, and the measured runtime.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app.benchmark.large import evaluate_large  # noqa: E402
from scripts.build_large_benchmark import (  # noqa: E402
    write_eval_report,
    write_stats_report,
)

DB = ROOT / "data" / "benchmark" / "task_benchmark_large.sqlite"
STATS_REPORT = ROOT / "reports" / "large_benchmark_stats.md"
EVAL_REPORT = ROOT / "reports" / "large_benchmark_eval.md"


def load_metadata_stats() -> tuple[dict, dict]:
    import sqlite3

    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata: dict = {}
        stats: dict = {}
        for row in connection.execute("SELECT key, value FROM metadata"):
            key = row["key"]
            value = json.loads(row["value"])
            if key.startswith("stat:"):
                stats[key[len("stat:"):]] = value
            else:
                metadata[key] = value
    finally:
        connection.close()
    return metadata, stats


def main() -> int:
    metadata, stats = load_metadata_stats()
    print(
        json.dumps(
            {
                "db": str(DB),
                "n_workers": metadata.get("n_workers"),
                "n_tasks": metadata.get("n_tasks"),
                "n_assignments": metadata.get("n_assignments"),
                "seed": metadata.get("seed"),
            },
            ensure_ascii=False,
        )
    )

    started = time.perf_counter()
    result = evaluate_large(DB)
    elapsed = time.perf_counter() - started

    dataset_view = SimpleNamespace(stats=stats, metadata=metadata)
    write_stats_report(dataset_view, STATS_REPORT)
    write_eval_report(result, stats, EVAL_REPORT)

    print(json.dumps({"runtime_seconds": round(elapsed, 3), "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
