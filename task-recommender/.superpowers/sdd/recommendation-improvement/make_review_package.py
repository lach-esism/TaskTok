"""Build a unified-diff review package without a git repository.

Usage: make_review_package.py BASE_DIR HEAD_DIR OUTFILE
"""

from __future__ import annotations

import difflib
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


def files(root: Path) -> dict[Path, Path]:
    result: dict[Path, Path] = {}
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in ROOT_EXCLUDE:
            continue
        if relative.parts[:2] == ("docs", "superpowers"):
            continue
        if any(part in CACHE_DIRS for part in relative.parts):
            continue
        result[relative] = path
    return result


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: make_review_package.py BASE_DIR HEAD_DIR OUTFILE", file=sys.stderr)
        return 2
    base = Path(sys.argv[1]).resolve()
    head = Path(sys.argv[2]).resolve()
    out = Path(sys.argv[3]).resolve()
    base_files = files(base)
    head_files = files(head)
    all_relative = sorted(set(base_files) | set(head_files))

    lines: list[str] = [
        f"# Review package: {base} -> {head}\n",
        "\n",
        "## Files changed\n",
    ]
    changed: list[str] = []
    for relative in all_relative:
        before = base_files.get(relative)
        after = head_files.get(relative)
        if before is None:
            changed.append(f"ADDED   {relative}\n")
        elif after is None:
            changed.append(f"DELETED {relative}\n")
        elif before.read_bytes() != after.read_bytes():
            changed.append(f"CHANGED {relative}\n")
    lines.extend(changed or ["(none)\n"])
    lines.extend(["\n", "## Diff\n", "\n"])

    for relative in all_relative:
        before = base_files.get(relative)
        after = head_files.get(relative)
        if before is not None and after is not None and before.read_bytes() == after.read_bytes():
            continue
        old_lines = read_lines(before) if before is not None else []
        new_lines = read_lines(after) if after is not None else []
        lines.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                n=10,
            )
        )
        lines.append("\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {out}: {len(changed)} changed files, {out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
