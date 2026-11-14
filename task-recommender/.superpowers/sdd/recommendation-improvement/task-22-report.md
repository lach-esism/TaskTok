# Task 22 Report — Bidirectional Upload/Analysis (Task → Workers, Resume → Tasks)

**Status:** DONE_WITH_CONCERNS (non-blocking; see §8)
**Date:** 2026-11-14
**Scope:** upload text extraction, task/resume analysis, two read-only upload
endpoints, a paste-text resume endpoint, two frontend cards, and tests.

---

## 1. What was implemented

### 1.1 Secure in-memory extraction — `app/upload/extract.py`

- `extract_text(filename, content, content_type=None) -> str`.
- Native `.txt` / `.md` decoding (`utf-8-sig`, then `gb18030`); NUL bytes are
  rejected so a binary renamed to `.txt` cannot be silently accepted.
- `.pdf` via lazily imported optional `pypdf`; pages are joined with newlines.
  A missing `%PDF-` header, encryption, or parser failure becomes a clear
  user-facing 422.
- `.docx` via lazily imported optional `python-docx`; paragraphs and table
  cells are read. A missing ZIP header or parser failure becomes a clear 422.
- Missing optional packages raise `UploadError` with install instructions
  (`pip install pypdf` / `pip install python-docx`) instead of `ImportError`.
- `sanitize_filename` removes path components, control characters, and unsafe
  characters, and bounds length.
- Extension whitelist: `.txt`, `.md`, `.pdf`, `.docx`.
- MIME/extension agreement: concrete MIME types must match the extension;
  generic `application/octet-stream` is tolerated because browsers use it.
- Limits: `MAX_UPLOAD_BYTES = 10 * 1024 * 1024`, plus a
  `MAX_EXTRACTED_CHARS = 5_000_000` bound for ZIP/PDF expansion.
- Parsing happens from `bytes` / `io.BytesIO`; nothing is written to disk and
  no macro/script/embedded object is executed.

### 1.2 Analysis — `app/upload/analyze.py`

- `analyze_task_text(text, now=None) -> dict`
  - Uses the Task 23 `TaskTextClassifier.predict` and
    `extract_fields_v2`/`extract_fields`.
  - Returns category, label, calibrated confidence, raw confidence,
    `needs_clarification`, top-3 categories, evidence, and a `fields` block:
    budget range/min/max, duration days, deadline, skills, remote, requirements,
    suggested title, experience, language, and inferred region.
- `task_from_analysis(...) -> Task`
  - Builds a temporary `Task` with a content-hash `draft_task_*` ID,
    `required_skills` at level 2, a future deadline, estimated effort bounded to
    4–16 h, budget, region and remote flags. `status="open"` for eligibility.
- `build_task_draft(task, analysis) -> dict`
  - JSON-safe draft payload (`status="draft"`, confidence, deadline ISO).
- `analyze_resume_text(text, now=None, worker_id=None) -> dict`
  - Calls `parse_resume_sections` for education/work/projects/skills/
    certificates/languages and experience years.
  - Adds a lexicon/alias scan and a dedicated skills-section token scan
    (so `Python` and other non-taxonomy tools survive as raw worker skills).
  - Infers categories from skill→category membership
    (`CATEGORY_SKILLS` + a small raw-tool map), region from city cues, remote
    preference from remote/onsite cues, and expected pay/period from labeled
    salary patterns.
  - Builds a temporary `Worker` draft with a content-hash `draft_resume_*` ID,
    skills, specialties, preferred categories, level, region, remote flag and
    expected pay.
- `worker_from_draft(draft) -> Worker`
  - Reconstructs a `Worker` from the JSON-safe worker draft; extra UI keys
    (`draft`, `categories`, `confidence`, ...) are ignored.

### 1.3 API endpoints — `app/main.py`

| Method | Path | Behavior |
|---|---|---|
| POST | `/upload/task` | multipart `file` + `top_n` → extraction, task analysis, draft `Task`, Top-N workers from `RecommendationService.recommend_workers_for_task` (semantic + seven-dim). Never writes the store. |
| POST | `/upload/resume` | multipart `file` + `top_n` → resume analysis, draft `Worker`, Top-N open tasks via `RecommendationService.recommend_tasks` against an ephemeral store copy containing only the temp worker. Real store untouched. |
| POST | `/resume/analyze` | JSON `{"text": "...", "top_n": 5}` → same resume analyzer and recommendation path, no file. |

Shared response shape:

```json
{
  "kind": "task|resume",
  "filename": "task.txt|null",
  "content_type": "text/plain|null",
  "size_bytes": 123,
  "text_preview": "...",
  "analysis": { "...": "..." },
  "draft": { "...": "..." },
  "candidates": [
    {"candidate_id": "...", "score": 0.0, "breakdown": {}, "reasons": [], "cold_start": false, "propensity": 1.0}
  ],
  "request_id": "...",
  "persisted": false
}
```

The upload endpoints deliberately do **not** record impressions or events
(unlike `/recommend/workers` and `/recommend/tasks`), because that would be a
store write. They return a fresh `request_id` for correlation only.

### 1.4 Frontend — `frontend/index.html`, `app.js`, `styles.css`

- New “双向解析” tab with two cards:
  - “上传任务书”: file picker, Top-N, text preview, category/confidence bars,
    budget/duration/deadline/remote/skills/requirements, Top-N workers, and a
    confirm button.
  - “输入/上传简历”: paste textarea + file picker, Top-N, preview, detected
    skills, experience/region/remote/expected-pay profile, draft worker
    metadata, Top-N tasks, and a confirm button.
- `renderCandidates` gained an additive `options.allowAdopt` flag; upload cards
  hide “采纳并评分” because the draft does not exist in the store.
- Confirm-to-create is an explicit user action: the button marks the draft as
  confirmed and reveals the draft JSON. It never triggers an automatic write;
  the copy explicitly says the demo does not persist records.
- Existing markup/style conventions are reused (`.panel`, `.field`, `.btn`,
  `.classify-*`, `.candidate`, `.results`); no redesign.

### 1.5 Dependencies

- `requirements.txt` now lists `python-multipart>=0.0.9` (required by FastAPI
  multipart routes).
- `pypdf` and `python-docx` are documented as optional extras with the exact
  install commands and the 422 fallback behavior.

---

## 2. Security limits and guarantees

| Control | Implementation |
|---|---|
| Max upload | 10 MB (`MAX_UPLOAD_BYTES`), checked via `UploadFile.size` where available and via a bounded read; re-checked in `extract_text`. |
| Extension whitelist | `.txt`, `.md`, `.pdf`, `.docx` only. |
| MIME/extension | Concrete MIME must agree; generic octet-stream allowed. |
| Filename | `sanitize_filename` strips paths, control chars, unsafe chars; bounded to 180 chars. |
| Parsing | In memory (`io.BytesIO`); no temp files created by app code. |
| Execution | No `eval`/`exec`/macro; only `pypdf` text extraction and `python-docx` structural reads. |
| Decompression | Extracted text capped at 5,000,000 chars. |
| Optional deps | Lazy imports; absence yields 422 with install instructions. |
| Store | Upload endpoints only call read/recommendation paths; resume uses a shallow store copy plus a separate `workers` dict. |
| File persistence | No upload bytes are written; tested by diffing the client’s temp directory before/after all three endpoints. |

---

## 3. Tests

Created:

- `tests/test_upload.py` (20 tests)
  - extensions `.txt`/`.md`, BOM, unsupported extension, empty/binary/oversized,
    MIME mismatch, generic octet-stream, filename sanitization, 10 MB constant;
    PDF/DOCX missing-dependency 422s, fake-parser in-memory paths, and a real
    `python-docx` parse when the extra is installed (`importorskip`).
  - task analysis category/fields/top-3, blank rejection, draft `Task` builder.
  - resume analysis skills/experience/region/remote/expected pay/draft worker,
    blank rejection, and worker reconstruction.
- `tests/test_upload_api.py` (12 tests)
  - task upload analysis + Top-N workers + draft + unchanged store snapshot;
  - resume upload profile + Top-N tasks + draft + unchanged store snapshot;
  - paste `/resume/analyze` + unchanged store;
  - unsupported extension, oversized, MIME mismatch, PDF/DOCX optional-deps;
  - blank/invalid paste requests;
  - no files written to the temp dir;
  - frontend contains both cards and the confirm/app.js hooks.

Commands and results:

```text
python -m pytest tests/test_upload.py tests/test_upload_api.py -q
31 passed in 5.40s

python -m pytest -q
344 passed in 41.20s
```

`python-multipart 0.0.33` was installed locally for the test run; it is now in
`requirements.txt`.

---

## 4. Files changed

Created:

- `app/upload/__init__.py`
- `app/upload/extract.py`
- `app/upload/analyze.py`
- `tests/test_upload.py`
- `tests/test_upload_api.py`

Modified:

- `app/main.py` (imports, upload helpers, three endpoints)
- `app/schemas.py` (`ResumeAnalyzeRequest`)
- `frontend/index.html` (nav tab + two cards)
- `frontend/app.js` (`apiForm`, upload/analysis rendering, draft confirmation,
  additive `renderCandidates` option)
- `frontend/styles.css` (upload/confirm/draft styles)
- `requirements.txt` (`python-multipart`; optional PDF/DOCX documentation)

No other source files were modified. This directory is not a git repository, so
no commits were created.

---

## 5. Self-review findings

1. **Store immutability:** resume recommendations require a worker lookup that
   normally reads `store.workers`. Rather than temporarily mutating the live
   store, the endpoint builds `copy.copy(store)` with a new `workers` mapping.
   Other collections (assignments/events/preferences) are shared read-only.
   Tests snapshot IDs/lists before and after and assert equality.
2. **Upload impressions:** the existing recommend endpoints record impressions.
   Upload endpoints intentionally skip `EventService.record_impression`; doing
   otherwise would violate the no-write rule. The response `request_id` is not
   logged.
3. **Optional-dependency testing:** the PDF/DOCX fallback tests monkeypatch the
   lazy import functions, so they do not depend on extras. The DOCX happy path
   is additionally exercised with the real package when present.
4. **Resume skill noise:** the first implementation kept arbitrary Chinese
   skill-section tokens, which turned location lines (“上海”) into fake skills.
   Raw tokens are now restricted to ASCII tool/language names; Chinese skills
   come from the canonical lexicon/alias scan.
5. **Section scanning:** `parse_resume_sections` keeps only the first token of a
   comma-separated skills line. The analyzer adds its own skills-section line
   scan (stopping at section/personal-info boundaries) so multi-token lines are
   preserved.
6. **Deterministic draft IDs:** draft IDs are SHA-256 prefixes of the normalized
   text. Repeated identical uploads reuse semantic text caches instead of
   growing them; distinct files still get distinct IDs.
7. **Task deadline:** extracted full dates are normalized to 23:59:59 UTC and
   only used when in the future; otherwise the draft gets `now + 14 days`.
8. **Existing contracts:** `/classify`, `/recommend/*`, `/assignments`, and the
   rest of the app are unchanged. Full suite passes (344 tests).

---

## 6. Endpoint behavior details

- `top_n` is validated by FastAPI (`1..50`); task upload uses exactly `top_n`
  (no exploration rerank, because exploration could randomize an explanatory
  draft demo and uploads must stay read-only).
- `filename` in the response is the sanitized display name; for pasted text it
  is `null`.
- `persisted` is always `false`.
- Candidate payloads include the seven-dim breakdown and the service reasons
  (`skill=`, `reputation=`, `expertise=` for workers; `skill=`, `preference=`,
  `load=` for tasks).
- If no candidate passes eligibility, `candidates` is empty and the response is
  still 200 (matching the existing recommend endpoints’ “no eligible
  candidates” behavior).

---

## 7. Manual verification

- Real `python-docx` round-trip: generated a DOCX, extracted it through
  `extract_text`, confirmed heading/paragraph/table text present.
- Frontend served at `/ui/`; static test asserts the two card headings, file
  inputs, confirm slots, `runUploadTask`, `runResumeAnalyze`, and
  `confirmDraft` are present.
- `requirements.txt` was updated and `python-multipart` is importable in the
  test environment.

---

## 8. Concerns / limitations (non-blocking)

1. **Confirm-to-create is client-side only.** The project has no existing
   create-task/create-worker API and the brief requires drafts only. The
   confirm button records the draft in client state and displays its JSON; it
   does not persist a record. If a later task adds creation endpoints, the
   button is the natural integration point.
2. **Framework spooling.** Starlette/FastAPI may temporarily spool a multipart
   upload to a `SpooledTemporaryFile` before the handler runs. The app itself
   never writes or keeps the file, and the handler reads at most the 10 MB
   limit. A true pre-body rejection would need a `Content-Length` middleware,
   which is outside this task’s file scope.
3. **PDF happy path** is covered structurally with a fake reader; no real PDF
   fixture is committed because generating one without adding a new dependency
   is awkward. The `pypdf` call path is simple (`PdfReader(io.BytesIO(...))`,
   per-page `extract_text`), and missing-package behavior is tested.
4. **Region inference** uses the synthetic-city cue list from `app.resume` and
   defaults to `CN` when no cue is present; it is a heuristic, not geocoding.
5. **Expected pay** is kept as the parsed amount plus period; monthly amounts
   are not converted into a per-task budget, so `pay_fit` remains a heuristic
   input rather than a precise affordability check.
6. **`python-multipart` is now an import-time requirement** for the app because
   FastAPI validates `File(...)` routes at definition time. It is listed as a
   required dependency, so a normal install is sufficient.

---

## 9. Security review fix log (round 2)

All four review findings were addressed. The earlier concern in §8.2 (“framework
spooling”) is now resolved by the pre-parse body middleware and the RAM spool
threshold. The fix round changes `app/upload/extract.py`,
`app/upload/__init__.py`, `app/upload/analyze.py`, `app/main.py`,
`app/semantic.py`, `tests/test_upload.py`, and `tests/test_upload_api.py`.

### 9.1 Critical — body limit enforced before form parsing

- Added `UploadBodyLimitMiddleware`, a pure ASGI middleware (no
  `BaseHTTPMiddleware`) in `app/upload/extract.py`. It runs on
  `/upload/task`, `/upload/resume`, and `/resume/analyze`:
  - rejects an over-limit `Content-Length` immediately with HTTP 413 and a
    clear JSON detail;
  - counts streamed `http.request` chunks for chunked bodies and raises an
    internal exception before the wrapped app consumes the over-limit chunk;
  - an over-limit request never reaches the endpoint/general handler.
- Registered the middleware in `create_app`.
- Set `MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES`, so accepted file
  parts stay in RAM instead of rolling to a framework temp file.
- Replaced FastAPI's implicit `File`/`Form` parsing with an explicit
  `request.form(max_files=1, max_fields=8)` helper
  (`_parse_upload_form`) so file/field counts are capped and `top_n` is
  validated without broad endpoint-level catches.
- The same middleware protects the JSON `/resume/analyze` body.
- New tests:
  - `test_content_length_over_limit_is_rejected_before_handler`
  - `test_chunked_body_over_limit_never_reaches_handler`
  - `test_resume_analyze_json_body_has_the_same_cap`
  - `test_upload_task_rejects_oversized_file_before_form_parsing` (real
    `MAX_UPLOAD_BYTES + 1` payload; expects 413 and “10 MB”)
  - `test_upload_endpoints_do_not_persist_uploaded_files` now redirects
    `tempfile.tempdir` to a dedicated directory, asserts the spool threshold
    is at least the body cap, and asserts that directory remains empty.

### 9.2 Important — bounded DOCX/ZIP and PDF expansion

- `_inspect_docx_zip(content)` runs after the optional `python-docx` import
  and before `docx.Document`, using `zipfile.ZipFile.infolist()`:
  - max 2,048 entries;
  - max 32 MB per uncompressed entry;
  - max 64 MB total uncompressed;
  - compression ratio > 100 rejected for entries ≥ 1 MB;
  - encrypted/flag-bit entries rejected.
- `_extract_pdf` now caps at 200 pages (`MAX_PDF_PAGES`) and accumulates text
  with an early break/raise at `MAX_EXTRACTED_CHARS` (5,000,000) instead of
  joining all pages first.
- New tests:
  - `test_zip_bomb_like_docx_is_rejected_before_document_parse` (2 MB of zeros
    in a deflated ZIP);
  - `test_pdf_page_cap_is_enforced` (fake reader with 201 pages);
  - `test_pdf_text_cap_is_enforced_during_page_iteration` (fake reader, low
    char cap).
- The existing fake-DOCX parser test now supplies a valid ZIP container so the
  expansion pre-check and parser path are both exercised.

### 9.3 Important — monthly pay is not used as per-task pay

- Added `_worker_expected_pay`: a monthly (`月`) or hourly (`小时`) quote maps
  to `Worker.expected_pay = 0.0` (unknown per-task pay). Per-day and
  unqualified figures are kept as-is. The raw figure and period remain in the
  analysis `expected_pay` payload.
- Tests assert both the raw `15000 元/月` extraction and
  `draft_worker["expected_pay"] == 0.0` in the unit and API resume paths.

### 9.4 Minor hardening

- `SemanticMatcher` now has `MAX_CACHE_ENTRIES = 2048`; the pair cache evicts
  its oldest entry instead of growing without bound for upload drafts.
  `test_semantic_pair_cache_is_bounded` drives 20 unseen pairs with a cap of 5
  and asserts the cache stays bounded. (`app/semantic.py` was in scope for
  this round.)
- Upload endpoints now catch only `upload_extract.UploadError`; the broad
  `except ValueError` blocks were removed. Blank task/resume text is rejected
  explicitly with 422 in the payload helpers / paste route.
- The oversized-upload API test no longer monkeypatches the byte constant while
  asserting a “10 MB” message; it sends a real over-limit payload and expects
  the pre-parse 413.
- The no-persistence test now redirects the framework temp directory and
  checks the spool threshold, in addition to the store snapshot.

### 9.5 Verification

```text
python -m pytest tests/test_upload.py tests/test_upload_api.py -q
39 passed in 5.62s

python -m pytest -q
351 passed in 41.33s
```

### 9.6 Remaining concerns after the fix round

1. Confirm-to-create remains a client-side explicit confirm step (drafts shown
   as JSON, no persistence), because the project has no create-task /
   create-worker API and the brief requires drafts only.
2. The PDF happy path still uses a fake reader in tests; the real optional
   `pypdf` path is exercised only when a real PDF fixture is available. The
   missing-dependency path and caps are covered.
3. `python-multipart` remains an import-time requirement for the app because
   FastAPI route registration needs it; it is listed in `requirements.txt`.

---

## 10. Security re-review fix log (round 3)

All four follow-up findings are addressed. This round changes
`app/upload/analyze.py`, `app/semantic.py`, `app/main.py`,
`tests/test_upload.py`, and `tests/test_upload_api.py`.

### 10.1 Important — pay label forms

`_EXPECTED_PAY_RE` now captures the matched **label** (not only a trailing
`/月` or `/小时` suffix), and `_infer_expected_pay` derives the period from
the label when no explicit suffix is present:

- `月薪 15000 元` → value 15000, period `月`
- `期望月薪 15000` → value 15000, period `月`
- `时薪 100 元` → value 100, period `小时`
- `期望时薪 100 元` → value 100, period `小时`
- `日薪 800 元` → value 800, period `天`
- `期望薪资：15000 元/月` → value 15000, period `月`

`_worker_expected_pay` maps `月` and `小时` to `Worker.expected_pay = 0.0`
(unknown per-task pay). The raw value and period remain in
`analysis["expected_pay"]`. Per-day and unqualified figures stay
per-task-compatible.

Covering test:
`test_expected_pay_labels_drive_period_and_worker_pay` — a parameterized test
over all four label forms plus the explicit `/月` suffix, a per-day form, and
an unqualified form, asserting both the analysis payload and the draft
Worker's `expected_pay`.

### 10.2 Minor — optional-docx test decoupled from the extra

`test_zip_bomb_like_docx_is_rejected_before_document_parse` now monkeypatches
`extract._import_docx` with a fake module and asserts the fake
`Document(...)` is never called. The ZIP expansion pre-check therefore runs
and rejects the bomb without requiring `python-docx` to be installed. The
real-DOCX happy-path test still uses `pytest.importorskip("docx")`.

### 10.3 Minor — OpenAPI multipart contract restored

Because the upload handlers take `Request` (to enforce
`max_files=1` / `max_fields=8` after the ASGI cap), FastAPI no longer infers
form parameters. Both routes now declare
`openapi_extra=_UPLOAD_OPENAPI_EXTRA`, documenting a required
`multipart/form-data` body with:

- `file`: `string` / `binary`, required;
- `top_n`: `integer`, default 5, minimum 1, maximum 50.

Covering test: `test_upload_openapi_documents_multipart_contract` reads
`/openapi.json` and asserts both paths expose the multipart schema above.
The ASGI middleware and `max_files`/`max_fields` enforcement are unchanged.

### 10.4 Minor — bounded text→vector cache

`SemanticMatcher` now also bounds `_vectors` with
`MAX_VECTOR_ENTRIES = 4_096`. `_remember_vectors` evicts the oldest entry
before insertion; both `_embedding_for` (sentence-transformer provider) and
`_vector_for` (TF-IDF provider) use it.

Covering test: `test_semantic_vector_cache_is_bounded` fits a matcher, sets a
cap of 5, scores 20 unseen pairs, and asserts `len(matcher._vectors) <= 5`.

### 10.5 Verification

```text
python -m pytest tests/test_upload.py tests/test_upload_api.py -q
48 passed in 5.73s

python -m pytest -q
360 passed in 41.13s
```

### 10.6 Remaining concerns after round 3

1. Confirm-to-create remains a client-side explicit confirm step (drafts shown
   as JSON, no persistence), because the project has no create-task /
   create-worker API and the brief requires drafts only.
2. The real PDF happy path is still not fixture-tested; the fake-reader path
   covers page/char caps and the optional-dependency fallback is tested.
3. `python-multipart` remains an import-time requirement for FastAPI route
   registration and is listed in `requirements.txt`.
