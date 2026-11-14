import pytest

from app.learning.weights import AHP_PRIOR
from app.personalization.segments import Segmenter
from app.personalization.user_weights import PersonalizationService


def test_personalization_shrinks_toward_prior_for_new_user(small_store):
    personalizer = PersonalizationService(
        small_store, Segmenter(), AHP_PRIOR
    )
    personalizer.ensure_profile(
        "w_new",
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 2,
        },
    )
    weights = personalizer.weights_for("w_new")
    assert weights.source in {"profile", "segment", "global"}
    assert sum(weights.weights.values()) == pytest.approx(1.0)

    updated = personalizer.update(
        "w_new",
        {
            "reputation": 1.0,
            "skill": 0.0,
            "expertise": 0.0,
            "collaborative": 0.0,
            "preference": 0.0,
            "load": 0.0,
            "customer_preference": 0.0,
        },
        5,
    )
    assert updated.sample_count == 1
    assert sum(updated.weights.values()) == pytest.approx(1.0)
    assert 0.25 <= updated.weights["reputation"] <= 0.40


def test_personalization_preserves_initial_weights_anchor(small_store):
    personalizer = PersonalizationService(
        small_store, Segmenter(), AHP_PRIOR
    )
    personalizer.ensure_profile(
        "w_new",
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 2,
        },
    )
    initial = personalizer.weights_for("w_new")
    updated = personalizer.update(
        "w_new",
        {
            "reputation": 1.0,
            "skill": 0.0,
            "expertise": 0.0,
            "collaborative": 0.0,
            "preference": 0.0,
            "load": 0.0,
            "customer_preference": 0.0,
        },
        5,
    )
    assert updated.initial_weights == pytest.approx(initial.weights)


def test_service_accepts_user_id_without_crashing(small_store):
    from app.service import RecommendationService

    personalizer = PersonalizationService(
        small_store, Segmenter(), AHP_PRIOR
    )
    personalizer.ensure_profile(
        "w_good",
        "worker",
        {
            "role": "engineer",
            "industry": "software",
            "experience_years": 4,
        },
    )
    personalizer.update(
        "w_good",
        {
            "reputation": 1.0,
            "skill": 0.5,
            "expertise": 0.2,
            "collaborative": 0.0,
            "preference": 0.3,
            "load": 0.4,
            "customer_preference": 0.3,
        },
        5,
    )
    service = RecommendationService(small_store)
    candidates = service.recommend_workers(
        "t1", top_n=5, user_id="w_good"
    )
    assert candidates
    assert all(0.0 <= candidate.score <= 1.0 for candidate in candidates)
