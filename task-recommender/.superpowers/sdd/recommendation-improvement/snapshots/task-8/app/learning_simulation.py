"""20-round learning-vs-no-learning customer choice simulation.

Controlled experiment: customers choose among recommended workers. The true
choice is driven by a quality-heavy latent weight vector; the no-learning arm
keeps a deliberately wrong speed-heavy vector. The learning arm uses pairwise
hard-negative updates and should move toward the true preference.
"""

from __future__ import annotations

import math
import random

from app.features import candidate_features
from app.learning.online import OnlineWeightLearner
from app.learning.weights import project_weights
from app.service import is_eligible

SIM_TRUE_WEIGHTS = project_weights(
    {
        "reputation": 0.40,
        "skill": 0.20,
        "expertise": 0.15,
        "collaborative": 0.07,
        "preference": 0.05,
        "load": 0.06,
        "customer_preference": 0.07,
    }
)

SIM_INITIAL_WEIGHTS = project_weights(
    {
        "reputation": 0.25,
        "skill": 0.15,
        "expertise": 0.10,
        "collaborative": 0.10,
        "preference": 0.05,
        "load": 0.25,
        "customer_preference": 0.10,
    }
)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(a.get(key, 0.0) * b.get(key, 0.0) for key in keys)
    norm_a = math.sqrt(sum(a.get(key, 0.0) ** 2 for key in keys))
    norm_b = math.sqrt(sum(b.get(key, 0.0) ** 2 for key in keys))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _gumbel(rng: random.Random) -> float:
    value = max(rng.random(), 1e-12)
    return -math.log(-math.log(value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def simulate_learning_rounds(
    store,
    customer_ids: list[str],
    rounds: int = 20,
    selections_per_round: int = 50,
    candidate_pool: int = 20,
    top_k: int = 5,
    seed: int = 42,
    learning_rate: float = 0.1,
) -> dict:
    for customer_id in customer_ids:
        if customer_id not in store.customers:
            raise ValueError(f"unknown customer {customer_id}")

    task_candidates = []
    for task in store.tasks.values():
        if task.status != "open":
            continue
        candidates = [
            worker
            for worker in store.workers.values()
            if is_eligible(
                worker, task, store, now=store.reference_time
            )[0]
        ]
        if len(candidates) >= 2:
            task_candidates.append((task, candidates))
    if not task_candidates:
        raise ValueError("no tasks with at least two eligible workers")

    learners = {
        customer_id: OnlineWeightLearner(
            prior=SIM_INITIAL_WEIGHTS,
            weights=SIM_INITIAL_WEIGHTS,
            learning_rate=learning_rate,
            l2_lambda=0.01,
        )
        for customer_id in customer_ids
    }

    result = {
        "rounds": list(range(1, rounds + 1)),
        "learning_top1": [],
        "learning_top5": [],
        "baseline_top1": [],
        "baseline_top5": [],
        "learning_cosine": [],
        "baseline_cosine": [],
        "meta": {
            "mode": "customer-selects-worker",
            "users": len(customer_ids),
            "selections_per_round": selections_per_round,
            "candidate_pool": candidate_pool,
            "top_k": top_k,
            "seed": seed,
            "true_weights": dict(SIM_TRUE_WEIGHTS),
            "initial_weights": dict(SIM_INITIAL_WEIGHTS),
        },
    }

    for round_index in range(rounds):
        learn_top1: list[float] = []
        learn_top5: list[float] = []
        base_top1: list[float] = []
        base_top5: list[float] = []
        learn_cos: list[float] = []
        base_cos: list[float] = []

        for customer_index, customer_id in enumerate(customer_ids):
            customer = store.customers[customer_id]
            rng = random.Random(
                seed + round_index * 1000 + customer_index
            )
            learner = learners[customer_id]
            baseline_weights = SIM_INITIAL_WEIGHTS

            hits_learn_1 = 0
            hits_learn_k = 0
            hits_base_1 = 0
            hits_base_k = 0
            update_pairs: list[tuple[dict[str, float], dict[str, float]]] = []

            for _ in range(selections_per_round):
                task, candidates = rng.choice(task_candidates)
                sample = rng.sample(
                    candidates, min(candidate_pool, len(candidates))
                )
                vectors = [
                    candidate_features(
                        worker,
                        task,
                        customer,
                        cf_score=0.0,
                        now=store.reference_time,
                    )
                    for worker in sample
                ]
                utilities = []
                for vector in vectors:
                    utility = sum(
                        SIM_TRUE_WEIGHTS.get(key, 0.0)
                        * vector.get(key, 0.0)
                        for key in SIM_TRUE_WEIGHTS
                    )
                    utilities.append(utility + 0.02 * _gumbel(rng))
                chosen_index = max(
                    range(len(sample)),
                    key=lambda index: utilities[index],
                )
                chosen_vector = vectors[chosen_index]

                current = learner.weights
                learned_scores = [
                    sum(
                        current.get(key, 0.0) * vector.get(key, 0.0)
                        for key in current
                    )
                    for vector in vectors
                ]
                learned_rank = sorted(
                    range(len(sample)),
                    key=lambda index: learned_scores[index],
                    reverse=True,
                )
                hits_learn_1 += int(learned_rank[0] == chosen_index)
                hits_learn_k += int(
                    chosen_index in learned_rank[:top_k]
                )

                baseline_scores = [
                    sum(
                        baseline_weights.get(key, 0.0)
                        * vector.get(key, 0.0)
                        for key in baseline_weights
                    )
                    for vector in vectors
                ]
                baseline_rank = sorted(
                    range(len(sample)),
                    key=lambda index: baseline_scores[index],
                    reverse=True,
                )
                hits_base_1 += int(baseline_rank[0] == chosen_index)
                hits_base_k += int(
                    chosen_index in baseline_rank[:top_k]
                )

                if learned_rank[0] != chosen_index:
                    wrong_above = [
                        index
                        for index in range(len(sample))
                        if index != chosen_index
                        and learned_scores[index]
                        > learned_scores[chosen_index]
                    ]
                    if wrong_above:
                        rejected_index = rng.choice(wrong_above)
                        update_pairs.append(
                            (chosen_vector, vectors[rejected_index])
                        )

            # Learn after the round, then use the updated weights next round.
            for chosen, rejected in update_pairs:
                learner.update_pair(chosen, rejected)

            denominator = max(1, selections_per_round)
            learn_top1.append(hits_learn_1 / denominator)
            learn_top5.append(hits_learn_k / denominator)
            base_top1.append(hits_base_1 / denominator)
            base_top5.append(hits_base_k / denominator)
            learn_cos.append(
                _cosine(learner.weights, SIM_TRUE_WEIGHTS)
            )
            base_cos.append(
                _cosine(baseline_weights, SIM_TRUE_WEIGHTS)
            )

        result["learning_top1"].append(_mean(learn_top1))
        result["learning_top5"].append(_mean(learn_top5))
        result["baseline_top1"].append(_mean(base_top1))
        result["baseline_top5"].append(_mean(base_top5))
        result["learning_cosine"].append(_mean(learn_cos))
        result["baseline_cosine"].append(_mean(base_cos))

    return result
