"""Deterministic text normalization for Chinese/English task postings.

No LLM is used. The goal is a canonical surface so that downstream lexicons,
tokenizers, and regex extractors see consistent text:

* Unicode NFKC (which also maps most full-width Latin/digits to half-width),
* explicit full-width / half-width cleanup for characters NFKC leaves alone,
* whitespace collapsing,
* punctuation normalization (dashes, ellipsis, curly quotes).

The function is deliberately pure and case-preserving: callers that want a
case-folded surface (keyword matching, vocabulary lookup) call ``.lower()``
themselves.
"""

from __future__ import annotations

import re
import unicodedata

_FULLWIDTH_TO_HALFWIDTH = str.maketrans(
    {
        "　": " ",  # ideographic space -> ASCII space
        "！": "!",
        "＂": '"',
        "＃": "#",
        "＄": "$",
        "％": "%",
        "＆": "&",
        "＇": "'",
        "（": "(",
        "）": ")",
        "＊": "*",
        "＋": "+",
        "，": ",",
        "－": "-",
        "．": ".",
        "／": "/",
        "：": ":",
        "；": ";",
        "＜": "<",
        "＝": "=",
        "＞": ">",
        "？": "?",
        "＠": "@",
        "［": "[",
        "＼": "\\",
        "］": "]",
        "＾": "^",
        "＿": "_",
        "｀": "`",
        "｛": "{",
        "｜": "|",
        "｝": "}",
    }
)

_DASH_TRANSLATION = str.maketrans(
    {
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "―": "-",  # horizontal bar
        "−": "-",  # minus sign
        "﹘": "-",  # small em dash
        "﹣": "-",  # small hyphen-minus
        "－": "-",  # fullwidth hyphen-minus
        "〜": "~",  # wave dash
        "∼": "~",  # tilde operator
        "～": "~",  # fullwidth tilde
    }
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Return a canonical, whitespace-collapsed copy of ``text``.

    NFKC handles compatibility characters (including most full-width ASCII),
    then a small explicit table covers the remaining full-width forms. Dashes
    and tildes are collapsed to ``-`` / ``~`` so budget ranges written with
    ``–``, ``—``, ``～`` still match the same regular expressions. Whitespace
    runs become single spaces and leading/trailing whitespace is removed.
    """
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text))
    value = value.translate(_FULLWIDTH_TO_HALFWIDTH)
    value = value.translate(_DASH_TRANSLATION)
    value = value.replace("…", "...")  # horizontal ellipsis
    value = _WHITESPACE_RE.sub(" ", value)
    return value.strip()
