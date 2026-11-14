# Final Review Fix Wave — Report

- Date: 2026-11-14
- Branch scope: recommendation-improvement final whole-branch review
- Brief: `.superpowers/sdd/recommendation-improvement/final-fix-brief.md`
- Status: **DONE_WITH_CONCERNS** (all Critical/Important fixed; a few accepted limitations and parked minors remain)
- Accuracy target under serving-parity features: **MET**

---

## 1. Summary

All one Critical and nine Important findings were addressed. The evaluation and
tuning paths now fit and inject the same `SemanticMatcher` / `AcceptanceModel`
that `create_app` serves, using train-only stores. `scripts/tune_weights.py` was
re-run for seeds 42–46 and the tuned weights were activated as WeightStore
**v0008**; `reports/strict_eval_tuned.*` and `reports/strict_eval.*` were
regenerated. The strict target remains **MET** under serving parity.

Full suite: **392 passed in 46.15s** (after all post-review C1 corrections; see §3.3).

Trivial parked minors fixed while touching the same code: event `score`
null/non-numeric coercion, persisted event logs explicitly documented as
audit-only, and endpoint-vs-scoring latency naming. The remaining parked minors
are listed in §7.

---

## 2. Finding-by-finding status

### Critical

| # | Finding | Status | Fix / evidence |
|---|---|---|---|
| C1 | PDF expansion unbounded before parse (upload DoS) | **FIXED (corrected three times after re-review)** | `app/upload/extract.py` inspects pypdf's **object model** before `extract_text()`: it resolves page `/Contents`, `/Resources` (including `/XObject` forms/patterns), fonts, and `/Annots` appearance streams, following indirect references. `/Filter` aliases (`/Fl`), indirect `/Filter 5 0 R`, and arbitrarily long dictionary-to-`stream` gaps are resolved. An **iterative worklist** (no depth cap below pypdf's 5,000-nested-Form traversal; visited objects capped at 50,000, streams at 5,000) follows nested Form XObjects at any depth **and follows stream `/Parent`** to mirror pypdf's `get_inherited('/Resources')` lookup, so inherited parent resources cannot hide a stream; cycles are safe via the visited map. Flate streams are decoded with `zlib.decompressobj().decompress(raw, MAX_PDF_STREAM_BYTES + 1)`; overflow (`>32 MB`), `unconsumed_tail`, `unused_data`, multiple filters, unsupported filters, and total decoded size (`>64 MB`) all raise a clear 422 before any `page.extract_text()`. Regression tests: `/Fl`, indirect `/Filter`, 9 KB dictionary gap, 5th-level and 20th-level nested Form XObject bombs, `/Parent`-inherited Form resources, ~40 MB expansion, fail-closed stream/object caps, and unsupported/multiple filters; empty/fake-reader and optional-dependency paths still pass. |

### Important

| # | Finding | Status | Fix / evidence |
|---|---|---|---|
| I1 | Strict-eval/tuning evidence did not use serving features | **FIXED** | New `app/serving.py` owns `build_semantic_matcher`, `build_acceptance_model`, `build_serving_components`, and `serving_components` (fit-once-per-store cache). `app/evaluation_strict.evaluate_strict` fits both components per seed from the train-only store and injects them into baseline + candidate services; result JSON carries `serving_features.parity="serving"`. `scripts/tune_weights.py` now uses `service.features_for` for rating records, choice-event features, and validation/coordinate-search services, with the components fitted once per fit store. Tune + 5-seed strict eval re-run; see §4. Tests: `test_evaluate_strict_injects_serving_components`, `test_build_serving_components_fits_train_only_store`, `test_tuning_services_use_serving_parity_components`. |
| I2 | Event ingestion trusted client target labels | **FIXED** | `EventService.record_event` derives `candidate_type`/`task_id` from the impression, accepts client fields only when they match, rejects mismatches (`ValueError` → 409 at the API), and filters metadata to an allowlist (`candidate_type`, `task_id`, `score`, `weights_version`). `/assignments` auto-accept now validates worker-type `task_id == impression.query_id` / task-type `worker_id == impression.query_id`, requires the candidate to be in the impression, and uses the impression's role/user. Tests: `test_event_labels_come_from_impression_and_mismatches_are_rejected`, `test_task_impression_derives_task_label_without_client_input`, `test_events_reject_mismatched_target_labels_and_drop_extra_metadata`, `test_worker_assignment_records_accept_only_for_matching_impression`. |
| I3 | Frontend never used `request_id` or `/events` | **FIXED** | `frontend/app.js` retains `data.request_id` per recommendation, passes it to `renderCandidates`, posts `click` (card head), `apply` (adopt), and `reject` (“不感兴趣”) through a new `postRecommendationEvent`, and includes `request_id` in `recommendation_context` on adopt. The server-side auto-accept then records `accept`. `frontend/styles.css` adds the action row/rejected state. Tests: `test_frontend_recommendation_flow_uses_request_id_and_events`, plus the UI-payload accept test (`test_worker_assignment_records_accept_only_for_matching_impression`). |
| I4 | Tuned accuracy result not active; docs reproduced NOT MET | **FIXED** | New `scripts/activate_weights.py` versions a raw weight JSON and activates it. After re-tuning, `data/weights/weights_choice.json` was activated as **v0008** (`active.json` now points to `v0008`, source `choice-tuned`). README/flow now document `scripts/tune_weights.py` + `reports/strict_eval_tuned.*` as canonical and the activation command. Tests: `tests/test_activate_weights.py`. |
| I5 | Event persistence/ingestion O(n²); `/events` unbounded | **FIXED** | `EventService` keeps an in-memory line counter per active JSONL (counted once), an in-memory duplicate-key set, and an impression index (`record_event` no longer scans all events). `Store.reference_time`, `recent_impression_counts`, `has_assignment_pair`, and the service acceptance/collaboration indexes are incremental. `/events` is capped at 200 events/batch, 20 metadata keys, 2000 metadata characters, and 1 MB request body (ASGI `413` before JSON parsing). Persisted logs are explicitly **audit-only** (not replayed on startup). Tests: `test_duplicate_set_and_line_counts_are_seeded_and_incremental`, `test_persisted_logs_are_audit_only`, `test_store_recent_counts_and_assignment_index_are_incremental`, `test_events_batch_metadata_and_body_are_bounded`. |
| I6 | Per-request service/ItemCF rebuild; latency guardrail unmeasured | **FIXED** | `create_app` now caches one `RecommendationService` in `app.state.service_cache` (`active_service()`), keyed by weight version + assignment/feedback lengths; assignment, feedback, rollback, and recompute invalidate it. `recommend_workers`, `recommend_tasks`, upload drafts, chain plan/replan/node recommend, event choice learning, and recompute reuse it. The strict evaluator now reports `scoring_latency_p50_ms/p95_ms` (in-process scoring) and `endpoint_latency.available=false`, `guardrail="N/A"`; the Markdown says “NOT HTTP endpoint latency”. Tests: `test_recommend_reuses_cached_service_and_invalidates_on_assignment`, `test_evaluate_strict_marks_endpoint_latency_na`. |
| I7 | Semantic text caches unbounded on untrusted uploads | **FIXED** | `_WORKER_TEXT_CACHE` / `_TASK_TEXT_CACHE` are bounded (`MAX_TEXT_CACHE_ENTRIES = 4096`, oldest-entry eviction). `FeedbackService.record_feedback` calls `clear_text_caches()` so live profile changes are not stale. Tests: `test_text_caches_are_bounded_and_evict_oldest`, `test_record_feedback_clears_semantic_text_cache`. |
| I8 | Live feedback never updated `communication_ratings` | **FIXED** | `FeedbackService.record_feedback` validates `communication_rating` and appends `float(rating)` to `worker.communication_ratings` (synthetic generation remains train-only). Tests: `test_record_feedback_appends_communication_rating`, `test_feedback_updates_live_communication_signal` (feature input moves `0.5 → 0.2`). |
| I9 | README/flow docs stale | **FIXED** | README/flow updated for: test count (386), upload endpoints and decompression bounds, NLP/classifier, 10,000-task large benchmark and its strict train-only ItemCF, tuned weights + activation command + v0008 active, canonical tuned report, 1,000-task benchmark `collaborative = 0` vs the large benchmark, serving-parity strict evaluation, and endpoint-latency N/A. `tests/test_docs.py` now asserts the current commands, active-weights pointer, serving/endpoint claims, benchmark distinction, upload docs, and the test count. |

---

## 3. Commands and output

### Full suite

```text
$ python -m pytest tests/ -q
388 passed in 46.52s
```

Baseline before the fix wave was 360 passed in 41.51s; 32 regression tests were added.

### 3.3 Post-review C1 corrections

**Correction 1.** The first C1 patch used a raw 8 KB `/FlateDecode` literal scan.
Re-review showed `/Fl`, indirect `/Filter 5 0 R`, and >8 KB dictionary gaps
bypassed it (a crafted 81,876-byte `/Fl` PDF expanded to 41,943,034 bytes in
`page.extract_text()`). The raw scan was replaced by the pypdf object-model scan
described in §2 C1.

**Correction 2.** The first object-model scan still used a recursive depth cap
of 12, while pypdf follows nested Form XObjects up to 5,000. A 42,185-byte PDF
with a Flate bomb in a 5th-level Form XObject bypassed the scan and expanded to
41,943,040 bytes (85.5 MiB peak). The recursion was replaced by an **iterative
worklist** with a visited-object map (50,000 cap), stream cap (5,000), and no
depth cap below pypdf's traversal; nested Form XObjects at arbitrary depth are
now collected before `extract_text()`.

**Correction 3.** A form with no local `/Resources` and a crafted `/Parent`
dictionary could still hide a referenced Form XObject, because pypdf resolves
form resources with `get_inherited('/Resources')`, which walks `/Parent`. The
scan now follows `/Parent` from stream objects in addition to `/Resources`,
`/XObject`, and `/Annots`; the visited map makes cycles safe. The new
end-to-end test (`/F1` form with no local resources + `/Parent 8 0 R` →
`/F2 6 0 R` Flate bomb) asserts the public `extract_text()` raises the
over-limit `UploadError` and `page.extract_text` is never called. Focused and
full output:

```text
$ python -m pytest tests/test_upload.py -q
43 passed in 4.89s

$ python -m pytest tests/ -q
392 passed in 46.15s
```

The docs count minor is also fixed: `tests/test_docs.py` now asserts the exact
current count (392), so a stale README count fails.

### Tuning (serving parity)

```text
$ python scripts/tune_weights.py --seeds 42,43,44,45,46 --k 10
...
"target_met": true
"serving_features": {"semantic_matcher": true, "acceptance_model": true,
                     "parity": "serving"}
"constraint_violations": 0
"endpoint_latency": {"available": false, "guardrail": "N/A", ...}
```

Choice-tuned candidate before coordinate search:

```json
{
  "reputation": 0.36767264253,
  "skill": 0.168315064489,
  "expertise": 0.277518489448,
  "collaborative": 0.059291230226,
  "preference": 0.05216200726,
  "load": 0.039808410446,
  "customer_preference": 0.035232155602
}
```

Final tuned/activated weights (v0008):

```json
{
  "reputation": 0.36767264253,
  "skill": 0.168315064489,
  "expertise": 0.277518489448,
  "collaborative": 0.034023777334,
  "preference": 0.057919218554,
  "load": 0.04893876013,
  "customer_preference": 0.045612047514
}
```

### Activation

```text
$ python scripts/activate_weights.py --input data/weights/weights_choice.json --source choice-tuned
active_version: v0008
data/weights/active.json -> {"active_version": "v0008"}
```

### 5-seed strict evaluation

```text
$ python scripts/evaluate_strict.py --seeds 42,43,44,45,46 --k 10 \
    --candidate-weights data/weights/weights_v0008.json
...
"constraint_violations": 0
"serving_features": {"semantic_matcher": true, "acceptance_model": true,
                     "parity": "serving"}
"endpoint_latency": {"available": false, "guardrail": "N/A"}
```

Reports regenerated:

- `reports/strict_eval_tuned.json` / `reports/strict_eval_tuned.md` (canonical tuned evidence)
- `reports/strict_eval.json` / `reports/strict_eval.md` (generic strict report with v0008)

---

## 4. New strict metrics and target status

5 seeds (42–46), k=10, train-only store, serving-parity features
(`reports/strict_eval_tuned.md`):

| Direction | Metric | Baseline | Candidate | Delta mean [95% CI] p |
|---|---|---|---|---|
| task_to_workers | HR@10 | 0.6737 | 0.6797 | +0.0060 [+0.0007, +0.0123] p=0.038 |
| task_to_workers | NDCG@10 | 0.3569 | 0.3577 | +0.0008 [-0.0021, +0.0038] p=0.612 |
| task_to_workers | MRR | 0.2605 | 0.2598 | -0.0007 [-0.0040, +0.0025] p=0.676 |
| worker_to_tasks | HR@10 | 0.0637 | 0.2070 | +0.1433 [+0.1307, +0.1563] p=0.000 |
| worker_to_tasks | NDCG@10 | 0.0258 | 0.0991 | +0.0733 [+0.0671, +0.0796] p=0.000 |
| worker_to_tasks | MRR | 0.0148 | 0.0669 | +0.0521 [+0.0468, +0.0577] p=0.000 |
| worker_to_tasks_exposed | HR@10 | 0.4950 | 0.5077 | +0.0127 [+0.0040, +0.0204] p=0.008 |
| worker_to_tasks_exposed | NDCG@10 | 0.2273 | 0.2417 | +0.0145 [+0.0106, +0.0182] p=0.000 |

Relative changes: task→workers HR **+0.60pp**, NDCG **+0.21%**; worker→tasks
HR **+14.33pp**, NDCG **+283.55%**.

- **Target status: MET.** worker→tasks qualifies (NDCG relative +283.55% with CI
  low > 0 and HR +14.33pp with CI low > 0); task→workers does not deteriorate in
  the target sense (HR mean +0.006, NDCG mean +0.0008).
- Constraint violations: **0**.
- Cold start: **N/A** (`available=false`, `queries=0`; no workers without train
  assignments in the synthetic seeds).
- Calibration: Brier **0.0323** (raw 0.1186), Platt a/b 10.9652 / -3.5031; one
  populated reliability bin. Ranking is unaffected.
- In-process scoring p50/p95: **9.53 / 19.86 ms**. **Not** endpoint latency;
  the HTTP endpoint 2× guardrail is explicitly **N/A**.

Honest caveats:

- worker→tasks absolute NDCG is still low (~0.099) and HR ~0.207; the large
  relative gain rests on a low baseline. The report does not call this recovered
  historical performance.
- The previous `weights_v0007.json` report (NOT MET) is superseded by v0008.

---

## 5. Files changed

Code / scripts:

- `app/upload/extract.py` — PDF object-model stream scan (aliases/indirect filters/gaps, bounded Flate decode, unsupported/multiple filter rejection); reusable body-limit middleware limit parameter.
- `app/serving.py` (new) — train-only serving component builders and per-store cache.
- `app/evaluation_strict.py` — per-seed serving components; scoring/endpoint latency split.
- `app/service.py` — dynamic reference time; cached acceptance/collaboration indexes; indexed assignment eligibility.
- `app/data/store.py` — incremental reference time, impression window counts, assignment-pair index.
- `app/events.py` — impression-derived labels, metadata allowlist, duplicate set, line counters, audit-only note.
- `app/schemas.py` — event batch/metadata/body bounds.
- `app/main.py` — body cap for `/events`, cached `active_service()`, invalidation, assignment auto-accept validation, impression role/user metadata, serving helper imports.
- `app/feedback.py` — live `communication_ratings` append and semantic cache clear.
- `app/semantic.py` — bounded text caches.
- `scripts/tune_weights.py` — serving-parity services/features.
- `scripts/evaluate_strict.py` — serving-parity reporting and latency wording.
- `scripts/activate_weights.py` (new) — version + activate tuned weights.
- `frontend/app.js`, `frontend/styles.css` — request_id retention, click/apply/reject events, reject UI.

Tests:

- `tests/test_upload.py`, `tests/test_strict_eval.py`, `tests/test_tune_weights.py`,
  `tests/test_events.py`, `tests/test_api_events.py`, `tests/test_semantic.py`,
  `tests/test_feedback.py`, `tests/test_docs.py`
- `tests/test_activate_weights.py` (new)

Docs / data / reports:

- `README.md`, `docs/recommendation-flow.md`
- `data/weights/weights_choice.json` (re-tuned), `data/weights/weights_v0008.json`
  (new), `data/weights/active.json` (v0008), `data/weights/changelog.jsonl`
- `reports/strict_eval_tuned.json/.md`, `reports/strict_eval.json/.md`

---

## 6. Risks

1. **PDF object-model scan runs after `PdfReader` construction.** Content,
   XObject, font, pattern, and annotation streams are bounded before
   `extract_text()`, and multiple/unsupported filters are rejected. A malicious
   PDF could still attempt to exhaust CPU/RSS while pypdf resolves object/xref
   streams or a deeply nested object graph during `PdfReader`/`reader.pages`;
   the strongest follow-up is a subprocess with a hard timeout/RSS limit. The
   scan itself is iterative with no depth cap (it follows nested forms and
   stream `/Parent` chains), and fail-closed caps visited objects at 50,000 and
   streams at 5,000.
2. **PDF compatibility is intentionally reduced.** Streams with unsupported
   filters (e.g. DCT/JPEG images, JPX, LZW) or multiple filters now return 422
   with a clear message, and legitimate Flate streams expanding past 32 MB (or
   64 MB total) are rejected. This is the explicit security tradeoff requested
   by the re-review.
3. **Evaluation parity still uses the in-process ranker.** HTTP endpoint latency
   remains unmeasured; the 2× latency guardrail is N/A, not passed.
4. **Acceptance-model training includes each sample's own/future train
   accept/reject events in `historical_accept_rate`** (known Task 13 limitation).
   Baseline and candidate share this feature, so the delta is unaffected, but
   absolute calibration may be optimistic. Synthetic event labels come from the
   logging policy, not ground truth.
5. **Cold-start guardrail is N/A on these seeds.** The synthetic datasets have
   no workers without train assignments; a dedicated cold-start dataset is still
   needed to measure it.
6. **Service cache invalidation is length/version based.** It detects appends
   and weight-version changes, not in-place removal/replacement of assignments or
   feedback. Current code only appends, so this is safe today.
7. **Persisted event logs are audit-only.** Duplicate/idempotency state is
   per-process; a restart loses the in-memory duplicate set and impression index.
   This is documented and is not replayed into training.
8. **Large worker→tasks gain is relative.** Absolute NDCG/HR remain modest; do
   not describe it as recovered historical accuracy.

---

## 7. Remaining work / parked minors

Not fixed (parked, per brief):

- Funnel denominators/rank buckets; missing `GET /evaluation/strict`,
  `GET /config/semantic`, `scripts/simulate_events.py`,
  `reports/strict_eval_queries.csv`; 80/20 vs 70/15/15; exposure-fairness
  saturation; semantic text staleness beyond feedback; CRF pickle safety; upload
  section volume/CPU offload; 10 MB multipart overhead/413 vs 422; upload
  `request_id` without impression; global `MultiPartParser` mutation; binding
  per-update counts/unguarded write; leakage static/runtime tests; test
  `events_dir` cleanup; docs test token-only (now strengthened, but still
  token-based).
- PDF subprocess/timeout/RSS isolation for parser-time work before the object
  scan (see risk 1); non-Flate/multiple filters are now rejected, not decoded.
- Endpoint latency measurement (see risk 3).
- Cold-start evaluation dataset (see risk 5).
- 1,000-task benchmark `collaborative` remains 0; the 10,000-task large
  benchmark is strict train-only and does not replace it.

Cheap minors fixed opportunistically: event `score` null/non-numeric coercion,
persisted-log audit-only documentation, and scoring-vs-endpoint latency naming.
