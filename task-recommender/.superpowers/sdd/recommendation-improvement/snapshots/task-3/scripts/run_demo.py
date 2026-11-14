"""Start the Phase 1 FastAPI demo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
