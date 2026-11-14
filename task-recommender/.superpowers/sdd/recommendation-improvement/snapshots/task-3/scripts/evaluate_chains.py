"""Compare greedy, Beam Search, and MILP chain planners."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.store import Store  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.data.templates import load_templates  # noqa: E402
from app.evaluation_chains import evaluate_planners  # noqa: E402


def main() -> None:
    dataset = generate_dataset()
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    templates = load_templates(
        ROOT / "data" / "chain_templates" / "common_task_chains.json"
    )
    metrics = evaluate_planners(store, templates, n_samples=30)

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase3_chain_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Phase 3 链规划对比",
        "",
        "| 规划器 | 计划覆盖率 | blocked 率 | 平均节点分 | 交接次数 | 无环率 |",
        "|---|---|---|---|---|---|",
    ]
    for name, values in metrics.items():
        lines.append(
            f"| {name} | {values['plan_coverage']:.4f} | "
            f"{values['blocked_rate']:.4f} | "
            f"{values['mean_node_score']:.4f} | "
            f"{values['handoff_count']:.2f} | "
            f"{values['acyclic_rate']:.4f} |"
        )
    (reports / "phase3_chain_metrics.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
