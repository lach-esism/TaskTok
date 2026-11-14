## Task 15: Pairwise Choice Learner and Pair Builder

**Files:**
- Create: `app/learning/choice.py`
- Test: `tests/test_pairwise_learning.py` (create)

**Interfaces:**
- Consumes: `RecommendationEvent`, `Impression`, seven-dim feature dicts, `project_weights`.
- Produces:
  - `ChoicePair(chosen: dict[str, float], rejected: dict[str, float], weight: float = 1.0)`.
  - `PairwiseChoiceLearner(prior: dict[str, float], l2: float = 0.1)`.
  - `PairwiseChoiceLearner.fit(pairs: list[ChoicePair]) -> dict[str, float]`.
  - `PairwiseChoiceLearner.update_online(chosen, rejected, learning_rate: float = 0.05) -> dict[str, float]`.
  - `build_pairs(events, feature_lookup, time_decay_tau_days: float = 30.0) -> list[ChoicePair]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pairwise_learning.py`:

```python
import pytest
from app.config import DEFAULT_WEIGHTS
from app.learning.choice import ChoicePair, PairwiseChoiceLearner, build_pairs


def _features(**overrides):
    base = {key: 0.5 for key in DEFAULT_WEIGHTS}
    base.update(overrides)
    return base


def test_pairwise_learner_increases_chosen_dimension():
    prior = dict(DEFAULT_WEIGHTS)
    pairs = [
        ChoicePair(chosen=_features(skill=1.0), rejected=_features(skill=0.0), weight=1.0)
        for _ in range(50)
    ]
    weights = PairwiseChoiceLearner(prior).fit(pairs)
    assert weights["skill"] >= prior["skill"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_propensity_clipping():
    learner = PairwiseChoiceLearner(dict(DEFAULT_WEIGHTS))
    pair = ChoicePair(chosen=_features(skill=1.0), rejected=_features(skill=0.0), weight=20.0)
    weights = learner.fit([pair])
    assert abs(sum(weights.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pairwise_learning.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

- `PairwiseChoiceLearner.fit`: build `X = chosen - rejected` in a fixed key order (use `list(prior.keys())`); `y=1`; `sample_weight = [clamp(pair.weight, 0.1, 10)]`; fit `LogisticRegression(fit_intercept=False, C=1/l2, max_iter=1000)`; take `coef_[0]`; `project_weights`; if no pairs, return `prior`.
- `update_online`: reuse the existing `OnlineWeightLearner.update_pair` logic or implement the same gradient; `project_weights`.
- `build_pairs`: group events by `request_id`; positives = actions in `{"click","apply","accept"}`, negatives = `{"reject","ignore"}`; for each positive-negative combination, create a `ChoicePair` with `weight = exp(-Δt/30) * clamp(1/propensity, 0.1, 10)`, where `Δt` is the absolute seconds between event times (clamp negative to 0); use `feature_lookup(event)` to get the seven-dim vector.
- `feature_lookup` is `Callable[[RecommendationEvent], dict[str, float]]`; the caller supplies it (Task 19).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pairwise_learning.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

