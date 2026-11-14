# 自然语言任务分类评估

按标题模板分组做 5 折交叉验证，避免同模板泄漏。

| 方案 | alpha | Accuracy | Macro-F1 |
|---|---|---|---|
| 纯 TF-IDF + LR | 1.0 | 1.0000 | 1.0000 |
| 混合（0.6 ML + 0.4 词典） | 0.6 | 1.0000 | 1.0000 |
| 纯词典规则 | 0.0 | 1.0000 | 1.0000 |

手写未见句式 Top-1：1.0000

| 输入 | 期望 | 预测 | 置信度 | 需澄清 |
|---|---|---|---|---|
| 我们要做一个微信小程序，包含会员积分、下单支付和后台管理。 | software_dev | software_dev | 0.504 | 否 |
| 重新设计 App 首页和下单流程，需要 Figma 原型和设计规范。 | ui_ux_design | ui_ux_design | 0.522 | 否 |
| 需要一套品牌 Logo、包装和门店物料设计。 | brand_design | brand_design | 0.540 | 否 |
| 写一篇行业白皮书，要求逻辑清晰、有数据引用。 | content_writing | content_writing | 0.358 | 否 |
| 拍一支 30 秒的抖音投放短视频，包含脚本、拍摄和剪辑。 | video_production | video_production | 0.524 | 否 |
| 策划双十一促销活动，包含投放、物料和复盘。 | marketing_campaign | marketing_campaign | 0.398 | 否 |
| 对 10 万张道路图片做标注，按规范交付并接受质检。 | data_annotation | data_annotation | 0.521 | 否 |
| 把产品说明书翻译成英文和日文，要求术语统一。 | translation_localization | translation_localization | 0.558 | 否 |
| 负责天猫店铺日常运营和活动报名，对 GMV 负责。 | ecommerce_ops | ecommerce_ops | 0.452 | 否 |
| 招聘一名电池工艺工程师，要求 3 年以上经验。 | recruitment | recruitment | 0.460 | 否 |
| 做一份县域文旅产业调研报告，需要访谈和数据分析。 | consulting_research | consulting_research | 0.516 | 否 |
| 给新员工做信息安全培训，需要课件和考试。 | training_course | training_course | 0.480 | 否 |
