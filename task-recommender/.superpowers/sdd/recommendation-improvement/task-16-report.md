# Task 16 Report: Listwise Choice Learner

## Status

DONE_WITH_CONCERNS

## Files changed

- Modified `app/learning/choice.py`: added `ListwiseChoiceLearner`.
- Modified `tests/test_pairwise_learning.py`: appended the brief's
  `test_listwise_learner_prefers_chosen_candidate` (and its import)
  verbatim.
- Created this report (`.superpowers/sdd/recommendation-improvement/task-16-report.md`).

Diff scope against `snapshots/task-15` confirms only the two allowed source
files differ (excluding `__pycache__`/`.pytest_cache`). `app/main.py`,
`app/service.py`, the API, and the benchmark module were not touched.

## What was implemented

`app/learning/choice.py` now contains
`ListwiseChoiceLearner(prior, l2=0.1, learning_rate=0.05)`:

- `__init__` copies the prior, keeps a fixed key order from
  `list(prior)`, clamps `l2` at zero, stores `learning_rate`, and
  initializes `self.weights = project_weights(self.prior)` so the AHP
  simplex constraints hold from the first call.
- `learn(candidate_features, chosen_index, sample_weight=1.0)`:
  - Returns the current weights unchanged for an empty candidate list.
  - Raises `IndexError("chosen_index out of range")` when `chosen_index`
    is not a valid index into `candidate_features` (otherwise a bad index
    would silently produce an all-zero target and a meaningless gradient).
  - Scores every candidate as `sum(w[key] * features.get(key, 0.0))`
    over the seven fixed keys; missing feature keys default to 0.0.
  - Computes a numerically stable softmax (`exp(score - max(scores))`).
  - Computes the listwise gradient
    `gradient[key] = Σ_i (p_i - y_i) * x_i[key] * sample_weight` where
    `y` is one-hot on `chosen_index`.
  - Applies the update
    `w[key] -= learning_rate * gradient[key] - l2 * (w[key] - prior[key])`,
    i.e. gradient descent on the softmax cross-entropy plus an unscaled L2
    pull toward the prior (the same convention as
    `BenchmarkRecommender.learn`).
  - Projects the updated vector with `project_weights` before storing it
    on `self.weights` and returning a copy.

No new dependencies. No label/ground-truth reads: the only target is the
`chosen_index` argument.

## Tests run and output

1. Step 2, before implementation (confirmed the expected failure):

```
$ python -m pytest tests/test_pairwise_learning.py::test_listwise_learner_prefers_chosen_candidate -v
...
tests\test_pairwise_learning.py:30: in <module>
    from app.learning.choice import ListwiseChoiceLearner
E   ImportError: cannot import name 'ListwiseChoiceLearner' from 'app.learning.choice'
1 error in 1.16s
```

2. Step 4, focused tests after implementation:

```
$ python -m pytest tests/test_pairwise_learning.py -v
tests/test_pairwise_learning.py::test_pairwise_learner_increases_chosen_dimension PASSED [ 33%]
tests/test_pairwise_learning.py::test_propensity_clipping PASSED          [ 66%]
tests/test_pairwise_learning.py::test_listwise_learner_prefers_chosen_candidate PASSED [100%]
3 passed in 0.06s
```

3. Step 5, full suite:

```
$ python -m pytest tests/ -q
222 passed in 18.64s
```

The previous suite size (Task 15) was 221 tests; the appended test brings
it to 222 with no regressions.

## Manual verification of uncovered behavior

The brief's test only checks ranking and the simplex sum, so the following
were exercised with throwaway inline scripts (no files added):

- **Learning direction.** Chosen candidate with `skill=1.0` vs two at
  `skill=0.0` (all other features equal): scores went from
  `[0.6, 0.4, 0.4]` to `[0.66, 0.34, 0.34]` after one step at
  `learning_rate=0.5`; the `skill` weight rose `0.20 -> 0.32`.
- **Simplex validity.** `validate_weights` passes after every update, and
  50 alternating-chosen updates kept the sum at 1.0 to `< 1e-9`.
- **Empty candidates.** Returns the current weights unchanged.
- **Bad index.** `chosen_index=5` on three candidates raises `IndexError`.
- **Missing keys.** Candidates lacking some feature keys are treated as
  0.0 and produce a valid projected vector.
- **`sample_weight=0.0`.** With no data gradient and weights already at
  the prior, the step is a no-op (L2 deviation is zero).
- **L2 pull.** After two steps, `l2=0` put `skill` at its projection cap
  0.32, while `l2=5` kept it at 0.125 near the 0.20 prior, confirming the
  penalty pulls toward the prior.
- **Style.** No line in `app/learning/choice.py` exceeds 79 characters.

## Self-review findings

1. **Sign of the update (brief ambiguity).** The brief says
   `weights += learning_rate * gradient` while also saying to use the
   gradient from `BenchmarkRecommender.learn`, which subtracts
   `learning_rate * gradient` (the correct gradient-descent direction for
   softmax cross-entropy). The `+=` line would *decrease* the chosen
   candidate's score and is inconsistent with both the reference and the
   test name ("prefers chosen candidate"). I implemented the reference's
   descent direction and manually confirmed the chosen score rises.
   The brief's L2 wording ("subtract `l2 * (weights[key] - prior[key])`")
   is implemented literally and matches the reference's unscaled penalty.
2. **Empty candidate set.** Returning the current weights mirrors
   `PairwiseChoiceLearner.fit([])`'s no-op behaviour instead of raising.
3. **Out-of-range index.** Validated explicitly with `IndexError`; a
   silent all-zero target would corrupt the weights.
4. **Numerical stability.** Softmax subtracts the maximum score, as in the
   benchmark reference, so large scores cannot overflow `math.exp`.
5. **Missing feature keys.** `.get(key, 0.0)` keeps partial feature dicts
   usable, consistent with the rest of `app/learning`.
6. **Diff scope.** Verified against `snapshots/task-15`: only
   `app/learning/choice.py` and `tests/test_pairwise_learning.py` differ.

## Concerns

1. **Brief sign inconsistency (documented above).** If a reviewer
   genuinely intended gradient *ascent* (`weights += lr * gradient`), the
   signed update would need to flip; the provided test does not
   distinguish because the three candidates are collinear in the only
   differing dimensions. I chose the benchmark-reference semantics, which
   is also what Task 19 names as "the listwise reference".
2. **`sample_weight` is not clamped.** The pairwise path clamps weights
   to `[0.1, 10.0]`; the brief does not ask for clamping here, so a caller
   passing a very large weight can take a large raw step (still bounded
   after projection). Task 19 should supply sane weights.
3. **L2 is unscaled by `learning_rate`.** This follows the brief and the
   benchmark reference, but means an unusually large `l2` can overshoot
   the prior (e.g. `l2=5` pulled `skill` well under its prior in two
   steps). The default `l2=0.1` is stable.
4. **No API wiring or config mode.** Intentionally out of scope; Task 19
   adds `CHOICE_LEARNING_MODE="listwise"`.
5. **`learn` has no averaging over impressions.** It applies one
   impression's gradient per call, exactly as specified. Task 19 should
   average/merge vectors across impressions if desired.
