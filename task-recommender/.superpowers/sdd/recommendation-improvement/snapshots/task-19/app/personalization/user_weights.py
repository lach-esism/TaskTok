"""Three-level personalization: global -> segment -> individual."""

from __future__ import annotations

from app.data.store import Store
from app.domain import LearningSnapshot, UserWeightProfile
from app.learning.online import OnlineWeightLearner, shrink_weights
from app.learning.weights import project_weights
from app.personalization.profile import build_profile
from app.personalization.segments import (
    Segmenter,
    apply_preference_bias,
    initial_weights,
)


class PersonalizationService:
    def __init__(
        self,
        store: Store,
        segmenter: Segmenter,
        global_weights: dict[str, float],
    ) -> None:
        self.store = store
        self.segmenter = segmenter
        self.global_weights = dict(global_weights)

    def ensure_profile(
        self,
        user_id: str,
        entity_type: str,
        declared: dict | None = None,
    ):
        if user_id in self.store.profiles:
            return self.store.profiles[user_id]
        user = self.store.workers.get(user_id) or self.store.customers.get(
            user_id
        )
        if user is None:
            raise KeyError(user_id)
        profile = build_profile(user, entity_type, declared)
        self.store.profiles[user_id] = profile
        return profile

    def _refresh_segments(self) -> None:
        weights_by_user = {
            user_id: profile.weights
            for user_id, profile in self.store.user_weight_profiles.items()
            if user_id in self.store.profiles
        }
        self.segmenter.fit(
            list(self.store.profiles.values()),
            weights_by_user,
            global_weights=self.global_weights,
        )

    def weights_for(self, user_id: str) -> UserWeightProfile:
        existing = self.store.user_weight_profiles.get(user_id)
        if existing is not None:
            return existing
        entity_type = (
            "worker" if user_id in self.store.workers else "customer"
        )
        profile = self.ensure_profile(user_id, entity_type)
        self._refresh_segments()
        weights, segment_id = initial_weights(
            profile, self.segmenter, self.global_weights
        )
        weights = apply_preference_bias(
            weights, profile.declared_preferences
        )
        if profile.declared_preferences:
            source = "profile"
        elif (
            profile.profile_completeness >= 0.6
            and self.segmenter.segment_weights(segment_id)
        ):
            source = "segment"
        else:
            source = "global"
        profile.segment_id = segment_id
        result = UserWeightProfile(
            user_id=user_id,
            weights=weights,
            source=source,
            segment_id=segment_id,
            sample_count=0,
            confidence=0.0,
            version="u0000",
            initial_weights=dict(weights),
        )
        self.store.user_weight_profiles[user_id] = result
        return result

    def update(
        self,
        user_id: str,
        features: dict[str, float],
        rating: int,
        n0_override: float | None = None,
    ) -> UserWeightProfile:
        current = self.weights_for(user_id)
        profile = self.store.profiles[user_id]
        learner = OnlineWeightLearner(
            prior=current.weights, weights=current.weights
        )
        learned = learner.update(features, rating)
        n = current.sample_count + 1
        n0 = (
            n0_override
            if n0_override is not None
            else 10.0 + 30.0 * (1.0 - profile.profile_completeness)
        )
        anchor = current.initial_weights or current.weights
        weights = shrink_weights(
            learned, anchor, n, n0=int(round(n0))
        )
        updated = UserWeightProfile(
            user_id=user_id,
            weights=weights,
            source="online",
            segment_id=current.segment_id,
            sample_count=n,
            confidence=n / (n + 20.0),
            version=f"u{n:04d}",
            initial_weights=dict(anchor),
        )
        self.store.user_weight_profiles[user_id] = updated
        self._refresh_segments()
        return updated

    def update_pair(
        self,
        user_id: str,
        chosen: dict[str, float],
        rejected: dict[str, float],
    ) -> UserWeightProfile:
        current = self.weights_for(user_id)
        profile = self.store.profiles[user_id]
        learner = OnlineWeightLearner(
            prior=current.weights, weights=current.weights
        )
        learned = learner.update_pair(chosen, rejected)
        n = current.sample_count + 1
        n0 = 10.0 + 30.0 * (1.0 - profile.profile_completeness)
        anchor = current.initial_weights or current.weights
        weights = shrink_weights(
            learned, anchor, n, n0=int(round(n0))
        )
        updated = UserWeightProfile(
            user_id=user_id,
            weights=weights,
            source="online_pair",
            segment_id=current.segment_id,
            sample_count=n,
            confidence=n / (n + 20.0),
            version=f"u{n:04d}",
            initial_weights=dict(anchor),
        )
        self.store.user_weight_profiles[user_id] = updated
        self._refresh_segments()
        return updated

    def nudge_weights(
        self,
        user_id: str,
        signals: dict[str, float],
        strength: float = 0.3,
        n0: float = 5.0,
    ) -> UserWeightProfile:
        """Move weights toward dimensions the acceptance record validated.

        ``signals`` is a -1..1 score per scoring dimension, derived from
        criterion outcomes. Unlike a single rating, it preserves *which*
        dimension the customer cared about.
        """
        current = self.weights_for(user_id)
        raw = {
            key: max(
                1e-9,
                current.weights[key]
                * (1.0 + strength * signals.get(key, 0.0)),
            )
            for key in current.weights
        }
        learned = project_weights(raw)
        n = current.sample_count + 1
        anchor = current.initial_weights or current.weights
        weights = shrink_weights(learned, anchor, n, n0=int(round(n0)))
        updated = UserWeightProfile(
            user_id=user_id,
            weights=weights,
            source="acceptance",
            segment_id=current.segment_id,
            sample_count=n,
            confidence=n / (n + 20.0),
            version=f"u{n:04d}",
            initial_weights=dict(anchor),
        )
        self.store.user_weight_profiles[user_id] = updated
        self._refresh_segments()
        return updated

    def snapshot(
        self,
        user_id: str,
        ndcg_at_10: float,
        hr_at_10: float,
        regret: float,
    ) -> LearningSnapshot:
        current = self.weights_for(user_id)
        snapshot = LearningSnapshot(
            user_id=user_id,
            n_feedback=current.sample_count,
            weights=dict(current.weights),
            ndcg_at_10=ndcg_at_10,
            hr_at_10=hr_at_10,
            regret=regret,
        )
        self.store.learning_snapshots.append(snapshot)
        return snapshot
