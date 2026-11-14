"""FastAPI application factory and routes."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.acceptance.service import AcceptanceService
from app.benchmark.db import BenchmarkRepository, build_benchmark_db
from app.benchmark.runner import BenchmarkRoundRunner
from app.chains.compose import compose_templates
from app.chains.decompose import decompose, quality_score
from app.chains.plan_store import ChainPlanStore
from app.chains.planner import plan_chain, propagate_breach, replan_chain
from app.config import APP_VERSION, DEFAULT_WEIGHTS
from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.data.templates import load_templates
from app.domain import Task, TaskChain, Worker
from app.evaluation_phase2 import evaluate_two_runs
from app.events import EventService
from app.feedback import FeedbackService
from app.features import candidate_features, pay_fit_score, skill_score
from app.learning.acceptance import AcceptanceModel, accept_features
from app.learning.exploration import ExplorationPolicy
from app.learning.online import OnlineWeightLearner
from app.learning.weights import AHP_PRIOR
from app.semantic import (
    SemanticMatcher,
    build_matcher,
    build_task_text,
    build_worker_text,
)
from app.nlp.classifier import get_default_classifier
from app.personalization.segments import Segmenter
from app.resume import build_resume
from app.personalization.user_weights import PersonalizationService
from app.preference.customer import (
    CustomerPreferenceProfile,
    update_customer_preferences,
)
from app.preference.worker import (
    WorkerPreferenceProfile,
    update_worker_preferences,
)
from app.schemas import (
    CandidateResponse,
    ClassifyRequest,
    CreateAssignmentRequest,
    DecisionRequest,
    DecomposeRequest,
    EventsRequest,
    EventsResponse,
    FeedbackRequest,
    NodeRecommendRequest,
    NodeStatusRequest,
    ReviewRequest,
    SubmissionRequest,
    OnboardingRequest,
    PlanRollbackRequest,
    RecommendResponse,
    RecommendTasksRequest,
    RecommendWorkersRequest,
    ReplanRequest,
    RollbackRequest,
)
from app.service import RecommendationService
from app.versioning import WeightStore

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "chain_templates"
    / "common_task_chains.json"
)
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
BENCHMARK_DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "benchmark"
    / "task_benchmark.sqlite"
)


def _serialize_chain(chain: TaskChain) -> dict:
    return {
        "chain_id": chain.chain_id,
        "root_task_id": chain.root_task_id,
        "customer_id": chain.customer_id,
        "status": chain.status,
        "deadline": chain.deadline,
        "budget": chain.budget,
        "critical_path": chain.critical_path,
        "nodes": [asdict(node) for node in chain.nodes],
        "edges": [asdict(edge) for edge in chain.edges],
    }


def _region_match(worker: Worker, task: Task) -> float:
    if worker.region == task.region:
        return 1.0
    if worker.remote_ok and task.remote_ok:
        return 0.8
    return 0.3


def _build_semantic_matcher(store: Store) -> SemanticMatcher | None:
    """Fit one matcher over the store's worker/task corpus."""
    try:
        matcher = build_matcher()
        matcher.fit(
            [
                build_worker_text(worker)
                for worker in store.workers.values()
            ],
            [
                build_task_text(task)
                for task in store.tasks.values()
            ],
        )
    except Exception:  # noqa: BLE001 - a missing matcher degrades to neutral
        return None
    return matcher if matcher.is_fitted else None


def _build_acceptance_model(store: Store) -> AcceptanceModel | None:
    """Fit the global ``P(accept)`` model from logged accept/reject events."""
    counts: dict[str, tuple[int, int]] = {}
    for event in store.events:
        if event.candidate_type != "worker":
            continue
        if event.action not in {"accept", "reject"}:
            continue
        accepted, rejected = counts.get(event.candidate_id, (0, 0))
        if event.action == "accept":
            accepted += 1
        else:
            rejected += 1
        counts[event.candidate_id] = (accepted, rejected)

    samples: list[tuple[dict[str, float], int]] = []
    for event in store.events:
        if event.candidate_type != "worker":
            continue
        if event.action not in {"accept", "reject"}:
            continue
        worker = store.workers.get(event.candidate_id)
        task = store.tasks.get(event.task_id)
        if worker is None or task is None:
            continue
        accepted, rejected = counts.get(worker.worker_id, (0, 0))
        historical = (
            (accepted + 1) / (accepted + rejected + 2)
            if accepted + rejected > 0
            else 0.5
        )
        samples.append(
            (
                accept_features(
                    worker,
                    task,
                    skill=skill_score(worker, task),
                    pay_fit=pay_fit_score(worker, task),
                    region_match=_region_match(worker, task),
                    historical_accept_rate=historical,
                ),
                1 if event.action == "accept" else 0,
            )
        )
    try:
        model = AcceptanceModel().fit(samples)
    except Exception:  # noqa: BLE001 - an unfitted model degrades to prior
        return None
    return model if model.is_fitted else None


def _node_candidates(
    chain: TaskChain,
    node_id: str,
    current: Store,
    top_n: int,
    exploration: ExplorationPolicy,
    weights: dict[str, float] | None = None,
    semantic_matcher: SemanticMatcher | None = None,
    acceptance_model: AcceptanceModel | None = None,
) -> RecommendResponse:
    node = next(
        (
            candidate
            for candidate in chain.nodes
            if candidate.key == node_id or candidate.subtask_id == node_id
        ),
        None,
    )
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")

    root_task = current.tasks.get(chain.root_task_id)
    temporary_task = Task(
        task_id=node.subtask_id,
        customer_id=chain.customer_id,
        title=node.title,
        category=root_task.category if root_task else "",
        required_skills=node.required_skills,
        required_level=1,
        difficulty=3,
        priority=3,
        estimated_hours=node.estimated_hours,
        deadline=chain.deadline,
        region=root_task.region if root_task else "CN",
        remote_ok=root_task.remote_ok if root_task else True,
        description="",
        status="open",
    )
    service = RecommendationService(
        current,
        weights=weights,
        semantic_matcher=semantic_matcher,
        acceptance_model=acceptance_model,
    )
    pool_size = min(100, max(top_n * 3, top_n + 1))
    candidates = service.recommend_workers_for_task(
        temporary_task, top_n=pool_size
    )
    candidates = exploration.rerank(candidates, k=top_n)
    return RecommendResponse(
        query_id=node.subtask_id,
        candidates=[
            CandidateResponse(
                candidate_id=candidate.candidate_id,
                score=candidate.score,
                breakdown=candidate.breakdown,
                reasons=candidate.reasons,
                cold_start=candidate.cold_start,
                propensity=candidate.propensity,
            )
            for candidate in candidates
        ],
        reason=None if candidates else "no eligible candidates",
    )


def create_app(
    store: Store | None = None,
    weights_dir: Path | None = None,
    benchmark_db: Path | None = None,
    events_dir: Path | None = None,
    exploration_seed: int | None = None,
) -> FastAPI:
    """Create the Phase 2 application."""
    app = FastAPI(title="Task Assignment Recommender", version=APP_VERSION)
    test_assignments = []
    if store is None:
        dataset = generate_dataset()
        store = Store(
            workers=dataset.workers,
            customers=dataset.customers,
            tasks=dataset.tasks,
            assignments=dataset.train,
            feedback=dataset.train_feedback,
            events=dataset.train_events,
            impressions=dataset.train_impressions,
        )
        test_assignments = dataset.test
    app.state.store = store
    app.state.test_assignments = test_assignments
    app.state.semantic_matcher = _build_semantic_matcher(store)
    app.state.acceptance_model = _build_acceptance_model(store)
    app.state.chains = {}
    app.state.drafts = {}
    app.state.plan_store = ChainPlanStore()
    resolved_weights_dir = weights_dir or (
        Path(__file__).resolve().parent.parent / "data" / "weights"
    )
    app.state.weight_store = WeightStore(
        resolved_weights_dir, prior=DEFAULT_WEIGHTS
    )
    app.state.personalizer = PersonalizationService(
        store, Segmenter(), AHP_PRIOR
    )
    app.state.acceptance = AcceptanceService(
        store, personalizer=app.state.personalizer
    )
    app.state.benchmark_db = Path(benchmark_db or BENCHMARK_DB_PATH)
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"template file not found: {TEMPLATE_PATH}")
    app.state.templates = load_templates(TEMPLATE_PATH)

    def require_store() -> Store:
        if app.state.store is None:
            raise HTTPException(status_code=503, detail="store is not initialized")
        return app.state.store

    app.state.events = EventService(
        require_store(),
        persist_dir=events_dir
        or Path(__file__).resolve().parent.parent / "data" / "events",
    )
    app.state.exploration = ExplorationPolicy(
        epsilon=0.10, seed=exploration_seed
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/workers")
    def list_workers() -> list[dict]:
        current = require_store()
        return [asdict(worker) for worker in current.workers.values()]

    @app.get("/resumes")
    def list_resumes(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        current = require_store()
        workers = list(current.workers.values())
        page = workers[offset : offset + limit]
        items = [build_resume(worker)["resume"] for worker in page]
        return {"total": len(workers), "items": items}

    @app.get("/workers/{worker_id}")
    def get_worker(worker_id: str) -> dict:
        current = require_store()
        worker = current.workers.get(worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="worker not found")
        return asdict(worker)

    @app.get("/workers/{worker_id}/resume")
    def get_worker_resume(worker_id: str) -> dict:
        current = require_store()
        worker = current.workers.get(worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="worker not found")
        return build_resume(worker)

    @app.get("/tasks")
    def list_tasks() -> list[dict]:
        current = require_store()
        return [asdict(task) for task in current.tasks.values()]

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        current = require_store()
        task = current.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return asdict(task)

    @app.post("/classify")
    def classify_text(request: ClassifyRequest) -> dict:
        """Classify a free-form posting and extract task fields (no LLM)."""
        try:
            result = get_default_classifier().predict(
                request.text, top_k=request.top_k
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        result["suggested_template"] = result["category"]
        return result

    # ------------------------------------------------------------------
    # Acceptance workflow
    # ------------------------------------------------------------------
    def _acceptance() -> AcceptanceService:
        return app.state.acceptance

    @app.get("/acceptance/demo")
    def acceptance_demo() -> dict:
        try:
            payload = _acceptance().demo_payload()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        task = payload["task"]
        return {
            "task": asdict(task),
            "spec": asdict(payload["spec"]),
            "worker_id": payload["worker_id"],
            "worker_name": payload["worker_name"],
            "reference_time": payload["reference_time"],
            "example_artifacts": payload["example_artifacts"],
            "records": [
                asdict(record)
                for record in _acceptance().records_for_task(task.task_id)
            ],
        }

    @app.post("/acceptance/demo/learning")
    def acceptance_learning(
        rounds: int = Query(default=5, ge=1, le=10),
    ) -> dict:
        try:
            return _acceptance().run_learning_demo(rounds=rounds)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))

    @app.get("/acceptance/metrics")
    def acceptance_metrics() -> dict:
        return _acceptance().metrics()

    @app.get("/tasks/{task_id}/acceptance-spec")
    def acceptance_spec(task_id: str) -> dict:
        current = require_store()
        task = current.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        try:
            spec = _acceptance().spec_for(task)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        return asdict(spec)

    @app.post("/tasks/{task_id}/submissions")
    def create_submission(
        task_id: str, request: SubmissionRequest
    ) -> dict:
        try:
            submission, record = _acceptance().submit(
                task_id,
                request.worker_id,
                request.artifacts,
                submitted_at=request.submitted_at,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        return {
            "submission": asdict(submission),
            "machine_record": asdict(record),
        }

    @app.get("/submissions/{submission_id}")
    def get_submission(submission_id: str) -> dict:
        submission = _acceptance().submissions.get(submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="submission not found")
        return asdict(submission)

    @app.post("/submissions/{submission_id}/review")
    def review_submission(
        submission_id: str, request: ReviewRequest
    ) -> dict:
        try:
            record = _acceptance().review(
                submission_id,
                request.reviewer_id,
                request.scores,
                comments=request.comments,
                layer=request.layer,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        return asdict(record)

    @app.post("/submissions/{submission_id}/decision")
    def decide_submission(
        submission_id: str, request: DecisionRequest
    ) -> dict:
        try:
            record, learning = _acceptance().decide(
                submission_id,
                request.reviewer_id,
                request.decision,
                comment=request.comment,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        submission = _acceptance().submissions[submission_id]
        return {
            "record": asdict(record),
            "submission": asdict(submission),
            "learning": learning,
        }

    @app.get("/tasks/{task_id}/acceptance-records")
    def acceptance_records(task_id: str) -> list[dict]:
        current = require_store()
        if task_id not in current.tasks:
            raise HTTPException(status_code=404, detail="task not found")
        return [
            asdict(record)
            for record in _acceptance().records_for_task(task_id)
        ]

    @app.get("/workers/{worker_id}/capability")
    def worker_capability(worker_id: str) -> dict:
        try:
            return _acceptance().capability(worker_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))

    # ------------------------------------------------------------------
    # 1000-task round benchmark
    # ------------------------------------------------------------------
    @app.get("/benchmark/summary")
    def benchmark_summary() -> dict:
        path = app.state.benchmark_db
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="benchmark db not found; run scripts/build_benchmark.py",
            )
        repo = BenchmarkRepository(path)
        return {
            "db_path": str(path),
            "metadata": repo.load_metadata(),
            "tasks": len(repo.load_tasks()),
            "workers": len(repo.load_workers()),
            "rounds": repo.load_rounds(),
        }

    @app.post("/benchmark/run")
    def run_benchmark(
        rounds: int = Query(default=5, ge=1, le=20),
    ) -> dict:
        path = app.state.benchmark_db
        if not path.exists():
            build_benchmark_db(path)
        runner = BenchmarkRoundRunner(path)
        results = runner.run(rounds=rounds)
        return {
            "db_path": str(path),
            "results": results,
            "rounds": runner.repo.load_rounds(),
        }

    @app.get("/weights")
    def get_weights() -> dict:
        return asdict(app.state.weight_store.active())

    @app.get("/weights/diff")
    def diff_weights(
        from_version: str = Query(alias="from"),
        to_version: str = Query(alias="to"),
    ) -> dict:
        try:
            return app.state.weight_store.diff(from_version, to_version)
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail=f"unknown version: {error}"
            )

    @app.post("/weights/rollback")
    def rollback_weights(request: RollbackRequest) -> dict:
        try:
            version = app.state.weight_store.rollback(
                request.to_version, request.reason
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail=f"unknown version: {error}"
            )
        return asdict(version)

    @app.get("/learning/changelog")
    def learning_changelog() -> list[dict]:
        return app.state.weight_store.changelog()

    @app.post("/assignments")
    def create_assignment(request: CreateAssignmentRequest) -> dict:
        current = require_store()
        service = FeedbackService(current)
        try:
            assignment = service.record_assignment(
                request.task_id,
                request.worker_id,
                request.customer_id,
                request.recommendation_context,
            )
        except KeyError:
            raise HTTPException(
                status_code=404, detail="task or worker not found"
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))
        context = request.recommendation_context
        if context is not None and context.request_id:
            try:
                app.state.events.record_event(
                    context.request_id,
                    request.worker_id,
                    "accept",
                    user_id=request.customer_id,
                    role="customer",
                    metadata={
                        "weights_version": app.state.weight_store.active().version
                    },
                )
            except (KeyError, ValueError):
                # The assignment still succeeds when the recommendation
                # request is unknown, e.g. it predates this process, or the
                # accept was already recorded through POST /events.
                pass
        return asdict(assignment)

    @app.post("/feedback")
    def create_feedback(request: FeedbackRequest) -> dict:
        current = require_store()
        service = FeedbackService(current)
        try:
            feedback = service.record_feedback(
                request.assignment_id,
                request.overall_rating,
                quality_rating=request.quality_rating,
                timeliness_rating=request.timeliness_rating,
                communication_rating=request.communication_rating,
                comment=request.comment,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="assignment not found")
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))

        response = asdict(feedback)
        assignment = next(
            (
                item
                for item in current.assignments
                if item.assignment_id == feedback.assignment_id
            ),
            None,
        )
        if assignment is not None:
            task = current.tasks.get(assignment.task_id)
            worker = current.workers.get(assignment.worker_id)
            customer = (
                current.customers.get(task.customer_id) if task else None
            )
            if task is not None and worker is not None and customer is not None:
                features = candidate_features(
                    worker,
                    task,
                    customer,
                    cf_score=0.0,
                    now=current.reference_time,
                )
                personalizer: PersonalizationService = (
                    app.state.personalizer
                )
                personalizer.ensure_profile(worker.worker_id, "worker")
                updated = personalizer.update(
                    worker.worker_id, features, feedback.overall_rating
                )
                worker_preference = current.worker_preferences.get(
                    worker.worker_id
                ) or WorkerPreferenceProfile(worker.worker_id)
                current.worker_preferences[worker.worker_id] = (
                    update_worker_preferences(
                        worker_preference,
                        task,
                        accepted=True,
                        rating=feedback.overall_rating,
                        now=current.reference_time,
                    )
                )
                customer_preference = (
                    current.customer_preferences.get(customer.customer_id)
                    or CustomerPreferenceProfile(customer.customer_id)
                )
                current.customer_preferences[customer.customer_id] = (
                    update_customer_preferences(
                        customer_preference,
                        worker,
                        task,
                        feedback.overall_rating,
                        current.reference_time,
                    )
                )
                personalizer.snapshot(
                    worker.worker_id, 0.0, 0.0, 0.0
                )
                response["weights_updated"] = True
                response["new_version"] = updated.version
        return response

    @app.get("/workers/{worker_id}/reputation")
    def worker_reputation(worker_id: str) -> dict:
        current = require_store()
        try:
            return FeedbackService(current).reputation(worker_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="worker not found")

    def onboarding_response(
        user_id: str, entity_type: str, request: OnboardingRequest
    ) -> dict:
        current = require_store()
        user = (
            current.workers.get(user_id)
            if entity_type == "worker"
            else current.customers.get(user_id)
        )
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        personalizer: PersonalizationService = app.state.personalizer
        personalizer.global_weights = dict(
            app.state.weight_store.active().weights
        )
        if request.reset:
            current.profiles.pop(user_id, None)
            current.user_weight_profiles.pop(user_id, None)
        personalizer.ensure_profile(
            user_id, entity_type, request.model_dump()
        )
        profile = personalizer.weights_for(user_id)
        return {
            "user_id": user_id,
            "weights": profile.weights,
            "source": profile.source,
            "segment_id": profile.segment_id,
            "sample_count": profile.sample_count,
            "confidence": profile.confidence,
            "version": profile.version,
        }

    @app.post("/workers/{worker_id}/onboarding")
    def onboard_worker(
        worker_id: str, request: OnboardingRequest
    ) -> dict:
        return onboarding_response(worker_id, "worker", request)

    @app.post("/customers/{customer_id}/onboarding")
    def onboard_customer(
        customer_id: str, request: OnboardingRequest
    ) -> dict:
        return onboarding_response(customer_id, "customer", request)

    @app.get("/workers/{worker_id}/weight-profile")
    def worker_weight_profile(worker_id: str) -> dict:
        current = require_store()
        if worker_id not in current.workers:
            raise HTTPException(status_code=404, detail="worker not found")
        profile = app.state.personalizer.weights_for(worker_id)
        return asdict(profile)

    @app.get("/customers/{customer_id}/weight-profile")
    def customer_weight_profile(customer_id: str) -> dict:
        current = require_store()
        if customer_id not in current.customers:
            raise HTTPException(status_code=404, detail="customer not found")
        profile = app.state.personalizer.weights_for(customer_id)
        return asdict(profile)

    @app.get("/workers/{worker_id}/learning-curve")
    def worker_learning_curve(worker_id: str) -> list[dict]:
        current = require_store()
        if worker_id not in current.workers:
            raise HTTPException(status_code=404, detail="worker not found")
        return [
            asdict(snapshot)
            for snapshot in current.learning_snapshots
            if snapshot.user_id == worker_id
        ]

    @app.post("/weights/recompute")
    def recompute_weights() -> dict:
        current = require_store()
        feedback_by_assignment = {
            feedback.assignment_id: feedback
            for feedback in current.feedback
        }
        records = []
        for assignment in current.assignments:
            feedback = feedback_by_assignment.get(assignment.assignment_id)
            if feedback is None:
                continue
            task = current.tasks.get(assignment.task_id)
            worker = current.workers.get(assignment.worker_id)
            customer = (
                current.customers.get(task.customer_id) if task else None
            )
            if task is None or worker is None or customer is None:
                continue
            features = candidate_features(
                worker,
                task,
                customer,
                cf_score=0.0,
                now=current.reference_time,
            )
            records.append((features, feedback.overall_rating))
        active = app.state.weight_store.active()
        learner = OnlineWeightLearner(active.weights)
        learner.batch_fit(records, epochs=1)
        version = app.state.weight_store.create(
            learner.weights, len(records), "batch"
        )
        return asdict(version)

    @app.get("/metrics/compare")
    def metrics_compare(
        run_a: str | None = None,
        run_b: str | None = None,
    ) -> dict:
        if run_a is not None or run_b is not None:
            if not run_a or not run_b:
                raise HTTPException(
                    status_code=422,
                    detail="run_a and run_b are required together",
                )
            try:
                version_a = app.state.weight_store.get(run_a)
                version_b = app.state.weight_store.get(run_b)
            except KeyError:
                raise HTTPException(
                    status_code=404, detail="unknown weight version"
                )
            current = require_store()
            service = RecommendationService(
                current,
                weights=version_a.weights,
                semantic_matcher=app.state.semantic_matcher,
                acceptance_model=app.state.acceptance_model,
            )
            held_out = getattr(app.state, "test_assignments", [])
            if not held_out:
                return {
                    "available": False,
                    "reason": "no held-out test assignments",
                }
            evaluation_store = Store(
                workers=list(current.workers.values()),
                customers=list(current.customers.values()),
                tasks=list(current.tasks.values()),
                assignments=held_out[-50:],
                feedback=current.feedback,
            )
            metrics = evaluate_two_runs(
                evaluation_store,
                service,
                version_a.weights,
                version_b.weights,
            )
            return {
                "run_a": run_a,
                "run_b": run_b,
                "metrics": metrics,
            }
        path = REPORTS_DIR / "phase2_metrics.json"
        if not path.exists():
            return {"available": False}
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/metrics/learning-curve")
    def metrics_learning_curve() -> dict:
        path = REPORTS_DIR / "phase2_metrics.json"
        if not path.exists():
            return {"available": False}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("learning_curve", {})

    @app.get("/metrics/learning-rounds")
    def metrics_learning_rounds() -> dict:
        path = REPORTS_DIR / "learning_rounds.json"
        if not path.exists():
            return {"available": False}
        return json.loads(path.read_text(encoding="utf-8"))

    @app.post("/events", response_model=EventsResponse)
    def record_events(request: EventsRequest) -> EventsResponse:
        weights_version = app.state.weight_store.active().version
        accepted = 0
        for item in request.events:
            metadata = dict(item.metadata)
            if "candidate_type" in item.model_fields_set:
                metadata["candidate_type"] = item.candidate_type
            if "task_id" in item.model_fields_set:
                metadata["task_id"] = item.task_id
            metadata["weights_version"] = weights_version
            try:
                app.state.events.record_event(
                    item.request_id,
                    item.candidate_id,
                    item.action,
                    user_id=item.user_id,
                    role=item.role,
                    metadata=metadata,
                )
            except KeyError as error:
                raise HTTPException(
                    status_code=404, detail=f"unknown event target: {error}"
                )
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error))
            accepted += 1
        return EventsResponse(accepted=accepted)

    @app.get("/events/metrics")
    def event_metrics() -> dict:
        return app.state.events.funnel_metrics()

    @app.post("/recommend/workers", response_model=RecommendResponse)
    def recommend_workers(request: RecommendWorkersRequest) -> RecommendResponse:
        current = require_store()
        service = RecommendationService(
            current,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )
        pool_size = min(100, max(request.top_n * 3, request.top_n + 1))
        try:
            candidates = service.recommend_workers(
                request.task_id,
                top_n=pool_size,
                user_id=request.user_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="task not found")
        candidates = app.state.exploration.rerank(
            candidates, k=request.top_n
        )
        request_id = uuid.uuid4().hex
        if candidates:
            app.state.events.record_impression(
                request_id,
                request.task_id,
                [candidate.candidate_id for candidate in candidates],
                {
                    candidate.candidate_id: candidate.propensity
                    for candidate in candidates
                },
                "epsilon_greedy_topk",
                metadata={"candidate_type": "worker"},
            )
        return RecommendResponse(
            query_id=request.task_id,
            candidates=[
                CandidateResponse(
                    candidate_id=candidate.candidate_id,
                    score=candidate.score,
                    breakdown=candidate.breakdown,
                    reasons=candidate.reasons,
                    cold_start=candidate.cold_start,
                    propensity=candidate.propensity,
                )
                for candidate in candidates
            ],
            reason=None if candidates else "no eligible candidates",
            request_id=request_id,
        )

    @app.post("/recommend/tasks", response_model=RecommendResponse)
    def recommend_tasks(request: RecommendTasksRequest) -> RecommendResponse:
        current = require_store()
        service = RecommendationService(
            current,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )
        pool_size = min(100, max(request.top_n * 3, request.top_n + 1))
        try:
            candidates = service.recommend_tasks(
                request.worker_id,
                top_n=pool_size,
                user_id=request.user_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="worker not found")
        candidates = app.state.exploration.rerank(
            candidates, k=request.top_n
        )
        request_id = uuid.uuid4().hex
        if candidates:
            app.state.events.record_impression(
                request_id,
                request.worker_id,
                [candidate.candidate_id for candidate in candidates],
                {
                    candidate.candidate_id: candidate.propensity
                    for candidate in candidates
                },
                "epsilon_greedy_topk",
                metadata={"candidate_type": "task"},
            )
        return RecommendResponse(
            query_id=request.worker_id,
            candidates=[
                CandidateResponse(
                    candidate_id=candidate.candidate_id,
                    score=candidate.score,
                    breakdown=candidate.breakdown,
                    reasons=candidate.reasons,
                    cold_start=candidate.cold_start,
                    propensity=candidate.propensity,
                )
                for candidate in candidates
            ],
            reason=None if candidates else "no eligible candidates",
            request_id=request_id,
        )

    @app.post("/chains/decompose")
    def decompose_chain(request: DecomposeRequest) -> dict:
        current = require_store()
        task = current.tasks.get(request.task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        try:
            if request.mode == "compose":
                categories = request.categories or [task.category]
                template = compose_templates(
                    task, app.state.templates, categories
                )
            else:
                template = app.state.templates.get(task.category)
                if template is None:
                    raise ValueError(
                        f"没有该任务类别的模板: {task.category}"
                    )
            draft = decompose(
                task,
                template,
                variant=request.variant,
                max_nodes=template.get("max_nodes", 10),
            )
            draft.quality = quality_score(draft, current)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        app.state.chains[draft.chain.chain_id] = draft.chain
        app.state.drafts[draft.draft_id] = draft
        return {
            "draft_id": draft.draft_id,
            "chain_id": draft.chain.chain_id,
            "quality": asdict(draft.quality),
            "nodes": [asdict(node) for node in draft.chain.nodes],
            "critical_path": draft.chain.critical_path,
        }

    @app.get("/chains/{chain_id}")
    def get_chain(chain_id: str) -> dict:
        chain = app.state.chains.get(chain_id)
        if chain is None:
            raise HTTPException(status_code=404, detail="chain not found")
        return _serialize_chain(chain)

    @app.post("/chains/{chain_id}/plan")
    def plan(chain_id: str) -> dict:
        current = require_store()
        chain = app.state.chains.get(chain_id)
        if chain is None:
            raise HTTPException(status_code=404, detail="chain not found")
        service = RecommendationService(
            current,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )
        result = plan_chain(chain, service)
        version = app.state.plan_store.save(result)
        return {
            "plan_id": result.plan_id,
            "chain_id": result.chain_id,
            "score": result.score,
            "blocked": result.blocked,
            "version": version,
            "planner": result.planner,
            "nodes": [asdict(node) for node in result.nodes],
        }

    @app.get("/chains/{chain_id}/plans")
    def list_chain_plans(chain_id: str) -> list[dict]:
        plans = app.state.plan_store.versions(chain_id)
        return [
            {"version": index + 1, "plan": asdict(plan)}
            for index, plan in enumerate(plans)
        ]

    @app.post("/chains/{chain_id}/plan/rollback")
    def rollback_chain_plan(
        chain_id: str, request: PlanRollbackRequest
    ) -> dict:
        try:
            plan = app.state.plan_store.rollback(
                chain_id, request.version
            )
        except KeyError:
            raise HTTPException(
                status_code=404, detail="plan version not found"
            )
        return {"version": request.version, "plan": asdict(plan)}

    @app.post("/chains/{chain_id}/replan")
    def replan(chain_id: str, request: ReplanRequest) -> dict:
        current = require_store()
        chain = app.state.chains.get(chain_id)
        if chain is None:
            raise HTTPException(status_code=404, detail="chain not found")
        try:
            active_plan = app.state.plan_store.active(chain_id)
        except KeyError:
            raise HTTPException(
                status_code=404, detail="no active plan"
            )
        service = RecommendationService(
            current,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )
        locked_nodes = set(request.locked_nodes) | {
            node.key
            for node in chain.nodes
            if node.status in {"completed", "in_progress"}
        }
        try:
            result = replan_chain(
                chain,
                service,
                request.failed_node,
                request.delay_hours,
                locked_nodes,
                current_plan=active_plan,
            )
            impact = propagate_breach(
                chain, request.failed_node, request.delay_hours
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        version = app.state.plan_store.save(result)
        return {
            "plan_id": result.plan_id,
            "chain_id": result.chain_id,
            "score": result.score,
            "blocked": result.blocked,
            "version": version,
            "planner": result.planner,
            "affected_nodes": impact.affected_nodes,
            "replanned": sorted(
                set(impact.affected_nodes) | {request.failed_node}
            ),
            "nodes": [asdict(node) for node in result.nodes],
        }

    @app.post("/chains/{chain_id}/nodes/{node_id}/status")
    def set_node_status(
        chain_id: str, node_id: str, request: NodeStatusRequest
    ) -> dict:
        chain = app.state.chains.get(chain_id)
        if chain is None:
            raise HTTPException(status_code=404, detail="任务链不存在")
        node = next(
            (
                item
                for item in chain.nodes
                if item.key == node_id or item.subtask_id == node_id
            ),
            None,
        )
        if node is None:
            raise HTTPException(status_code=404, detail="节点不存在")
        if request.status not in {"pending", "in_progress", "completed"}:
            raise HTTPException(
                status_code=422, detail="不支持的节点状态"
            )
        node.status = request.status
        if request.worker_id is not None:
            node.assigned_worker_id = request.worker_id
        return {
            "node": node.key,
            "status": node.status,
            "worker_id": node.assigned_worker_id,
        }

    if FRONTEND_DIR.exists():
        app.mount(
            "/ui",
            StaticFiles(directory=FRONTEND_DIR, html=True),
            name="ui",
        )

        @app.get("/")
        def root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

    @app.post(
        "/chains/{chain_id}/nodes/{node_id}/recommend",
        response_model=RecommendResponse,
    )
    def recommend_node(
        chain_id: str, node_id: str, request: NodeRecommendRequest
    ) -> RecommendResponse:
        current = require_store()
        chain = app.state.chains.get(chain_id)
        if chain is None:
            raise HTTPException(status_code=404, detail="chain not found")
        return _node_candidates(
            chain,
            node_id,
            current,
            request.top_n,
            app.state.exploration,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )

    return app
