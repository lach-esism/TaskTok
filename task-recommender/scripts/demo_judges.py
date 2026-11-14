"""Judge-facing demo: real learned weights, query diff, rollback, restore."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.store import Store  # noqa: E402
from app.data.synthetic import generate_dataset  # noqa: E402
from app.features import candidate_features  # noqa: E402
from app.learning.online import OnlineWeightLearner  # noqa: E402
from app.learning.weights import AHP_PRIOR  # noqa: E402
from app.service import RecommendationService  # noqa: E402
from app.versioning import WeightStore  # noqa: E402


def _learned_weights(dataset, store: Store) -> tuple[dict, int]:
    assignment_by_id = {
        assignment.assignment_id: assignment
        for assignment in store.assignments
    }
    records = []
    for feedback in dataset.feedback:
        assignment = assignment_by_id.get(feedback.assignment_id)
        if assignment is None:
            continue
        task = store.tasks.get(assignment.task_id)
        worker = store.workers.get(assignment.worker_id)
        customer = store.customers.get(task.customer_id) if task else None
        if task is None or worker is None or customer is None:
            continue
        features = candidate_features(
            worker,
            task,
            customer,
            cf_score=0.0,
            now=store.reference_time,
        )
        records.append((features, feedback.overall_rating))
    learner = OnlineWeightLearner(AHP_PRIOR)
    learner.batch_fit(records, epochs=2)
    return learner.weights, len(records)


def main() -> None:
    dataset = generate_dataset()
    store = Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
    )
    weights, sample_count = _learned_weights(dataset, store)
    weight_store = WeightStore(ROOT / "data" / "weights_demo", AHP_PRIOR)
    baseline = weight_store.active()
    learned = weight_store.create(weights, sample_count, "batch")

    task = list(store.tasks.values())[0]
    baseline_service = RecommendationService(
        store, weights=baseline.weights
    )
    learned_service = RecommendationService(
        store, weights=learned.weights
    )
    baseline_ranking = [
        item.candidate_id
        for item in baseline_service.recommend_workers(
            task.task_id, top_n=5
        )
    ]
    learned_ranking = [
        item.candidate_id
        for item in learned_service.recommend_workers(
            task.task_id, top_n=5
        )
    ]

    print("task:", task.task_id)
    print("baseline:", baseline.version, baseline_ranking)
    print("learned :", learned.version, learned_ranking)
    print("diff    :", json.dumps(weight_store.diff(baseline.version, learned.version), ensure_ascii=False))

    rolled = weight_store.rollback(baseline.version, "judge demo")
    restored_service = RecommendationService(
        store, weights=rolled.weights
    )
    restored_ranking = [
        item.candidate_id
        for item in restored_service.recommend_workers(
            task.task_id, top_n=5
        )
    ]
    print("rollback:", rolled.version, restored_ranking)
    print("restored equals baseline:", restored_ranking == baseline_ranking)

    weight_store.rollback(learned.version, "restore learned")
    print("changelog:", json.dumps(weight_store.changelog(), ensure_ascii=False))


if __name__ == "__main__":
    main()
