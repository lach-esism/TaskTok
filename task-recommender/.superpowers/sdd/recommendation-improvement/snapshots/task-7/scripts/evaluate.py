"""Run Phase 1 offline evaluation and write reports/phase1_metrics.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import (  # noqa: E402
    DEFAULT_N_ASSIGNMENTS,
    DEFAULT_N_TASKS,
    DEFAULT_N_WORKERS,
    DEFAULT_SEED,
)
from app.data.store import Store  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.data.templates import load_templates  # noqa: E402
from app.metrics import evaluate_chains, evaluate_recommender  # noqa: E402
from app.service import RecommendationService  # noqa: E402


def main() -> None:
    dataset = generate_dataset(
        n_workers=DEFAULT_N_WORKERS,
        n_tasks=DEFAULT_N_TASKS,
        n_assignments=DEFAULT_N_ASSIGNMENTS,
        seed=DEFAULT_SEED,
    )
    full_store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    test_store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.test,
        feedback=dataset.feedback,
    )
    templates = load_templates(
        ROOT / "data" / "chain_templates" / "common_task_chains.json"
    )

    service = RecommendationService(full_store)
    metrics = evaluate_recommender(test_store, service, k=10)
    metrics.update(evaluate_chains(full_store, templates, n_samples=50))

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    output = reports / "phase1_metrics.json"
    output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
