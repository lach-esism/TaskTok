"""Evaluate the non-LLM NLP layer on a hand-written/paraphrased holdout.

Metrics reported per field (precision/recall/F1), per category (top-1,
top-3, macro-F1), calibration (ECE/Brier), and confidence gating
(clarification rate, wrong-confident rate), plus paraphrase/typo/ambiguous
slices. The holdout lives at ``data/lexicon/nlp_holdout.jsonl`` and is
hand-written, so the numbers reflect held-out phrasing rather than the
synthetic templates used for training.

Run from the repo root::

    python scripts/evaluate_nlp.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.nlp.classifier import TaskTextClassifier, get_default_classifier  # noqa: E402
from app.nlp.extract import extract_fields_v2  # noqa: E402
from app.nlp.lexicon import CATEGORY_LABELS  # noqa: E402

HOLDOUT_PATH = ROOT / "data" / "lexicon" / "nlp_holdout.jsonl"
REPORTS_DIR = ROOT / "reports"

#: Fixed evaluation clock; all holdout deadlines are after this instant.
EVAL_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def load_holdout(path: Path | None = None) -> list[dict]:
    path = path or HOLDOUT_PATH
    records = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            records.append(json.loads(line))
    return records


# --------------------------------------------------------------------------
# Field matching
# --------------------------------------------------------------------------
def _budget_match(predicted: list | None, labels: dict) -> bool | None:
    if "budget_min" not in labels and "budget_max" not in labels:
        return None
    if not predicted:
        return False
    low, high = predicted
    return (
        low == labels.get("budget_min")
        and high == labels.get("budget_max")
    )


def _scalar_match(predicted, expected) -> bool | None:
    if expected is None:
        return None
    if predicted is None:
        return False
    if isinstance(expected, float) and isinstance(predicted, float):
        return abs(predicted - expected) < 0.011
    return predicted == expected


def _language_match(predicted: list, labels: dict) -> bool | None:
    expected = labels.get("languages")
    if expected is None:
        return None
    return set(predicted or []) == set(expected)


def _skill_match(predicted: list, labels: dict) -> tuple[int, int, int] | None:
    expected = labels.get("skills")
    if expected is None:
        return None
    pred_set = set(predicted or [])
    exp_set = set(expected)
    tp = len(pred_set & exp_set)
    fp = len(pred_set - exp_set)
    fn = len(exp_set - pred_set)
    return tp, fp, fn


def _field_outcomes(records: list[dict], now: datetime) -> dict:
    """Return per-field TP/FP/FN counts and skill micro counts."""
    fields = (
        "budget",
        "duration",
        "date",
        "remote",
        "count",
        "experience",
        "language",
    )
    counts = {field: {"tp": 0, "fp": 0, "fn": 0} for field in fields}
    skill_tp = skill_fp = skill_fn = 0
    for record in records:
        extracted = extract_fields_v2(record["text"], now=now)
        labels = record.get("fields", {})

        budget_match = _budget_match(extracted["budget"]["value"], labels)
        if budget_match is not None:
            if budget_match:
                counts["budget"]["tp"] += 1
            elif labels.get("budget_min") is not None:
                counts["budget"]["fn"] += 1
            else:
                counts["budget"]["fp"] += 1

        scalar_fields = (
            ("duration", extracted["duration"]["value"], "duration_days"),
            ("date", extracted["date"]["value"], "date"),
            ("remote", extracted["remote"]["value"], "remote_ok"),
            ("count", extracted["count"]["value"], "count"),
            ("experience", extracted["experience"]["value"], "experience"),
        )
        for field, pred, label_key in scalar_fields:
            expected = labels.get(label_key)
            match = _scalar_match(pred, expected)
            if match is None:
                continue
            if match:
                counts[field]["tp"] += 1
            elif expected is not None:
                counts[field]["fn"] += 1
            else:
                counts[field]["fp"] += 1

        lang_match = _language_match(extracted["language"]["value"], labels)
        if lang_match is not None:
            if lang_match:
                counts["language"]["tp"] += 1
            elif labels.get("languages"):
                counts["language"]["fn"] += 1
            else:
                counts["language"]["fp"] += 1

        skill_outcome = _skill_match(extracted["skills"]["value"], labels)
        if skill_outcome is not None:
            tp, fp, fn = skill_outcome
            skill_tp += tp
            skill_fp += fp
            skill_fn += fn

    return counts, (skill_tp, skill_fp, skill_fn)


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def _ece(confs: list[float], correct: list[int], bins: int = 10) -> float:
    if not confs:
        return 0.0
    total = 0.0
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        bucket = [
            (confidence, label)
            for confidence, label in zip(confs, correct, strict=True)
            if low <= confidence < high or (high == 1.0 and confidence == 1.0)
        ]
        if not bucket:
            continue
        avg_conf = sum(item[0] for item in bucket) / len(bucket)
        accuracy = sum(item[1] for item in bucket) / len(bucket)
        total += (len(bucket) / len(confs)) * abs(avg_conf - accuracy)
    return round(total, 4)


def _brier(confs: list[float], correct: list[int]) -> float:
    if not confs:
        return 0.0
    total = sum(
        (confidence - label) ** 2
        for confidence, label in zip(confs, correct, strict=True)
    )
    return round(total / len(confs), 4)


def evaluate_nlp(
    records: list[dict],
    classifier: TaskTextClassifier | None = None,
    now: datetime | None = None,
) -> dict:
    """Evaluate classification, fields, calibration, and gating."""
    classifier = classifier or get_default_classifier()
    now = now or EVAL_NOW

    y_true: list[str] = []
    y_pred: list[str] = []
    top3_hits = 0
    confs: list[float] = []
    correct: list[int] = []
    flagged = 0
    wrong_confident = 0
    labeled_total = 0
    slice_stats: dict[str, dict] = {}
    slice_category: dict[str, dict] = {}

    for record in records:
        result = classifier.predict(record["text"], now=now)
        slice_name = record.get("slice", "other")
        stats = slice_stats.setdefault(
            slice_name, {"total": 0, "correct": 0, "flagged": 0, "labeled": 0}
        )
        cat_stats = slice_category.setdefault(
            slice_name, {"y_true": [], "y_pred": [], "top3": 0, "labeled": 0}
        )
        stats["total"] += 1

        if result["needs_clarification"]:
            flagged += 1
            stats["flagged"] += 1

        category = record.get("category")
        if category is None:
            continue
        labeled_total += 1
        predicted = result["category"]
        is_correct = predicted == category
        y_true.append(category)
        y_pred.append(predicted)
        confs.append(float(result["calibrated_confidence"]))
        correct.append(1 if is_correct else 0)
        stats["labeled"] += 1
        cat_stats["labeled"] += 1
        cat_stats["y_true"].append(category)
        cat_stats["y_pred"].append(predicted)
        if is_correct:
            stats["correct"] += 1
        if category in {item["category"] for item in result["candidates"]}:
            top3_hits += 1
            cat_stats["top3"] += 1
        if not is_correct and not result["needs_clarification"]:
            wrong_confident += 1

    from sklearn.metrics import f1_score

    # Compute slice-level top-3 from the pre-aggregated counters.
    category_slices: dict[str, dict] = {}
    for name, cat in sorted(slice_category.items()):
        total = cat["labeled"]
        if not total:
            category_slices[name] = {"top1": 0.0, "top3": 0.0, "macro_f1": 0.0, "n": 0}
            continue
        hits = sum(
            1 for true, pred in zip(cat["y_true"], cat["y_pred"], strict=True)
            if true == pred
        )
        category_slices[name] = {
            "top1": round(hits / total, 4),
            "top3": round(cat["top3"] / total, 4),
            "macro_f1": round(
                f1_score(cat["y_true"], cat["y_pred"], average="macro", zero_division=0.0),
                4,
            ),
            "n": total,
        }

    # Aggregate "easy" (paraphrase + typo) vs "hard" slices.
    easy_true = [
        value
        for name in ("paraphrase", "typo")
        for value in slice_category.get(name, {}).get("y_true", [])
    ]
    easy_pred = [
        value
        for name in ("paraphrase", "typo")
        for value in slice_category.get(name, {}).get("y_pred", [])
    ]
    easy_top3 = sum(
        slice_category.get(name, {}).get("top3", 0)
        for name in ("paraphrase", "typo")
    )
    hard_true = slice_category.get("hard", {}).get("y_true", [])
    hard_pred = slice_category.get("hard", {}).get("y_pred", [])
    hard_top3 = slice_category.get("hard", {}).get("top3", 0)

    def _summary(true_list: list[str], pred_list: list[str], top3: int) -> dict:
        total = len(true_list)
        if not total:
            return {"top1": 0.0, "top3": 0.0, "macro_f1": 0.0, "n": 0}
        hits = sum(
            1 for true, pred in zip(true_list, pred_list, strict=True)
            if true == pred
        )
        return {
            "top1": round(hits / total, 4),
            "top3": round(top3 / total, 4),
            "macro_f1": round(
                f1_score(true_list, pred_list, average="macro", zero_division=0.0),
                4,
            ),
            "n": total,
        }

    easy_summary = _summary(easy_true, easy_pred, easy_top3)
    hard_summary = _summary(hard_true, hard_pred, hard_top3)

    macro_f1 = (
        f1_score(y_true, y_pred, average="macro", zero_division=0.0)
        if y_true
        else 0.0
    )
    top1 = sum(correct) / labeled_total if labeled_total else 0.0
    top3 = top3_hits / labeled_total if labeled_total else 0.0

    field_counts, skill_counts = _field_outcomes(records, now)
    field_metrics = {
        field: _prf(**field_counts[field]) for field in field_counts
    }
    skill_tp, skill_fp, skill_fn = skill_counts
    field_metrics["skills"] = _prf(skill_tp, skill_fp, skill_fn)

    total_records = len(records)
    return {
        "dataset": {
            "records": total_records,
            "labeled": labeled_total,
            "slices": {
                name: {
                    "total": stats["total"],
                    "labeled": stats["labeled"],
                    "top1_accuracy": round(
                        stats["correct"] / stats["labeled"], 4
                    )
                    if stats["labeled"]
                    else 0.0,
                    "clarification_rate": round(
                        stats["flagged"] / stats["total"], 4
                    )
                    if stats["total"]
                    else 0.0,
                }
                for name, stats in sorted(slice_stats.items())
            },
        },
        "category": {
            "top1": round(top1, 4),
            "top3": round(top3, 4),
            "macro_f1": round(macro_f1, 4),
            "easy": easy_summary,
            "hard": hard_summary,
            "by_slice": category_slices,
        },
        "fields": field_metrics,
        "calibration": {
            "method": getattr(classifier, "calibration_method", "unknown"),
            "ece": _ece(confs, correct),
            "brier": _brier(confs, correct),
            "mean_confidence": round(
                sum(confs) / len(confs), 4
            )
            if confs
            else 0.0,
        },
        "gating": {
            "clarification_rate": round(flagged / total_records, 4)
            if total_records
            else 0.0,
            "wrong_confident_rate": round(wrong_confident / labeled_total, 4)
            if labeled_total
            else 0.0,
            "wrong_confident": wrong_confident,
        },
    }


def _render_markdown(metrics: dict, baseline: dict) -> str:
    hard = metrics["category"]["hard"]
    easy = metrics["category"]["easy"]
    cal_method = metrics["calibration"].get("method", "unknown")
    cal_note = (
        "拟合 Platt 校准"
        if cal_method == "platt"
        else "固定先验（未证明校准）"
    )
    ece_verdict = (
        "PASS"
        if cal_method == "platt" and metrics["calibration"]["ece"] <= 0.10
        else "NOT DEMONSTRATED"
    )
    clar = metrics["gating"]["clarification_rate"]
    wrong = metrics["gating"]["wrong_confident_rate"]
    top1_delta = hard["top1"] - baseline.get("hard_top1", 0.0)
    top1_verdict = (
        f"{top1_delta:+.4f}"
        if top1_delta >= 0.03
        else "NOT DEMONSTRATED"
    )
    lines = [
        "# NLP 层评估报告",
        "",
        f"Holdout：{metrics['dataset']['records']} 条手写/改写样本，"
        f"{metrics['dataset']['labeled']} 条带类别标签。",
        "",
        "## 类别分类（Easy = 改写 + 错别字切片，Hard = 去除判别词切片）",
        "",
        "| 指标 | 目标 | Easy | Hard | 判定 |",
        "|---|---|---|---|---|",
        f"| Top-1 | ≥ baseline + 3pp（Hard） | {easy['top1']:.4f} | {hard['top1']:.4f} | "
        f"{top1_verdict} |",
        f"| Top-3 | ≥ 0.95（Hard） | {easy['top3']:.4f} | {hard['top3']:.4f} | "
        f"{'PASS' if hard['top3'] >= 0.95 else 'NOT DEMONSTRATED'} |",
        f"| Macro-F1 | ≥ 0.80（Hard） | {easy['macro_f1']:.4f} | {hard['macro_f1']:.4f} | "
        f"{'PASS' if hard['macro_f1'] >= 0.80 else 'NOT DEMONSTRATED'} |",
        "",
        "## 字段抽取（P / R / F1，全 holdout）",
        "",
        "| 字段 | Precision | Recall | F1 | TP/FP/FN |",
        "|---|---|---|---|---|",
    ]
    for field, value in metrics["fields"].items():
        lines.append(
            f"| {field} | {value['precision']:.4f} | {value['recall']:.4f} | "
            f"{value['f1']:.4f} | {value['tp']}/{value['fp']}/{value['fn']} |"
        )
    lines.extend(
        [
            "",
            "## 校准与置信度",
            "",
            f"校准方式：**{cal_note}**。",
            "",
            "| 指标 | 目标 | 实测 | 判定 |",
            "|---|---|---|---|",
            f"| ECE | ≤ 0.10（需拟合校准） | {metrics['calibration']['ece']:.4f} | {ece_verdict} |",
            f"| Brier | — | {metrics['calibration']['brier']:.4f} | — |",
            f"| 澄清率 | ≤ 15% | {clar:.4f} | {'PASS' if clar <= 0.15 else 'NOT DEMONSTRATED'} |",
            f"| 错误自信率 | < 5% | {wrong:.4f} | {'PASS' if wrong < 0.05 else 'NOT DEMONSTRATED'} |",
            "",
            "## 切片",
            "",
            "| 切片 | 样本 | 带标签 | Top-1 | 澄清率 |",
            "|---|---|---|---|---|",
        ]
    )
    for name, value in metrics["dataset"]["slices"].items():
        lines.append(
            f"| {name} | {value['total']} | {value['labeled']} | "
            f"{value['top1_accuracy']:.4f} | {value['clarification_rate']:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _baseline_top1(records: list[dict], now: datetime) -> dict:
    """Top-1 of the pre-calibration (same ranking) classifier for reference."""
    from app.data.synthetic import generate_dataset

    baseline_model = TaskTextClassifier(alpha=0.6, calibrate=False).fit(
        generate_dataset().tasks
    )
    totals: dict[str, int] = {}
    hits: dict[str, int] = {}
    for record in records:
        if record.get("category") is None:
            continue
        slice_name = record.get("slice", "other")
        totals[slice_name] = totals.get(slice_name, 0) + 1
        if baseline_model.predict(record["text"], now=now)["category"] == record["category"]:
            hits[slice_name] = hits.get(slice_name, 0) + 1

    total = sum(totals.values())
    hit_total = sum(hits.values())
    hard_total = totals.get("hard", 0)
    hard_hits = hits.get("hard", 0)
    return {
        "top1": round(hit_total / total, 4) if total else 0.0,
        "hard_top1": round(hard_hits / hard_total, 4) if hard_total else 0.0,
        "n": total,
    }


def main() -> None:
    records = load_holdout()
    metrics = evaluate_nlp(records)
    baseline = _baseline_top1(records, EVAL_NOW)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"metrics": metrics, "baseline": baseline}
    (REPORTS_DIR / "nlp_eval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPORTS_DIR / "nlp_eval.md").write_text(
        _render_markdown(metrics, baseline) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
