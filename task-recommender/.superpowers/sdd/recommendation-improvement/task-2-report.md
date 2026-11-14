# Task 2 Report: EventService and Funnel Metrics

## Status

DONE

## What Was Implemented

Created `app/events.py` with:

- `ACTIONS = {"click", "apply", "accept", "reject", "ignore"}`
- `EventService(store: Store, persist_dir: Path | None = None)`
  - Creates `persist_dir` when provided.
  - `record_impression(...)`: builds an `Impression`, appends it to
    `store.impressions`, and appends one JSON line to
    `persist_dir/impressions.jsonl` when persistence is enabled.
  - `record_event(...)`: validates `action` against `ACTIONS` (`ValueError`),
    looks up the impression by `request_id` (`KeyError` if unknown), validates
    `candidate_id` is among the impression candidates (`KeyError`), rejects
    duplicate `(request_id, candidate_id, action)` tuples (`ValueError`), then
    appends a `RecommendationEvent` with:
    - `task_id = impression.query_id`
    - `rank = impression.candidate_ids.index(candidate_id) + 1`
    - `score = metadata.get("score", 0.0)`
    - `propensity = impression.propensities[candidate_id]`
    - `weights_version = metadata.get("weights_version", "v0000")`
    - `candidate_type = metadata.get("candidate_type", "worker")`
    - `event_id = uuid.uuid4().hex`
    - `created_at = store.reference_time`
    and appends one JSON line to `persist_dir/events.jsonl`.
  - `funnel_metrics()`: returns `impressions`, `candidates`, `clicks`,
    `applies`, `accepts`, `rejects`, `ignores` plus the five rates using the
    exact denominators from the brief (`max(1, ...)` guards).
- JSONL writing follows the existing `FeedbackService._persist` pattern
  (`json.dumps(..., ensure_ascii=False, default=str)`).

Appended the two brief-specified tests verbatim to `tests/test_events.py`
(imports included as given). Existing 10 tests untouched.

No app code reads `data/ground_truth.csv` or benchmark labels. No new
dependencies. Only `app/events.py` and `tests/test_events.py` were modified.

## Tests Run

1. After appending tests, before implementation:
   `python -m pytest tests/test_events.py -v`
   Result: collection error, `ModuleNotFoundError: No module named
   'app.events'` at `tests/test_events.py:287` (expected failure).

2. After implementation:
   `python -m pytest tests/test_events.py -v`
   Result: `12 passed in 0.07s` (10 existing + 2 new).

3. Full suite:
   `python -m pytest tests/ -q`
   Result: `162 passed in 10.03s`.

4. Manual sanity check of JSONL contents and non-click funnel behavior
   (ignore action, metadata score/weights_version overrides, `rank=2`,
   `task_id="t1"`, `candidate_type="worker"`, `ignore_rate=0.5`); both JSONL
   lines parsed cleanly.

## Files Changed

- `app/events.py` (new)
- `tests/test_events.py` (appended imports + 2 tests)

## Self-Review Findings

- Interfaces match the brief exactly (signatures, `ACTIONS`, JSONL filenames,
  rate formulas, default `score=0.0` / `weights_version="v0000"`).
- Duplicate detection scans `store.events`, so it also catches duplicates from
  another `EventService` instance sharing the same store.
- Unknown `action` raises `ValueError` before ID lookups; a call with both an
  invalid action and an unknown request_id yields `ValueError` rather than
  `KeyError`. The brief does not define precedence for that double-fault case;
  the tested cases each fail with their expected exception type.
- Multiple impressions with the same `request_id` are tolerated and the most
  recently appended one is used for event lookup (the brief does not forbid
  duplicates; no extra validation was added).
- If a `candidate_id` is listed in an impression but missing from
  `propensities`, the natural `KeyError` from the dict lookup surfaces
  (consistent with keying event propensity off the impression).
- Timestamps use `store.reference_time`, matching `FeedbackService`. On an
  empty store this falls back to wall clock; within one service call sequence
  the impression and its events share the reference timestamp.
- Extra metadata keys (`score`, `weights_version`, `candidate_type`) are
  retained in the persisted/stored metadata, which is harmless and keeps the
  record self-describing.
- Event counts in `funnel_metrics` ignore any store events with actions outside
  `ACTIONS` (defensive; such events cannot be created through this service).

## Concerns

None blocking. Minor notes: the double-fault validation precedence and
duplicate-impression tolerance are unspecified by the brief and were resolved
as described above.

---

# Fix Report (Review Follow-up)

## Changes

1. **JSONL rotation (spec gap).** `EventService.__init__` now accepts
   `max_events: int = 1_000_000`. `_persist` counts the active file's lines
   and, once it has reached `max_events`, renames it to the first unused
   `<name>.<n>.jsonl` (`events.1.jsonl`, `events.2.jsonl`, …) before appending
   to a fresh active file. Rotation applies to both `impressions.jsonl` and
   `events.jsonl` through the shared helper. `max_events <= 0` disables
   rotation defensively (brief does not define non-positive values).
2. **`weights_version` string coercion.** Stored as
   `str(metadata.get("weights_version", "v0000"))`, so a non-string metadata
   value cannot violate the dataclass annotation or write a non-string JSONL
   field.
3. **Coverage tests added** to `tests/test_events.py` (plus `import json` in
   the appended import block):
   - `test_event_service_rotates_jsonl`: `max_events=2`; records three
     impressions and three events; asserts `events.1.jsonl` and
     `impressions.1.jsonl` exist and each active file holds the 1-line
     remainder.
   - `test_event_service_funnel_rates_and_jsonl_fields`: 3-candidate
     impression with click/apply/accept on w1, reject on w2, ignore on w3;
     asserts `click_rate=1/3`, `apply_rate=1.0`, `accept_rate=1.0`,
     `reject_rate=1/3`, `ignore_rate=1/3`; parses the persisted reject JSONL
     line and asserts `candidate_id="w2"`, `rank=2`, `propensity=0.2`,
     `weights_version="7"` (metadata value `7`, verifying coercion).

Out-of-scope rulings honored: no duplicate `action="impression"` events were
added (impression counts stay derived from `store.impressions`), no
`candidate_type` changes for `/recommend/tasks`, and `_persist` atomicity, O(n)
scans, duplicate `request_id` tolerance, and the unknown-action bucket were
left unchanged.

## Tests Run

1. `python -m pytest tests/test_events.py -v`
   Result: `14 passed in 0.22s` (10 original + 2 prior Task 2 tests + 2 new).
2. `python -m pytest tests/ -q`
   Result: `164 passed in 10.05s`.

## Files Changed

- `app/events.py`
- `tests/test_events.py`

## Concerns

- Rotation counts the active file's lines before each append (O(n) per write);
  this is inherent to exact line-count rotation and falls under the parked
  Minor note rather than being optimized now.
- Archive naming uses the first unused suffix without shifting older archives.
- `max_events <= 0` disables rotation; the brief is silent on non-positive
  values.
