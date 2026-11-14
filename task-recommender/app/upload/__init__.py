"""Bidirectional upload/analysis support (Task 22).

* :mod:`app.upload.extract` — secure, in-memory document text extraction.
* :mod:`app.upload.analyze` — task/resume analysis and draft builders.

Nothing in this package writes uploaded content to the store or to disk.
"""

from app.upload.analyze import (
    analyze_resume_text,
    analyze_task_text,
    build_task_draft,
    task_from_analysis,
    worker_from_draft,
)
from app.upload.extract import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    SUPPORTED_EXTENSIONS,
    UploadBodyLimitMiddleware,
    UploadError,
    extract_text,
    sanitize_filename,
    upload_limit_label,
)

__all__ = [
    "MAX_UPLOAD_BYTES",
    "MAX_UPLOAD_MB",
    "SUPPORTED_EXTENSIONS",
    "UploadBodyLimitMiddleware",
    "UploadError",
    "analyze_resume_text",
    "analyze_task_text",
    "build_task_draft",
    "extract_text",
    "sanitize_filename",
    "task_from_analysis",
    "upload_limit_label",
    "worker_from_draft",
]
