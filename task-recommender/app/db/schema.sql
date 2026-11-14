-- TaskTok business database (SQLite).
--
-- Every row keeps the full entity as a JSON document in ``doc`` (decoded
-- back into the domain dataclass on startup). The typed columns next to it
-- duplicate the fields that are filtered, joined or counted, so the data can
-- also be inspected with plain SQL.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- parties
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    region      TEXT NOT NULL,
    doc         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    level     INTEGER NOT NULL,
    status    TEXT NOT NULL,
    region    TEXT NOT NULL,
    doc       TEXT NOT NULL
);

-- ---------------------------------------------------------------- market
-- status: open -> assigned -> completed | closed
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    status      TEXT NOT NULL,
    budget_min  REAL NOT NULL,
    budget_max  REAL NOT NULL,
    deadline    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'seed',   -- seed | published
    doc         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_customer ON tasks(customer_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, category);

-- status: pending | accepted | rejected | withdrawn
CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL REFERENCES tasks(task_id),
    worker_id      TEXT NOT NULL REFERENCES workers(worker_id),
    status         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    doc            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_task ON applications(task_id);
CREATE INDEX IF NOT EXISTS idx_applications_worker ON applications(worker_id);

-- split: train = serving history, test = held-out for /metrics/compare
CREATE TABLE IF NOT EXISTS assignments (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id TEXT NOT NULL UNIQUE,
    task_id       TEXT NOT NULL REFERENCES tasks(task_id),
    worker_id     TEXT NOT NULL REFERENCES workers(worker_id),
    customer_id   TEXT NOT NULL,
    status        TEXT NOT NULL,
    split         TEXT NOT NULL DEFAULT 'train',
    created_at    TEXT NOT NULL,
    doc           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignments_worker ON assignments(worker_id);
CREATE INDEX IF NOT EXISTS idx_assignments_task ON assignments(task_id);

CREATE TABLE IF NOT EXISTS feedback (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id   TEXT NOT NULL UNIQUE,
    assignment_id TEXT NOT NULL UNIQUE REFERENCES assignments(assignment_id),
    worker_id     TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    overall_rating INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    doc           TEXT NOT NULL
);

-- ---------------------------------------------------------------- recommendation log
CREATE TABLE IF NOT EXISTS impressions (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    query_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    doc        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,
    request_id   TEXT NOT NULL,
    user_id      TEXT,
    task_id      TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    action       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    doc          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, action);

-- ---------------------------------------------------------------- learning state
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    doc     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_weight_profiles (
    user_id TEXT PRIMARY KEY,
    doc     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_snapshots (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    doc     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_preferences (
    worker_id TEXT PRIMARY KEY,
    doc       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_preferences (
    customer_id TEXT PRIMARY KEY,
    doc         TEXT NOT NULL
);

-- ---------------------------------------------------------------- task chains
-- ``doc`` holds the whole TaskChain, nodes and edges included.
CREATE TABLE IF NOT EXISTS chains (
    chain_id     TEXT PRIMARY KEY,
    root_task_id TEXT NOT NULL,
    status       TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    doc          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chains_task ON chains(root_task_id);

CREATE TABLE IF NOT EXISTS chain_plans (
    chain_id TEXT NOT NULL,
    version  INTEGER NOT NULL,
    doc      TEXT NOT NULL,
    PRIMARY KEY (chain_id, version)
);
CREATE TABLE IF NOT EXISTS chain_plan_active (
    chain_id TEXT PRIMARY KEY,
    version  INTEGER NOT NULL
);

-- ---------------------------------------------------------------- acceptance
CREATE TABLE IF NOT EXISTS acceptance_specs (
    task_id TEXT PRIMARY KEY,
    doc     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    task_id       TEXT NOT NULL,
    worker_id     TEXT NOT NULL,
    version       INTEGER NOT NULL,
    status        TEXT NOT NULL,
    doc           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_task ON submissions(task_id);
CREATE TABLE IF NOT EXISTS acceptance_records (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     TEXT NOT NULL UNIQUE,
    task_id       TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    layer         TEXT NOT NULL,
    decision      TEXT NOT NULL,
    is_final      INTEGER NOT NULL DEFAULT 0,
    doc           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_task ON acceptance_records(task_id);
