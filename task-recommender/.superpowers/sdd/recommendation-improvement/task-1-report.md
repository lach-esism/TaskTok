# Task 1 Report — Domain Models, Store Extensions, and Dataset Split Helpers

**Status:** DONE

## What was implemented

### `app/domain.py`
- Added `Impression` dataclass with the exact spec §5.1 fields:
  `request_id`, `query_id`, `candidate_ids`, `propensities`, `policy`,
  `created_at` (default `_utcnow`), `metadata` (default empty dict; required for
  synthetic assignment correlation).
- Added `RecommendationEvent` dataclass with the exact spec §5.2 fields:
  `event_id`, `request_id`, `user_id`, `role`, `task_id`, `candidate_id`,
  `candidate_type`, `rank`, `score`, `propensity`, `weights_version`, `action`,
  `created_at` (default `_utcnow`), `metadata` (default empty dict).
- Extended `Worker` with defaulted fields appended after existing defaulted fields:
  `expected_pay: float = 0.0`, `certifications: dict[str, float] = {}`,
  `communication_ratings: list[float] = []`.
- Extended `Task` with `required_skill_weights: dict[str, float] = {}` appended
  after `created_at`.
- Extended `Dataset` with `events` and `impressions` defaulted lists (appended
  after `new_users`).
- Added `Dataset` split helpers:
  - `split_time` -> max `train` assignment `created_at`, falling back to
    `datetime.now(timezone.utc)` when `train` is empty.
  - `train_feedback` / `test_feedback` -> feedback whose `assignment_id` is in
    the train / test assignment ID sets (spec §7 leakage rule: filter by
    `train_assignment_ids`).
  - `train_events` / `test_events` -> partition by `created_at <= split_time`
    vs `> split_time`.
  - `train_impressions` / `test_impressions` -> same temporal partition.
- Added a small `_as_utc` helper so naive timestamps compare safely with aware
  timestamps.

### `app/data/store.py`
- `Store.__init__` accepts optional `events` and `impressions` (appended at the
  end of the signature, preserving all existing positional/keyword callers).
  They are stored as mutable lists (`self.events`, `self.impressions`).
- `reference_time` now takes the max timestamp across assignments, events, and
  impressions, falling back to wall-clock UTC only when all are empty.
- Added `events_for(request_id)` and `events_for_user(user_id)`, both returning
  events sorted by `created_at` (stable, so equal timestamps keep insertion
  order).
- Added `recent_impression_counts(now, days=30)`: counts candidate IDs from
  impressions with `now - days <= created_at <= now`, keyed by candidate ID.
- Added `prior_collaboration_count(customer_id, worker_id, before=None)`:
  counts assignments with `status == "completed"` for that customer/worker pair
  strictly before `before` (default `self.reference_time`).
- Timezone-naive timestamps are normalized via a local `_aware` helper.

## Tests run and output

1. Baseline before any change: `python -m pytest tests/ -q`
   -> `150 passed in 9.96s`.
2. Wrote `tests/test_events.py` exactly as the brief specifies, then
   `python -m pytest tests/test_events.py -v`
   -> collection error, expected:
   `ImportError: cannot import name 'Impression' from 'app.domain'`.
3. After implementation: `python -m pytest tests/test_events.py -v`
   -> `5 passed in 0.04s`
   (impression fields; worker/task defaults; reference_time/events_for;
   impression window; prior collaboration).
4. Full suite: `python -m pytest tests/ -q`
   -> `155 passed in 9.86s` (after cleanup, re-confirmed `155 passed in 9.96s`).
5. Ad-hoc sanity check of `Dataset` split properties (not committed to tests):
   train/test feedback, events, and impressions partition correctly; empty
   `train` returns an aware UTC `split_time`. Output: `DATASET_SPLIT_OK`.
6. `python -m compileall -q app/domain.py app/data/store.py tests/test_events.py`
   -> `COMPILE_OK`.

## Files changed

- `app/domain.py` (modified)
- `app/data/store.py` (modified)
- `tests/test_events.py` (created)
- `.superpowers/sdd/recommendation-improvement/task-1-report.md` (this report)

No files outside the task's listed files were modified. No git commands run;
the directory is not a git repository.

## Self-review findings

- Dataclass field ordering is safe: all new `Worker`, `Task`, and `Dataset`
  fields are defaulted and appended after existing defaulted fields; no
  `TypeError: non-default argument follows default argument`.
- `Store` signature compatibility preserved by appending the new parameters.
- `reference_time` preserves previous behavior when no events/impressions exist
  (assignment max), and now includes events/impressions as required.
- `prior_collaboration_count` uses strict `<` on `before`, matching "before"
  semantics; the test's later completed assignment at `NOW + 10d` is excluded
  and the cancelled assignment is ignored.
- `recent_impression_counts` only counts impressions inside the closed window;
  expired and future impressions are excluded.
- Split helpers are consistent: `train_*`/`test_*` partitions are disjoint and
  exhaustive for events and impressions (every record is on one side of
  `split_time`). For feedback, partition follows assignment IDs as the spec
  requires, so feedback is exhaustive when every feedback row references an
  assignment in `train ∪ test` (true for synthetic data).
- No new dependencies; seven feature keys untouched; no app code reads
  `data/ground_truth.csv` or benchmark labels.

## Concerns

- `Dataset.split_time` uses `max(a.created_at for a in train)` without
  normalizing first. If a dataset ever mixes naive and aware datetimes within
  `train`, `max()` would raise a `TypeError`. All current producers are aware;
  a normalization helper is used only for partitioning comparisons.
- Feedback split is by assignment ID (per spec §7), not by `Feedback.created_at`.
  If a future producer emits feedback for an assignment absent from both
  `train` and `test`, that feedback would belong to neither split. Synthetic
  data always partitions every assignment, so Task 3's disjoint/exhaustive
  assertions will hold.
- `events_for` / `events_for_user` sort by `created_at`; this is deterministic
  and stable for ties. Callers that need original insertion order under
  differing timestamps would see chronological order instead.
- There is a small duplication of the naive-to-UTC normalization helper
  (`_as_utc` in `domain.py`, `_aware` in `store.py`). Kept separate to avoid
  importing a private domain helper; harmless. (Review finding: deferred.)

---

## Review Fix Report (post-review)

**Status after fixes:** DONE_WITH_CONCERNS

### What changed

`app/domain.py`:
- Added `_split_by_assignment(records, train_ids, test_ids, split_time)`:
  - when a record has `metadata["assignment_id"]`, classification is by
    assignment-ID membership in `train` / `test` (works on boundary timestamp
    ties);
  - otherwise falls back to timestamp comparison (`created_at < split_time` ->
    train), with ties at `split_time` conservatively placed in test, so a test
    record can never leak into train;
  - unknown assignment IDs also fall back to timestamps.
- `Dataset.train_events` / `test_events` and `train_impressions` /
  `test_impressions` now use this helper via `_event_split()` and
  `_impression_split()`.
- `Dataset.split_time` now normalizes each train timestamp with `_as_utc`
  before `max()`, returning an aware datetime and tolerating naive inputs.
- Feedback split remains assignment-ID based (already correct per spec §7).

`tests/test_events.py`:
- Extended `test_store_reference_time_includes_events_and_impressions` to pass
  an impression and assert that a later impression can drive `reference_time`
  (impressions branch exercised).
- Added `_split_dataset()` fixture where one train and one test assignment
  share `NOW`, with impressions/events carrying
  `metadata={"assignment_id": ...}`.
- Added regression tests:
  - `test_dataset_split_prefers_assignment_metadata_on_timestamp_ties`;
  - `test_dataset_event_impression_and_feedback_splits_are_disjoint`;
  - `test_dataset_split_without_metadata_falls_back_to_timestamps`;
  - `test_dataset_split_time_is_timezone_aware_with_empty_train`;
  - `test_dataset_split_time_normalizes_naive_train_timestamps`.

### Evidence

Command: `python -m pytest tests/test_events.py -v`
Output: `10 passed in 0.07s` (all 10 tests listed PASSED).

Command: `python -m pytest tests/ -q`
Output: `160 passed in 10.06s`.

Default-size seed-43 reproduction (ad-hoc):
`generate_dataset(seed=43)` yields exactly 1 train and 1 test assignment sharing
`split_time`. With impressions/events carrying assignment metadata, the tied
train record appears only in `train_*` and the tied test record only in
`test_*`. Output: `SEED_43_TIE_PARTITION_OK`.

### Remaining concerns

- Records without assignment metadata at exactly `split_time` go to test
  (leak-safe, possibly conservative train-data loss). Task 4 should stamp
  synthetic events and impressions with `metadata["assignment_id"]` for exact
  partitioning; otherwise the conservative fallback prevents leakage but can
  reclassify tied train records.
- Feedback split still drops feedback whose assignment appears in neither
  `train` nor `test`; synthetic data partitions every assignment, so Task 3's
  exhaustive/disjoint assertions hold.
- Duplicated normalization helper (`_as_utc` / `_aware`) intentionally deferred
  per review.
