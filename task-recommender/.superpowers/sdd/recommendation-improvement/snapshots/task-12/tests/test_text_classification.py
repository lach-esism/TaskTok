import pytest

from app.nlp.classifier import extract_fields, get_default_classifier


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "我们要做一个微信小程序，包含会员积分、下单支付和后台管理，希望有相关开发经验。",
            "software_dev",
        ),
        (
            "帮我们重新设计 App 的首页和下单流程，需要 Figma 原型和设计规范。",
            "ui_ux_design",
        ),
        ("需要一套品牌 Logo、包装和门店物料设计。", "brand_design"),
        ("写一篇行业白皮书，要求逻辑清晰、有数据引用。", "content_writing"),
        (
            "拍一支 30 秒的抖音投放短视频，包含脚本、拍摄和剪辑。",
            "video_production",
        ),
        ("策划双十一促销活动，包含投放、物料和复盘。", "marketing_campaign"),
        ("对 10 万张道路图片做标注，按规范交付并接受质检。", "data_annotation"),
        ("把产品说明书翻译成英文和日文，要求术语统一。", "translation_localization"),
        ("负责天猫店铺日常运营和活动报名，对 GMV 负责。", "ecommerce_ops"),
        ("招聘一名电池工艺工程师，要求 3 年以上经验。", "recruitment"),
        ("做一份县域文旅产业调研报告，需要访谈和数据分析。", "consulting_research"),
        ("给新员工做信息安全培训，需要课件和考试。", "training_course"),
    ],
)
def test_classifier_handles_short_natural_language(text, expected):
    result = get_default_classifier().predict(text)
    assert result["category"] == expected
    assert result["needs_clarification"] is False
    assert len(result["candidates"]) == 3


def test_ambiguous_text_asks_for_clarification():
    result = get_default_classifier().predict("帮我做个东西，越快越好。")
    assert result["needs_clarification"] is True


def test_extract_fields_from_natural_language_posting():
    text = (
        "我们要开发一个会员小程序，预算 8,000–30,000 元，期望 30 天内交付，"
        "截止 2026-12-01，支持远程。要求熟悉微信小程序和支付接口，"
        "有同类项目经验优先。"
    )
    fields = extract_fields(text)

    assert fields["suggested_title"] == "开发一个会员小程序"
    assert fields["budget_min"] == 8000
    assert fields["budget_max"] == 30000
    assert fields["budget"] == 19000
    assert fields["duration_days"] == 30
    assert fields["dates"] == ["2026-12-01"]
    assert fields["remote_ok"] is True
    assert any("熟悉微信小程序" in item for item in fields["requirements"])
    assert "frontend" in fields["skills"]
    assert "backend" in fields["skills"]


def test_extract_budget_uses_shared_ten_thousand_unit():
    fields = extract_fields("这个项目预算 1-2 万，要求两周内完成。")
    assert fields["budget_min"] == 10000
    assert fields["budget_max"] == 20000
    assert fields["duration_days"] == 14


def test_classify_endpoint_returns_category_and_fields(client):
    response = client.post(
        "/classify",
        json={
            "text": "招聘一名电池工艺工程师，要求 3 年以上经验，预算 8000 元。",
            "top_k": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "recruitment"
    assert body["suggested_template"] == "recruitment"
    assert len(body["candidates"]) == 2
    assert body["extracted"]["budget_min"] == 8000
    assert "recruiting" in body["extracted"]["skills"]
