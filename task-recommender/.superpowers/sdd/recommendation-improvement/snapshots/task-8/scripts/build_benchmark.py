"""Build the 1,000-task natural-language round benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.benchmark.db import build_benchmark_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "benchmark" / "task_benchmark.sqlite"),
    )
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.05)
    args = parser.parse_args()

    summary = build_benchmark_db(
        Path(args.db),
        n_tasks=args.tasks,
        n_workers=args.workers,
        seed=args.seed,
        truth_noise=args.noise,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
