from app.data.synthetic import generate_dataset
from app.resume import build_resume


def test_resume_is_deterministic_and_looks_human():
    dataset = generate_dataset(n_workers=10, n_tasks=20, n_assignments=40)
    worker = dataset.workers[0]

    first = build_resume(worker)
    second = build_resume(worker)

    assert first == second
    resume = first["resume"]
    assert resume["name"] != f"Worker 1"
    assert len(resume["name"]) >= 2
    assert resume["headline"]
    assert resume["summary"]
    assert resume["education"]
    assert resume["expected_rate"].startswith("¥")
    assert len(resume["work_experience"]) >= 2
    assert len(resume["projects"]) >= 2
    assert 2 <= len(resume["skills"]) <= 8


def test_surface_hides_internal_skill_keys():
    dataset = generate_dataset(n_workers=10, n_tasks=20, n_assignments=40)
    worker = dataset.workers[0]
    payload = build_resume(worker)

    surface = payload["resume"]
    internal_keys = set(worker.skills)
    assert not internal_keys.intersection(surface["skills"])
    assert "skills" in payload["platform_data"]
    assert payload["platform_data"]["skills"] == worker.skills
    assert "level" in payload["platform_data"]
    assert "current_load_hours" in payload["platform_data"]


def test_resume_endpoints(client):
    detail = client.get("/workers/w_good/resume")
    assert detail.status_code == 200
    body = detail.json()
    assert body["resume"]["name"]
    assert "platform_data" in body
    assert body["platform_data"]["worker_id"] == "w_good"

    listing = client.get("/resumes?limit=3")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] >= 3
    assert len(payload["items"]) == 3
    assert all("platform_data" not in item for item in payload["items"])
    assert all(item["name"] for item in payload["items"])
