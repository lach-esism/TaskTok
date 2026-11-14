## Task 18: `/events` API, `request_id`, and Auto-Accept

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Modify: `app/events.py` (event `task_id` precedence)
- Modify: `tests/conftest.py`
- Modify: `tests/test_phase2_api.py` (rollback test exposure-state reset)
- Test: `tests/test_api_events.py` (create)

**Interfaces:**
- Consumes: `EventService`, `ExplorationPolicy`.
- Produces:
  - Pydantic `EventItem` (`request_id`, `candidate_id`, `candidate_type` default `"worker"`, `action`, `task_id`, `user_id`, `role`, `metadata`).
  - `EventsRequest(events: list[EventItem])`.
  - `EventsResponse(accepted: int, rejected: list[dict])`.
  - `RecommendResponse.request_id: str = ""`.
  - `RecommendationContext.request_id: str = ""`.
  - `create_app(..., events_dir: Path | None = None, exploration_seed: int | None = None)` sets `app.state.events = EventService(store, persist_dir=events_dir or Path(...)/"data"/"events")` and `app.state.exploration = ExplorationPolicy(epsilon=0.10, seed=exploration_seed)`.
  - Update `tests/conftest.py` `client` fixture to pass `events_dir=tmp_path / "events"` and `exploration_seed=42` so tests do not write into the repository data directory and remain deterministic.
  - `/recommend/workers` and `/recommend/tasks` create a `request_id`, record an impression, and return it.
  - **Ruling from pre-flight scan:** replace the per-request `ExplorationPolicy(epsilon=0.10, seed=42)` constructions in both routes with `app.state.exploration.rerank(...)`. Production uses `exploration_seed=None` (system entropy); tests/demos inject a seed. Without this, the Task 5 propensity fix never takes effect.
  - `POST /events`, `GET /events/metrics`.
  - `/assignments` auto-records `accept` when `recommendation_context.request_id` is non-empty.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_events.py`:

```python
def test_recommend_returns_request_id_and_events_flow(client):
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    candidate = body["candidates"][0]["candidate_id"]
    event = client.post(
        "/events",
        json={"events": [{
            "request_id": body["request_id"],
            "candidate_id": candidate,
            "action": "click",
            "task_id": "t1",
            "user_id": "c1",
            "role": "customer",
        }]},
    )
    assert event.status_code == 200
    metrics = client.get("/events/metrics").json()
    assert metrics["clicks"] >= 1


def test_events_reject_duplicates_and_invalid_actions(client):
    response = client.post("/recommend/workers", json={"task_id": "t1", "top_n": 1})
    body = response.json()
    candidate = body["candidates"][0]["candidate_id"]
    payload = {"events": [{
        "request_id": body["request_id"], "candidate_id": candidate,
        "action": "click", "task_id": "t1",
    }]}
    assert client.post("/events", json=payload).status_code == 200
    assert client.post("/events", json=payload).status_code == 409
    bad = {"events": [{
        "request_id": body["request_id"], "candidate_id": candidate,
        "action": "nope", "task_id": "t1",
    }]}
    assert client.post("/events", json=bad).status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_api_events.py -v`
Expected: FAIL because `request_id` is absent / `/events` is 404.

- [ ] **Step 3: Implement**

- Add the Pydantic models and the `request_id` field to `RecommendResponse` / `RecommendationContext`.
- Add `events_dir: Path | None = None` and `exploration_seed: int | None = None` to `create_app`; create `EventService(require_store(), persist_dir=events_dir or Path(__file__).resolve().parent.parent / "data" / "events")`; create `app.state.exploration = ExplorationPolicy(epsilon=0.10, seed=exploration_seed)`; store both on `app.state`.
- Update `tests/conftest.py` `client` fixture to `TestClient(create_app(small_store, weights_dir=tmp_path, events_dir=tmp_path / "events", exploration_seed=42))`.
- In the recommendation routes, replace the per-request `ExplorationPolicy(epsilon=0.10, seed=42)` with `app.state.exploration.rerank(...)`; generate `request_id = uuid.uuid4().hex`; after `rerank`, call `events.record_impression(request_id, query_id, [c.candidate_id for c in candidates], {c.candidate_id: c.propensity for c in candidates}, "epsilon_greedy_topk")`; pass `request_id` to the response.
- `POST /events`: validate actions (Pydantic `Literal` or a manual check returning 422); call `record_event` with `metadata={"candidate_type": item.candidate_type, "task_id": item.task_id, "weights_version": ...}`; map `KeyError`→404, `ValueError`→409; return `EventsResponse`. The `/recommend/tasks` flow sends `candidate_type="task"` and `task_id=candidate_id`; `/recommend/workers` sends `"worker"` and the impression query_id is the task.
- **Server-side event labeling:** `EventService.record_event` must fall back to the impression's `metadata` for `candidate_type` and `task_id` when the event omits them. For `candidate_type="task"`, the event `task_id` is the candidate task. Add a test where the client omits both fields on a `/recommend/tasks` request and the stored event is still labeled correctly.
- **Skip empty impressions:** do not record an `Impression` when the recommendation returns zero candidates; otherwise `funnel_metrics()["impressions"]` is inflated.
- **Event `task_id` must be correct for both directions.** `EventService.record_event` should use `metadata["task_id"]` when provided, else `impression.query_id`. For worker→tasks, the event's `task_id` is the candidate task, not the worker query id. Add a test asserting this.
- **Use the shared exploration policy everywhere.** Pass `app.state.exploration` into `_node_candidates` (chain node recommendation); do not construct a new fixed-seed policy there. The two main routes and chain-node recommendation must all use the shared policy.
- **Update the pre-existing rollback test.** `tests/test_phase2_api.py::test_active_weight_version_changes_and_rollback_restores` now sees stateful exposure counts from impression logging. Expand the allowed edit set to include that file: snapshot/clear `store.impressions` between baseline, learned, and restored calls (or use a fresh store per call), and create its client with `events_dir=tmp_path / "events", exploration_seed=42`. Do not weaken the rollback assertion; the comparison must be under identical exposure state.
- `GET /events/metrics`: return `app.state.events.funnel_metrics()`.
- `/assignments`: if `recommendation_context.request_id`, call `record_event(..., action="accept", user_id=customer_id, role="customer", metadata={"weights_version": app.state.weight_store.active().version})`; catch **both** `KeyError` and `ValueError` so an unknown request or a duplicate accept never turns a successful assignment into a 500. Add a test that posts an `accept` event first, then assigns with the same `request_id`, and asserts 200 (not 500).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_api_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. Existing API tests should still pass because the new response field has a default.

- [ ] **Step 6: Checkpoint**

No git commit.

---

