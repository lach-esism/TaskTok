from fastapi.testclient import TestClient
from app.main import create_app


def test_health():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.3.0"}


def test_default_app_generates_store():
    app = create_app()
    assert app.state.store is not None
    assert app.state.store.workers


def test_frontend_served(client):
    root = client.get("/", follow_redirects=False)
    assert root.status_code in (302, 307)
    page = client.get("/ui/")
    assert page.status_code == 200
    assert "TASKWEAVE" in page.text
    assert "progress-chart" in page.text
    assert "classify-text" in page.text
    assert "acceptance-load" in page.text
    assert "talent-resume" in page.text
    assert "benchmark-chart" in page.text
    assert client.get("/ui/styles.css").status_code == 200
    script = client.get("/ui/app.js")
    assert script.status_code == 200
    assert "runDemo" in script.text
    assert "renderProgressChart" in script.text
    assert "runClassification" in script.text
    assert "loadAcceptanceDemo" in script.text
    assert "renderTalentResume" in script.text
    assert "runBenchmark" in script.text


def test_learning_curve_endpoint(client):
    response = client.get("/metrics/learning-curve")
    assert response.status_code == 200
    curve = response.json()
    assert curve.get("n")
    assert len(curve["weight_cosine"]) == len(curve["n"])


def test_learning_rounds_endpoint(client):
    response = client.get("/metrics/learning-rounds")
    assert response.status_code == 200
    data = response.json()
    assert len(data.get("rounds", [])) == 20
    assert len(data["learning_top1"]) == 20


def test_compose_mode_api(client):
    response = client.post(
        "/chains/decompose",
        json={
            "task_id": "t1",
            "mode": "compose",
            "categories": ["software_dev", "content_writing"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    keys = [node["key"] for node in body["nodes"]]
    assert "content_writing:publish" in keys
    assert "content_writing:draft" in keys
    assert body["critical_path"]


def test_chain_api_flow(client):
    decompose = client.post(
        "/chains/decompose", json={"task_id": "t1", "mode": "template"}
    )
    assert decompose.status_code == 200
    body = decompose.json()
    assert body["nodes"]
    assert body["critical_path"]
    chain_id = body["chain_id"]

    detail = client.get(f"/chains/{chain_id}")
    assert detail.status_code == 200

    plan = client.post(f"/chains/{chain_id}/plan")
    assert plan.status_code == 200
    assert len(plan.json()["nodes"]) == len(body["nodes"])
