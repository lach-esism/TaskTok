# Task 19 Report: Wire Choice Learning into Weight Recompute and Personalization

## Status

DONE

## Files changed

- `app/main.py`
- `app/service.py`
- `tests/test_api_events.py`
- `tests/test_pairwise_learning.py`
- This report (`.superpowers/sdd/recommendation-improvement/task-19-report.md`)

`app/personalization/user_weights.py` was **not** modified: `update_pair`
already existed from Task 13, and this task wires it in from the API.

No git commands were run and no commits were created (the directory is not a
git repository).

## What was implemented

### `app/service.py` — `features_for`

`RecommendationService.features_for(task_id, worker_id) -> dict[str, float]`
builds the customer fallback (`Customer(..., "Unknown", ...)`), uses the
service's `ItemCF.score` for `cf_score`, passes stored worker/customer
preference profiles, fixes `semantic_similarity=0.5`, and calls
`candidate_features` with the service reference time. Unknown task or worker
IDs raise `KeyError`.

`candidate_features` does not accept a weight vector, so "the same effective
weights" is interpreted as using the service's scoring context (same ItemCF,
profiles, and reference time). Restricting to the instructed inputs keeps
choice-training features stable for the same `(task, worker)` pair.

### `app/main.py` — recompute, binding, personalization, auto-accept

- Added module config `CHOICE_LEARNING_MODE = os.environ.get(...,
  "pairwise").strip().lower()`, stored on `app.state.choice_learning_mode`.
  The recompute route normalizes any non-`listwise` value to `pairwise`.
- `POST /weights/recompute?include_events=true` (default `true`):
  - keeps the existing rating-based `OnlineWeightLearner.batch_fit`;
  - pairwise mode resolves features for every `click`/`apply`/`accept` and
    `reject`/`ignore` event via `features_for` (with a `(task_id, worker_id)`
    cache) and runs `PairwiseChoiceLearner(prior=active.weights).fit(pairs)`
    built with `build_pairs`;
  - listwise mode runs `ListwiseChoiceLearner` once per logged impression:
    every candidate in `impression.candidate_ids` is featurized, the earliest
    positive event is the one-hot target, and the sample weight is
    `clamp(1 / propensity, 0.1, 10.0)`;
  - merges the batch and choice vectors with a 50/50 average, then projects
    with `project_weights_with_report`;
  - creates a new `WeightStore` version (`source="batch+pairwise"` /
    `"batch+listwise"` when choice updates exist, otherwise `"batch"`) and
    returns the version payload plus `updates`, `binding`, and `mode`.
  - `updates` is the total learning sample count (rating records + choice
    pairs, or rating records + impressions in listwise mode).
  - Events that cannot be resolved to a live impression/task/worker are
    dropped instead of failing the recompute.
- `GET /weights/binding` returns `{"available": False}` before any recompute,
  otherwise `{"available": True, **WeightBindingReport}` from
  `app.state.last_binding` (written by the latest recompute).
- `POST /events`: after recording the batch, groups events by `request_id`;
  when the same payload contains an `accept` and a `reject` with a resolvable
  `user_id`, it computes `features_for` for both candidates and calls
  `app.state.personalizer.update_pair(user_id, chosen, rejected)`.
  `KeyError` is swallowed so event ingestion never fails because the
  personalizer or an entity is unavailable. Task-direction events resolve the
  worker from the impression's `query_id`.
- `/assignments` auto-accept now inspects the impression for
  `recommendation_context.request_id`: when its
  `metadata["candidate_type"] == "task"`, the accept is recorded with
  `candidate_id=request.task_id`; otherwise it keeps
  `candidate_id=request.worker_id`. This fixes silently dropped
  task-direction accepts.

### Tests added

`tests/test_api_events.py`:

- `test_recompute_with_events_changes_weights` — the brief's test verbatim.
- `test_assignment_from_task_recommendation_records_accept` — assigns from a
  `/recommend/tasks` request and asserts the accept event is stored with the
  chosen task id and `candidate_type == "task"`.
- `test_recompute_with_listwise_mode_changes_weights` — exercises the
  `CHOICE_LEARNING_MODE="listwise"` path.
- `test_weight_binding_endpoint_reports_last_recompute` — checks the
  unavailable fallback and the report written by recompute.

`tests/test_pairwise_learning.py`:

- `test_service_features_for_builds_choice_vectors` — seven keys, bounded
  values, and `KeyError` for unknown task/worker.

## Tests run and output

Failing-first check after appending the tests:

```
$ python -m pytest tests/test_api_events.py tests/test_pairwise_learning.py -v
FAILED test_recompute_with_events_changes_weights
FAILED test_assignment_from_task_recommendation_records_accept
FAILED test_recompute_with_listwise_mode_changes_weights
FAILED test_weight_binding_endpoint_reports_last_recompute
FAILED test_service_features_for_builds_choice_vectors
5 failed, 9 passed in 2.30s
```

The failures were the expected ones: missing `updates`, no `/weights/binding`
route, dropped task-direction accept (`IndexError` on the event log), and
missing `features_for`.

Focused tests after implementation:

```
$ python -m pytest tests/test_api_events.py tests/test_pairwise_learning.py -v
...
tests/test_api_events.py::test_recompute_with_events_changes_weights PASSED
tests/test_api_events.py::test_assignment_from_task_recommendation_records_accept PASSED
tests/test_api_events.py::test_recompute_with_listwise_mode_changes_weights PASSED
tests/test_api_events.py::test_weight_binding_endpoint_reports_last_recompute PASSED
tests/test_pairwise_learning.py::test_service_features_for_builds_choice_vectors PASSED
14 passed in 1.38s
```

The brief's focused command:

```
$ python -m pytest tests/test_api_events.py::test_recompute_with_events_changes_weights -v
tests/test_api_events.py::test_recompute_with_events_changes_weights PASSED
1 passed in 0.28s
```

Full suite:

```
$ python -m pytest tests/ -q
237 passed in 19.88s
```

The pre-task suite (Task 18) was 232 tests; the five added tests bring it to
237 with no regressions.

## Manual verification

- Small-store API run: `/weights/binding` starts as `{"available": False}`,
  accept+reject for a recommendation produces
  `source="batch+pairwise"`, `updates > 0`, a weight vector that differs from
  the prior, sum 1.0, and a populated binding report.
- Generated-data run (20 workers / 60 tasks / 200 assignments, seed 42):
  recompute used 652 updates, returned
  `mode="pairwise"`, a valid projected simplex, and
  `{"available": True, "reputation_hit_low": 0, ...}` from
  `/weights/binding`.
- Personalization with a real generated customer: posting accept+reject
  produced `UserWeightProfile.source == "online_pair"` and
  `sample_count == 1`. Posting with an unknown user id left event ingestion
  at HTTP 200 (personalization skipped).
- Source files compile (`python -m py_compile`) and no new source line
  exceeds 79 characters (the only long lines in `app/main.py`/`app/service.py`
  are pre-existing).

## Self-review findings

1. **Merge only when choice data exists.** If `include_events=true` yields no
   usable pairs/impressions, the response keeps the pure rating-based batch
   fit instead of averaging it with the unchanged prior. This preserves the
   old recompute behavior when no choice signal is present.
2. **Stale log rows never fail recompute.** `features_for` `KeyError`s are
   caught per event/candidate; unresolvable events are skipped and, in
   listwise mode, the whole impression is skipped so the softmax is never
   computed over a partial candidate set.
3. **Task-direction event resolution.** For task-candidate events the worker
   is recovered from the impression's `query_id`; for worker-candidate events
   the task comes from `event.task_id`. The `/assignments` auto-accept uses
   the same impression metadata rule.
4. **Mode is normalized.** Unknown `CHOICE_LEARNING_MODE` values fall back to
   `pairwise` rather than producing an unusable source label.
5. **No new dependencies; no ground-truth/label reads.** Recompute consumes
   `store.events`, `store.impressions`, and existing rating feedback only.
6. **Allowed-file scope respected.** Only `app/main.py`, `app/service.py`,
   the two named test files, and this report changed.
7. **Test count.** Five new tests cover the mandated recompute path, the
   task-direction auto-accept fix, listwise mode, binding, and
   `features_for`; existing tests are unchanged.

## Concerns

1. **Personalization pairing is per `/events` payload.** An accept in one
   HTTP call and a reject in a later call for the same `request_id` will not
   produce an `update_pair` (the payload has only one side). This follows the
   brief's "if the request has both a positive and negative event" wording.
   If cross-batch pairing is intended, the route should gather
   `store.events_for(request_id)` and dedupe already-learned requests.
2. **Choice features do not include the acceptance model or recent-impression
   fairness term.** `features_for` follows the brief's narrower list
   (`cf_score`, profiles, semantic 0.5), while `_build_features` also passes
   `p_accept` and `recent_impressions`. The choice vectors are therefore
   slightly different from online ranking vectors; chosen/rejected pairs from
   the same request remain consistently scored.
3. **Binding is in-memory.** The design doc mentions
   `reports/weight_binding.json`; this task only stores the latest report on
   `app.state` as instructed. If Task 20/21 needs history, persistence must
   be added.
4. **Recompute cost grows with event volume.** Pairwise mode calls
   `features_for` once per distinct `(task, worker)` choice event (cached),
   so a large event log makes `include_events=true` (now the default)
   noticeably heavier than the old recompute. The 200-assignment synthetic
   dataset completed comfortably.
5. **Extra tests beyond the brief.** The listwise, binding, and
   `features_for` tests were added to cover the new wiring; the mandated test
   is included verbatim and unmodified.

---

# Fix Report (review round 1)

## Status

DONE — all three Important review findings and the additional assertions are
addressed. Full suite: 238 passed.

## Fixes

### 1. Split-batch personalization (Important)

`app/main.py::_learn_pairs_from_events` now:

- takes the affected `request_id`s from accept/reject events in the current
  payload; returns immediately when the payload has no accept/reject (so no
  `RecommendationService` is constructed for click-only payloads);
- for each affected request, loads the full `store.events_for(request_id)`
  (current payload + prior events), and only proceeds when the combined set
  has both an `accept` and a `reject`;
- constructs `RecommendationService` only after at least one such completed
  group exists;
- records successfully learned requests in
  `app.state.personalized_requests`, skipping them on later re-posts;
- still guards `features_for`/`update_pair` with `except KeyError`, so event
  ingestion never fails when personalization is unavailable.

New test `tests/test_api_events.py::test_split_accept_reject_updates_personal_weights`
posts the accept and reject in two separate `/events` calls, asserts the
customer profile has `source == "online_pair"` and `sample_count == 1`, then
posts another accept for the same recommendation and asserts the sample count
stays at 1 (learned-request set).

### 2. `features_for` serving parity (Important)

`app/service.py` now extracts `_task_context(task)` (fallback customer,
eligible worker pool, normalized ItemCF, recent impressions, acceptance
counts, collaboration counts). Both `recommend_workers_for_task` and
`features_for` use it. `features_for` then calls the same `_build_features`
as serving, so it includes:

- normalized ItemCF (not raw);
- semantic matcher similarity (0.5 only when no matcher);
- `p_accept` when the acceptance model is fitted;
- recent impressions and exposure fairness;
- collaboration, communication, pay fit, worker/customer profiles;
- the same `self.reference_time`.

Unknown task/worker IDs still raise `KeyError`.

`tests/test_pairwise_learning.py::test_service_features_for_builds_choice_vectors`
now compares `features_for("t1", "w_good")` (rounded to 4 decimals) with the
serving `breakdown` for the same candidate from `recommend_workers("t1")`.

### 3. Binding report persistence (Important)

`POST /weights/recompute` writes `asdict(report)` to
`reports/weight_binding.json` (creating `reports/` if needed) after the final
`project_weights_with_report`. `GET /weights/binding` returns the in-memory
report when present; otherwise it reads `reports/weight_binding.json`, and
returns `{"available": False}` when neither exists or the file is unreadable.

`tests/test_api_events.py::test_weight_binding_endpoint_reports_last_recompute`
redirects `app.main.REPORTS_DIR` to `tmp_path` with `monkeypatch`, asserts the
initial unavailable response, recomputes with `include_events=false`, asserts
the file exists and equals the response's `binding` report, clears
`app.state.last_binding`, and asserts the GET fallback returns the same
report (`min_hits`, `iterations`).

### 4. Choice-branch liveness assertions

- `test_recompute_with_events_changes_weights` now also asserts
  `source == "batch+pairwise"` and `mode == "pairwise"`.
- `test_recompute_with_listwise_mode_changes_weights` now also asserts
  `source == "batch+listwise"` and `mode == "listwise"`.

### 5. Earlier concern resolved

The first report's concern about split accept/reject batches is now
implemented and covered; the remaining concerns (in-memory vs persisted
binding is resolved; choice features now match serving) are updated below.

## Files changed in this round

- `app/main.py` (split-batch pairing + learned-request set + service-construction
  filter; binding JSON persistence and GET fallback)
- `app/service.py` (`_task_context` shared by serving and `features_for`)
- `tests/test_api_events.py` (split-batch, binding persistence, source/mode
  assertions)
- `tests/test_pairwise_learning.py` (features_for serving-parity assertion)

No change to `app/personalization/user_weights.py` (its `update_pair` already
existed and is now exercised end-to-end). No conftest or other files changed.

## Covering tests, command, and output

Focused command:

```
$ python -m pytest tests/test_api_events.py tests/test_pairwise_learning.py -v
...
tests/test_api_events.py::test_recompute_with_events_changes_weights PASSED
tests/test_api_events.py::test_assignment_from_task_recommendation_records_accept PASSED
tests/test_api_events.py::test_recompute_with_listwise_mode_changes_weights PASSED
tests/test_api_events.py::test_split_accept_reject_updates_personal_weights PASSED
tests/test_api_events.py::test_weight_binding_endpoint_reports_last_recompute PASSED
tests/test_pairwise_learning.py::test_service_features_for_builds_choice_vectors PASSED
15 passed in 1.48s
```

Full suite:

```
$ python -m pytest tests/ -q
238 passed in 20.00s
```

The previous full-suite count was 237; the split-batch test brings it to 238
with no regressions.

## Self-review findings (fix round)

1. `features_for` now calls the identical `_build_features` path as
   `recommend_workers_for_task`; the parity test would fail if any serving
   kwarg (normalized CF, `p_accept`, recent impressions, collaboration,
   communication, pay fit, profiles) diverged.
2. Personalization only builds the `RecommendationService` when at least one
   combined request group has both accept and reject, satisfying the
   "filter first" instruction.
3. The learned-request set is updated only after a successful
   `update_pair`; a `KeyError` (unknown user/entity) leaves the request
   eligible for a later retry and still returns HTTP 200.
4. Binding writes are unconditional after projection. A test redirects the
   module-level `REPORTS_DIR` so the assertion is isolated; normal runs write
   the design-mandated `reports/weight_binding.json`.
5. Source/mode assertions make a dead choice-learner branch fail the tests.
6. No new source line exceeds 79 characters; `app/main.py` and
   `app/service.py` compile.

## Concerns (fix round)

1. `GET /weights/binding` reads the file only when `app.state.last_binding`
   is `None`; a stale file from a previous process is therefore reported as
   available on startup (by design, per the review instruction).
2. Binding writes happen on every recompute; a read-only `reports/`
   directory would make recompute fail at the write step. No fallback is
   applied because the review requires the file to exist.
3. `features_for` rebuilds the per-task serving context (eligible pool,
   counts) for each distinct `(task, worker)` pair; `app/main.py` caches whole
   feature vectors per pair, but large logs may still be slower than the old
   raw-CF version.
