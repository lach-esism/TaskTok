"""Evaluate the non-LLM task-text classifier with group-aware CV.

Groups are base titles (variant suffixes removed), so near-duplicate
templates cannot leak between train and test folds.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data.synthetic import generate_dataset  # noqa: E402
from app.nlp.classifier import TaskTextClassifier  # noqa: E402
from app.nlp.lexicon import CATEGORY_LABELS  # noqa: E402

PROBES = [
    ("我们要做一个微信小程序，包含会员积分、下单支付和后台管理。", "software_dev"),
    ("重新设计 App 首页和下单流程，需要 Figma 原型和设计规范。", "ui_ux_design"),
    ("需要一套品牌 Logo、包装和门店物料设计。", "brand_design"),
    ("写一篇行业白皮书，要求逻辑清晰、有数据引用。", "content_writing"),
    ("拍一支 30 秒的抖音投放短视频，包含脚本、拍摄和剪辑。", "video_production"),
    ("策划双十一促销活动，包含投放、物料和复盘。", "marketing_campaign"),
    ("对 10 万张道路图片做标注，按规范交付并接受质检。", "data_annotation"),
    ("把产品说明书翻译成英文和日文，要求术语统一。", "translation_localization"),
    ("负责天猫店铺日常运营和活动报名，对 GMV 负责。", "ecommerce_ops"),
    ("招聘一名电池工艺工程师，要求 3 年以上经验。", "recruitment"),
    ("做一份县域文旅产业调研报告，需要访谈和数据分析。", "consulting_research"),
    ("给新员工做信息安全培训，需要课件和考试。", "training_course"),
]


def text_of(task) -> str:
    return "。".join([task.title, task.description, *task.requirements])


def base_title(title: str) -> str:
    return re.sub(r"（[^）]*）$", "", title)


def evaluate(alpha: float, tasks) -> dict:
    texts = [text_of(task) for task in tasks]
    labels = [task.category for task in tasks]
    groups = [base_title(task.title) for task in tasks]
    predicted = ["" for _ in tasks]

    splitter = GroupKFold(n_splits=5)
    for train_index, test_index in splitter.split(texts, labels, groups):
        model = TaskTextClassifier(alpha=alpha).fit(
            [tasks[index] for index in train_index]
        )
        for index in test_index:
            predicted[index] = model.predict(texts[index])["category"]

    return {
        "alpha": alpha,
        "accuracy": round(accuracy_score(labels, predicted), 4),
        "macro_f1": round(
            f1_score(labels, predicted, average="macro"), 4
        ),
    }


def main() -> None:
    dataset = generate_dataset()
    tasks = dataset.tasks

    results = [evaluate(alpha, tasks) for alpha in (1.0, 0.6, 0.0)]

    probe_model = TaskTextClassifier(alpha=0.6).fit(tasks)
    probes = []
    for text, expected in PROBES:
        result = probe_model.predict(text)
        probes.append(
            {
                "text": text,
                "expected": expected,
                "predicted": result["category"],
                "confidence": result["confidence"],
                "needs_clarification": result["needs_clarification"],
                "correct": result["category"] == expected,
            }
        )

    report = {
        "dataset": {
            "tasks": len(tasks),
            "categories": len({task.category for task in tasks}),
            "labels": CATEGORY_LABELS,
        },
        "grouped_cv": results,
        "handwritten_probes": probes,
        "probe_accuracy": round(
            sum(item["correct"] for item in probes) / len(probes), 4
        ),
    }

    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "text_classifier.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 自然语言任务分类评估",
        "",
        "按标题模板分组做 5 折交叉验证，避免同模板泄漏。",
        "",
        "| 方案 | alpha | Accuracy | Macro-F1 |",
        "|---|---|---|---|",
    ]
    for item in results:
        label = {
            1.0: "纯 TF-IDF + LR",
            0.6: "混合（0.6 ML + 0.4 词典）",
            0.0: "纯词典规则",
        }[item["alpha"]]
        lines.append(
            f"| {label} | {item['alpha']} | {item['accuracy']:.4f} | "
            f"{item['macro_f1']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"手写未见句式 Top-1：{report['probe_accuracy']:.4f}",
            "",
            "| 输入 | 期望 | 预测 | 置信度 | 需澄清 |",
            "|---|---|---|---|---|",
        ]
    )
    for item in probes:
        lines.append(
            f"| {item['text']} | {item['expected']} | {item['predicted']} | "
            f"{item['confidence']:.3f} | {'是' if item['needs_clarification'] else '否'} |"
        )
    (reports / "text_classifier.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
