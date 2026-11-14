def test_replan_locks_completed_nodes_and_versions_plan(
    software_task, small_store
):
    from app.chains.decompose import decompose
    from app.chains.planner import plan_chain, replan_chain
    from app.data.templates import load_templates
    from app.service import RecommendationService

    templates = load_templates(
        "data/chain_templates/common_task_chains.json"
    )
    draft = decompose(software_task, templates["software_dev"])
    service = RecommendationService(small_store)
    plan = plan_chain(draft.chain, service)
    locked = {draft.chain.nodes[0].key}
    replanned = replan_chain(
        draft.chain,
        service,
        draft.chain.critical_path[1],
        4.0,
        locked,
    )
    assert replanned.plan_id != plan.plan_id
    first_subtask = draft.chain.nodes[0].subtask_id
    original = next(
        node for node in plan.nodes if node.subtask_id == first_subtask
    )
    redone = next(
        node
        for node in replanned.nodes
        if node.subtask_id == first_subtask
    )
    assert redone.worker_id == original.worker_id


def test_replan_locked_capacity_is_respected():
    from datetime import datetime, timedelta, timezone

    from app.chains.planner import plan_chain, replan_chain
    from app.data.store import Store
    from app.domain import (
        ChainEdge,
        Customer,
        SubTask,
        Task,
        TaskChain,
        Worker,
    )
    from app.service import RecommendationService

    now = datetime.now(timezone.utc)
    customer = Customer(customer_id="c1", name="C", region="CN")

    def make_worker(worker_id: str) -> Worker:
        return Worker(
            worker_id=worker_id,
            name=worker_id,
            skills={},
            specialties={},
            level=3,
            capacity_hours=40,
            current_load_hours=0,
            preferred_categories={},
            preferred_difficulty=(1, 5),
            region="CN",
            remote_ok=True,
        )

    root = Task(
        task_id="t_root",
        customer_id="c1",
        title="root",
        category="software_dev",
        required_skills={},
        required_level=1,
        difficulty=3,
        priority=3,
        estimated_hours=1,
        deadline=now + timedelta(days=7),
        region="CN",
        remote_ok=True,
    )
    nodes = [
        SubTask(
            subtask_id="s_a",
            chain_id="chain",
            key="a",
            title="a",
            node_type="task",
            estimated_hours=20,
            required_skills={},
            depends_on=[],
            acceptance=["ok"],
        ),
        SubTask(
            subtask_id="s_b",
            chain_id="chain",
            key="b",
            title="b",
            node_type="task",
            estimated_hours=20,
            required_skills={},
            depends_on=["a"],
            acceptance=["ok"],
        ),
        SubTask(
            subtask_id="s_c",
            chain_id="chain",
            key="c",
            title="c",
            node_type="delivery",
            estimated_hours=25,
            required_skills={},
            depends_on=["b"],
            acceptance=["ok"],
        ),
    ]
    chain = TaskChain(
        chain_id="chain",
        root_task_id="t_root",
        customer_id="c1",
        deadline=now + timedelta(days=30),
        budget=0.0,
        nodes=nodes,
        edges=[
            ChainEdge(chain_id="chain", from_node="a", to_node="b"),
            ChainEdge(chain_id="chain", from_node="b", to_node="c"),
        ],
        critical_path=["a", "b", "c"],
    )
    store = Store(
        workers=[make_worker("wL"), make_worker("wW")],
        customers=[customer],
        tasks=[root],
        assignments=[],
        feedback=[],
        chains={"chain": chain},
    )
    service = RecommendationService(store)
    baseline = plan_chain(chain, service)
    original_a = next(
        node for node in baseline.nodes if node.subtask_id == "s_a"
    )
    replanned = replan_chain(
        chain, service, "b", 1.0, {"a"}, current_plan=baseline
    )
    key_by_subtask = {
        node.subtask_id: node.key for node in chain.nodes
    }
    hours: dict[str, float] = {}
    for node in replanned.nodes:
        key = key_by_subtask[node.subtask_id]
        if node.worker_id is not None:
            duration = next(
                item.estimated_hours
                for item in chain.nodes
                if item.key == key
            )
            hours[node.worker_id] = (
                hours.get(node.worker_id, 0.0) + duration
            )
    for worker in store.workers.values():
        assert hours.get(worker.worker_id, 0.0) <= (
            worker.capacity_hours + 1e-9
        )
    replanned_a = next(
        node for node in replanned.nodes if node.subtask_id == "s_a"
    )
    assert replanned_a.worker_id == original_a.worker_id


def test_replan_auto_locks_completed_node(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    body = client.post(
        "/chains/decompose", json={"task_id": "t1"}
    ).json()
    chain_id = body["chain_id"]
    plan = client.post(f"/chains/{chain_id}/plan").json()
    first = body["nodes"][0]
    original = next(
        node
        for node in plan["nodes"]
        if node["subtask_id"] == first["subtask_id"]
    )
    status = client.post(
        f"/chains/{chain_id}/nodes/{first['subtask_id']}/status",
        json={
            "status": "completed",
            "worker_id": original["worker_id"],
        },
    )
    assert status.status_code == 200
    replanned = client.post(
        f"/chains/{chain_id}/replan",
        json={
            "failed_node": body["critical_path"][1],
            "delay_hours": 4.0,
            "locked_nodes": [],
        },
    ).json()
    redone = next(
        node
        for node in replanned["nodes"]
        if node["subtask_id"] == first["subtask_id"]
    )
    assert redone["worker_id"] == original["worker_id"]
    assert "affected_nodes" in replanned
    assert "replanned" in replanned


def test_replan_api_creates_new_version(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    body = client.post(
        "/chains/decompose", json={"task_id": "t1"}
    ).json()
    chain_id = body["chain_id"]
    first = client.post(f"/chains/{chain_id}/plan").json()
    assert first["version"] == 1
    replanned = client.post(
        f"/chains/{chain_id}/replan",
        json={
            "failed_node": body["critical_path"][1],
            "delay_hours": 4.0,
            "locked_nodes": [body["nodes"][0]["key"]],
        },
    )
    assert replanned.status_code == 200
    assert replanned.json()["version"] == 2
    plans = client.get(f"/chains/{chain_id}/plans").json()
    assert len(plans) == 2
