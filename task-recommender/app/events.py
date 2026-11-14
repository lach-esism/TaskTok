"""Impression and event capture with funnel metrics.

Persisted ``events.jsonl`` / ``impressions.jsonl`` files (and rotated
``*.N.jsonl`` archives) are **audit-only**: they are never replayed into the
in-memory store, because replaying historical accept/ignore rows would change
training features and double-count the funnel. Rotation line counts are kept
in memory per active file instead of rescanning the file on every append.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from app.data.store import Store
from app.domain import Impression, RecommendationEvent

ACTIONS = {"click", "apply", "accept", "reject", "ignore"}
#: Client-supplied metadata keys that may be stored on an event. Target labels
#: (``candidate_type`` / ``task_id``) are only accepted when they agree with
#: the impression; arbitrary client keys are dropped.
ALLOWED_METADATA_KEYS = frozenset(
    {"candidate_type", "task_id", "score", "weights_version"}
)


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
        self._impressions_by_request: dict[str, Impression] = {
            impression.request_id: impression
            for impression in store.impressions
        }
        self._seen_event_keys: set[tuple[str, str, str]] = {
            (event.request_id, event.candidate_id, event.action)
            for event in store.events
        }
        self._line_counts: dict[str, int] = {}
        if self.persist_dir is not None:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

    def _line_count(self, name: str, path: Path) -> int:
        """Count the active file once; increments are tracked in memory."""
        if name not in self._line_counts:
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    self._line_counts[name] = sum(1 for _ in handle)
            else:
                self._line_counts[name] = 0
        return self._line_counts[name]

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
        if (
            self.max_events > 0
            and self._line_count(name, path) >= self.max_events
        ):
            self._rotate(path)
            self._line_counts[name] = 0
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str))
            handle.write("\n")
        self._line_counts[name] = self._line_counts.get(name, 0) + 1

    def _impression_for(self, request_id: str) -> Impression:
        impression = self._impressions_by_request.get(request_id)
        if impression is not None:
            return impression
        # Tolerate impressions appended directly to the store after start-up.
        for candidate in reversed(self.store.impressions):
            if candidate.request_id == request_id:
                self._impressions_by_request[request_id] = candidate
                return candidate
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
        self._impressions_by_request[request_id] = impression
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
        key = (request_id, candidate_id, action)
        if key in self._seen_event_keys:
            raise ValueError(
                "duplicate event for "
                f"({request_id}, {candidate_id}, {action})"
            )
        context = {
            key: value
            for key, value in dict(metadata or {}).items()
            if key in ALLOWED_METADATA_KEYS
        }
        impression_type = str(
            impression.metadata.get("candidate_type") or "worker"
        )
        if impression_type not in {"worker", "task"}:
            raise ValueError(
                f"unknown impression candidate_type: {impression_type!r}"
            )
        impression_task_id = impression.metadata.get("task_id") or (
            candidate_id
            if impression_type == "task"
            else impression.query_id
        )
        client_type = context.get("candidate_type")
        if client_type is not None and client_type != impression_type:
            raise ValueError(
                "candidate_type does not match the impression "
                f"({client_type!r} != {impression_type!r})"
            )
        client_task_id = context.get("task_id")
        if (
            client_task_id is not None
            and client_task_id != impression_task_id
        ):
            raise ValueError(
                "task_id does not match the impression "
                f"({client_task_id!r} != {impression_task_id!r})"
            )
        try:
            score = float(context.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        event = RecommendationEvent(
            event_id=uuid.uuid4().hex,
            request_id=request_id,
            user_id=user_id,
            role=role,
            task_id=impression_task_id,
            candidate_id=candidate_id,
            candidate_type=impression_type,
            rank=impression.candidate_ids.index(candidate_id) + 1,
            score=score,
            propensity=impression.propensities[candidate_id],
            weights_version=str(context.get("weights_version", "v0000")),
            action=action,
            created_at=self.store.reference_time,
            metadata=context,
        )
        self.store.events.append(event)
        self._seen_event_keys.add(key)
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
