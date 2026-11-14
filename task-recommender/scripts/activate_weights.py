"""Create a WeightStore version from a raw weight JSON and activate it.

``scripts/tune_weights.py`` writes ``data/weights/weights_choice.json`` but the
serving app reads the active WeightStore version. This explicit activation step
turns the tuned JSON into a normal versioned record (with prior, sample count,
source, and changelog entry) and points ``active.json`` at it.

Usage::

    python scripts/activate_weights.py \
        --input data/weights/weights_choice.json \
        --source choice-tuned

The input may be a bare seven-key mapping or a WeightStore payload containing
a ``weights`` object.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DEFAULT_WEIGHTS  # noqa: E402
from app.versioning import WeightStore  # noqa: E402


def load_weights(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("weights"), dict):
        payload = payload["weights"]
    if not isinstance(payload, dict) or not payload:
        raise ValueError("weights JSON must be a non-empty object")
    return {str(key): float(value) for key, value in payload.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Version and activate a seven-key weight JSON file."
    )
    parser.add_argument(
        "--input",
        default=str(ROOT / "data" / "weights" / "weights_choice.json"),
        help="raw weights JSON (default: weights_choice.json)",
    )
    parser.add_argument(
        "--weights-dir",
        default=str(ROOT / "data" / "weights"),
        help="WeightStore directory",
    )
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--source", default="choice-tuned")
    args = parser.parse_args(argv)

    try:
        weights = load_weights(Path(args.input))
    except (OSError, ValueError) as error:
        print(f"error: cannot load weights: {error}", file=sys.stderr)
        return 2

    store = WeightStore(Path(args.weights_dir), prior=DEFAULT_WEIGHTS)
    try:
        version = store.create(
            weights,
            sample_count=args.sample_count,
            source=args.source,
        )
    except ValueError as error:
        print(f"error: invalid weights: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "active_version": version.version,
                "weights": version.weights,
                "source": version.source,
                "sample_count": version.sample_count,
                "weights_dir": str(Path(args.weights_dir).resolve()),
                "changelog": store.changelog()[-1],
                "active": asdict(store.active()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
