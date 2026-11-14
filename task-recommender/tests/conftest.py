from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.data.store import Store
from app.data.synthetic import SKILLS, generate_dataset
from app.domain import Assignment, Customer, Feedback, Task, Worker
from app.main import create_app

NOW = datetime.now(timezone.utc)


@pytest.fixture
def dataset():
    return generate_dataset(
        n_workers=20, n_tasks=60, n_assignments=200, seed=42, n_new_users=0,
    )


def _worker(
    worker_id: str,
    skills: dict[str, int],
    *,
    level: int = 3,
    capacity: float = 40,
    load: float = 0,
    ratings: list[float] | None = None,
    completed: int = 0,
    on_time: int = 0,
    breach_dates: list[datetime] | None = None,
) -> Worker:
    return Worker(
        worker_id=worker_id,
        name=worker_id,
        skills=skills,
        specialties={"software_dev": 3},
        level=level,
        capacity_hours=capacity,
        current_load_hours=load,
        preferred_categories={"software_dev": 0.8},
        preferred_difficulty=(2, 4),
        region="CN",
        remote_ok=True,
        ratings=ratings or [],
        completed=completed,
        on_time=on_time,
        breach_dates=breach_dates or [],
    )


@pytest.fixture
def small_store() -> Store:
    customer = Customer(customer_id="c1", name="Customer", region="CN")
    good = _worker(
        "w_good",
        {"python": 4},
        ratings=[5.0, 4.0],
        completed=2,
        on_time=2,
    )
    new = _worker("w_new", {"python": 4})
    bad = _worker("w_bad", {"writing": 3})
    overloaded = _worker("w_overloaded", {"python": 4}, load=40)
    breach = _worker(
        "w_breach",
        {"python": 4},
        breach_dates=[
            NOW - timedelta(days=10),
            NOW - timedelta(days=20),
        ],
    )
    full = _worker(
        "w_full",
        {"python": 4, **{skill: 4 for skill in SKILLS}},
        capacity=200,
        load=0,
    )
    low = _worker("w_low", {"python": 4}, level=1)
    other = _worker("w_other", {"python": 4})
    warm = _worker("w_warm", {"python": 4})
    cold = _worker("w_cold", {"python": 4})

    t1 = Task(
        task_id="t1",
        customer_id="c1",
        title="Build API",
        description="需求文档；交付 API",
        category="software_dev",
        required_skills={"python": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=NOW + timedelta(days=7),
        region="CN",
        remote_ok=True,
    )
    t_empty = Task(
        task_id="t_empty",
        customer_id="c1",
        title="Impossible task",
        description="需要不存在的技能",
        category="software_dev",
        required_skills={"nonexistent_skill": 5},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=NOW + timedelta(days=7),
        region="CN",
        remote_ok=True,
    )
    t_past = Task(
        task_id="t_past",
        customer_id="c1",
        title="Past task",
        description="历史任务",
        category="software_dev",
        required_skills={"python": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=NOW - timedelta(days=20),
        region="CN",
        remote_ok=True,
        status="completed",
        created_at=NOW - timedelta(days=30),
    )
    t2 = Task(
        task_id="t2",
        customer_id="c1",
        title="Second open task",
        description="开放任务",
        category="software_dev",
        required_skills={"python": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=NOW + timedelta(days=7),
        region="CN",
        remote_ok=True,
    )
    t_hist = Task(
        task_id="t_hist",
        customer_id="c1",
        title="History task",
        description="历史任务",
        category="software_dev",
        required_skills={"python": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=NOW - timedelta(days=40),
        region="CN",
        remote_ok=True,
        status="completed",
        created_at=NOW - timedelta(days=60),
    )

    assignments = [
        Assignment(
            assignment_id="a1",
            task_id="t_past",
            worker_id="w_good",
            customer_id="c1",
            status="completed",
            on_time=True,
            created_at=NOW - timedelta(days=20),
        ),
        Assignment(
            assignment_id="a_hist_other",
            task_id="t_hist",
            worker_id="w_other",
            customer_id="c1",
            status="completed",
            on_time=True,
            created_at=NOW - timedelta(days=50),
        ),
        Assignment(
            assignment_id="a_hist_warm",
            task_id="t_hist",
            worker_id="w_warm",
            customer_id="c1",
            status="completed",
            on_time=True,
            created_at=NOW - timedelta(days=50),
        ),
        Assignment(
            assignment_id="a2_other",
            task_id="t2",
            worker_id="w_other",
            customer_id="c1",
            status="completed",
            on_time=True,
            created_at=NOW - timedelta(days=10),
        ),
    ]
    feedback = [
        Feedback(
            feedback_id="f1",
            assignment_id="a1",
            worker_id="w_good",
            task_id="t_past",
            overall_rating=5,
            created_at=NOW - timedelta(days=19),
        )
    ]
    return Store(
        workers=[good, new, bad, overloaded, breach, full, low, other, warm, cold],
        customers=[customer],
        tasks=[t1, t_empty, t_past, t2, t_hist],
        assignments=assignments,
        feedback=feedback,
    )


@pytest.fixture
def software_task() -> Task:
    return Task(
        task_id="t_soft",
        customer_id="c1",
        title="Build website",
        description="需求文档；前端页面；测试报告",
        category="software_dev",
        required_skills={"python": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=NOW + timedelta(days=14),
        region="CN",
        remote_ok=True,
    )


@pytest.fixture
def client(small_store: Store, tmp_path) -> TestClient:
    return TestClient(
        create_app(
            small_store,
            weights_dir=tmp_path,
            events_dir=tmp_path / "events",
            exploration_seed=42,
        )
    )


@pytest.fixture
def split_task_factory():
    def make(
        description: str,
        category: str = "software_dev",
        estimated_hours: float = 40,
        budget: float = 20000,
        **overrides,
    ):
        values = dict(
            task_id="t_split",
            customer_id="c1",
            title="测试任务",
            description=description,
            category=category,
            required_skills={"backend": 3},
            required_level=2,
            difficulty=3,
            priority=3,
            estimated_hours=estimated_hours,
            deadline=datetime.now(timezone.utc) + timedelta(days=14),
            region="CN",
            remote_ok=True,
            budget=budget,
        )
        values.update(overrides)
        return Task(**values)

    return make


@pytest.fixture
def split_draft_factory():
    from app.chains.decompose import decompose
    from app.data.templates import load_templates

    templates = load_templates("data/chain_templates/common_task_chains.json")

    def make(task):
        return decompose(task, templates[task.category])

    return make


@pytest.fixture
def make_draft():
    from app.domain import DecompositionDraft, TaskChain

    def make(nodes):
        chain = TaskChain(
            chain_id="ch_make",
            root_task_id="t1",
            customer_id="c1",
            deadline=NOW + timedelta(days=7),
            budget=10000,
            nodes=list(nodes),
        )
        return DecompositionDraft(
            draft_id="d_make",
            task_id="t1",
            template_id="make",
            variant="standard",
            chain=chain,
            requirements=[],
            coverage={},
        )

    return make
