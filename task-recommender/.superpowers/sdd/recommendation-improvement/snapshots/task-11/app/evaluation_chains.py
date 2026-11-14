"""Chain planner comparison metrics."""

from __future__ import annotations

from statistics import mean

from app.chains.dag import validate_dag
from app.chains.decompose import decompose
from app.chains.planner import plan_chain, plan_chain_beam, plan_chain_milp
from app.data.store import Store
from app.service import RecommendationService

PLANNERS = {
    "greedy": plan_chain,
    "beam": plan_chain_beam,
    "milp": plan_chain_milp,
}


def _plan_metrics(draft, plan) -> dict[str, float]:
    total = max(1, len(plan.nodes))
    assigned = [
        node for node in plan.nodes if node.worker_id is not None
    ]
    key_by_subtask = {
        node.subtask_id: node.key for node in draft.chain.nodes
    }
    worker_by_key = {
        key_by_subtask[node.subtask_id]: node.worker_id
        for node in plan.nodes
    }
    handoffs = 0
    for edge in draft.chain.edges:
        from_worker = worker_by_key.get(edge.from_node)
        to_worker = worker_by_key.get(edge.to_node)
        if (
            from_worker is not None
            and to_worker is not None
            and from_worker != to_worker
        ):
            handoffs += 1
    return {
        "plan_coverage": len(assigned) / total,
        "blocked_rate": len(plan.blocked) / total,
        "mean_node_score": (
            mean(node.node_score for node in assigned)
            if assigned
            else 0.0
        ),
        "handoff_count": float(handoffs),
        "acyclic_rate": (
            1.0 if validate_dag(draft.chain.nodes).valid else 0.0
        ),
    }


def evaluate_planners(
    store: Store,
    templates: dict[str, dict],
    planner_names: tuple[str, ...] = ("greedy", "beam", "milp"),
    n_samples: int = 30,
) -> dict[str, dict[str, float]]:
    tasks = [
        task
        for task in store.tasks.values()
        if task.category in templates
    ][:n_samples]
    service = RecommendationService(store)
    collected: dict[str, dict[str, list[float]]] = {
        name: {
            "plan_coverage": [],
            "blocked_rate": [],
            "mean_node_score": [],
            "handoff_count": [],
            "acyclic_rate": [],
        }
        for name in planner_names
    }

    for task in tasks:
        try:
            draft = decompose(task, templates[task.category])
        except Exception:
            continue
        for name in planner_names:
            if name not in PLANNERS:
                continue
            try:
                plan = PLANNERS[name](draft.chain, service)
            except Exception:
                continue
            metrics = _plan_metrics(draft, plan)
            for key, value in metrics.items():
                collected[name][key].append(value)

    return {
        name: {
            key: (mean(values) if values else 0.0)
            for key, values in metrics.items()
        }
        for name, metrics in collected.items()
    }
