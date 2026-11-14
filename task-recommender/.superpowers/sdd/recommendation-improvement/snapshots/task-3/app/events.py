"""Impression and event capture with funnel metrics."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from app.data.store import Store
from app.domain import Impression, RecommendationEvent

ACTIONS = {"click", "apply", "accept", "reject", "ignore"}


class EventService:
    """Records recommendation impressions/events and computes funnel rates."""

    def __init__(
        self,
        store: Store,
        persist_dir: Path | None = None,
        max_events: int = 1_000_000,
    ) -> None:
        self.store = store
        self.persist_dir = Path(persist_dir) if persist_dir else None
        self.max_events = max_events
        if self.persist_dir is not None:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _line_count(path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)

    @staticmethod
    def _rotate(path: Path) -> None:
        index = 1
        while True:
            archived = path.with_name(f"{path.stem}.{index}.jsonl")
            if not archived.exists():
                path.replace(archived)
                return
            index += 1

    def _persist(self, name: str, payload: dict) -> None:
        if self.persist_dir is None:
            return
        path = self.persist_dir / f"{name}.jsonl"
        if self.max_events > 0 and self._line_count(path) >= self.max_events:
            self._rotate(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str))
            handle.write("\n")

    def _impression_for(self, request_id: str) -> Impression:
        for impression in reversed(self.store.impressions):
            if impression.request_id == request_id:
                return impression
        raise KeyError(request_id)

    def record_impression(
        self,
        request_id: str,
        query_id: str,
        candidate_ids: list[str],
        propensities: dict[str, float],
        policy: str,
        metadata: dict | None = None,
    ) -> Impression:
        impression = Impression(
            request_id=request_id,
            query_id=query_id,
            candidate_ids=list(candidate_ids),
            propensities=dict(propensities),
            policy=policy,
            created_at=self.store.reference_time,
            metadata=dict(metadata or {}),
        )
        self.store.impressions.append(impression)
        self._persist("impressions", asdict(impression))
        return impression

    def record_event(
        self,
        request_id: str,
        candidate_id: str,
        action: str,
        user_id: str | None = None,
        role: str = "customer",
        metadata: dict | None = None,
    ) -> RecommendationEvent:
        if action not in ACTIONS:
            raise ValueError(f"unknown action: {action}")
        impression = self._impression_for(request_id)
        if candidate_id not in impression.candidate_ids:
            raise KeyError(candidate_id)
        if any(
            event.request_id == request_id
            and event.candidate_id == candidate_id
            and event.action == action
            for event in self.store.events
        ):
            raise ValueError(
                "duplicate event for "
                f"({request_id}, {candidate_id}, {action})"
            )
        context = dict(metadata or {})
        event = RecommendationEvent(
            event_id=uuid.uuid4().hex,
            request_id=request_id,
            user_id=user_id,
            role=role,
            task_id=impression.query_id,
            candidate_id=candidate_id,
            candidate_type=context.get("candidate_type", "worker"),
            rank=impression.candidate_ids.index(candidate_id) + 1,
            score=float(context.get("score", 0.0)),
            propensity=impression.propensities[candidate_id],
            weights_version=str(context.get("weights_version", "v0000")),
            action=action,
            created_at=self.store.reference_time,
            metadata=context,
        )
        self.store.events.append(event)
        self._persist("events", asdict(event))
        return event

    def funnel_metrics(self) -> dict:
        impressions = len(self.store.impressions)
        candidates = sum(
            len(impression.candidate_ids)
            for impression in self.store.impressions
        )
        counts = {action: 0 for action in ACTIONS}
        for event in self.store.events:
            if event.action in counts:
                counts[event.action] += 1
        clicks = counts["click"]
        applies = counts["apply"]
        accepts = counts["accept"]
        rejects = counts["reject"]
        ignores = counts["ignore"]
        return {
            "impressions": impressions,
            "candidates": candidates,
            "clicks": clicks,
            "applies": applies,
            "accepts": accepts,
            "rejects": rejects,
            "ignores": ignores,
            "click_rate": clicks / max(1, candidates),
            "apply_rate": applies / max(1, clicks),
            "accept_rate": accepts / max(1, applies),
            "reject_rate": rejects / max(1, candidates),
            "ignore_rate": ignores / max(1, candidates),
        }
