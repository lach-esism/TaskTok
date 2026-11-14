"""Hybrid task-text classification and structured-field extraction.

No LLM is used. The classifier combines:

1. a weighted lexicon (explainable, strong on short posts),
2. character 2-4 gram TF-IDF + multinomial logistic regression (robust to
   unseen phrasing without needing a Chinese word segmenter), and
3. optional word 1-2 gram TF-IDF features when ``jieba`` is available.

The two (or three) distributions are blended. Top-1 confidence is then
calibrated (Platt) on out-of-fold blended scores so ``confidence`` reflects
``P(top-1 correct)``, and a per-category threshold gates a low-margin or
low-confidence prediction into ``needs_clarification`` instead of forcing it
into one category.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Iterable
from datetime import datetime

from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.domain import Task
from app.learning.calibration import PlattCalibrator
from app.nlp.extract import extract_fields_v2
from app.nlp.lexicon import (
    CATEGORY_KEYWORDS,
    CATEGORY_LABELS,
    SKILL_KEYWORDS,
)
from app.nlp.normalize import normalize_text

SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_BUDGET_RANGE_RE = re.compile(
    rf"({_NUM})\s*(万)?\s*元?\s*(?:[-–—~～至到])\s*"
    rf"({_NUM})\s*(万)?\s*元?"
)
_BUDGET_SINGLE_RE = re.compile(
    rf"(?:预算|报酬|薪酬|费用|价格)\s*(?:为|是|约|：|:)?\s*"
    rf"({_NUM})\s*(万)?\s*元?"
)
_DAYS_RE = re.compile(r"([一二三四五六七八九十两\d]+)\s*天(?:内|以内)?")
_WEEKS_RE = re.compile(
    r"([一二三四五六七八九十两\d]+)\s*(?:周|星期)(?:内|以内)?"
)
_ISO_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?")
_CN_MONTH_DAY_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")

_REQUIREMENT_CUES = (
    "需要",
    "需",
    "要求",
    "熟悉",
    "经验",
    "能",
    "可",
    "优先",
    "负责",
    "完成",
    "交付",
    "具备",
    "有相关",
    "独立",
    "配合",
    "接受",
)

_REMOTE_CUES = ("远程", "线上", "居家", "异地")
_ONSITE_CUES = ("现场", "线下", "驻场", "到岗", "坐班")


def _normalize(text: str) -> str:
    return normalize_text(text or "").lower()


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(text or "") if part.strip()]


def _amount(number: str, ten_thousand: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * (10000.0 if ten_thousand else 1.0)


def _extract_budget(text: str) -> tuple[float | None, float | None]:
    match = _BUDGET_RANGE_RE.search(text)
    if match:
        low = _amount(match.group(1), match.group(2))
        high = _amount(match.group(3), match.group(4))
        # "1-2 万" means both ends are in 万; share the unit when only one
        # side states it.
        if match.group(4) and not match.group(2):
            low *= 10000.0
        elif match.group(2) and not match.group(4):
            high *= 10000.0
        low, high = sorted((low, high))
        return low, high

    match = _BUDGET_SINGLE_RE.search(text)
    if match:
        value = _amount(match.group(1), match.group(2))
        return value, value
    return None, None


_CN_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _to_int(token: str) -> int:
    if token.isdigit():
        return int(token)
    if token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if "十" in token:
        head, _, tail = token.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return 0


def _extract_duration_days(text: str) -> int | None:
    match = _DAYS_RE.search(text)
    if match:
        return _to_int(match.group(1))
    match = _WEEKS_RE.search(text)
    if match:
        return _to_int(match.group(1)) * 7
    return None


def _extract_dates(text: str) -> list[str]:
    dates: list[str] = []
    for year, month, day in _ISO_DATE_RE.findall(text):
        dates.append(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    for month, day in _CN_MONTH_DAY_RE.findall(text):
        value = f"{int(month):02d}-{int(day):02d}"
        if not any(item.endswith(value) for item in dates):
            dates.append(value)
    return dates


def _extract_requirements(sentences: Iterable[str]) -> list[str]:
    requirements: list[str] = []
    for sentence in sentences:
        lowered = _normalize(sentence)
        if len(sentence) < 4:
            continue
        if not any(cue in lowered for cue in _REQUIREMENT_CUES):
            continue
        if sentence not in requirements:
            requirements.append(sentence)
    return requirements[:10]


def _extract_skills(text: str) -> tuple[list[str], dict[str, list[str]]]:
    lowered = _normalize(text)
    evidence: dict[str, list[str]] = {}
    for skill, phrases in SKILL_KEYWORDS.items():
        matched = [phrase for phrase in phrases if phrase in lowered]
        if matched:
            evidence[skill] = matched
    return sorted(evidence), evidence


_TITLE_PREFIXES = (
    "我们需要",
    "我们要",
    "我需要",
    "我想要",
    "请帮我们",
    "帮我",
    "请",
)


def _suggested_title(sentences: list[str], fallback: str) -> str:
    first = sentences[0] if sentences else fallback.strip()
    for prefix in _TITLE_PREFIXES:
        if first.startswith(prefix):
            first = first[len(prefix):]
            break
    clause = re.split(r"[，,]", first)[0].strip()
    return (clause or first)[:40]


def extract_fields(text: str) -> dict:
    """Turn a free-form posting into the fields the recommender needs."""
    normalized = _normalize(text)
    sentences = split_sentences(text)
    budget_min, budget_max = _extract_budget(normalized)
    duration_days = _extract_duration_days(normalized)

    remote_ok: bool | None = None
    if any(cue in normalized for cue in _REMOTE_CUES):
        remote_ok = True
    elif any(cue in normalized for cue in _ONSITE_CUES):
        remote_ok = False

    skills, skill_evidence = _extract_skills(normalized)

    return {
        "suggested_title": _suggested_title(sentences, text),
        "budget_min": budget_min,
        "budget_max": budget_max,
        "budget": (
            round((budget_min + budget_max) / 2, 2)
            if budget_min is not None and budget_max is not None
            else None
        ),
        "duration_days": duration_days,
        "dates": _extract_dates(normalized),
        "remote_ok": remote_ok,
        "requirements": _extract_requirements(sentences),
        "skills": skills,
        "skill_evidence": skill_evidence,
    }


def rule_scores(text: str) -> dict[str, float]:
    """Weighted keyword hits per category, before normalization."""
    lowered = _normalize(text)
    scores = {category: 0.0 for category in CATEGORY_KEYWORDS}
    for category, keywords in CATEGORY_KEYWORDS.items():
        for phrase, weight in keywords.items():
            count = lowered.count(phrase)
            if count:
                scores[category] += weight * min(count, 2)
    return scores


def _task_text(task: Task) -> str:
    parts = [task.title, task.description, *task.requirements]
    return "。".join(part for part in parts if part)


def _jieba_available() -> bool:
    try:
        import jieba  # noqa: F401
    except ImportError:
        return False
    return True


def _word_analyzer(text: str) -> list[str]:
    from app.nlp.tokenizer import tokenize

    return tokenize(text)


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


class _PriorCalibrator:
    """Fixed prior mapping used only when no negatives are observable.

    The synthetic training corpus is saturated (100% out-of-fold top-1), so a
    Platt/isotonic fit has no negative class to learn from. This prior maps the
    classifier's observed correct-score band (>= ~0.3 blended mass) to high
    confidence and the near-zero ambiguous band to low confidence. It is a
    documented fallback, not a fit; real calibration is used whenever the
    training corpus contains errors.
    """

    def __init__(self, scale: float = 20.0, offset: float = 0.20) -> None:
        self.scale = scale
        self.offset = offset

    def predict(self, score: float) -> float:
        value = _sigmoid(self.scale * (float(score) - self.offset))
        return max(0.0, min(1.0, value))


class TaskTextClassifier:
    """Blend a lexicon scorer with char (+ optional word) n-gram models.

    ``predict`` returns the existing top-k surface plus calibrated confidence,
    a per-category confidence threshold, lexicon evidence for the top category,
    and ``extracted_v2`` (evidence-bearing fields). Calibration is computed
    out-of-fold during :meth:`fit` so the reported confidence is honest on
    unseen text.
    """

    def __init__(self, alpha: float = 0.6, calibrate: bool = True) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be between 0 and 1")
        self.alpha = alpha
        self.calibrate = calibrate
        self.vectorizer: TfidfVectorizer | None = None
        self.word_vectorizer: TfidfVectorizer | None = None
        self.model: LogisticRegression | None = None
        self.classes_: list[str] = []
        self.calibrator: PlattCalibrator | None = None
        self.calibration_method = "none"  # "platt" | "prior" | "none"
        self.default_threshold = 0.5
        self.min_threshold = 0.4
        self.max_threshold = 0.8
        self.thresholds: dict[str, float] = {}

    def fit(self, tasks: Iterable[Task]) -> "TaskTextClassifier":
        tasks = list(tasks)
        if len(tasks) < 2:
            raise ValueError("at least two labeled tasks are required")
        texts = [_normalize(_task_text(task)) for task in tasks]
        labels = [task.category for task in tasks]
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            min_df=1,
            sublinear_tf=True,
        )
        matrices = [self.vectorizer.fit_transform(texts)]
        self.word_vectorizer = None
        if _jieba_available():
            self.word_vectorizer = TfidfVectorizer(
                analyzer=_word_analyzer,
                ngram_range=(1, 2),
                min_df=1,
                sublinear_tf=True,
            )
            matrices.append(self.word_vectorizer.fit_transform(texts))
        matrix = sparse.hstack(matrices) if len(matrices) > 1 else matrices[0]
        self.model = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            C=4.0,
        )
        self.model.fit(matrix, labels)
        self.classes_ = [str(label) for label in self.model.classes_]
        self._fit_calibration(tasks, labels)
        return self

    # ------------------------------------------------------------------
    # Probabilities and ranking
    # ------------------------------------------------------------------
    def _ml_probabilities(self, text: str) -> dict[str, float]:
        if self.model is None or self.vectorizer is None:
            raise RuntimeError("classifier is not fitted")
        normalized = _normalize(text)
        matrices = [self.vectorizer.transform([normalized])]
        if self.word_vectorizer is not None:
            matrices.append(self.word_vectorizer.transform([normalized]))
        matrix = sparse.hstack(matrices) if len(matrices) > 1 else matrices[0]
        probabilities = self.model.predict_proba(matrix)[0]
        return {
            category: float(probability)
            for category, probability in zip(
                self.classes_, probabilities, strict=True
            )
        }

    def _rank(self, text: str) -> list[tuple[str, float]]:
        """Blended scores ordered by descending confidence."""
        ml_probs = self._ml_probabilities(text)
        raw_rules = rule_scores(text)
        rule_total = sum(raw_rules.values())
        rule_probs = (
            {category: score / rule_total for category, score in raw_rules.items()}
            if rule_total > 0
            else {}
        )
        categories = set(ml_probs) | set(rule_probs)
        blended = {
            category: self.alpha * ml_probs.get(category, 0.0)
            + (1.0 - self.alpha) * rule_probs.get(category, 0.0)
            for category in categories
        }
        return sorted(blended.items(), key=lambda item: (-item[1], item[0]))

    # ------------------------------------------------------------------
    # Calibration and confidence gating
    # ------------------------------------------------------------------
    def _fit_calibration(self, tasks: list[Task], labels: list[str]) -> None:
        self.calibrator = None
        self.calibration_method = "none"
        self.thresholds = {
            category: self.default_threshold for category in self.classes_
        }
        if not self.calibrate:
            return
        if len(tasks) < 40 or len(set(labels)) < 3:
            return

        from sklearn.model_selection import StratifiedKFold

        splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        all_scores: list[float] = []
        all_correct: list[int] = []
        all_by_category: dict[str, list[tuple[float, bool]]] = {}
        for train_index, test_index in splitter.split(tasks, labels):
            if not len(train_index) or not len(test_index):
                continue
            fold_model = TaskTextClassifier(
                alpha=self.alpha, calibrate=False
            ).fit([tasks[index] for index in train_index])
            for index in test_index:
                text = _normalize(_task_text(tasks[index]))
                label = labels[index]
                variants = [text] + self._perturb_variants(text)
                for variant in variants:
                    try:
                        ordered = fold_model._rank(variant)
                    except Exception:  # noqa: BLE001 - a bad variant is cosmetic
                        continue
                    top_category, top_score = ordered[0]
                    correct = top_category == label
                    all_scores.append(top_score)
                    all_correct.append(1 if correct else 0)
                    all_by_category.setdefault(label, []).append(
                        (top_score, correct)
                    )

        if len(set(all_correct)) < 2 or len(all_scores) < 10:
            # No negative class anywhere: fall back to the documented prior so
            # confidence stays meaningful on saturated synthetic training data.
            self.calibrator = _PriorCalibrator()
            self.calibration_method = "prior"
            self.thresholds = {
                category: self.default_threshold for category in self.classes_
            }
            return
        self.calibrator = PlattCalibrator().fit(all_scores, all_correct)
        self.calibration_method = "platt"
        self.thresholds = {
            category: self._category_threshold(all_by_category.get(category, []))
            for category in self.classes_
        }

    _NOISE_CHARS = "的了是在有一个和人"

    def _perturb_variants(self, text: str) -> list[str]:
        """Deterministic degraded copies of ``text`` for calibration.

        Variants are scored with the *fold* model (out-of-fold), never the
        fully fitted model, so calibration never leaks training labels. The
        keyword-removal variant is the strongest: it strips the single most
        heavily weighted lexicon cue, which is exactly the distribution a
        saturated corpus fails to cover.
        """
        rng = random.Random(f"nlp-calibration|{text}")
        variants: list[str] = []
        cjk_positions = [
            position
            for position, char in enumerate(text)
            if "一" <= char <= "鿿"
        ]
        if len(cjk_positions) >= 2:
            position = rng.choice(cjk_positions)
            variants.append(text[:position] + text[position + 1:])  # deletion
            position = rng.choice(cjk_positions)
            variants.append(
                text[:position] + rng.choice(self._NOISE_CHARS) + text[position + 1:]
            )  # substitution
        without_keyword = self._remove_top_keyword(text)
        if without_keyword and without_keyword != text:
            variants.append(without_keyword)
        return variants

    @staticmethod
    def _remove_top_keyword(text: str) -> str | None:
        best_weight = -1.0
        best_phrase: str | None = None
        for keywords in CATEGORY_KEYWORDS.values():
            for phrase, weight in keywords.items():
                if phrase in text and weight > best_weight:
                    best_weight = weight
                    best_phrase = phrase
        if best_phrase is None:
            return None
        return text.replace(best_phrase, "", 1)

    def _category_threshold(
        self, pairs: list[tuple[float, bool]]
    ) -> float:
        """Lowest calibrated confidence whose precision is >= 0.9.

        Falls back to the category's median correct confidence (clamped) when
        the category has too few or too clean observations to estimate a
        meaningful precision point.
        """
        if len(pairs) < 6:
            return self.default_threshold
        scored = [(self._calibrate(score), correct) for score, correct in pairs]
        scored.sort(key=lambda item: -item[0])
        correct_count = 0
        for index, (confidence, correct) in enumerate(scored, start=1):
            if correct:
                correct_count += 1
            if index >= 3 and correct_count / index >= 0.9:
                return max(self.min_threshold, min(self.max_threshold, confidence))
        correct_confs = [confidence for confidence, correct in scored if correct]
        fallback = (
            sorted(correct_confs)[len(correct_confs) // 2]
            if correct_confs
            else self.default_threshold
        )
        return max(self.min_threshold, min(self.max_threshold, fallback))

    def _calibrate(self, score: float) -> float:
        if self.calibrator is None:
            return score
        return self.calibrator.predict(score)

    def _evidence(self, text: str, category: str) -> list[dict]:
        lowered = _normalize(text)
        matched = [
            {"phrase": phrase, "weight": weight}
            for phrase, weight in CATEGORY_KEYWORDS.get(category, {}).items()
            if phrase in lowered
        ]
        matched.sort(key=lambda item: -item["weight"])
        return matched[:12]

    # ------------------------------------------------------------------
    # Public prediction
    # ------------------------------------------------------------------
    def predict(
        self, text: str, top_k: int = 3, now: datetime | None = None
    ) -> dict:
        if not text or not text.strip():
            raise ValueError("text is required")
        top_k = max(1, min(int(top_k), 6))

        ordered = self._rank(text)
        top = ordered[:top_k]
        top_category = top[0][0]
        top_score = top[0][1]
        margin = top_score - (top[1][1] if len(top) > 1 else 0.0)
        calibrated = self._calibrate(top_score)
        threshold = self.thresholds.get(top_category, self.default_threshold)

        return {
            "category": top_category,
            "label": CATEGORY_LABELS.get(top_category, top_category),
            "confidence": round(top_score, 4),
            "calibrated_confidence": round(calibrated, 4),
            "confidence_threshold": round(threshold, 4),
            "margin": round(margin, 4),
            "needs_clarification": (
                margin < 0.08
                or top_score < 0.18
                or calibrated < threshold
            ),
            "candidates": [
                {
                    "category": category,
                    "label": CATEGORY_LABELS.get(category, category),
                    "confidence": round(score, 4),
                }
                for category, score in top
            ],
            "evidence": self._evidence(text, top_category),
            "extracted": extract_fields(text),
            "extracted_v2": extract_fields_v2(text, now=now),
        }


_DEFAULT_CLASSIFIER: TaskTextClassifier | None = None


def get_default_classifier() -> TaskTextClassifier:
    """Fit once on the synthetic labeled postings, then reuse."""
    global _DEFAULT_CLASSIFIER
    if _DEFAULT_CLASSIFIER is None:
        from app.data.synthetic import generate_dataset

        _DEFAULT_CLASSIFIER = TaskTextClassifier().fit(
            generate_dataset().tasks
        )
    return _DEFAULT_CLASSIFIER
