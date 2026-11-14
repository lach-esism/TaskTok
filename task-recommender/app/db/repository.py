"""SQLite persistence for the serving state.

The recommender works on the in-memory ``Store``; this module makes that
state durable:

* first start: the synthetic dataset is written into an empty database;
* later starts: ``load`` rebuilds ``Store`` plus the chain / plan /
  acceptance state from the database;
* while serving: ``sync`` runs after every write request and writes only
  what changed (append-only logs by length, mutable entities by a JSON
  snapshot diff).

The diff approach keeps the algorithm modules untouched: they keep mutating
plain dataclasses, and persistence catches up once per request.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.chains.plan_store import ChainPlanStore
from app.data.store import Store
from app.db.codec import dumps, loads
from app.domain import (
    AcceptanceRecord,
    AcceptanceSpec,
    Application,
    Assignment,
    ChainPlan,
    Customer,
    Feedback,
    Impression,
    LearningSnapshot,
    RecommendationEvent,
    Submission,
    Task,
    TaskChain,
    UserProfile,
    UserWeightProfile,
    Worker,
)
from app.preference.customer import CustomerPreferenceProfile
from app.preference.worker import WorkerPreferenceProfile

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "1"
# Chain draft materializations (draft_id -> record) are a small dict; kept in
# the meta table as one JSON value. The subtasks themselves live in ``tasks``.
MATERIALIZATIONS_KEY = "chain_materializations"


def _iso(value) -> str:
    text = dumps(value)
    return json.loads(text)


@dataclass
class LoadedState:
    store: Store
    test_assignments: list[Assignment]
    chains: dict[str, TaskChain]
    plan_versions: dict[str, list[ChainPlan]]
    plan_active: dict[str, int]
    specs: dict[str, AcceptanceSpec]
    submissions: dict[str, Submission]
    records: dict[str, list[AcceptanceRecord]]
    final_records: dict[str, AcceptanceRecord]
    materializations: dict[str, dict] = field(default_factory=dict)


# Mutable keyed collections: (table, key column, extra typed columns).
def _task_row(task: Task) -> dict:
    return {
        "customer_id": task.customer_id,
        "title": task.title,
        "category": task.category,
        "status": task.status,
        "budget_min": float(task.budget_min),
        "budget_max": float(task.budget_max),
        "deadline": _iso(task.deadline),
        "created_at": _iso(task.created_at),
        "source": "published" if task.task_id.startswith("pub_") else "seed",
    }


KEYED = {
    "customers": ("customer_id", Customer, lambda c: {"name": c.name, "region": c.region}),
    "workers": (
        "worker_id",
        Worker,
        lambda w: {"name": w.name, "level": w.level, "status": w.status, "region": w.region},
    ),
    "tasks": ("task_id", Task, _task_row),
    "applications": (
        "application_id",
        Application,
        lambda a: {
            "task_id": a.task_id,
            "worker_id": a.worker_id,
            "status": a.status,
            "created_at": _iso(a.created_at),
        },
    ),
    "user_profiles": ("user_id", UserProfile, lambda _: {}),
    "user_weight_profiles": ("user_id", UserWeightProfile, lambda _: {}),
    "worker_preferences": ("worker_id", WorkerPreferenceProfile, lambda _: {}),
    "customer_preferences": ("customer_id", CustomerPreferenceProfile, lambda _: {}),
    "acceptance_specs": ("task_id", AcceptanceSpec, lambda _: {}),
    "submissions": (
        "submission_id",
        Submission,
        lambda s: {
            "task_id": s.task_id,
            "worker_id": s.worker_id,
            "version": s.version,
            "status": s.status,
        },
    ),
}


class Database:
    """One SQLite file holding the whole serving state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None
        )
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.lock = threading.RLock()
        # Last written JSON per keyed row, and written lengths of logs.
        self._snapshots: dict[str, dict[str, str]] = {name: {} for name in KEYED}
        self._snapshots.update(
            {"assignments": {}, "chains": {}, "plans": {}, "records": {}}
        )
        self._lengths: dict[str, int] = {}
        self._chain_seq = 0
        self._materializations_doc: str | None = None

    # ------------------------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def is_empty(self) -> bool:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return row is None

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def stats(self) -> dict[str, int]:
        tables = [
            "customers", "workers", "tasks", "applications", "assignments",
            "feedback", "impressions", "events", "chains", "submissions",
            "acceptance_records",
        ]
        return {
            table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }

    # ------------------------------------------------------------------
    # Generic writers
    # ------------------------------------------------------------------
    def _upsert(self, table: str, key_col: str, key: str, doc: str, extra: dict) -> None:
        columns = [key_col, *extra.keys(), "doc"]
        values = [key, *extra.values(), doc]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{col}=excluded.{col}" for col in columns[1:])
        self.conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({key_col}) DO UPDATE SET {updates}",
            values,
        )

    def _sync_keyed(self, table: str, items: dict) -> int:
        key_col, _cls, extra_fn = KEYED[table]
        seen = self._snapshots[table]
        changed = 0
        for key, entity in list(items.items()):
            doc = dumps(entity)
            if seen.get(key) == doc:
                continue
            self._upsert(table, key_col, key, doc, extra_fn(entity))
            seen[key] = doc
            changed += 1
        for key in set(seen) - set(items):
            self.conn.execute(f"DELETE FROM {table} WHERE {key_col} = ?", (key,))
            del seen[key]
            changed += 1
        return changed

    def _append(self, name: str, items: list, insert) -> int:
        start = self._lengths.get(name, 0)
        if len(items) < start:
            raise RuntimeError(f"{name} shrank; append-only log was rewritten")
        for item in items[start:]:
            insert(item)
        self._lengths[name] = len(items)
        return len(items) - start

    # ------------------------------------------------------------------
    # Per-collection writers
    # ------------------------------------------------------------------
    def _insert_feedback(self, item: Feedback) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO feedback (feedback_id, assignment_id, worker_id, "
            "task_id, overall_rating, created_at, doc) VALUES (?,?,?,?,?,?,?)",
            (
                item.feedback_id, item.assignment_id, item.worker_id, item.task_id,
                item.overall_rating, _iso(item.created_at), dumps(item),
            ),
        )

    def _insert_impression(self, item: Impression) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO impressions (request_id, query_id, created_at, doc) "
            "VALUES (?,?,?,?)",
            (item.request_id, item.query_id, _iso(item.created_at), dumps(item)),
        )

    def _insert_event(self, item: RecommendationEvent) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO events (event_id, request_id, user_id, task_id, "
            "candidate_id, action, created_at, doc) VALUES (?,?,?,?,?,?,?,?)",
            (
                item.event_id, item.request_id, item.user_id, item.task_id,
                item.candidate_id, item.action, _iso(item.created_at), dumps(item),
            ),
        )

    def _insert_snapshot(self, item: LearningSnapshot) -> None:
        self.conn.execute(
            "INSERT INTO learning_snapshots (user_id, doc) VALUES (?, ?)",
            (item.user_id, dumps(item)),
        )

    def _sync_assignments(self, items: list[Assignment], split: str) -> int:
        seen = self._snapshots["assignments"]
        changed = 0
        for item in items:
            doc = dumps(item)
            if seen.get(item.assignment_id) == doc:
                continue
            self.conn.execute(
                "INSERT INTO assignments (assignment_id, task_id, worker_id, customer_id, "
                "status, split, created_at, doc) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(assignment_id) DO UPDATE SET status=excluded.status, "
                "doc=excluded.doc",
                (
                    item.assignment_id, item.task_id, item.worker_id, item.customer_id,
                    item.status, split, _iso(item.created_at), doc,
                ),
            )
            seen[item.assignment_id] = doc
            changed += 1
        return changed

    def _sync_chains(self, chains: dict[str, TaskChain]) -> int:
        seen = self._snapshots["chains"]
        changed = 0
        for chain_id, chain in list(chains.items()):
            doc = dumps(chain)
            if seen.get(chain_id) == doc:
                continue
            if chain_id not in seen:
                self._chain_seq += 1
            self.conn.execute(
                "INSERT INTO chains (chain_id, root_task_id, status, seq, doc) "
                "VALUES (?,?,?,?,?) ON CONFLICT(chain_id) DO UPDATE SET "
                "status=excluded.status, doc=excluded.doc",
                (chain_id, chain.root_task_id, chain.status, self._chain_seq, doc),
            )
            seen[chain_id] = doc
            changed += 1
        return changed

    def _sync_plans(self, plan_store: ChainPlanStore) -> int:
        seen = self._snapshots["plans"]
        changed = 0
        for chain_id, versions in plan_store._versions.items():
            for index, plan in enumerate(versions, start=1):
                key = f"{chain_id}#{index}"
                if key in seen:
                    continue
                self.conn.execute(
                    "INSERT OR REPLACE INTO chain_plans (chain_id, version, doc) VALUES (?,?,?)",
                    (chain_id, index, dumps(plan)),
                )
                seen[key] = "1"
                changed += 1
        for chain_id, version in plan_store._active.items():
            key = f"{chain_id}@active"
            if seen.get(key) == str(version):
                continue
            self.conn.execute(
                "INSERT INTO chain_plan_active (chain_id, version) VALUES (?, ?) "
                "ON CONFLICT(chain_id) DO UPDATE SET version=excluded.version",
                (chain_id, version),
            )
            seen[key] = str(version)
            changed += 1
        return changed

    def _sync_records(self, acceptance) -> int:
        seen = self._snapshots["records"]
        final_ids = {record.record_id for record in acceptance.final_records.values()}
        changed = 0
        for records in acceptance.records.values():
            for record in records:
                doc = dumps(record)
                marker = doc + ("#final" if record.record_id in final_ids else "")
                if seen.get(record.record_id) == marker:
                    continue
                self.conn.execute(
                    "INSERT INTO acceptance_records (record_id, task_id, submission_id, "
                    "layer, decision, is_final, doc) VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(record_id) DO UPDATE SET decision=excluded.decision, "
                    "is_final=excluded.is_final, doc=excluded.doc",
                    (
                        record.record_id, record.task_id, record.submission_id,
                        record.layer, record.decision,
                        int(record.record_id in final_ids), doc,
                    ),
                )
                seen[record.record_id] = marker
                changed += 1
        return changed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def sync(
        self,
        store: Store,
        *,
        chains: dict[str, TaskChain] | None = None,
        plan_store: ChainPlanStore | None = None,
        acceptance=None,
        test_assignments: list[Assignment] | None = None,
        materializations: dict[str, dict] | None = None,
    ) -> int:
        """Write every change since the previous sync in one transaction."""
        with self.lock:
            # Snapshots are advanced while writing; restore them on rollback
            # so the next sync retries the same rows.
            saved_snapshots = {name: dict(rows) for name, rows in self._snapshots.items()}
            saved_lengths = dict(self._lengths)
            saved_seq = self._chain_seq
            saved_materializations = self._materializations_doc
            self.conn.execute("BEGIN")
            try:
                changed = 0
                changed += self._sync_keyed("customers", store.customers)
                changed += self._sync_keyed("workers", store.workers)
                changed += self._sync_keyed("tasks", store.tasks)
                changed += self._sync_keyed("applications", store.applications)
                changed += self._sync_assignments(store.assignments, "train")
                if test_assignments:
                    changed += self._sync_assignments(test_assignments, "test")
                changed += self._append("feedback", store.feedback, self._insert_feedback)
                changed += self._append("impressions", store.impressions, self._insert_impression)
                changed += self._append("events", store.events, self._insert_event)
                changed += self._append(
                    "learning_snapshots", store.learning_snapshots, self._insert_snapshot
                )
                changed += self._sync_keyed("user_profiles", store.profiles)
                changed += self._sync_keyed("user_weight_profiles", store.user_weight_profiles)
                changed += self._sync_keyed("worker_preferences", store.worker_preferences)
                changed += self._sync_keyed("customer_preferences", store.customer_preferences)
                if chains is not None:
                    changed += self._sync_chains(chains)
                if plan_store is not None:
                    changed += self._sync_plans(plan_store)
                if materializations is not None:
                    doc = json.dumps(materializations, ensure_ascii=False, sort_keys=True)
                    if doc != self._materializations_doc:
                        self.conn.execute(
                            "INSERT INTO meta (key, value) VALUES (?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (MATERIALIZATIONS_KEY, doc),
                        )
                        self._materializations_doc = doc
                        changed += 1
                if acceptance is not None:
                    changed += self._sync_keyed("acceptance_specs", acceptance.specs)
                    changed += self._sync_keyed("submissions", acceptance.submissions)
                    changed += self._sync_records(acceptance)
                if self.is_empty():
                    self.conn.execute(
                        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                        (SCHEMA_VERSION,),
                    )
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                self._snapshots = saved_snapshots
                self._lengths = saved_lengths
                self._chain_seq = saved_seq
                self._materializations_doc = saved_materializations
                raise
            return changed

    def _rows(self, sql: str) -> list[str]:
        return [row[0] for row in self.conn.execute(sql)]

    def load(self) -> LoadedState:
        """Rebuild the serving state and prime the diff snapshots."""
        with self.lock:
            def keyed(table: str) -> dict:
                key_col, cls, _ = KEYED[table]
                result = {}
                for key, doc in self.conn.execute(f"SELECT {key_col}, doc FROM {table}"):
                    result[key] = loads(cls, doc)
                    self._snapshots[table][key] = doc
                return result

            def log(table: str, cls) -> list:
                items = [loads(cls, doc) for doc in self._rows(f"SELECT doc FROM {table} ORDER BY seq")]
                self._lengths[table] = len(items)
                return items

            train: list[Assignment] = []
            test: list[Assignment] = []
            for split, doc in self.conn.execute(
                "SELECT split, doc FROM assignments ORDER BY seq"
            ):
                item = loads(Assignment, doc)
                (test if split == "test" else train).append(item)
                self._snapshots["assignments"][item.assignment_id] = doc

            store = Store(
                workers=list(keyed("workers").values()),
                customers=list(keyed("customers").values()),
                tasks=list(keyed("tasks").values()),
                assignments=train,
                feedback=log("feedback", Feedback),
                profiles=keyed("user_profiles"),
                user_weight_profiles=keyed("user_weight_profiles"),
                learning_snapshots=log("learning_snapshots", LearningSnapshot),
                worker_preferences=keyed("worker_preferences"),
                customer_preferences=keyed("customer_preferences"),
                events=log("events", RecommendationEvent),
                impressions=log("impressions", Impression),
                applications=keyed("applications"),
            )

            chains: dict[str, TaskChain] = {}
            for chain_id, seq, doc in self.conn.execute(
                "SELECT chain_id, seq, doc FROM chains ORDER BY seq"
            ):
                chains[chain_id] = loads(TaskChain, doc)
                self._snapshots["chains"][chain_id] = doc
                self._chain_seq = max(self._chain_seq, seq)

            plan_versions: dict[str, list[ChainPlan]] = {}
            for chain_id, version, doc in self.conn.execute(
                "SELECT chain_id, version, doc FROM chain_plans ORDER BY chain_id, version"
            ):
                plan_versions.setdefault(chain_id, []).append(loads(ChainPlan, doc))
                self._snapshots["plans"][f"{chain_id}#{version}"] = "1"
            plan_active: dict[str, int] = {}
            for chain_id, version in self.conn.execute(
                "SELECT chain_id, version FROM chain_plan_active"
            ):
                plan_active[chain_id] = version
                self._snapshots["plans"][f"{chain_id}@active"] = str(version)

            specs = keyed("acceptance_specs")
            submissions = keyed("submissions")
            records: dict[str, list[AcceptanceRecord]] = {}
            final_records: dict[str, AcceptanceRecord] = {}
            for is_final, doc in self.conn.execute(
                "SELECT is_final, doc FROM acceptance_records ORDER BY seq"
            ):
                record = loads(AcceptanceRecord, doc)
                records.setdefault(record.task_id, []).append(record)
                if is_final:
                    final_records[record.submission_id] = record
                self._snapshots["records"][record.record_id] = doc + (
                    "#final" if is_final else ""
                )

            raw = self.get_meta(MATERIALIZATIONS_KEY)
            materializations = json.loads(raw) if raw else {}
            self._materializations_doc = raw

            return LoadedState(
                store=store,
                test_assignments=test,
                chains=chains,
                plan_versions=plan_versions,
                plan_active=plan_active,
                specs=specs,
                submissions=submissions,
                records=records,
                final_records=final_records,
                materializations=materializations,
            )
