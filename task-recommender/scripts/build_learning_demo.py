"""Generate the standalone two-sided learning-process demo page.

Usage::

    python scripts/build_learning_demo.py
    python scripts/build_learning_demo.py --rounds 20 --output frontend/learning-demo.html

The page is self-contained: data and rendering code live in one HTML file,
so it can be opened by double-clicking without starting the API server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.learning.demo_data import build_demo_data  # noqa: E402
from app.learning.demo_html import render_demo_html  # noqa: E402

DEFAULT_OUTPUT = ROOT / "frontend" / "learning-demo.html"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the standalone TaskTok learning demo page."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = build_demo_data(seed=args.seed, rounds=args.rounds)
    html = render_demo_html(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")

    worker_end = data["worker"]["rounds"][-1]
    customer_end = data["customer"]["rounds"][-1]
    print(f"wrote {args.output} ({len(html):,} bytes)")
    print(
        "worker: gold rank "
        f"{data['worker']['rounds'][0]['gold_rank']} -> {worker_end['gold_rank']}, "
        f"cosine {worker_end['cosine_after']:.3f}"
    )
    print(
        "customer: gold rank "
        f"{data['customer']['rounds'][0]['gold_rank']} -> {customer_end['gold_rank']}, "
        f"cosine {customer_end['cosine_after']:.3f}"
    )


if __name__ == "__main__":
    main()
