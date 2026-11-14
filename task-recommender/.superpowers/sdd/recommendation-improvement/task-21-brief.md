## Task 21: Large Natural-Language Benchmark (scheme E)

**Goal:** Generate 10,000 realistic natural-language tasks and 1,000 natural-language worker resumes with no exact or near duplicates, plus 100,000 historical assignments, 80/20 split, SQLite + JSONL, and a sampled evaluation report.

**Scheme E:** A (template slots + sentence variants) for 80–90% of records, B (latent DGP) for assignments/accept/rating/ground truth, C (optional LLM seed JSON) off by default, D (real corpus) not required.

**Files:**
- Create: `app/data/large_synthetic.py`, `scripts/build_large_benchmark.py`, `app/benchmark/large.py`
- Test: `tests/test_large_synthetic.py`, `tests/test_large_benchmark.py`
- Outputs: `data/benchmark/task_benchmark_large.sqlite`, `data/benchmark/task_benchmark_large.jsonl`, `reports/large_benchmark_stats.md`, `reports/large_benchmark_eval.md`

**Interfaces:**
- `generate_large_dataset(n_workers=1000, n_tasks=10000, n_assignments=100000, seed=42) -> Dataset` with `task_text` and `resume_text` natural-language fields.
- `normalized_text_hash(text) -> str`, `simhash64(text) -> int`, `is_near_duplicate(a: str, b: str, max_hamming: int = 3) -> bool`.
- `build_large_sqlite(dataset, path) -> None`, `load_large_sqlite(path) -> Dataset`.
- `evaluate_large(path, test_tasks=500, candidates=200, seeds=(42,43,44,45,46)) -> dict`.

**Tasks:**
- 21a: natural-language task/resume generator (A) with unique titles, sentence variants, category/industry quotas, and a `--llm-seeds PATH` optional JSON hook (C, default off).
- 21b: latent DGP (B) for assignments, accept/reject, ratings, and ground truth; 80/20 task split; train-only worker history.
- 21c: dedup (exact hash + unique title + simhash near-duplicate) and SQLite/JSONL export with a stats report (duplicate rate, category/industry/budget/duration distributions, text lengths, resume completeness).
- 21d: sampled evaluation (500 test tasks × 200 candidates × 5 seeds) and report; wire ItemCF into the large benchmark and normalize collaborative scores across the candidate pool. **The ItemCF similarity graph must be built from train-split accepted assignments only; test-task co-occurrences must not enter it.** Add a leakage regression test asserting a test-split assignment cannot change `item_users`/`item_similarity` or a test-task score. Model-facing loaders/JSONL must expose only train-split outcomes; test outcomes are evaluator-only. Document the gold definition (latent-best in a 10-worker exposure pool), its acceptance rate, and add a feature-only/exposure-pool baseline; qualify any random-baseline comparison. Resume project results and certificates must be category-consistent, with a coherence test.

**Acceptance:** 10,000 unique task texts, 1,000 unique resume texts, exact-duplicate rate = 0, near-duplicate rate < 0.5%, all natural-language fields non-empty, 100,000 assignments, 80/20 split, sampled evaluation report with Top-1/Top-5/MRR/NDCG and a data-quality section.

---

