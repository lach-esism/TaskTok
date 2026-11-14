## Task 10: `skill` and `expertise` Upgrades

**Files:**
- Modify: `app/features.py`
- Test: `tests/test_features_v2.py` (create)

**Interfaces:**
- Consumes: `Worker.certifications`, `Worker.category_ratings`, `Task.required_skill_weights`.
- Produces:
  - `category_history_score(worker: Worker) -> float`.
  - `skill_score(worker: Worker, task: Task) -> float` (updated).
  - `expertise_score(worker: Worker, task: Task, semantic_similarity: float | None = None) -> float` (updated).
  - `candidate_features(..., semantic_similarity: float = 0.5) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_features_v2.py`; copy the `make_worker` / `make_task` helpers from `tests/test_features.py` and add:

```python
import pytest
from app.features import category_history_score, expertise_score, skill_score


def test_skill_uses_required_skill_weights():
    task = make_task(
        required_skills={"python": 3, "writing": 3},
        required_skill_weights={"python": 3.0, "writing": 1.0},
    )
    worker = make_worker(skills={"python": 3, "writing": 1})
    expected = (3.0 * 1.0 + 1.0 * (1 / 3)) / 4.0
    assert skill_score(worker, task) == pytest.approx(expected)


def test_no_required_skills_does_not_return_one():
    worker = make_worker()
    task = make_task(required_skills={})
    expected = 0.5 * expertise_score(worker, task) + 0.5 * category_history_score(worker)
    assert skill_score(worker, task) == pytest.approx(expected)
    assert skill_score(worker, task) != 1.0


def test_expertise_uses_certification_and_semantic():
    worker = make_worker(certifications={"software_dev": 1.0}, ratings=[], completed=0)
    task = make_task()
    value = expertise_score(worker, task, semantic_similarity=1.0)
    expected = 0.35 * 0.6 + 0.15 * 1.0 + 0.25 * (4.2 / 5) + 0.25 * 1.0
    assert value == pytest.approx(expected, abs=1e-6)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_features_v2.py -v`
Expected: FAIL because `category_history_score` is missing / formulas are old.

- [ ] **Step 3: Implement the formulas**

Implement spec §8.2–8.3 exactly:
- `category_history_score`: `global_rating = compute_reputation(worker).rating` is already normalized to **0–1** in this codebase; `category_values = worker.category_ratings.get(category, [])`; `n`, `mean`; `(n*mean/5 + 10*global_rating) / (n+10)`; if `n == 0`, `global_rating`. Do not divide `global_rating` by 5 again.
- `skill_score`: weighted average using `task.required_skill_weights.get(skill, 1.0)`; no required skills → `0.5 * expertise_score(worker, task) + 0.5 * category_history_score(worker)`.
- `expertise_score`: `0.35*specialty + 0.15*certification + 0.25*category_history + 0.25*semantic`, with `specialty = worker.specialties.get(task.category, 0)/5`, `certification = clamp(worker.certifications.get(task.category, 0.0))`, `semantic = semantic_similarity if provided else 0.5`. Clamp to `[0,1]`.
- `candidate_features` passes `semantic_similarity` through.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_features_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. The existing `test_features.py` should still pass because it uses required skills and expects `skill_score` 1.0/0.0.

- [ ] **Step 6: Checkpoint**

No git commit.

---

