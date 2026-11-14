"""API tests for multipart upload analysis and resume paste analysis.

The critical invariant is that both upload directions are *read-only*: they
return a draft plus Top-N candidates and never mutate the store or persist the
uploaded bytes.
"""

from __future__ import annotations

import tempfile

from starlette.formparsers import MultiPartParser

from app.upload import extract

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


def _upload(
    client,
    url: str,
    filename: str,
    content: bytes,
    *,
    content_type: str = "text/plain",
    top_n: int = 3,
):
    return client.post(
        url,
        files={"file": (filename, content, content_type)},
        data={"top_n": str(top_n)},
    )


def _store_snapshot(store) -> dict:
    return {
        "workers": sorted(store.workers),
        "tasks": sorted(store.tasks),
        "customers": sorted(store.customers),
        "assignments": list(store.assignments),
        "feedback": list(store.feedback),
        "events": list(store.events),
        "impressions": list(store.impressions),
        "profiles": sorted(store.profiles),
        "worker_preferences": sorted(store.worker_preferences),
        "customer_preferences": sorted(store.customer_preferences),
    }


def test_upload_task_txt_returns_analysis_draft_and_top_workers(client, small_store):
    before = _store_snapshot(small_store)

    response = _upload(
        client, "/upload/task", "task.txt", TASK_TEXT.encode("utf-8")
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["kind"] == "task"
    assert body["persisted"] is False
    assert body["filename"] == "task.txt"
    assert body["size_bytes"] == len(TASK_TEXT.encode("utf-8"))
    assert TASK_TEXT[:20] in body["text_preview"]
    assert body["request_id"]

    analysis = body["analysis"]
    assert analysis["category"] == "software_dev"
    assert analysis["fields"]["budget"] == [8000.0, 20000.0]
    assert analysis["fields"]["duration_days"] == 30
    assert len(analysis["top_categories"]) == 3

    draft = body["draft"]
    assert draft["task_id"].startswith("draft_task_")
    assert draft["customer_id"] == "c1"
    assert draft["category"] == "software_dev"
    assert draft["required_skills"]
    assert draft["status"] == "draft"

    candidates = body["candidates"]
    assert 1 <= len(candidates) <= 3
    for candidate in candidates:
        assert candidate["candidate_id"] in small_store.workers
        assert {"score", "breakdown", "reasons", "cold_start"} <= set(candidate)

    assert _store_snapshot(small_store) == before


def test_upload_task_rejects_unsupported_extension(client):
    response = _upload(
        client, "/upload/task", "payload.exe", b"MZ binary", content_type="application/octet-stream"
    )
    assert response.status_code == 422
    assert ".txt" in response.json()["detail"]


def test_upload_task_rejects_oversized_file_before_form_parsing(client):
    response = _upload(
        client,
        "/upload/task",
        "task.txt",
        b"x" * (extract.MAX_UPLOAD_BYTES + 1),
    )
    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]


def test_upload_task_rejects_mime_mismatch(client):
    response = _upload(
        client,
        "/upload/task",
        "task.txt",
        b"plain text",
        content_type="image/png",
    )
    assert response.status_code == 422
    assert "类型" in response.json()["detail"] or "mime" in response.json()["detail"].lower()


def test_upload_pdf_without_optional_dependency_returns_422(client, monkeypatch):
    def _missing():
        raise ImportError("No module named 'pypdf'")

    monkeypatch.setattr(extract, "_import_pypdf", _missing)
    response = _upload(
        client,
        "/upload/task",
        "task.pdf",
        b"%PDF-1.4\nfake",
        content_type="application/pdf",
    )
    assert response.status_code == 422
    assert "pypdf" in response.json()["detail"]


def test_upload_docx_without_optional_dependency_returns_422(client, monkeypatch):
    def _missing():
        raise ImportError("No module named 'docx'")

    monkeypatch.setattr(extract, "_import_docx", _missing)
    response = _upload(
        client,
        "/upload/resume",
        "resume.docx",
        b"PK\x03\x04fake",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    assert response.status_code == 422
    assert "python-docx" in response.json()["detail"]


def test_upload_resume_txt_returns_profile_draft_and_top_tasks(client, small_store):
    before = _store_snapshot(small_store)

    response = _upload(
        client, "/upload/resume", "resume.txt", RESUME_TEXT.encode("utf-8")
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["kind"] == "resume"
    assert body["persisted"] is False
    assert body["filename"] == "resume.txt"
    assert "张三" in body["text_preview"]

    analysis = body["analysis"]
    assert "backend" in analysis["skills"]
    assert "python" in analysis["skills"]
    assert analysis["experience_years"] >= 6.0
    assert analysis["expected_pay"]["value"] == 15000.0
    assert analysis["categories"]

    draft = body["draft"]
    assert draft["worker_id"].startswith("draft_")
    assert draft["skills"]["python"] >= 1
    assert draft["status"] == "active"
    assert draft["expected_pay"] == 0.0  # monthly quote is not per-task pay
    assert body["draft"] is not None

    candidates = body["candidates"]
    assert 1 <= len(candidates) <= 3
    for candidate in candidates:
        assert candidate["candidate_id"] in small_store.tasks
        assert {"score", "breakdown", "reasons", "cold_start"} <= set(candidate)

    # No uploaded data was written back to the store.
    assert _store_snapshot(small_store) == before


def test_resume_analyze_json_paste_returns_top_tasks(client, small_store):
    before = _store_snapshot(small_store)

    response = client.post(
        "/resume/analyze", json={"text": RESUME_TEXT, "top_n": 2}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["kind"] == "resume"
    assert body["filename"] is None
    assert body["persisted"] is False
    assert body["analysis"]["draft_worker"]["skills"]["backend"] >= 1
    assert 1 <= len(body["candidates"]) <= 2
    assert _store_snapshot(small_store) == before


def test_resume_analyze_rejects_blank_text(client):
    response = client.post("/resume/analyze", json={"text": "    "})
    assert response.status_code == 422


def test_resume_analyze_validates_top_n(client):
    response = client.post(
        "/resume/analyze", json={"text": RESUME_TEXT, "top_n": 0}
    )
    assert response.status_code == 422


def test_upload_endpoints_do_not_persist_uploaded_files(
    client, tmp_path, monkeypatch
):
    framework_tmp = tmp_path / "framework_tmp"
    framework_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(framework_tmp))
    # Accepted uploads stay in RAM: the spool threshold is at least the body
    # cap, so no accepted file part should roll to the framework temp dir.
    assert MultiPartParser.spool_max_size >= extract.MAX_UPLOAD_BYTES

    before = sorted(str(path) for path in tmp_path.rglob("*"))

    assert _upload(
        client, "/upload/task", "task.txt", TASK_TEXT.encode("utf-8")
    ).status_code == 200
    assert _upload(
        client, "/upload/resume", "resume.txt", RESUME_TEXT.encode("utf-8")
    ).status_code == 200
    assert client.post(
        "/resume/analyze", json={"text": RESUME_TEXT, "top_n": 3}
    ).status_code == 200

    after = sorted(str(path) for path in tmp_path.rglob("*"))
    assert after == before
    assert list(framework_tmp.iterdir()) == []


def test_upload_openapi_documents_multipart_contract(client):
    spec = client.get("/openapi.json").json()
    for path in ("/upload/task", "/upload/resume"):
        request_body = spec["paths"][path]["post"]["requestBody"]
        assert request_body["required"] is True
        schema = request_body["content"]["multipart/form-data"]["schema"]
        assert schema["required"] == ["file"]
        assert schema["properties"]["file"]["type"] == "string"
        assert schema["properties"]["file"]["format"] == "binary"
        assert schema["properties"]["top_n"]["minimum"] == 1
        assert schema["properties"]["top_n"]["maximum"] == 50


def test_upload_ui_has_two_cards_and_no_auto_write_copy(client):
    page = client.get("/ui/")
    assert page.status_code == 200
    for needle in (
        "上传任务书",
        "输入/上传简历",
        "upload-task-file",
        "resume-file",
        "upload-task-confirm",
        "resume-confirm",
    ):
        assert needle in page.text

    script = client.get("/ui/app.js")
    assert script.status_code == 200
    assert "runUploadTask" in script.text
    assert "runResumeAnalyze" in script.text
    assert "confirmDraft" in script.text
