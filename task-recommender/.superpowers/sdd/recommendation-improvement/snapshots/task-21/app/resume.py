"""Turn internal worker records into a human-readable resume.

The resume is deterministic per worker. Internal scores remain available
under ``platform_data`` but are never used to build the visible surface.
All names, companies and projects are synthetic.
"""

from __future__ import annotations

import random
import statistics
from datetime import datetime, timezone

from app.domain import Worker
from app.nlp.lexicon import CATEGORY_LABELS

SURNAMES = list("陈林周沈顾许叶程苏陆何宋唐韩冯邓")
GIVEN_FIRST = list("思雨嘉子若明知一景书清可亦安望映之楚云星")
GIVEN_SECOND = list("远桐宁墨溪轩夏诺行言和欣辰澜舒川然舟遥白")

CITIES = {
    "CN": ["上海", "北京", "深圳", "杭州", "成都", "广州", "南京"],
    "US": ["旧金山", "纽约", "西雅图", "波士顿"],
    "EU": ["柏林", "伦敦", "巴黎", "阿姆斯特丹"],
}

UNIVERSITIES = {
    "CN": ["复旦大学", "上海交通大学", "浙江大学", "南京大学", "武汉大学"],
    "US": ["UC Berkeley", "New York University", "University of Washington"],
    "EU": ["TU Berlin", "University College London", "HEC Paris"],
}

SKILL_LABELS = {
    "requirements": "需求分析",
    "architecture": "系统架构",
    "backend": "后端开发",
    "frontend": "前端开发",
    "qa": "测试与质量",
    "devops": "部署运维",
    "ux": "用户体验",
    "ui": "界面设计",
    "research": "行业研究",
    "brand": "品牌策略",
    "graphic_design": "平面与包装",
    "writing": "内容写作",
    "editing": "编辑审校",
    "publishing": "排版发布",
    "video": "视频制作",
    "shooting": "拍摄",
    "video_editing": "剪辑后期",
    "audio": "配音与音频",
    "marketing": "营销策划",
    "creative": "创意策划",
    "analytics": "数据分析",
    "data_labeling": "数据标注",
    "qa_labeling": "标注质检",
    "translation": "翻译",
    "localization": "本地化",
    "ecommerce": "电商运营",
    "customer_service": "客户服务",
    "recruiting": "招聘",
    "sourcing": "人才寻访",
    "interviewing": "面试评估",
    "hr": "人力资源",
    "consulting": "管理咨询",
    "analysis": "商业分析",
    "presentation": "汇报呈现",
    "training_design": "课程设计",
    "content_development": "课件开发",
    "security": "信息安全",
    "design": "视觉设计",
    "operations": "运营管理",
    "legal": "法务合规",
}

CATEGORY_PROFILES = {
    "software_dev": {
        "headline": "全栈开发工程师 / 小程序与业务系统",
        "titles": ["高级全栈工程师", "后端工程师", "技术负责人"],
        "companies": ["云启科技", "数联软件", "星链网络"],
        "majors": ["计算机科学与技术", "软件工程", "信息管理"],
        "tags": ["小程序", "支付系统", "接口联调", "系统架构"],
        "responsibilities": [
            "负责核心业务模块的设计、开发与上线",
            "主导接口联调、性能优化与线上问题排查",
        ],
        "projects": [
            ("连锁零售会员小程序", "核心开发", "负责支付、积分与订单模块，2 个月上线", "接口平均响应从 800ms 降到 220ms"),
            ("制造业 ERP 库存升级", "后端负责人", "重构库存与调拨接口，支撑 12 个仓库", "上线后库存差异率下降 35%"),
        ],
        "certifications": ["AWS Certified Developer", "PMP"],
    },
    "ui_ux_design": {
        "headline": "UI/UX 设计师 / B 端与移动端体验",
        "titles": ["高级体验设计师", "UI/UX 设计师", "设计负责人"],
        "companies": ["像素设计", "体验实验室", "木棉设计"],
        "majors": ["视觉传达设计", "工业设计", "数字媒体"],
        "tags": ["Figma", "信息架构", "可点击原型", "设计规范"],
        "responsibilities": [
            "负责关键流程的用户研究、信息架构与高保真设计",
            "推动设计规范落地并配合开发走查",
        ],
        "projects": [
            ("SaaS 数据看板改版", "主设计师", "重构信息架构与 6 个核心看板", "上线后关键任务完成率提升 28%"),
            ("医疗预约小程序体验优化", "体验设计", "重做挂号与支付流程，输出可点击原型", "用户投诉率下降 40%"),
        ],
        "certifications": ["Figma 专业认证", "NN/g UX 认证"],
    },
    "brand_design": {
        "headline": "品牌设计师 / VI、包装与门店物料",
        "titles": ["品牌设计主管", "资深平面设计师", "视觉负责人"],
        "companies": ["造物品牌", "白昼设计", "有光创意"],
        "majors": ["视觉传达设计", "广告学", "艺术设计"],
        "tags": ["品牌 VI", "包装设计", "Logo", "门店物料"],
        "responsibilities": [
            "负责品牌视觉概念、Logo 与基础规范",
            "跟进包装印刷工艺与门店物料落地",
        ],
        "projects": [
            ("新茶饮品牌 VI 与包装", "品牌主设计", "完成 VI、杯贴与礼盒包装延展", "支持 30 家门店统一换新"),
            ("宠物食品品牌视觉升级", "视觉负责人", "重做 Logo、色彩与电商主视觉", "首月店铺转化率提升 18%"),
        ],
        "certifications": ["Adobe 认证设计师", "包装印刷工艺认证"],
    },
    "content_writing": {
        "headline": "内容策划 / 行业研究、品牌文案与白皮书",
        "titles": ["资深内容策划", "行业研究员", "品牌文案"],
        "companies": ["知行内容", "青禾文化", "远见研究所"],
        "majors": ["新闻传播学", "汉语言文学", "经济学"],
        "tags": ["行业白皮书", "品牌文案", "深度访谈", "官网内容"],
        "responsibilities": [
            "负责选题、资料研究、访谈与成稿",
            "把专业内容转成可读的官网、销售与投放素材",
        ],
        "projects": [
            ("工业机器人选型白皮书", "主笔", "完成 3 万字白皮书与 12 个案例", "被 20 家企业用于销售材料"),
            ("SaaS 产品官网内容重构", "内容负责人", "重写首页、产品页与客户案例", "官网留资率提升 22%"),
        ],
        "certifications": ["CATTI 三级笔译", "Google Analytics 认证"],
    },
    "video_production": {
        "headline": "视频导演 / 短视频、宣传片与产品演示",
        "titles": ["视频导演", "资深剪辑师", "内容制作负责人"],
        "companies": ["光年影像", "逐帧工作室", "野火视频"],
        "majors": ["影视摄影与制作", "广播电视编导", "数字媒体艺术"],
        "tags": ["短视频", "宣传片", "分镜脚本", "剪辑后期"],
        "responsibilities": [
            "负责脚本、分镜、拍摄与剪辑全流程",
            "适配抖音、视频号等竖屏平台的节奏与规格",
        ],
        "projects": [
            ("618 家电品牌信息流短视频", "导演/剪辑", "完成 6 条 30 秒竖屏素材", "投放 CTR 高于行业均值 35%"),
            ("新能源汽车功能介绍视频", "视频负责人", "脚本、拍摄与三维演示整合", "用于发布会与门店循环播放"),
        ],
        "certifications": ["DaVinci Resolve 认证", "无人机航拍证"],
    },
    "marketing_campaign": {
        "headline": "整合营销策划 / 活动、投放与复盘",
        "titles": ["营销策划经理", "整合营销负责人", "增长策划"],
        "companies": ["原野营销", "橙子创意", "增长工场"],
        "majors": ["市场营销", "广告学", "工商管理"],
        "tags": ["整合营销", "活动策划", "投放策略", "数据复盘"],
        "responsibilities": [
            "负责策略、创意、渠道与预算规划",
            "跟踪核心指标并输出投放与活动复盘",
        ],
        "projects": [
            ("商场周年庆整合营销", "项目负责人", "统筹线上投放与线下活动", "活动期客流同比增长 26%"),
            ("新消费品牌新品上市", "营销策划", "完成种子用户、内容与渠道组合", "首月售罄率超过 80%"),
        ],
        "certifications": ["Google Ads 认证", "巨量千川投放认证"],
    },
    "data_annotation": {
        "headline": "数据标注项目负责人 / 图像、语音与文本",
        "titles": ["标注项目经理", "数据质检负责人", "标注组长"],
        "companies": ["数标科技", "清源数据", "标点智能"],
        "majors": ["信息管理", "统计学", "计算机应用"],
        "tags": ["图像标注", "语音转写", "标注规范", "质量抽检"],
        "responsibilities": [
            "负责标注规范、人员培训与进度管理",
            "执行质检、抽检与返修，保证一致率",
        ],
        "projects": [
            ("自动驾驶路侧图像标注", "项目负责人", "完成 10 万帧标注与 3 轮质检", "抽检一致率保持在 98% 以上"),
            ("语音客服对话转写", "质检负责人", "制定转写规范并培训 40 名标注员", "返修率从 12% 降到 4%"),
        ],
        "certifications": ["数据标注项目管理认证", "保密与数据安全培训"],
    },
    "translation_localization": {
        "headline": "本地化译者 / 中英日与行业术语",
        "titles": ["资深本地化译者", "技术翻译", "本地化项目经理"],
        "companies": ["译言本地化", "桥接语言服务", "东岸翻译"],
        "majors": ["翻译学", "英语语言文学", "日语"],
        "tags": ["中英日翻译", "术语管理", "审校", "界面本地化"],
        "responsibilities": [
            "负责翻译、审校与术语统一",
            "按目标市场规范完成界面与文档本地化",
        ],
        "projects": [
            ("医疗器械说明书中英日本地化", "主译/审校", "完成 3 语种术语表与终稿", "通过客户合规评审"),
            ("SaaS 产品界面本地化", "本地化负责人", "统一 600 条界面文案与术语", "上线后海外工单下降 30%"),
        ],
        "certifications": ["CATTI 二级笔译", "SDL Trados 认证"],
    },
    "ecommerce_ops": {
        "headline": "电商运营 / 店铺、投流与私域复购",
        "titles": ["电商运营经理", "店铺负责人", "增长运营"],
        "companies": ["海川电商", "橙链科技", "远航品牌"],
        "majors": ["电子商务", "市场营销", "国际贸易"],
        "tags": ["天猫运营", "独立站", "投流", "复购增长"],
        "responsibilities": [
            "负责店铺日常运营、活动报名与商品页优化",
            "跟踪转化率、ROI 与复购并持续复盘",
        ],
        "projects": [
            ("跨境电商独立站黑五运营", "运营负责人", "统筹选品、投放与站内活动", "黑五 GMV 同比增长 65%"),
            ("天猫旗舰店日常托管", "店铺负责人", "优化详情页与活动节奏", "月转化率从 1.8% 提升到 2.6%"),
        ],
        "certifications": ["天猫运营认证", "Google Analytics 认证"],
    },
    "recruitment": {
        "headline": "招聘顾问 / 制造、新能源与互联网",
        "titles": ["资深招聘顾问", "猎头顾问", "招聘负责人"],
        "companies": ["伯乐猎聘", "远航人才", "锐仕咨询"],
        "majors": ["人力资源管理", "心理学", "工商管理"],
        "tags": ["人才寻访", "岗位画像", "面试评估", "Offer 跟进"],
        "responsibilities": [
            "负责岗位画像、人才寻访与候选人筛选",
            "协调面试、Offer 与入职跟进",
        ],
        "projects": [
            ("新能源电池厂工艺工程师招聘", "项目顾问", "完成 18 个关键岗位寻访", "到岗率 83%，试用期留存 90%"),
            ("AI 创业公司算法团队搭建", "招聘负责人", "搭建 12 人算法团队", "平均到岗周期 38 天"),
        ],
        "certifications": ["人力资源管理师", "领英人才解决方案认证"],
    },
    "consulting_research": {
        "headline": "战略咨询顾问 / 市场进入与竞品研究",
        "titles": ["高级咨询顾问", "行业研究负责人", "战略分析师"],
        "companies": ["行远咨询", "灼识咨询", "远见研究所"],
        "majors": ["管理学", "经济学", "金融学"],
        "tags": ["市场进入", "竞品分析", "专家访谈", "管理层汇报"],
        "responsibilities": [
            "负责研究框架、访谈、数据测算与报告撰写",
            "向管理层汇报结论并支持进入决策",
        ],
        "projects": [
            ("县域文旅产业升级调研", "项目经理", "完成 24 场访谈与 3 个案例研究", "报告被用于年度规划"),
            ("新能源产业链投资研究", "研究负责人", "搭建市场规模与竞争格局模型", "支持 2 个标的的投决"),
        ],
        "certifications": ["PMP", "CFA Level II"],
    },
    "training_course": {
        "headline": "企业培训讲师 / 课程开发与交付",
        "titles": ["高级培训讲师", "课程开发负责人", "学习发展顾问"],
        "companies": ["知行学堂", "启程培训", "砾石学习"],
        "majors": ["教育学", "心理学", "工商管理"],
        "tags": ["课程开发", "讲师手册", "考试评估", "训练营"],
        "responsibilities": [
            "负责需求分析、课程设计与课件开发",
            "完成现场/线上授课与效果评估",
        ],
        "projects": [
            ("新员工信息安全意识培训", "课程负责人", "开发 6 门课程与在线考试", "覆盖 1,200 名员工"),
            ("连锁门店店长训练营", "主讲/设计", "设计 4 周训练营与实战任务", "结营考核通过率 92%"),
        ],
        "certifications": ["企业培训师认证", "ATD 课程设计认证"],
    },
}

REGION_LABELS = {"CN": "中国大陆", "US": "美国", "EU": "欧洲"}

CATEGORY_SKILLS = {
    "software_dev": {
        "requirements", "architecture", "backend", "frontend", "qa", "devops"
    },
    "ui_ux_design": {"ux", "ui", "research", "design"},
    "brand_design": {"brand", "graphic_design", "design"},
    "content_writing": {"writing", "editing", "research", "publishing"},
    "video_production": {"video", "shooting", "video_editing", "audio"},
    "marketing_campaign": {"marketing", "creative", "analytics", "operations"},
    "data_annotation": {"data_labeling", "qa_labeling", "operations"},
    "translation_localization": {"translation", "localization", "editing"},
    "ecommerce_ops": {
        "ecommerce", "operations", "marketing", "analytics", "customer_service"
    },
    "recruitment": {"recruiting", "sourcing", "interviewing", "hr"},
    "consulting_research": {
        "research", "consulting", "analysis", "presentation", "writing"
    },
    "training_course": {
        "training_design", "content_development", "presentation", "hr"
    },
}


def _rng(worker: Worker) -> random.Random:
    return random.Random(f"{worker.worker_id}|resume")


def _name(rng: random.Random) -> str:
    return (
        rng.choice(SURNAMES)
        + rng.choice(GIVEN_FIRST)
        + rng.choice(GIVEN_SECOND)
    )


def _top_category(worker: Worker) -> str:
    if not worker.specialties:
        return "consulting_research"
    return max(
        worker.specialties,
        key=lambda key: (worker.specialties[key], key),
    )


def _skill_tags(
    worker: Worker, category: str, profile: dict
) -> list[str]:
    ranked = sorted(
        worker.skills.items(),
        key=lambda item: (-item[1], item[0]),
    )
    relevant = CATEGORY_SKILLS.get(category, set())
    tags = list(profile["tags"])
    for skill, _ in ranked:
        if skill not in relevant:
            continue
        label = SKILL_LABELS.get(skill)
        if label and label not in tags:
            tags.append(label)
        if len(tags) >= 8:
            break
    return tags[:8]


def _years(worker: Worker, rng: random.Random) -> int:
    return max(3, 2 + worker.level * 2 + rng.randint(0, 3))


def _rating(worker: Worker) -> float:
    return round(statistics.mean(worker.ratings), 1) if worker.ratings else 4.5


def _on_time_rate(worker: Worker) -> float:
    if worker.completed <= 0:
        return 0.9
    return round(worker.on_time / worker.completed, 3)


def _education(worker: Worker, profile: dict, rng: random.Random) -> str:
    university = rng.choice(UNIVERSITIES.get(worker.region, UNIVERSITIES["CN"]))
    degree = "硕士" if worker.level >= 4 else "学士"
    major = rng.choice(profile["majors"])
    return f"{university} · {major}{degree}"


def _work_experience(
    worker: Worker,
    profile: dict,
    years: int,
    rng: random.Random,
    now: datetime,
) -> list[dict]:
    current_year = now.year
    companies = list(profile["companies"])
    titles = list(profile["titles"])
    rng.shuffle(companies)
    rng.shuffle(titles)
    entries = [
        {
            "company": companies[0],
            "title": titles[0],
            "period": f"{current_year - 3} – 至今",
            "bullets": list(profile["responsibilities"]),
        },
        {
            "company": companies[1],
            "title": titles[1],
            "period": f"{current_year - years} – {current_year - 3}",
            "bullets": [profile["responsibilities"][0]],
        },
    ]
    return entries


def _projects(profile: dict, rng: random.Random) -> list[dict]:
    projects = list(profile["projects"])
    rng.shuffle(projects)
    return [
        {
            "name": name,
            "role": role,
            "bullets": [bullet_one, bullet_two],
        }
        for name, role, bullet_one, bullet_two in projects[:2]
    ]


def _expected_rate(worker: Worker, rng: random.Random) -> str:
    low = 600 + worker.level * 320 + rng.randint(0, 200)
    high = low + 600 + rng.randint(0, 500)
    return f"¥{low:,}–{high:,}/天"


def build_resume(
    worker: Worker, now: datetime | None = None
) -> dict:
    """Return ``{resume, platform_data}`` for one worker."""
    now = now or datetime.now(timezone.utc)
    rng = _rng(worker)
    category = _top_category(worker)
    profile = CATEGORY_PROFILES.get(
        category, CATEGORY_PROFILES["consulting_research"]
    )
    years = _years(worker, rng)
    rating = _rating(worker)
    on_time = _on_time_rate(worker)
    city = rng.choice(CITIES.get(worker.region, CITIES["CN"]))
    remaining_hours = max(
        0.0, worker.capacity_hours - worker.current_load_hours
    )

    summary = (
        f"{years} 年{CATEGORY_LABELS.get(category, category)}相关经验，"
        f"完成 {worker.completed} 个项目，客户评分 {rating}/5，"
        f"按时交付率 {on_time:.0%}。擅长"
        f"{profile['tags'][0]}、{profile['tags'][1]}，"
        "能独立负责从需求澄清到验收交付。"
    )

    resume = {
        "worker_id": worker.worker_id,
        "name": _name(rng),
        "headline": profile["headline"],
        "city": city,
        "region": REGION_LABELS.get(worker.region, worker.region),
        "years_experience": years,
        "education": _education(worker, profile, rng),
        "summary": summary,
        "availability": (
            f"本周可投入 {remaining_hours:.0f} 小时"
            + (" · 支持远程" if worker.remote_ok else " · 需线下协作")
        ),
        "expected_rate": _expected_rate(worker, rng),
        "stats": {
            "completed": worker.completed,
            "rating": rating,
            "on_time_rate": on_time,
            "rework_rate": (
                round(worker.rework_count / worker.completed, 3)
                if worker.completed
                else 0.0
            ),
        },
        "skills": _skill_tags(worker, category, profile),
        "work_experience": _work_experience(
            worker, profile, years, rng, now
        ),
        "projects": _projects(profile, rng),
        "certifications": list(profile["certifications"]),
    }

    platform_data = {
        "worker_id": worker.worker_id,
        "status": worker.status,
        "region": worker.region,
        "remote_ok": worker.remote_ok,
        "level": worker.level,
        "capacity_hours": worker.capacity_hours,
        "current_load_hours": worker.current_load_hours,
        "skills": dict(worker.skills),
        "skill_labels": {
            skill: SKILL_LABELS.get(skill, skill)
            for skill in worker.skills
        },
        "specialties": dict(worker.specialties),
        "preferred_categories": dict(worker.preferred_categories),
        "preferred_difficulty": list(worker.preferred_difficulty),
        "ratings": list(worker.ratings),
        "completed": worker.completed,
        "on_time": worker.on_time,
        "rework_count": worker.rework_count,
        "breach_dates": [
            value.isoformat() for value in worker.breach_dates
        ],
        "category_ratings": {
            category_name: round(statistics.mean(values), 2)
            for category_name, values in worker.category_ratings.items()
            if values
        },
    }
    return {"resume": resume, "platform_data": platform_data}
