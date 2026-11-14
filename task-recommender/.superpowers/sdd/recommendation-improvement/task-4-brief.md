## Task 4: Synthetic Impressions and Events

**Files:**
- Modify: `app/data/synthetic.py`
- Test: `tests/test_synthetic.py` (extend)

**Interfaces:**
- Consumes: `Impression`, `RecommendationEvent`, `Dataset` split helpers.
- Produces: `generate_dataset(...)` returns non-empty `impressions` and `events`; each assignment has one impression.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthetic.py`:

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

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_synthetic.py::test_synthetic_events_cover_assignments -v`
Expected: FAIL because `events` / `impressions` are empty.

- [ ] **Step 3: Implement synthetic events**

Inside the assignment loop, after the chosen `worker` is determined:
- Compute the logging weights for every candidate using the existing local `weight(worker)` function; normalize to propensities.
- Create an `Impression(request_id=f"r{len(impressions)+1:06d}", query_id=task.task_id, candidate_ids=[...], propensities={...}, policy="synthetic_weighted", created_at=assignment_time, metadata={"assignment_id": assignment.assignment_id})`.
- Create one `accept` event for the chosen worker; set `metadata={"assignment_id": assignment.assignment_id}` on it and on every negative event.
- Sample at most 20 unchosen candidates uniformly; for each, create an `ignore` event, except 10% become `reject` (use `rng.random() < 0.1`).
- Use `event_id=f"e{len(events)+1:06d}"`; `rank` is the candidate's position in `candidate_ids`; `score` is the logging weight; `propensity` from the impression; `weights_version="v0000"`.
- After building all assignments, sort events by `created_at`; the `Dataset.train_events` / `test_events` properties partition by `split_time`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_synthetic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. If existing synthetic tests assert exact counts of assignments/feedback, they should still pass; do not change those counts.

- [ ] **Step 6: Checkpoint**

No git commit.

---

