import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from app.data.synthetic import generate_dataset
from app.nlp.classifier import TaskTextClassifier

ROOT = Path(__file__).resolve().parent.parent


def _load_evaluate_nlp():
    spec = importlib.util.spec_from_file_location(
        "evaluate_nlp", ROOT / "scripts" / "evaluate_nlp.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _classifier():
    dataset = generate_dataset(
        n_workers=5, n_tasks=40, n_assignments=20, seed=7, n_new_users=0
    )
    return TaskTextClassifier(alpha=0.6, calibrate=False).fit(dataset.tasks)


def test_evaluate_nlp_returns_expected_sections():
    evaluate = _load_evaluate_nlp()
    records = [
        {
            "id": "t1",
            "slice": "paraphrase",
            "category": "software_dev",
            "text": "我们要做一个微信小程序，包含会员积分和下单支付，预算 8000–30000 元，30 天内交付，截止 2026-12-20，支持远程。",
            "fields": {
                "budget_min": 8000,
                "budget_max": 30000,
                "duration_days": 30,
                "date": "2026-12-20",
                "remote_ok": True,
            },
        },
        {
            "id": "t2",
            "slice": "ambiguous",
            "category": None,
            "text": "帮我做个东西，越快越好。",
            "fields": {},
        },
    ]
    metrics = evaluate.evaluate_nlp(
        records,
        classifier=_classifier(),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert "category" in metrics
    assert "top1" in metrics["category"]
    assert "top3" in metrics["category"]
    assert "macro_f1" in metrics["category"]
    assert "easy" in metrics["category"]
    assert "hard" in metrics["category"]
    assert "budget" in metrics["fields"]
    assert "duration" in metrics["fields"]
    assert "date" in metrics["fields"]
    assert "remote" in metrics["fields"]
    assert "method" in metrics["calibration"]
    assert "ece" in metrics["calibration"]
    assert "brier" in metrics["calibration"]
    assert "clarification_rate" in metrics["gating"]
    assert "wrong_confident_rate" in metrics["gating"]
    assert "slices" in metrics["dataset"]


def test_evaluate_nlp_holdout_file_loads():
    evaluate = _load_evaluate_nlp()
    records = evaluate.load_holdout()
    assert len(records) >= 50
    assert all("text" in record for record in records)
    assert all("slice" in record for record in records)
    assert any(record["slice"] == "typo" for record in records)
    assert any(record["slice"] == "paraphrase" for record in records)
    hard = [record for record in records if record["slice"] == "hard"]
    assert 20 <= len(hard) <= 40
