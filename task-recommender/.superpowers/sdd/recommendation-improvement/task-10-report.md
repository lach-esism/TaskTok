# Task 10 Report: `skill` and `expertise` Upgrades

## Status

DONE

## What Was Implemented

All changes in `app/features.py`:

1. **`category_history_score(worker, category=None) -> float`** (new)
   - Uses `compute_reputation(worker).rating` as the global Bayesian prior.
   - With no rated history for `category` (including `category=None`), returns
     the normalized global rating.
   - Otherwise applies Bayesian shrinkage with `m = 10`:
     `(n * mean/5 + m * global_rating) / (n + m)`, clamped to `[0, 1]`.
   - Note: `compute_reputation(...).rating` is already normalized to `[0, 1]`
     in this codebase (see `app/reputation.py`), whereas the spec text labels
     the same quantity as a 0-5 rating. The normalized value is therefore used
     directly as the weighted prior; this is algebraically identical to the
     spec formula (`10 * global_rating_0to5 / 5 == 10 * normalized`).

2. **`skill_score(worker, task)`** (updated)
   - Weighted skill match:
     `sum(w_s * min(skill/required, 1)) / sum(w_s)` where
     `w_s = task.required_skill_weights.get(skill, 1.0)`.
   - Guards a non-positive total weight (returns `0.0`, never NaN).
   - No `required_skills` -> `0.5 * expertise_score(worker, task) +
     0.5 * category_history_score(worker, task.category)` (clamped), never `1.0`.

3. **`expertise_score(worker, task, semantic_similarity=None)`** (updated)
   - `specialty = worker.specialties.get(task.category, 0) / 5`
   - `certification = clamp(worker.certifications.get(task.category, 0.0))`
   - `category_history = category_history_score(worker, task.category)`
   - `semantic = 0.5` when `None`, else clamped; NaN maps to `0.5`.
   - Result: `clamp(0.35*specialty + 0.15*certification + 0.25*category_history
     + 0.25*semantic)`.

4. **`candidate_features(..., semantic_similarity: float = 0.5)`**
   - New trailing keyword parameter (placed after `customer_profile` to keep
     existing positional calls intact).
   - Passed through to `expertise_score`.
   - Seven feature keys unchanged.

## Tests

Created `tests/test_features_v2.py` with the three tests and the
`make_worker`/`make_task` helpers copied from `tests/test_features.py`.

Step 2 (expected failure) output:

```
tests/test_features_v2.py:6: in <module>
    from app.features import category_history_score, expertise_score, skill_score
E   ImportError: cannot import name 'category_history_score' from 'app.features'
ERROR tests/test_features_v2.py
1 error in 1.42s
```

Focused run after implementation:

```
$ python -m pytest tests/test_features_v2.py -v
collected 3 items

tests/test_features_v2.py::test_skill_uses_required_skill_weights PASSED [ 33%]
tests/test_features_v2.py::test_no_required_skills_does_not_return_one PASSED [ 66%]
tests/test_features_v2.py::test_expertise_uses_certification_and_semantic PASSED [100%]

3 passed in 0.03s
```

Full suite:

```
$ python -m pytest tests/ -q
196 passed in 14.82s
```

Additional ad-hoc sanity check confirmed:
- `candidate_features` returns exactly the seven original keys.
- All values are within `[0, 1]` and non-NaN for a worker with category
  history, both with the default semantic prior and `semantic_similarity=1.0`.
- NaN `semantic_similarity` degrades safely to the `0.5` neutral prior.

## Files Changed

- `app/features.py` (modified)
- `tests/test_features_v2.py` (created)
- `.superpowers/sdd/recommendation-improvement/task-10-report.md` (this report)

No other files modified. No git commands run (directory is not a git
repository), no commits created.

## Self-Review Findings

1. **`compute_reputation(...).rating` normalization mismatch.** The brief
   assumes `rating` is 0-5, but `app/reputation.py` already divides the
   Bayesian rating by 5, so it is 0-1. Initial implementation divided by 5
   again and failed `test_expertise_uses_certification_and_semantic`
   (obtained 0.652 vs expected 0.82). Fixed by using the normalized rating
   directly as the shrinkage prior; category means are still normalized via
   `/5`. The resulting math matches the spec once the scale difference is
   accounted for.
2. **`category_history_score` signature.** The brief lists
   `category_history_score(worker) -> float` but the formula and the
   `expertise`/`skill` formulas require a category. Implemented as
   `category_history_score(worker, category=None)`; the one-argument call in
   the test works and returns the global prior.
3. **`skill_score` no-required-skills path** passes `task.category` to
   `category_history_score` because spec §8.3 defines category history per
   task category. The test computes its expectation with the one-argument
   form, which is identical for that worker (no `category_ratings`), so the
   test passes.
4. **Division-by-zero / NaN guards.** Empty weight totals return `0.0`;
   NaN semantic similarity maps to `0.5`; every returned score is clamped.
5. Existing `tests/test_features.py` expectations (`skill_score` 1.0 / 0.0
   with a required skill) still hold.

## Concerns

- The `compute_reputation().rating` scale mismatch between the spec text
  (0-5) and the existing implementation (0-1) is documented above; future
  tasks referencing a 0-5 `rating` should be aware of it.
- `skill_score`'s no-required-skills fallback deliberately uses the task's
  category for its history term, which is slightly more specific than the
  literal one-argument call shown in the brief/test, but is required by
  spec §8.3 semantics. Behavior is identical wherever the worker has no
  category ratings.
- `_recent_breach_count` remains imported but unused in `app/features.py`
  (pre-existing; left untouched to keep the diff scoped).
