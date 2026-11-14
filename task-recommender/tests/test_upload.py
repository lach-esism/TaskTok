"""Unit tests for secure upload text extraction and text analyzers.

These tests cover the four documented formats, the optional-dependency
fallback contract (a clear 422-shaped error instead of ``ImportError``), the
10 MB limit, extension/MIME whitelists, filename sanitization, and the two
analysis functions. No file is written to disk by any path under test.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
import zlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.semantic import SemanticMatcher
from app.upload import extract
from app.upload.analyze import (
    analyze_resume_text,
    analyze_task_text,
    build_task_draft,
    task_from_analysis,
    worker_from_draft,
)
from app.upload.extract import (
    MAX_UPLOAD_BYTES,
    UploadError,
    extract_text,
    sanitize_filename,
)

TASK_TEXT = (
    "我们需要开发一个会员小程序，包含前端页面、接口联调和后台管理，"
    "预算 8000-20000 元，30 天内交付，可以远程。"
)

RESUME_TEXT = """张三
教育经历
复旦大学 计算机科学与技术 本科
工作经历
2020 - 至今 云启科技 后端工程师
负责接口开发与数据库设计
技能
Python、后端开发、数据库、接口、Figma
期望薪资：15000 元/月
上海 · 可远程
"""


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def test_max_upload_limit_is_ten_megabytes():
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024


def test_extract_txt_and_md_native():
    assert extract_text("task.txt", "任务书正文".encode("utf-8")) == "任务书正文"
    assert extract_text("resume.md", "# 简历\n后端工程师".encode("utf-8")) == "# 简历\n后端工程师"


def test_extract_accepts_utf8_bom():
    assert extract_text("task.txt", "\ufeff正文".encode("utf-8")) == "正文"


def test_extract_rejects_unsupported_extension_with_clear_message():
    with pytest.raises(UploadError) as excinfo:
        extract_text("payload.exe", b"MZ binary")
    assert excinfo.value.status_code == 422
    message = str(excinfo.value)
    assert ".txt" in message and ".md" in message and ".pdf" in message and ".docx" in message


def test_extract_rejects_oversized_file():
    payload = b"x" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(UploadError) as excinfo:
        extract_text("big.txt", payload)
    assert excinfo.value.status_code == 422
    assert "10 MB" in str(excinfo.value)


def test_extract_rejects_empty_file_and_empty_text():
    with pytest.raises(UploadError):
        extract_text("empty.txt", b"")
    with pytest.raises(UploadError):
        extract_text("blank.txt", b"   \n\t  ")


def test_extract_rejects_binary_content_in_text_file():
    with pytest.raises(UploadError):
        extract_text("fake.txt", b"\x00\x01\x02binary\x00")


def test_extract_rejects_mime_extension_mismatch():
    with pytest.raises(UploadError):
        extract_text("notes.txt", b"plain text", content_type="image/png")


def test_extract_allows_generic_octet_stream():
    assert extract_text(
        "notes.txt", b"plain text", content_type="application/octet-stream"
    ) == "plain text"


def _run_body_limit_middleware(path: str, headers: list, chunks: list[bytes]):
    """Drive the pure ASGI middleware directly and record handler calls."""
    reached: list[bool] = []
    sent: list[dict] = []

    async def inner_app(scope, receive, send):
        # Simulate form parsing: the body stream is consumed before the
        # endpoint logic is considered reached.
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        reached.append(True)
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = extract.UploadBodyLimitMiddleware(inner_app)
    pending = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        if pending:
            return pending.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "headers": headers}
    asyncio.run(middleware(scope, receive, send))
    return reached, sent


def test_content_length_over_limit_is_rejected_before_handler():
    headers = [
        (b"content-length", str(MAX_UPLOAD_BYTES + 1).encode("ascii"))
    ]
    reached, sent = _run_body_limit_middleware("/upload/task", headers, [b""])
    assert reached == []
    assert sent[0]["status"] == 413
    assert "10 MB" in json.loads(sent[1]["body"])["detail"]


def test_chunked_body_over_limit_never_reaches_handler(monkeypatch):
    monkeypatch.setattr(extract, "MAX_UPLOAD_BYTES", 16)
    reached, sent = _run_body_limit_middleware(
        "/upload/task", [], [b"x" * 10, b"x" * 10]
    )
    assert reached == []
    assert sent[0]["status"] == 413
    assert "16 字节" in json.loads(sent[1]["body"])["detail"]


def test_resume_analyze_json_body_has_the_same_cap():
    headers = [
        (b"content-length", str(MAX_UPLOAD_BYTES + 1).encode("ascii"))
    ]
    reached, sent = _run_body_limit_middleware(
        "/resume/analyze", headers, [b""]
    )
    assert reached == []
    assert sent[0]["status"] == 413


def test_zip_bomb_like_docx_is_rejected_before_document_parse(monkeypatch):
    document_calls: list[bool] = []

    def _fake_document(stream):
        document_calls.append(True)
        return SimpleNamespace(paragraphs=[], tables=[])

    # The ZIP expansion check must run even when python-docx is not installed,
    # and it must reject before any Document parsing happens.
    monkeypatch.setattr(
        extract,
        "_import_docx",
        lambda: SimpleNamespace(Document=_fake_document),
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        # 2 MB of zeros compresses to a few KB, well above the ratio budget.
        archive.writestr("word/document.xml", b"0" * (2 * 1024 * 1024))

    with pytest.raises(UploadError) as excinfo:
        extract_text(
            "bomb.docx",
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
    assert "压缩" in str(excinfo.value) or "解压" in str(excinfo.value)
    assert document_calls == []


def _pdf_file(objects: list[bytes], root: int = 1) -> bytes:
    """Build a minimal, xref-correct PDF for object-model tests."""
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray(header)
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += b"xref\n0 " + str(len(objects) + 1).encode("ascii") + b"\n"
    body += b"0000000000 65535 f \n"
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode("ascii")
    body += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + b" /Root "
        + str(root).encode("ascii")
        + b" 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return bytes(body)


@pytest.fixture(scope="module")
def flate_bomb_payload() -> bytes:
    """A ~40 MB expansion compressed to a few KB."""
    expanded_size = extract.MAX_PDF_STREAM_BYTES + 8 * 1024 * 1024
    return zlib.compress(b"\x00" * expanded_size, 9)


def _bomb_pdf(
    payload: bytes,
    *,
    filter_entry: bytes = b"/Fl",
    gap: bytes = b"",
    extra_objects: list[bytes] | None = None,
) -> bytes:
    content_stream = (
        b"<< /Length "
        + str(len(payload)).encode("ascii")
        + b" /Filter "
        + filter_entry
        + b" "
        + gap
        + b">>\nstream\n"
        + payload
        + b"\nendstream"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << >> /Contents 4 0 R >>"
        ),
        content_stream,
    ]
    objects.extend(extra_objects or [])
    return _pdf_file(objects)


def _nested_form_bomb_pdf(payload: bytes, levels: int) -> bytes:
    """Nest ``levels`` Form XObjects, with the Flate bomb at the deepest one."""
    assert levels >= 1
    forms: list[bytes] = []
    for level in range(1, levels + 1):
        if level < levels:
            next_level = level + 1
            next_object = 4 + next_level
            form_content = f"/F{next_level} Do".encode("ascii")
            resources = (
                f"/Resources << /XObject << /F{next_level} "
                f"{next_object} 0 R >> >>"
            ).encode("ascii")
            body = (
                b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] "
                + resources
                + b" /Length "
                + str(len(form_content)).encode("ascii")
                + b" >>\nstream\n"
                + form_content
                + b"\nendstream"
            )
        else:
            body = (
                b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] "
                b"/Resources << >> /Length "
                + str(len(payload)).encode("ascii")
                + b" /Filter /Fl >>\nstream\n"
                + payload
                + b"\nendstream"
            )
        forms.append(body)
    page_content = b"/F1 Do"
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    return _pdf_file(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            page,
            (
                b"<< /Length "
                + str(len(page_content)).encode("ascii")
                + b" >>\nstream\n"
                + page_content
                + b"\nendstream"
            ),
            *forms,
        ]
    )


def _assert_rejected_before_extract_text(monkeypatch, content, match):
    pytest.importorskip("pypdf")
    import pypdf

    extract_calls: list[bool] = []

    def _spy(self, *args, **kwargs):
        extract_calls.append(True)
        return "pypdf text extraction must not run"

    monkeypatch.setattr(pypdf.PageObject, "extract_text", _spy)
    assert len(content) < MAX_UPLOAD_BYTES
    with pytest.raises(UploadError, match=match):
        extract_text("bomb.pdf", content)
    assert extract_calls == []


def test_pdf_flate_alias_bomb_is_rejected_before_extract_text(
    monkeypatch, flate_bomb_payload
):
    """The `/Fl` alias must be resolved, not missed as a raw literal."""
    content = _bomb_pdf(flate_bomb_payload, filter_entry=b"/Fl")
    _assert_rejected_before_extract_text(monkeypatch, content, "解压")


def test_pdf_indirect_filter_bomb_is_rejected_before_extract_text(
    monkeypatch, flate_bomb_payload
):
    """`/Filter 5 0 R` must resolve to the filter instead of bypassing."""
    content = _bomb_pdf(
        flate_bomb_payload,
        filter_entry=b"5 0 R",
        extra_objects=[b"/FlateDecode"],
    )
    _assert_rejected_before_extract_text(monkeypatch, content, "解压")


def test_pdf_large_dictionary_gap_bomb_is_rejected_before_extract_text(
    monkeypatch, flate_bomb_payload
):
    """A comment gap larger than the old 8 KB window must not bypass the bound."""
    gap = b"%" + b"x" * 9_000 + b"\n"
    content = _bomb_pdf(
        flate_bomb_payload, filter_entry=b"/Fl", gap=gap
    )
    _assert_rejected_before_extract_text(monkeypatch, content, "解压")


def test_pdf_nested_form_bomb_is_rejected_before_extract_text(
    monkeypatch, flate_bomb_payload
):
    """A bomb in the 5th nested Form XObject must not bypass the scan."""
    content = _nested_form_bomb_pdf(flate_bomb_payload, levels=5)
    _assert_rejected_before_extract_text(monkeypatch, content, "解压")


def test_pdf_deeply_nested_form_bomb_is_rejected_before_extract_text(
    monkeypatch, flate_bomb_payload
):
    """Deeper than the old depth cap (20 levels) must also be inspected."""
    content = _nested_form_bomb_pdf(flate_bomb_payload, levels=20)
    _assert_rejected_before_extract_text(monkeypatch, content, "解压")


def test_pdf_parent_inherited_form_resources_are_scanned(
    monkeypatch, flate_bomb_payload
):
    """A form with no local /Resources must inherit /Parent and be inspected.

    pypdf's ``get_inherited('/Resources')`` walks ``/Parent``; the scan mirrors
    that so ``/F2`` in the parent resources cannot hide the Flate bomb.
    """
    page_content = b"/F1 Do"
    form_content = b"/F2 Do"
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    form = (
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] "
        b"/Parent 8 0 R /Length "
        + str(len(form_content)).encode("ascii")
        + b" >>\nstream\n"
        + form_content
        + b"\nendstream"
    )
    bomb = (
        b"<< /Length "
        + str(len(flate_bomb_payload)).encode("ascii")
        + b" /Filter /Fl >>\nstream\n"
        + flate_bomb_payload
        + b"\nendstream"
    )
    content = _pdf_file(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            page,
            (
                b"<< /Length "
                + str(len(page_content)).encode("ascii")
                + b" >>\nstream\n"
                + page_content
                + b"\nendstream"
            ),
            form,
            bomb,
            b"<< >>",
            b"<< /Resources << /XObject << /F2 6 0 R >> >> >>",
        ]
    )
    _assert_rejected_before_extract_text(monkeypatch, content, "解压")


def test_pdf_stream_and_object_caps_are_fail_closed(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(extract, "MAX_PDF_STREAMS", 1)
    too_many_streams = _nested_form_bomb_pdf(b"small", levels=2)
    with pytest.raises(UploadError, match="流对象过多"):
        extract_text("many-streams.pdf", too_many_streams)

    monkeypatch.undo()
    monkeypatch.setattr(extract, "MAX_PDF_OBJECTS", 2)
    with pytest.raises(UploadError, match="对象图过大"):
        extract_text(
            "many-objects.pdf",
            _nested_form_bomb_pdf(b"small", levels=1),
        )


def test_pdf_unsupported_or_multiple_filters_are_rejected():
    pytest.importorskip("pypdf")
    unsupported = _bomb_pdf(
        b"fake", filter_entry=b"/DCTDecode"
    )
    with pytest.raises(UploadError, match="不支持"):
        extract_text("unsupported.pdf", unsupported)

    multiple = _bomb_pdf(
        b"fake", filter_entry=b"[/ASCII85Decode /FlateDecode]"
    )
    with pytest.raises(UploadError, match="多重"):
        extract_text("multiple.pdf", multiple)


def test_pdf_page_cap_is_enforced(monkeypatch):
    class FakePage:
        def extract_text(self) -> str:
            return "x"

    class FakeReader:
        is_encrypted = False
        pages = [FakePage() for _ in range(extract.MAX_PDF_PAGES + 1)]

    monkeypatch.setattr(
        extract,
        "_import_pypdf",
        lambda: SimpleNamespace(PdfReader=lambda stream: FakeReader()),
    )
    with pytest.raises(UploadError) as excinfo:
        extract_text("big.pdf", b"%PDF-1.4\nfake")
    assert "页数" in str(excinfo.value)


def test_pdf_text_cap_is_enforced_during_page_iteration(monkeypatch):
    class FakePage:
        def extract_text(self) -> str:
            return "x" * 200

    class FakeReader:
        is_encrypted = False
        pages = [FakePage()]

    monkeypatch.setattr(extract, "MAX_EXTRACTED_CHARS", 100)
    monkeypatch.setattr(
        extract,
        "_import_pypdf",
        lambda: SimpleNamespace(PdfReader=lambda stream: FakeReader()),
    )
    with pytest.raises(UploadError) as excinfo:
        extract_text("long.pdf", b"%PDF-1.4\nfake")
    assert "文本过大" in str(excinfo.value)


def test_sanitize_filename_strips_paths_and_control_characters():
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("C:\\Users\\me\\resume.md") == "resume.md"
    assert sanitize_filename("bad\x00name.txt") == "badname.txt"
    assert sanitize_filename("") == "document.txt"


def test_pdf_without_optional_dependency_raises_clear_upload_error(monkeypatch):
    def _missing():
        raise ImportError("No module named 'pypdf'")

    monkeypatch.setattr(extract, "_import_pypdf", _missing)
    with pytest.raises(UploadError) as excinfo:
        extract_text("task.pdf", b"%PDF-1.4\nfake")
    assert excinfo.value.status_code == 422
    assert "pypdf" in str(excinfo.value)


def test_docx_without_optional_dependency_raises_clear_upload_error(monkeypatch):
    def _missing():
        raise ImportError("No module named 'docx'")

    monkeypatch.setattr(extract, "_import_docx", _missing)
    with pytest.raises(UploadError) as excinfo:
        extract_text("resume.docx", b"PK\x03\x04fake")
    assert excinfo.value.status_code == 422
    assert "python-docx" in str(excinfo.value)


def test_pdf_parsing_stays_in_memory_and_joins_pages(monkeypatch):
    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, stream) -> None:
            self.is_encrypted = False
            self.pages = [FakePage("第一页"), FakePage("第二页")]

    fake_pypdf = SimpleNamespace(PdfReader=FakeReader)
    monkeypatch.setattr(extract, "_import_pypdf", lambda: fake_pypdf)

    text = extract_text("task.pdf", b"%PDF-1.4\nfake")
    assert "第一页" in text and "第二页" in text


def test_docx_parses_with_the_real_optional_dependency_when_installed():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("个人简历", level=1)
    document.add_paragraph("2020 - 至今 云启科技 后端工程师")
    document.add_paragraph("Python、接口、数据库")
    buffer = io.BytesIO()
    document.save(buffer)

    text = extract_text(
        "resume.docx",
        buffer.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    assert "个人简历" in text
    assert "Python" in text


def test_docx_parsing_reads_paragraphs_and_tables(monkeypatch):
    class FakeParagraph:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeCell:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeRow:
        cells = [FakeCell("表格甲"), FakeCell("表格乙")]

    class FakeTable:
        rows = [FakeRow()]

    class FakeDocument:
        paragraphs = [FakeParagraph("简历正文"), FakeParagraph("")]
        tables = [FakeTable()]

    fake_docx = SimpleNamespace(Document=lambda stream: FakeDocument())
    monkeypatch.setattr(extract, "_import_docx", lambda: fake_docx)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", b"<w:document/>")
    text = extract_text("resume.docx", buffer.getvalue())
    assert "简历正文" in text
    assert "表格甲" in text and "表格乙" in text


# ---------------------------------------------------------------------------
# Task analysis
# ---------------------------------------------------------------------------


def test_analyze_task_text_extracts_category_fields_and_top3():
    analysis = analyze_task_text(TASK_TEXT)

    assert analysis["category"] == "software_dev"
    assert analysis["label"] == "软件开发"
    assert 0.0 <= analysis["confidence"] <= 1.0
    assert len(analysis["top_categories"]) == 3
    assert analysis["top_categories"][0]["category"] == "software_dev"

    fields = analysis["fields"]
    assert fields["budget"] == [8000.0, 20000.0]
    assert fields["budget_min"] == 8000.0
    assert fields["budget_max"] == 20000.0
    assert fields["duration_days"] == 30
    assert fields["remote_ok"] is True
    assert {"frontend", "backend"} & set(fields["skills"])
    assert fields["requirements"]


def test_analyze_task_text_rejects_blank_text():
    with pytest.raises(ValueError):
        analyze_task_text("   ")


def test_task_from_analysis_builds_a_recommendable_draft():
    analysis = analyze_task_text(TASK_TEXT)
    task = task_from_analysis(
        analysis,
        customer_id="c1",
        text=TASK_TEXT,
        task_id="draft_task_test",
    )
    draft = build_task_draft(task, analysis)

    assert task.task_id == "draft_task_test"
    assert task.customer_id == "c1"
    assert task.status == "open"
    assert task.required_skills
    assert task.deadline > datetime.now(timezone.utc)
    assert draft["task_id"] == "draft_task_test"
    assert draft["status"] == "draft"
    assert draft["deadline"].startswith("20")
    assert draft["confidence"] == analysis["confidence"]


# ---------------------------------------------------------------------------
# Resume analysis
# ---------------------------------------------------------------------------


def test_analyze_resume_text_detects_skills_experience_and_profile():
    analysis = analyze_resume_text(RESUME_TEXT)

    assert "backend" in analysis["skills"]
    assert "python" in analysis["skills"]
    assert analysis["experience_years"] >= 6.0
    assert analysis["region"] == "CN"
    assert analysis["remote_preference"] is True
    assert analysis["expected_pay"]["value"] == 15000.0
    assert analysis["expected_pay"]["period"] == "月"
    assert any(
        item["category"] == "software_dev" for item in analysis["categories"]
    )

    draft = analysis["draft_worker"]
    assert draft["worker_id"].startswith("draft_")
    assert draft["skills"]["backend"] >= 1
    assert draft["skills"]["python"] >= 1
    assert draft["status"] == "active"
    assert draft["region"] == "CN"
    assert draft["remote_ok"] is True
    # A monthly quote is not a per-task budget, so the Worker draft must not
    # feed 15000 into pay_fit; the raw figure stays in the analysis payload.
    assert draft["expected_pay"] == 0.0

    worker = worker_from_draft(draft)
    assert worker.worker_id == draft["worker_id"]
    assert worker.skills["backend"] >= 1
    assert isinstance(worker.preferred_difficulty, tuple)


@pytest.mark.parametrize(
    ("pay_text", "expected_value", "expected_period", "worker_pay"),
    [
        ("月薪 15000 元", 15000.0, "月", 0.0),
        ("期望月薪 15000", 15000.0, "月", 0.0),
        ("时薪 100 元", 100.0, "小时", 0.0),
        ("期望时薪 100 元", 100.0, "小时", 0.0),
        # Non-monthly/hourly forms remain per-task-compatible.
        ("日薪 800 元", 800.0, "天", 800.0),
        ("期望薪资 8000 元", 8000.0, None, 8000.0),
        ("期望薪资：15000 元/月", 15000.0, "月", 0.0),
    ],
)
def test_expected_pay_labels_drive_period_and_worker_pay(
    pay_text, expected_value, expected_period, worker_pay
):
    analysis = analyze_resume_text(f"张三\n技能\nPython\n{pay_text}")

    assert analysis["expected_pay"]["value"] == expected_value
    assert analysis["expected_pay"]["period"] == expected_period
    assert analysis["draft_worker"]["expected_pay"] == worker_pay


def test_analyze_resume_text_rejects_blank_text():
    with pytest.raises(ValueError):
        analyze_resume_text("\n \t ")


# ---------------------------------------------------------------------------
# Upload-specific semantic cache hardening
# ---------------------------------------------------------------------------


def test_semantic_pair_cache_is_bounded(monkeypatch):
    matcher = SemanticMatcher(provider="tfidf_svd")
    matcher.fit(
        ["worker text alpha", "worker text beta"],
        ["task text gamma", "task text delta"],
    )
    monkeypatch.setattr(SemanticMatcher, "MAX_CACHE_ENTRIES", 5)
    for index in range(20):
        matcher.similarity(
            f"unseen task text {index}", f"unseen worker text {index}"
        )
    assert len(matcher._cache) <= 5


def test_semantic_vector_cache_is_bounded(monkeypatch):
    matcher = SemanticMatcher(provider="tfidf_svd")
    matcher.fit(
        ["worker text alpha", "worker text beta"],
        ["task text gamma", "task text delta"],
    )
    monkeypatch.setattr(SemanticMatcher, "MAX_VECTOR_ENTRIES", 5)
    for index in range(20):
        matcher.similarity(
            f"fresh task vector {index}", f"fresh worker vector {index}"
        )
    assert len(matcher._vectors) <= 5
