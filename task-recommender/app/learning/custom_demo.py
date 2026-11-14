"""Stateless simulation for the user-supplied custom demo case.

The request carries the custom task/worker, the current seven weights and
the selected candidate. Everything else (candidate pool, features, learner)
is rebuilt from the active store, so no session state is stored server-side
and nothing the user types is persisted.
"""

from __future__ import annotations

from datetime import timedelta

from app.config import DEFAULT_WEIGHTS
from app.data.store import Store
from app.domain import Task, Worker
from app.features import fuse_scores
from app.learning.online import OnlineWeightLearner
from app.learning.weights import KEYS, project_weights, validate_weights
from app.personalization.segments import apply_preference_bias
from app.service import RecommendationService

CUSTOM_TASK_ID = "custom_task"
CUSTOM_WORKER_ID = "custom_worker"
CUSTOM_LEARNING_RATE = 0.1
PREFERENCE_KEYS = frozenset(
    {"quality", "speed", "specialty", "flexibility"}
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _preferences(value) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("preferences must be an object")
    output = {}
    for key, raw in value.items():
        if key not in PREFERENCE_KEYS:
            raise ValueError(f"unknown preference: {key}")
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"preference {key} must be numeric") from exc
        output[key] = _clamp(number, 0.0, 1.0)
    return output


def _initial_weights(preferences: dict[str, float]) -> dict[str, float]:
    return project_weights(
        apply_preference_bias(DEFAULT_WEIGHTS, preferences)
    )


def _required_skills(value) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("required_skills must be an object")
    skills = {}
    for key, raw in value.items():
        try:
            level = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"skill level must be numeric: {key}") from exc
        skills[str(key)] = max(1, min(5, level))
    return skills


def _build_task(store: Store, payload: dict) -> Task:
    category = str(payload.get("category") or "")
    known = {task.category for task in store.tasks.values()}
    if category not in known:
        raise ValueError(f"unknown category: {category}")
    now = store.reference_time
    try:
        deadline_days = max(1, int(payload.get("deadline_days", 14)))
        difficulty = max(1, min(5, int(payload.get("difficulty", 3))))
        required_level = max(1, min(5, int(payload.get("required_level", 3))))
        budget = max(0.0, float(payload.get("budget", 0.0)))
        estimated_hours = max(0.5, float(payload.get("estimated_hours", 8)))
    except (TypeError, ValueError) as exc:
        raise ValueError("task numbers are invalid") from exc
    required_skills = _required_skills(payload.get("required_skills"))
    return Task(
        task_id=CUSTOM_TASK_ID,
        customer_id=next(iter(store.customers)),
        title=str(payload.get("title") or "自定义任务")[:120],
        category=category,
        required_skills=required_skills,
        required_level=required_level,
        difficulty=difficulty,
        priority=1,
        estimated_hours=estimated_hours,
        deadline=now + timedelta(days=deadline_days),
        region=str(payload.get("region") or "CN")[:40],
        remote_ok=bool(payload.get("remote_ok", True)),
        description=str(payload.get("description") or "")[:2000],
        status="open",
        budget=budget,
        budget_min=budget,
        budget_max=budget,
        created_at=now,
        required_skill_weights={key: 1.0 for key in required_skills},
    )


def _build_worker(payload: dict) -> Worker:
    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, dict) or not raw_skills:
        raise ValueError("worker skills must be a non-empty object")
    skills = {}
    for key, raw in raw_skills.items():
        try:
            skills[str(key)] = max(1, min(5, int(raw)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"skill level must be numeric: {key}") from exc
    raw_categories = payload.get("preferred_categories") or {}
    if not isinstance(raw_categories, dict):
        raise ValueError("preferred_categories must be an object")
    categories = {
        str(key): _clamp(float(value), 0.0, 1.0)
        for key, value in raw_categories.items()
    }
    try:
        expected_pay = max(0.0, float(payload.get("expected_pay", 0.0)))
        current_load = max(0.0, float(payload.get("current_load_hours", 0.0)))
        capacity = max(1.0, float(payload.get("capacity_hours", 40.0)))
        level = max(1, min(5, int(payload.get("level", 3))))
    except (TypeError, ValueError) as exc:
        raise ValueError("worker numbers are invalid") from exc
    return Worker(
        worker_id=CUSTOM_WORKER_ID,
        name=str(payload.get("name") or "自定义画像")[:60],
        skills=skills,
        specialties=dict(skills),
        level=level,
        capacity_hours=capacity,
        current_load_hours=current_load,
        preferred_categories=categories,
        preferred_difficulty=(2, 4),
        region=str(payload.get("region") or "CN")[:40],
        remote_ok=bool(payload.get("remote_ok", True)),
        status="active",
        expected_pay=expected_pay,
        certifications={},
        ratings=[],
    )


def _store_with(
    base: Store, mode: str, entity: Task | Worker
) -> Store:
    workers = {worker.worker_id: worker for worker in base.workers.values()}
    tasks = {task.task_id: task for task in base.tasks.values()}
    if mode == "task":
        tasks[entity.task_id] = entity  # type: ignore[index]
    else:
        workers[entity.worker_id] = entity  # type: ignore[index]
    return Store(
        workers=list(workers.values()),
        customers=list(base.customers.values()),
        tasks=list(tasks.values()),
        assignments=list(base.assignments),
        feedback=list(base.feedback),
        events=list(base.events),
        impressions=list(base.impressions),
    )


def _feed(
    store: Store,
    service: RecommendationService,
    mode: str,
    weights: dict[str, float],
) -> tuple[list[dict], dict[str, dict[str, float]], int]:
    if mode == "task":
        candidates = [
            worker_id
            for worker_id in store.workers
            if worker_id != CUSTOM_WORKER_ID
        ]
    else:
        candidates = [
            task_id
            for task_id, task in store.tasks.items()
            if task_id != CUSTOM_TASK_ID and task.status == "open"
        ]
    if not candidates:
        raise ValueError("no candidates available")

    features = {}
    for candidate in candidates:
        if mode == "task":
            features[candidate] = service.features_for(
                CUSTOM_TASK_ID, candidate
            )
        else:
            features[candidate] = service.features_for(
                candidate, CUSTOM_WORKER_ID
            )
    scores = {
        candidate: fuse_scores(features[candidate], weights)
        for candidate in candidates
    }
    ranked = sorted(candidates, key=scores.get, reverse=True)
    top = ranked[:5]

    items = []
    for rank, candidate in enumerate(top, start=1):
        if mode == "task":
            worker = store.workers[candidate]
            title = worker.name
            subtitle = f"{worker.region} · L{worker.level}"
        else:
            task = store.tasks[candidate]
            title = task.title
            subtitle = f"{task.category} · ¥{task.budget:.0f}"
        items.append(
            {
                "id": candidate,
                "title": title,
                "subtitle": subtitle,
                "score": round(scores[candidate], 6),
                "rank": rank,
                "features": {
                    key: round(features[candidate][key], 4)
                    for key in KEYS
                },
            }
        )
    return items, features, len(candidates)


def simulate_custom_step(base_store: Store, payload: dict) -> dict:
    """Return one recommendation step for a user-supplied case."""
    mode = str(payload.get("mode") or "")
    if mode not in {"task", "worker"}:
        raise ValueError("mode must be 'task' or 'worker'")
    preferences = _preferences(payload.get("preferences"))

    raw_weights = payload.get("weights")
    if raw_weights is None:
        weights = _initial_weights(preferences)
    else:
        if not isinstance(raw_weights, dict):
            raise ValueError("weights must be an object")
        weights = {key: float(raw_weights[key]) for key in KEYS}
        validate_weights(weights)
        weights = project_weights(weights)

    round_number = max(1, int(payload.get("round", 1)))
    choice = payload.get("choice")

    if mode == "task":
        if not isinstance(payload.get("task"), dict):
            raise ValueError("task payload is required")
        entity = _build_task(base_store, payload["task"])
    else:
        if not isinstance(payload.get("worker"), dict):
            raise ValueError("worker payload is required")
        entity = _build_worker(payload["worker"])

    store = _store_with(base_store, mode, entity)
    service = RecommendationService(store, weights=weights)
    feed, features, pool_size = _feed(store, service, mode, weights)
    delta = {key: 0.0 for key in KEYS}

    if choice is not None:
        shown = [item["id"] for item in feed]
        if choice not in shown:
            raise ValueError("choice must be one of the current feed items")
        negative = next(
            item["id"] for item in feed if item["id"] != choice
        )
        learner = OnlineWeightLearner(
            prior=weights,
            weights=weights,
            learning_rate=CUSTOM_LEARNING_RATE,
        )
        updated = learner.update_pair(
            features[choice], features[negative]
        )
        delta = {
            key: updated[key] - weights[key] for key in KEYS
        }
        weights = updated
        round_number += 1
        feed, features, pool_size = _feed(
            store, service, mode, weights
        )

    return {
        "mode": mode,
        "round": round_number,
        "choice": choice,
        "weights": weights,
        "delta": delta,
        "feed": feed,
        "pool_size": pool_size,
        "note": (
            "自定义案例没有 ground truth，因此不计算命中率；"
            "学习信号来自你的点击，特征与权重更新使用真实代码路径。"
        ),
    }
