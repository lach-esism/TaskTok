"""Greedy chain planner and breach propagation."""

from __future__ import annotations

import uuid

from app.chains.dag import compute_slack, critical_path, topological_order
from app.domain import (
    BreachImpact,
    ChainPlan,
    ChainPlanNode,
    Task,
    TaskChain,
)
from app.service import RecommendationService


def plan_chain(
    chain: TaskChain,
    service: RecommendationService,
    top_n_per_node: int = 3,
) -> ChainPlan:
    order = topological_order(chain.nodes)
    by_key = {node.key: node for node in chain.nodes}
    root_task = service.store.tasks.get(chain.root_task_id)
    category = root_task.category if root_task else ""
    region = root_task.region if root_task else "CN"
    remote_ok = root_task.remote_ok if root_task else True

    assigned_hours = {
        worker_id: worker.current_load_hours
        for worker_id, worker in service.store.workers.items()
    }
    worker_by_key: dict[str, str | None] = {}
    plan_nodes: list[ChainPlanNode] = []
    blocked: list[str] = []
    blocked_keys: set[str] = set()

    for key in order:
        node = by_key[key]
        if any(
            dependency in blocked_keys
            for dependency in node.depends_on
        ):
            blocked.append(key)
            blocked_keys.add(key)
            worker_by_key[key] = None
            plan_nodes.append(
                ChainPlanNode(
                    subtask_id=node.subtask_id,
                    worker_id=None,
                    rank=0,
                    node_score=0.0,
                )
            )
            continue
        temporary_task = Task(
            task_id=node.subtask_id,
            customer_id=chain.customer_id,
            title=node.title,
            category=category,
            required_skills=node.required_skills,
            required_level=1,
            difficulty=3,
            priority=3,
            estimated_hours=node.estimated_hours,
            deadline=chain.deadline,
            region=region,
            remote_ok=remote_ok,
            description="",
            status="open",
        )
        candidates = service.recommend_workers_for_task(
            temporary_task, top_n=top_n_per_node
        )

        chosen_worker: str | None = None
        chosen_rank = 0
        chosen_score = 0.0
        for rank, candidate in enumerate(candidates, start=1):
            worker = service.store.workers.get(candidate.candidate_id)
            if worker is None:
                continue
            used = assigned_hours.get(
                worker.worker_id, worker.current_load_hours
            )
            if used + node.estimated_hours <= worker.capacity_hours:
                chosen_worker = worker.worker_id
                chosen_rank = rank
                chosen_score = candidate.score
                assigned_hours[worker.worker_id] = used + node.estimated_hours
                break

        if chosen_worker is None:
            blocked.append(key)
            blocked_keys.add(key)
        worker_by_key[key] = chosen_worker
        plan_nodes.append(
            ChainPlanNode(
                subtask_id=node.subtask_id,
                worker_id=chosen_worker,
                rank=chosen_rank,
                node_score=chosen_score,
            )
        )

    handoffs = 0
    for edge in chain.edges:
        from_worker = worker_by_key.get(edge.from_node)
        to_worker = worker_by_key.get(edge.to_node)
        if (
            from_worker is not None
            and to_worker is not None
            and from_worker != to_worker
        ):
            handoffs += 1

    assigned_scores = [
        node.node_score for node in plan_nodes if node.worker_id is not None
    ]
    score = (
        sum(assigned_scores) / len(assigned_scores) - 0.05 * handoffs
        if assigned_scores
        else 0.0
    )

    return ChainPlan(
        plan_id=uuid.uuid4().hex,
        chain_id=chain.chain_id,
        score=score,
        nodes=plan_nodes,
        blocked=blocked,
        planner="greedy",
    )


def plan_chain_beam(
    chain: TaskChain,
    service: RecommendationService,
    beam_width: int = 5,
    top_n_per_node: int = 3,
    locked_assignments: dict[str, str] | None = None,
    locked_scores: dict[str, float] | None = None,
    locked_ranks: dict[str, int] | None = None,
) -> ChainPlan:
    locked_assignments = dict(locked_assignments or {})
    locked_scores = dict(locked_scores or {})
    locked_ranks = dict(locked_ranks or {})
    order = topological_order(chain.nodes)
    by_key = {node.key: node for node in chain.nodes}
    root_task = service.store.tasks.get(chain.root_task_id)
    category = root_task.category if root_task else ""
    region = root_task.region if root_task else "CN"
    remote_ok = root_task.remote_ok if root_task else True

    candidates_by_key = {}
    for key in order:
        node = by_key[key]
        temporary_task = Task(
            task_id=node.subtask_id,
            customer_id=chain.customer_id,
            title=node.title,
            category=category,
            required_skills=node.required_skills,
            required_level=1,
            difficulty=3,
            priority=3,
            estimated_hours=node.estimated_hours,
            deadline=chain.deadline,
            region=region,
            remote_ok=remote_ok,
            description="",
            status="open",
        )
        candidates_by_key[key] = service.recommend_workers_for_task(
            temporary_task, top_n=top_n_per_node
        )

    initial_hours = {
        worker_id: worker.current_load_hours
        for worker_id, worker in service.store.workers.items()
    }
    for key, worker_id in locked_assignments.items():
        node = by_key.get(key)
        if node is not None and worker_id in initial_hours:
            initial_hours[worker_id] += node.estimated_hours

    initial_assignments = dict(locked_assignments)
    initial_scores = {
        key: locked_scores.get(key, 0.0) for key in locked_assignments
    }
    initial_ranks = {
        key: locked_ranks.get(key, 0) for key in locked_assignments
    }
    initial_handoffs = sum(
        1
        for edge in chain.edges
        if edge.from_node in locked_assignments
        and edge.to_node in locked_assignments
        and locked_assignments[edge.from_node]
        != locked_assignments[edge.to_node]
    )
    states = [
        {
            "assignments": initial_assignments,
            "hours": dict(initial_hours),
            "node_scores": initial_scores,
            "ranks": initial_ranks,
            "blocked": set(),
            "score": sum(initial_scores.values()),
            "handoffs": initial_handoffs,
        }
    ]

    for key in order:
        if key in locked_assignments:
            continue
        node = by_key[key]
        next_states = []
        for state in states:
            if any(
                dependency in state["blocked"]
                for dependency in node.depends_on
            ):
                blocked_state = {
                    "assignments": dict(state["assignments"]),
                    "hours": dict(state["hours"]),
                    "node_scores": dict(state["node_scores"]),
                    "ranks": dict(state["ranks"]),
                    "blocked": set(state["blocked"]) | {key},
                    "score": state["score"],
                    "handoffs": state["handoffs"],
                }
                blocked_state["assignments"][key] = None
                blocked_state["node_scores"][key] = 0.0
                blocked_state["ranks"][key] = 0
                next_states.append(blocked_state)
                continue

            feasible = False
            for rank, candidate in enumerate(
                candidates_by_key[key], start=1
            ):
                worker = service.store.workers.get(candidate.candidate_id)
                if worker is None:
                    continue
                used = state["hours"].get(
                    worker.worker_id, worker.current_load_hours
                )
                if used + node.estimated_hours > worker.capacity_hours:
                    continue
                feasible = True
                new_state = {
                    "assignments": dict(state["assignments"]),
                    "hours": dict(state["hours"]),
                    "node_scores": dict(state["node_scores"]),
                    "ranks": dict(state["ranks"]),
                    "blocked": set(state["blocked"]),
                    "score": state["score"] + candidate.score,
                    "handoffs": state["handoffs"],
                }
                new_state["assignments"][key] = worker.worker_id
                new_state["hours"][worker.worker_id] = (
                    used + node.estimated_hours
                )
                new_state["node_scores"][key] = candidate.score
                new_state["ranks"][key] = rank
                for dependency in node.depends_on:
                    assigned = new_state["assignments"].get(dependency)
                    if assigned is not None and assigned != worker.worker_id:
                        new_state["handoffs"] += 1
                next_states.append(new_state)
            if not feasible:
                blocked_state = {
                    "assignments": dict(state["assignments"]),
                    "hours": dict(state["hours"]),
                    "node_scores": dict(state["node_scores"]),
                    "ranks": dict(state["ranks"]),
                    "blocked": set(state["blocked"]) | {key},
                    "score": state["score"],
                    "handoffs": state["handoffs"],
                }
                blocked_state["assignments"][key] = None
                blocked_state["node_scores"][key] = 0.0
                blocked_state["ranks"][key] = 0
                next_states.append(blocked_state)
        next_states.sort(
            key=lambda state: state["score"] - 0.05 * state["handoffs"],
            reverse=True,
        )
        states = next_states[: max(1, beam_width)]

    best = max(
        states,
        key=lambda state: state["score"] - 0.05 * state["handoffs"],
    )
    plan_nodes = [
        ChainPlanNode(
            subtask_id=by_key[key].subtask_id,
            worker_id=best["assignments"].get(key),
            rank=best["ranks"].get(key, 0),
            node_score=best["node_scores"].get(key, 0.0),
        )
        for key in order
    ]
    blocked = [
        key for key in order if best["assignments"].get(key) is None
    ]
    return ChainPlan(
        plan_id=uuid.uuid4().hex,
        chain_id=chain.chain_id,
        score=best["score"] - 0.05 * best["handoffs"],
        nodes=plan_nodes,
        blocked=blocked,
        planner="beam",
    )


def plan_chain_milp(
    chain: TaskChain,
    service: RecommendationService,
    max_nodes: int = 20,
) -> ChainPlan:
    def fallback() -> ChainPlan:
        result = plan_chain_beam(chain, service)
        result.planner = "beam_fallback"
        return result

    if len(chain.nodes) > max_nodes:
        return fallback()
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
    except Exception:
        return fallback()

    order = topological_order(chain.nodes)
    by_key = {node.key: node for node in chain.nodes}
    root_task = service.store.tasks.get(chain.root_task_id)
    category = root_task.category if root_task else ""
    region = root_task.region if root_task else "CN"
    remote_ok = root_task.remote_ok if root_task else True

    variables: list[tuple[str, str, float, int]] = []
    for key in order:
        node = by_key[key]
        temporary_task = Task(
            task_id=node.subtask_id,
            customer_id=chain.customer_id,
            title=node.title,
            category=category,
            required_skills=node.required_skills,
            required_level=1,
            difficulty=3,
            priority=3,
            estimated_hours=node.estimated_hours,
            deadline=chain.deadline,
            region=region,
            remote_ok=remote_ok,
            description="",
            status="open",
        )
        candidates = service.recommend_workers_for_task(
            temporary_task, top_n=100
        )
        for rank, candidate in enumerate(candidates, start=1):
            variables.append(
                (
                    key,
                    candidate.candidate_id,
                    candidate.score,
                    rank,
                )
            )

    if not variables:
        return fallback()
    by_node: dict[str, list[int]] = {key: [] for key in order}
    for index, variable in enumerate(variables):
        by_node[variable[0]].append(index)
    if any(not by_node[key] for key in order):
        return fallback()

    n = len(variables)
    objective = np.array(
        [
            -(
                1.2 if variable[0] in chain.critical_path else 1.0
            )
            * variable[2]
            for variable in variables
        ]
    )
    rows: list[list[float]] = []
    lower: list[float] = []
    upper: list[float] = []
    for key in order:
        row = [0.0] * n
        for index in by_node[key]:
            row[index] = 1.0
        rows.append(row)
        lower.append(1.0)
        upper.append(1.0)

    by_worker: dict[str, list[int]] = {}
    for index, variable in enumerate(variables):
        worker = service.store.workers.get(variable[1])
        if worker is not None:
            by_worker.setdefault(worker.worker_id, []).append(index)
    for worker_id, indices in by_worker.items():
        worker = service.store.workers[worker_id]
        row = [0.0] * n
        for index in indices:
            row[index] = by_key[variables[index][0]].estimated_hours
        rows.append(row)
        lower.append(-np.inf)
        upper.append(
            max(
                0.0,
                worker.capacity_hours - worker.current_load_hours,
            )
        )

    result = milp(
        objective,
        integrality=np.ones(n),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(
            np.array(rows), np.array(lower), np.array(upper)
        ),
        options={"time_limit": 5},
    )
    if not result.success or result.x is None:
        return fallback()

    selected: dict[str, str] = {}
    ranks: dict[str, int] = {}
    scores: dict[str, float] = {}
    for index, value in enumerate(result.x):
        if value > 0.5:
            key, worker_id, score, rank = variables[index]
            selected[key] = worker_id
            ranks[key] = rank
            scores[key] = score
    if len(selected) != len(order):
        return fallback()

    blocked: set[str] = set()
    for key in order:
        if selected.get(key) is None or any(
            selected.get(dependency) is None
            for dependency in by_key[key].depends_on
        ):
            blocked.add(key)
            selected[key] = None
            scores[key] = 0.0
            ranks[key] = 0

    handoffs = 0
    for edge in chain.edges:
        from_worker = selected.get(edge.from_node)
        to_worker = selected.get(edge.to_node)
        if (
            from_worker is not None
            and to_worker is not None
            and from_worker != to_worker
        ):
            handoffs += 1

    plan_nodes = [
        ChainPlanNode(
            subtask_id=by_key[key].subtask_id,
            worker_id=selected[key],
            rank=ranks[key],
            node_score=scores[key],
        )
        for key in order
    ]
    return ChainPlan(
        plan_id=uuid.uuid4().hex,
        chain_id=chain.chain_id,
        score=sum(scores.values()) - 0.05 * handoffs,
        nodes=plan_nodes,
        blocked=sorted(blocked),
        planner="milp",
    )


def replan_chain(
    chain: TaskChain,
    service: RecommendationService,
    failed_node_key: str,
    delay_hours: float,
    locked_nodes: set[str],
    current_plan: ChainPlan | None = None,
    beam_width: int = 5,
) -> ChainPlan:
    impact = propagate_breach(chain, failed_node_key, delay_hours)
    baseline = current_plan or plan_chain(chain, service)
    if not impact.requires_replan:
        return baseline

    subtask_to_key = {
        node.subtask_id: node.key for node in chain.nodes
    }
    affected = set(impact.affected_nodes) | {failed_node_key}
    all_keys = {node.key for node in chain.nodes}
    locked_keys = (all_keys - affected) | set(locked_nodes)

    locked_workers: dict[str, str] = {}
    locked_scores: dict[str, float] = {}
    locked_ranks: dict[str, int] = {}
    for node in baseline.nodes:
        key = subtask_to_key.get(node.subtask_id)
        if key in locked_keys and node.worker_id is not None:
            locked_workers[key] = node.worker_id
            locked_scores[key] = node.node_score
            locked_ranks[key] = node.rank

    replanned = plan_chain_beam(
        chain,
        service,
        beam_width=beam_width,
        locked_assignments=locked_workers,
        locked_scores=locked_scores,
        locked_ranks=locked_ranks,
    )
    replanned.planner = "replan"
    return replanned


def propagate_breach(
    chain: TaskChain,
    failed_node_key: str,
    delay_hours: float,
) -> BreachImpact:
    by_key = {node.key: node for node in chain.nodes}
    if failed_node_key not in by_key:
        raise ValueError(f"unknown node: {failed_node_key}")

    adjacency: dict[str, list[str]] = {node.key: [] for node in chain.nodes}
    for edge in chain.edges:
        adjacency[edge.from_node].append(edge.to_node)

    affected: list[str] = []
    stack = list(adjacency.get(failed_node_key, []))
    visited = {failed_node_key}
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        affected.append(current)
        stack.extend(adjacency.get(current, []))

    critical = chain.critical_path or critical_path(chain.nodes)[0]
    critical_path_delay = (
        delay_hours if failed_node_key in critical else 0.0
    )
    slack = compute_slack(chain.nodes).get(failed_node_key, 0.0)
    severity = max(0.0, critical_path_delay - slack) / max(slack, 1.0)
    requires_replan = severity > 0.0 or failed_node_key in critical

    return BreachImpact(
        failed_node=failed_node_key,
        affected_nodes=sorted(affected),
        critical_path_delay=critical_path_delay,
        chain_slack=slack,
        severity=severity,
        requires_replan=requires_replan,
    )
