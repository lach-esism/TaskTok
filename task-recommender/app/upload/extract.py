"""In-memory, whitelist-only text extraction for uploaded documents.

Security posture (Task 22):

* the filename is sanitized before it is used anywhere (path separators and
  control characters are removed);
* only ``.txt`` / ``.md`` / ``.pdf`` / ``.docx`` are accepted, and the declared
  MIME type (when meaningful) must agree with the extension;
* the upload is capped at :data:`MAX_UPLOAD_BYTES` (10 MB);
* DOCX ZIP entries and PDF stream objects are inspected before the optional
  parser decodes them: zip entry sizes/ratios and Flate expansion are bounded,
  so a compression bomb is rejected before it can allocate memory;
* bytes are parsed in memory from ``io.BytesIO``; nothing is written to disk,
  and no macro / script / embedded object is executed;
* optional parsers (``pypdf`` for PDF, ``python-docx`` for DOCX) are imported
  lazily. When absent, the caller receives an :class:`UploadError` whose
  message explains which extra to install instead of an ``ImportError``.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
import zlib
from pathlib import PurePosixPath

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_MB = 10
# A small DOCX/PDF can inflate to a very large document; keep parsing bounded.
MAX_EXTRACTED_CHARS = 5_000_000
MAX_PDF_PAGES = 200
# PDF streams are decoded lazily by pypdf during ``extract_text``. Scan the
# raw stream objects first and bound both compressed declarations and Flate
# expansions, so a small upload cannot decompress into gigabytes before the
# post-page text check runs.
MAX_PDF_STREAMS = 5_000
MAX_PDF_OBJECTS = 50_000
MAX_PDF_STREAM_BYTES = 32 * 1024 * 1024
MAX_PDF_TOTAL_DECODED = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 2_048
MAX_ZIP_TOTAL_UNCOMPRESSED = 64 * 1024 * 1024
MAX_ZIP_ENTRY_UNCOMPRESSED = 32 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
_ZIP_RATIO_MIN_SIZE = 1024 * 1024

SUPPORTED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx")
TEXT_EXTENSIONS = (".txt", ".md")
UPLOAD_PATHS = frozenset({"/upload/task", "/upload/resume", "/resume/analyze"})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z一-鿿._\-()（） ]+")
_MAX_FILENAME_LENGTH = 180

_MIME_BY_EXTENSION = {
    ".txt": {"text/plain", "text/x-markdown", "text/markdown"},
    ".md": {"text/markdown", "text/x-markdown", "text/plain"},
    ".pdf": {"application/pdf", "application/x-pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
}
_GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}


class UploadError(ValueError):
    """A user-facing upload/parse failure that maps to HTTP 422."""

    status_code = 422


def upload_limit_label(limit: int | None = None) -> str:
    """Render a byte limit without assuming it is always exactly 10 MB."""
    value = MAX_UPLOAD_BYTES if limit is None else int(limit)
    if value and value % (1024 * 1024) == 0:
        return f"{value // (1024 * 1024)} MB"
    if value and value % 1024 == 0:
        return f"{value // 1024} KB"
    return f"{value} 字节"


class _BodyTooLarge(Exception):
    """Raised inside the receive wrapper when a chunked body exceeds the cap."""


class UploadBodyLimitMiddleware:
    """Pure ASGI body cap applied before multipart/JSON parsing.

    Starlette normally receives and spools a multipart body before the route
    handler runs. This middleware runs outside form parsing, rejects an
    over-limit ``Content-Length`` immediately, and counts streamed chunks for
    chunked bodies. An over-limit request never reaches the endpoint.
    """

    def __init__(
        self,
        app,
        paths: frozenset[str] | None = None,
        limit: int | None = None,
    ) -> None:
        self.app = app
        self.paths = paths or UPLOAD_PATHS
        self.limit = MAX_UPLOAD_BYTES if limit is None else int(limit)

    async def __call__(self, scope, receive, send) -> None:
        path = (scope.get("path") or "").rstrip("/") or "/"
        if scope.get("type") != "http" or path not in self.paths:
            await self.app(scope, receive, send)
            return

        limit = self.limit
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        declared = headers.get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                await self._reject(
                    send, 413, "无效的 Content-Length 请求头"
                )
                return
            if declared_size > limit:
                await self._reject(
                    send,
                    413,
                    f"请求体超过大小限制（{upload_limit_label(limit)}）",
                )
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(
                send,
                413,
                f"请求体超过大小限制（{upload_limit_label(limit)}）",
            )

    @staticmethod
    async def _reject(send, status: int, detail: str) -> None:
        body = json.dumps(
            {"detail": detail}, ensure_ascii=False
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def sanitize_filename(filename: str | None) -> str:
    """Return a display-only, path-free filename.

    ``..`` traversal, Windows/POSIX separators and control characters are
    removed. The extension is preserved for the whitelist check, and an empty
    result falls back to ``document.txt`` (which then fails the whitelist only
    if the caller ignores the returned name).
    """
    raw = str(filename or "")
    raw = raw.replace("\\", "/")
    name = PurePosixPath(raw).name
    name = _CONTROL_RE.sub("", name).strip()
    name = _SAFE_NAME_RE.sub("", name).strip(" .")
    if not name:
        return "document.txt"
    if len(name) > _MAX_FILENAME_LENGTH:
        stem, dot, extension = name.rpartition(".")
        if dot and len(extension) <= 10:
            keep = _MAX_FILENAME_LENGTH - len(extension) - 1
            name = f"{stem[:keep]}.{extension}"
        else:
            name = name[:_MAX_FILENAME_LENGTH]
    return name


def _extension(filename: str) -> str:
    name = sanitize_filename(filename).lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _content_type_allowed(extension: str, content_type: str | None) -> bool:
    if not content_type:
        return True
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in _GENERIC_MIME_TYPES:
        return True
    allowed = _MIME_BY_EXTENSION.get(extension, set())
    if extension in TEXT_EXTENSIONS and normalized.startswith("text/"):
        return True
    return normalized in allowed


def _import_pypdf():
    """Import ``pypdf`` lazily so the fallback can be tested and documented."""
    import pypdf

    return pypdf


def _import_docx():
    """Import ``python-docx`` lazily so the fallback can be tested."""
    import docx

    return docx


def _decode_text(content: bytes) -> str:
    if b"\x00" in content:
        raise UploadError("文本文件包含二进制内容，无法作为 .txt/.md 解析")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UploadError("文本编码无法识别，请使用 UTF-8 或 GB18030 编码")


_PDF_FLATE_FILTERS = frozenset({"/FlateDecode", "/Fl"})


def _resolve_pdf_value(value):
    """Resolve an indirect PDF object without decoding any stream data."""
    getter = getattr(value, "get_object", None)
    if callable(getter):
        try:
            return getter()
        except Exception:  # noqa: BLE001 - leave the raw value for the caller
            return value
    return value


def _pdf_filter_names(stream) -> tuple[list[str], bool]:
    """Return ``(filter names, is_multiple)`` for a pypdf stream object.

    ``/Filter`` may be a name, an indirect reference to a name, or an array of
    filters. Aliases (``/Fl``) are preserved as names; the caller decides which
    are supported.
    """
    filter_value = _resolve_pdf_value(stream.get("/Filter"))
    if filter_value is None:
        return [], False
    if isinstance(filter_value, (list, tuple)):
        names = [
            str(_resolve_pdf_value(item)) for item in filter_value
        ]
        return names, len(names) > 1
    return [str(filter_value)], False


def _collect_pdf_streams(
    roots,
    seen: dict[int, object],
    streams: list,
) -> None:
    """Collect reachable stream objects without calling ``get_data()``.

    An iterative worklist avoids any recursion/depth cap below pypdf's own
    nested Form XObject traversal (pypdf follows up to 5,000 nested forms).
    Streams can appear in page ``/Contents``, resource ``/XObject`` form/media
    entries, fonts, patterns, and annotation appearance dictionaries. Form
    XObjects are followed through their own ``/Resources`` and through
    ``/Parent`` (pypdf's ``get_inherited('/Resources')`` lookup), so a form with
    no local resources cannot hide a referenced bomb. Resolving indirect
    references and walking the object graph catches every stream that
    ``extract_text`` might decode, regardless of nesting depth or how far the
    dictionary sits from the ``stream`` keyword.

    Fail-closed caps bound the visited object graph and stream count. ``seen``
    maps ``id(value)`` to the object itself so CPython cannot recycle an id
    while the scan is running.
    """
    from pypdf.generic import StreamObject  # noqa: PLC0415

    worklist = list(roots)
    while worklist:
        value = worklist.pop()
        if value is None:
            continue
        value = _resolve_pdf_value(value)
        marker = id(value)
        if marker in seen:
            continue
        if len(seen) >= MAX_PDF_OBJECTS:
            raise UploadError(
                f"PDF 对象图过大（最多 {MAX_PDF_OBJECTS} 个对象）"
            )
        seen[marker] = value
        if isinstance(value, StreamObject):
            streams.append(value)
            if len(streams) > MAX_PDF_STREAMS:
                raise UploadError(
                    f"PDF 内部流对象过多（最多 {MAX_PDF_STREAMS} 个）"
                )
            # pypdf resolves Form XObject resources with
            # ``get_inherited('/Resources')``, which walks ``/Parent`` even
            # when the form has no own resource dictionary. Follow the same
            # keys; the visited set makes ``/Parent`` cycles safe.
            for key in ("/Resources", "/Annots", "/Parent"):
                if hasattr(value, "get") and key in value:
                    worklist.append(value.get(key))
            continue
        if isinstance(value, dict):
            worklist.extend(value.values())
        elif isinstance(value, (list, tuple)):
            worklist.extend(value)


def _decode_pdf_stream_bounded(stream) -> int:
    """Validate one stream's filter and bounded decoded size.

    Returns the number of decoded bytes. Raises ``UploadError`` for an
    unbounded Flate expansion, multiple filters, or an unsupported filter.
    """
    filters, is_multiple = _pdf_filter_names(stream)
    raw = getattr(stream, "_data", None)
    if raw is None:
        if filters:
            raise UploadError("PDF 流数据无法安全读取")
        raw = stream.get_data()
    if not isinstance(raw, (bytes, bytearray)):
        raise UploadError("PDF 流数据格式无效")
    raw = bytes(raw)

    if is_multiple:
        raise UploadError("PDF 包含多重流过滤器，无法安全解析")
    if not filters:
        if len(raw) > MAX_PDF_STREAM_BYTES:
            raise UploadError("PDF 流数据过大")
        return len(raw)
    unsupported = [
        name for name in filters if name not in _PDF_FLATE_FILTERS
    ]
    if unsupported:
        raise UploadError(
            f"PDF 使用了不支持的流过滤器 {unsupported[0]}，无法安全解析"
        )

    decompressor = zlib.decompressobj()
    try:
        expanded = decompressor.decompress(
            raw, MAX_PDF_STREAM_BYTES + 1
        )
    except zlib.error:
        raise UploadError("PDF Flate 流已损坏，无法解析") from None
    if len(expanded) > MAX_PDF_STREAM_BYTES or decompressor.unconsumed_tail:
        raise UploadError("PDF 流解压后过大（疑似解压炸弹）")
    if decompressor.unused_data:
        raise UploadError("PDF Flate 流包含多余数据，无法安全解析")
    return len(expanded)


def _inspect_pdf_object_streams(reader) -> None:
    """Reject oversized/unsupported PDF streams before ``extract_text``.

    Uses pypdf's object model, so aliases (``/Fl``), indirect ``/Filter``
    references, arbitrarily long dictionary-to-``stream`` gaps, and nested Form
    XObjects at any depth are resolved the same way pypdf will resolve them. The
    iterative worklist has no depth cap below pypdf's 5,000-form traversal;
    visited objects (50,000) and streams (5,000) are capped fail-closed. Only
    Flate (and unfiltered) streams are decoded in-process, and every decode is
    capped; multiple or unsupported filters also raise a user-facing 422 before
    the parser runs.
    """
    pages = getattr(reader, "pages", None)
    if not pages:
        return
    try:
        page_list = list(pages)
    except Exception as error:  # noqa: BLE001 - malformed page tree
        raise UploadError(
            f"PDF 文件无法解析（文件可能损坏）：{type(error).__name__}"
        ) from None
    # Fake readers used by optional-dependency tests expose only
    # ``extract_text``; there is no object model to inspect.
    if not all(hasattr(page, "get") for page in page_list):
        return

    roots = []
    for page in page_list:
        for key in ("/Contents", "/Resources", "/Annots"):
            if key in page:
                roots.append(page.get(key))
    seen: dict[int, object] = {}
    streams: list = []
    _collect_pdf_streams(roots, seen, streams)

    decoded_total = 0
    for stream in streams:
        decoded_total += _decode_pdf_stream_bounded(stream)
        if decoded_total > MAX_PDF_TOTAL_DECODED:
            raise UploadError("PDF 解压后的总体积过大")


def _extract_pdf(content: bytes) -> str:
    if not content.lstrip().startswith(b"%PDF-"):
        raise UploadError("文件不是有效的 PDF（缺少 %PDF 文件头）")
    try:
        pypdf = _import_pypdf()
    except ImportError:
        raise UploadError(
            "PDF 解析需要可选依赖 pypdf；请安装：pip install pypdf"
        ) from None
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        if getattr(reader, "is_encrypted", False):
            raise UploadError("PDF 已加密，无法解析")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise UploadError(
                f"PDF 页数超过限制（最多 {MAX_PDF_PAGES} 页）"
            )
        # Resolve the object model and bound every reachable stream before
        # pypdf's text extraction lazily decodes content/XObject/font streams.
        _inspect_pdf_object_streams(reader)
        collected: list[str] = []
        total_chars = 0
        for page in reader.pages:
            chunk = page.extract_text() or ""
            total_chars += len(chunk)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise UploadError("PDF 解析后的文本过大，请上传更小的文件")
            collected.append(chunk)
    except UploadError:
        raise
    except Exception as error:  # noqa: BLE001 - parser errors are user-facing
        raise UploadError(
            f"PDF 文件无法解析（文件可能损坏）：{type(error).__name__}"
        ) from None
    return "\n".join(page for page in collected if page.strip())


def _inspect_docx_zip(content: bytes) -> None:
    """Reject suspicious ZIP expansion before ``docx.Document`` parses it."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise UploadError("DOCX 文件不是有效的 ZIP 结构") from None
    try:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise UploadError(
                f"DOCX 内部条目过多（最多 {MAX_ZIP_ENTRIES} 个）"
            )
        total_uncompressed = 0
        for entry in entries:
            if entry.flag_bits & 0x1:
                raise UploadError("DOCX 包含加密条目，无法解析")
            if entry.file_size > MAX_ZIP_ENTRY_UNCOMPRESSED:
                raise UploadError("DOCX 单条目解压后过大")
            total_uncompressed += entry.file_size
            if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED:
                raise UploadError("DOCX 解压后总体积过大")
            if (
                entry.file_size >= _ZIP_RATIO_MIN_SIZE
                and entry.compress_size > 0
                and entry.file_size / entry.compress_size
                > MAX_ZIP_COMPRESSION_RATIO
            ):
                raise UploadError("DOCX 压缩比异常（疑似压缩炸弹）")
    finally:
        archive.close()


def _extract_docx(content: bytes) -> str:
    if not content.startswith(b"PK\x03\x04"):
        raise UploadError("文件不是有效的 DOCX（缺少 ZIP 文件头）")
    try:
        docx = _import_docx()
    except ImportError:
        raise UploadError(
            "DOCX 解析需要可选依赖 python-docx；请安装：pip install python-docx"
        ) from None
    _inspect_docx_zip(content)
    try:
        document = docx.Document(io.BytesIO(content))
        parts = [
            paragraph.text.strip()
            for paragraph in document.paragraphs
            if paragraph.text and paragraph.text.strip()
        ]
        for table in document.tables:
            for row in table.rows:
                cells = [
                    cell.text.strip()
                    for cell in row.cells
                    if cell.text and cell.text.strip()
                ]
                if cells:
                    parts.append(" | ".join(cells))
    except Exception as error:  # noqa: BLE001 - parser errors are user-facing
        raise UploadError(
            f"DOCX 文件无法解析（文件可能损坏）：{type(error).__name__}"
        ) from None
    return "\n".join(parts)


def extract_text(
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> str:
    """Extract plain text from an uploaded document without touching disk.

    ``filename`` drives the extension whitelist and is sanitized first. When
    ``content_type`` is a concrete value it must agree with the extension;
    generic browser fallbacks such as ``application/octet-stream`` are allowed.
    Any rejection raises :class:`UploadError` (HTTP 422 at the API layer).
    """
    if not isinstance(content, (bytes, bytearray)):
        raise UploadError("文件内容格式无效")
    content = bytes(content)
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadError(
            f"文件超过上传大小限制（{upload_limit_label()}）"
        )
    if not content:
        raise UploadError("文件为空")

    safe_name = sanitize_filename(filename)
    extension = _extension(safe_name)
    if extension not in SUPPORTED_EXTENSIONS:
        supported = "、".join(SUPPORTED_EXTENSIONS)
        raise UploadError(
            f"不支持的文件类型 {extension or '(无扩展名)'}；仅支持 {supported}"
        )
    if not _content_type_allowed(extension, content_type):
        raise UploadError(
            f"文件类型 {content_type} 与扩展名 {extension} 不匹配"
        )

    if extension in TEXT_EXTENSIONS:
        text = _decode_text(content)
    elif extension == ".pdf":
        text = _extract_pdf(content)
    else:  # .docx
        text = _extract_docx(content)

    if len(text) > MAX_EXTRACTED_CHARS:
        raise UploadError("文档解析后的文本过大，请上传更小的文件")
    if not text.strip():
        raise UploadError("未能从文件中解析到文本内容")
    return text
