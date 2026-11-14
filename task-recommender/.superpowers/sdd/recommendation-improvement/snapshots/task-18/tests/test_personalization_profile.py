import pytest

from app.learning.weights import AHP_PRIOR
from app.personalization.profile import build_profile, profile_completeness
from app.personalization.segments import Segmenter, initial_weights


def test_segment_and_initial_weights_are_deterministic(small_store):
    profile = build_profile(
        small_store.workers["w_good"],
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 5,
        },
    )
    assert profile.segment_id == "engineer:mid"
    assert 0.0 <= profile_completeness(profile) <= 1.0

    segmenter = Segmenter()
    segmenter.fit([profile], {"w_good": AHP_PRIOR})
    weights, segment_id = initial_weights(
        profile, segmenter, AHP_PRIOR
    )
    assert segment_id == "engineer:mid"
    assert sum(weights.values()) == pytest.approx(1.0)
    assert min(weights.values()) >= 0.02 - 1e-9


def test_incomplete_profile_falls_back_to_global(small_store):
    profile = build_profile(small_store.workers["w_new"], "worker", {})
    segmenter = Segmenter()
    weights, _ = initial_weights(profile, segmenter, AHP_PRIOR)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_initial_preferences_change_weights(small_store):
    from app.personalization.segments import apply_preference_bias

    quality = build_profile(
        small_store.workers["w_good"],
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 3,
            "preferences": {"quality": 1.0},
        },
    )
    speed = build_profile(
        small_store.workers["w_good"],
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 3,
            "preferences": {"speed": 1.0},
        },
    )
    quality_weights, _ = initial_weights(quality, Segmenter(), AHP_PRIOR)
    speed_weights, _ = initial_weights(speed, Segmenter(), AHP_PRIOR)
    quality_weights = apply_preference_bias(
        quality_weights, quality.declared_preferences
    )
    speed_weights = apply_preference_bias(
        speed_weights, speed.declared_preferences
    )
    assert quality_weights["reputation"] > speed_weights["reputation"]
    assert speed_weights["load"] > quality_weights["load"]
    assert sum(quality_weights.values()) == pytest.approx(1.0)
    assert sum(speed_weights.values()) == pytest.approx(1.0)


def test_segment_weights_shrink_toward_global(small_store):
    profile = build_profile(
        small_store.workers["w_good"],
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 5,
        },
    )
    extreme = {
        "reputation": 0.40,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.13,
        "preference": 0.08,
        "load": 0.02,
        "customer_preference": 0.02,
    }
    segmenter = Segmenter()
    segmenter.fit(
        [profile], {"w_good": extreme}, global_weights=AHP_PRIOR
    )
    weights = segmenter.segment_weights("engineer:mid")
    assert weights["reputation"] < 0.40
