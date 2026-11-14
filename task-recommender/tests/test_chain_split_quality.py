from app.chains.split import (
    SplitPolicy,
    apply_split,
    split_quality_score,
)


def test_split_quality_version_and_range(
    small_store, split_task_factory, split_draft_factory
):
    task = split_task_factory(
        "后端接口开发；前端页面；联调测试", estimated_hours=48
    )
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    quality = split_quality_score(
        draft, task, small_store, SplitPolicy()
    )
    assert quality.quality_version == "v2-split"
    assert 0.0 <= quality.total <= 1.0
    assert quality.split_fidelity > 0.99
    assert quality.dependency == 1.0


def test_uncovered_requirement_lowers_coverage(
    small_store, split_task_factory, split_draft_factory
):
    task = split_task_factory("完全无关的一件事", estimated_hours=16)
    draft = apply_split(split_draft_factory(task), task, SplitPolicy())
    quality = split_quality_score(
        draft, task, small_store, SplitPolicy()
    )
    assert quality.coverage < 1.0
    assert draft.uncovered_requirements
