from datetime import timedelta

from app.domain import Worker
from app.reputation import category_reputation, compute_reputation


def make_worker(**overrides):
    data = dict(
        worker_id="w1",
        name="W",
        skills={},
        specialties={},
        level=3,
        capacity_hours=40,
        current_load_hours=0,
        preferred_categories={},
        preferred_difficulty=(1, 5),
        region="CN",
        remote_ok=True,
        ratings=[5.0, 4.0],
        completed=2,
        on_time=2,
        rework_count=0,
        breach_dates=[],
    )
    data.update(overrides)
    return Worker(**data)


def test_one_recent_breach_is_warning_not_excluded(small_store):
    reference = small_store.reference_time
    worker = make_worker(breach_dates=[reference - timedelta(days=10)])
    breakdown = compute_reputation(worker, now=reference)
    assert breakdown.recent_breaches == 1
    assert breakdown.warning
    assert not breakdown.excluded
    assert breakdown.breach_penalty == 0.5


def test_two_recent_breaches_are_excluded(small_store):
    reference = small_store.reference_time
    worker = make_worker(
        breach_dates=[
            reference - timedelta(days=10),
            reference - timedelta(days=20),
        ]
    )
    breakdown = compute_reputation(worker, now=reference)
    assert breakdown.recent_breaches == 2
    assert breakdown.excluded
    assert not breakdown.warning
    assert breakdown.breach_penalty == 0.0


def test_category_reputation_shrinks_toward_global(small_store):
    reference = small_store.reference_time
    worker = make_worker(
        category_ratings={"software_dev": [5.0, 5.0]}
    )
    global_score = compute_reputation(worker, now=reference).total
    category_score = category_reputation(
        worker, "software_dev", m=1
    )
    assert category_score > global_score
    assert 0.0 <= category_score <= 1.0


def test_category_reputation_changes_feature_score(small_store):
    from app.features import reputation_score

    reference = small_store.reference_time
    worker = make_worker(
        ratings=[2.0, 2.0],
        completed=2,
        on_time=2,
        category_ratings={"software_dev": [5.0, 5.0]},
    )
    global_score = reputation_score(worker, now=reference)
    category_score = reputation_score(
        worker, "software_dev", now=reference
    )
    assert category_score > global_score
