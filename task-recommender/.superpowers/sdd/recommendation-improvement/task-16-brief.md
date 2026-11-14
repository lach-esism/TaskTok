## Task 16: Listwise Choice Learner

**Files:**
- Modify: `app/learning/choice.py`
- Test: `tests/test_pairwise_learning.py` (extend)

**Interfaces:**
- Produces:
  - `ListwiseChoiceLearner(prior: dict[str, float], l2: float = 0.1, learning_rate: float = 0.05)`.
  - `ListwiseChoiceLearner.learn(candidate_features: list[dict[str, float]], chosen_index: int, sample_weight: float = 1.0) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pairwise_learning.py`:

```python
from app.learning.choice import ListwiseChoiceLearner


def test_listwise_learner_prefers_chosen_candidate():
    prior = dict(DEFAULT_WEIGHTS)
    learner = ListwiseChoiceLearner(prior, learning_rate=0.5)
    candidates = [
        _features(skill=1.0, reputation=1.0),
        _features(skill=0.1, reputation=0.1),
        _features(skill=0.2, reputation=0.2),
    ]
    weights = prior
    for _ in range(20):
        weights = learner.learn(candidates, chosen_index=0, sample_weight=1.0)
    score = lambda f: sum(weights[k] * f[k] for k in weights)
    assert score(candidates[0]) > score(candidates[1])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pairwise_learning.py::test_listwise_learner_prefers_chosen_candidate -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Use the softmax gradient from `app/benchmark/recommender.py::BenchmarkRecommender.learn`: `p = softmax(scores)`, `gradient[key] = Σ (p_i - y_i) * x_i[key] * sample_weight`, then `weights -= learning_rate * gradient` (gradient descent; the reference uses a minus sign), then `project_weights`. Include L2 toward the prior: subtract `l2 * (weights[key] - prior[key])`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pairwise_learning.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

