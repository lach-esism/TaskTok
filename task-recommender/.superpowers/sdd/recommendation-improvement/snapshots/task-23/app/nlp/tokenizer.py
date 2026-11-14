"""Word segmentation for Chinese/English task text.

``jieba`` is an *optional* dependency. When it is installed the tokenizer
segments Chinese text with ``jieba`` and a custom user dictionary loaded from
``data/lexicon/jieba_userdict.txt`` (skill/role/industry terms that jieba would
otherwise split). When ``jieba`` is missing the module falls back to a
character bigram tokenizer: overlapping CJK bigrams plus whole Latin words.
The fallback keeps ``tokenize`` / ``content_words`` / ``keywords`` usable in a
dependency-free environment.

The import is lazy: importing this module never imports ``jieba``.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.nlp.normalize import normalize_text

LEXICON_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "lexicon"

_CJK_RUN_RE = re.compile(r"[一-鿿]+")
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_SPLIT_RE = re.compile(r"[^\w一-鿿]+", re.UNICODE)

#: Single-character tokens that never carry topical signal on their own.
_DEFAULT_STOPWORDS = frozenset(
    {
        "的", "了", "和", "与", "及", "或", "要", "在", "是", "有", "为",
        "对", "把", "被", "让", "给", "请", "帮", "做", "一个", "一些",
        "这个", "那个", "我们", "你们", "他们", "我", "你", "他", "她",
        "它", "可以", "需要", "希望", "能够", "进行", "负责", "完成",
        "the", "a", "an", "and", "or", "of", "to", "for", "with", "in",
        "on", "is", "are", "be", "we", "you", "it",
    }
)

_STOPWORDS_CACHE: frozenset[str] | None = None
_USER_DICT_CACHE: list[str] | None = None


def _read_lines(filename: str) -> list[str]:
    path = LEXICON_DIR / filename
    if not path.exists():
        return []
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _load_stopwords() -> frozenset[str]:
    global _STOPWORDS_CACHE
    if _STOPWORDS_CACHE is None:
        extra = set(_DEFAULT_STOPWORDS)
        for line in _read_lines("stopwords.txt"):
            # ``word`` or ``word  freq``
            extra.add(line.split()[0])
        _STOPWORDS_CACHE = frozenset(extra)
    return _STOPWORDS_CACHE


def _load_userdict() -> list[str]:
    global _USER_DICT_CACHE
    if _USER_DICT_CACHE is None:
        words: list[str] = []
        for line in _read_lines("jieba_userdict.txt"):
            words.append(line.split()[0])
        # Also seed the dictionary with the taxonomy files so that skill and
        # role phrases survive segmentation even without an explicit entry.
        for filename in ("skills.txt", "roles.txt", "industries.txt"):
            for line in _read_lines(filename):
                first = line.split("\t", 1)[0].strip()
                if first:
                    words.append(first)
        _USER_DICT_CACHE = list(dict.fromkeys(words))
    return _USER_DICT_CACHE


_JIEBA = None
_JIEBA_PROBED = False


def jieba_available() -> bool:
    """Whether the optional ``jieba`` segmenter can be imported."""
    return _get_jieba() is not None


def _get_jieba():
    """Return the lazily imported ``jieba`` module, or ``None`` if missing."""
    global _JIEBA, _JIEBA_PROBED
    if not _JIEBA_PROBED:
        _JIEBA_PROBED = True
        try:
            import jieba  # type: ignore
        except ImportError:
            _JIEBA = None
        else:
            for word in _load_userdict():
                try:
                    jieba.add_word(word, freq=100000, tag="nz")
                except Exception:  # noqa: BLE001 - a bad dict entry is cosmetic
                    pass
            _JIEBA = jieba
    return _JIEBA


def _fallback_tokens(text: str) -> list[str]:
    """Overlapping CJK bigrams plus whole Latin tokens (no ``jieba``)."""
    lowered = text.lower()
    tokens: list[str] = []
    for segment in _SPLIT_RE.split(lowered):
        if not segment:
            continue
        position = 0
        for match in _CJK_RUN_RE.finditer(segment):
            if match.start() > position:
                tokens.extend(
                    _LATIN_TOKEN_RE.findall(segment[position : match.start()])
                )
            run = match.group(0)
            if len(run) == 1:
                tokens.append(run)
            else:
                tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
            position = match.end()
        if position < len(segment):
            tokens.extend(_LATIN_TOKEN_RE.findall(segment[position:]))
    return [token for token in tokens if token]


def tokenize(text: str | None) -> list[str]:
    """Segment ``text`` into tokens.

    Uses ``jieba`` with the custom dictionary when available; otherwise falls
    back to overlapping CJK bigrams plus Latin words.
    """
    normalized = normalize_text(text)
    if not normalized:
        return []
    jieba = _get_jieba()
    if jieba is not None:
        return [
            token.strip()
            for token in jieba.cut(normalized, cut_all=False)
            if token.strip()
        ]
    return _fallback_tokens(normalized)


def _is_stopword(token: str) -> bool:
    stopwords = _load_stopwords()
    if token in stopwords:
        return True
    return False


def content_words(text: str | None) -> list[str]:
    """Tokens that carry topical signal (stopwords and stray digits removed).

    With the bigram fallback, single CJK characters are dropped because a lone
    character is rarely a stable keyword; Latin words and multi-character
    tokens are kept.
    """
    words: list[str] = []
    for token in tokenize(text):
        if _is_stopword(token):
            continue
        if len(token) == 1 and _CJK_RUN_RE.fullmatch(token):
            continue
        if len(token) == 1 and not token.isalnum():
            continue
        if token.isdigit():
            continue
        words.append(token)
    return words


def keywords(text: str | None, top_k: int = 10) -> list[str]:
    """Return up to ``top_k`` high-signal tokens ranked by frequency.

    Longer tokens are preferred on ties, so a segmented full word outranks a
    bigram substring that happens to occur equally often. The list is
    deterministic for a given input.
    """
    top_k = max(1, int(top_k))
    counts: Counter[str] = Counter(content_words(text))
    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], -len(item[0]), item[0]),
    )
    return [word for word, _ in ranked[:top_k]]
