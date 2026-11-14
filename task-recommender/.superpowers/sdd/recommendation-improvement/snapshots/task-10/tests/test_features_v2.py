from datetime import datetime, timedelta

import pytest

from app.domain import Task, Worker
from app.features import category_history_score, expertise_score, skill_score


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


def test_skill_uses_required_skill_weights():
    task = make_task(
        required_skills={"python": 3, "writing": 3},
        required_skill_weights={"python": 3.0, "writing": 1.0},
    )
    worker = make_worker(skills={"python": 3, "writing": 1})
    expected = (3.0 * 1.0 + 1.0 * (1 / 3)) / 4.0
    assert skill_score(worker, task) == pytest.approx(expected)


def test_no_required_skills_does_not_return_one():
    worker = make_worker()
    task = make_task(required_skills={})
    expected = 0.5 * expertise_score(worker, task) + 0.5 * category_history_score(worker)
    assert skill_score(worker, task) == pytest.approx(expected)
    assert skill_score(worker, task) != 1.0


def test_expertise_uses_certification_and_semantic():
    worker = make_worker(certifications={"software_dev": 1.0}, ratings=[], completed=0)
    task = make_task()
    value = expertise_score(worker, task, semantic_similarity=1.0)
    expected = 0.35 * 0.6 + 0.15 * 1.0 + 0.25 * (4.2 / 5) + 0.25 * 1.0
    assert value == pytest.approx(expected, abs=1e-6)
