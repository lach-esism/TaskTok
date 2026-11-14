"""Start the TaskTok demo: API + SQLite business database + frontend at /app/.

The database defaults to ``data/tasktok.sqlite`` (seeded on first start).
Set ``TASKTOK_DB`` to use another file, or ``TASKTOK_DB=`` (empty) to run
in memory without a database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402


if __name__ == "__main__":
    os.environ.setdefault("TASKTOK_DB", str(ROOT / "data" / "tasktok.sqlite"))
    port = int(os.environ.get("PORT", "8000"))
    print(f"TaskTok: http://127.0.0.1:{port}/app/  (db: {os.environ['TASKTOK_DB'] or 'memory'})")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        reload=False,
    )
