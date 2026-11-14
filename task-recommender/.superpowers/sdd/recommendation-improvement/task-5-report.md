# Task 5 Report: Exact ε-Greedy Propensities

## Status

DONE (concern 1 resolved in the fix report at the end of this document; concern 2
remains an expected scope note for Task 18)

## What Was Implemented

### `app/learning/exploration.py`

Added `epsilon_greedy_propensities(candidate_ids, k, epsilon)` implementing the exact formula:

- `N = len(candidate_ids)`, `K = min(k, N)`
- `N == 0` -> `{}`
- `N <= K` -> `{cid: 1.0}` for every candidate
- rank `i < K - 1` -> `p = 1.0`
- rank `i == K - 1` -> `p = (1 - epsilon) + epsilon / (N - K + 1)`
- rank `i > K - 1` -> `p = epsilon / (N - K + 1)`
- every probability clamped to `[1e-6, 1.0]`
- `epsilon` clamped to `[0.0, 1.0]`

Added module constants `MIN_PROPENSITY = 1e-6` / `MAX_PROPENSITY = 1.0` and a
`_clamp_propensity` helper.

Updated `ExplorationPolicy`:

- `__init__(self, epsilon=0.10, seed: int | None = None)`; `seed=None` now builds
  `random.Random()` from system entropy, `seed=int` remains deterministic for tests.
- `rerank` computes propensities from the original ranked IDs via
  `epsilon_greedy_propensities`, keeps the top `k`, and with probability `epsilon`
  replaces the last item with a uniformly sampled item from the non-top-K pool
  (`candidates[k:]`). The exact per-candidate propensity is stored in
  `_propensities` and written with `replace(item, propensity=p)`.
- `k <= 0` returns `[]` and clears stored propensities.
- `propensity_for` is unchanged (returns `0.0` for unknown IDs).
- `ips_score` / `snips_score` are unchanged.

### `tests/test_propensity.py` (created)

Contains the three tests from the brief verbatim:

- `test_exact_epsilon_greedy_propensities`
- `test_k_ge_n_returns_ones`
- `test_forced_exploration_replaces_last_and_uses_exact_propensity`

## Tests Run and Output

### Step 2 — failing test first

Command: `python -m pytest tests/test_propensity.py -v`

Result (before implementation):

```text
ERROR collecting tests/test_propensity.py
E   ImportError: cannot import name 'epsilon_greedy_propensities' from
    'app.learning.exploration'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
============================== 1 error in 0.96s ==============================
```

Confirms the expected failure mode.

### Step 4 — focused tests after implementation

Command: `python -m pytest tests/test_propensity.py -v`

Result:

```text
tests/test_propensity.py::test_exact_epsilon_greedy_propensities PASSED   [ 33%]
tests/test_propensity.py::test_k_ge_n_returns_ones PASSED                 [ 66%]
tests/test_propensity.py::test_forced_exploration_replaces_last_and_uses_exact_propensity PASSED [100%]

3 passed in 0.04s
```

### Step 5 — full suite

Command: `python -m pytest tests/ -q`

Result:

```text
173 passed in 13.25s
```

## Files Changed

- `app/learning/exploration.py` (modified)
- `tests/test_propensity.py` (created)
- `.superpowers/sdd/recommendation-improvement/task-5-report.md` (this report)

No changes to `app/main.py` or any other file.

## Self-Review Findings

- Existing tests remain compatible: `test_exploration.py` (determinism, explored
  propensity > 0) and `test_phase2_api.py` (`0.0 < propensity <= 1.0` and at least
  one `< 1.0`) all pass. The API test still sees a sub-1.0 propensity on the K-th
  rank because `p_K = (1 - eps) + eps / (N - K + 1) < 1`.
- `N <= K` path returns all ones and cannot trigger exploration (the guard
  `len(candidates) > k` is false), matching the brief.
- `seed=None` produces a system-entropy `random.Random`; no fixed seed reset inside
  `rerank`, so repeated calls on one instance advance the RNG as intended.
- `epsilon` is clamped consistently in both the policy and the free function.
- Degenerate direct call `epsilon_greedy_propensities(ids, k=0, ...)` follows the
  brief's pseudocode path (all ranks fall into the "rest" branch) rather than
  returning `{}`. `rerank` never calls it with `k == 0` (it returns `[]` early), so
  this does not affect policy behavior. Left unguarded to stay verbatim with the
  brief.
- Duplicate candidate IDs would collapse in the returned dict; this matches the
  pre-existing assumption that candidate IDs are unique.

## Concerns

1. **Formula vs. sampling pool denominator.** The brief's exact formula divides the
   exploration mass by `N - K + 1` (the K-th rank plus all ranks below it), which is
   the correct inclusion probability if exploration samples uniformly from
   `{rank K, ..., rank N}` and treats selecting rank K as a no-op. The brief's
   `rerank` instruction, however, says to replace the last item with a uniformly
   sampled **non-top-K** item (`candidates[k:]`, size `N - K`), which is also what
   the provided test requires (with `epsilon=1.0`, `seed=42`, any pool containing
   the K-th rank in rank order would select the K-th item and fail the
   `result[-1] not in top_ids` assertion). Consequently the values reported by
   `rerank` are the formula's exact values as mandated and stored in
   `_propensities`, but the empirical sampling frequency of the K-th rank
   (`1 - epsilon`) and of each tail rank (`epsilon / (N - K)`) differ slightly from
   the reported `(1 - epsilon) + epsilon / (N - K + 1)` and
   `epsilon / (N - K + 1)`. This is an inconsistency in the brief/design, not a
   test failure. If a future task adds the design doc's empirical-frequency test
   (100,000 impressions, error < 0.01), `rerank`'s sampling pool would need to
   include the K-th rank as a no-op option (and the test's RNG expectation would
   need revisiting).
2. **`app/main.py` still constructs `ExplorationPolicy(seed=42)` per request**, so
   the production RNG remains effectively deterministic until Task 18 wires in a
   shared policy. This task was scoped not to touch `main.py`.

---

## Fix Report (post-review)

Concern 1 was a real correctness bug: the reported propensity must match the
logging policy. The updated brief made the formula binding and specified the
sampling pool as `candidates[K-1:]` (the K-th item plus the tail, size `N-K+1`).

### What Was Fixed

`app/learning/exploration.py` — `ExplorationPolicy.rerank` now samples uniformly
from `candidates[k - 1:]` whenever the RNG draw is below `epsilon`:

- if the sampled item is the K-th candidate, the Top-K is left unchanged (the K-th
  is the "no-op" outcome);
- if the sampled item is a tail candidate, it replaces the last (K-th) slot.

This makes the empirical inclusion distribution exactly match
`epsilon_greedy_propensities`: top-(K-1) = 1, K-th =
`(1 - epsilon) + epsilon / (N - K + 1)`, tail = `epsilon / (N - K + 1)`.

`tests/test_propensity.py`:

- Updated `test_forced_exploration_replaces_last_and_uses_exact_propensity` to
  accept the K-th item from the exploration pool:
  `result[-1].candidate_id in {c.candidate_id for c in candidates[2:]}`.
- Added `test_empirical_inclusion_matches_theoretical_propensity`: 100,000
  `rerank` trials with `N=5`, `K=3`, `epsilon=0.1`; each candidate's empirical
  inclusion frequency must match `epsilon_greedy_propensities` within `0.01`.

### Commands and Output

Command: `python -m pytest tests/test_propensity.py -v`

```text
tests/test_propensity.py::test_exact_epsilon_greedy_propensities PASSED  [ 25%]
tests/test_propensity.py::test_k_ge_n_returns_ones PASSED                [ 50%]
tests/test_propensity.py::test_forced_exploration_replaces_last_and_uses_exact_propensity PASSED [ 75%]
tests/test_propensity.py::test_empirical_inclusion_matches_theoretical_propensity PASSED [100%]

4 passed in 1.01s
```

Command: `python -m pytest tests/ -q`

```text
174 passed in 14.31s
```

### Remaining Concerns

Concern 2 is unchanged and expected: `app/main.py` still constructs
`ExplorationPolicy(seed=42)` per request; Task 18 wires the shared policy. No
other concerns remain.

