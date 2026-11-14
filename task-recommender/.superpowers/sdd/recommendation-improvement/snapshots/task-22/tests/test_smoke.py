def test_smoke_flow(client):
    assert client.get("/health").status_code == 200
    assert client.get("/workers").status_code == 200
    assert client.get("/tasks").status_code == 200
    response = client.post(
        "/recommend/workers", json={"task_id": "t1", "top_n": 3}
    )
    assert response.status_code == 200
