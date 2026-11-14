"""Focused tests for large-benchmark storage and sampled evaluation."""

from __future__ import annotations

import json
import sqlite3

import numpy as np

from app.benchmark.large import (
    LargeFeatureBuilder,
    build_itemcf,
    build_large_sqlite,
    collaborative_scores,
    evaluate_large,
    export_large_jsonl,
    item_similarity,
    load_large_sqlite,
    pool_normalize,
)
from app.data.large_synthetic import generate_large_dataset
from app.models.itemcf import ItemCF


def build_small(tmp_path, **overrides):
    kwargs = dict(n_workers=60, n_tasks=200, n_assignments=2000, seed=7)
    kwargs.update(overrides)
    dataset = generate_large_dataset(**kwargs)
    db_path = tmp_path / "bench.sqlite"
    build_large_sqlite(dataset, db_path)
    return db_path, dataset


def test_build_and_load_large_sqlite_roundtrip(tmp_path):
    db_path, dataset = build_small(tmp_path)
    loaded = load_large_sqlite(db_path)
    assert len(loaded.workers) == len(dataset.workers)
    assert len(loaded.tasks) == len(dataset.tasks)
    assert len(loaded.customers) == len(dataset.customers)
    assert len(loaded.assignments) == len(dataset.assignments)
    assert loaded.splits == dataset.splits
    assert loaded.labels == {}
    assert not any(key.startswith("stat:") for key in loaded.metadata)
    assert loaded.workers[0]["resume_text"]
    assert loaded.tasks[0]["task_text"]
    assert "skills" in loaded.workers[0]

    for assignment in loaded.assignments:
        if assignment["split"] == "test":
            assert assignment["status"] == "unknown"
            assert assignment["on_time"] is None
            assert assignment["rating"] is None
            assert assignment["rework"] is None
        else:
            assert assignment["status"] in {"accepted", "rejected"}


def test_evaluate_large_metrics_bounded(tmp_path):
    db_path, _ = build_small(tmp_path)
    result = evaluate_large(db_path, test_tasks=20, candidates=50, seeds=(42, 43))
    assert set(result["metrics"]) == {"top1", "top5", "mrr", "ndcg"}
    for name, value in result["metrics"].items():
        assert 0.0 <= value["mean"] <= 1.0
        assert 0.0 <= value["std"] <= 1.0
    assert len(result["per_seed"]) == 2
    for row in result["per_seed"]:
        assert 0.0 <= row["top1"] <= 1.0
        assert 0.0 <= row["top5"] <= 1.0
        assert 0.0 <= row["mrr"] <= 1.0
        assert 0.0 <= row["ndcg"] <= 1.0
    assert 0.0 <= result["collaborative_nonzero_rate"] <= 1.0


def test_itemcf_wiring_and_pool_normalization():
    sim = ItemCF([("w1", "t1", 5.0), ("w2", "t1", 4.0), ("w2", "t2", 3.0)])
    history = ItemCF([("w1", "t1", 5.0), ("w2", "t2", 3.0)])

    assert item_similarity(sim, "t1", "t2") > 0.0

    scores = collaborative_scores(sim, history, "t2", ["w1", "w2"])
    assert scores["w1"] > 0.0
    assert scores["w2"] >= 0.0

    assert pool_normalize({"a": 0.2, "b": 0.4}) == {"a": 0.5, "b": 1.0}
    assert pool_normalize({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}
    assert pool_normalize({}) == {}


def test_build_itemcf_filters_by_split():
    assignments = [
        {"worker_id": "w1", "task_id": "t1", "status": "accepted", "rating": 5.0, "split": "train"},
        {"worker_id": "w2", "task_id": "t2", "status": "accepted", "rating": 4.0, "split": "test"},
        {"worker_id": "w3", "task_id": "t3", "status": "rejected", "rating": None, "split": "train"},
    ]
    train_cf = build_itemcf(assignments, split="train")
    assert set(train_cf.user_items) == {"w1"}
    all_cf = build_itemcf(assignments)
    assert set(all_cf.user_items) == {"w1", "w2"}


def test_evaluate_large_wires_real_itemcf(tmp_path):
    db_path, _ = build_small(tmp_path)
    result = evaluate_large(db_path, test_tasks=10, candidates=30, seeds=(42,))
    assert result["itemcf"]["pool_normalized"] is True
    assert result["itemcf"]["history_is_train_only"] is True
    assert result["itemcf"]["history_interactions"] > 0
    assert result["itemcf"]["similarity_interactions"] >= result["itemcf"]["history_interactions"]


def test_test_split_assignments_cannot_affect_itemcf_or_scores():
    train_assignments = [
        {"worker_id": "w1", "task_id": "t1", "status": "accepted", "rating": 5.0, "split": "train"},
        {"worker_id": "w2", "task_id": "t1", "status": "accepted", "rating": 4.0, "split": "train"},
        {"worker_id": "w2", "task_id": "t2", "status": "accepted", "rating": 3.0, "split": "train"},
    ]
    itemcf = build_itemcf(train_assignments, split="train")
    baseline_item_users = {
        task_id: dict(users) for task_id, users in itemcf.item_users.items()
    }
    baseline_similarity = item_similarity(itemcf, "t1", "t2")
    baseline_scores = collaborative_scores(
        itemcf, itemcf, "t_held_out", ["w1", "w2"]
    )

    with_test_rows = train_assignments + [
        {
            "worker_id": "w1",
            "task_id": "t_held_out",
            "status": "accepted",
            "rating": 5.0,
            "split": "test",
        },
        {
            "worker_id": "w3",
            "task_id": "t_held_out",
            "status": "accepted",
            "rating": 5.0,
            "split": "test",
        },
    ]
    itemcf_with_test = build_itemcf(with_test_rows, split="train")
    assert {
        task_id: dict(users)
        for task_id, users in itemcf_with_test.item_users.items()
    } == baseline_item_users
    assert item_similarity(itemcf_with_test, "t1", "t2") == baseline_similarity
    assert collaborative_scores(
        itemcf_with_test, itemcf_with_test, "t_held_out", ["w1", "w2"]
    ) == baseline_scores


def test_evaluate_large_is_train_only_and_reports_baselines(tmp_path):
    db_path, _ = build_small(tmp_path)
    result = evaluate_large(db_path, test_tasks=10, candidates=30, seeds=(42,))
    itemcf = result["itemcf"]
    assert itemcf["similarity_splits"] == ["train"]
    assert itemcf["history_splits"] == ["train"]
    assert itemcf["similarity_is_train_only"] is True
    assert itemcf["history_is_train_only"] is True
    assert itemcf["excluded_test_accepted_interactions"] > 0
    assert (
        itemcf["accepted_interactions_total"]
        == itemcf["similarity_interactions"]
        + itemcf["excluded_test_accepted_interactions"]
    )
    assert result["collaborative_nonzero_rate"] == 0.0
    assert result["protocol"]["similarity_graph"] == (
        "train-split accepted assignments only"
    )
    assert result["protocol"]["exposure_pool_size"] == 10
    assert result["protocol"]["candidate_pool"] == "gold + 29 random workers"
    assert set(result["baselines"]["feature_only"]) == {
        "top1",
        "top5",
        "mrr",
        "ndcg",
    }
    assert result["baselines"]["random"]["top1"] == round(1 / 30, 6)
    assert result["baselines"]["random"]["top5"] == round(5 / 30, 6)
    for name in ("top1", "top5", "mrr", "ndcg"):
        assert result["metrics"][name] == result["baselines"]["feature_only"][name]


def test_mutating_test_assignments_does_not_change_evaluation(tmp_path):
    db_path, _ = build_small(tmp_path)
    before = evaluate_large(db_path, test_tasks=10, candidates=30, seeds=(42,))

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT assignment_id FROM assignments "
            "WHERE split='test' AND status='accepted' LIMIT 1"
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE assignments SET status='rejected', rating=NULL, "
            "on_time=NULL, rework=NULL WHERE assignment_id=?",
            (row[0],),
        )
        connection.commit()
    finally:
        connection.close()

    after = evaluate_large(db_path, test_tasks=10, candidates=30, seeds=(42,))
    assert after["metrics"] == before["metrics"]
    assert after["collaborative_nonzero_rate"] == before["collaborative_nonzero_rate"]
    for key in (
        "similarity_interactions",
        "history_interactions",
        "similarity_splits",
        "history_splits",
        "similarity_is_train_only",
        "history_is_train_only",
    ):
        assert after["itemcf"][key] == before["itemcf"][key]
    assert (
        after["itemcf"]["excluded_test_accepted_interactions"]
        == before["itemcf"]["excluded_test_accepted_interactions"] - 1
    )


def test_jsonl_is_model_safe_and_hides_test_outcomes(tmp_path):
    _, dataset = build_small(tmp_path)
    jsonl_path = tmp_path / "bench.jsonl"
    export_large_jsonl(dataset, jsonl_path)
    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    meta = records[0]
    assert meta["type"] == "meta"
    assert "stats" not in meta
    assert not any(key.startswith("stat:") for key in meta["metadata"])
    assert meta["outcome_policy"] == {
        "test_split": "redacted",
        "train_split": "full",
    }

    test_rows = [
        row
        for row in records
        if row["type"] == "assignment" and row["split"] == "test"
    ]
    train_rows = [
        row
        for row in records
        if row["type"] == "assignment" and row["split"] == "train"
    ]
    assert test_rows and train_rows
    for row in test_rows:
        assert row["status"] == "unknown"
        assert row["on_time"] is None
        assert row["rating"] is None
        assert row["rework"] is None
    for row in train_rows:
        assert row["status"] in {"accepted", "rejected"}
    assert not any("gold_worker_id" in row or "labels" in row for row in records)

    raw_path = tmp_path / "raw.jsonl"
    export_large_jsonl(dataset, raw_path, include_test_outcomes=True)
    raw_records = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
    ]
    raw_test_rows = [
        row
        for row in raw_records
        if row["type"] == "assignment" and row["split"] == "test"
    ]
    assert {row["status"] for row in raw_test_rows} <= {"accepted", "rejected"}


def test_feature_builder_fits_on_train_text_only():
    dataset = generate_large_dataset(
        n_workers=10, n_tasks=30, n_assignments=300, seed=3
    )
    train_ids = [
        task["task_id"]
        for task in dataset.tasks
        if dataset.splits[task["task_id"]] == "train"
    ]
    test_task = next(
        task
        for task in dataset.tasks
        if dataset.splits[task["task_id"]] == "test"
    )
    builder = LargeFeatureBuilder(
        dataset.workers,
        dataset.tasks,
        dataset.customers,
        train_task_ids=train_ids,
    )
    mutated_tasks = [dict(task) for task in dataset.tasks]
    for task in mutated_tasks:
        if task["task_id"] == test_task["task_id"]:
            task["task_text"] = (
                "这是一段包含独特词元 QWXZ 的测试任务文本。" + task["task_text"]
            )
    mutated_builder = LargeFeatureBuilder(
        dataset.workers,
        mutated_tasks,
        dataset.customers,
        train_task_ids=train_ids,
    )
    assert builder.transductive is False
    assert builder.vectorizer.vocabulary_ == mutated_builder.vectorizer.vocabulary_
    assert np.allclose(builder.vectorizer.idf_, mutated_builder.vectorizer.idf_)
