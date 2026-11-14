"""Category-specific module and batch rules for task-chain splitting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleRule:
    """A splittable module within a task category."""

    key: str
    label: str
    keywords: tuple[str, ...]
    skills: dict[str, int]


@dataclass(frozen=True)
class BatchRule:
    """Batch sizing hints for a splittable task category."""

    units: tuple[str, ...]
    default_batch_size: int


MODULE_RULES = {
    "software_dev": (
        ModuleRule(
            "backend",
            "后端",
            ("后端", "服务端", "接口", "API", "数据库"),
            {"backend": 4},
        ),
        ModuleRule(
            "frontend",
            "前端",
            ("前端", "页面", "UI", "小程序", "App"),
            {"frontend": 4},
        ),
        ModuleRule(
            "integration",
            "联调",
            ("联调", "集成", "接口对接"),
            {"frontend": 3, "backend": 3},
        ),
        ModuleRule(
            "dashboard",
            "数据看板",
            ("数据看板", "报表", "看板"),
            {"backend": 3},
        ),
        ModuleRule("payment", "支付", ("支付", "结算"), {"backend": 4}),
        ModuleRule("membership", "会员", ("会员", "账户"), {"backend": 3}),
    ),
    "data_annotation": (
        ModuleRule(
            "batch_annotation", "标注", ("标注", "打标"), {"annotation": 3}
        ),
        ModuleRule("qa", "质检", ("质检", "验收"), {"qa": 3}),
    ),
    "translation_localization": (
        ModuleRule(
            "translation", "翻译", ("翻译", "本地化"), {"translation": 3}
        ),
        ModuleRule("review", "校对", ("校对", "审校"), {"proofreading": 3}),
    ),
    "content_writing": (
        ModuleRule(
            "draft", "撰写", ("撰写", "章节", "稿件", "正文"), {"writing": 3}
        ),
        ModuleRule("edit", "编辑", ("编辑", "润色"), {"editing": 3}),
    ),
    "video_production": (
        ModuleRule(
            "storyboard", "分镜", ("分镜", "脚本"), {"storyboard": 3}
        ),
        ModuleRule("shoot", "拍摄", ("拍摄", "摄影"), {"videography": 3}),
        ModuleRule("edit", "剪辑", ("剪辑", "后期"), {"video_editing": 3}),
    ),
}

BATCH_RULES = {
    "data_annotation": BatchRule(("条", "个", "张", "段"), 500),
    "translation_localization": BatchRule(("字", "词", "页", "章"), 2000),
    "content_writing": BatchRule(("字", "章", "篇", "节"), 3000),
}
DEFAULT_BATCH_RULE = BatchRule(
    ("条", "个", "页", "张", "篇", "章", "节"), 500
)


def rules_for(category: str | None) -> tuple[ModuleRule, ...]:
    """Return the module rules for a category, or an empty tuple."""
    if not category:
        return ()
    return MODULE_RULES.get(category, ())


def batch_rule_for(category: str | None) -> BatchRule:
    """Return the batch rule for a category, falling back to the default."""
    if not category:
        return DEFAULT_BATCH_RULE
    return BATCH_RULES.get(category, DEFAULT_BATCH_RULE)
