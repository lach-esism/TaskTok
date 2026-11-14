"""Lightweight, non-LLM natural-language utilities for task postings."""

from app.nlp.classifier import (
    TaskTextClassifier,
    extract_fields,
    get_default_classifier,
)

__all__ = [
    "TaskTextClassifier",
    "extract_fields",
    "get_default_classifier",
]
