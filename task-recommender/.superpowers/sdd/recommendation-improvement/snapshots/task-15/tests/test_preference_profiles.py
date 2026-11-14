import pytest

from app.preference.customer import (
    CustomerPreferenceProfile,
    update_customer_preferences,
)
from app.preference.worker import (
    WorkerPreferenceProfile,
    update_worker_preferences,
)


def test_worker_preference_moves_toward_accepted_category(
    small_store, software_task
):
    profile = WorkerPreferenceProfile(
        worker_id="w_new",
        category_preferences={"software_dev": 0.5},
        difficulty_preference=(2, 4),
        confidence=0.0,
    )
    updated = update_worker_preferences(
        profile,
        software_task,
        accepted=True,
        rating=5,
        now=small_store.reference_time,
    )
    assert updated.category_preferences["software_dev"] > 0.5
    assert 0.0 <= updated.confidence <= 1.0


def test_default_attribute_weights_cover_all_attributes_and_sum_to_one():
    from app.preference.customer import DEFAULT_ATTRIBUTE_WEIGHTS

    assert DEFAULT_ATTRIBUTE_WEIGHTS == {
        "reputation": 0.30,
        "expertise": 0.20,
        "speed": 0.15,
        "communication": 0.10,
        "price": 0.10,
        "collaboration": 0.10,
        "deadline_fit": 0.05,
    }


def test_customer_preference_boosts_reputation_after_high_rating(small_store):
    profile = CustomerPreferenceProfile(customer_id="c1")
    before = profile.attribute_weights["reputation"]
    updated = update_customer_preferences(
        profile,
        small_store.workers["w_good"],
        small_store.tasks["t1"],
        5,
    )
    assert updated.attribute_weights["reputation"] > before
    assert sum(updated.attribute_weights.values()) == pytest.approx(1.0)


def test_preference_score_falls_back_without_confident_profile(
    small_store, software_task
):
    from app.features import preference_score

    worker = small_store.workers["w_good"]
    now = small_store.reference_time
    assert preference_score(
        worker, software_task, now=now
    ) == preference_score(
        worker,
        software_task,
        profile=WorkerPreferenceProfile(worker_id="w_good"),
        now=now,
    )
