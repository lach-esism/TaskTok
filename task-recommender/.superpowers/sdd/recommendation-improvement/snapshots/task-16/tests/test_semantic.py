import math
import sys
import types
from datetime import datetime, timezone

import numpy as np
import pytest

from app.domain import Task, Worker
from app.semantic import (
    SemanticMatcher,
    build_matcher,
    build_task_text,
    build_worker_text,
    clear_text_caches,
)


def _make_worker(worker_id: str = "w_semantic", **overrides) -> Worker:
    values = {
        "worker_id": worker_id,
        "name": worker_id,
        "skills": {"backend": 4, "qa": 3},
        "specialties": {"software_dev": 3},
        "level": 3,
        "capacity_hours": 40,
        "current_load_hours": 8,
        "preferred_categories": {"software_dev": 0.8},
        "preferred_difficulty": (2, 4),
        "region": "CN",
        "remote_ok": True,
        "ratings": [5.0, 4.0],
        "completed": 7,
        "on_time": 6,
        "rework_count": 1,
        "certifications": {"software_dev": 0.8},
    }
    values.update(overrides)
    return Worker(**values)


def _make_task(
    task_id: str = "t_semantic",
    category: str = "ui_ux_design",
    **overrides,
) -> Task:
    values = {
        "task_id": task_id,
        "customer_id": "c1",
        "title": "设计登录页",
        "category": category,
        "required_skills": {},
        "required_level": 1,
        "difficulty": 2,
        "priority": 2,
        "estimated_hours": 4,
        "deadline": datetime.now(timezone.utc),
        "region": "CN",
        "remote_ok": True,
        "description": "需要响应式设计",
        "requirements": ["熟悉 Figma", "有 B 端经验"],
    }
    values.update(overrides)
    return Task(**values)


def test_tfidf_svd_similarity_is_bounded_and_deterministic():
    matcher = SemanticMatcher(provider="tfidf_svd").fit(
        ["Python 后端开发，支付系统", "品牌 VI 与包装设计", "数据分析与报表"],
        ["需要 Python 后端工程师开发支付接口", "需要品牌设计师做 VI 包装", "需要数据分析师"],
    )
    sim = matcher.similarity(
        "需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统",
    )
    assert 0.0 <= sim <= 1.0
    assert sim == pytest.approx(
        matcher.similarity("需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统")
    )
    assert matcher.fit_count == 1


def test_disabled_provider_returns_half():
    matcher = SemanticMatcher(provider="disabled")
    assert matcher.similarity("a", "b") == 0.5


def test_sentence_transformer_falls_back_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    matcher = build_matcher("sentence_transformer")
    assert matcher.provider == "tfidf_svd"


def test_similarity_batch_matches_single_and_does_not_refit():
    matcher = SemanticMatcher(provider="tfidf_svd").fit(
        ["Python 后端开发，支付系统", "品牌 VI 与包装设计"],
        ["需要 Python 后端工程师开发支付接口", "需要品牌设计师做 VI 包装"],
    )
    task_text = "需要 Python 后端工程师开发支付接口"
    worker_texts = ["Python 后端开发，支付系统", "品牌 VI 与包装设计"]

    batch = matcher.similarity_batch(task_text, worker_texts)
    single = [matcher.similarity(task_text, text) for text in worker_texts]

    assert batch == pytest.approx(single)
    assert all(0.0 <= value <= 1.0 for value in batch)
    assert matcher.fit_count == 1


def test_sentence_transformer_provider_encodes_when_available(monkeypatch):
    class FakeEncoder:
        def __init__(self, model_name, **kwargs):
            self.model_name = model_name
            self.kwargs = kwargs

        def encode(
            self,
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ):
            vectors = np.zeros((len(texts), 4))
            for row, text in enumerate(texts):
                for index, char in enumerate(text):
                    vectors[row, index % 4] += 1.0
            return vectors

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    matcher = build_matcher("sentence_transformer")
    assert matcher.provider == "sentence_transformer"
    matcher.fit(
        ["Python 后端开发，支付系统", "品牌 VI 与包装设计"],
        ["需要 Python 后端工程师开发支付接口", "需要品牌设计师做 VI 包装"],
    )
    sim = matcher.similarity(
        "需要 Python 后端工程师开发支付接口", "Python 后端开发，支付系统"
    )
    assert 0.0 <= sim <= 1.0
    assert not math.isnan(sim)
    assert matcher.fit_count == 1


def test_worker_text_uses_resume_surface_without_internal_stats():
    clear_text_caches()
    worker = _make_worker()

    text = build_worker_text(worker)

    assert "全栈开发工程师 / 小程序与业务系统" in text
    assert "AWS Certified Developer" in text
    assert "客户评分" not in text
    assert "platform_data" not in text
    assert text == build_worker_text(worker)


def test_task_text_joins_title_description_requirements_and_category():
    clear_text_caches()
    task = _make_task()

    assert build_task_text(task) == (
        "设计登录页。需要响应式设计。熟悉 Figma。有 B 端经验。ui_ux_design"
    )


def test_task_text_varies_with_category():
    clear_text_caches()
    software = _make_task(
        task_id="t_semantic_soft", category="software_dev"
    )
    brand = _make_task(
        task_id="t_semantic_brand", category="brand_design"
    )

    software_text = build_task_text(software)
    brand_text = build_task_text(brand)

    assert software_text.endswith("software_dev")
    assert brand_text.endswith("brand_design")
    assert software_text != brand_text


def test_text_builders_cache_by_id_until_cleared():
    clear_text_caches()
    worker = _make_worker(worker_id="w_semantic_cache")
    worker_text = build_worker_text(worker)
    task = _make_task(
        task_id="t_semantic_cache", category="software_dev"
    )
    task_text = build_task_text(task)

    # Same IDs keep serving the memoized text even if the objects mutate.
    worker.specialties = {"brand_design": 5}
    task.category = "brand_design"
    assert build_worker_text(worker) == worker_text
    assert build_task_text(task) == task_text

    # Clearing the caches lets the rebuilt text reflect the new fields.
    clear_text_caches()
    assert build_worker_text(worker) != worker_text
    assert build_task_text(task).endswith("brand_design")
