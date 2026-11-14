"""Run Phase 2 two-run, learning-curve, and query-diff evaluation."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.store import Store  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.evaluation_phase2 import (  # noqa: E402
    compare_queries,
    evaluate_two_runs,
    learning_curve,
)
from app.features import candidate_features  # noqa: E402
from app.learning.online import OnlineWeightLearner  # noqa: E402
from app.learning.weights import AHP_PRIOR  # noqa: E402
from app.personalization.segments import Segmenter  # noqa: E402
from app.personalization.user_weights import PersonalizationService  # noqa: E402
from app.service import RecommendationService  # noqa: E402


def main() -> None:
    dataset = generate_dataset()
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
    full_store.true_weights = dataset.true_weights
    for worker in dataset.new_users:
        full_store.workers[worker.worker_id] = worker

    assignment_by_id = {
        assignment.assignment_id: assignment
        for assignment in full_store.assignments
    }
    records = []
    for feedback in dataset.feedback:
        assignment = assignment_by_id.get(feedback.assignment_id)
        if assignment is None:
            continue
        task = full_store.tasks.get(assignment.task_id)
        worker = full_store.workers.get(assignment.worker_id)
        if task is None or worker is None:
            continue
        customer = full_store.customers.get(task.customer_id)
        if customer is None:
            continue
        features = candidate_features(
            worker,
            task,
            customer,
            cf_score=0.0,
            now=full_store.reference_time,
        )
        records.append((features, feedback.overall_rating))

    learner = OnlineWeightLearner(AHP_PRIOR)
    learner.batch_fit(records, epochs=2)
    learned_weights = learner.weights

    service = RecommendationService(full_store)
    metrics = evaluate_two_runs(
        test_store, service, AHP_PRIOR, learned_weights
    )

    personalizer = PersonalizationService(
        full_store, Segmenter(), AHP_PRIOR
    )
    new_user_ids = [
        worker.worker_id for worker in dataset.new_users[:200]
    ]
    curve = learning_curve(
        full_store,
        personalizer,
        new_user_ids,
        steps=(0, 5, 10, 20, 50),
    )

    queries = [
        {"task_id": task.task_id}
        for task in list(full_store.tasks.values())[:20]
    ]
    baseline_service = RecommendationService(
        full_store, weights=AHP_PRIOR
    )
    learned_service = RecommendationService(
        full_store, weights=learned_weights
    )
    differences = compare_queries(
        full_store, baseline_service, learned_service, queries
    )

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    payload = {
        "metrics": metrics,
        "learning_curve": curve,
        "weights": learned_weights,
    }
    (reports / "phase2_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    compare_lines = [
        "# Phase 2 两次运行对比",
        "",
        "| 指标 | 基线 | 学习后 |",
        "|---|---|---|",
        f"| NDCG | {metrics['baseline_ndcg']:.4f} | {metrics['learned_ndcg']:.4f} |",
        f"| HR | {metrics['baseline_hr']:.4f} | {metrics['learned_hr']:.4f} |",
        f"| 违约率 | {metrics['breach_rate']:.4f} | {metrics['breach_rate']:.4f} |",
    ]
    (reports / "phase2_compare.md").write_text(
        "\n".join(compare_lines) + "\n", encoding="utf-8"
    )

    curve_lines = [
        "# Phase 2 新用户学习曲线",
        "",
        "| n | NDCG@10 | HR@10 | Regret | 权重 cosine |",
        "|---|---|---|---|---|",
    ]
    for index, n_value in enumerate(curve["n"]):
        curve_lines.append(
            f"| {int(n_value)} | {curve['ndcg'][index]:.4f} | "
            f"{curve['hr'][index]:.4f} | {curve['regret'][index]:.4f} | "
            f"{curve['weight_cosine'][index]:.4f} |"
        )
    (reports / "phase2_learning_curve.md").write_text(
        "\n".join(curve_lines) + "\n", encoding="utf-8"
    )

    with (reports / "phase2_queries.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["task_id", "changed", "baseline", "learned"])
        for row in differences:
            writer.writerow(
                [
                    row["task_id"],
                    row["changed"],
                    "|".join(row["baseline"]),
                    "|".join(row["learned"]),
                ]
            )

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
