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


from datetime import datetime, timedelta, timezone
from app.features import pay_fit_score, preference_score, time_fit_score


def test_pay_fit_exact_match_and_missing():
    worker = make_worker(expected_pay=1000)
    assert pay_fit_score(worker, make_task(budget=1000)) == pytest.approx(1.0)
    assert pay_fit_score(worker, make_task(budget=2000)) == pytest.approx(1 - 1000 / 2000)
    assert pay_fit_score(make_worker(expected_pay=0), make_task(budget=1000)) == pytest.approx(0.5)


def test_time_fit_exact_value():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(current_load_hours=0)
    task = make_task(estimated_hours=5, deadline=now + timedelta(hours=10))
    assert time_fit_score(worker, task, now=now) == pytest.approx(0.5)


def test_preference_weighted_formula():
    worker = make_worker()
    task = make_task()
    value = preference_score(worker, task, p_accept=0.8)
    declared = 0.6 * 0.8 + 0.4 * 1.0  # category 0.8, difficulty midpoint 3 = task difficulty 3
    pay = pay_fit_score(worker, task)
    time_fit = time_fit_score(worker, task)
    expected = 0.4 * 0.8 + 0.3 * declared + 0.15 * pay + 0.15 * time_fit
    assert value == pytest.approx(expected)


def test_time_fit_subtracts_current_load():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(current_load_hours=4)
    task = make_task(estimated_hours=3, deadline=now + timedelta(hours=10))
    # hours_until = 10, available = 10 - 4 = 6, utilization = 3/6 = 0.5
    assert time_fit_score(worker, task, now=now) == pytest.approx(0.5)


def test_p_accept_defaults_to_declared():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker()
    task = make_task(deadline=now + timedelta(hours=10))
    declared = 0.6 * 0.8 + 0.4 * 1.0
    pay = pay_fit_score(worker, task)
    time_fit = time_fit_score(worker, task, now=now)
    expected = 0.4 * declared + 0.3 * declared + 0.15 * pay + 0.15 * time_fit
    assert preference_score(worker, task, now=now) == pytest.approx(expected)
    assert preference_score(
        worker, task, p_accept=declared, now=now
    ) == pytest.approx(expected)


def test_pay_fit_zero_budget_with_positive_expected_pay():
    # max(..., 1) guard: no ZeroDivisionError and the score bottoms out at 0.
    worker = make_worker(expected_pay=500)
    assert pay_fit_score(worker, make_task(budget=0)) == pytest.approx(0.0)


from app.features import load_score
from app.preference.customer import DEFAULT_ATTRIBUTE_WEIGHTS


def test_load_formula_with_exposure():
    import math
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(capacity_hours=40, current_load_hours=10)
    task = make_task(estimated_hours=10, deadline=now + timedelta(hours=20))
    value = load_score(worker, task, now=now, recent_impressions=100)
    capacity_score = (40 - 10 - 10) / 40
    deadline_feasibility = time_fit_score(worker, task, now=now)
    exposure_fairness = math.exp(-100 / 20)
    expected = 0.6 * capacity_score + 0.25 * deadline_feasibility + 0.15 * exposure_fairness
    assert value == pytest.approx(expected, abs=1e-9)


def test_customer_attribute_weights_sum_to_one_and_include_new_keys():
    assert set(DEFAULT_ATTRIBUTE_WEIGHTS) == {
        "reputation", "expertise", "speed", "communication",
        "price", "collaboration", "deadline_fit",
    }
    assert sum(DEFAULT_ATTRIBUTE_WEIGHTS.values()) == pytest.approx(1.0)


def test_customer_preference_fallback_uses_supplied_now():
    from datetime import datetime, timezone

    from app.domain import Customer
    from app.features import customer_preference_score
    from app.preference.customer import CustomerPreferenceProfile

    now = datetime(2020, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(capacity_hours=40, current_load_hours=0)
    task = make_task(estimated_hours=5, deadline=now + timedelta(hours=10))
    profile = CustomerPreferenceProfile(customer_id="c1", confidence=0.1)
    customer = Customer(customer_id="c1", name="C", region="CN")

    value = customer_preference_score(
        customer,
        worker,
        task,
        0.8,
        0.6,
        profile,
        pay_fit=0.7,
        now=now,
    )
    load_with_now = load_score(worker, task, now=now)
    expected = (
        0.4 * 0.8 + 0.3 * 0.6 + 0.15 * load_with_now + 0.15 * 0.7
    )
    assert value == pytest.approx(expected)

    # The 2020 deadline is long past for the wall clock, so ignoring the
    # supplied now would produce a different load term.
    wall_clock_load = load_score(worker, task)
    wall_clock_expected = (
        0.4 * 0.8 + 0.3 * 0.6 + 0.15 * wall_clock_load + 0.15 * 0.7
    )
    assert load_with_now != pytest.approx(wall_clock_load)
    assert value != pytest.approx(wall_clock_expected)
