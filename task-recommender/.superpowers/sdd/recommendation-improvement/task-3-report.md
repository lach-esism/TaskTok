# Task 3 Report: Synthetic New Fields and Train/Test Feedback Split

## Status

DONE

## What Was Implemented

All changes are in `app/data/synthetic.py` (`generate_dataset`) and
`tests/test_synthetic.py`.

### Worker fields (main worker loop)

- `expected_pay`: uses the first specialty category's
  `TASK_PROFILES[category]["budget"]` midpoint multiplied by
  `rng.uniform(0.7, 1.3)`, rounded to 2 decimals. The brief's no-specialty
  fallback `rng.uniform(2000, 12000)` is present defensively; with
  `rng.sample(CATEGORIES, k=rng.randint(1, 3))` specialties are never empty.
- `certifications`: per specialty category,
  `0.8 if rng.random() < 0.3 else 0.5 if rng.random() < 0.4 else 0.0`
  (conditional-expression short-circuit keeps the 0.3 / 0.7*0.4 / remainder
  probabilities exact).
- Both are passed to the `Worker(...)` constructor.

### New-user worker fields

The new-user loop also creates `Worker` instances inside `generate_dataset`,
so `expected_pay` and `certifications` are populated there with the same
formulas, driven by `new_rng`. These assignments happen *after* the existing
`Worker(...)` construction so the pre-existing `new_rng` draw sequence for
skills/specialties/level/capacity/region/remote_ok is byte-for-byte unchanged.
`communication_ratings` stays empty for new users (they have no history), as
with `ratings`.

### Task fields

- `required_skill_weights = {skill: 1.0 for skill in required_skills}` on every
  generated `Task`, so the key set always equals `required_skills`.

### Feedback and train-only communication ratings

- Inside the existing 0.7-probability feedback branch, with probability 0.5
  compute
  `communication_rating = int(round(clamp(quality * 5 + rng.uniform(-0.5, 0.5), 1, 5)))`
  and set it on the `Feedback` (remainder stay `None`). At generation time the
  value is also appended to `worker.communication_ratings`, mirroring
  `worker.ratings`.
- In the post-generation aggregate reset block, `worker.communication_ratings`
  is cleared alongside `ratings`, `completed`, `on_time`, `rework_count`,
  `breach_dates`, `category_ratings`, then repopulated *only* inside the
  `if item.assignment_id in train_assignment_ids` feedback loop (appended as
  `float(item.communication_rating)`). This matches the existing train-only
  rule for `ratings` and `category_ratings`; test feedback cannot leak in.

No ground-truth CSV or benchmark labels are read. No new dependencies.
No files outside `app/data/synthetic.py` and `tests/test_synthetic.py` were
modified. No git commands were run.

## Tests Run

1. Tests appended first, before implementation:
   `python -m pytest tests/test_synthetic.py -v`
   Result: 1 failed, 6 passed. `test_synthetic_new_fields_are_populated` failed
   at `assert all(worker.expected_pay > 0 ...)` (`expected_pay` was still the
   0.0 default). `test_train_and_test_feedback_are_disjoint` already passed
   because `Dataset.train_feedback` / `test_feedback` from Task 1 partition the
   feedback by assignment membership.

2. After implementation:
   `python -m pytest tests/test_synthetic.py -v`
   Result: `7 passed in 1.38s`.

3. Full suite:
   `python -m pytest tests/ -q`
   Result: `166 passed in 10.31s`.

4. Manual invariant check (`python -c`, no files created), seed=3,
   n_workers=30, n_tasks=60, n_assignments=200, n_new_users=5:
   - `worker.communication_ratings` equals, per worker, the multiset of
     `communication_rating` values from `dataset.train_feedback` only
     (54 train communication ratings observed; 28 feedback items landed in
     `test_feedback`, and none influenced worker aggregates).
   - Every task's `required_skill_weights` keys equal `required_skills` keys
     with all weights `1.0`.
   - All main and new-user workers have `expected_pay > 0` and
     `certifications` keyed exactly by their `specialties`.
   - Two runs with the same seed produce identical `expected_pay`,
     `certifications`, and `communication_ratings` lists (determinism).

## Files Changed

- `app/data/synthetic.py`
- `tests/test_synthetic.py` (appended, verbatim from the brief, the duplicate
  `from app.data.synthetic import generate_dataset` import plus 2 tests)

## Self-Review Findings

- The new `rng` draws in the main worker loop shift the downstream random
  sequence relative to pre-change datasets, so sample values for a given seed
  differ from before. The determinism contract (same seed -> identical
  dataset) is preserved, and all pre-existing tests (including candidate-pool
  size, realistic-posting, and title-diversity assertions) pass unchanged.
- Worker aggregate reset/repopulation order is unchanged: the reset clears
  `communication_ratings` before the single train-feedback pass repopulates it.
- Communication gating uses one `rng.random() < 0.5` draw per emitted feedback
  record, exactly as specified; the `quality * 5` scale (not `1 + 4*quality`)
  follows the brief.
- `Feedback.communication_rating` remains `int | None`; worker-level list is
  appended as `float` in the train pass for type consistency with
  `list[float]`. The initial (pre-reset) append stores the int value, which
  is discarded by the reset and is numerically identical anyway.
- The appended test file repeats the `generate_dataset` import mid-module
  because the brief specifies the snippet verbatim; harmless, and pytest
  collects 7 tests.
- No side effects on `fix_*`, benchmark, or learning code paths; the only
  behavioral change is populated fields plus the deterministic sequence shift
  noted above.

## Concerns

- Non-blocking: the brief's Step 3 describes worker creation in the main
  loop; I also populated `expected_pay`/`certifications` for `new_users`,
  interpreting "when creating each Worker" broadly. This is untested by the
  brief's tests and could be reverted if the intent was main-loop-only, though
  it prevents cold-start workers from carrying an `expected_pay` of 0.
- Non-blocking: because new `rng` calls were inserted before the existing
  `level`/`capacity`/`preferred_categories`/`region` draws, values for a fixed
  seed differ from the pre-Task-3 dataset. No test pins exact values and
  seed-to-seed determinism holds.

---

# Fix Report (Review Follow-up)

## What Was Fixed

1. **Important — certification distribution.** The previous conditional used
   two sequential draws, yielding P(0.8)=0.30, P(0.5)=0.28, P(0)=0.42. The
   helper now draws one uniform per category and maps
   `0.8 if r < 0.3 else 0.5 if r < 0.7 else 0.0`, giving exactly
   P(0.8)=0.3, P(0.5)=0.4, P(0)=0.3.
2. **Minor — DRY.** Added
   `_sample_pay_and_certifications(rng, specialties) -> tuple[float, dict[str, float]]`
   in `app/data/synthetic.py` (next to `_realistic_task_fields`). Both the main
   worker loop and the new-user loop now call it; no duplicated pay or
   certification logic remains. The `expected_pay` formula is unchanged
   (`TASK_PROFILES[first_specialty]["budget"]` midpoint × `uniform(0.7, 1.3)`,
   rounded to 2 decimals; `uniform(2000, 12000)` fallback retained). The
   new-user call still occurs after `Worker(...)` construction, so the
   existing `new_rng` draw sequence for skills/specialties/level/capacity/
   region/remote_ok is unchanged.
3. **Minor — regression tests.** Appended to `tests/test_synthetic.py`:
   - `test_certification_values_are_limited_to_expected_levels`: every worker's
     certification keys equal its specialty keys and every value is in
     `{0.0, 0.5, 0.8}`.
   - `test_expected_pay_matches_specialty_budget_formula`: for every worker,
     `expected_pay` lies in `[0.7, 1.3] ×` the `TASK_PROFILES` midpoint of the
     worker's first specialty and is rounded to 2 decimals (no hard-coded
     amount).
   - `test_communication_ratings_are_train_only`: per worker, the sorted
     `worker.communication_ratings` multiset equals the sorted
     `communication_rating` values from `dataset.train_feedback` for that
     worker only (mirrors `test_worker_aggregates_are_train_only`).
4. **Minor — float append.** The generation pass now appends
   `float(communication_rating)` to `worker.communication_ratings`, matching
   the `list[float]` annotation and the train-pass append.

### Parked (not changed, per review)

- Duplicate `from app.data.synthetic import generate_dataset` import in
  `tests/test_synthetic.py` (kept as the brief's verbatim snippet).
- The unreachable no-specialty `expected_pay` fallback branch (kept; it is the
  brief's specified guard).

## Tests Run

1. Focused:
   `python -m pytest tests/test_synthetic.py -v`
   Result: `10 passed in 1.42s` (5 pre-existing + 2 brief tests + 3 new
   regression tests).
2. Full suite:
   `python -m pytest tests/ -q`
   Result: `169 passed in 10.60s`.
3. Manual distribution/invariant probe (`python -c`, seed=11, n_workers=100,
   n_new_users=20): certification value frequencies `{0.0: 0.283, 0.5: 0.401,
   0.8: 0.316}` (≈0.3/0.4/0.3), all values in `{0.0, 0.5, 0.8}`, all main and
   new-user workers have non-empty `certifications`, and all have
   `expected_pay > 0`.

## Files Changed

- `app/data/synthetic.py`
- `tests/test_synthetic.py`

## Self-Review Findings

- Helper uses `next(iter(specialties), None)`; dict insertion order preserves
  the sampled order, so "first specialty" remains identical to the previous
  `chosen_specialties[0]` behavior.
- Single-draw certification probabilities verified empirically (~0.3/0.4/0.3)
  and structurally in the helper.
- Both worker-creation paths call the same helper; no residual duplicated
  logic.
- `communication_ratings` is still cleared in the aggregate reset and rebuilt
  only from `train_feedback`; the new train-only multiset test passes.

## Concerns

- None blocking. The only remaining parked items are listed above.
