## Task 23: Natural Language Processing Enhancement

**Goal:** Improve classification, field extraction, skill/resume parsing, keyword extraction, calibration, and explainability **without an LLM**. Execution order: after Task 20, before Task 21/22 (both reuse this layer).

**Files:**
- Create: `app/nlp/normalize.py`, `app/nlp/tokenizer.py`, `app/nlp/sections.py`, `scripts/evaluate_nlp.py`, `tests/test_nlp_normalize.py`, `tests/test_nlp_extract.py`, `tests/test_nlp_sections.py`, `tests/test_nlp_eval.py`
- Modify: `app/nlp/classifier.py`, `app/nlp/lexicon.py`, `app/main.py` (only `/classify` response fields), `frontend/app.js` (confidence/correction display), `requirements.txt` (document optional `jieba`/`sklearn-crfsuite`)
- Data: `data/lexicon/skills.txt`, `roles.txt`, `industries.txt`, `aliases.txt`, `stopwords.txt`, `jieba_userdict.txt`

**Interfaces:**
- `normalize_text(text: str) -> str` — NFKC, full/half width, whitespace, punctuation.
- `tokenize(text) -> list[str]`, `content_words(text) -> list[str]`, `keywords(text, top_k=10) -> list[str]` — optional jieba with custom dictionary; fallback to char n-grams when unavailable.
- `extract_fields_v2(text) -> dict` — budget/duration/date/remote/count/experience/language/skills, each with value, confidence, and evidence span; post-validate min≤max, deadline>now, skills in taxonomy.
- `parse_resume_sections(text) -> dict` — education/work/projects/skills/certificates/languages; extract titles, companies, dates, experience years.
- `classify_task(text) -> dict` — existing top-3 + confidence + `needs_clarification`; add calibrated probabilities.
- `evaluate_nlp(records) -> dict` — per-field P/R/F1, category top-1/top-3/macro-F1, ECE/Brier, clarification rate, wrong-confident rate, paraphrase/typo slices.

**Tasks:**
- 23a: normalization + alias/synonym lexicon + optional jieba tokenizer with char-ngram fallback.
- 23b: field extraction v2 with evidence spans and validation.
- 23c: hybrid char+word classifier features, Platt/isotonic calibration, per-category thresholds, confidence gating.
- 23d: resume section parser + skill/experience extraction (dictionary + optional char-BIO CRF).
- 23e: NLP evaluation script and report; include a hand-written/paraphrased holdout **and a hard category slice where the discriminating lexicon keyword is removed or replaced while the meaning is kept**. Report easy vs hard slices separately. Do not claim category targets from the easy slice alone. If the hard slice does not support the target, mark it NOT DEMONSTRATED.
- 23f: integrate into `/classify` and Task 22 upload/resume analysis; frontend shows per-field confidence and allows correction.

**Acceptance:** no new required dependencies (`jieba`, `sklearn-crfsuite` optional with fallback); budget/duration/date/remote F1 on a labeled holdout ≥ 0.90; category top-1 ≥ baseline + 3pp and top-3 ≥ 0.95 **on the hard slice**, macro-F1 ≥ 0.80 **on the hard slice**; ECE ≤ 0.10 only when a fitted calibrator is used — if a fixed prior fallback is used, mark it "met numerically only / not demonstrated"; clarification rate ≤ 15% with wrong-confident rate < 5%. If a hard-slice target is unmet, report NOT DEMONSTRATED rather than claiming success.

---

