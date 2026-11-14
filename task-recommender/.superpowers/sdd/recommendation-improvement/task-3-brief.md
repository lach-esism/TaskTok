## Task 3: Synthetic New Fields and Train/Test Feedback Split

**Files:**
- Modify: `app/data/synthetic.py`
- Test: `tests/test_synthetic.py` (extend)

**Interfaces:**
- Consumes: `Dataset.train_feedback` / `test_feedback` from Task 1.
- Produces: `generate_dataset(...)` populates `expected_pay`, `certifications`, `communication_ratings`, and `required_skill_weights`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_synthetic.py`:

```python
from app.data.synthetic import generate_dataset


def test_synthetic_new_fields_are_populated():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    assert all(worker.expected_pay > 0 for worker in dataset.workers)
    assert any(worker.certifications for worker in dataset.workers)
    assert any(worker.communication_ratings for worker in dataset.workers)
    for task in dataset.tasks:
        assert set(task.required_skill_weights) == set(task.required_skills)


def test_train_and_test_feedback_are_disjoint():
    dataset = generate_dataset(
        n_workers=10, n_tasks=20, n_assignments=40, seed=42, n_new_users=0,
    )
    train_ids = {item.feedback_id for item in dataset.train_feedback}
    test_ids = {item.feedback_id for item in dataset.test_feedback}
    assert train_ids.isdisjoint(test_ids)
    assert len(train_ids) + len(test_ids) == len(dataset.feedback)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_synthetic.py::test_synthetic_new_fields_are_populated -v`
Expected: FAIL because fields are still empty/default.

- [ ] **Step 3: Implement the synthetic fields**

In `generate_dataset`:
- Add a shared helper `_sample_pay_and_certifications(rng, specialties) -> tuple[float, dict[str, float]]` and use it in both the main worker loop and the new-user loop (do not duplicate the logic):
  - `expected_pay = round(median_budget_of_specialty * rng.uniform(0.7, 1.3), 2)`; use the `TASK_PROFILES[category]["budget"]` midpoint for the worker's first specialty. If no specialty, use `rng.uniform(2000, 12000)`.
  - For each `category` in `specialties`, draw `r = rng.random()` **once** and set `0.8 if r < 0.3 else 0.5 if r < 0.7 else 0.0`. This yields exactly P(0.8)=0.3, P(0.5)=0.4, P(0)=0.3. Do not use two sequential draws.
- When generating feedback, with probability 0.5 append `communication_rating = int(round(clamp(quality * 5 + rng.uniform(-0.5, 0.5), 1, 5)))` to the `Feedback` and to `worker.communication_ratings` as a `float`.
- In the post-generation reset block (where `worker.ratings`, `completed`, etc. are cleared), also clear `worker.communication_ratings = []`, then repopulate only from `train` feedback.
- Set `Task.required_skill_weights = {skill: 1.0 for skill in required_skills}`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_synthetic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

