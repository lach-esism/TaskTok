"""Hybrid task-text classification and structured-field extraction.

No LLM is used. The classifier combines:

1. a weighted lexicon (explainable, strong on short posts), and
2. character 2-4 gram TF-IDF + multinomial logistic regression (robust to
   unseen phrasing without needing a Chinese word segmenter).

The two distributions are blended. A low-margin prediction is marked as
needing clarification instead of being forced into one category.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.domain import Task
from app.nlp.lexicon import (
    CATEGORY_KEYWORDS,
    CATEGORY_LABELS,
    SKILL_KEYWORDS,
)

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
    return unicodedata.normalize("NFKC", text or "").lower()


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


class TaskTextClassifier:
    """Blend a lexicon scorer with a char n-gram linear model."""

    def __init__(self, alpha: float = 0.6) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be between 0 and 1")
        self.alpha = alpha
        self.vectorizer: TfidfVectorizer | None = None
        self.model: LogisticRegression | None = None
        self.classes_: list[str] = []

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
        matrix = self.vectorizer.fit_transform(texts)
        self.model = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            C=4.0,
        )
        self.model.fit(matrix, labels)
        self.classes_ = [str(label) for label in self.model.classes_]
        return self

    def _ml_probabilities(self, text: str) -> dict[str, float]:
        if self.model is None or self.vectorizer is None:
            raise RuntimeError("classifier is not fitted")
        matrix = self.vectorizer.transform([_normalize(text)])
        probabilities = self.model.predict_proba(matrix)[0]
        return {
            category: float(probability)
            for category, probability in zip(
                self.classes_, probabilities, strict=True
            )
        }

    def predict(self, text: str, top_k: int = 3) -> dict:
        if not text or not text.strip():
            raise ValueError("text is required")
        top_k = max(1, min(int(top_k), 6))

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
        ordered = sorted(blended.items(), key=lambda item: (-item[1], item[0]))
        top = ordered[:top_k]
        top_score = top[0][1]
        margin = top_score - (top[1][1] if len(top) > 1 else 0.0)

        return {
            "category": top[0][0],
            "label": CATEGORY_LABELS.get(top[0][0], top[0][0]),
            "confidence": round(top_score, 4),
            "margin": round(margin, 4),
            "needs_clarification": margin < 0.08 or top_score < 0.18,
            "candidates": [
                {
                    "category": category,
                    "label": CATEGORY_LABELS.get(category, category),
                    "confidence": round(score, 4),
                }
                for category, score in top
            ],
            "extracted": extract_fields(text),
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
