# Task 18 Report: `/events` API, `request_id`, and Auto-Accept

## Status

DONE — implementation is complete and the full suite passes (232 passed). The
earlier NEEDS_CONTEXT blocker (a pre-existing rollback test that conflicted with
per-recommendation impression logging) was resolved by the coordinator's ruling,
and the first review round's findings were fixed in the second fix report at the
end of this file. `app/events.py` is now explicitly in the allowed edit set.

## What was implemented

### `app/schemas.py`
- `RecommendResponse.request_id: str = ""` (additive default; existing callers
  and response consumers keep working).
- `RecommendationContext.request_id: str = ""`.
- `EventItem` with `request_id`, `candidate_id`, `candidate_type` (default
  `"worker"`), `action` (`Literal["click", "apply", "accept", "reject", "ignore"]`),
  `task_id`, `user_id`, `role` (default `"customer"`), `metadata`.
- `EventsRequest(events: list[EventItem])`.
- `EventsResponse(accepted: int, rejected: list[dict])`.

### `app/main.py`
- Added `events_dir: Path | None = None` and `exploration_seed: int | None = None`
  to `create_app`.
- `create_app` stores:
  - `app.state.events = EventService(require_store(), persist_dir=events_dir or
    <repo>/data/events)`
  - `app.state.exploration = ExplorationPolicy(epsilon=0.10, seed=exploration_seed)`
- `/recommend/workers` and `/recommend/tasks` now call
  `app.state.exploration.rerank(...)` (no per-request `seed=42`), generate
  `request_id = uuid.uuid4().hex`, record an impression with all returned
  candidates/propensities and policy `"epsilon_greedy_topk"`, and return the
  `request_id`. Impression metadata carries `candidate_type="worker"` for
  `/recommend/workers` and `"task"` for `/recommend/tasks`.
- `POST /events`:
  - Invalid actions are rejected by Pydantic (`Literal`) with HTTP 422.
  - Each item calls `EventService.record_event` with
    `metadata={"candidate_type": item.candidate_type, "weights_version":
    <active version>}` (item-provided metadata is merged in first, these keys win).
  - `KeyError` (unknown request or candidate) → 404; `ValueError` (duplicate
    event) → 409; success returns `EventsResponse(accepted=n)`.
- `GET /events/metrics` returns `app.state.events.funnel_metrics()`.
- `POST /assignments` auto-records `accept` after a successful assignment when
  `recommendation_context.request_id` is non-empty, with
  `user_id=customer_id`, `role="customer"`; `KeyError` (unknown recommendation
  request/candidate) is ignored so the assignment still succeeds.

### `tests/conftest.py`
- `client` fixture now passes `events_dir=tmp_path / "events"` and
  `exploration_seed=42`, so tests do not write to the repository data directory
  and are deterministic.

### `tests/test_api_events.py`
- Created with the two tests from the brief verbatim.

## Tests run and output

Failing-first check (before implementation):

```
$ python -m pytest tests/test_api_events.py -v
ERROR ... TypeError: create_app() got an unexpected keyword argument 'events_dir'
2 errors in 1.07s
```

Focused tests after implementation:

```
$ python -m pytest tests/test_api_events.py -v
tests/test_api_events.py::test_recommend_returns_request_id_and_events_flow PASSED
tests/test_api_events.py::test_events_reject_duplicates_and_invalid_actions PASSED
============================== 2 passed in 0.35s ==============================
```

Full suite:

```
$ python -m pytest tests/ -q
FAILED tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores
1 failed, 227 passed in 20.35s
```

Failure detail: the test asserts that a recommendation made after rolling back
the active weights returns the same candidate ids/scores as the baseline
recommendation. Because Task 18 records an impression on every recommendation,
`Store.recent_impression_counts` changes, which feeds `exposure_fairness` into
`candidate_features`, so later recommendations of the same task get slightly
different scores (and, with system-entropy exploration, sometimes a different
last candidate). Reproduced in isolation: with `EventService.record_impression`
monkeypatched to a no-op, the test's baseline and restored scores are identical;
with normal impression recording they differ:

```
ids equal: True
scores baseline: [0.7293, 0.6667, 0.6604, 0.6604, 0.6604]
scores restored: [0.7293, 0.6667, 0.6604, 0.6604, 0.6604]   # impressions disabled

# normal recording, seed=42:
ids equal: False
scores baseline: [0.7293, 0.6667, 0.6604, 0.6604, 0.6604]
scores restored: [0.7285, 0.6658, 0.6599, 0.6599, 0.6595]
```

Ad-hoc verification (not committed as tests) confirmed:
- `request_id` is present on both recommendation routes.
- `/assignments` with a recommendation `request_id` increments `accepts`.
- `/assignments` with an unknown `request_id` still returns 200.
- Posting an event with `candidate_type="task"` stores
  `RecommendationEvent.candidate_type == "task"` and the active
  `weights_version`.

## Files changed

- `app/schemas.py`
- `app/main.py`
- `tests/conftest.py`
- `tests/test_api_events.py` (new)

No other files were modified.

## Self-review findings

- Response/schema changes are additive with defaults; existing request models
  and response consumers are untouched.
- `POST /events` imports `EventsRequest`/`EventsResponse` only; no unused
  `EventItem` import remains in `main.py`.
- `EventsResponse.rejected` is currently always empty because failures abort the
  whole request with 404/409 (as required by the brief's 409 duplicate test).
  The field exists for the specified interface but is unused.
- `EventItem.task_id` now flows into `record_event` metadata; `EventService`
  uses it when provided and otherwise falls back to `impression.query_id`
  (fixed in the follow-up round; see the fix report).
- `.metadata["weights_version"]` uses the active weight version at event time,
  not the version that produced the impression (impressions do not store it).
- `_node_candidates` (chain-node recommendation) now receives and uses
  `app.state.exploration`; no fixed-seed policy is constructed there (fixed in
  the follow-up round; see the fix report).
- Auto-accept catches only `KeyError`, as specified. A duplicate `accept` is
  effectively unreachable through `/assignments` (the same worker/task pair
  returns 409 before the event is recorded, and a different candidate has a
  different duplicate key).

## Concern / required ruling (resolved)

`tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores`
is incompatible with the mandated "record an impression on every recommendation"
behavior: the impression log feeds exposure fairness, so repeated recommendations
are not score-identical. This is not a flake caused by exploration seed choice;
it fails deterministically. The coordinator resolved this by expanding the
allowed edit set and ruling that the test should reset `store.impressions`
between calls under a seeded exploration policy. See the fix report below.

## Report path

`.superpowers/sdd/recommendation-improvement/task-18-report.md`

---

# Fix Report (post-ruling round)

## Status

DONE_WITH_CONCERNS (all tests green; one allowlist discrepancy noted below).

## Rulings addressed

1. **Rollback test exposure state** — `tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores`
   now creates its client with `events_dir=tmp_path / "events",
   exploration_seed=42`, and clears `small_store.impressions` after the baseline
   and learned recommendations (with a comment explaining the exposure-fairness
   reset). The original rollback assertions were not weakened; all three
   comparisons run under empty exposure state.
2. **Worker→tasks event `task_id`** — `EventService.record_event` now uses
   `metadata["task_id"]` when provided and falls back to
   `impression.query_id` otherwise. `POST /events` passes
   `metadata["task_id"] = item.task_id`. Added
   `test_task_event_uses_candidate_task_id` to `tests/test_api_events.py`, which
   records a task event for a `/recommend/tasks` candidate and asserts the
   stored `RecommendationEvent.candidate_type == "task"` and
   `RecommendationEvent.task_id == candidate task id`.
3. **Shared exploration for chain-node recommendations** — `_node_candidates`
   now takes `exploration: ExplorationPolicy` and calls
   `exploration.rerank(...)`; `recommend_node` passes
   `app.state.exploration`. No fixed-seed `ExplorationPolicy` remains in
   `main.py`.
4. **`EventsResponse.rejected`** — left as-is (unused), per ruling.

## Files changed in this round

- `app/events.py` (one line: task_id precedence)
- `app/main.py` (task_id metadata pass-through; `_node_candidates` shared policy)
- `tests/test_phase2_api.py` (rollback test exposure-state reset + seeded app)
- `tests/test_api_events.py` (new `test_task_event_uses_candidate_task_id`)

Previously changed in this task: `app/schemas.py`, `tests/conftest.py`.

**Allowlist discrepancy:** ruling 2 explicitly requires
`EventService.record_event` to prefer `metadata["task_id"]`, but
`app/events.py` was not included in the allowed edit set (neither in the
coordinator's list nor the updated brief's Files list). The one-line change was
made in `app/events.py` as the only clean way to implement the ruling; it is
called out here for the record.

## Tests run and output

```
$ python -m pytest tests/test_api_events.py tests/test_phase2_api.py -v
tests/test_api_events.py::test_recommend_returns_request_id_and_events_flow PASSED
tests/test_api_events.py::test_events_reject_duplicates_and_invalid_actions PASSED
tests/test_api_events.py::test_task_event_uses_candidate_task_id PASSED
tests/test_phase2_api.py::test_phase2_api_flow PASSED
tests/test_phase2_api.py::test_customer_onboarding PASSED
tests/test_phase2_api.py::test_recommend_accepts_user_id PASSED
tests/test_phase2_api.py::test_recommendations_include_propensity PASSED
tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores PASSED
tests/test_phase2_api.py::test_onboarding_reset_switches_preferences PASSED
tests/test_phase2_api.py::test_feedback_updates_personal_weights_and_snapshot PASSED
tests/test_phase2_api.py::test_metrics_compare_rejects_unknown_version PASSED
tests/test_phase2_api.py::test_metrics_compare_success_with_heldout PASSED
============================== 12 passed in 6.49s ==============================
```

```
$ python -m pytest tests/ -q
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 94%]
.............                                                            [100%]
229 passed in 18.93s
```

## Self-review notes

- `metadata["task_id"] = item.task_id` may store `None` in the event metadata;
  `record_event` falls back to `impression.query_id` via `or`, so behavior is
  unchanged when the client omits `task_id`.
- Chain-node recommendations now consume the shared policy stream. They still do
  not record impressions or return a `request_id`; the ruling only required the
  shared policy there.
- Full suite (including existing `tests/test_events.py` EventService tests) passes
  after the `record_event` change.


---

# Fix Report (review round 2)

## Status

DONE — all four review items addressed; focused tests 15 passed; full suite 232
passed.

## Fixes

1. **Duplicate `accept` no longer 500s `/assignments`.**
   `app/main.py` auto-accept now catches `(KeyError, ValueError)` around
   `record_event`, so a client-accepted event followed by an assignment with the
   same `request_id` returns 200 and the assignment is persisted. New test:
   `test_assignment_succeeds_after_duplicate_accept_event` posts an `accept`
   through `/events`, then assigns with the same `request_id`, asserts 200,
   asserts the stored event is `accept`, asserts its `weights_version` matches
   the active weight version, and asserts `metrics["accepts"] == 1`.
2. **Server-side event labeling fallback.**
   `EventService.record_event` (`app/events.py`) now resolves
   `candidate_type` as event metadata → impression metadata → `"worker"`, and
   `task_id` as event metadata → impression metadata → candidate id when
   `candidate_type == "task"` → `impression.query_id` otherwise.
   `POST /events` (`app/main.py`) only forwards top-level `candidate_type` /
   `task_id` into event metadata when the client explicitly set those fields
   (`item.model_fields_set`), preserving the server-side fallback.
   New test: `test_task_event_labels_fall_back_to_impression` omits both fields
   on a `/recommend/tasks` request and asserts the stored event has
   `candidate_type == "task"` and `task_id == candidate task id`.
3. **Empty impressions skipped.**
   Both recommendation routes now only call `record_impression` when the
   reranked candidate list is non-empty; `request_id` is still generated and
   returned. New test: `test_empty_recommendations_do_not_record_impressions`
   checks `t_empty` (workers) and `w_bad` (tasks), asserts empty candidate
   lists, non-empty `request_id`, and unchanged `funnel_metrics()["impressions"]`.
4. **Auto-accept provenance.**
   The auto-accept event now passes
   `metadata={"weights_version": app.state.weight_store.active().version}`,
   matching the `/events` path. Covered by
   `test_assignment_succeeds_after_duplicate_accept_event` asserting the stored
   event's `weights_version`.

Parked minors were left unchanged: non-atomic `/events` batches, in-memory
impression cap, test sites creating the repo `data/events` directory, and the
unused `EventsResponse.rejected` field.

## Files changed this round

- `app/events.py` (candidate_type/task_id fallback resolution)
- `app/main.py` (conditional metadata forwarding, empty-impression guard,
  auto-accept exception handling + weights_version metadata)
- `tests/test_api_events.py` (four covering tests)

## Tests run and output

```
$ python -m pytest tests/test_api_events.py tests/test_phase2_api.py -v
tests/test_api_events.py::test_recommend_returns_request_id_and_events_flow PASSED
tests/test_api_events.py::test_events_reject_duplicates_and_invalid_actions PASSED
tests/test_api_events.py::test_task_event_uses_candidate_task_id PASSED
tests/test_api_events.py::test_task_event_labels_fall_back_to_impression PASSED
tests/test_api_events.py::test_empty_recommendations_do_not_record_impressions PASSED
tests/test_api_events.py::test_assignment_succeeds_after_duplicate_accept_event PASSED
tests/test_phase2_api.py::test_phase2_api_flow PASSED
tests/test_phase2_api.py::test_customer_onboarding PASSED
tests/test_phase2_api.py::test_recommend_accepts_user_id PASSED
tests/test_phase2_api.py::test_recommendations_include_propensity PASSED
tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores PASSED
tests/test_phase2_api.py::test_onboarding_reset_switches_preferences PASSED
tests/test_phase2_api.py::test_feedback_updates_personal_weights_and_snapshot PASSED
tests/test_phase2_api.py::test_metrics_compare_rejects_unknown_version PASSED
tests/test_phase2_api.py::test_metrics_compare_success_with_heldout PASSED
============================== 15 passed in 6.88s ==============================
```

```
$ python -m pytest tests/ -q
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
................                                                         [100%]
232 passed in 19.40s
```

## Self-review notes

- `item.model_fields_set` (Pydantic v2) distinguishes client-supplied
  `candidate_type`/`task_id` from defaults, so an omitted task event label falls
  back to the impression rather than being forced to `"worker"`.
- Existing `tests/test_events.py` EventService tests still pass: when event and
  impression metadata contain neither field, the previous behavior
  (`query_id`, `"worker"`) is preserved.
- Chain-node recommendations still do not record impressions/request_ids; only
  the shared exploration policy was required there.
