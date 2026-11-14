"""Feedback ingestion and reputation updates for Phase 2."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from app.data.store import Store
from app.domain import Assignment, Feedback
from app.reputation import recent_breach_count as _recent_breach_count


class FeedbackService:
    def __init__(
        self,
        store: Store,
        persist_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.persist_dir = Path(persist_dir) if persist_dir else None
        if self.persist_dir is not None:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

    def _persist(self, name: str, payload: dict) -> None:
        if self.persist_dir is None:
            return
        path = self.persist_dir / f"{name}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str))
            handle.write("\n")

    def record_assignment(
        self,
        task_id: str,
        worker_id: str,
        customer_id: str,
        recommendation_context: dict | None = None,
    ) -> Assignment:
        if task_id not in self.store.tasks:
            raise KeyError(task_id)
        if worker_id not in self.store.workers:
            raise KeyError(worker_id)
        if any(
            item.task_id == task_id and item.worker_id == worker_id
            for item in self.store.assignments
        ):
            raise ValueError("task already assigned to worker")
        if recommendation_context is None:
            context = {}
        elif hasattr(recommendation_context, "model_dump"):
            context = recommendation_context.model_dump()
        else:
            context = dict(recommendation_context)
        now = self.store.reference_time
        assignment = Assignment(
            assignment_id=uuid.uuid4().hex,
            task_id=task_id,
            worker_id=worker_id,
            customer_id=customer_id,
            status="assigned",
            on_time=True,
            created_at=now,
            recommended_at=now,
            recommendation_score=float(context.get("score", 0.0)),
            recommendation_rank=int(context.get("rank", 0)),
            propensity=float(context.get("propensity", 1.0)),
            weights_version=str(context.get("weights_version", "v0000")),
        )
        self.store.assignments.append(assignment)
        self._persist("assignments", asdict(assignment))
        return assignment

    def record_feedback(
        self,
        assignment_id: str,
        overall_rating: int,
        quality_rating: int | None = None,
        timeliness_rating: int | None = None,
        communication_rating: int | None = None,
        comment: str = "",
    ) -> Feedback:
        assignment = next(
            (
                item
                for item in self.store.assignments
                if item.assignment_id == assignment_id
            ),
            None,
        )
        if assignment is None:
            raise KeyError(assignment_id)
        if any(
            item.assignment_id == assignment_id
            for item in self.store.feedback
        ):
            raise ValueError("feedback already recorded")
        if not 1 <= overall_rating <= 5:
            raise ValueError("overall_rating must be between 1 and 5")

        feedback = Feedback(
            feedback_id=uuid.uuid4().hex,
            assignment_id=assignment_id,
            worker_id=assignment.worker_id,
            task_id=assignment.task_id,
            overall_rating=overall_rating,
            created_at=self.store.reference_time,
            quality_rating=quality_rating,
            timeliness_rating=timeliness_rating,
            communication_rating=communication_rating,
            comment=comment,
            propensity=assignment.propensity,
        )
        self.store.feedback.append(feedback)

        worker = self.store.workers[assignment.worker_id]
        worker.ratings.append(float(overall_rating))
        task = self.store.tasks.get(assignment.task_id)
        if task is not None:
            worker.category_ratings.setdefault(task.category, []).append(
                float(overall_rating)
            )
        if assignment.status != "completed":
            worker.completed += 1
            if assignment.on_time:
                worker.on_time += 1
        assignment.status = "completed"
        self._persist("feedback", asdict(feedback))
        return feedback

    def reputation(self, worker_id: str) -> dict:
        worker = self.store.workers.get(worker_id)
        if worker is None:
            raise KeyError(worker_id)
        from app.reputation import compute_reputation

        breakdown = compute_reputation(
            worker, self.store.reference_time
        )
        if breakdown.excluded:
            status = "excluded"
        elif breakdown.warning:
            status = "warning"
        else:
            status = "active"
        return {
            "worker_id": worker_id,
            "ratings_count": len(worker.ratings),
            "rating": breakdown.rating,
            "completed": worker.completed,
            "on_time": worker.on_time,
            "recent_breaches": breakdown.recent_breaches,
            "warning": breakdown.warning,
            "excluded": breakdown.excluded,
            "status": status,
        }
