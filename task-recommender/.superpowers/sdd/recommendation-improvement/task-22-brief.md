## Task 22: Bidirectional Upload/Analysis — Task → Workers and Resume → Tasks

**Goal:** Support both directions: upload/paste a task document → semantic analysis → Top-N workers; upload/paste a resume → semantic analysis → Top-N open tasks. No auto-write; the user confirms a draft.

**Files:**
- Create: `app/upload/extract.py`, `app/upload/analyze.py`, `tests/test_upload.py`, `tests/test_upload_api.py`
- Modify: `app/main.py`, `app/schemas.py`, `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `requirements.txt` (document optional PDF/DOCX extras)
- No persistence of the uploaded file.

**Interfaces:**
- `extract_text(filename: str, content: bytes) -> str` — `.txt`/`.md` native; `.pdf` via optional `pypdf`, `.docx` via optional `python-docx`; unsupported/oversized → 422 with a clear message.
- `analyze_task_text(text: str) -> dict` — `TaskTextClassifier.predict` + `extract_fields`; returns category, confidence, top-3 categories, budget/days/skills/remote/requirements.
- `analyze_resume_text(text: str) -> dict` — skill/category lexicon + `extract_fields`; returns detected skills, inferred categories, experience years, region/remote preference, expected pay if mentioned, and a draft `Worker` payload. No auto-write.
- `POST /upload/task` multipart — file → analysis + Top-N workers (semantic similarity + seven-dim scores) + a draft task payload.
- `POST /upload/resume` multipart — file → analysis + Top-N open tasks using a temporary `Worker` profile and `RecommendationService.recommend_tasks`; include a draft `Worker` payload.
- `POST /resume/analyze` JSON `{"text": "..."}` — paste-text path for the resume side (same analyzer, no file).
- Both upload endpoints never write to the store.

**Tasks:**
- 22a: text extraction layer with 10 MB limit, MIME/extension whitelist, in-memory parsing, no execution. **Enforce the limit in a pure ASGI middleware before multipart parsing**: reject an over-limit `Content-Length` and count streamed bytes for chunked bodies; set the Starlette `MultiPartParser` spool threshold so accepted files stay in RAM; cap `max_files`/`max_fields`; apply the same body cap to `/resume/analyze`. Pre-check ZIP entries (total/per-entry uncompressed size and compression ratio) before `docx.Document`. **PDF pre-scan must resolve `/Filter` aliases (`/Fl`, `/FlateDecode`), indirect filter references, and arbitrary dictionary-to-stream gaps; for Flate streams, decode with `zlib.decompressobj` and a hard `max_length` before `extract_text`, rejecting output over the bound. Traverse the reachable object graph iteratively (page `/Contents`, `/Resources`, `/Annots`, nested Form XObjects via `/Resources`/`/XObject`, and **`/Parent`-inherited resources** to mirror pypdf's `get_inherited` form-resource lookup) with a visited set and fail-closed node/stream caps; do not use a depth cap below pypdf's Form XObject traversal (which reaches thousands). Reject unsupported filters (or isolate them in a subprocess with a hard timeout/RSS limit).** Cap PDF pages/characters with an early break.
- 22b: task analysis + `POST /upload/task` recommendation response; reuse `RecommendationService`/`candidate_features`; include a draft `Task` payload.
- 22c: resume analysis + `POST /upload/resume` and `POST /resume/analyze`; build a temporary `Worker` profile from extracted skills/experience; return Top-N tasks with reasons; include a draft `Worker` payload. **Do not use monthly/hourly expected pay directly as per-task pay**: if the period is 月/小时 — including label forms `月薪`, `时薪`, `期望月薪`, `期望时薪` — set `Worker.expected_pay=0.0` (unknown per-task) or convert to a per-task/day rate, and keep the raw figure only in the analysis payload.
- 22d: frontend with two cards/tabs ("上传任务书" and "输入/上传简历"), text preview, extracted fields/profile, Top-N results, and confirm-to-create.
- 22e: unit + API tests; document optional PDF/DOCX dependencies and the no-persistence rule.

**Acceptance:** `.txt`/`.md` work without optional deps; `.pdf`/`.docx` work when extras are installed and return a clear 422 otherwise; the 10 MB limit is enforced **before form parsing** (ASGI Content-Length + streamed-byte count, no oversized temp-file spool); ZIP/PDF expansion is bounded before full parse; no auto-write; task upload returns Top-N workers; resume paste/upload returns Top-N tasks; monthly pay is not used as per-task pay; tests pass. `python-multipart` is required for FastAPI uploads and must be added to `requirements.txt`.

---

## Self-Review Checklist

Before handing off the plan, verify:

- [x] **Spec coverage:** every spec section maps to at least one task:
  - §3 strict evaluation → Tasks 6–7, 20
  - §5 data model → Task 1
  - §6 events → Tasks 2–4, 18
  - §7 propensity → Task 5
  - §8 seven-dim features → Tasks 10–14
  - §9 semantic → Task 9
  - §10 learning/calibration → Tasks 15–17
  - §11 API → Task 18
  - §12 engineering → Tasks 1–19
  - §13 tests → every task
  - §14 phases → task order
  - §15 risks → Review Focus + leakage tests
  - §16 non-goals → Global Constraints
  - §17 defaults → task values
- [x] **Step scan:** each step names one action with a checkable result.
- [x] **Type consistency:** `Impression`, `RecommendationEvent`, `EventService`, `SemanticMatcher`, `PairwiseChoiceLearner`, `ListwiseChoiceLearner`, `PlattCalibrator`, `WeightBindingReport` names are used consistently across tasks.
- [x] **Review Focus:** the five failure modes have owning tests:
  - tiny pools → Task 5/7
  - cold start → Task 10/12/13
  - duplicate/out-of-order events → Task 2/15/18
  - missing dependency/fields → Task 9/10
  - test leakage → Task 3/6
- [x] **Proportion:** this plan describes interfaces, tests, and exact values; it does not paste full implementations.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-13-recommendation-improvement.md`.

This directory is not a git repository, so there is no branch to create and no commit steps. The executor should treat each task’s full-suite run as the checkpoint.

Recommended execution: **subagent-driven** — the tasks depend on each other’s interfaces (`Impression`/`RecommendationEvent`/features/choice learner), and a fresh reviewer per task catches interface drift before it compounds. If the user prefers speed, native execution is acceptable, but the interface-heavy Tasks 1, 15, and 18 should still be reviewed carefully.
