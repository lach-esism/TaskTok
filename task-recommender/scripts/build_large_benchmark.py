"""Build the large natural-language benchmark and run the sampled evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.benchmark.large import (  # noqa: E402
    build_large_sqlite,
    evaluate_large,
    export_large_jsonl,
)
from app.data.large_synthetic import generate_large_dataset  # noqa: E402

DEFAULT_DB = ROOT / "data" / "benchmark" / "task_benchmark_large.sqlite"
DEFAULT_JSONL = ROOT / "data" / "benchmark" / "task_benchmark_large.jsonl"
DEFAULT_STATS = ROOT / "reports" / "large_benchmark_stats.md"
DEFAULT_EVAL = ROOT / "reports" / "large_benchmark_eval.md"


def _table(rows: list[tuple[str, str]]) -> str:
    lines = ["| item | value |", "| --- | --- |"]
    lines.extend(f"| {key} | {value} |" for key, value in rows)
    return "\n".join(lines)


def write_stats_report(dataset, path: Path) -> Path:
    stats = dataset.stats
    lines: list[str] = []
    lines.append("# Large Benchmark — Data Quality & Statistics\n")
    lines.append(
        _table(
            [
                ("workers", str(stats["n_workers"])),
                ("tasks", str(stats["n_tasks"])),
                ("customers", str(stats["n_customers"])),
                ("assignments", str(stats["n_assignments"])),
                ("train tasks", str(stats["train_tasks"])),
                ("test tasks", str(stats["test_tasks"])),
                ("accepted", str(stats["accepted"])),
                ("rejected", str(stats["rejected"])),
                ("scheme", dataset.metadata.get("scheme", "E")),
                ("seed", str(dataset.metadata.get("seed"))),
            ]
        )
    )

    lines.append("\n## Duplicate checks (computed from the emitted corpus)\n")
    lines.append(
        _table(
            [
                ("task exact duplicates", str(stats["task_exact_duplicates"])),
                ("task title duplicates", str(stats.get("task_title_duplicates", 0))),
                ("task unique titles", f"{stats['task_unique_titles']} / {stats['n_tasks']}"),
                ("task near-dup collisions", str(stats.get("task_near_dup_collisions", 0))),
                ("task near-dup rate", f"{stats['task_near_dup_rate']:.4%}"),
                ("task near-dup resamples", str(stats["task_near_dup_rejections"])),
                ("resume exact duplicates", str(stats["resume_exact_duplicates"])),
                ("resume near-dup collisions", str(stats.get("resume_near_dup_collisions", 0))),
                ("resume near-dup rate", f"{stats['resume_near_dup_rate']:.4%}"),
                ("resume near-dup resamples", str(stats["resume_near_dup_rejections"])),
            ]
        )
    )
    lines.append(
        "\nExact duplicates use normalized SHA-256; title duplicates use the "
        "normalized title set; near-duplicates use 64-bit simhash with Hamming "
        "distance <= 3. Exact/title/near counters are recomputed from the "
        "emitted texts, while the resample counters record generator retries."
    )

    lines.append("\n## Category distribution\n")
    lines.append(_table([(key, str(value)) for key, value in stats["category_distribution"].items()]))

    lines.append("\n## Industry distribution\n")
    lines.append(_table([(key, str(value)) for key, value in stats["industry_distribution"].items()]))

    lines.append("\n## Budget (midpoint, CNY)\n")
    budget = stats["budget"]
    lines.append(
        _table(
            [
                ("min", f"{budget['min']:,.0f}"),
                ("mean", f"{budget['mean']:,.0f}"),
                ("max", f"{budget['max']:,.0f}"),
            ]
        )
    )

    lines.append("\n## Duration (days)\n")
    duration = stats["duration_days"]
    lines.append(
        _table(
            [
                ("min", str(duration["min"])),
                ("mean", f"{duration['mean']:.1f}"),
                ("max", str(duration["max"])),
            ]
        )
    )

    lines.append("\n## Text lengths (characters)\n")
    task_len = stats["task_text_length"]
    resume_len = stats["resume_text_length"]
    lines.append(
        _table(
            [
                ("task_text min/mean/max", f"{task_len['min']} / {task_len['mean']} / {task_len['max']}"),
                ("resume_text min/mean/max", f"{resume_len['min']} / {resume_len['mean']} / {resume_len['max']}"),
            ]
        )
    )

    lines.append("\n## Resume completeness (fraction of resumes containing each section)\n")
    lines.append(
        _table(
            [
                (marker, f"{value:.1%}")
                for marker, value in stats["resume_completeness"].items()
            ]
        )
    )

    lines.append("\n## Assignment outcomes\n")
    lines.append(
        _table(
            [
                ("rating distribution", json.dumps(stats["rating_distribution"], ensure_ascii=False)),
                ("on-time rate", f"{stats['on_time_rate']:.2%}"),
            ]
        )
    )

    split_outcomes = stats.get("split_outcomes", {})
    if split_outcomes:
        lines.append("\n## Split outcomes\n")
        lines.append(
            "| split | assignments | accepted | rejected | mean rating | on-time |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for split in ("train", "test"):
            outcome = split_outcomes.get(split, {})
            lines.append(
                f"| {split} | {outcome.get('assignments', 0)} | "
                f"{outcome.get('accepted', 0)} | {outcome.get('rejected', 0)} | "
                f"{outcome.get('mean_rating', 0)} | "
                f"{outcome.get('on_time_rate', 0):.2%} |"
            )

    lines.append("\n## Gold definition\n")
    lines.append(
        _table(
            [
                (
                    "definition",
                    "latent-best worker (argmax DGP true-match) in the task's exposure pool",
                ),
                ("exposure pool size", str(stats.get("exposure_pool_size", "n/a"))),
                ("distinct gold workers", str(stats["gold_workers"])),
                (
                    "gold accepted the task",
                    f"{stats.get('gold_accepted', 0)} / {stats['n_tasks']} "
                    f"({stats.get('gold_acceptance_rate', 0):.2%})",
                ),
                ("max gold share", f"{stats['max_gold_share']:.2%}"),
            ]
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_eval_report(result: dict, stats: dict, path: Path) -> Path:
    metrics = result["metrics"]
    lines: list[str] = []
    lines.append("# Large Benchmark — Sampled Evaluation\n")
    lines.append(
        _table(
            [
                ("sampled test tasks", str(result["sampled_test_tasks"])),
                ("candidates per task", str(result["candidates"])),
                ("seeds", ", ".join(str(seed) for seed in result["seeds"])),
                ("workers", str(result["n_workers"])),
                ("tasks", str(result["n_tasks"])),
            ]
        )
    )

    lines.append("\n## Protocol\n")
    protocol = result.get("protocol", {})
    lines.append(
        _table(
            [
                ("eval split", protocol.get("eval_split", "test")),
                (
                    "similarity graph",
                    protocol.get(
                        "similarity_graph", "train-split accepted assignments only"
                    ),
                ),
                (
                    "worker history",
                    protocol.get(
                        "worker_history", "train-split accepted assignments only"
                    ),
                ),
                (
                    "candidate pool",
                    protocol.get(
                        "candidate_pool",
                        f"gold + {result['candidates'] - 1} random workers",
                    ),
                ),
                (
                    "gold definition",
                    protocol.get(
                        "gold_definition", "latent-best worker in the exposure pool"
                    ),
                ),
                (
                    "exposure pool size",
                    str(
                        protocol.get(
                            "exposure_pool_size",
                            stats.get("exposure_pool_size", "n/a"),
                        )
                    ),
                ),
                (
                    "feature weights",
                    protocol.get("feature_weights", "SIM_INITIAL_WEIGHTS"),
                ),
            ]
        )
    )
    lines.append(
        "\nGold is the latent-best worker (argmax of the DGP true-match score) "
        "inside the task's exposure pool, not an accepted-only label. "
        f"{stats.get('gold_accepted', 0)} / {stats.get('n_tasks', 0)} gold workers "
        f"({stats.get('gold_acceptance_rate', 0):.2%}) accepted their task. Each "
        f"{result['candidates']}-candidate pool is the gold worker plus "
        f"{result['candidates'] - 1} uniformly sampled workers."
    )

    lines.append("\n## Metrics (mean ± std across seeds)\n")
    lines.append(
        _table(
            [
                (
                    key.upper(),
                    f"{metrics[key]['mean']:.4f} ± {metrics[key]['std']:.4f}",
                )
                for key in ("top1", "top5", "mrr", "ndcg")
            ]
        )
    )

    lines.append("\n## Baselines\n")
    feature_only = result.get("baselines", {}).get("feature_only", {})
    random_baseline = result.get("baselines", {}).get("random", {})
    lines.append("| baseline | Top-1 | Top-5 | MRR | NDCG |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        "| feature-only (no collaborative) | "
        f"{feature_only.get('top1', {}).get('mean', 0):.4f} ± "
        f"{feature_only.get('top1', {}).get('std', 0):.4f} | "
        f"{feature_only.get('top5', {}).get('mean', 0):.4f} ± "
        f"{feature_only.get('top5', {}).get('std', 0):.4f} | "
        f"{feature_only.get('mrr', {}).get('mean', 0):.4f} ± "
        f"{feature_only.get('mrr', {}).get('std', 0):.4f} | "
        f"{feature_only.get('ndcg', {}).get('mean', 0):.4f} ± "
        f"{feature_only.get('ndcg', {}).get('std', 0):.4f} |"
    )
    lines.append(
        "| uniform random (analytical) | "
        f"{random_baseline.get('top1', 0):.4f} | "
        f"{random_baseline.get('top5', 0):.4f} | n/a | n/a |"
    )
    lines.append(
        "\nThe feature-only baseline uses the same six observable features and "
        "weights with the collaborative term removed. The analytical random "
        "baseline is 1/200 Top-1 and 5/200 Top-5. Random is only a scale "
        "reference, not a fair model comparison: gold is latent-best inside a "
        "10-worker exposure pool and the 199 distractors are uniformly random, "
        "so most distractors are not plausible candidates. The feature-only "
        "baseline is the meaningful reference for the ItemCF contribution."
    )

    lines.append("\n## Per-seed metrics\n")
    lines.append("| seed | top1 | top5 | mrr | ndcg |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in result["per_seed"]:
        lines.append(
            f"| {row['seed']} | {row['top1']} | {row['top5']} | {row['mrr']} | {row['ndcg']} |"
        )

    lines.append("\n## ItemCF wiring (strict train-only graph)\n")
    itemcf = result["itemcf"]
    lines.append(
        _table(
            [
                ("similarity interactions (train accepted)", str(itemcf["similarity_interactions"])),
                ("history interactions (train accepted)", str(itemcf["history_interactions"])),
                ("similarity splits", json.dumps(itemcf.get("similarity_splits"))),
                ("history splits", json.dumps(itemcf.get("history_splits"))),
                ("similarity is train-only", str(itemcf.get("similarity_is_train_only"))),
                ("history is train-only", str(itemcf.get("history_is_train_only"))),
                ("accepted interactions total", str(itemcf.get("accepted_interactions_total"))),
                (
                    "excluded test accepted interactions",
                    str(itemcf.get("excluded_test_accepted_interactions")),
                ),
                ("collaborative pool-normalized", str(itemcf["pool_normalized"])),
                ("collaborative nonzero rate", f"{result['collaborative_nonzero_rate']:.2%}"),
            ]
        )
    )
    lines.append(
        "\nThe similarity graph and the worker history are both built from "
        "train-split accepted assignments only. A held-out test task therefore "
        "has no ItemCF co-occurrence edges and is a cold-start item, so the "
        "collaborative term is zero for every test-task candidate under this "
        "protocol. This is the strict, leak-free result; the pre-fix graph used "
        "test-task co-occurrences and was optimistic."
    )

    lines.append("\n## Data quality\n")
    lines.append(
        _table(
            [
                (
                    "task exact / title / near duplicates",
                    f"{stats['task_exact_duplicates']} / "
                    f"{stats.get('task_title_duplicates', 0)} / "
                    f"{stats.get('task_near_dup_collisions', 0)}",
                ),
                (
                    "resume exact / near duplicates",
                    f"{stats['resume_exact_duplicates']} / "
                    f"{stats.get('resume_near_dup_collisions', 0)}",
                ),
                ("task near-dup rate", f"{stats['task_near_dup_rate']:.4%}"),
                ("resume near-dup rate", f"{stats['resume_near_dup_rate']:.4%}"),
                ("task unique titles", f"{stats['task_unique_titles']} / {stats['n_tasks']}"),
                ("task_text mean length", str(stats["task_text_length"]["mean"])),
                ("resume_text mean length", str(stats["resume_text_length"]["mean"])),
            ]
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1000)
    parser.add_argument("--tasks", type=int, default=10000)
    parser.add_argument("--assignments", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--llm-seeds", default=None, help="optional JSON seed file (scheme C)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    parser.add_argument("--stats", default=str(DEFAULT_STATS))
    parser.add_argument("--eval-report", default=str(DEFAULT_EVAL))
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    llm_seeds = None
    if args.llm_seeds:
        llm_seeds = json.loads(Path(args.llm_seeds).read_text(encoding="utf-8"))

    dataset = generate_large_dataset(
        n_workers=args.workers,
        n_tasks=args.tasks,
        n_assignments=args.assignments,
        seed=args.seed,
        llm_seeds=llm_seeds,
    )

    db_path = build_large_sqlite(dataset, Path(args.db))
    jsonl_path = export_large_jsonl(dataset, Path(args.jsonl))
    stats_path = write_stats_report(dataset, Path(args.stats))

    summary = {
        "db": str(db_path),
        "jsonl": str(jsonl_path),
        "stats_report": str(stats_path),
        "seed": args.seed,
        "workers": len(dataset.workers),
        "tasks": len(dataset.tasks),
        "customers": len(dataset.customers),
        "assignments": len(dataset.assignments),
        "train_tasks": dataset.stats["train_tasks"],
        "test_tasks": dataset.stats["test_tasks"],
        "task_near_dup_rate": dataset.stats["task_near_dup_rate"],
        "resume_near_dup_rate": dataset.stats["resume_near_dup_rate"],
    }

    if not args.skip_eval:
        result = evaluate_large(Path(args.db))
        eval_path = write_eval_report(result, dataset.stats, Path(args.eval_report))
        summary["eval_report"] = str(eval_path)
        summary["metrics"] = result["metrics"]

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
