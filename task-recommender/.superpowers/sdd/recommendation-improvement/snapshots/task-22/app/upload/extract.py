"""In-memory, whitelist-only text extraction for uploaded documents.

Security posture (Task 22):

* the filename is sanitized before it is used anywhere (path separators and
  control characters are removed);
* only ``.txt`` / ``.md`` / ``.pdf`` / ``.docx`` are accepted, and the declared
  MIME type (when meaningful) must agree with the extension;
* the upload is capped at :data:`MAX_UPLOAD_BYTES` (10 MB);
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
from pathlib import PurePosixPath

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_MB = 10
# A small DOCX/PDF can inflate to a very large document; keep parsing bounded.
MAX_EXTRACTED_CHARS = 5_000_000
MAX_PDF_PAGES = 200
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

    def __init__(self, app, paths: frozenset[str] | None = None) -> None:
        self.app = app
        self.paths = paths or UPLOAD_PATHS

    async def __call__(self, scope, receive, send) -> None:
        path = (scope.get("path") or "").rstrip("/") or "/"
        if scope.get("type") != "http" or path not in self.paths:
            await self.app(scope, receive, send)
            return

        limit = MAX_UPLOAD_BYTES
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
                    f"请求体超过上传大小限制（{upload_limit_label(limit)}）",
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
                f"请求体超过上传大小限制（{upload_limit_label(limit)}）",
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
