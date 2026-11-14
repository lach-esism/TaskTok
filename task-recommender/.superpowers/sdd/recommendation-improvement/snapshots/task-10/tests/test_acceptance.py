from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.acceptance.service import AcceptanceService, example_research_artifacts
from app.data.store import Store
from app.domain import Customer, Task, Worker
from app.learning.weights import AHP_PRIOR
from app.main import create_app
from app.personalization.segments import Segmenter
from app.personalization.user_weights import PersonalizationService


def build_store() -> Store:
    now = datetime.now(timezone.utc)
    worker = Worker(
        worker_id="w1",
        name="Worker One",
        skills={"research": 5, "analysis": 4, "writing": 4},
        specialties={"consulting_research": 5},
        level=5,
        capacity_hours=40,
        current_load_hours=0,
        preferred_categories={"consulting_research": 0.8},
        preferred_difficulty=(1, 5),
        region="CN",
        remote_ok=True,
        ratings=[5.0],
    )
    customer = Customer(customer_id="c1", name="Customer", region="CN")
    task = Task(
        task_id="t1",
        customer_id="c1",
        title="B2B 市场进入研究",
        category="consulting_research",
        required_skills={"research": 3},
        required_level=2,
        difficulty=3,
        priority=3,
        estimated_hours=8,
        deadline=now + timedelta(days=7),
        region="CN",
        remote_ok=True,
        description="调研目标市场并给出进入建议。",
        requirements=["至少 8 个来源", "包含竞品分析"],
        budget=10000,
    )
    return Store(
        workers=[worker],
        customers=[customer],
        tasks=[task],
        assignments=[],
        feedback=[],
    )


def build_service() -> AcceptanceService:
    store = build_store()
    personalizer = PersonalizationService(store, Segmenter(), AHP_PRIOR)
    return AcceptanceService(store, personalizer=personalizer)


def submit_complete(service: AcceptanceService):
    store = service.store
    task = store.tasks["t1"]
    return service.submit(
        task.task_id,
        "w1",
        example_research_artifacts(),
        submitted_at=store.reference_time,
    )


def test_research_spec_has_ten_weighted_criteria():
    service = build_service()
    spec = service.spec_for(service.store.tasks["t1"])

    assert len(spec.criteria) == 10
    assert round(sum(item.weight for item in spec.criteria), 6) == 1.0
    assert sum(1 for item in spec.criteria if item.required) == 8
    assert sum(1 for item in spec.criteria if item.layer == "machine") == 8
    assert {item.layer for item in spec.criteria} == {
        "machine",
        "customer",
        "peer",
    }


def test_machine_check_flags_missing_section_and_sources():
    service = build_service()
    artifacts = copy.deepcopy(example_research_artifacts())
    del artifacts["sections"]["competitive_landscape"]
    artifacts["sources"] = artifacts["sources"][:4]

    submission, record = service.submit(
        "t1", "w1", artifacts, submitted_at=service.store.reference_time
    )

    failed = {
        result.criterion_key
        for result in submission.machine_results
        if not result.passed
    }
    assert submission.status == "machine_failed"
    assert "competitive_landscape_section" in failed
    assert "sources" in failed
    assert record.total_score < 1.0


def test_acceptance_flow_updates_capability_and_personal_weights():
    service = build_service()
    submission, machine_record = submit_complete(service)
    assert submission.status == "machine_checked"
    assert machine_record.total_score == 1.0

    service.review(
        submission.submission_id,
        "c1",
        {"insight": 0.9, "citation_consistency": 0.8},
        {"insight": "clear recommendation"},
    )
    record, learning = service.decide(
        submission.submission_id, "c1", "accepted", "looks good"
    )

    assert record.decision == "accepted"
    assert record.total_score == pytest.approx(0.96)
    assert learning is not None
    assert learning["decision"] == "accepted"
    assert learning["signals"]["expertise"] > 0
    assert sum(learning["after"].values()) == pytest.approx(1.0)
    assert learning["top_up"] in {"reputation", "expertise"}
    assert learning["top_down"] in learning["after"]

    capability = service.capability("w1")
    assert capability["accepted"] == 1
    assert capability["first_pass_accepted"] == 1
    assert capability["first_pass_rate_raw"] == 1.0
    assert capability["avg_acceptance_score"] == pytest.approx(0.96)


def test_rejection_without_failed_criterion_becomes_dispute():
    service = build_service()
    submission, _ = submit_complete(service)
    service.review(
        submission.submission_id,
        "c1",
        {"insight": 0.9, "citation_consistency": 0.8},
    )
    record, learning = service.decide(
        submission.submission_id, "c1", "rejected", "感觉不行"
    )

    assert record.decision == "disputed"
    assert "converted to dispute" in record.comment
    assert learning is None


def test_cannot_accept_when_required_criterion_fails():
    service = build_service()
    artifacts = copy.deepcopy(example_research_artifacts())
    del artifacts["sections"]["market_size"]
    submission, _ = service.submit(
        "t1", "w1", artifacts, submitted_at=service.store.reference_time
    )
    service.review(
        submission.submission_id,
        "c1",
        {"insight": 0.9, "citation_consistency": 0.8},
    )

    with pytest.raises(ValueError, match="required criteria failed"):
        service.decide(submission.submission_id, "c1", "accepted")


def test_review_requires_all_human_criteria():
    service = build_service()
    submission, _ = submit_complete(service)

    with pytest.raises(ValueError, match="missing scores"):
        service.review(
            submission.submission_id,
            "c1",
            {"insight": 0.9},
        )


def test_learning_demo_accumulates_samples_and_reports_ranking():
    service = build_service()
    result = service.run_learning_demo(rounds=5)

    assert len(result["rounds"]) == 5
    assert result["sample_count"] == 5
    assert result["capability"]["accepted"] == 5
    assert result["before_ranking"]
    assert result["after_ranking"]
    assert result["top_up"] in result["weights_after"]
    assert round(sum(result["weights_after"].values()), 6) == 1.0
    assert len(result["ranking_changes"]) == len(result["after_ranking"])


def test_acceptance_endpoints(tmp_path):
    store = build_store()
    client = TestClient(create_app(store, weights_dir=tmp_path))

    demo = client.get("/acceptance/demo")
    assert demo.status_code == 200
    assert len(demo.json()["spec"]["criteria"]) == 10

    submitted = client.post(
        "/tasks/t1/submissions",
        json={
            "worker_id": "w1",
            "artifacts": example_research_artifacts(),
        },
    )
    assert submitted.status_code == 200
    submission_id = submitted.json()["submission"]["submission_id"]

    reviewed = client.post(
        f"/submissions/{submission_id}/review",
        json={
            "reviewer_id": "c1",
            "scores": {"insight": 0.9, "citation_consistency": 0.8},
        },
    )
    assert reviewed.status_code == 200

    decided = client.post(
        f"/submissions/{submission_id}/decision",
        json={"reviewer_id": "c1", "decision": "accepted"},
    )
    assert decided.status_code == 200
    body = decided.json()
    assert body["record"]["decision"] == "accepted"
    assert body["learning"]["sample_count"] == 1

    records = client.get("/tasks/t1/acceptance-records")
    assert records.status_code == 200
    assert len(records.json()) == 3

    capability = client.get("/workers/w1/capability")
    assert capability.status_code == 200
    assert capability.json()["accepted"] == 1

    metrics = client.get("/acceptance/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["accepted"] == 1
