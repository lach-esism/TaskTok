"""Snapshot the task-recommender source tree for git-free task reviews."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT_EXCLUDE = {
    ".superpowers",
    "data",
    "reports",
    ".git",
    "node_modules",
}
CACHE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def ignore(directory: str, names: list[str]) -> set[str]:
    is_root = Path(directory).resolve() == Path(".").resolve()
    is_docs = Path(directory).name == "docs"
    excluded = set()
    for name in names:
        if name in CACHE_DIRS:
            excluded.add(name)
        elif is_root and name in ROOT_EXCLUDE:
            excluded.add(name)
        elif is_docs and name == "superpowers":
            excluded.add(name)
    return excluded


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: snapshot.py DEST", file=sys.stderr)
        return 2
    source = Path(".").resolve()
    destination = Path(sys.argv[1]).resolve()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=ignore)
    print(f"snapshot: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
