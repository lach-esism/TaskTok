from datetime import datetime, timedelta

from app.domain import Customer, Task, Worker
from app.features import candidate_features, fuse_scores, skill_score


def make_worker(**overrides):
    data = dict(
        worker_id="w1",
        name="A",
        skills={"python": 4},
        specialties={"software_dev": 3},
        level=3,
        capacity_hours=40,
        current_load_hours=10,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
        ratings=[5.0, 4.0],
        completed=2,
        on_time=2,
        rework_count=0,
    )
    data.update(overrides)
    return Worker(**data)


def make_task(**overrides):
    data = dict(
        task_id="t1",
        customer_id="c1",
        title="Build API",
        description="",
        category="software_dev",
        required_skills={"python": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=datetime.now() + timedelta(days=7),
        region="CN",
        remote_ok=True,
    )
    data.update(overrides)
    return Task(**data)


def test_skill_score_full_match_and_missing_skill():
    assert skill_score(make_worker(), make_task()) == 1.0
    assert skill_score(make_worker(skills={}), make_task()) == 0.0


def test_features_are_normalized_and_fusion_sums_to_score():
    features = candidate_features(
        make_worker(),
        make_task(),
        Customer(customer_id="c1", name="C", region="CN"),
    )
    assert all(0.0 <= value <= 1.0 for value in features.values())
    weights = {
        "reputation": 0.32,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.13,
        "preference": 0.10,
        "load": 0.06,
        "customer_preference": 0.04,
    }
    score = fuse_scores(features, weights)
    assert 0.0 <= score <= 1.0
