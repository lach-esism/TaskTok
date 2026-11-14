"""Run 20 rounds x 50 choices: learning vs no-learning accuracy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.store import Store  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.learning_simulation import simulate_learning_rounds  # noqa: E402


def main() -> None:
    dataset = generate_dataset()
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    customer_ids = [
        customer.customer_id for customer in dataset.customers[:20]
    ]
    result = simulate_learning_rounds(
        store,
        customer_ids,
        rounds=20,
        selections_per_round=50,
        candidate_pool=20,
        top_k=5,
        seed=42,
        learning_rate=0.03,
    )

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "learning_rounds.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 20 轮学习 vs 不学习对照实验",
        "",
        "每轮 50 次选择，20 个候选人；学习组用 pairwise hard-negative 更新，",
        "对照组固定初始权重。",
        "",
        "| 轮次 | 学习 Top-1 | 对照 Top-1 | 学习 Top-5 | 对照 Top-5 | 学习 cosine |",
        "|---|---|---|---|---|---|",
    ]
    for index, round_number in enumerate(result["rounds"]):
        lines.append(
            f"| {round_number} | {result['learning_top1'][index]:.4f} | "
            f"{result['baseline_top1'][index]:.4f} | "
            f"{result['learning_top5'][index]:.4f} | "
            f"{result['baseline_top5'][index]:.4f} | "
            f"{result['learning_cosine'][index]:.4f} |"
        )
    (reports / "learning_rounds.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "rounds": len(result["rounds"]),
                "selections_per_round": result["meta"][
                    "selections_per_round"
                ],
                "final_learning_top1": result["learning_top1"][-1],
                "final_baseline_top1": result["baseline_top1"][-1],
                "final_learning_top5": result["learning_top5"][-1],
                "final_baseline_top5": result["baseline_top5"][-1],
                "final_learning_cosine": result["learning_cosine"][-1],
                "final_baseline_cosine": result["baseline_cosine"][-1],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
