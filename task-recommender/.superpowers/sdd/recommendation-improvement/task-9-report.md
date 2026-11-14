# Task 9 Report: SemanticMatcher

## Status

DONE_WITH_CONCERNS (implementation complete and all tests pass; deferred items noted below).

## What was implemented

Created `app/semantic.py` with:

- `SemanticMatcher(provider="tfidf_svd", model=None, cache_dir=None, random_state=42)`
  - `fit(worker_texts, task_texts) -> SemanticMatcher`
  - `similarity(task_text, worker_text) -> float`
  - `similarity_batch(task_text, worker_texts) -> list[float]`
  - read-only `provider` and `fit_count` properties, plus `is_fitted`
- `tfidf_svd` provider: `TfidfVectorizer(analyzer="char", ngram_range=(2,4), min_df=2, sublinear_tf=True)` fitted on the union of worker/task texts, `TruncatedSVD(n_components=min(128, max(2, n_docs-1)), random_state=random_state)`, L2-normalized embeddings, cosine via dot product clamped to `[0, 1]`.
- `disabled` provider: always returns the neutral prior `0.5`.
- `sentence_transformer` provider: lazy import of `sentence_transformers.SentenceTransformer`; model load deferred until the first encode; `encode(..., normalize_embeddings=True, convert_to_numpy=True)`; cosine clamped to `[0, 1]`. On `ImportError` (and `OSError` while loading/encoding) the provider falls back to `tfidf_svd`.
- In-memory pair cache `_cache: dict[tuple[str, str], float]`, cleared on `fit`. `fit_count` increments only inside `fit`. Embeddings for fitted texts are precomputed; unseen texts are transformed/encoded on demand and memoized.
- `build_matcher(provider=None)`: reads `SEMANTIC_PROVIDER`, `SEMANTIC_MODEL`, `SEMANTIC_CACHE_DIR` from `app.config` via `getattr` (so a later config task can add them without touching this file), then defaults to `tfidf_svd`.
- `build_worker_text(worker)`: calls `app.resume.build_resume(worker)` and joins only resume-surface fields: `headline`, `city`, `skills`, project name/role/bullets, and `certifications`. `summary`, `stats`, and `platform_data` are excluded.
- `build_task_text(task)`: joins title, description, and requirements with `。` (empty segments collapse rather than producing doubled separators).

Created `tests/test_semantic.py` with the three brief tests verbatim plus four focused extras: batch/single consistency without refitting, the sentence-transformer path via a fake `sys.modules` encoder, resume-surface-only worker text, and task text joining.

## Files changed

- `app/semantic.py` (new)
- `tests/test_semantic.py` (new)

`diff -rq` against the task-8 snapshot confirms no other project files changed. No git commands were run.

## Tests run and output

Step 2, before implementation:

```
$ python -m pytest tests/test_semantic.py -v
...
E   ModuleNotFoundError: No module named 'app.semantic'
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

After implementation:

```
$ python -m pytest tests/test_semantic.py -v
collected 7 items
tests/test_semantic.py::test_tfidf_svd_similarity_is_bounded_and_deterministic PASSED [ 14%]
tests/test_semantic.py::test_disabled_provider_returns_half PASSED       [ 28%]
tests/test_semantic.py::test_sentence_transformer_falls_back_when_missing PASSED [ 42%]
tests/test_semantic.py::test_similarity_batch_matches_single_and_does_not_refit PASSED [ 57%]
tests/test_semantic.py::test_sentence_transformer_provider_encodes_when_available PASSED [ 71%]
tests/test_semantic.py::test_worker_text_uses_resume_surface_without_internal_stats PASSED [ 85%]
tests/test_semantic.py::test_task_text_joins_title_description_and_requirements PASSED [100%]
============================== 7 passed in 0.06s ==============================
```

Full suite:

```
$ python -m pytest tests/ -q
191 passed in 14.71s
```

Focused tests also pass under `-W error`:

```
$ python -m pytest tests/test_semantic.py -q -W error
7 passed in 0.07s
```

## Self-review findings

1. **Degenerate corpora.** The literal brief formula (`min_df=2`, `n_components=min(128, max(2, n_docs-1))`) raises on tiny corpora: TF-IDF can produce zero or one feature, and `TruncatedSVD` requires at least two features. Fixed by retrying TF-IDF with `min_df=1` when the vocabulary has fewer than two features, clamping `n_components` to the feature count, and leaving the matcher unfitted (neutral `0.5`) when fewer than two documents exist. Normal corpora use exactly the brief's parameters.
2. **sklearn warning.** Degenerate corpora make `TruncatedSVD` divide by zero in `explained_variance_ratio_`. The components themselves are finite; the warning is suppressed locally to keep logs clean. Verified with `-W error::RuntimeWarning` and explicit NaN checks.
3. **Sentence-transformer fallback.** Import happens in the constructor (so `build_matcher()` reports the effective provider immediately) but model loading/encoding is deferred. Fallback sets `provider = "tfidf_svd"` as required. `OSError` during model load/encode is treated as unavailable in addition to `ImportError`.
4. **Blank/unfitted inputs.** Blank text and an unfitted TF-IDF matcher return `0.5` rather than raising, matching the service's "unavailable = neutral prior" contract.
5. **Unknown provider.** Silently falls back to `tfidf_svd` for config resilience instead of raising.
6. **Determinism.** Two independently constructed matchers with the same corpus and `random_state=42` produced identical scores; all sampled scores were bounded and non-NaN.
7. **Leakage check.** `app/semantic.py` imports only numpy/sklearn plus `app.config`, `app.domain`, and `app.resume`; no ground-truth/label reads, no generative LLM, no required `sentence-transformers` dependency.

## Concerns / deferred items

- **Persistent embedding cache.** Design §9.3 describes a `sha256(provider + model + text)` disk cache under `SEMANTIC_CACHE_DIR`; the Task 9 brief only specifies the in-memory `_cache`, so disk persistence was not implemented. `cache_dir` is currently forwarded to `SentenceTransformer(cache_folder=...)` and otherwise reserved.
- **Task text category.** Design §9.3 lists `category` in the task text; the Task 9 brief's exact formula omits it, so `build_task_text` omits it. Followed the brief.
- **Worker-text cost.** `build_worker_text` calls `build_resume` on every invocation. Task 13's per-candidate call path should cache built texts (or precompute vectors) if resume generation shows up in latency; the pair cache only helps after texts are built.
- **Optional-provider coverage.** The real `sentence-transformers` path was exercised only through a fake module because the package is intentionally not a dependency; model download behavior is untested.
- **Config constants.** `SEMANTIC_PROVIDER` / `SEMANTIC_MODEL` / `SEMANTIC_CACHE_DIR` are not added to `app/config.py` (outside this task's file scope). `build_matcher` picks them up automatically once a later task adds them.

## Fix round 1 (coordinator-requested)

Updated brief re-read: `build_task_text` now includes `category`, and both text builders must cache by ID. Final status after this round: **DONE**.

Changes:

1. `build_task_text` now joins `title`, `description`, requirements, and `category` with `。`. Output for the test task is `设计登录页。需要响应式设计。熟悉 Figma。有 B 端经验。ui_ux_design`.
2. Added module-level `_WORKER_TEXT_CACHE: dict[str, str]` and `_TASK_TEXT_CACHE: dict[str, str]`, keyed by `worker_id` / `task_id`. Repeated candidate scoring reuses the built text instead of calling `build_resume` again. Inputs are documented as static for the duration of a run.
3. Added `clear_text_caches()` (also exported in `__all__`) so tests and long-running processes can invalidate after a data refresh.
4. Tests added/updated:
   - `test_task_text_joins_title_description_requirements_and_category`
   - `test_task_text_varies_with_category` (asserts different categories produce different text)
   - `test_text_builders_cache_by_id_until_cleared` (mutation under the same ID stays memoized; `clear_text_caches()` rebuilds)

Resolved by ruling:

- Persistent sha256 disk embedding cache (design §9.3) is explicitly deferred as a performance follow-up; the in-memory pair cache is sufficient at this scale.
- `SEMANTIC_*` config via `getattr` defaults is accepted; Task 13/18 may add constants to `app.config`.
- The fake-module test for the optional `sentence-transformers` path is accepted coverage.

Files changed remain only:

- `app/semantic.py`
- `tests/test_semantic.py`

Commands and output:

```
$ python -m pytest tests/test_semantic.py -v
collected 9 items
test_tfidf_svd_similarity_is_bounded_and_deterministic PASSED
test_disabled_provider_returns_half PASSED
test_sentence_transformer_falls_back_when_missing PASSED
test_similarity_batch_matches_single_and_does_not_refit PASSED
test_sentence_transformer_provider_encodes_when_available PASSED
test_worker_text_uses_resume_surface_without_internal_stats PASSED
test_task_text_joins_title_description_requirements_and_category PASSED
test_task_text_varies_with_category PASSED
test_text_builders_cache_by_id_until_cleared PASSED
============================== 9 passed in 0.10s ==============================
```

```
$ python -m pytest tests/ -q
193 passed in 14.76s
```

Focused tests are also clean under warnings-as-errors:

```
$ python -m pytest tests/test_semantic.py -q -W error
9 passed in 0.07s
```
