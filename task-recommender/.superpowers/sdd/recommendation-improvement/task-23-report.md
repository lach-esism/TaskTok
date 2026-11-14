# Task 23: Natural Language Processing Enhancement (no LLM)

## Status: DONE_WITH_CONCERNS

## What was implemented

### New modules
- `app/nlp/normalize.py` — `normalize_text` (NFKC, full/half width, whitespace
  collapse, dash/ellipsis punctuation normalization). Pure and case-preserving.
- `app/nlp/tokenizer.py` — `tokenize`, `content_words`, `keywords`, and
  `jieba_available`. `jieba` is a lazy optional import; without it the module
  falls back to overlapping CJK bigrams + whole Latin words. A custom user
  dictionary is loaded from `data/lexicon/jieba_userdict.txt` (seeded from
  skills/roles/industries) only when jieba is present.
- `app/nlp/extract.py` — `extract_fields_v2(text, now=None)` returning
  budget/duration/date/remote/count/experience/language/skills, each as
  `{value, confidence, evidence}`. Post-validation: `min <= max` (swapped when
  reversed), deadline must be `> now`, skills filtered through the taxonomy via
  `normalize_skill`. A currency-unit guard prevents `2026-12-05` date fragments
  from being read as a budget range.
- `app/nlp/sections.py` — `parse_resume_sections(text)` for
  education/work/projects/skills/certificates/languages with titles, companies,
  dates and experience years (dictionary + rules, line-preserving
  normalization). Optional char-BIO CRF path (`crf_available`) is a dormant
  lazy path that requires both `sklearn-crfsuite` and a trained
  `data/lexicon/resume_crf.pkl` artifact; it always returns `None` otherwise.
- `scripts/evaluate_nlp.py` — `evaluate_nlp(records)` reports per-field P/R/F1,
  category top-1/top-3/macro-F1, ECE/Brier, clarification rate, wrong-confident
  rate, and paraphrase/typo/ambiguous slices. Writes `reports/nlp_eval.json` and
  `reports/nlp_eval.md`.

### Modified modules
- `app/nlp/classifier.py` — kept the char 2–4 gram TF-IDF + lexicon blend
  (public behavior and tests unchanged). Added optional word 1–2 gram features
  when jieba is available, out-of-fold Platt calibration, a per-category
  confidence threshold, confidence gating, lexicon `evidence` for the top
  category, `calibrated_confidence`, and `extracted_v2` in the prediction.
- `app/nlp/lexicon.py` — added `normalize_skill`, `normalize_category`,
  `known_skills`, `known_categories` backed by unambiguous keyword phrases plus
  an additive alias file (`data/lexicon/aliases.txt`). No circular imports
  (leaf dependency on `app.nlp.normalize`).
- `app/main.py` — `/classify` only: added a stable additive alias `fields_v2`
  (mirrors `extracted_v2`) for Task 22 to consume; all other additive fields
  (`confidence`, `calibrated_confidence`, `confidence_threshold`, `evidence`,
  `extracted_v2`) flow through from the classifier unchanged.
- `frontend/app.js` — minimal confidence display: the header now shows
  calibrated confidence and renders lexicon evidence chips (no UI redesign).
- `requirements.txt` — documented `jieba` and `sklearn-crfsuite` as optional
  extras; no required dependencies were added.

### Data
- `data/lexicon/`: `skills.txt`, `roles.txt`, `industries.txt`, `aliases.txt`,
  `stopwords.txt`, `jieba_userdict.txt`, and the hand-written holdout
  `nlp_holdout.jsonl` (47 records: 36 paraphrase, 9 typo, 2 ambiguous; 45 with
  category labels; 25 with budget labels, 23 duration, 16 date, 22 remote).

### Tests
- `tests/test_nlp_normalize.py`, `tests/test_nlp_extract.py`,
  `tests/test_nlp_sections.py`, `tests/test_nlp_eval.py`,
  `tests/test_nlp_api.py` (33 new tests). Full suite: **292 passed**.

## Metrics vs targets (measured on the hand-written holdout)

| Target | Result | Met? |
|---|---|---|
| budget/duration/date/remote F1 ≥ 0.90 | 1.00 / 1.00 / 1.00 / 1.00 | Yes |
| Category top-1 ≥ baseline + 3pp | 1.00 (baseline 1.00) | No — see gap |
| Category top-3 ≥ 0.95 | 1.00 | Yes |
| Category macro-F1 ≥ 0.80 | 1.00 | Yes |
| ECE ≤ 0.10 | 0.0112 | Yes |
| Clarification rate ≤ 15% | 0.0426 | Yes |
| Wrong-confident rate < 5% | 0.0000 | Yes |

Non-target fields also all F1 = 1.00 (count/experience/language); skills F1 =
0.76 (micro, 70 TP / 31 FP / 13 FN). The skills F1 gap is label completeness on
the holdout (the extractor returns additional valid taxonomy skills such as
`design`/`analytics` that the hand labels did not enumerate), not an
out-of-taxonomy leak — all extracted skills pass the `known_skills()` filter.

## Gaps / concerns

1. **Top-1 ≥ baseline + 3pp is NOT demonstrated.** In this environment `jieba`
   is not installed, so the optional word-level features are inactive and the
   ranking is unchanged from the pre-task classifier; baseline top-1 and
   enhanced top-1 are both 1.00 on this holdout (delta 0pp). The +3pp target
   is also structurally unattainable on a 45-label holdout whose baseline is
   already saturated. Word features only activate with `jieba`; I could not
   verify that path at runtime (jieba/sklearn-crfsuite are absent and must stay
   optional).
2. **Calibration falls back to a documented prior on this corpus.** The
   synthetic training data is saturated (100% out-of-fold top-1, including
   perturbed copies), so Platt/isotonic has no negative class to fit.
   `_PriorCalibrator` (`sigmoid(20 * (score - 0.20))`) is used instead. This is
   honest for the saturated regime and yields low ECE here, but it would
   over-generalize to a harder corpus; real Platt fitting is used automatically
   whenever negatives exist in training. This is the main reason for the
   DONE_WITH_CONCERNS status.
3. **CRF path is dormant.** There is no trained `resume_crf.pkl`, so the
   optional char-BIO CRF can never activate. The dictionary+rule parser is the
   effective implementation.
4. **Holdout size/coverage is small.** 47 records; field label counts for
   count/experience/language are tiny (3/2/4 positives). The four target fields
   and category metrics are adequately covered.

## Files changed

Created: `app/nlp/normalize.py`, `app/nlp/tokenizer.py`, `app/nlp/extract.py`,
`app/nlp/sections.py`, `scripts/evaluate_nlp.py`, `tests/test_nlp_normalize.py`,
`tests/test_nlp_extract.py`, `tests/test_nlp_sections.py`,
`tests/test_nlp_eval.py`, `tests/test_nlp_api.py`, `data/lexicon/*` (7 files).
Modified: `app/nlp/classifier.py`, `app/nlp/lexicon.py`, `app/main.py`
(`/classify` only), `frontend/app.js` (confidence display only),
`requirements.txt`.

## Concerns for follow-up

- Task 22 should import `from app.nlp.extract import extract_fields_v2` and
  `from app.nlp.sections import parse_resume_sections` directly (the modules are
  importable; `app/nlp/__init__.py` was intentionally left untouched per the
  file allow-list).
- Installing `jieba` would enable word features and give the classifier a
  genuine chance to beat the baseline ranking; re-run `scripts/evaluate_nlp.py`
  in that environment.

---

## FIX REPORT (round 1 review)

Addressed reviewer findings. Corrected verdicts below supersede the first-pass
claims; category and calibration targets are now measured on a hard slice.

### 1. Category evaluation validity — hard slice added
`data/lexicon/nlp_holdout.jsonl` now includes a `slice="hard"` set of 24
hand-written records (2 per category, h200–h223) where the discriminating
lexicon keyword is removed/replaced while the meaning is kept (e.g. "招聘" ->
"物色工程人员", "翻译" -> "改成英文和日文两个版本", "培训" -> "讲一次", "标注" ->
"做标记"). The evaluation reports Easy (paraphrase+typo) and Hard slices
separately.

Category metrics, measured on the hard slice (n=24):

| Metric | Target | Easy | Hard | Verdict |
|---|---|---|---|---|
| Top-1 | ≥ baseline + 3pp | 1.00 | 0.75 (baseline 0.75) | NOT DEMONSTRATED (+0pp) |
| Top-3 | ≥ 0.95 | 1.00 | 0.9583 | PASS |
| Macro-F1 | ≥ 0.80 | 1.00 | 0.7167 | NOT DEMONSTRATED |

The hard slice exposes that the classifier is lexicon-dependent: without the
signature cue it drops to 75% top-1 / 71.7% macro-F1. Top-1 "+3pp over
baseline" is 0pp because word-level features are inactive without `jieba`, so
ranking is unchanged from the pre-task baseline. No +3pp claim is made.

### 2. Calibration claim — annotated and de-leaked
- `evaluate_nlp` now reports `calibration.method` (`platt` / `prior` / `none`)
  and the report/table marks ECE as **fixed prior, NOT DEMONSTRATED**. On the
  hard-inclusive holdout ECE = 0.1334 (> 0.10) and Brier = 0.1322, so the
  numeric target is no longer claimed.
- `_fit_calibration` was restructured: perturbed copies (char deletion,
  substitution, and top-lexicon-keyword removal) are now scored with the
  per-fold out-of-fold model, never the fully fitted model. The old
  `_perturbed_calibration_pairs` (which used `self._rank` on the fully fitted
  model) was removed. On the saturated synthetic corpus even top-4 keyword
  removal yields 100% OOF top-1, so no fitted Platt calibrator is trainable
  from synthetic data and the documented `_PriorCalibrator` fallback remains in
  effect; the de-leaked path will activate automatically on any corpus with
  negatives.

### 3. Skills F1 note
The hand-written `skills` labels were not curated against the taxonomy
(primary skills only; the extractor also returns valid secondary skills such
as `design`/`analytics`). The reported micro F1 0.76 is therefore a **lower
bound**, not a clean target metric; every extracted skill passes the
`known_skills()` taxonomy filter.

### 4. Minor fixes
- Added `tests/test_nlp_extract.py::test_date_fragment_is_not_parsed_as_budget`
  asserting `2026-12-05` yields no budget value and is parsed as the deadline.
- `parse_resume_sections(text, now=None)` now injects a reference clock into
  open-ended "至今" year-range computation; tests pass a fixed `now`.
- `app/nlp/extract.py` placement beyond the brief's create-list is accepted.

### Final metrics (post-fix, hard-inclusive holdout, 71 records / 69 labeled)
- Field F1 (targets ≥ 0.90): budget 1.00, duration 1.00, date 1.00, remote 1.00 — PASS.
- Hard slice category: top-3 0.9583 PASS; top-1 +3pp and macro-F1 ≥ 0.80 NOT DEMONSTRATED.
- Calibration: fixed prior — ECE 0.1334 / Brier 0.1322 NOT DEMONSTRATED.
- Gating: clarification rate 0.169 (> 0.15) and wrong-confident rate 0.058 (> 0.05) — NOT DEMONSTRATED (4 wrong-confident predictions on the hard slice).
- Full test suite: 293 passed.
