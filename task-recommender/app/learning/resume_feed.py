"""Serving-parity push feed for the natural-language resume demo.

The demo runs on its own synthetic marketplace so the full recommendation
path can be exercised without touching the main store:

* ItemCF / reputation history exists for every task
* SemanticMatcher and AcceptanceModel are fitted on the demo store
* ``is_eligible`` hard constraints gate the candidate pool
* the draft worker gets a personal weight profile
* epsilon-greedy exploration assigns exact propensities
* impressions and accept/reject events are recorded on the demo store
"""

from __future__ import annotations

import os
import uuid
from collections import Counter

from app.config import DEFAULT_WEIGHTS
from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.domain import UserWeightProfile, Worker
from app.events import EventService
from app.features import fuse_scores
from app.learning.capability import (
    auto_completion,
    evaluate_capability,
    normalize_completion,
)
from app.learning.exploration import ExplorationPolicy
from app.learning.weights import KEYS, project_weights, validate_weights
from app.personalization.profile import build_profile
from app.personalization.segments import Segmenter
from app.personalization.user_weights import PersonalizationService
from app.service import RecommendationService, is_eligible
from app.serving import serving_components
from app.upload.analyze import worker_from_draft

RESUME_LEARNING_RATE = 0.1
DEFAULT_BATCH = 5
MAX_BATCH = 10
DEFAULT_RETRIEVAL = 300
DEFAULT_WORKERS = 200
DEFAULT_TASKS = 2000
DEFAULT_ASSIGNMENTS = 12000
EXTRA_SEED = 20261114

FEATURE_LABELS = {
    "reputation": "信誉",
    "skill": "技能匹配",
    "expertise": "专业度",
    "collaborative": "协同",
    "preference": "历史偏好",
    "load": "负载",
    "customer_preference": "客户偏好",
}

CATEGORY_LABELS = {
    "brand_design": "品牌设计",
    "consulting_research": "咨询调研",
    "content_writing": "内容写作",
    "data_annotation": "数据标注",
    "ecommerce_ops": "电商运营",
    "marketing_campaign": "营销活动",
    "recruitment": "招聘",
    "software_dev": "软件开发",
    "training_course": "培训课程",
    "translation_localization": "翻译本地化",
    "ui_ux_design": "UI/UX 设计",
    "video_production": "视频制作",
}


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def build_resume_demo_store(
    n_workers: int | None = None,
    n_tasks: int | None = None,
    n_assignments: int | None = None,
    seed: int = EXTRA_SEED,
) -> Store:
    """Build the dedicated marketplace used by the resume push demo."""
    workers = n_workers if n_workers is not None else _env_int(
        "RESUME_DEMO_WORKERS", DEFAULT_WORKERS
    )
    tasks = n_tasks if n_tasks is not None else _env_int(
        "RESUME_DEMO_TASKS", DEFAULT_TASKS
    )
    assignments = (
        n_assignments
        if n_assignments is not None
        else _env_int("RESUME_DEMO_ASSIGNMENTS", DEFAULT_ASSIGNMENTS)
    )
    workers = max(4, workers)
    tasks = max(4, tasks)
    assignments = max(0, assignments)
    dataset = generate_dataset(
        n_workers=workers,
        n_tasks=tasks,
        n_assignments=assignments,
        seed=seed,
    )
    return Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=list(dataset.train) + list(dataset.test),
        feedback=dataset.feedback,
        events=dataset.events,
        impressions=dataset.impressions,
    )


def _worker(draft) -> Worker:
    if not isinstance(draft, dict):
        raise ValueError("draft must be an object")
    try:
        worker = worker_from_draft(draft)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid resume draft") from error
    if not worker.name or not worker.skills:
        raise ValueError("invalid resume draft")
    return worker


def _string_list(value, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [str(item) for item in value]


def _completion_records(value) -> dict[str, dict]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ValueError("completion_records must be a list")
    records = {}
    for record in value:
        if not isinstance(record, dict):
            continue
        task_id = str(record.get("task_id") or "")
        normalized = normalize_completion(record)
        if task_id and normalized is not None:
            records[task_id] = normalized
    return records


def _capability(
    draft, history, features, scores, completions=None
) -> dict:
    items = []
    for task_id in dict.fromkeys(history):
        if task_id in features:
            item = {
                "task_id": task_id,
                "score": scores[task_id],
                "load": features[task_id].get(
                    "load", scores[task_id]
                ),
            }
            if completions and task_id in completions:
                item["completion"] = completions[task_id]
            items.append(item)
    return evaluate_capability(draft, items)


def _feed_item(
    store: Store,
    task_id: str,
    score: float,
    rank: int,
    features,
    weights,
    propensity: float,
) -> dict:
    task = store.tasks[task_id]
    label = CATEGORY_LABELS.get(task.category, task.category)
    deadline = task.deadline.strftime("%m-%d")
    contributions = sorted(
        ((key, features[key] * weights[key]) for key in KEYS),
        key=lambda item: item[1],
        reverse=True,
    )[:2]
    return {
        "id": task_id,
        "title": task.title,
        "subtitle": f"{label} · ¥{task.budget:.0f} · 截止 {deadline}",
        "category": task.category,
        "category_label": label,
        "budget": task.budget,
        "deadline": task.deadline.isoformat(),
        "description": task.description,
        "requirements": list(task.requirements[:5]),
        "difficulty": task.difficulty,
        "estimated_hours": task.estimated_hours,
        "customer_name": (
            store.customers[task.customer_id].name
            if task.customer_id in store.customers
            else ""
        ),
        "score": round(score, 6),
        "rank": rank,
        "propensity": round(float(propensity), 6),
        "features": {key: round(features[key], 4) for key in KEYS},
        "reasons": [
            f"{FEATURE_LABELS[key]} {value:.2f}"
            for key, value in contributions
        ],
        "completion": auto_completion(features, score),
    }


def _profile(worker: Worker) -> dict:
    categories = sorted(
        worker.preferred_categories.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:4]
    return {
        "worker_id": worker.worker_id,
        "name": worker.name,
        "region": worker.region,
        "level": worker.level,
        "expected_pay": worker.expected_pay,
        "skills": sorted(
            worker.skills.items(), key=lambda item: item[1], reverse=True
        )[:8],
        "categories": [
            {
                "key": category,
                "label": CATEGORY_LABELS.get(category, category),
                "score": round(score, 3),
            }
            for category, score in categories
        ],
    }


def _retrieval_score(worker: Worker, task) -> float:
    category = float(
        worker.preferred_categories.get(task.category, 0.0)
    )
    skills = task.required_skills
    if skills:
        overlap = sum(
            min(
                float(worker.skills.get(skill, 0))
                / max(1, minimum),
                1.0,
            )
            for skill, minimum in skills.items()
        ) / len(skills)
    else:
        overlap = 0.5
    return 0.7 * category + 0.3 * overlap


def _retrieve(
    store: Store, worker: Worker, limit: int
) -> tuple[int, set[str]]:
    """Cheap retrieval stage over all hard-eligible open tasks.

    Skill requirements stay a soft ranking signal for the demo (they are
    still part of the seven features), while status/level/capacity/breach/
    assignment remain hard gates. This keeps a continuous feed without
    pretending every retrieved task is a strict skill match.
    """
    eligible = []
    for task in store.tasks.values():
        ok, _ = is_eligible(
            worker,
            task,
            store,
            now=store.reference_time,
            require_skills=False,
        )
        if ok:
            eligible.append(task)
    ranked = sorted(
        eligible,
        key=lambda task: (
            _retrieval_score(worker, task),
            task.task_id,
        ),
        reverse=True,
    )
    return len(eligible), {
        task.task_id for task in ranked[: max(0, limit)]
    }


def _personal_profile(
    store: Store, worker: Worker, raw_weights, sample_count: int
) -> UserWeightProfile:
    profile = build_profile(worker, "worker", None)
    store.profiles[worker.worker_id] = profile
    if raw_weights is None:
        current = UserWeightProfile(
            user_id=worker.worker_id,
            weights=project_weights(dict(DEFAULT_WEIGHTS)),
            source="global",
            segment_id=profile.segment_id,
            sample_count=0,
            confidence=0.0,
            version="u0000",
            initial_weights=project_weights(dict(DEFAULT_WEIGHTS)),
        )
        store.user_weight_profiles[worker.worker_id] = current
        return current
    if not isinstance(raw_weights, dict):
        raise ValueError("weights must be an object")
    weights = {key: float(raw_weights[key]) for key in KEYS}
    validate_weights(weights)
    weights = project_weights(weights)
    current = UserWeightProfile(
        user_id=worker.worker_id,
        weights=weights,
        source="client",
        segment_id=profile.segment_id,
        sample_count=max(0, int(sample_count)),
        confidence=min(1.0, max(0, sample_count) / (max(0, sample_count) + 20.0)),
        version=f"u{max(0, sample_count):04d}",
        initial_weights=dict(weights),
    )
    store.user_weight_profiles[worker.worker_id] = current
    return current


def _funnel(store: Store, worker_id: str) -> dict:
    impressions = sum(
        1
        for impression in store.impressions
        if impression.query_id == worker_id
        or impression.metadata.get("user_id") == worker_id
    )
    actions = Counter(
        event.action
        for event in store.events
        if event.user_id == worker_id
    )
    return {
        "impressions": impressions,
        "accepts": actions.get("accept", 0),
        "rejects": actions.get("reject", 0),
        "clicks": actions.get("click", 0),
        "applies": actions.get("apply", 0),
    }


def simulate_resume_refresh(
    store: Store,
    payload: dict,
    *,
    exploration: ExplorationPolicy | None = None,
    events: EventService | None = None,
    personalizer: PersonalizationService | None = None,
) -> dict:
    """Return the next pushed batch for a parsed resume (serving parity)."""
    worker = _worker(payload.get("draft"))
    store.workers[worker.worker_id] = worker

    raw_weights = payload.get("weights")
    sample_count = int(payload.get("personal_samples", 0) or 0)
    personal = _personal_profile(
        store, worker, raw_weights, sample_count
    )
    initial_weights = dict(personal.weights)

    if exploration is None:
        exploration = ExplorationPolicy(epsilon=0.1, seed=42)
    if events is None:
        events = EventService(store)
    if personalizer is None:
        personalizer = PersonalizationService(
            store, Segmenter(seed=42), DEFAULT_WEIGHTS
        )
    personalizer.store = store
    semantic_matcher, acceptance_model = serving_components(store)

    refresh = max(0, int(payload.get("refresh", 0))) + 1
    batch = int(payload.get("batch_size", DEFAULT_BATCH))
    batch = max(1, min(MAX_BATCH, batch))
    seen = set(_string_list(payload.get("seen"), "seen"))
    accepted = _string_list(payload.get("accepted"), "accepted")
    skipped = _string_list(payload.get("skipped"), "skipped")
    accepted_history = _string_list(
        payload.get("accepted_history"), "accepted_history"
    )
    completions = _completion_records(
        payload.get("completion_records")
    )
    # Only evaluated tasks count toward capability. An accepted-but-not-
    # submitted task affects weight learning/events, not the fulfillment score.
    capability_history = list(dict.fromkeys(accepted_history))
    previous_request = payload.get("request_id")
    try:
        retrieval_limit = int(
            payload.get("retrieval_limit", DEFAULT_RETRIEVAL)
        )
    except (TypeError, ValueError):
        retrieval_limit = DEFAULT_RETRIEVAL
    retrieval_limit = max(10, min(2000, retrieval_limit))
    pool_size, retrieval_ids = _retrieve(
        store, worker, retrieval_limit
    )

    service = RecommendationService(
        store,
        weights=initial_weights,
        semantic_matcher=semantic_matcher,
        acceptance_model=acceptance_model,
    )

    # Record user actions against the previous impression. Duplicate or
    # stale events are ignored; event logging must never fail the refresh.
    if previous_request:
        for task_id in accepted:
            try:
                events.record_event(
                    str(previous_request),
                    task_id,
                    "accept",
                    user_id=worker.worker_id,
                    role="worker",
                    metadata={
                        "candidate_type": "task",
                        "task_id": task_id,
                    },
                )
            except (KeyError, ValueError):
                pass
        for task_id in skipped:
            try:
                events.record_event(
                    str(previous_request),
                    task_id,
                    "reject",
                    user_id=worker.worker_id,
                    role="worker",
                    metadata={
                        "candidate_type": "task",
                        "task_id": task_id,
                    },
                )
            except (KeyError, ValueError):
                pass

    # Personal pairwise learning: each accepted task is compared with a
    # skipped task, or with the current top-scoring non-accepted task.
    if accepted:
        try:
            ranked_for_negative = service.recommend_tasks(
                worker.worker_id,
                top_n=100,
                user_id=worker.worker_id,
                candidate_ids=retrieval_ids,
                require_skills=False,
            )
        except KeyError:
            ranked_for_negative = []
        accepted_set = set(accepted)
        for task_id in dict.fromkeys(accepted):
            if task_id not in store.tasks:
                continue
            negative = next(
                (item for item in skipped if item in store.tasks),
                None,
            ) or next(
                (
                    item.candidate_id
                    for item in ranked_for_negative
                    if item.candidate_id not in accepted_set
                ),
                None,
            )
            if negative is None or negative == task_id:
                continue
            try:
                chosen_features = service.features_for(
                    task_id, worker.worker_id
                )
                rejected_features = service.features_for(
                    negative, worker.worker_id
                )
                personal = personalizer.update_pair(
                    worker.worker_id,
                    chosen_features,
                    rejected_features,
                )
            except KeyError:
                continue
        initial_weights = dict(initial_weights)
        current_weights = dict(personal.weights)
    else:
        current_weights = dict(initial_weights)

    service = RecommendationService(
        store,
        weights=current_weights,
        semantic_matcher=semantic_matcher,
        acceptance_model=acceptance_model,
    )
    try:
        candidates = service.recommend_tasks(
            worker.worker_id,
            top_n=100,
            user_id=worker.worker_id,
            candidate_ids=retrieval_ids,
            require_skills=False,
        )
    except KeyError as error:
        raise ValueError("worker not found in demo store") from error

    retrieval_pool = len(retrieval_ids)
    unseen = [
        candidate
        for candidate in candidates
        if candidate.candidate_id not in seen
    ]
    if not unseen:
        return {
            "refresh": refresh,
            "weights": current_weights,
            "delta": {
                key: current_weights[key] - initial_weights[key]
                for key in KEYS
            },
            "feed": [],
            "request_id": None,
            "seen_count": len(seen),
            "pool_size": pool_size,
            "retrieval_pool": retrieval_pool,
            "exhausted": True,
            "profile": _profile(worker),
            "personalization": _personalization(personal),
            "funnel": _funnel(store, worker.worker_id),
            "capability": _capability(
                payload["draft"],
                capability_history,
                {},
                {},
                completions,
            ),
        }

    explored = exploration.rerank(unseen, k=min(batch, len(unseen)))
    request_id = uuid.uuid4().hex
    candidate_ids = [item.candidate_id for item in explored]
    propensities = {
        item.candidate_id: float(item.propensity) for item in explored
    }
    events.record_impression(
        request_id,
        worker.worker_id,
        candidate_ids,
        propensities,
        "epsilon_greedy_topk",
        metadata={
            "candidate_type": "task",
            "user_id": worker.worker_id,
        },
    )

    features_by_task = {
        item.candidate_id: service.features_for(
            item.candidate_id, worker.worker_id
        )
        for item in explored
    }
    scores_by_task = {
        item.candidate_id: item.score for item in explored
    }
    feed = [
        _feed_item(
            store,
            item.candidate_id,
            item.score,
            rank,
            features_by_task[item.candidate_id],
            current_weights,
            item.propensity,
        )
        for rank, item in enumerate(explored, start=1)
    ]

    history_features = {}
    history_scores = {}
    for task_id in dict.fromkeys(capability_history):
        if task_id not in store.tasks:
            continue
        try:
            features_for_task = service.features_for(
                task_id, worker.worker_id
            )
        except KeyError:
            continue
        history_features[task_id] = features_for_task
        history_scores[task_id] = fuse_scores(
            features_for_task, current_weights
        )

    return {
        "refresh": refresh,
        "weights": current_weights,
        "delta": {
            key: current_weights[key] - initial_weights[key]
            for key in KEYS
        },
        "feed": feed,
        "request_id": request_id,
        "seen_count": len(seen),
        "pool_size": pool_size,
        "retrieval_pool": retrieval_pool,
        "exhausted": False,
        "profile": _profile(worker),
        "personalization": _personalization(personal),
        "funnel": _funnel(store, worker.worker_id),
        "capability": _capability(
            payload["draft"],
            capability_history,
            history_features,
            history_scores,
            completions,
        ),
    }


def _personalization(profile: UserWeightProfile) -> dict:
    return {
        "source": profile.source,
        "segment_id": profile.segment_id,
        "sample_count": profile.sample_count,
        "confidence": round(profile.confidence, 4),
        "version": profile.version,
    }
