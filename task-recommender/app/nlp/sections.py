"""Resume section parsing: dictionary + rules (no LLM).

``parse_resume_sections`` turns free-form resume text into structured sections
(education / work / projects / skills / certificates / languages) and extracts
titles, companies, dates and experience years where possible. Parsing is
dictionary + rule based so it runs with zero optional dependencies.

An optional character-level BIO CRF path is provided for callers that have
``sklearn-crfsuite`` *and* a trained model artifact at
``data/lexicon/resume_crf.pkl``. It is a dormant optional path: the import is
lazy and the rules fall back automatically when the package or artifact is
missing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from app.nlp.lexicon import normalize_skill
from app.nlp.normalize import normalize_text

LEXICON_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "lexicon"

_SECTION_HEADERS = {
    "education": ("教育经历", "教育背景", "教育", "学历", "学习经历"),
    "work": ("工作经历", "工作经验", "职业经历", "工作", "任职经历"),
    "projects": ("项目经历", "项目经验", "项目"),
    "skills": ("技能", "专业技能", "技能特长", "技术栈", "擅长"),
    "certificates": ("证书", "认证", "资格证书", "证书与认证"),
    "languages": ("语言", "语言能力", "外语"),
}

_HEADER_RE = re.compile(r"^[#\s]*([^#:：\s].*?)[:：]?\s*$")

_YEAR_RANGE_RE = re.compile(
    r"(20\d{2})\s*年?\s*(?:[-–—~至到]|/)\s*(至今|现在|20\d{2})\s*年?"
)
_YEARS_EXPERIENCE_RE = re.compile(
    r"([\d一二两三四五六七八九十]+)\s*年[^，。；;！？!?\n]{0,14}?经验"
)

_DEGREES = ("博士", "硕士", "学士", "本科", "大专", "中专", "高中")
_DEGREE_RE = re.compile("|".join(_DEGREES))
_SCHOOL_RE = re.compile(r"[一-鿿A-Za-z0-9]{2,20}(?:大学|学院|研究院|研究所)")

_COMPANY_HINTS = (
    "公司", "集团", "科技", "网络", "软件", "工作室", "事务所", "银行",
    "研究院", "研究所", "厂", "中心", "平台", "咨询", "实验室", "文化",
)
_TITLE_HINTS = (
    "工程师", "设计师", "经理", "主管", "负责人", "顾问", "编辑", "总监",
    "运营", "策划", "分析师", "讲师", "翻译", "研究员", "架构师", "产品",
)

_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# --------------------------------------------------------------------------
# Optional char-BIO CRF (dormant unless sklearn-crfsuite + model exist)
# --------------------------------------------------------------------------
_CRF_PROBED = False
_CRF_AVAILABLE: bool | None = None


def crf_available() -> bool:
    global _CRF_PROBED, _CRF_AVAILABLE
    if not _CRF_PROBED:
        _CRF_PROBED = True
        try:
            import sklearn_crfsuite  # noqa: F401
        except ImportError:
            _CRF_AVAILABLE = False
        else:
            _CRF_AVAILABLE = (LEXICON_DIR / "resume_crf.pkl").exists()
    return bool(_CRF_AVAILABLE)


def _char_features(line: str, index: int) -> dict:
    char = line[index] if 0 <= index < len(line) else ""
    return {
        "c": char,
        "c.lower": char.lower(),
        "c.isdigit": char.isdigit(),
        "c.ispunct": bool(char and not char.isalnum() and not char.isspace()),
        "prev": line[index - 1] if index - 1 >= 0 else "<BOS>",
        "next": line[index + 1] if index + 1 < len(line) else "<EOS>",
    }


def _try_crf_sections(text: str) -> dict | None:
    """Return CRF-derived sections, or ``None`` when unavailable.

    This is intentionally a thin, honest wrapper: without a trained model
    artifact it always returns ``None`` so the dictionary rules take over.
    """
    if not crf_available():
        return None
    try:
        import pickle  # noqa: F401  (stdlib)

        from sklearn_crfsuite import CRF  # type: ignore
    except ImportError:
        return None
    model_path = LEXICON_DIR / "resume_crf.pkl"
    try:
        with model_path.open("rb") as handle:
            model = pickle.load(handle)  # noqa: S301 - local trusted artifact
    except (OSError, ValueError):
        return None
    if not isinstance(model, CRF):
        return None
    lines = [normalize_text(line) for line in str(text).splitlines()]
    lines = [line for line in lines if line]
    sentences = [
        [_char_features(line, index) for index in range(len(line))]
        for line in lines
    ]
    tags = model.predict(sentences)
    # Convert BIO tags back into a coarse section split; the mapping is kept
    # deliberately small and only labels headers, so fallback rules still fill
    # in the entry-level detail.
    sections: dict[str, list[str]] = {}
    for tokens, sequence in zip(lines, tags, strict=False):
        label = next((item for item in sequence if item not in {"O", "B-O", "I-O"}), "O")
        sections.setdefault(label, []).append(tokens)
    if not sections:
        return None
    return sections


# --------------------------------------------------------------------------
# Dictionary + rules parser
# --------------------------------------------------------------------------
def _split_entries(line: str) -> list[str]:
    parts = re.split(r"[|;；·、,，]+", line)
    return [part.strip() for part in parts if part.strip()]


def _tokens(line: str) -> list[str]:
    tokens: list[str] = []
    for chunk in re.split(r"[|;；·、,，]+", line):
        tokens.extend(part for part in chunk.split() if part)
    return tokens


def _years_from_range(text: str, now: datetime) -> float | None:
    match = _YEAR_RANGE_RE.search(text)
    if not match:
        return None
    start = int(match.group(1))
    end = now.year if match.group(2) in {"至今", "现在"} else int(match.group(2))
    return float(max(0, end - start))


def _parse_work_line(line: str, now: datetime) -> dict:
    dates_match = _YEAR_RANGE_RE.search(line)
    dates = dates_match.group(0) if dates_match else ""
    rest = line.replace(dates, " ", 1) if dates else line
    company = ""
    title = ""
    for part in _tokens(rest):
        if not company and any(hint in part for hint in _COMPANY_HINTS):
            company = part
            continue
        if not title and any(hint in part for hint in _TITLE_HINTS):
            title = part
            continue
    if not title and not company:
        tokens = _tokens(rest)
        if tokens:
            title = tokens[-1]
    years = _years_from_range(dates, now) if dates else None
    return {"title": title, "company": company, "dates": dates, "years": years}


def _parse_education_line(line: str) -> dict:
    degree = ""
    school = ""
    major = ""
    dates = ""
    for part in _split_entries(line):
        if not degree:
            match = _DEGREE_RE.search(part)
            if match:
                degree = match.group(0)
        if not school:
            match = _SCHOOL_RE.search(part)
            if match:
                school = match.group(0)
        if _YEAR_RANGE_RE.search(part):
            dates = _YEAR_RANGE_RE.search(part).group(0)
    # Whatever is left over becomes the major.
    leftover = re.sub(r"20\d{2}年?|[–—~至到/-]|至今|现在", "", line)
    for token in (_DEGREES + (school,)):
        if token:
            leftover = leftover.replace(token, "")
    major = re.sub(r"[|;；·、,，\s]+", " ", leftover).strip()
    return {"degree": degree, "school": school, "major": major, "dates": dates}


def _parse_skill_line(line: str) -> dict:
    name = ""
    years: float | None = None
    for part in _split_entries(line):
        match = re.search(r"([\d一二两三四五六七八九十]+)\s*年", part)
        if match:
            years = _to_int(match.group(1))
            part = part[: match.start()].strip()
        if not name and part:
            name = part
    category = normalize_skill(name)
    return {"name": name, "category": category, "years": years}


def _to_int(token: str) -> float | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return float(token)
    if token in _CN_DIGITS:
        return float(_CN_DIGITS[token])
    return None


def parse_resume_sections(
    text: str | None, now: datetime | None = None
) -> dict:
    """Parse free-form resume text into sections with entry-level detail.

    Lines are normalized individually so the newline structure (which defines
    the sections) is preserved while each line's whitespace/punctuation is
    still canonicalized. ``now`` fixes the reference clock for open-ended
    periods such as "至今", so experience years are reproducible in tests.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    lines = [normalize_text(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]

    result: dict[str, list] = {
        "education": [],
        "work": [],
        "projects": [],
        "skills": [],
        "certificates": [],
        "languages": [],
    }
    current: str | None = None
    for line in lines:
        header = _classify_header(line)
        if header:
            current = header
            continue
        if current is None:
            # Before any explicit header, treat lines with dates/titles as work.
            if _YEAR_RANGE_RE.search(line) or any(h in line for h in _TITLE_HINTS):
                current = "work"
            else:
                continue
        if current == "education":
            result["education"].append(_parse_education_line(line))
        elif current == "work":
            result["work"].append(_parse_work_line(line, now))
        elif current == "projects":
            result["projects"].append(_parse_project_line(line))
        elif current == "skills":
            result["skills"].append(_parse_skill_line(line))
        elif current == "certificates":
            result["certificates"].extend(_split_entries(line))
        elif current == "languages":
            result["languages"].extend(_split_entries(line))

    experience_years = _experience_years(" ".join(lines), result["work"])

    return {
        "education": result["education"],
        "work": result["work"],
        "projects": result["projects"],
        "skills": result["skills"],
        "certificates": result["certificates"],
        "languages": result["languages"],
        "experience_years": experience_years,
    }


def _parse_project_line(line: str) -> dict:
    dates_match = _YEAR_RANGE_RE.search(line)
    dates = dates_match.group(0) if dates_match else ""
    rest = line.replace(dates, " ", 1) if dates else line
    role = ""
    for part in _tokens(rest):
        if any(hint in part for hint in _TITLE_HINTS):
            role = part
    name = rest.strip()
    if role and name.endswith(role):
        name = name[: -len(role)].strip()
    return {"name": name, "role": role, "dates": dates}


def _classify_header(line: str) -> str | None:
    if len(line) > 24:
        return None
    for section, keywords in _SECTION_HEADERS.items():
        for keyword in keywords:
            if line == keyword or line.startswith(keyword + "：") or line.startswith(keyword + ":"):
                return section
    return None


def _experience_years(text: str, work: list[dict]) -> float | None:
    match = _YEARS_EXPERIENCE_RE.search(text)
    if match:
        value = _to_int(match.group(1))
        if value is not None:
            return value
    years = [entry.get("years") for entry in work if entry.get("years") is not None]
    if years:
        return round(sum(years), 1)
    return None
