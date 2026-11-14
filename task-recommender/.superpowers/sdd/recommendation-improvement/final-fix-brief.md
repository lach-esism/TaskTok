# Final Review Fix Brief

Spec: `docs/superpowers/specs/2026-11-13-recommendation-improvement-design.md`
Plan: `docs/superpowers/plans/2026-11-13-recommendation-improvement.md`
Ledger: `.superpowers/sdd/recommendation-improvement/progress.md`
Final review verdict: **Ready to merge? With fixes.**

Address the Critical and Important findings below in one consolidated fix wave. Keep the Minor items parked unless a fix is trivial. Do not retry `opus` (API 402); use the existing stack. Run the full suite and the affected scripts; report honestly if the MET target changes.

## Critical

1. **PDF expansion is unbounded before parse (upload DoS).**
   `app/upload/extract.py:222-255` checks `%PDF-`, encryption, and page count, then calls `page.extract_text()` and only checks `MAX_EXTRACTED_CHARS` after each page. A crafted PDF can decompress a huge stream before the check. Fix: inspect PDF stream objects (declared/decoded sizes) and reject over a bound before extraction, or parse in a subprocess/RSS-limited worker; add a Flate-bomb regression test analogous to the DOCX one.

## Important

1. **Strict-eval/tuning evidence does not use serving features.**
   `app/evaluation_strict.py:744-749` and `scripts/tune_weights.py:147,210` build services with weights only (`semantic_matcher=None`, `acceptance_model=None`), while `create_app` injects both. Fix: build a train-only `SemanticMatcher` (fit on train worker/task text) and `AcceptanceModel` per seed, inject into baseline, candidate, and validation services; re-run `scripts/tune_weights.py` and the 5-seed strict evaluation; update `reports/strict_eval_tuned.*`. If the target is no longer MET under serving-parity features, report that honestly and do not claim success.
2. **Event ingestion trusts client target labels.**
   `app/events.py:112-124`, `app/main.py:1489-1494`, `app/main.py:1035-1060` read `candidate_type`/`task_id` from free-form client metadata. Derive them from the impression; allow a client field only if it matches; reject mismatches; allowlist metadata keys. Validate `/assignments` auto-accept against the impression (worker-type: task_id == impression.query_id; task-type: worker_id == impression.query_id) and use the impression’s role/user.
3. **The shipped frontend never uses `request_id` or `/events`.**
   `frontend/app.js:1744-1761` posts `/assignments` without `recommendation_context.request_id`; there are zero `request_id`/`/events` references. Retain `request_id` per recommendation result, pass it on adopt, and post at least the `accept` action (plus click/apply/reject buttons if practical). Add a test/demo proving a UI adopt produces an accept event.
4. **The tuned accuracy result is not active and docs reproduce the NOT MET report.**
   `data/weights/active.json` is `v0000`; `weights_choice.json` is not a WeightStore version; README/flow command uses `weights_v0007.json` which produced `NOT MET`. Create a version from `weights_choice.json`, activate it (or add an explicit activation command), document `scripts/tune_weights.py` + `reports/strict_eval_tuned.md` as canonical, and make the docs command reproduce the tuned evidence.
5. **Event persistence/ingestion is O(n²) and `/events` is unbounded.**
   `app/events.py:32-58,100-107`, `app/data/store.py:68-79,101-125`, `app/schemas.py:52-53`, `app/service.py:252-260`: `_persist` scans the whole JSONL per append, `record_event` scans all events, `reference_time`/`recent_impression_counts` scan history per request, batch/metadata are uncapped, and persisted logs are not loaded on startup. Fix: in-memory line counters + duplicate-key set (or SQLite), cap batch size/metadata/request body, load persisted logs on startup or document them audit-only; add a large-batch test.
6. **Per-request service/ItemCF rebuild; latency guardrail unmeasured.**
   `app/service.py:79-99`, `app/main.py:1522-1527` (and routes), `app/evaluation_strict.py:660-685`: cache one `RecommendationService` in `app.state`, invalidate on assignment/event/feedback/recompute; measure actual `/recommend/*` endpoint latency or mark the 2× guardrail N/A and stop presenting in-process scoring time as endpoint latency.
7. **Semantic text caches unbounded on untrusted uploads.**
   `app/semantic.py:67-69,397,418,428,444`: bound/evict `_WORKER_TEXT_CACHE`/`_TASK_TEXT_CACHE` (or scope to Store) and clear on data refresh/feedback; add a test.
8. **Live feedback never updates `communication_ratings`.**
   `app/feedback.py:75-118`, `app/features.py:265-271`, `app/service.py:127-131`: append `communication_rating` to `worker.communication_ratings` in `FeedbackService.record_feedback` (keep synthetic train-only behavior); add an API test showing the feature changes.
9. **README/flow docs are stale and omit final work.**
   `README.md:49,54,98,180`, `docs/recommendation-flow.md:170,304,445,508`: update the test count (360), upload/NLP/large-benchmark/tuned sections, the canonical tuned command, active weights, the fact that the 1,000-task benchmark `collaborative` remains 0 while the large benchmark is strict train-only, and strengthen `tests/test_docs.py` to assert current claims.

## Parked Minors (do not block unless trivial)

Funnel denominators/rank buckets; missing `GET /evaluation/strict`, `GET /config/semantic`, `scripts/simulate_events.py`, `reports/strict_eval_queries.csv`; 80/20 vs 70/15/15; exposure-fairness saturation; semantic text staleness after feedback; CRF pickle safety; event score null coercion; upload sections volume/CPU offload; 10 MB multipart overhead/413 vs 422; upload `request_id` without impression; global `MultiPartParser` mutation; binding per-update counts/unguarded write; leakage static/runtime tests; test `events_dir` cleanup; docs test token-only.

## Constraints

- No git commands; no new required dependencies.
- Do not retry `opus`.
- Run `python -m pytest tests/ -q`; run `scripts/tune_weights.py` and the 5-seed strict eval for the parity change; update reports.
- Write a full report to `.superpowers/sdd/recommendation-improvement/final-fix-report.md` with: each finding fixed/not fixed, tests/commands/output, new strict metrics/target status, risks, and remaining work.
- Reply with ONLY: Status, files changed, one-line test summary, target status/metrics, remaining findings, report path.
