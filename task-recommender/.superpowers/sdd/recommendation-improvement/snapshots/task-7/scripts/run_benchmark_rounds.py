"""Run recommend -> score -> learn -> forget -> repeat."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.benchmark.runner import BenchmarkRoundRunner  # noqa: E402
from app.learning.weights import KEYS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "benchmark" / "task_benchmark.sqlite"),
    )
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    args = parser.parse_args()

    runner = BenchmarkRoundRunner(
        Path(args.db), learning_rate=args.learning_rate
    )
    results = runner.run(rounds=args.rounds)

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "benchmark_rounds.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 1000 任务对答案学习基准",
        "",
        "每轮：清空上一轮推荐缓存 → 重新推荐 → 对答案计算命中率 → 只用训练集学习。",
        "标签表只在对答案和学习阶段读取，推荐器看不到 gold worker。",
        "",
        "| 轮次 | Top-1 | Top-5 | MRR | NDCG@5 | 训练 Top-1 | 测试 Top-1 | 更新数 | 遗忘答案 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in results:
        metrics = item["metrics"]
        lines.append(
            f"| {item['round']} | {metrics['top1']:.4f} | "
            f"{metrics['top5']:.4f} | {metrics['mrr']:.4f} | "
            f"{metrics['ndcg']:.4f} | {metrics['train_top1']:.4f} | "
            f"{metrics['test_top1']:.4f} | {item['updates']} | "
            f"{'是' if item['forgot_previous_answers'] else '否'} |"
        )

    if results:
        first = results[0]["weights_before"]
        last = results[-1]["weights_after"]
        lines.extend(
            [
                "",
                "## 权重变化",
                "",
                "| 维度 | 初始 | 最终 | 变化 |",
                "|---|---|---|---|",
            ]
        )
        for key in KEYS:
            delta = last[key] - first.get(key, 0.0)
            lines.append(
                f"| {key} | {first.get(key, 0):.4f} | {last[key]:.4f} | "
                f"{delta:+.4f} |"
            )

    (reports / "benchmark_rounds.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "rounds": len(results),
                "first": results[0]["metrics"] if results else None,
                "last": results[-1]["metrics"] if results else None,
                "weights": results[-1]["weights_after"] if results else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
