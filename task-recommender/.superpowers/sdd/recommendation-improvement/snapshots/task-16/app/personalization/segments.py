"""Rule-based segments and initial personalized weights."""

from __future__ import annotations

from app.domain import Segment, UserProfile
from app.learning.weights import project_weights


class Segmenter:
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.segments: dict[str, Segment] = {}

    def fit(
        self,
        profiles: list[UserProfile],
        weights_by_user: dict[str, dict[str, float]],
        global_weights: dict[str, float] | None = None,
    ) -> list[Segment]:
        self.segments = {}
        grouped: dict[str, list[dict[str, float]]] = {}
        for profile in profiles:
            weights = weights_by_user.get(profile.user_id)
            if weights:
                grouped.setdefault(profile.segment_id, []).append(weights)

        for segment_id, group in grouped.items():
            keys = set().union(*(weights for weights in group))
            mean = {
                key: sum(
                    weights.get(key, 0.0) for weights in group
                ) / len(group)
                for key in keys
            }
            if global_weights:
                n = len(group)
                ratio = n / (n + 50.0)
                mean = {
                    key: ratio * mean.get(key, 0.0)
                    + (1.0 - ratio) * global_weights.get(key, 0.0)
                    for key in set(mean) | set(global_weights)
                }
            self.segments[segment_id] = Segment(
                segment_id=segment_id,
                name=segment_id,
                centroid={},
                weights=project_weights(mean),
                member_count=len(group),
            )
        return list(self.segments.values())

    def assign(self, profile: UserProfile) -> str:
        return profile.segment_id

    def segment_weights(self, segment_id: str) -> dict[str, float]:
        segment = self.segments.get(segment_id)
        return dict(segment.weights) if segment else {}


def apply_preference_bias(
    weights: dict[str, float],
    preferences: dict[str, float] | None,
) -> dict[str, float]:
    if not preferences:
        return project_weights(weights)
    values = {
        key: max(float(value), 0.0)
        for key, value in preferences.items()
    }
    quality = values.get("quality", 0.0)
    speed = values.get("speed", 0.0)
    specialty = values.get("specialty", 0.0)
    flexibility = values.get("flexibility", 0.0)

    adjusted = dict(weights)
    adjusted["reputation"] = adjusted.get("reputation", 0.0) * (
        1.0 + 0.8 * quality
    )
    adjusted["skill"] = adjusted.get("skill", 0.0) * (
        1.0 + 0.25 * quality + 0.20 * specialty
    )
    adjusted["expertise"] = adjusted.get("expertise", 0.0) * (
        1.0 + 0.30 * specialty
    )
    adjusted["load"] = adjusted.get("load", 0.0) * (
        1.0 + 0.9 * speed + 0.4 * flexibility
    )
    adjusted["customer_preference"] = adjusted.get(
        "customer_preference", 0.0
    ) * (1.0 + 0.2 * speed)
    adjusted["preference"] = adjusted.get("preference", 0.0) * (
        1.0 + 0.2 * flexibility
    )
    return project_weights(adjusted)


def initial_weights(
    profile: UserProfile,
    segmenter: Segmenter,
    global_weights: dict[str, float],
) -> tuple[dict[str, float], str]:
    if profile.profile_completeness >= 0.6:
        segment_weights = segmenter.segment_weights(profile.segment_id)
        if segment_weights:
            return project_weights(segment_weights), profile.segment_id
    return project_weights(global_weights), profile.segment_id
