"""Build the linked two-sided learning demo from real recommendation code.

The demo intentionally runs the production ``OnlineWeightLearner`` over
serving-parity features. Only the simulated human choices are synthetic:
each side has a hidden preference vector and always picks the candidate it
likes most among the five cards that are actually shown. Every weight update
therefore comes from the same projected pairwise gradient used by the app.

The returned payload contains:

* ``scenarios`` — 27 tag combinations for the interactive main case
  (3 domains x 3 worker preferences x 3 customer preferences)
* ``case_wall`` — eight cross-domain baseline trajectories proving the effect
  is not a single cherry-picked pair
* ``options`` — categories/skills/regions for the custom-case form
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.config import DEFAULT_WEIGHTS
from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.features import fuse_scores
from app.learning.online import OnlineWeightLearner
from app.learning.weights import KEYS, project_weights
from app.personalization.segments import apply_preference_bias
from app.service import RecommendationService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = PROJECT_ROOT / "reports"

WORKER_LEARNING_RATE = 0.15
CUSTOMER_LEARNING_RATE = 0.05
DEFAULT_ROUNDS = 20

WORKER_LATENT = project_weights(
    {
        "reputation": 0.30,
        "skill": 0.13,
        "expertise": 0.12,
        "collaborative": 0.08,
        "preference": 0.07,
        "load": 0.25,
        "customer_preference": 0.05,
    }
)
CUSTOMER_LATENT = project_weights(
    {
        "reputation": 0.40,
        "skill": 0.10,
        "expertise": 0.20,
        "collaborative": 0.04,
        "preference": 0.02,
        "load": 0.02,
        "customer_preference": 0.22,
    }
)

#: Deterministic pair for the interactive main case.
PREFERRED_PAIR = ("t0119", "w0097")

#: Cross-domain cases for the wall. Every pair is a latent fixed point:
#: the task is the worker's true best task and the worker is the task's true
#: best worker, so the baseline trajectory has a clear "right answer".
CASE_WALL_PAIRS = (
    ("t0119", "w0097"),  # video_production
    ("t0434", "w0004"),  # ecommerce_ops
    ("t0044", "w0056"),  # ui_ux_design
    ("t0218", "w0031"),  # consulting_research
    ("t0290", "w0077"),  # content_writing
    ("t0021", "w0072"),  # data_annotation
    ("t0325", "w0054"),  # training_course
    ("t0053", "w0052"),  # brand_design
)

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

DOMAIN_OPTIONS = (
    {"key": "all", "label": "不限"},
    {"key": "video_production", "label": "视频制作"},
    {"key": "ecommerce_ops", "label": "电商运营"},
)

PREFERENCE_OPTIONS = (
    {"key": "none", "label": "未选择", "values": {}},
    {"key": "quality", "label": "质量优先", "values": {"quality": 0.8}},
    {"key": "speed", "label": "速度优先", "values": {"speed": 0.8}},
)

POOL_ABOVE = 2
POOL_BELOW = 3


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    dot = sum(left[key] * right[key] for key in KEYS)
    left_norm = math.sqrt(sum(left[key] ** 2 for key in KEYS))
    right_norm = math.sqrt(sum(right[key] ** 2 for key in KEYS))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _build_store(dataset) -> Store:
    return Store(
        workers=dataset.workers,
        customers=dataset.customers,
        tasks=dataset.tasks,
        assignments=dataset.train,
        feedback=dataset.feedback,
        events=dataset.events,
        impressions=dataset.impressions,
    )


def _pick_pair(store: Store) -> tuple[str, str]:
    task_id, worker_id = PREFERRED_PAIR
    if task_id in store.tasks and worker_id in store.workers:
        return task_id, worker_id
    raise RuntimeError(
        "demo dataset no longer contains the preferred task/worker pair"
    )


def _default_score(features: dict[str, float]) -> float:
    return fuse_scores(features, DEFAULT_WEIGHTS)


def _select_pool(candidates, gold, score) -> list[str]:
    above = sorted(
        (
            candidate
            for candidate in candidates
            if candidate != gold and score(candidate) > score(gold)
        ),
        key=score,
        reverse=True,
    )[:POOL_ABOVE]
    below = sorted(
        (
            candidate
            for candidate in candidates
            if candidate != gold and score(candidate) <= score(gold)
        ),
        key=score,
        reverse=True,
    )[:POOL_BELOW]
    return [gold, *above, *below]


def _worker_variant(worker, domain: str):
    if domain == "all":
        return worker
    variant = copy.deepcopy(worker)
    variant.preferred_categories = {domain: 1.0}
    return variant


def _store_with_worker(base: Store, worker) -> Store:
    workers = [
        worker if item.worker_id == worker.worker_id else item
        for item in base.workers.values()
    ]
    return Store(
        workers=workers,
        customers=list(base.customers.values()),
        tasks=list(base.tasks.values()),
        assignments=list(base.assignments),
        feedback=list(base.feedback),
        events=list(base.events),
        impressions=list(base.impressions),
    )


def _run_side(
    items: list[str],
    features: dict[str, dict[str, float]],
    latent: dict[str, float],
    learning_rate: float,
    rounds: int,
    label,
    profile,
    initial_weights: dict[str, float],
) -> list[dict]:
    weights = project_weights(dict(initial_weights))
    output: list[dict] = []

    for round_number in range(1, rounds + 1):
        scores = {
            item: fuse_scores(features[item], weights) for item in items
        }
        ranked = sorted(items, key=scores.get, reverse=True)
        shown = ranked[:5]
        latent_scores = {
            item: sum(latent[key] * features[item][key] for key in KEYS)
            for item in items
        }
        gold = max(latent_scores, key=latent_scores.get)
        chosen = max(shown, key=lambda item: latent_scores[item])
        rejected = max(
            (item for item in shown if item != chosen),
            key=lambda item: scores[item],
        )

        feed = [
            {
                "id": item,
                "title": label(item)[0],
                "subtitle": label(item)[1],
                "score": round(scores[item], 6),
                "rank": index + 1,
                "is_gold": item == gold,
                "is_chosen": item == chosen,
            }
            for index, item in enumerate(shown)
        ]
        hit = ranked[0] == gold
        profile_snapshot = profile(
            chosen=chosen,
            gold=gold,
            round_number=round_number,
        )

        learner = OnlineWeightLearner(
            prior=weights,
            weights=weights,
            learning_rate=learning_rate,
        )
        weights = learner.update_pair(
            features[chosen], features[rejected]
        )

        output.append(
            {
                "round": round_number,
                "feed": feed,
                "chosen": chosen,
                "rejected": rejected,
                "gold": gold,
                "gold_rank": ranked.index(gold) + 1,
                "gold_shown": gold in shown,
                "hit": hit,
                "weights_after": dict(weights),
                "delta": {
                    key: weights[key] - (
                        output[-1]["weights_after"][key]
                        if output
                        else initial_weights[key]
                    )
                    for key in KEYS
                },
                "cosine_after": _cosine(weights, latent),
                "profile": profile_snapshot,
            }
        )

    cumulative = 0
    for round_data in output:
        cumulative += int(round_data["hit"])
        round_data["hit_rate"] = cumulative / round_data["round"]

    return output


def _task_label(store: Store, task_id: str):
    task = store.tasks[task_id]
    return task.title, f"{task.category} · ¥{task.budget:.0f}"


def _worker_label(store: Store, worker_id: str):
    worker = store.workers[worker_id]
    return worker.name, f"{worker.region} · L{worker.level}"


def _scenario(store: Store, task_id: str, worker_id: str) -> dict:
    task = store.tasks[task_id]
    worker = store.workers[worker_id]
    customer = store.customers[task.customer_id]
    return {
        "pair": {"task_id": task_id, "worker_id": worker_id},
        "task": {
            "id": task.task_id,
            "title": task.title,
            "category": task.category,
            "category_label": CATEGORY_LABELS.get(
                task.category, task.category
            ),
            "description": task.description,
            "budget": task.budget,
            "budget_min": task.budget_min,
            "budget_max": task.budget_max,
            "deadline": task.deadline.isoformat(),
            "region": task.region,
            "remote_ok": task.remote_ok,
            "requirements": list(task.requirements[:4]),
        },
        "worker": {
            "id": worker.worker_id,
            "name": worker.name,
            "level": worker.level,
            "region": worker.region,
            "skills": sorted(
                worker.skills.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:4],
            "rating": (
                round(sum(worker.ratings) / len(worker.ratings), 2)
                if worker.ratings
                else None
            ),
            "completed": worker.completed,
            "on_time": worker.on_time,
        },
        "customer": {
            "id": customer.customer_id,
            "name": customer.name,
            "region": customer.region,
        },
        "latent": {
            "worker": dict(WORKER_LATENT),
            "customer": dict(CUSTOMER_LATENT),
        },
        "initial_weights": dict(DEFAULT_WEIGHTS),
    }


def _customer_profile():
    selections = 0
    acceptance_scores: list[float] = []

    def snapshot(chosen: str, gold: str, round_number: int) -> dict:
        nonlocal selections
        selections += 1
        score = 5.0 if chosen == gold else 3.0
        acceptance_scores.append(score)
        return {
            "selections": selections,
            "last_acceptance": score,
            "avg_acceptance": round(
                sum(acceptance_scores) / len(acceptance_scores), 2
            ),
            "samples": round_number,
        }

    return snapshot


def _earnings_profile(store: Store, worker_id: str):
    """Worker profile that accumulates the budget of each accepted task."""

    worker = store.workers[worker_id]
    accepted = 0
    earnings = 0.0

    def snapshot(chosen: str, gold: str, round_number: int) -> dict:
        nonlocal accepted, earnings
        accepted += 1
        earnings += store.tasks[chosen].budget
        return {
            "accepted": accepted,
            "simulated_earnings": round(earnings, 2),
            "rating": (
                round(sum(worker.ratings) / len(worker.ratings), 2)
                if worker.ratings
                else None
            ),
            "completed": worker.completed,
            "on_time": worker.on_time,
            "samples": round_number,
        }

    return snapshot


def _load_global_data() -> dict:
    benchmark_path = REPORTS_DIR / "benchmark_rounds.json"
    learning_path = REPORTS_DIR / "learning_rounds.json"
    benchmark = []
    learning = {}
    if benchmark_path.exists():
        raw = json.loads(benchmark_path.read_text(encoding="utf-8"))
        benchmark = [
            {
                "round": item["round"],
                "top1": item["metrics"]["top1"],
                "top5": item["metrics"]["top5"],
                "test_top1": item["metrics"].get("test_top1"),
                "test_top5": item["metrics"].get("test_top5"),
            }
            for item in raw
        ]
    if learning_path.exists():
        learning = json.loads(learning_path.read_text(encoding="utf-8"))
    return {
        "available": bool(benchmark or learning),
        "benchmark_rounds": benchmark,
        "learning_rounds": learning,
    }


def _options(store: Store) -> dict:
    categories = sorted({task.category for task in store.tasks.values()})
    skill_counts: Counter[str] = Counter()
    for task in store.tasks.values():
        skill_counts.update(task.required_skills)
    for worker in store.workers.values():
        skill_counts.update(worker.skills)
    regions = sorted({worker.region for worker in store.workers.values()})
    return {
        "categories": [
            {
                "key": category,
                "label": CATEGORY_LABELS.get(category, category),
            }
            for category in categories
        ],
        "skills": [name for name, _ in skill_counts.most_common(20)],
        "regions": regions[:10],
    }


def _prepare_pools(store: Store, service: RecommendationService, task_id: str, worker_id: str):
    task_features_all = {
        candidate: service.features_for(candidate, worker_id)
        for candidate in store.tasks
    }
    worker_features_all = {
        candidate: service.features_for(task_id, candidate)
        for candidate in store.workers
    }
    task_pool = _select_pool(
        list(store.tasks),
        task_id,
        lambda candidate: _default_score(task_features_all[candidate]),
    )
    worker_pool = _select_pool(
        list(store.workers),
        worker_id,
        lambda candidate: _default_score(worker_features_all[candidate]),
    )
    return (
        task_pool,
        worker_pool,
        {candidate: task_features_all[candidate] for candidate in task_pool},
        {candidate: worker_features_all[candidate] for candidate in worker_pool},
    )


def _build_case_wall(store: Store, rounds: int) -> list[dict]:
    wall = []
    for task_id, worker_id in CASE_WALL_PAIRS:
        service = RecommendationService(store)
        (
            task_pool,
            worker_pool,
            task_features,
            worker_features,
        ) = _prepare_pools(store, service, task_id, worker_id)
        worker_rounds = _run_side(
            task_pool,
            task_features,
            WORKER_LATENT,
            WORKER_LEARNING_RATE,
            rounds,
            lambda item: _task_label(store, item),
            _earnings_profile(store, worker_id),
            DEFAULT_WEIGHTS,
        )
        customer_rounds = _run_side(
            worker_pool,
            worker_features,
            CUSTOMER_LATENT,
            CUSTOMER_LEARNING_RATE,
            rounds,
            lambda item: _worker_label(store, item),
            _customer_profile(),
            DEFAULT_WEIGHTS,
        )
        task = store.tasks[task_id]
        worker = store.workers[worker_id]
        wall.append(
            {
                "key": f"{task_id}/{worker_id}",
                "category": task.category,
                "category_label": CATEGORY_LABELS.get(
                    task.category, task.category
                ),
                "task_id": task_id,
                "worker_id": worker_id,
                "task_title": task.title,
                "worker_name": worker.name,
                "worker": {
                    "initial_rank": worker_rounds[0]["gold_rank"],
                    "final_rank": worker_rounds[-1]["gold_rank"],
                    "hit_curve": [
                        round_data["hit_rate"]
                        for round_data in worker_rounds
                    ],
                    "cosine_start": worker_rounds[0]["cosine_after"],
                    "cosine_end": worker_rounds[-1]["cosine_after"],
                },
                "customer": {
                    "initial_rank": customer_rounds[0]["gold_rank"],
                    "final_rank": customer_rounds[-1]["gold_rank"],
                    "hit_curve": [
                        round_data["hit_rate"]
                        for round_data in customer_rounds
                    ],
                    "cosine_start": customer_rounds[0]["cosine_after"],
                    "cosine_end": customer_rounds[-1]["cosine_after"],
                },
            }
        )
    return wall


def build_demo_data(
    seed: int = 42,
    rounds: int = DEFAULT_ROUNDS,
) -> dict:
    """Return the complete two-sided learning trajectory for the demo page."""
    dataset = generate_dataset(seed=seed)
    store = _build_store(dataset)
    service = RecommendationService(store)
    task_id, worker_id = _pick_pair(store)
    (
        task_pool,
        worker_pool,
        base_task_features,
        base_worker_features,
    ) = _prepare_pools(store, service, task_id, worker_id)

    domain_features = {"all": base_task_features}
    for option in DOMAIN_OPTIONS:
        domain = option["key"]
        if domain == "all":
            continue
        variant = _worker_variant(store.workers[worker_id], domain)
        variant_store = _store_with_worker(store, variant)
        variant_service = RecommendationService(variant_store)
        domain_features[domain] = {
            candidate: variant_service.features_for(candidate, worker_id)
            for candidate in task_pool
        }

    worker_labels = lambda item: _task_label(store, item)
    customer_labels = lambda item: _worker_label(store, item)

    scenarios: dict[str, dict] = {}
    for domain in DOMAIN_OPTIONS:
        for worker_preference in PREFERENCE_OPTIONS:
            for customer_preference in PREFERENCE_OPTIONS:
                key = (
                    f"{domain['key']}|{worker_preference['key']}|"
                    f"{customer_preference['key']}"
                )
                worker_initial = apply_preference_bias(
                    DEFAULT_WEIGHTS, worker_preference["values"]
                )
                customer_initial = apply_preference_bias(
                    DEFAULT_WEIGHTS, customer_preference["values"]
                )
                worker_rounds = _run_side(
                    task_pool,
                    domain_features[domain["key"]],
                    WORKER_LATENT,
                    WORKER_LEARNING_RATE,
                    rounds,
                    worker_labels,
                    _earnings_profile(store, worker_id),
                    worker_initial,
                )
                customer_rounds = _run_side(
                    worker_pool,
                    base_worker_features,
                    CUSTOMER_LATENT,
                    CUSTOMER_LEARNING_RATE,
                    rounds,
                    customer_labels,
                    _customer_profile(),
                    customer_initial,
                )
                scenarios[key] = {
                    "key": key,
                    "labels": {
                        "domain": domain["label"],
                        "worker_preference": worker_preference["label"],
                        "customer_preference": customer_preference["label"],
                    },
                    "worker": {
                        "rounds": worker_rounds,
                        "initial_weights": worker_initial,
                    },
                    "customer": {
                        "rounds": customer_rounds,
                        "initial_weights": customer_initial,
                    },
                }

    baseline_key = "all|none|none"
    baseline = scenarios[baseline_key]
    baseline_worker_weights = baseline["worker"]["initial_weights"]
    baseline_customer_weights = baseline["customer"]["initial_weights"]
    baseline_worker_rank = baseline["worker"]["rounds"][0]["gold_rank"]
    baseline_customer_rank = baseline["customer"]["rounds"][0]["gold_rank"]

    for scenario in scenarios.values():
        worker_initial = scenario["worker"]["initial_weights"]
        customer_initial = scenario["customer"]["initial_weights"]
        scenario["tag_effect"] = {
            "worker_initial_rank": scenario["worker"]["rounds"][0][
                "gold_rank"
            ],
            "customer_initial_rank": scenario["customer"]["rounds"][0][
                "gold_rank"
            ],
            "worker_initial_rank_delta": (
                scenario["worker"]["rounds"][0]["gold_rank"]
                - baseline_worker_rank
            ),
            "customer_initial_rank_delta": (
                scenario["customer"]["rounds"][0]["gold_rank"]
                - baseline_customer_rank
            ),
            "worker_weights_delta": {
                key: worker_initial[key] - baseline_worker_weights[key]
                for key in KEYS
            },
            "customer_weights_delta": {
                key: customer_initial[key] - baseline_customer_weights[key]
                for key in KEYS
            },
        }

    return {
        "meta": {
            "seed": seed,
            "rounds": rounds,
            "worker_learning_rate": WORKER_LEARNING_RATE,
            "customer_learning_rate": CUSTOMER_LEARNING_RATE,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": (
                "推荐排序与权重更新使用真实代码路径；人类的点选/验收由隐藏偏好"
                "模拟生成，用于演示学习方向，不代表线上效果。"
            ),
        },
        "variables": {
            "domains": [dict(option) for option in DOMAIN_OPTIONS],
            "worker_preferences": [
                dict(option) for option in PREFERENCE_OPTIONS
            ],
            "customer_preferences": [
                dict(option) for option in PREFERENCE_OPTIONS
            ],
        },
        "baseline_key": baseline_key,
        "scenario": _scenario(store, task_id, worker_id),
        "worker": baseline["worker"],
        "customer": baseline["customer"],
        "scenarios": scenarios,
        "case_wall": _build_case_wall(store, rounds),
        "options": _options(store),
        "global": _load_global_data(),
    }
