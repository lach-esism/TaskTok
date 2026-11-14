## Task 13: `load` and `customer_preference` Upgrades

**Files:**
- Modify: `app/features.py`
- Modify: `app/preference/customer.py`
- Modify: `app/service.py` (wire the new feature inputs)
- Test: `tests/test_features_v2.py`, `tests/test_preference_profiles.py` (update), `tests/test_recommend.py` (extend)

**Interfaces:**
- Produces:
  - `load_score(worker: Worker, task: Task, now: datetime | None = None, recent_impressions: int = 0) -> float`.
  - `customer_preference_score(customer, worker, task, reputation, expertise, profile=None, *, pay_fit=0.5, deadline_feasibility=0.5, collaboration=0.0, communication=0.5, now: datetime | None = None) -> float`. The no-profile fallback must call `load_score(worker, task, now=now)` so the load term uses the data-relative reference.
  - Final `candidate_features` signature:
    ```python
    def candidate_features(
        worker, task, customer, cf_score=0.0, now=None,
        worker_profile=None, customer_profile=None,
        semantic_similarity=0.5, p_accept=None, recent_impressions=0,
    ) -> dict[str, float]
    ```
  - `RecommendationService.__init__(..., semantic_matcher: SemanticMatcher | None = None, acceptance_model: AcceptanceModel | None = None)`.
  - `DEFAULT_ATTRIBUTE_WEIGHTS` extended with `collaboration: 0.10`, `deadline_fit: 0.05`, and adjusted existing values to sum to 1.0.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features_v2.py`:

```python
from app.features import load_score
from app.preference.customer import DEFAULT_ATTRIBUTE_WEIGHTS


def test_load_formula_with_exposure():
    import math
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = make_worker(capacity_hours=40, current_load_hours=10)
    task = make_task(estimated_hours=10, deadline=now + timedelta(hours=20))
    value = load_score(worker, task, now=now, recent_impressions=100)
    capacity_score = (40 - 10 - 10) / 40
    deadline_feasibility = time_fit_score(worker, task, now=now)
    exposure_fairness = math.exp(-100 / 20)
    expected = 0.6 * capacity_score + 0.25 * deadline_feasibility + 0.15 * exposure_fairness
    assert value == pytest.approx(expected, abs=1e-9)


def test_customer_attribute_weights_sum_to_one_and_include_new_keys():
    assert set(DEFAULT_ATTRIBUTE_WEIGHTS) == {
        "reputation", "expertise", "speed", "communication",
        "price", "collaboration", "deadline_fit",
    }
    assert sum(DEFAULT_ATTRIBUTE_WEIGHTS.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_features_v2.py::test_customer_attribute_weights_sum_to_one_and_include_new_keys -v`
Expected: FAIL because the new keys are absent.

- [ ] **Step 3: Implement**

- `load_score`: `capacity_score` as before; `deadline_feasibility = time_fit_score(...)`; `exposure_fairness = exp(-recent_impressions / 20)`; return `0.6*capacity + 0.25*deadline + 0.15*exposure`, clamped.
- `DEFAULT_ATTRIBUTE_WEIGHTS`: exactly `{"reputation":0.30, "expertise":0.20, "speed":0.15, "communication":0.10, "price":0.10, "collaboration":0.10, "deadline_fit":0.05}`.
- `customer_preference_score`: use the profile weights when `confidence >= 0.2`; for missing attributes, fill from `DEFAULT_ATTRIBUTE_WEIGHTS`; compute values: reputation, expertise, speed (`on_time/completed` or 0.5), communication, price=pay_fit, collaboration, deadline_fit=deadline_feasibility; normalize by the sum of weights. If no profile, use the fallback `0.4*reputation + 0.3*expertise + 0.15*load + 0.15*pay_fit`.
- `candidate_features`: pass `semantic_similarity`, `p_accept`, and `recent_impressions` into `expertise_score`, `preference_score`, and `load_score`; compute `pay_fit` and `communication` if not supplied; forward `now` into `preference_score` and `customer_preference_score` so the fallback load term is data-relative.
- `RecommendationService`: in both `recommend_workers_for_task` and `recommend_tasks`, before scoring each candidate:
  - `recent = self.store.recent_impression_counts(self.reference_time)`;
  - `communication = mean(worker.communication_ratings)/5 if worker.communication_ratings else 0.5`;
  - `collaboration = self.store.prior_collaboration_count(customer.customer_id, worker.worker_id)`;
  - `pay_fit = pay_fit_score(worker, task)`;
  - `semantic = self.semantic_matcher.similarity(build_task_text(task), build_worker_text(worker)) if self.semantic_matcher else 0.5`;
  - `p_accept = self.acceptance_model.predict(accept_features(...)) if self.acceptance_model and self.acceptance_model.is_fitted else None`. Compute the two passthrough inputs: `region_match = 1.0` same region, `0.8` both remote, else `0.3`; `historical_accept_rate = (accepted + 1) / (accepted + rejected + 2)` from the worker's accept/reject events, or `0.5` when no events exist;
  - pass all values to `candidate_features`.
- `create_app`: build one `SemanticMatcher` from all worker/task texts and one global `AcceptanceModel` from `store.events`; pass both to `RecommendationService`. If the matcher cannot fit (too few texts), pass `None`.
- Update `tests/test_preference_profiles.py` expected `DEFAULT_ATTRIBUTE_WEIGHTS` to the new dict.
- Add to `tests/test_recommend.py`:
  ```python
  def test_service_wires_new_feature_inputs(small_store):
      service = RecommendationService(small_store)
      candidates = service.recommend_workers("t1", top_n=3)
      assert candidates
      assert set(candidates[0].breakdown) == {
          "reputation", "skill", "expertise", "collaborative",
          "preference", "load", "customer_preference",
      }
  ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_features_v2.py tests/test_preference_profiles.py tests/test_recommend.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

