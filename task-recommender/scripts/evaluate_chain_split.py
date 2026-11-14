"""Evaluate dynamic chain splitting against pure-template decomposition."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.chains.decompose import decompose  # noqa: E402
from app.chains.materialize import build_subtask_task  # noqa: E402
from app.chains.split import (  # noqa: E402
    parse_split_policy,
    split_quality_score,
)
from app.data.store import Store  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.data.templates import load_templates  # noqa: E402
from app.domain import Task  # noqa: E402
from app.service import is_eligible  # noqa: E402

DEFAULT_TEMPLATES = ROOT / "data" / "chain_templates" / "common_task_chains.json"
DEFAULT_GOLDEN = ROOT / "dev_data" / "chains" / "split_cases.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "chain_split_eval.json"


def _coverage_ratio(draft, exclude_fallbacks: bool = False) -> float:
    requirements = draft.requirements
    if not requirements:
        return 1.0
    fallbacks = (
        set(getattr(draft, "coverage_fallbacks", []))
        if exclude_fallbacks
        else set()
    )
    covered = sum(
        1
        for item in requirements
        if draft.coverage.get(item) and item not in fallbacks
    )
    return covered / len(requirements)


def _build_store() -> Store:
    dataset = generate_dataset(
        n_workers=200, n_tasks=50, n_assignments=0, seed=42
    )
    return Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=[],
        feedback=[],
    )


def _to_task(case: dict, now: datetime) -> Task:
    return Task(
        task_id=case["task_id"],
        customer_id="c_eval",
        title=case["title"],
        description=case["description"],
        category=case["category"],
        required_skills=dict(case.get("required_skills", {})),
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=float(case["estimated_hours"]),
        deadline=now + timedelta(days=int(case["deadline_days"])),
        region="CN",
        remote_ok=True,
        budget=float(case["budget"]),
    )


def _fingerprint(draft) -> list[tuple]:
    return [
        (node.key, round(node.estimated_hours, 4))
        for node in draft.chain.nodes
    ]


def evaluate(templates_path: Path, golden_path: Path) -> dict:
    templates = load_templates(templates_path)
    cases = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    store = _build_store()
    workers = list(store.workers.values())
    now = datetime.now(timezone.utc)

    coverage_gains: list[float] = []
    dispatchable = 0
    total_nodes = 0
    hours: list[float] = []
    duplicate_dispatch = 0
    deterministic = True
    quality_scores: list[float] = []
    processed = 0

    for case in cases:
        template = templates.get(case["category"])
        if template is None:
            continue
        processed += 1
        task = _to_task(case, now)
        base = decompose(task, template)
        split_draft = decompose(task, template, split=True)
        policy = parse_split_policy(split_draft.split_policy)
        quality_scores.append(
            split_quality_score(
                split_draft, task, store, policy
            ).total
        )
        coverage_gains.append(
            _coverage_ratio(split_draft)
            - _coverage_ratio(base, exclude_fallbacks=True)
        )

        subtask_tasks = [
            build_subtask_task(
                task, node, split_draft.chain, split_draft.draft_id
            )
            for node in split_draft.chain.nodes
        ]
        total_nodes += len(subtask_tasks)
        hours.extend(node.estimated_hours for node in split_draft.chain.nodes)
        for built in subtask_tasks:
            if any(
                is_eligible(worker, built, store)[0]
                for worker in workers
            ):
                dispatchable += 1

        task.status = "split"
        duplicate_dispatch += sum(
            1
            for worker in workers
            if is_eligible(worker, task, store)[0]
            and any(
                is_eligible(worker, built, store)[0]
                for built in subtask_tasks
            )
        )

        replay = decompose(task, template, split=True)
        if _fingerprint(replay) != _fingerprint(split_draft):
            deterministic = False

    in_band = sum(1 for value in hours if 2.0 <= value <= 16.0)
    return {
        "cases": processed,
        "coverage_gain": (
            statistics.mean(coverage_gains) if coverage_gains else 0.0
        ),
        "dispatchable_rate": (
            dispatchable / total_nodes if total_nodes else 0.0
        ),
        "granularity_p50": (
            float(np.percentile(hours, 50)) if hours else 0.0
        ),
        "granularity_p95": (
            float(np.percentile(hours, 95)) if hours else 0.0
        ),
        "in_band_rate": in_band / len(hours) if hours else 0.0,
        "duplicate_dispatch": duplicate_dispatch,
        "deterministic": deterministic,
        "quality_mean": (
            statistics.mean(quality_scores)
            if quality_scores
            else 0.0
        ),
        "total_nodes": total_nodes,
    }


def _write_markdown(output: Path, metrics: dict) -> Path:
    markdown = output.with_suffix(".md")
    markdown.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"| {key} | {value} |" for key, value in metrics.items()
    )
    markdown.write_text(
        "# Chain Split Evaluation\n\n"
        f"- Cases: {metrics['cases']}\n\n"
        "| Metric | Value |\n|---|---|\n"
        f"{rows}\n",
        encoding="utf-8",
    )
    return markdown


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates", type=Path, default=DEFAULT_TEMPLATES)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    metrics = evaluate(args.templates, args.golden)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown = _write_markdown(args.output, metrics)
    print(json.dumps(metrics, ensure_ascii=False))
    print(f"wrote {args.output}")
    print(f"wrote {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
