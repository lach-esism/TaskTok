"""FastAPI application factory and routes."""

from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser

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
from app.domain import (
    Impression,
    RecommendationEvent,
    Task,
    TaskChain,
    Worker,
)
from app.evaluation_phase2 import evaluate_two_runs
from app.events import EventService
from app.feedback import FeedbackService
from app.features import candidate_features
from app.learning.acceptance import AcceptanceModel
from app.learning.custom_demo import simulate_custom_step
from app.learning.resume_feed import (
    build_resume_demo_store,
    simulate_resume_refresh,
)
from app.learning.choice import (
    NEGATIVE_ACTIONS,
    POSITIVE_ACTIONS,
    ListwiseChoiceLearner,
    PairwiseChoiceLearner,
    build_pairs,
)
from app.learning.exploration import ExplorationPolicy
from app.learning.online import OnlineWeightLearner
from app.learning.weights import AHP_PRIOR, project_weights_with_report
from app.semantic import SemanticMatcher
from app.serving import (
    build_acceptance_model as _build_acceptance_model,
)
from app.serving import (
    build_semantic_matcher as _build_semantic_matcher,
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
    CustomDemoRequest,
    DecisionRequest,
    DecomposeRequest,
    EventsRequest,
    EventsResponse,
    FeedbackRequest,
    NodeRecommendRequest,
    MAX_EVENTS_BODY_BYTES,
    NodeStatusRequest,
    ReviewRequest,
    SubmissionRequest,
    OnboardingRequest,
    PlanRollbackRequest,
    RecommendResponse,
    RecommendTasksRequest,
    RecommendWorkersRequest,
    ReplanRequest,
    ResumeAnalyzeRequest,
    ResumeFeedRequest,
    RollbackRequest,
)
from app.service import RecommendationService
from app.upload import analyze as upload_analyze
from app.upload import extract as upload_extract
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


#: Choice-learning objective used by ``POST /weights/recompute``. The
#: default pairwise learner is exact-event based; ``listwise`` fits one
#: softmax step per logged impression instead.
CHOICE_LEARNING_MODE = os.environ.get(
    "CHOICE_LEARNING_MODE", "pairwise"
).strip().lower()
CHOICE_ACTIONS = POSITIVE_ACTIONS | NEGATIVE_ACTIONS


def _find_impression(
    impressions: list[Impression], request_id: str
) -> Impression | None:
    for impression in reversed(impressions):
        if impression.request_id == request_id:
            return impression
    return None


def _event_target(
    event: RecommendationEvent,
    impressions_by_request: dict[str, Impression],
) -> tuple[str, str] | None:
    """Map an event to the ``(task_id, worker_id)`` pair it refers to."""
    if event.candidate_type == "task":
        impression = impressions_by_request.get(event.request_id)
        if impression is None:
            return None
        return event.candidate_id, impression.query_id
    if not event.task_id:
        return None
    return event.task_id, event.candidate_id


def _impression_candidate_target(
    impression: Impression, candidate_id: str
) -> tuple[str, str]:
    """Map an impression candidate to ``(task_id, worker_id)``."""
    if impression.metadata.get("candidate_type") == "task":
        return candidate_id, impression.query_id
    return impression.query_id, candidate_id


def _features_with_cache(
    service: RecommendationService,
    cache: dict[tuple[str, str], dict[str, float]],
    target: tuple[str, str],
) -> dict[str, float]:
    cached = cache.get(target)
    if cached is None:
        cached = service.features_for(*target)
        cache[target] = cached
    return cached


def _events_with_features(
    events: list[RecommendationEvent],
    service: RecommendationService,
) -> tuple[list[RecommendationEvent], dict[str, dict[str, float]]]:
    """Resolve feature vectors for events that still map to store entities.

    Events whose impression, task, or worker is unavailable are dropped so a
    stale log row can never fail choice learning.
    """
    impressions_by_request = {
        impression.request_id: impression
        for impression in service.store.impressions
    }
    cache: dict[tuple[str, str], dict[str, float]] = {}
    usable: list[RecommendationEvent] = []
    features_by_event: dict[str, dict[str, float]] = {}
    for event in events:
        if event.action not in CHOICE_ACTIONS:
            continue
        target = _event_target(event, impressions_by_request)
        if target is None:
            continue
        try:
            features = _features_with_cache(service, cache, target)
        except KeyError:
            continue
        features_by_event[event.event_id] = features
        usable.append(event)
    return usable, features_by_event


def _listwise_choice_weights(
    store: Store,
    service: RecommendationService,
    prior: dict[str, float],
) -> tuple[dict[str, float], int]:
    """Run one listwise softmax pass over each logged impression."""
    events_by_request: dict[str, list[RecommendationEvent]] = {}
    for event in store.events:
        events_by_request.setdefault(event.request_id, []).append(event)

    learner = ListwiseChoiceLearner(prior)
    cache: dict[tuple[str, str], dict[str, float]] = {}
    updates = 0
    for impression in store.impressions:
        request_events = events_by_request.get(impression.request_id, [])
        positives = [
            event
            for event in request_events
            if event.action in POSITIVE_ACTIONS
            and event.candidate_id in impression.candidate_ids
        ]
        if not positives:
            continue
        chosen = min(positives, key=lambda event: event.rank)
        candidate_features: list[dict[str, float]] = []
        try:
            for candidate_id in impression.candidate_ids:
                candidate_features.append(
                    _features_with_cache(
                        service,
                        cache,
                        _impression_candidate_target(
                            impression, candidate_id
                        ),
                    )
                )
        except KeyError:
            continue
        chosen_index = impression.candidate_ids.index(chosen.candidate_id)
        propensity = max(float(chosen.propensity), 1e-12)
        sample_weight = max(0.1, min(10.0, 1.0 / propensity))
        learner.learn(
            candidate_features,
            chosen_index,
            sample_weight=sample_weight,
        )
        updates += 1
    return dict(learner.weights), updates


def _node_candidates(
    chain: TaskChain,
    node_id: str,
    current: Store,
    top_n: int,
    exploration: ExplorationPolicy,
    weights: dict[str, float] | None = None,
    semantic_matcher: SemanticMatcher | None = None,
    acceptance_model: AcceptanceModel | None = None,
    service: RecommendationService | None = None,
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
    if service is None:
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


def _candidate_payload(candidate) -> dict:
    """Serialize a ``ScoredCandidate`` without mutating or logging anything."""
    return {
        "candidate_id": candidate.candidate_id,
        "score": round(float(candidate.score), 4),
        "breakdown": dict(candidate.breakdown),
        "reasons": list(candidate.reasons),
        "cold_start": bool(candidate.cold_start),
        "propensity": float(candidate.propensity),
    }


def _ephemeral_store_with_worker(store: Store, worker: Worker) -> Store:
    """Return a shallow store copy whose only difference is one temp worker.

    ``RecommendationService.recommend_tasks`` looks the worker up by ID, but
    uploads must never write into the real store. A shallow copy plus a new
    ``workers`` mapping gives the service a valid lookup without touching the
    live data.
    """
    clone = copy.copy(store)
    clone.workers = dict(store.workers)
    clone.workers[worker.worker_id] = worker
    return clone


async def _parse_upload_form(request: Request) -> tuple[UploadFile, int]:
    """Parse the upload form with explicit file/field caps.

    FastAPI's implicit parsing uses Starlette's broad defaults; parsing here
    lets us cap ``max_files=1`` / ``max_fields=8`` while the ASGI middleware
    has already rejected over-limit bodies before this point.
    """
    try:
        form = await request.form(max_files=1, max_fields=8)
    except StarletteHTTPException as error:
        raise HTTPException(
            status_code=422, detail=f"multipart 表单无效：{error.detail}"
        ) from None

    file = form.get("file")
    if not isinstance(file, UploadFile):
        await form.close()
        raise HTTPException(
            status_code=422, detail="缺少 multipart 文件字段 file"
        )
    raw_top_n = form.get("top_n", "5")
    try:
        top_n = int(raw_top_n)
    except (TypeError, ValueError):
        await form.close()
        raise HTTPException(
            status_code=422, detail="top_n 必须是整数"
        ) from None
    if not 1 <= top_n <= 50:
        await form.close()
        raise HTTPException(
            status_code=422, detail="top_n 必须在 1 到 50 之间"
        )
    return file, top_n


async def _read_upload(file: UploadFile) -> bytes:
    """Read at most the upload limit, then reject anything larger."""
    limit = upload_extract.MAX_UPLOAD_BYTES
    declared_size = getattr(file, "size", None)
    if declared_size is not None and declared_size > limit:
        await file.close()
        raise HTTPException(
            status_code=422,
            detail=(
                "文件超过上传大小限制"
                f"（{upload_extract.upload_limit_label(limit)}）"
            ),
        )
    raw = await file.read(limit + 1)
    await file.close()
    if len(raw) > limit:
        raise HTTPException(
            status_code=422,
            detail=(
                "文件超过上传大小限制"
                f"（{upload_extract.upload_limit_label(limit)}）"
            ),
        )
    return raw


def _text_preview(text: str, limit: int = 600) -> str:
    return " ".join(text.split())[:limit]


# The upload handlers take ``Request`` so they can call
# ``request.form(max_files=1, max_fields=8)`` after the ASGI body cap. That
# removes FastAPI's automatic File/Form parameters, so document the multipart
# contract explicitly for OpenAPI clients.
_UPLOAD_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": ".txt, .md, .pdf, or .docx (≤10 MB)",
                        },
                        "top_n": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                }
            }
        },
    }
}


def create_app(
    store: Store | None = None,
    weights_dir: Path | None = None,
    benchmark_db: Path | None = None,
    events_dir: Path | None = None,
    exploration_seed: int | None = None,
) -> FastAPI:
    """Create the Phase 2 application."""
    # Accepted uploads are capped at MAX_UPLOAD_BYTES before form parsing, so
    # this spool threshold keeps the accepted file parts in RAM.
    MultiPartParser.spool_max_size = upload_extract.MAX_UPLOAD_BYTES
    app = FastAPI(title="Task Assignment Recommender", version=APP_VERSION)
    app.add_middleware(upload_extract.UploadBodyLimitMiddleware)
    # ``/events`` has its own smaller body cap (no multipart, JSON only).
    app.add_middleware(
        upload_extract.UploadBodyLimitMiddleware,
        paths=frozenset({"/events"}),
        limit=MAX_EVENTS_BODY_BYTES,
    )
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
    app.state.choice_learning_mode = CHOICE_LEARNING_MODE
    app.state.last_binding = None
    app.state.personalized_requests = set()
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
    app.state.service_cache = None

    def invalidate_service() -> None:
        """Drop the cached ranker after assignments/feedback/weights change."""
        app.state.service_cache = None

    def active_service() -> RecommendationService:
        """Return one cached ``RecommendationService`` for serving requests.

        Rebuilding the service recreates ItemCF and the per-request context
        indexes. The cache is keyed by the active weight version and by the
        assignment/feedback lengths, which are the only store inputs that alter
        ItemCF or eligibility. Impressions and events are read live through the
        shared store, so ordinary event ingestion does not force a rebuild.
        """
        current = require_store()
        version = app.state.weight_store.active().version
        signature = (
            version,
            id(current),
            len(current.assignments),
            len(current.feedback),
        )
        cached = app.state.service_cache
        if cached is not None and cached[0] == signature:
            return cached[1]
        service = RecommendationService(
            current,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )
        app.state.service_cache = (signature, service)
        return service

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
        # Additive, evidence-bearing fields. ``confidence``, ``margin``,
        # ``calibrated_confidence``, ``confidence_threshold``, ``evidence``
        # and ``extracted_v2`` already come from the classifier; ``fields_v2``
        # is a stable alias for Task 22's upload/resume analysis to consume.
        result["fields_v2"] = result.get("extracted_v2", {})
        return result

    # ------------------------------------------------------------------
    # Bidirectional upload / paste analysis (drafts only, no store writes)
    # ------------------------------------------------------------------
    def _upload_service(current: Store) -> RecommendationService:
        if current is app.state.store:
            return active_service()
        # Upload drafts may use an ephemeral store clone with a temporary
        # worker; that store is never cached.
        return RecommendationService(
            current,
            weights=app.state.weight_store.active().weights,
            semantic_matcher=app.state.semantic_matcher,
            acceptance_model=app.state.acceptance_model,
        )

    def _task_upload_payload(
        current: Store,
        text: str,
        filename: str,
        content_type: str | None,
        size_bytes: int,
        top_n: int,
    ) -> dict:
        if not text.strip():
            raise HTTPException(status_code=422, detail="任务文本不能为空")
        analysis = upload_analyze.analyze_task_text(text)
        customer_id = next(iter(current.customers), "customer_upload")
        draft_task = upload_analyze.task_from_analysis(
            analysis, customer_id=customer_id, text=text
        )
        candidates = _upload_service(current).recommend_workers_for_task(
            draft_task, top_n=top_n
        )
        return {
            "kind": "task",
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "text_preview": _text_preview(text),
            "analysis": analysis,
            "draft": upload_analyze.build_task_draft(analysis=analysis, task=draft_task),
            "candidates": [
                _candidate_payload(candidate) for candidate in candidates
            ],
            "request_id": uuid.uuid4().hex,
            "persisted": False,
        }

    def _resume_payload(
        current: Store,
        text: str,
        filename: str | None,
        content_type: str | None,
        size_bytes: int,
        top_n: int,
    ) -> dict:
        if not text.strip():
            raise HTTPException(status_code=422, detail="简历文本不能为空")
        analysis = upload_analyze.analyze_resume_text(text)
        draft_worker = analysis["draft_worker"]
        worker = upload_analyze.worker_from_draft(draft_worker)
        ephemeral = _ephemeral_store_with_worker(current, worker)
        candidates = _upload_service(ephemeral).recommend_tasks(
            worker.worker_id, top_n=top_n
        )
        return {
            "kind": "resume",
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "text_preview": _text_preview(text),
            "analysis": analysis,
            "draft": draft_worker,
            "candidates": [
                _candidate_payload(candidate) for candidate in candidates
            ],
            "request_id": uuid.uuid4().hex,
            "persisted": False,
        }

    @app.post("/upload/task", openapi_extra=_UPLOAD_OPENAPI_EXTRA)
    async def upload_task(request: Request) -> dict:
        """Analyze an uploaded task document and return Top-N workers.

        The body cap is enforced by ``UploadBodyLimitMiddleware`` before form
        parsing. The file is parsed in memory and never persisted; the returned
        task is a draft. The store is not written to.
        """
        current = require_store()
        file, top_n = await _parse_upload_form(request)
        raw = await _read_upload(file)
        filename = upload_extract.sanitize_filename(
            file.filename or "document.txt"
        )
        try:
            text = upload_extract.extract_text(
                filename, raw, content_type=file.content_type
            )
            return _task_upload_payload(
                current,
                text,
                filename,
                file.content_type,
                len(raw),
                top_n,
            )
        except upload_extract.UploadError as error:
            raise HTTPException(status_code=422, detail=str(error))

    @app.post("/upload/resume", openapi_extra=_UPLOAD_OPENAPI_EXTRA)
    async def upload_resume(request: Request) -> dict:
        """Analyze an uploaded resume and return Top-N open tasks.

        A temporary ``Worker`` profile is placed in an ephemeral store copy so
        ``RecommendationService.recommend_tasks`` can score it. The real store
        is never mutated and the returned worker is a draft.
        """
        current = require_store()
        file, top_n = await _parse_upload_form(request)
        raw = await _read_upload(file)
        filename = upload_extract.sanitize_filename(
            file.filename or "document.txt"
        )
        try:
            text = upload_extract.extract_text(
                filename, raw, content_type=file.content_type
            )
            return _resume_payload(
                current,
                text,
                filename,
                file.content_type,
                len(raw),
                top_n,
            )
        except upload_extract.UploadError as error:
            raise HTTPException(status_code=422, detail=str(error))

    @app.post("/resume/analyze")
    def analyze_resume_text(request: ResumeAnalyzeRequest) -> dict:
        """Paste-text resume path: same analyzer, no file and no persistence."""
        current = require_store()
        if not request.text.strip():
            raise HTTPException(status_code=422, detail="简历文本不能为空")
        try:
            return _resume_payload(
                current,
                request.text,
                None,
                None,
                len(request.text.encode("utf-8")),
                request.top_n,
            )
        except upload_extract.UploadError as error:
            raise HTTPException(status_code=422, detail=str(error))

    @app.post("/demo/resume/refresh")
    def resume_feed_refresh(request: ResumeFeedRequest) -> dict:
        require_store()
        demo_store = getattr(app.state, "resume_demo_store", None)
        if demo_store is None:
            demo_store = build_resume_demo_store()
            app.state.resume_demo_store = demo_store
            app.state.resume_exploration = ExplorationPolicy(
                epsilon=0.1, seed=42
            )
            app.state.resume_events = EventService(demo_store)
            app.state.resume_personalizer = PersonalizationService(
                demo_store, Segmenter(seed=42), DEFAULT_WEIGHTS
            )
        try:
            return simulate_resume_refresh(
                demo_store,
                request.model_dump(),
                exploration=app.state.resume_exploration,
                events=app.state.resume_events,
                personalizer=app.state.resume_personalizer,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))

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

    @app.post("/demo/custom/step")
    def custom_demo_step(request: CustomDemoRequest) -> dict:
        current = require_store()
        try:
            return simulate_custom_step(current, request.model_dump())
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
        rounds: int = Query(default=20, ge=1, le=20),
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
        invalidate_service()
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
        invalidate_service()
        context = request.recommendation_context
        if context is not None and context.request_id:
            impression = _find_impression(
                current.impressions, context.request_id
            )
            if impression is not None:
                # Derive the accepted candidate from the impression, and only
                # record the accept when this assignment matches the query that
                # produced the recommendation. A client cannot attach an
                # unrelated request_id to manufacture an accept event.
                impression_type = str(
                    impression.metadata.get("candidate_type") or "worker"
                )
                if impression_type == "task":
                    candidate_id = request.task_id
                    valid = (
                        request.worker_id == impression.query_id
                        and request.task_id in impression.candidate_ids
                    )
                    default_role = "worker"
                    default_user = request.worker_id
                else:
                    candidate_id = request.worker_id
                    valid = (
                        request.task_id == impression.query_id
                        and request.worker_id in impression.candidate_ids
                    )
                    default_role = "customer"
                    default_user = request.customer_id
                if valid:
                    try:
                        app.state.events.record_event(
                            context.request_id,
                            candidate_id,
                            "accept",
                            user_id=(
                                impression.metadata.get("user_id")
                                or default_user
                            ),
                            role=str(
                                impression.metadata.get("role")
                                or default_role
                            ),
                            metadata={
                                "weights_version": (
                                    app.state.weight_store.active().version
                                )
                            },
                        )
                    except (KeyError, ValueError):
                        # The assignment still succeeds when the accept was
                        # already recorded through POST /events.
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

        invalidate_service()
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
    def recompute_weights(
        include_events: bool = Query(default=True),
    ) -> dict:
        current = require_store()
        active = app.state.weight_store.active()
        prior = dict(active.weights)
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

        learner = OnlineWeightLearner(prior)
        learner.batch_fit(records, epochs=1)
        merged = dict(learner.weights)
        updates = len(records)
        choice_updates = 0
        mode = getattr(
            app.state, "choice_learning_mode", CHOICE_LEARNING_MODE
        )
        mode = "listwise" if mode == "listwise" else "pairwise"
        if include_events:
            service = active_service()
            if mode == "listwise":
                choice_weights, choice_updates = _listwise_choice_weights(
                    current, service, prior
                )
            else:
                usable, features_by_event = _events_with_features(
                    current.events, service
                )
                pairs = build_pairs(
                    usable,
                    lambda event: features_by_event[event.event_id],
                )
                choice_learner = PairwiseChoiceLearner(prior=prior)
                choice_weights = choice_learner.fit(pairs)
                choice_updates = len(pairs)
            updates += choice_updates
            if choice_updates:
                merged = {
                    key: 0.5 * merged.get(key, 0.0)
                    + 0.5 * choice_weights.get(key, 0.0)
                    for key in prior
                }
        final, report = project_weights_with_report(merged)
        binding = asdict(report)
        app.state.last_binding = binding
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "weight_binding.json").write_text(
            json.dumps(binding, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source = (
            f"batch+{mode}"
            if include_events and choice_updates
            else "batch"
        )
        version = app.state.weight_store.create(
            final, updates, source
        )
        invalidate_service()
        payload = asdict(version)
        payload["updates"] = updates
        payload["binding"] = binding
        payload["mode"] = mode
        return payload

    @app.get("/weights/binding")
    def weight_binding() -> dict:
        binding = app.state.last_binding
        if binding is None:
            path = REPORTS_DIR / "weight_binding.json"
            if not path.exists():
                return {"available": False}
            try:
                binding = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {"available": False}
            if not isinstance(binding, dict):
                return {"available": False}
        return {"available": True, **binding}

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

    def _learn_pairs_from_events(
        recorded: list[RecommendationEvent],
    ) -> None:
        """Apply one pairwise personalization update per completed choice.

        The current payload is merged with prior ``store.events`` for the
        affected recommendation requests, so an accept and reject posted in
        separate ``/events`` calls still form a pair. A learned-request set
        keeps later re-posts from updating the same request twice.
        """
        affected = {
            event.request_id
            for event in recorded
            if event.action in {"accept", "reject"}
        }
        if not affected:
            return
        current = require_store()
        learned = app.state.personalized_requests
        grouped: dict[str, list[RecommendationEvent]] = {}
        for request_id in affected:
            if request_id in learned:
                continue
            request_events = current.events_for(request_id)
            has_accept = any(
                event.action == "accept" for event in request_events
            )
            has_reject = any(
                event.action == "reject" for event in request_events
            )
            if has_accept and has_reject:
                grouped[request_id] = request_events
        if not grouped:
            return
        impressions_by_request = {
            impression.request_id: impression
            for impression in current.impressions
        }
        service = active_service()
        for request_id, request_events in grouped.items():
            positives = [
                event
                for event in request_events
                if event.action == "accept"
            ]
            negatives = [
                event
                for event in request_events
                if event.action == "reject"
            ]
            user_id = next(
                (
                    event.user_id
                    for event in positives + negatives
                    if event.user_id
                ),
                None,
            )
            if not user_id:
                continue
            chosen_target = _event_target(
                positives[0], impressions_by_request
            )
            rejected_target = _event_target(
                negatives[0], impressions_by_request
            )
            if chosen_target is None or rejected_target is None:
                continue
            try:
                chosen = service.features_for(*chosen_target)
                rejected = service.features_for(*rejected_target)
                app.state.personalizer.update_pair(
                    user_id, chosen, rejected
                )
            except KeyError:
                # Choice personalization is best-effort: event ingestion
                # must not fail when the user/entity no longer resolves.
                continue
            learned.add(request_id)

    @app.post("/events", response_model=EventsResponse)
    def record_events(request: EventsRequest) -> EventsResponse:
        weights_version = app.state.weight_store.active().version
        accepted = 0
        recorded: list[RecommendationEvent] = []
        for item in request.events:
            metadata = dict(item.metadata)
            # Pass explicit client labels through so ``EventService`` can
            # validate them against the impression; it derives the authoritative
            # values and drops every non-allowlisted metadata key.
            if "candidate_type" in item.model_fields_set:
                metadata["candidate_type"] = item.candidate_type
            if item.task_id is not None:
                metadata["task_id"] = item.task_id
            metadata["weights_version"] = weights_version
            try:
                event = app.state.events.record_event(
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
            recorded.append(event)
            accepted += 1
        _learn_pairs_from_events(recorded)
        return EventsResponse(accepted=accepted)

    @app.get("/events/metrics")
    def event_metrics() -> dict:
        return app.state.events.funnel_metrics()

    @app.post("/recommend/workers", response_model=RecommendResponse)
    def recommend_workers(request: RecommendWorkersRequest) -> RecommendResponse:
        current = require_store()
        service = active_service()
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
                metadata={
                    "candidate_type": "worker",
                    "role": "customer",
                    "user_id": request.user_id,
                },
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
        service = active_service()
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
                metadata={
                    "candidate_type": "task",
                    "role": "worker",
                    "user_id": request.worker_id,
                },
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
        service = active_service()
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
        service = active_service()
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
            service=active_service(),
        )

    return app
