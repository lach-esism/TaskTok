"""Deterministic synthetic dataset for Phase 1.

The generator is intentionally simple and reproducible. It creates latent
worker reliability, task outcomes, breaches, and customer ratings so the
recommender and chain modules have realistic interaction history to score.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.data.latent import true_weight_simplex
from app.domain import Assignment, Customer, Dataset, Feedback, Task, Worker

CATEGORIES = [
    "software_dev",
    "ui_ux_design",
    "brand_design",
    "content_writing",
    "video_production",
    "marketing_campaign",
    "data_annotation",
    "translation_localization",
    "ecommerce_ops",
    "recruitment",
    "consulting_research",
    "training_course",
]

# Covers every skill used by the 12 chain templates, plus a few extras.
SKILLS = [
    "requirements",
    "architecture",
    "backend",
    "frontend",
    "qa",
    "devops",
    "ux",
    "ui",
    "research",
    "brand",
    "graphic_design",
    "writing",
    "editing",
    "publishing",
    "video",
    "shooting",
    "video_editing",
    "audio",
    "marketing",
    "creative",
    "analytics",
    "data_labeling",
    "qa_labeling",
    "translation",
    "localization",
    "ecommerce",
    "customer_service",
    "recruiting",
    "sourcing",
    "interviewing",
    "hr",
    "consulting",
    "analysis",
    "presentation",
    "training_design",
    "content_development",
    "security",
    "design",
    "operations",
    "legal",
]

REGIONS = ["CN", "US", "EU"]
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)

TASK_PROFILES = {
    "software_dev": {
        "titles": [
            "连锁咖啡品牌会员小程序开发",
            "制造业 ERP 库存模块升级",
            "跨境电商独立站支付接入",
            "社区团购订单履约系统开发",
            "医院预约挂号小程序开发",
            "物流企业司机端 App 改版",
            "连锁餐饮门店数据看板开发",
        ],
        "requirements": [
            "3 年以上相关开发经验，能独立完成模块设计与实现",
            "熟悉微信小程序或 Web 前后端开发，能完成联调",
            "有同类业务系统交付案例，可提供案例说明",
            "代码规范，能提供部署文档与上线支持",
            "可配合里程碑验收，沟通响应及时",
        ],
        "deliverables": ["需求确认清单", "可运行系统", "部署文档", "上线后 1 个月维护"],
        "context": "客户希望把线下流程搬到线上，要求按里程碑交付并配合验收。",
        "budget": (8000, 30000),
        "days": (14, 45),
    },
    "ui_ux_design": {
        "titles": [
            "SaaS 数据看板体验改版",
            "移动端保险投保流程重设计",
            "智能家居 App 交互优化",
            "B2B 采购平台信息架构梳理",
            "医疗预约小程序体验优化",
            "电商详情页转化率提升设计",
        ],
        "requirements": [
            "3 年以上 UI/UX 设计经验，有完整项目案例",
            "能独立完成用户研究、信息架构与原型",
            "熟练使用 Figma，能交付可点击原型",
            "有 B 端或移动端产品设计经验优先",
            "能配合开发走查并输出设计规范",
        ],
        "deliverables": ["用户研究摘要", "线框图", "高保真视觉稿", "可点击原型", "设计规范"],
        "context": "客户现有界面转化率偏低，需要重做关键流程并给出可落地的设计规范。",
        "budget": (5000, 20000),
        "days": (10, 30),
    },
    "brand_design": {
        "titles": [
            "新茶饮品牌 VI 与包装设计",
            "宠物食品品牌视觉升级",
            "区域连锁健身房品牌焕新",
            "农产品礼盒包装设计",
            "科技创业公司 Logo 与品牌手册",
            "咖啡烘焙品牌门店物料设计",
        ],
        "requirements": [
            "3 年以上品牌/平面设计经验，有完整 VI 案例",
            "能完成品牌定位、视觉概念与延展设计",
            "熟悉印刷工艺与包装落地要求",
            "能交付源文件与多尺寸资产",
            "可配合客户评审完成修改",
        ],
        "deliverables": ["品牌视觉概念", "Logo 与基础规范", "包装/物料设计稿", "源文件与切图"],
        "context": "客户准备进入新市场，希望建立统一、可延展的品牌视觉体系。",
        "budget": (3000, 15000),
        "days": (7, 21),
    },
    "content_writing": {
        "titles": [
            "工业机器人选型白皮书",
            "母婴品牌小红书种草文案",
            "SaaS 产品官网内容重构",
            "金融科技行业研究报告",
            "连锁餐饮品牌故事与官网文案",
            "医疗健康科普系列文章",
        ],
        "requirements": [
            "有 B2B 或行业内容写作经验，能提供作品",
            "能独立完成资料研究、提纲与成稿",
            "文字逻辑清晰，事实与引用可核查",
            "能配合编辑修改并按时交稿",
            "有相关行业背景优先",
        ],
        "deliverables": ["选题与提纲", "初稿", "编辑润色稿", "引用来源清单"],
        "context": "客户需要一套可用于官网、销售和投放的内容资产，强调专业性与可读性。",
        "budget": (1000, 8000),
        "days": (3, 10),
    },
    "video_production": {
        "titles": [
            "618 家电品牌 30 秒信息流短视频",
            "新能源汽车功能介绍视频",
            "连锁餐饮门店宣传片",
            "SaaS 产品演示视频",
            "美妆品牌达人种草视频",
            "文旅景区招商宣传片",
        ],
        "requirements": [
            "有商业短视频或宣传片制作经验",
            "能完成脚本、分镜、拍摄与剪辑全流程",
            "熟悉抖音/视频号等平台内容节奏",
            "能提供配音、字幕与封面版本",
            "可配合客户多轮修改",
        ],
        "deliverables": ["脚本与分镜", "拍摄素材", "成片", "字幕与封面版本"],
        "context": "客户需要一支可直接投放的短视频，突出核心卖点并适配竖屏平台。",
        "budget": (3000, 20000),
        "days": (7, 21),
    },
    "marketing_campaign": {
        "titles": [
            "商场周年庆整合营销活动",
            "新消费品牌新品上市 campaign",
            "区域银行信用卡拉新活动",
            "跨境电商黑五促销策划",
            "教育机构秋季招生推广",
            "B2B 制造业线上获客活动",
        ],
        "requirements": [
            "有整合营销或活动策划经验，能提供案例",
            "能完成策略、创意、渠道与预算规划",
            "熟悉线上投放与线下活动执行",
            "能跟踪核心指标并输出复盘",
            "有相关行业资源优先",
        ],
        "deliverables": ["活动策略", "创意与物料", "渠道排期", "执行方案", "复盘报告"],
        "context": "客户希望在限定预算内提升活动声量与转化，需要从策略到复盘的整体方案。",
        "budget": (5000, 30000),
        "days": (10, 30),
    },
    "data_annotation": {
        "titles": [
            "自动驾驶路侧 10 万帧图像标注",
            "电商商品图文分类标注",
            "医疗影像病灶区域标注",
            "语音客服对话转写与意图标注",
            "金融票据字段抽取标注",
            "短视频内容安全审核标注",
        ],
        "requirements": [
            "有对应类型数据标注经验，理解标注规范",
            "能按规范完成批量标注并保证一致率",
            "可配合质检与返修，接受抽检",
            "有隐私与数据安全意识",
            "能按周交付进度",
        ],
        "deliverables": ["标注规范确认", "批量标注结果", "质检报告", "返修记录"],
        "context": "客户需要按统一规范完成一批数据标注，质量一致率和交付周期是核心要求。",
        "budget": (2000, 12000),
        "days": (7, 30),
    },
    "translation_localization": {
        "titles": [
            "医疗器械说明书中英日本地化",
            "跨境电商商品详情多语言翻译",
            "SaaS 产品界面本地化",
            "法律合同英译中审校",
            "游戏剧情文本本地化",
            "制造业技术手册翻译",
        ],
        "requirements": [
            "目标语言母语级或同等水平，有翻译案例",
            "熟悉行业术语与本地表达习惯",
            "能完成翻译、审校与术语统一",
            "可配合格式与交付规范",
            "有相关行业背景优先",
        ],
        "deliverables": ["术语表", "翻译稿", "审校稿", "本地化终稿"],
        "context": "客户需要面向海外市场发布内容，要求术语准确、表达自然并符合当地合规要求。",
        "budget": (2000, 10000),
        "days": (5, 20),
    },
    "ecommerce_ops": {
        "titles": [
            "跨境电商独立站黑五运营",
            "天猫旗舰店日常运营托管",
            "抖音小店起盘与投流",
            "生鲜电商私域复购运营",
            "家居品牌京东店铺优化",
            "出海品牌 Amazon Listing 优化",
        ],
        "requirements": [
            "有对应平台店铺运营经验，能提供数据案例",
            "熟悉商品页、活动与投放的基本打法",
            "能独立完成数据跟踪与复盘",
            "对转化率、ROI 等指标负责",
            "可配合品牌方节奏执行",
        ],
        "deliverables": ["店铺诊断", "运营计划", "活动/投放执行", "数据复盘"],
        "context": "客户希望在关键销售节点提升店铺转化与复购，需要能落地执行的运营方案。",
        "budget": (4000, 20000),
        "days": (10, 30),
    },
    "recruitment": {
        "titles": [
            "新能源电池厂工艺工程师招聘",
            "连锁零售区域经理猎聘",
            "AI 创业公司算法工程师招聘",
            "医疗器械注册专员招聘",
            "跨境电商运营团队搭建",
            "制造业班组长批量招聘",
        ],
        "requirements": [
            "有对应行业招聘经验，熟悉人才画像",
            "能独立完成寻访、筛选与面试安排",
            "有稳定的候选人渠道与寻访能力",
            "能按周期反馈招聘进展",
            "了解相关岗位薪酬水平",
        ],
        "deliverables": ["岗位画像", "候选人名单", "面试安排", "Offer 跟进"],
        "context": "客户需要在一定周期内补齐关键岗位，重视到岗率与候选人质量。",
        "budget": (5000, 25000),
        "days": (20, 60),
    },
    "consulting_research": {
        "titles": [
            "县域文旅产业升级调研",
            "新能源产业链投资研究",
            "连锁餐饮选址与单店模型咨询",
            "SaaS 行业竞品分析",
            "制造业数字化转型诊断",
            "消费品牌用户画像研究",
        ],
        "requirements": [
            "有相关行业研究或咨询经验，能提供报告案例",
            "能独立完成访谈、数据收集与分析",
            "逻辑严谨，结论有证据支撑",
            "能输出可汇报的报告与建议",
            "有相关行业资源优先",
        ],
        "deliverables": ["研究框架", "访谈与数据", "分析报告", "汇报材料"],
        "context": "客户需要为重要决策提供外部视角，要求研究过程可追溯、结论可落地。",
        "budget": (8000, 40000),
        "days": (10, 40),
    },
    "training_course": {
        "titles": [
            "新员工信息安全意识培训",
            "连锁门店店长管理能力训练营",
            "制造业班组长精益生产培训",
            "SaaS 客户成功团队培训",
            "跨境电商运营实战课程",
            "医疗行业合规培训",
        ],
        "requirements": [
            "有企业培训或课程开发经验，能提供课程案例",
            "能完成需求分析、课程设计与课件开发",
            "具备现场或线上授课能力",
            "能设计练习、考试与效果评估",
            "有相关行业经验优先",
        ],
        "deliverables": ["课程大纲", "讲师手册", "课件与练习", "考试/评估方案"],
        "context": "客户希望提升团队在特定主题上的实操能力，需要可复用、可评估的课程包。",
        "budget": (5000, 25000),
        "days": (10, 30),
    },
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


REGION_LABELS = {"CN": "中国大陆", "US": "美国", "EU": "欧洲"}

TITLE_VARIANTS = ["", "", "", "", "（一期）", "（二期）", "（加急）", "（年度框架）"]


def _realistic_task_fields(
    profile: dict, rng: random.Random, region: str, remote_ok: bool
) -> dict:
    """Build a posting that reads like a real client brief, not test data."""
    base_min, base_max = profile["budget"]
    scale = rng.uniform(0.85, 1.2)
    budget_min = float(round(base_min * scale / 100) * 100)
    budget_max = float(round(base_max * scale / 100) * 100)
    days = rng.randint(*profile["days"])
    deliverables = profile["deliverables"]
    mode = (
        "支持远程协作，按周同步进度"
        if remote_ok
        else f"需要与{REGION_LABELS.get(region, region)}团队线下协作"
    )
    title = rng.choice(profile["titles"]) + rng.choice(TITLE_VARIANTS)
    description = "。".join(
        [
            profile["context"].rstrip("。；;"),
            f"服务报酬 {budget_min:,.0f}–{budget_max:,.0f} 元，期望 {days} 天内交付",
            f"主要交付物包括{'、'.join(deliverables)}",
            mode,
        ]
    ) + "。"
    requirements = rng.sample(
        profile["requirements"],
        k=rng.randint(3, min(4, len(profile["requirements"]))),
    )
    requirements.append(f"交付周期 {days} 天，需按里程碑同步进度")
    return {
        "title": title,
        "description": description,
        "requirements": requirements,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "budget": round((budget_min + budget_max) / 2, 2),
        "days": days,
    }


def generate_dataset(
    n_workers: int = 100,
    n_tasks: int = 500,
    n_assignments: int = 3000,
    seed: int = 42,
    n_new_users: int = 200,
    with_ground_truth: bool = True,
) -> Dataset:
    """Generate a reproducible dataset with a temporal 80/20 split."""
    rng = random.Random(seed)

    n_customers = max(10, n_workers // 2)
    customers = [
        Customer(
            customer_id=f"c{i + 1:04d}",
            name=f"Customer {i + 1}",
            region=rng.choice(REGIONS),
            preference_weights={
                "reputation": 0.5,
                "expertise": 0.3,
                "load": 0.2,
            },
        )
        for i in range(n_customers)
    ]
    customer_leniency = {
        customer.customer_id: rng.uniform(-0.25, 0.25) for customer in customers
    }

    workers: list[Worker] = []
    reliability: dict[str, float] = {}
    for i in range(n_workers):
        worker_id = f"w{i + 1:04d}"
        chosen_skills = rng.sample(SKILLS, k=rng.randint(10, 18))
        skills = {skill: rng.randint(1, 5) for skill in chosen_skills}
        chosen_specialties = rng.sample(CATEGORIES, k=rng.randint(1, 3))
        specialties = {
            category: rng.randint(1, 5) for category in chosen_specialties
        }
        low = rng.randint(1, 4)
        high = rng.randint(low + 1, 5)
        worker = Worker(
            worker_id=worker_id,
            name=f"Worker {i + 1}",
            skills=skills,
            specialties=specialties,
            level=rng.randint(1, 5),
            capacity_hours=rng.randint(30, 50),
            current_load_hours=rng.randint(0, 15),
            preferred_categories={
                category: round(rng.uniform(0.3, 0.9), 2)
                for category in chosen_specialties
            },
            preferred_difficulty=(low, high),
            region=rng.choice(REGIONS),
            remote_ok=rng.random() < 0.6,
        )
        workers.append(worker)
        reliability[worker_id] = rng.uniform(0.4, 1.0)

    tasks: list[Task] = []
    task_seed_worker: dict[str, str] = {}
    for i in range(n_tasks):
        task_id = f"t{i + 1:04d}"
        task_hours = round(rng.uniform(2, 24), 1)
        feasible = [
            w
            for w in workers
            if w.capacity_hours - w.current_load_hours >= task_hours
        ]
        if not feasible:
            task_hours = max(
                2.0,
                min(w.capacity_hours - w.current_load_hours for w in workers),
            )
            feasible = [
                w
                for w in workers
                if w.capacity_hours - w.current_load_hours >= task_hours
            ]
        seed_worker = rng.choice(feasible) if feasible else rng.choice(workers)
        task_seed_worker[task_id] = seed_worker.worker_id

        skill_keys = rng.sample(
            list(seed_worker.skills),
            k=rng.randint(1, min(2, len(seed_worker.skills))),
        )
        required_skills = {
            skill: max(
                1,
                min(
                    seed_worker.skills[skill],
                    rng.randint(1, 3),
                ),
            )
            for skill in skill_keys
        }
        category = (
            rng.choice(list(seed_worker.specialties))
            if seed_worker.specialties and rng.random() < 0.7
            else rng.choice(CATEGORIES)
        )
        created_at = BASE_TIME + timedelta(
            days=rng.randint(0, 300), hours=rng.randint(0, 23)
        )
        profile = TASK_PROFILES[category]
        posting = _realistic_task_fields(
            profile, rng, seed_worker.region, seed_worker.remote_ok
        )
        tasks.append(
            Task(
                task_id=task_id,
                customer_id=rng.choice(customers).customer_id,
                title=posting["title"],
                description=posting["description"],
                category=category,
                required_skills=required_skills,
                required_level=min(seed_worker.level, rng.randint(1, 2)),
                difficulty=rng.randint(1, 5),
                priority=rng.randint(1, 5),
                estimated_hours=task_hours,
                deadline=created_at + timedelta(days=posting["days"]),
                region=seed_worker.region,
                remote_ok=seed_worker.remote_ok,
                budget=posting["budget"],
                requirements=posting["requirements"],
                budget_min=posting["budget_min"],
                budget_max=posting["budget_max"],
                created_at=created_at,
            )
        )

    assignments: list[Assignment] = []
    feedback: list[Feedback] = []
    attempts = 0
    max_attempts = n_assignments * 30
    while len(assignments) < n_assignments and attempts < max_attempts:
        attempts += 1
        task = rng.choice(tasks)
        assignment_time = task.created_at + timedelta(
            days=rng.randint(0, 10), hours=rng.randint(0, 23)
        )
        candidates = [
            worker
            for worker in workers
            if worker.status == "active"
            and worker.level >= task.required_level
            and all(
                worker.skills.get(skill, 0) >= minimum
                for skill, minimum in task.required_skills.items()
            )
            and worker.current_load_hours + task.estimated_hours
            <= worker.capacity_hours
        ]
        if not candidates:
            seed_worker_id = task_seed_worker[task.task_id]
            candidates = [w for w in workers if w.worker_id == seed_worker_id]
        if not candidates:
            continue

        def weight(worker: Worker) -> float:
            skill_match = sum(
                min(
                    worker.skills.get(skill, 0) / max(minimum, 1),
                    1.0,
                )
                for skill, minimum in task.required_skills.items()
            ) / max(1, len(task.required_skills))
            specialty = worker.specialties.get(task.category, 0) / 5.0
            load_ratio = _clamp(
                (worker.current_load_hours + task.estimated_hours)
                / worker.capacity_hours,
                0.0,
                1.0,
            )
            return (
                0.4 * skill_match
                + 0.3 * specialty
                + 0.2 * (1.0 - load_ratio)
                + 0.1 * reliability[worker.worker_id]
                + 0.01
            )

        worker = rng.choices(candidates, weights=[weight(w) for w in candidates], k=1)[0]
        skill_match = sum(
            min(worker.skills.get(skill, 0) / max(minimum, 1), 1.0)
            for skill, minimum in task.required_skills.items()
        ) / max(1, len(task.required_skills))
        load_ratio = _clamp(
            (worker.current_load_hours + task.estimated_hours)
            / worker.capacity_hours,
            0.0,
            1.0,
        )
        rel = reliability[worker.worker_id]

        on_time_probability = _clamp(
            0.55 + 0.35 * skill_match + 0.15 * rel - 0.25 * load_ratio,
            0.05,
            0.98,
        )
        on_time = rng.random() < on_time_probability
        breach_probability = _clamp(
            0.03 + 0.15 * (1.0 - rel) - 0.08 * skill_match,
            0.005,
            0.30,
        )
        breach = rng.random() < breach_probability
        breach_type: str | None = None
        if breach:
            breach_type = rng.choice(
                ["late", "cancel_after_accept", "acceptance_failed"]
            )
            if breach_type == "late":
                on_time = False

        quality = _clamp(
            0.5 * skill_match
            + 0.3 * rel
            + 0.2 * (1.0 if on_time else 0.0)
            + rng.uniform(-0.1, 0.1),
            0.0,
            1.0,
        )
        rework_count = 1 if quality < 0.45 and rng.random() < 0.5 else 0
        status = "failed" if breach else "completed"
        assignment = Assignment(
            assignment_id=f"a{len(assignments) + 1:06d}",
            task_id=task.task_id,
            worker_id=worker.worker_id,
            customer_id=task.customer_id,
            status=status,
            on_time=on_time,
            rework_count=rework_count,
            breach_type=breach_type,
            created_at=assignment_time,
        )
        assignments.append(assignment)

        if status == "completed":
            worker.completed += 1
            if on_time:
                worker.on_time += 1
            worker.rework_count += rework_count
            if rng.random() < 0.7:
                leniency = customer_leniency[task.customer_id]
                rating = int(
                    round(
                        _clamp(
                            1.0
                            + 4.0 * quality
                            + leniency
                            + rng.uniform(-0.3, 0.3),
                            1.0,
                            5.0,
                        )
                    )
                )
                feedback.append(
                    Feedback(
                        feedback_id=f"f{len(feedback) + 1:06d}",
                        assignment_id=assignment.assignment_id,
                        worker_id=worker.worker_id,
                        task_id=task.task_id,
                        overall_rating=rating,
                        created_at=assignment_time,
                    )
                )
                worker.ratings.append(float(rating))
        if breach:
            worker.breach_dates.append(assignment_time)

    assignments.sort(key=lambda a: a.created_at)
    split_index = int(len(assignments) * 0.8)
    train = assignments[:split_index]
    test = assignments[split_index:]

    # Worker aggregates must reflect train-period outcomes only, otherwise
    # offline evaluation leaks test feedback into reputation features.
    worker_by_id = {worker.worker_id: worker for worker in workers}
    for worker in workers:
        worker.ratings = []
        worker.completed = 0
        worker.on_time = 0
        worker.rework_count = 0
        worker.breach_dates = []
        worker.category_ratings = {}
    train_assignment_ids = {
        assignment.assignment_id for assignment in train
    }
    task_by_id = {task.task_id: task for task in tasks}
    for assignment in train:
        worker = worker_by_id[assignment.worker_id]
        if assignment.status == "completed":
            worker.completed += 1
            if assignment.on_time:
                worker.on_time += 1
            worker.rework_count += assignment.rework_count
        if assignment.breach_type:
            worker.breach_dates.append(assignment.created_at)
    for item in feedback:
        if item.assignment_id in train_assignment_ids:
            worker = worker_by_id[item.worker_id]
            worker.ratings.append(float(item.overall_rating))
            task = task_by_id.get(item.task_id)
            if task is not None:
                worker.category_ratings.setdefault(
                    task.category, []
                ).append(float(item.overall_rating))

    true_weights: dict[str, dict[str, float]] = {}
    if with_ground_truth:
        true_rng = random.Random(seed + 1)
        true_weights = {
            worker.worker_id: true_weight_simplex(true_rng)
            for worker in workers
        }
        true_weights.update(
            {
                customer.customer_id: true_weight_simplex(true_rng)
                for customer in customers
            }
        )

    new_users: list[Worker] = []
    if n_new_users > 0:
        new_rng = random.Random(seed + 2)
        for index in range(n_new_users):
            worker_id = f"wu{index + 1:04d}"
            latent = true_weight_simplex(true_rng)
            max_weight = max(latent.values()) or 1.0
            skill_rel = latent["skill"] / max_weight
            expertise_rel = latent["expertise"] / max_weight
            preference_rel = latent["preference"] / max_weight
            reputation_rel = latent["reputation"] / max_weight

            skill_count = min(
                len(SKILLS), 8 + int(10 * skill_rel)
            )
            specialty_count = min(
                len(CATEGORIES), 1 + int(2 * expertise_rel)
            )
            level = 1 + int(4 * reputation_rel)
            preference_strength = round(
                0.3 + 0.6 * min(1.0, preference_rel), 2
            )

            chosen_skills = new_rng.sample(SKILLS, k=skill_count)
            skills = {
                skill: new_rng.randint(1, 5) for skill in chosen_skills
            }
            chosen_specialties = new_rng.sample(
                CATEGORIES, k=specialty_count
            )
            specialties = {
                category: new_rng.randint(1, 5)
                for category in chosen_specialties
            }
            low = new_rng.randint(1, 4)
            high = new_rng.randint(low + 1, 5)
            worker = Worker(
                worker_id=worker_id,
                name=f"New User {index + 1}",
                skills=skills,
                specialties=specialties,
                level=level,
                capacity_hours=new_rng.randint(30, 50),
                current_load_hours=0,
                preferred_categories={
                    category: preference_strength
                    for category in chosen_specialties
                },
                preferred_difficulty=(low, high),
                region=new_rng.choice(REGIONS),
                remote_ok=new_rng.random() < 0.6,
            )
            new_users.append(worker)
            if with_ground_truth:
                true_weights[worker_id] = latent

    return Dataset(
        workers=workers,
        customers=customers,
        tasks=tasks,
        assignments=assignments,
        feedback=feedback,
        train=train,
        test=test,
        true_weights=true_weights,
        new_users=new_users,
    )
