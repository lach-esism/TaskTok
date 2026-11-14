"""Generate data/ground_truth.csv from the deterministic dataset."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.ground_truth import build_ground_truth  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402


def main() -> None:
    dataset = generate_dataset()
    path = build_ground_truth(dataset, ROOT / "data" / "ground_truth.csv")
    print(path)


if __name__ == "__main__":
    main()
