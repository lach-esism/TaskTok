def test_plan_store_versions_and_rollback():
    from app.chains.plan_store import ChainPlanStore
    from app.domain import ChainPlan

    store = ChainPlanStore()
    first = ChainPlan(plan_id="p1", chain_id="c1", score=0.5, nodes=[])
    second = ChainPlan(plan_id="p2", chain_id="c1", score=0.7, nodes=[])
    assert store.save(first) == 1
    assert store.save(second) == 2
    assert store.active("c1").plan_id == "p2"
    assert store.rollback("c1", 1).plan_id == "p1"
    assert [plan.plan_id for plan in store.versions("c1")] == ["p1", "p2"]


def test_plan_rollback_api(small_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app(small_store, weights_dir=tmp_path))
    chain_id = client.post(
        "/chains/decompose", json={"task_id": "t1"}
    ).json()["chain_id"]
    first = client.post(f"/chains/{chain_id}/plan").json()
    client.post(f"/chains/{chain_id}/plan")
    plans = client.get(f"/chains/{chain_id}/plans").json()
    assert len(plans) == 2
    rolled = client.post(
        f"/chains/{chain_id}/plan/rollback", json={"version": 1}
    ).json()
    assert rolled["plan"]["plan_id"] == first["plan_id"]
