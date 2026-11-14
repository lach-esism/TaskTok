# Task 4 Report: Synthetic Impressions and Events

## Status

DONE

## What Was Implemented

All changes are in `app/data/synthetic.py` (`generate_dataset`) and
`tests/test_synthetic.py` (appended test).

### Test (written first)

Appended the brief's test verbatim:

```python
def test_synthetic_events_cover_assignments():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    assert len(dataset.impressions) == len(dataset.assignments)
    for impression in dataset.impressions:
        assert impression.candidate_ids
        assert abs(sum(impression.propensities.values()) - 1.0) < 1e-6
    accepts = [event for event in dataset.events if event.action == "accept"]
    assert len(accepts) == len(dataset.assignments)
    train_ids = {event.event_id for event in dataset.train_events}
    test_ids = {event.event_id for event in dataset.test_events}
    assert train_ids.isdisjoint(test_ids)
    assert len(train_ids) + len(test_ids) == len(dataset.events)
```

Existing tests were not modified.

### Generator changes

Imports now include `Impression` and `RecommendationEvent` from `app.domain`.
The assignment loop gains `impressions: list[Impression]` and
`events: list[RecommendationEvent]` accumulators.

Inside the assignment loop, immediately after the `Assignment` is constructed
and appended (so `assignment.assignment_id` exists):

1. **Logging weights.** `logging_weights = {candidate.worker_id:
   weight(candidate) for candidate in candidates}` reuses the existing local
   `weight(worker)` closure (skill match, specialty, load, reliability, +0.01
   floor). `candidate_ids` preserves the `candidates` order.
2. **Normalized propensities.**
   `propensities[cid] = logging_weights[cid] / sum(logging_weights.values())`.
   The +0.01 floor guarantees a positive denominator.
3. **Impression.** One per assignment:
   `request_id=f"r{len(impressions)+1:06d}"`, `query_id=task.task_id`,
   `candidate_ids`, `propensities`, `policy="synthetic_weighted"`,
   `created_at=assignment_time`,
   `metadata={"assignment_id": assignment.assignment_id}`.
   (The impression and the assignment share the exact timestamp, which
   Task 6's `"exposed"` candidate mode relies on.)
4. **Accept event.** One `action="accept"` event for the chosen `worker`.
5. **Negative events.** `rng.sample(unchosen_ids, k=min(20, len(unchosen_ids)))`
   draws at most 20 unchosen candidates uniformly; each becomes `"ignore"`,
   except a `rng.random() < 0.1` draw makes it `"reject"`.
6. **Event fields.** `event_id=f"e{len(events)+1:06d}"`,
   `request_id` from the impression, `user_id=task.customer_id`,
   `role="customer"`, `task_id=task.task_id`, `candidate_type="worker"`,
   `rank=candidate_ids.index(candidate_id) + 1` (1-based position, matching
   `EventService.record_event`), `score=logging_weights[candidate_id]`,
   `propensity=propensities[candidate_id]`, `weights_version="v0000"`,
   `created_at=assignment_time`, and a fresh
   `metadata={"assignment_id": assignment.assignment_id}` dict on every event.
7. **Ordering / split.** After the loop, `events.sort(key=lambda event:
   event.created_at)` (stable, so the events of one impression stay together).
   Because every impression and event carries `metadata["assignment_id"]`,
   `Dataset.train_events` / `test_events` and `train_impressions` /
   `test_impressions` classify by assignment membership rather than timestamp
   ties, preserving the Task 1 partition semantics.
8. **Wiring.** `events=events, impressions=impressions` are passed to the
   returned `Dataset`.

No ground-truth CSV or benchmark `labels` are read. No new dependencies.
No files outside `app/data/synthetic.py` and `tests/test_synthetic.py` were
modified (plus this report). No git commands were run.

## Tests Run

1. Failing test first:
   `python -m pytest tests/test_synthetic.py::test_synthetic_events_cover_assignments -v`
   Result: `1 failed` —
   `AssertionError: assert 0 == 40` at
   `len(dataset.impressions) == len(dataset.assignments)`, i.e. impressions and
   events were empty as expected.

2. Focused suite after implementation:
   `python -m pytest tests/test_synthetic.py -v`
   Result: `11 passed in 2.63s` (10 pre-existing + the new test).

3. Full suite:
   `python -m pytest tests/ -q`
   Result: `170 passed in 13.53s`.

4. Manual invariant probe (`python -c`, no files created), seed=42,
   n_workers=10, n_tasks=20, n_assignments=40, n_new_users=0:
   - `assignments=40`, `impressions=40`, `events=105`.
   - Actions: `accept=40`, `ignore=60`, `reject=5`.
   - `train_events=87`, `test_events=18` (sum 105 = all events, disjoint).
   - `train_impressions=32`, `test_impressions=8` (sum 40 = all assignments).
   - Every event and impression has a non-empty `metadata["assignment_id"]`.
   - Every event's `candidate_id` is in its impression's `candidate_ids`.
   - `impression.created_at` equals the matching assignment's `created_at`.
   - Max propensity-sum error: `1.11e-16` (well inside 1e-6).
   - Two same-seed runs produced identical event sequences and actions
     (determinism preserved).

## Files Changed

- `app/data/synthetic.py`
- `tests/test_synthetic.py` (appended the brief's test only)
- `.superpowers/sdd/recommendation-improvement/task-4-report.md` (this report)

## Self-Review Findings

- **RNG stream shift.** The new `rng.sample` / `rng.random` draws occur inside
  the assignment loop, so for a fixed seed the generated assignments/feedback
  differ from the pre-Task-4 dataset. Determinism (same seed -> identical
  dataset) is preserved and all existing tests — including exact assignment
  count (3000), title diversity, candidate-pool size, and train-only worker
  aggregates — pass unchanged. Default-size generation still reaches
  `n_assignments=3000` within `max_attempts`.
- **Rank convention.** The brief says "rank is the candidate's position in
  `candidate_ids`". I used 1-based `index + 1` to match the established
  convention in `EventService.record_event` (`impression.candidate_ids.index(
  candidate_id) + 1`) and the planner's `enumerate(..., start=1)`. This is the
  only ambiguous point in the brief; 0-based would also satisfy the appended
  test but would be inconsistent with the rest of the codebase.
- **Required fields not dictated by the brief.** `user_id=task.customer_id`,
  `role="customer"`, and `candidate_type="worker"` follow the design spec's
  semantics (requester is the customer; candidates are workers).
- **Metadata isolation.** Each event receives `dict(event_metadata)`, so no two
  events share the same metadata dict instance; impressions build their own
  dict.
- **Impression ordering.** Impressions are appended in assignment-creation
  order and not re-sorted, as the brief only requires sorting `events`.
  `request_id` sequence therefore matches impression index. Split correctness
  comes from metadata, so ordering does not affect `train_impressions` /
  `test_impressions` membership.
- **Edge cases.** A single-candidate fallback pool yields propensity `1.0` and
  no negatives; `total_logging_weight` is always positive because `weight`
  adds 0.01. With `n_assignments=0` both lists are empty, and the existing
  `Dataset` helpers remain safe.
- **No leakage.** Events record only candidate IDs, ranks, logging weights,
  propensities, and actions — never `reliability`, latent weights, or labels.
- **Performance.** Default generation now emits roughly 60k events; the full
  suite runs in ~14s, so the added cost is acceptable.

## Concerns

- None blocking.
- Non-blocking note: the 1-based `rank` choice noted above is an interpretation
  of the brief. If a downstream consumer (e.g. a future funnel-by-rank report)
  expects 0-based positions, this one line
  (`rank=candidate_ids.index(candidate_id) + 1`) would need to change.
- Non-blocking: as with Task 3, seeding now produces a different concrete
  dataset than before (same-seed reproducibility intact). No test pins exact
  per-worker or per-assignment values.
