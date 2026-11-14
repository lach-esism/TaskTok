"""Marketplace business flow behind the TaskTok frontend.

One demo person plays both sides (the frontend's "一端两用"): worker
``DEMO_WORKER_ID`` claims and delivers; customer ``DEMO_CUSTOMER_ID`` (same
display name) publishes and reviews.

State lives in existing entities so the SQLite sync picks it up unchanged:

* ``Application``          claim (pending / accepted / rejected / withdrawn)
* ``Assignment``           created when the customer selects a worker
* ``Task.meta``            market_status (recruiting / working / reviewing /
                           done), latest submission, review, rework history
* ``AcceptanceService``    machine checks + customer review + decision
* ``apply_feedback``       reputation / preference learning on acceptance
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.acceptance.specs import build_generic_spec
from app.data.store import Store
from app.domain import Application, Customer, Task
from app.feedback import FeedbackService
from app.market import cards
from app.nlp.classifier import extract_fields, rule_scores
from app.nlp.lexicon import CATEGORY_LABELS
from app.resume import CATEGORY_SKILLS
from app.schemas import FeedbackRequest

DEMO_WORKER_ID = "w0033"
DEMO_CUSTOMER_ID = "c_demo"
DEMO_FILES = ["交付成果.pdf", "数据明细.xlsx", "过程说明.docx"]


class MarketError(Exception):
    """Business rule violation; ``status`` maps to the HTTP status code."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None, field: str) -> datetime:
    if not value:
        raise MarketError(f"缺少{field}", 422)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MarketError(f"{field}格式不正确", 422) from error
    return cards.aware(parsed)


class MarketService:
    def __init__(
        self,
        store_fn: Callable[[], Store],
        service_fn: Callable,
        acceptance,
        events,
        exploration,
        templates: dict,
        apply_feedback: Callable[[FeedbackRequest], dict],
        invalidate: Callable[[], None],
    ) -> None:
        self._store_fn = store_fn
        self._service_fn = service_fn
        self.acceptance = acceptance
        self.events = events
        self.exploration = exploration
        self.templates = templates
        self.apply_feedback = apply_feedback
        self.invalidate = invalidate

    @property
    def store(self) -> Store:
        return self._store_fn()

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def task(self, task_id: str) -> Task:
        task = self.store.tasks.get(task_id)
        if task is None:
            raise MarketError("任务不存在", 404)
        return task

    def worker(self, worker_id: str):
        worker = self.store.workers.get(worker_id)
        if worker is None:
            raise MarketError("执行者不存在", 404)
        return worker

    def _status(self, task: Task) -> str:
        return task.meta.get("market_status") or (
            "recruiting" if task.status == "open" else "working"
        )

    def _applications(self, task_id: str, *, active: bool = True) -> list[Application]:
        return [
            item
            for item in self.store.applications.values()
            if item.task_id == task_id
            and (not active or item.status != "withdrawn")
        ]

    def _application(self, task_id: str, worker_id: str) -> Application | None:
        return next(
            (
                item
                for item in self.store.applications.values()
                if item.task_id == task_id and item.worker_id == worker_id
            ),
            None,
        )

    def _assignment(self, task: Task):
        worker_id = task.meta.get("worker_id")
        return next(
            (
                item
                for item in reversed(self.store.assignments)
                if item.task_id == task.task_id and item.worker_id == worker_id
            ),
            None,
        )

    def _poster(self, task: Task) -> str:
        customer = self.store.customers.get(task.customer_id)
        return customer.name if customer else "发包方"

    def _checks(self, task: Task) -> list[str]:
        if task.meta.get("checks"):
            return list(task.meta["checks"])
        template = self.templates.get(task.category) or {}
        return [node["title"] for node in template.get("nodes", [])]

    def _category_rates(self) -> dict[str, int]:
        good: Counter = Counter()
        total: Counter = Counter()
        for item in self.store.feedback:
            task = self.store.tasks.get(item.task_id)
            if task is None:
                continue
            total[task.category] += 1
            good[task.category] += item.overall_rating >= 4
        return {key: round(100 * good[key] / total[key]) for key in total}

    def _interest_counts(self) -> Counter:
        """Historical clicks/applies per task plus live claims, for 已申请."""
        counts: Counter = Counter(
            event.task_id
            for event in self.store.events
            if event.action in {"click", "apply", "accept"}
        )
        for item in self.store.applications.values():
            if item.status != "withdrawn":
                counts[item.task_id] += 1
        return counts

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    def clock(self) -> datetime:
        """Display clock: wall time, never behind the data clock."""
        return max(_now(), cards.aware(self.store.reference_time))

    def card(
        self,
        task: Task,
        *,
        match: float = 0.0,
        why: list[str] | None = None,
        rates: dict[str, int] | None = None,
        interest: Counter | None = None,
    ) -> dict:
        rates = self._category_rates() if rates is None else rates
        interest = self._interest_counts() if interest is None else interest
        return cards.task_card(
            task,
            poster=self._poster(task),
            now=self.clock(),
            checks=self._checks(task),
            match=match,
            why=why,
            applicants=interest.get(task.task_id, 0),
            rate=rates.get(task.category, 0),
        )

    def live_task_ids(self) -> set[str]:
        now = self.clock()
        return {
            task.task_id
            for task in self.store.tasks.values()
            if task.status == "open"
            and task.customer_id != DEMO_CUSTOMER_ID
            and cards.aware(task.created_at) <= now < cards.aware(task.deadline)
        }

    def feed(self, worker_id: str = DEMO_WORKER_ID) -> dict:
        """Personalized feed of open marketplace tasks for one worker.

        Ranked by the live recommender, re-ranked by the exploration policy,
        and logged as an impression so claims can be attributed (``apply``).
        """
        worker = self.worker(worker_id)
        live = self.live_task_ids()
        service = self._service_fn()
        ranked = service.recommend_tasks(
            worker_id,
            top_n=max(len(live), 1),
            user_id=worker_id,
            candidate_ids=live,
            require_skills=False,
        )
        ranked = self.exploration.rerank(ranked, len(ranked))
        request_id = uuid.uuid4().hex
        if ranked:
            self.events.record_impression(
                request_id,
                worker_id,
                [item.candidate_id for item in ranked],
                {item.candidate_id: item.propensity for item in ranked},
                "epsilon_greedy_topk",
                metadata={
                    "candidate_type": "task",
                    "role": "worker",
                    "user_id": worker_id,
                    "source": "market_feed",
                },
            )
        rates = self._category_rates()
        interest = self._interest_counts()
        scored = {item.candidate_id for item in ranked}
        items = [
            self.card(
                self.store.tasks[item.candidate_id],
                match=item.score,
                why=cards.task_reasons(item.breakdown, worker),
                rates=rates,
                interest=interest,
            )
            for item in ranked
        ]
        # Tasks this worker cannot take right now (level/capacity) still exist
        # in the market; list them after the ranked ones without a match score.
        for task_id in sorted(live - scored):
            items.append(
                self.card(self.store.tasks[task_id], rates=rates, interest=interest)
            )
        return {"request_id": request_id, "items": items}

    def detail(self, task_id: str) -> dict:
        task = self.task(task_id)
        card = self.card(task)
        card.update(self._market_fields(task))
        return card

    def _market_fields(self, task: Task) -> dict:
        meta = task.meta
        return {
            "status": self._status(task),
            "claimDeadline": meta.get("claim_deadline"),
            "deliverDeadline": meta.get("deliver_deadline") or cards.iso(task.deadline),
            "workerId": meta.get("worker_id"),
            "selectedAt": meta.get("selected_at"),
            "submission": meta.get("submission"),
            "review": meta.get("review"),
            "reworks": list(meta.get("reworks") or []),
            "createdAt": cards.iso(task.created_at),
        }

    # ------------------------------------------------------------------
    # Customer side: publish / edit / select / review
    # ------------------------------------------------------------------
    def ensure_demo_customer(self) -> Customer:
        customer = self.store.customers.get(DEMO_CUSTOMER_ID)
        if customer is None:
            customer = Customer(DEMO_CUSTOMER_ID, "李洋", "CN")
            self.store.customers[DEMO_CUSTOMER_ID] = customer
        return customer

    def publish(self, payload: dict, customer_id: str = DEMO_CUSTOMER_ID) -> dict:
        if customer_id == DEMO_CUSTOMER_ID:
            self.ensure_demo_customer()
        elif customer_id not in self.store.customers:
            raise MarketError("发包方不存在", 404)
        title = str(payload.get("title") or "").strip()
        desc = str(payload.get("desc") or "").strip()
        if not title:
            raise MarketError("任务标题不能为空", 422)
        budget = _budget(payload.get("budget"))
        level = payload.get("level") or "L2"
        if level not in cards.LEVEL_DIFFICULTY:
            raise MarketError("任务等级不正确", 422)
        claim_deadline = _parse(payload.get("claimDeadline"), "认领截止时间")
        deliver_deadline = _parse(payload.get("deliverDeadline"), "交付截止时间")
        if deliver_deadline < claim_deadline:
            raise MarketError("交付截止不能早于认领截止", 422)
        task_id = str(payload.get("id") or "")
        if not _CLIENT_ID.fullmatch(task_id) or task_id in self.store.tasks:
            task_id = f"pub_{uuid.uuid4().hex[:12]}"
        outputs = _lines(payload.get("outputs"))
        accept = _lines(payload.get("accept"))
        verify = payload.get("verify") or "manual"

        text = f"{title}。{desc}"
        category = payload.get("category")
        if category not in CATEGORY_SKILLS:
            scores = rule_scores(text)
            best = max(scores, key=scores.get) if scores else None
            category = best if best and scores[best] > 0 else "marketing_campaign"
        # Required skills are hard eligibility filters, so keep them few and
        # at the entry level; the rest of the match comes from the ranker.
        skills = [s for s in extract_fields(text).get("skills") or [] if s][:2]
        if not skills:
            skills = sorted(CATEGORY_SKILLS[category])[:1]
        span = (deliver_deadline - claim_deadline).total_seconds() / 3600
        now = self.clock()

        task = Task(
            task_id=task_id,
            customer_id=customer_id,
            title=title,
            category=category,
            required_skills={skill: 1 for skill in skills},
            required_level=1,
            difficulty=cards.LEVEL_DIFFICULTY[level],
            priority=3,
            estimated_hours=round(max(4.0, min(24.0, span / 8)), 1),
            deadline=deliver_deadline,
            region="CN",
            remote_ok=True,
            description=desc,
            budget=budget,
            requirements=accept,
            budget_min=budget,
            budget_max=budget,
            created_at=now,
        )
        task.meta = {
            "verify": verify,
            "outputs": outputs,
            "accept": accept,
            "checks": accept or outputs,
            "level": level,
            "claim_deadline": cards.iso(claim_deadline),
            "deliver_deadline": cards.iso(deliver_deadline),
            "market_status": "recruiting",
            "reworks": [],
        }
        self.store.tasks[task.task_id] = task
        self.acceptance.specs[task.task_id] = build_generic_spec(task.task_id)
        self.invalidate()
        self._invite(task)
        return self.detail(task.task_id)

    def _invite(self, task: Task, limit: int = 3) -> None:
        """Seed the applicant list with recommended workers (source=invited)."""
        try:
            ranked = self._service_fn().recommend_workers_for_task(
                task, top_n=limit + 1
            )
        except (KeyError, ValueError):
            return
        now = self.clock()
        for item in ranked:
            worker = self.store.workers.get(item.candidate_id)
            if worker is None or worker.worker_id == DEMO_WORKER_ID:
                continue
            if len(self._applications(task.task_id)) >= limit:
                break
            app_id = uuid.uuid4().hex
            self.store.applications[app_id] = Application(
                application_id=app_id,
                task_id=task.task_id,
                worker_id=worker.worker_id,
                note=_invite_note(worker, task),
                source="invited",
                score=round(item.score, 4),
                created_at=now,
                updated_at=now,
            )

    def patch(self, task_id: str, payload: dict) -> dict:
        task = self.task(task_id)
        if self._status(task) != "recruiting":
            raise MarketError("任务已开始执行，不能再修改")
        if "title" in payload:
            title = str(payload["title"] or "").strip()
            if not title:
                raise MarketError("任务标题不能为空", 422)
            task.title = title
        if "desc" in payload:
            task.description = str(payload["desc"] or "").strip()
        if "budget" in payload:
            budget = _budget(payload["budget"])
            task.budget = task.budget_min = task.budget_max = budget
        if payload.get("deliverDeadline"):
            deadline = _parse(payload["deliverDeadline"], "交付截止时间")
            task.deadline = deadline
            task.meta["deliver_deadline"] = cards.iso(deadline)
        self.invalidate()
        return self.detail(task_id)

    def applicants(self, task_id: str) -> list[dict]:
        self.task(task_id)
        result = []
        for item in self._applications(task_id):
            if item.status == "rejected":
                continue
            worker = self.store.workers.get(item.worker_id)
            if worker is None:
                continue
            card = cards.worker_card(worker, item.note, item.score)
            card["status"] = item.status
            card["source"] = item.source
            result.append(card)
        return result

    def applicant(self, worker_id: str) -> dict:
        return cards.worker_card(self.worker(worker_id))

    def select(self, task_id: str, worker_id: str) -> dict:
        task = self.task(task_id)
        if self._status(task) != "recruiting":
            raise MarketError("任务已选定执行者")
        chosen = self._application(task_id, worker_id)
        if chosen is None or chosen.status != "pending":
            raise MarketError("该执行者没有有效的认领", 422)
        try:
            assignment = FeedbackService(self.store).record_assignment(
                task_id,
                worker_id,
                task.customer_id,
                {"score": chosen.score or 0.0},
            )
        except (KeyError, ValueError) as error:
            raise MarketError(f"无法创建派单：{error}") from error
        now = self.clock()
        assignment.status = "assigned"
        task.status = "assigned"
        task.meta.update(
            worker_id=worker_id,
            selected_at=cards.iso(now),
            market_status="working",
            assignment_id=assignment.assignment_id,
        )
        for item in self._applications(task_id):
            if item.application_id == chosen.application_id:
                item.status = "accepted"
                item.assignment_id = assignment.assignment_id
            elif item.status == "pending":
                item.status = "rejected"
            item.updated_at = now
        self.invalidate()
        return self.detail(task_id)

    def decline(self, task_id: str, worker_id: str) -> dict:
        """Customer turns one claim down without selecting anyone yet."""
        application = self._application(task_id, worker_id)
        if application is None or application.status != "pending":
            raise MarketError("该执行者没有有效的认领", 422)
        application.status = "rejected"
        application.updated_at = self.clock()
        return self._work_item(application)

    def simulate_delivery(self, task_id: str) -> dict:
        """Demo: the selected (synthetic) worker hands in a delivery."""
        task = self.task(task_id)
        worker_id = task.meta.get("worker_id")
        if self._status(task) != "working" or not worker_id:
            raise MarketError("任务不在执行中")
        return self.submit(
            task_id,
            worker_id,
            DEMO_FILES,
            "已按交付物清单完成，过程说明里写了数据口径和来源。",
        )

    def _pending_submission(self, task: Task) -> str:
        if self._status(task) != "reviewing":
            raise MarketError("没有待验收的成果")
        return task.meta["submission"]["submission_id"]

    def review_pass(
        self, task_id: str, passed: list[int], reviewer_id: str = DEMO_CUSTOMER_ID
    ) -> dict:
        task = self.task(task_id)
        submission_id = self._pending_submission(task)
        accept = task.meta.get("accept") or task.requirements
        if len(set(passed or [])) < len(accept):
            raise MarketError("还有验收标准没有勾选通过", 422)
        try:
            self.acceptance.review(
                submission_id, reviewer_id, {"quality": 1.0, "completeness": 1.0}
            )
            self.acceptance.decide(submission_id, reviewer_id, "accepted")
        except (KeyError, ValueError) as error:
            raise MarketError(f"验收失败：{error}") from error
        assignment = self._assignment(task)
        if assignment is not None:
            assignment.on_time = cards.aware(
                datetime.fromisoformat(task.meta["submission"]["at"])
            ) <= cards.aware(task.deadline)
            try:
                self.apply_feedback(
                    FeedbackRequest(
                        assignment_id=assignment.assignment_id,
                        overall_rating=5,
                        quality_rating=5,
                        timeliness_rating=5 if assignment.on_time else 3,
                        communication_rating=5,
                        comment="验收通过",
                    )
                )
            except Exception as error:  # HTTPException from the feedback route
                raise MarketError(f"结算失败：{getattr(error, 'detail', error)}") from error
        now = cards.iso(self.clock())
        task.status = "completed"
        task.meta.update(
            market_status="done",
            completed_at=now,
            review={"decision": "pass", "passed": sorted(set(passed)), "at": now},
        )
        self.invalidate()
        return self.detail(task_id)

    def rework(
        self, task_id: str, reason: str, reviewer_id: str = DEMO_CUSTOMER_ID
    ) -> dict:
        task = self.task(task_id)
        submission_id = self._pending_submission(task)
        reason = (reason or "").strip()
        if len(reason) < 6:
            raise MarketError("请写清需要修改的地方（至少 6 个字）", 422)
        try:
            self.acceptance.review(
                submission_id,
                reviewer_id,
                {"quality": 0.4, "completeness": 0.4},
                comments={"quality": reason},
            )
            self.acceptance.decide(submission_id, reviewer_id, "rework", reason)
        except (KeyError, ValueError) as error:
            raise MarketError(f"返工失败：{error}") from error
        assignment = self._assignment(task)
        if assignment is not None:
            assignment.rework_count += 1
        reworks = list(task.meta.get("reworks") or [])
        reworks.append(
            {
                "reason": reason,
                "at": cards.iso(self.clock()),
                "submission": task.meta.get("submission"),
            }
        )
        task.meta.update(market_status="working", submission=None, reworks=reworks)
        self.invalidate()
        return self.detail(task_id)

    # ------------------------------------------------------------------
    # Worker side: claim / withdraw / submit
    # ------------------------------------------------------------------
    def apply(
        self,
        task_id: str,
        worker_id: str = DEMO_WORKER_ID,
        note: str = "",
        request_id: str | None = None,
    ) -> dict:
        task = self.task(task_id)
        self.worker(worker_id)
        if task.customer_id == DEMO_CUSTOMER_ID and worker_id == DEMO_WORKER_ID:
            raise MarketError("不能认领自己发布的任务")
        if self._status(task) != "recruiting" or task.status != "open":
            raise MarketError("任务已不在招募阶段")
        existing = self._application(task_id, worker_id)
        now = self.clock()
        if existing is not None and existing.status != "withdrawn":
            raise MarketError("已经认领过这个任务")
        score = None
        if request_id:
            try:
                event = self.events.record_event(
                    request_id,
                    task_id,
                    "apply",
                    user_id=worker_id,
                    role="worker",
                    metadata={"candidate_type": "task", "task_id": task_id},
                )
                score = getattr(event, "score", None)
            except (KeyError, ValueError):
                pass  # stale or unknown feed request; the claim still counts
        if existing is not None:
            existing.status = "pending"
            existing.note = note
            existing.request_id = request_id
            existing.updated_at = now
            application = existing
        else:
            app_id = uuid.uuid4().hex
            application = Application(
                application_id=app_id,
                task_id=task_id,
                worker_id=worker_id,
                note=note,
                request_id=request_id,
                score=score,
                created_at=now,
                updated_at=now,
            )
            self.store.applications[app_id] = application
        return self._work_item(application)

    def withdraw(self, task_id: str, worker_id: str = DEMO_WORKER_ID) -> dict:
        application = self._application(task_id, worker_id)
        if application is None or application.status != "pending":
            raise MarketError("只有等待选定的认领可以取消")
        application.status = "withdrawn"
        application.updated_at = self.clock()
        return {"taskId": task_id, "status": "withdrawn"}

    def submit(
        self, task_id: str, worker_id: str, files: list[str], note: str = ""
    ) -> dict:
        task = self.task(task_id)
        if task.meta.get("worker_id") != worker_id or self._status(task) != "working":
            raise MarketError("当前任务不能提交")
        files = _lines(files)
        if not files:
            raise MarketError("至少上传一个交付文件", 422)
        now = self.clock()
        submission, _record = self.acceptance.submit(
            task_id,
            worker_id,
            {"files": files, "content": note or ""},
            submitted_at=now,
        )
        if submission.status == "machine_failed":
            raise MarketError("交付未通过机器检查", 422)
        task.meta.update(
            market_status="reviewing",
            submission={
                "files": files,
                "note": (note or "").strip(),
                "at": cards.iso(now),
                "submission_id": submission.submission_id,
            },
        )
        return self.detail(task_id)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def _work_item(self, application: Application) -> dict:
        """One workspace row, same shape as ``state.workItems`` in the frontend."""
        task = self.store.tasks.get(application.task_id)
        meta = task.meta if task else {}
        item = {
            "taskId": application.task_id,
            "status": "accepted",
            "addedAt": cards.iso(application.created_at),
        }
        if application.status == "rejected":
            item["status"] = "declined"
        elif application.status == "accepted" and task is not None:
            market = self._status(task)
            reworks = meta.get("reworks") or []
            if market == "reviewing":
                item["status"] = "submitted"
            elif market == "done":
                item["status"] = "completed"
                item["completedAt"] = meta.get("completed_at")
                item["score"] = 100
            elif reworks:
                item["status"] = "rework"
            else:
                item["status"] = "active"
            submission = meta.get("submission") or (
                reworks[-1]["submission"] if reworks else None
            )
            if submission:
                item["submission"] = {
                    k: submission[k] for k in ("files", "note", "at") if k in submission
                }
            if meta.get("review"):
                item["review"] = meta["review"]
            elif reworks and item["status"] == "rework":
                item["review"] = {
                    "decision": "rework",
                    "reason": reworks[-1]["reason"],
                    "at": reworks[-1]["at"],
                }
        return item

    def work_items(self, worker_id: str = DEMO_WORKER_ID, history: int = 3) -> dict:
        """Workspace rows plus the task cards they reference.

        Live claims come from Applications; the last ``history`` completed
        historical assignments are shown as finished work.
        """
        self.worker(worker_id)
        items = [
            self._work_item(application)
            for application in sorted(
                self.store.applications.values(), key=lambda a: a.created_at
            )
            if application.worker_id == worker_id and application.status != "withdrawn"
        ]
        seen = {item["taskId"] for item in items}
        ratings = {f.assignment_id: f for f in self.store.feedback}
        past = [
            a
            for a in self.store.assignments
            if a.worker_id == worker_id
            and a.status == "completed"
            and a.task_id not in seen
            and a.task_id in self.store.tasks
        ]
        latest = {a.task_id: a for a in sorted(past, key=lambda a: a.created_at)}
        for assignment in sorted(latest.values(), key=lambda a: a.created_at)[-history:]:
            feedback = ratings.get(assignment.assignment_id)
            done_at = feedback.created_at if feedback else assignment.created_at
            items.append(
                {
                    "taskId": assignment.task_id,
                    "status": "completed",
                    "addedAt": cards.iso(assignment.created_at),
                    "completedAt": cards.iso(done_at),
                    "score": feedback.overall_rating * 20 if feedback else None,
                    "review": {"decision": "pass", "at": cards.iso(done_at)},
                }
            )
        rates = self._category_rates()
        interest = self._interest_counts()
        tasks = [
            self.card(self.store.tasks[item["taskId"]], rates=rates, interest=interest)
            for item in items
        ]
        return {"items": items, "tasks": tasks}

    def published(self, customer_id: str = DEMO_CUSTOMER_ID) -> list[dict]:
        """Customer's tasks with applicants and the selected worker inlined,
        so the frontend can render the management page without extra calls."""
        rates = self._category_rates()
        interest = self._interest_counts()
        result = []
        tasks = [t for t in self.store.tasks.values() if t.customer_id == customer_id]
        for task in sorted(tasks, key=lambda t: t.created_at, reverse=True):
            card = self.card(task, rates=rates, interest=interest)
            card.update(self._market_fields(task))
            card["applicantList"] = self.applicants(task.task_id)
            worker = self.store.workers.get(task.meta.get("worker_id") or "")
            card["worker"] = cards.worker_card(worker) if worker else None
            result.append(card)
        return result

    def seed_demo(self, worker_id: str = DEMO_WORKER_ID) -> bool:
        """First start only: give the demo worker live work in every state.

        Uses the real flow (claim → customer selects → submit → rework) on the
        worker's top recommended live tasks, so the workspace is not empty.
        Returns False when the worker is missing or already has claims.
        """
        if worker_id not in self.store.workers:
            return False
        if any(a.worker_id == worker_id for a in self.store.applications.values()):
            return False
        self.ensure_demo_customer()
        feed = self.feed(worker_id)
        ids = [card["id"] for card in feed["items"] if card["match"] > 0]
        plan = ["active", "rework", "submitted", "accepted", "accepted"]
        for task_id, target in zip(ids, plan):
            task = self.store.tasks[task_id]
            self.apply(task_id, worker_id, "可以马上开始。", feed["request_id"])
            if target == "accepted":
                continue
            self.select(task_id, worker_id)
            if target in {"rework", "submitted"}:
                self.submit(
                    task_id,
                    worker_id,
                    ["初稿.pdf", "数据明细.xlsx"],
                    "初稿已完成，数据来源写在附录。",
                )
            if target == "rework":
                self.rework(
                    task_id,
                    "第二部分的数据口径和任务说明不一致，请按原始数据重算并注明来源。",
                    reviewer_id=task.customer_id,
                )
        return True

    def me(self, worker_id: str = DEMO_WORKER_ID, weeks: int = 13) -> dict:
        """Profile numbers for 我的 / 能力图谱 / 收入明细."""
        worker = self.worker(worker_id)
        now = self.clock()
        on_time = round(100 * worker.on_time / worker.completed) if worker.completed else 0
        mine = [a for a in self.store.assignments if a.worker_id == worker_id]
        per_customer = Counter(a.customer_id for a in mine)
        repeat = (
            round(100 * sum(1 for n in per_customer.values() if n >= 2) / len(per_customer))
            if per_customer
            else 0
        )

        by_assignment = {a.assignment_id: a for a in mine}
        # Weekly buckets: per-day income is too sparse to read as a chart.
        start = (now - timedelta(weeks=weeks) + timedelta(days=1)).date()
        series = [0.0] * weeks
        month = 0.0
        for feedback in self.store.feedback:
            assignment = by_assignment.get(feedback.assignment_id)
            task = self.store.tasks.get(feedback.task_id)
            if assignment is None or task is None:
                continue
            day = cards.aware(feedback.created_at).date()
            net = task.budget * (1 - PLATFORM_FEE_RATE)
            if day.year == now.year and day.month == now.month:
                month += net
            index = (day - start).days // 7
            if 0 <= index < weeks:
                series[index] += net

        capability = sorted(
            (
                {
                    "category": category,
                    "label": CATEGORY_LABELS.get(category, category),
                    "score": round(20 * sum(values) / len(values)),
                    "count": len(values),
                }
                for category, values in worker.category_ratings.items()
                if values
            ),
            key=lambda row: (-row["count"], -row["score"]),
        )[:5]
        level = f"L{min(max(worker.level, 1), 4)}"
        customer = self.ensure_demo_customer()
        return {
            "workerId": worker_id,
            "name": customer.name,
            "avatar": customer.name[:1],
            "level": level,
            "levelText": cards.LEVEL_TEXT[level],
            "headline": " / ".join(row["label"] for row in capability[:3]),
            "completed": worker.completed,
            "onTime": on_time,
            "repeat": repeat,
            "monthIncome": round(month),
            "incomeSeries": [round(v) for v in series],
            "incomeFrom": start.isoformat(),
            "incomeTo": now.date().isoformat(),
            "capability": capability,
        }


PLATFORM_FEE_RATE = 0.05
# The frontend may pick the id so its optimistic copy and route stay valid.
_CLIENT_ID = re.compile(r"pub_[a-z0-9]{6,32}")


def _budget(value) -> float:
    try:
        budget = float(value)
    except (TypeError, ValueError) as error:
        raise MarketError("预算格式不正确", 422) from error
    if budget <= 0:
        raise MarketError("预算必须大于 0", 422)
    return budget


def _lines(values) -> list[str]:
    return [str(v).strip() for v in values or [] if str(v).strip()]


def _invite_note(worker, task: Task) -> str:
    label = CATEGORY_LABELS.get(task.category, "同类")
    done = len(worker.category_ratings.get(task.category) or [])
    on_time = round(100 * worker.on_time / worker.completed) if worker.completed else 0
    if done:
        return f"做过 {done} 个{label}任务，按时率 {on_time}%，可以马上开始。"
    return f"已完成 {worker.completed} 个任务，按时率 {on_time}%，想试试{label}方向。"
