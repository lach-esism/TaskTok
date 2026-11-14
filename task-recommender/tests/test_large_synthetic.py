"""Focused tests for the large natural-language synthetic generator."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from app.benchmark.large import build_large_sqlite, load_large_sqlite
from app.data.large_synthetic import (
    CATEGORY_CERTS,
    CATEGORY_RESULTS,
    generate_large_dataset,
    is_near_duplicate,
    normalized_text_hash,
    simhash64,
)
from app.resume import CATEGORY_PROFILES


def small_dataset(**overrides):
    kwargs = dict(n_workers=40, n_tasks=120, n_assignments=1200, seed=7)
    kwargs.update(overrides)
    return generate_large_dataset(**kwargs)


def test_generate_large_dataset_is_deterministic():
    a = small_dataset()
    b = small_dataset()
    assert [w["worker_id"] for w in a.workers] == [w["worker_id"] for w in b.workers]
    assert [t["task_id"] for t in a.tasks] == [t["task_id"] for t in b.tasks]
    assert [t["title"] for t in a.tasks] == [t["title"] for t in b.tasks]
    assert [t["task_text"] for t in a.tasks] == [t["task_text"] for t in b.tasks]
    assert a.splits == b.splits
    assert a.labels == b.labels

    c = small_dataset(seed=8)
    assert [t["task_text"] for t in a.tasks] != [t["task_text"] for t in c.tasks]


def test_tasks_and_resumes_unique_and_no_near_duplicates():
    dataset = small_dataset()
    task_texts = [t["task_text"] for t in dataset.tasks]
    resume_texts = [w["resume_text"] for w in dataset.workers]

    assert len({normalized_text_hash(text) for text in task_texts}) == len(task_texts)
    assert len({normalized_text_hash(text) for text in resume_texts}) == len(resume_texts)
    assert len({t["title"] for t in dataset.tasks}) == len(dataset.tasks)

    task_hashes = [simhash64(text) for text in task_texts]
    for i in range(len(task_hashes)):
        for j in range(i + 1, len(task_hashes)):
            assert (task_hashes[i] ^ task_hashes[j]).bit_count() > 3

    resume_hashes = [simhash64(text) for text in resume_texts]
    for i in range(len(resume_hashes)):
        for j in range(i + 1, len(resume_hashes)):
            assert (resume_hashes[i] ^ resume_hashes[j]).bit_count() > 3


def test_simhash_and_normalized_hash_semantics():
    long_a = (
        "连锁咖啡品牌会员小程序开发。客户计划在近期完成会员小程序开发，"
        "现阶段最关心的是交付质量与周期可控。要求如下：有 3 年以上相关开发经验，"
        "能独立完成模块设计与实现；需要熟悉后端开发、前端开发。"
        "主要交付物包括需求确认清单、可运行系统。预算 8,000–30,000 元，期望 30 天内完成。"
    )
    long_b = long_a[:-1] + "X"
    distinct = (
        "新茶饮品牌 VI 与包装设计。客户准备进入新市场，希望建立统一的品牌视觉体系。"
        "要求如下：有品牌设计经验；需要熟悉品牌策略、视觉设计。"
        "主要交付物包括 Logo 与基础规范、包装设计稿。预算 5,000–20,000 元，期望 20 天内完成。"
    )
    assert normalized_text_hash(long_a) == normalized_text_hash(long_a)
    assert normalized_text_hash("A b  c") == normalized_text_hash("a b c")
    assert normalized_text_hash(long_a) != normalized_text_hash(long_b)

    assert is_near_duplicate(long_a, long_a)
    assert is_near_duplicate(long_a, long_b)  # one-character edit is near-duplicate
    assert not is_near_duplicate(long_a, distinct)
    assert (simhash64(long_a) ^ simhash64(distinct)).bit_count() > 3


def test_split_is_disjoint_and_8020():
    dataset = small_dataset()
    splits = dataset.splits
    assert set(splits.values()) <= {"train", "test"}
    assert len(splits) == len(dataset.tasks)
    train = sum(1 for value in splits.values() if value == "train")
    test = sum(1 for value in splits.values() if value == "test")
    assert train == 96
    assert test == 24
    assert train + test == len(dataset.tasks)

    for assignment in dataset.assignments:
        assert assignment["split"] == splits[assignment["task_id"]]
    for task_id, label in dataset.labels.items():
        assert label["split"] == splits[task_id]


def test_no_label_leakage(tmp_path):
    dataset = small_dataset()
    db_path = tmp_path / "bench.sqlite"
    build_large_sqlite(dataset, db_path)

    loaded = load_large_sqlite(db_path)
    assert loaded.labels == {}
    assert not any(key.startswith("stat:") for key in loaded.metadata)
    for task in loaded.tasks:
        assert "gold_worker_id" not in task
        assert "category" not in task
    for worker in loaded.workers:
        assert "reliability" not in worker
    for assignment in loaded.assignments:
        if assignment["split"] == "test":
            assert assignment["status"] == "unknown"
            assert assignment["on_time"] is None
            assert assignment["rating"] is None
            assert assignment["rework"] is None
        else:
            assert assignment["status"] in {"accepted", "rejected"}

    raw = load_large_sqlite(db_path, include_test_outcomes=True)
    test_statuses = {
        row["status"] for row in raw.assignments if row["split"] == "test"
    }
    assert test_statuses <= {"accepted", "rejected"}
    assert test_statuses

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        assert "gold_worker_id" not in columns
        assert "category" not in columns
        label_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(labels)").fetchall()
        }
        assert "gold_worker_id" in label_columns
        test_outcomes = connection.execute(
            "SELECT status, rating FROM assignments WHERE split='test' "
            "AND status='accepted' AND rating IS NOT NULL LIMIT 1"
        ).fetchone()
        assert test_outcomes is not None
    finally:
        connection.close()


def test_natural_language_fields_are_complete():
    dataset = small_dataset()
    for task in dataset.tasks:
        assert task["task_text"].strip()
        assert task["title"].strip()
        assert "交付" in task["task_text"] or "预算" in task["task_text"]
        assert "天" in task["task_text"]
    for worker in dataset.workers:
        text = worker["resume_text"]
        assert text.strip()
        assert worker["name"] in text
        assert "技能" in text or "擅长" in text or "熟练" in text or "核心能力" in text
        assert "项目" in text
        assert "证书" in text or "认证" in text
        assert "担任" in text or "工作经历" in text


def _category_owners():
    result_owners = defaultdict(set)
    for category, items in CATEGORY_RESULTS.items():
        for item in items:
            result_owners[item].add(category)
    for category, profile in CATEGORY_PROFILES.items():
        for project in profile["projects"]:
            result_owners[project[3]].add(category)

    cert_owners = defaultdict(set)
    for category, items in CATEGORY_CERTS.items():
        for item in items:
            cert_owners[item].add(category)
    for category, profile in CATEGORY_PROFILES.items():
        for cert in profile["certifications"]:
            cert_owners[cert].add(category)
    return result_owners, cert_owners


def test_resume_results_and_certs_are_category_consistent():
    dataset = small_dataset()
    result_owners, cert_owners = _category_owners()
    for worker in dataset.workers:
        specialties = worker["specialties"]
        top_category = (
            max(specialties, key=lambda key: (specialties[key], key))
            if specialties
            else "consulting_research"
        )
        text = worker["resume_text"]
        for phrase, owners in result_owners.items():
            if phrase in text:
                assert top_category in owners, (
                    worker["worker_id"],
                    top_category,
                    phrase,
                )
        for phrase, owners in cert_owners.items():
            if phrase in text:
                assert top_category in owners, (
                    worker["worker_id"],
                    top_category,
                    phrase,
                )


def test_duplicate_stats_are_computed_from_emitted_texts():
    dataset = small_dataset()
    stats = dataset.stats
    assert stats["task_exact_duplicates"] == 0
    assert stats["task_title_duplicates"] == 0
    assert stats["task_near_dup_collisions"] == 0
    assert stats["task_near_dup_rate"] == 0.0
    assert stats["resume_exact_duplicates"] == 0
    assert stats["resume_near_dup_collisions"] == 0
    assert stats["resume_near_dup_rate"] == 0.0
    assert stats["task_unique_titles"] == len(dataset.tasks)
    assert stats["exposure_pool_size"] == 10
    assert 0.0 <= stats["gold_acceptance_rate"] <= 1.0
    assert stats["split_outcomes"]["train"]["assignments"] == 960
    assert stats["split_outcomes"]["test"]["assignments"] == 240


def test_llm_seeds_hook_is_optional_and_deterministic():
    base = small_dataset()
    seeded = small_dataset(
        llm_seeds={
            "tasks": [
                {"title": "种子任务标题", "task_text": "这是一段由 LLM 提供的种子任务文本，描述一个完全不同的需求。"},
            ]
        }
    )
    assert seeded.tasks[0]["task_text"] == "这是一段由 LLM 提供的种子任务文本，描述一个完全不同的需求。"
    assert base.tasks[0]["task_text"] != seeded.tasks[0]["task_text"]
    again = small_dataset(
        llm_seeds={
            "tasks": [
                {"title": "种子任务标题", "task_text": "这是一段由 LLM 提供的种子任务文本，描述一个完全不同的需求。"},
            ]
        }
    )
    assert seeded.tasks[0]["task_text"] == again.tasks[0]["task_text"]
