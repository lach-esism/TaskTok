## Task 19: Wire Choice Learning into Weight Recompute and Personalization

**Files:**
- Modify: `app/main.py`
- Modify: `app/service.py` (add `features_for`)
- Modify: `app/personalization/user_weights.py` (use `update_pair` from events if not already wired)
- Test: `tests/test_api_events.py`, `tests/test_pairwise_learning.py` (extend)

**Interfaces:**
- Produces:
  - `RecommendationService.features_for(task_id: str, worker_id: str) -> dict[str, float]`.
  - `POST /weights/recompute?include_events=true` uses `PairwiseChoiceLearner` on train events; response includes `weights`, `version`, `updates`, and `binding`.
  - `GET /weights/binding` returns the latest `WeightBindingReport` as JSON.
  - `POST /events` for `accept`/`reject` calls `personalizer.update_pair` for the request's user when both chosen and rejected features are available.
  - **Ruling from pre-flight scan:** add `CHOICE_LEARNING_MODE` config (`"pairwise"` default, `"listwise"` optional). `include_events=true` uses `PairwiseChoiceLearner` by default; when `CHOICE_LEARNING_MODE="listwise"`, use `ListwiseChoiceLearner` over each impression's candidate set. The benchmark's existing `BenchmarkRecommender.learn` remains the listwise reference.
  - **Auto-accept candidate type:** `/assignments` must choose the event candidate from the impression metadata. If the impression's `candidate_type == "task"`, use `request.task_id` as `candidate_id`; otherwise use `request.worker_id`. This fixes task-direction accepts being silently dropped. Add a test that assigns from a `/recommend/tasks` request and asserts the accept event is recorded.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_events.py`:

```python
def test_recompute_with_events_changes_weights(client):
    before = client.get("/weights").json()["weights"]
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 2})
    body = response.json()
    chosen = body["candidates"][0]["candidate_id"]
    rejected = body["candidates"][1]["candidate_id"]
    client.post("/events", json={"events": [
        {"request_id": body["request_id"], "candidate_id": chosen, "action": "accept", "task_id": "t1", "user_id": "c1"},
        {"request_id": body["request_id"], "candidate_id": rejected, "action": "reject", "task_id": "t1", "user_id": "c1"},
    ]})
    recomputed = client.post("/weights/recompute?include_events=true")
    assert recomputed.status_code == 200
    payload = recomputed.json()
    assert payload["weights"]
    assert payload.get("updates", 0) > 0
    assert payload["weights"] != before
    assert abs(sum(payload["weights"].values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_api_events.py::test_recompute_with_events_changes_weights -v`
Expected: FAIL because `include_events` is not supported.

- [ ] **Step 3: Implement**

- `RecommendationService.features_for`: **must be feature-parity with serving.** Reuse the same feature-building path/kwargs used by `recommend_workers_for_task`/`recommend_tasks`: normalized ItemCF score (not raw), semantic matcher similarity (0.5 only when no matcher), `p_accept` when the acceptance model is fitted, `recent_impressions`, `collaboration`, `communication`, `pay_fit`, profiles, and the same `now`. Add a test asserting `features_for(task_id, worker_id)` equals the serving feature breakdown for the same pair. Raise `KeyError` for unknown IDs.
- `POST /weights/recompute`: parse `include_events` (default true) and `mode` (from `CHOICE_LEARNING_MODE`, default `"pairwise"`). Build `ChoicePair`s from `dataset.train_events`/`store.events` using `features_for` as the lookup; call `PairwiseChoiceLearner(prior=current_weights).fit(pairs)`. When `mode="listwise"`, use `ListwiseChoiceLearner` over each impression's candidate features instead. Merge with the existing rating-based batch fit (e.g., average the two weight vectors, then `project_weights`); save a new version via the existing `WeightStore`; include `updates` and `binding` in the response.
- `GET /weights/binding`: return the last `WeightBindingReport` recorded during recompute; **persist it to `reports/weight_binding.json`** after projection and have `GET` fall back to reading that file when `app.state.last_binding` is None; if neither exists, return `{"available": False}`.
- Personalization: in `POST /events`, after recording an accept/reject, pair against **both** the current payload and prior `store.events` for the same `request_id` (split batches must work). Maintain a learned-request set so re-posts do not double-update. Call `app.state.personalizer.update_pair(user_id, chosen_features, rejected_features)` when both sides are available; guard with `try/except KeyError` so event ingestion never fails because personalization is unavailable. Add tests for split accept/reject batches and `source == "online_pair"`.
- Recompute tests: assert `source`/`mode` on the response so the tests fail if the purpose-built choice learner branch is dead. Binding test: assert specific keys plus the persisted `reports/weight_binding.json`.
- Do not construct `RecommendationService` on `/events` payloads that have no accept+reject group; filter first.
- `/assignments` auto-accept: look up the impression for `recommendation_context.request_id`; if its `metadata["candidate_type"] == "task"`, record the accept with `candidate_id=request.task_id`, else `candidate_id=request.worker_id`. Add a test that assigns from a `/recommend/tasks` request and asserts the event is recorded.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_api_events.py::test_recompute_with_events_changes_weights -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

