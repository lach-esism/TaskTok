"""Self-evolution lab for the hackathon demo: run -> feedback -> learn -> run.

One *run* dispatches a fixed batch of tasks: for every task the recommender
ranks a fixed candidate pool with the active weights and shows a top-5
shortlist. The client then picks the person they actually want, using a
standard the system cannot see (``CLIENT_STANDARD``). Those picks are the
only input to learning: every "picked over shown-but-not-picked" pair is fed
to the production ``OnlineWeightLearner.update_pair`` and the result is saved
as a new weight version. Running again with the new version shows what
changed; rolling back restores the previous version and its exact numbers.

Nothing here edits code, parameters or prompts between runs: the only thing
that changes is the weight version produced from feedback.

The lab uses its own seeded dataset and its own weight directory, so it is
reproducible and never touches the marketplace weights.
"""

from __future__ import annotations

import json
import shutil
import statistics
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import DEFAULT_WEIGHTS
from app.data.store import Store
from app.data.synthetic import generate_dataset
from app.db.bootstrap import localize_names
from app.features import fuse_scores
from app.learning.online import OnlineWeightLearner
from app.learning.weights import KEYS
from app.nlp.lexicon import CATEGORY_LABELS
from app.service import RecommendationService
from app.versioning import WeightStore

FEATURE_LABELS = {
    "reputation": "口碑",
    "skill": "技能",
    "expertise": "专长",
    "collaborative": "协同过滤",
    "preference": "接单偏好",
    "load": "档期余量",
    "customer_preference": "委托方偏好",
}

#: What the client really values. The recommender never reads this; it only
#: sees which candidate the client picked.
CLIENT_STANDARD = {
    "reputation": 0.35,
    "skill": 0.10,
    "expertise": 0.15,
    "collaborative": 0.0,
    "preference": 0.0,
    "load": 0.30,
    "customer_preference": 0.10,
}

SHORTLIST = 5
POOL_SIZE = 30
BATCH_SIZE = 10
BATCH_OFFSET = 60          # fixed demo batch inside the pool list
LEARNING_RATE = 0.3
EPOCHS = 10
DATASET = dict(n_workers=100, n_tasks=300, n_assignments=1500, seed=42, n_new_users=0)


class EvolutionError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utility(features: dict[str, float]) -> float:
    return sum(CLIENT_STANDARD[key] * features.get(key, 0.0) for key in KEYS)


class EvolutionLab:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self._pools: dict[str, dict[str, dict[str, float]]] | None = None
        self._open()

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _open(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.weights = WeightStore(self.directory / "weights", prior=DEFAULT_WEIGHTS)
        path = self.directory / "state.json"
        if path.exists():
            self.state = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.state = {"runs": [], "memory": []}

    def _save(self) -> None:
        path = self.directory / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def reset(self) -> dict:
        """Start the demo over from the prior weights (lab data only)."""
        with self.lock:
            shutil.rmtree(self.directory / "weights", ignore_errors=True)
            (self.directory / "state.json").unlink(missing_ok=True)
            self._open()
            return self.overview()

    # ------------------------------------------------------------------
    # fixed task pools
    # ------------------------------------------------------------------
    def _build(self) -> None:
        dataset = generate_dataset(**DATASET)
        store = Store(
            workers=dataset.workers,
            customers=dataset.customers,
            tasks=dataset.tasks,
            assignments=dataset.train,
            feedback=dataset.feedback,
        )
        localize_names(store)
        service = RecommendationService(store, weights=DEFAULT_WEIGHTS)
        pools: dict[str, dict[str, dict[str, float]]] = {}
        for task in sorted(store.tasks.values(), key=lambda t: t.task_id)[:120]:
            if task.status != "open":
                continue
            candidates = service.recommend_workers(task.task_id, top_n=POOL_SIZE)
            if len(candidates) >= 8:
                pools[task.task_id] = {
                    c.candidate_id: {key: round(c.breakdown.get(key, 0.0), 6) for key in KEYS}
                    for c in candidates
                }
        ids = list(pools)
        self.batch = ids[BATCH_OFFSET:BATCH_OFFSET + BATCH_SIZE]
        self.holdout = [task_id for task_id in ids if task_id not in self.batch]
        self.store = store
        self._pools = pools

    @property
    def pools(self) -> dict[str, dict[str, dict[str, float]]]:
        if self._pools is None:
            self._build()
        return self._pools

    def _rank(self, task_id: str, weights: dict[str, float]) -> list[str]:
        pool = self.pools[task_id]
        return sorted(pool, key=lambda w: (-fuse_scores(pool[w], weights), w))

    def _client_pick(self, task_id: str, shown: list[str]) -> str:
        pool = self.pools[task_id]
        return max(shown, key=lambda w: (_utility(pool[w]), w))

    def _gold(self, task_id: str) -> str:
        pool = self.pools[task_id]
        return max(pool, key=lambda w: (_utility(pool[w]), w))

    def _metrics(self, task_ids: list[str], weights: dict[str, float]) -> dict:
        hits, ranks, gaps = [], [], []
        for task_id in task_ids:
            pool = self.pools[task_id]
            ranked = self._rank(task_id, weights)
            gold = self._gold(task_id)
            hits.append(ranked[0] == gold)
            ranks.append(ranked.index(gold) + 1)
            gaps.append(_utility(pool[gold]) - _utility(pool[ranked[0]]))
        return {
            "hit_rate": round(sum(hits) / len(hits), 4),
            "hits": sum(hits),
            "total": len(hits),
            "avg_gold_rank": round(statistics.mean(ranks), 2),
            "in_shortlist": round(sum(r <= SHORTLIST for r in ranks) / len(ranks), 4),
            "satisfaction_gap": round(100 * statistics.mean(gaps), 2),
        }

    # ------------------------------------------------------------------
    # public actions
    # ------------------------------------------------------------------
    def run(self) -> dict:
        """Dispatch the fixed batch with the active weights (one 'run')."""
        with self.lock:
            self.pools  # build the fixed batch on first use
            started = time.perf_counter()
            active = self.weights.active()
            weights = active.weights
            tasks = []
            for task_id in self.batch:
                pool = self.pools[task_id]
                ranked = self._rank(task_id, weights)
                shown = ranked[:SHORTLIST]
                gold = self._gold(task_id)
                pick = self._client_pick(task_id, shown)
                task = self.store.tasks[task_id]
                tasks.append({
                    "taskId": task_id,
                    "title": task.title,
                    "category": CATEGORY_LABELS.get(task.category, task.category),
                    "budget": task.budget,
                    "top": ranked[0],
                    "gold": gold,
                    "goldRank": ranked.index(gold) + 1,
                    "clientPick": pick,
                    "hit": ranked[0] == gold,
                    "shown": [
                        {
                            "workerId": worker_id,
                            "name": self.store.workers[worker_id].name,
                            "score": round(fuse_scores(pool[worker_id], weights), 4),
                            "features": pool[worker_id],
                        }
                        for worker_id in shown
                    ],
                })
            record = {
                "runId": "run_" + uuid.uuid4().hex[:8],
                "number": len(self.state["runs"]) + 1,
                "version": active.version,
                "at": _now(),
                "batch": self._metrics(self.batch, weights),
                "holdout": self._metrics(self.holdout, weights),
                "elapsedMs": round(1000 * (time.perf_counter() - started), 1),
                "learned": False,
                "tasks": tasks,
            }
            self.state["runs"].append(record)
            self._save()
            return record

    def _find_run(self, run_id: str) -> dict:
        for record in self.state["runs"]:
            if record["runId"] == run_id:
                return record
        raise EvolutionError(404, "没有这次运行")

    def feedback(self, run_id: str, picks: dict[str, str] | None = None) -> dict:
        """Learn from the client's picks on one run and save a new version.

        ``picks`` lets a person override the client's choice for any task
        (task_id -> worker_id, must be one of the shown five).
        """
        with self.lock:
            self.pools
            record = self._find_run(run_id)
            if record["learned"]:
                raise EvolutionError(409, "这次运行的反馈已经学过了")
            active = self.weights.active()
            if record["version"] != active.version:
                raise EvolutionError(409, "权重版本已变化，请重新运行一次再给反馈")
            picks = picks or {}
            pairs = []
            memory = []
            for task in record["tasks"]:
                shown = [item["workerId"] for item in task["shown"]]
                chosen = picks.get(task["taskId"], task["clientPick"])
                if chosen not in shown:
                    raise EvolutionError(422, f"{task['taskId']} 只能从展示的 5 人里选")
                pool = self.pools[task["taskId"]]
                for other in shown:
                    if other != chosen:
                        pairs.append((pool[chosen], pool[other]))
                memory.append({
                    "taskId": task["taskId"],
                    "title": task["title"],
                    "chosen": chosen,
                    "chosenName": self.store.workers[chosen].name,
                    "systemTop": task["top"],
                    "systemTopName": self.store.workers[task["top"]].name,
                    "corrected": chosen != task["top"],
                    "source": "manual" if task["taskId"] in picks else "client",
                })
            learner = OnlineWeightLearner(
                active.weights, weights=active.weights, learning_rate=LEARNING_RATE
            )
            for _ in range(EPOCHS):
                for chosen_features, other_features in pairs:
                    learner.update_pair(chosen_features, other_features)
            version = self.weights.create(
                dict(learner.weights),
                sample_count=len(pairs),
                source=f"evolution:{run_id}",
                metrics={"from_version": active.version, "pairs": len(pairs)},
            )
            entry = {
                "id": "mem_" + uuid.uuid4().hex[:8],
                "runId": run_id,
                "fromVersion": active.version,
                "toVersion": version.version,
                "at": _now(),
                "pairs": len(pairs),
                "corrections": sum(item["corrected"] for item in memory),
                "items": memory,
                "rolledBack": False,
            }
            self.state["memory"].append(entry)
            record["learned"] = True
            self._save()
            return {"memory": entry, "diff": self._diff(active.version, version.version)}

    def rollback(self, to_version: str | None = None) -> dict:
        """Go back to the version before the active one (or ``to_version``)."""
        with self.lock:
            active = self.weights.active()
            if to_version is None:
                entry = next(
                    (
                        item for item in reversed(self.state["memory"])
                        if item["toVersion"] == active.version and not item["rolledBack"]
                    ),
                    None,
                )
                if entry is None:
                    raise EvolutionError(409, "当前已经是最初版本，没有可退回的学习")
                to_version = entry["fromVersion"]
            try:
                target = self.weights.rollback(to_version, reason="evolution demo rollback")
            except KeyError:
                raise EvolutionError(404, f"没有版本 {to_version}")
            for item in self.state["memory"]:
                if item["toVersion"] > target.version and not item["rolledBack"]:
                    item["rolledBack"] = True
            self._save()
            return {"from": active.version, "to": target.version, "diff": self._diff(active.version, target.version)}

    # ------------------------------------------------------------------
    # read models
    # ------------------------------------------------------------------
    def _diff(self, from_version: str, to_version: str) -> list[dict]:
        raw = self.weights.diff(from_version, to_version)
        return [
            {
                "key": key,
                "label": FEATURE_LABELS.get(key, key),
                "from": round(raw[key]["from"], 4),
                "to": round(raw[key]["to"], 4),
                "delta": round(raw[key]["delta"], 4),
            }
            for key in KEYS
            if key in raw
        ]

    def overview(self) -> dict:
        with self.lock:
            active = self.weights.active()
            versions = []
            for event in self.weights.changelog():
                if event.get("event_type") == "create":
                    versions.append({"version": event["version"], "source": event["source"], "at": event["updated_at"]})
            runs = [{key: value for key, value in run.items() if key != "tasks"} for run in self.state["runs"]]
            return {
                "activeVersion": active.version,
                "weights": [
                    {
                        "key": key,
                        "label": FEATURE_LABELS[key],
                        "value": round(active.weights[key], 4),
                        "initial": round(active.prior[key], 4),
                    }
                    for key in KEYS
                ],
                "versions": versions,
                "runs": runs,
                "lastRun": self.state["runs"][-1] if self.state["runs"] else None,
                "memory": self.state["memory"],
                "clientStandard": [
                    {"key": key, "label": FEATURE_LABELS[key], "value": value}
                    for key, value in CLIENT_STANDARD.items()
                    if value
                ],
                "setup": {
                    "batch": len(self.batch) if self._pools is not None else BATCH_SIZE,
                    "holdout": len(self.holdout) if self._pools is not None else None,
                    "shortlist": SHORTLIST,
                    "pool": POOL_SIZE,
                },
            }
