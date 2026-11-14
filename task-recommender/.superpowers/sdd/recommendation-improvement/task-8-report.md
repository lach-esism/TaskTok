# Task 8 Report: `project_weights_with_report`

## Status

DONE

## What was implemented

Refactored `app/learning/weights.py` so the simplex projection can report which constraints bind:

- Added frozen dataclass `WeightBindingReport` with fields:
  - `reputation_hit_low: int`
  - `reputation_hit_high: int`
  - `min_hits: dict[str, int]`
  - `iterations: int`
- Added `project_weights_with_report(weights: dict[str, float]) -> tuple[dict[str, float], WeightBindingReport]`, containing the former `project_weights` projection logic unchanged.
- Counters:
  - `reputation_hit_low` = 1 when raw `reputation` is strictly below `REPUTATION_MIN` before clamping.
  - `reputation_hit_high` = 1 when raw `reputation` is strictly above `REPUTATION_MAX` before clamping.
  - `min_hits` maps every one of the seven dimensions to 1 when its final projected value is at `MIN_WEIGHT` (within `1e-9`), else 0.
  - `iterations` is set to 1 per call, per the brief ("Increment `iterations` once per call").
- `project_weights(weights)` now delegates: `return project_weights_with_report(weights)[0]`, keeping its behavior identical.

## TDD sequence

1. Created `tests/test_weight_binding.py` with the two tests from the brief.
2. Ran `python -m pytest tests/test_weight_binding.py -v`: failed with
   `ImportError: cannot import name 'project_weights_with_report' from 'app.learning.weights'`.
3. Implemented the report and refactor.
4. Ran focused tests: 2 passed.
5. Ran full suite: 184 passed.

## Tests run and output

```
$ python -m pytest tests/test_weight_binding.py -v
tests/test_weight_binding.py::test_projection_reports_reputation_high_bound PASSED
tests/test_weight_binding.py::test_projection_reports_min_weight_hits PASSED
2 passed in 0.03s
```

Focused regression run including existing projection tests:

```
$ python -m pytest tests/test_weight_binding.py tests/test_weight_math.py -v
9 passed in 0.05s
```

Full suite:

```
$ python -m pytest tests/ -q
184 passed in 14.74s
```

## Files changed

- `app/learning/weights.py` (modified: added `dataclass` import, `WeightBindingReport`, `project_weights_with_report`; `project_weights` is now a delegating wrapper)
- `tests/test_weight_binding.py` (created, contains the two brief tests verbatim)
- `.superpowers/sdd/recommendation-improvement/task-8-report.md` (this report)

No other files were modified. No git commands were run.

## Self-review findings

- `project_weights` behavior is preserved: its body was moved verbatim into `project_weights_with_report`; all pre-existing projection tests (floors, all-zero input, idempotence, reputation-largest, reviewer repro, fuzz invariants) still pass.
- `min_hits` was initially sparse (only dimensions at the floor). It was changed to include all seven keys with 0/1 counts so it is a true per-dimension counter map; the test uses `.get(..., 0)` so both forms pass, and the full map is more useful for the later `GET /weights/binding` JSON endpoint.
- Floor detection uses the final projected values rather than instrumenting `_allocate_capped`. This catches both the minimum baseline allocated in `_allocate_capped` and any dimension pushed to the floor by the end-of-function normalization correction, which a single internal code path check would miss.
- Clamp comparison is strict (`< REPUTATION_MIN`, `> REPUTATION_MAX`), matching the actual clamping condition `min(MAX, max(MIN, raw))`; no hit is reported when the raw value equals a bound exactly.
- Dataclass fields have defaults (with `default_factory=dict` for `min_hits`) so accidental bare construction is safe and later serialization with `dataclasses.asdict` works.
- Formatting follows the file's existing style; no new dependencies introduced.

## Concerns

- `iterations` is always 1 because the brief explicitly says to increment it once per call. It does not measure inner allocation-loop iterations; if later tasks expected a loop count, that would need a separate counter.
- `min_hits` counts a dimension whose input happens to be exactly `MIN_WEIGHT` in the fast path as a hit, even though no explicit clamping occurred. This matches "allocated at `MIN_WEIGHT`" but is slightly broader than "clamped upward to `MIN_WEIGHT`".
- `min_hits` semantics are 0/1 indicators, not cumulative counts; within a single call a dimension can bind at most once, so this is equivalent for current use, but the field name allows future expansion.
