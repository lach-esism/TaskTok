## Task 5: Exact ε-Greedy Propensities

**Files:**
- Modify: `app/learning/exploration.py`
- Test: `tests/test_propensity.py` (create)

**Interfaces:**
- Consumes: existing `ScoredCandidate`-like objects with `candidate_id`.
- Produces:
  - `epsilon_greedy_propensities(candidate_ids: list[str], k: int, epsilon: float) -> dict[str, float]`.
  - `ExplorationPolicy.__init__(self, epsilon: float = 0.10, seed: int | None = None)`.
  - `ExplorationPolicy.rerank(self, candidates: list, k: int) -> list`.
  - `ExplorationPolicy.propensity_for(self, candidate_id: str) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_propensity.py`:

```python
import pytest
from app.learning.exploration import ExplorationPolicy, epsilon_greedy_propensities


def test_exact_epsilon_greedy_propensities():
    props = epsilon_greedy_propensities(["a", "b", "c", "d", "e"], k=3, epsilon=0.1)
    assert props["a"] == 1.0
    assert props["b"] == 1.0
    assert props["c"] == pytest.approx(0.9 + 0.1 / 3)
    assert props["d"] == pytest.approx(0.1 / 3)
    assert props["e"] == pytest.approx(0.1 / 3)
    assert sum(props.values()) == pytest.approx(3.0)


def test_k_ge_n_returns_ones():
    props = epsilon_greedy_propensities(["a", "b"], k=5, epsilon=0.1)
    assert props == {"a": 1.0, "b": 1.0}


def test_forced_exploration_replaces_last_and_uses_exact_propensity():
    from app.service import ScoredCandidate

    candidates = [
        ScoredCandidate(
            candidate_id=f"c{i}", score=1.0 - i * 0.01,
            breakdown={}, reasons=[], cold_start=False,
        )
        for i in range(10)
    ]
    policy = ExplorationPolicy(epsilon=1.0, seed=42)
    result = policy.rerank(candidates, k=3)
    assert len(result) == 3
    pool_ids = {candidate.candidate_id for candidate in candidates[2:]}
    assert result[-1].candidate_id in pool_ids
    for item in result:
        assert item.propensity == pytest.approx(policy.propensity_for(item.candidate_id))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_propensity.py -v`
Expected: FAIL with `ImportError: cannot import name 'epsilon_greedy_propensities'`.

- [ ] **Step 3: Implement the exact formula**

Implement:

```text
N = len(candidate_ids), K = min(k, N)
if N == 0: return {}
if N <= K: return {cid: 1.0 for cid in candidate_ids}
for i, cid in enumerate(candidate_ids):
    if i < K - 1: p = 1.0
    elif i == K - 1: p = (1 - epsilon) + epsilon / (N - K + 1)
    else: p = epsilon / (N - K + 1)
    clamp p to [1e-6, 1.0]
```

`ExplorationPolicy.rerank` builds candidates as objects with `candidate_id`; use `epsilon_greedy_propensities` on the original ranked IDs whenever the RNG draw is below `epsilon`, sample uniformly from `candidates[K-1:]` — the K-th item plus the tail, size N-K+1. If the sampled item is the K-th, keep the Top-K unchanged; otherwise replace the last item with the sampled tail item. `seed=None` uses `random.Random()`; `seed=int` is for tests. Store the exact propensities in `_propensities` and return `replace(item, propensity=p)`.

Add an empirical test: run `rerank` 100,000 times with N=5, K=3, ε=0.1 and count inclusion; each candidate's empirical inclusion frequency must match `epsilon_greedy_propensities` within 0.01. This is the test that catches a pool/formula mismatch.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_propensity.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass. Existing tests that only check `len(result)` and `propensity` in `(0,1]` should still pass.

- [ ] **Step 6: Checkpoint**

No git commit.

---

