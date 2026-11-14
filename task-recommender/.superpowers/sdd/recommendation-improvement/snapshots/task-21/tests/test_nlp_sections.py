from datetime import datetime, timezone

from app.nlp.sections import crf_available, parse_resume_sections

REFERENCE_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)

SAMPLE = """5 年软件开发相关经验，能独立负责项目交付。

教育经历
2012 – 2016 复旦大学 计算机科学与技术 学士

工作经历
2019 – 至今 云启科技 高级全栈工程师
2016 – 2019 数联软件 后端工程师

项目经历
连锁零售会员小程序 核心开发
制造业 ERP 库存升级 后端负责人

技能
后端开发
前端开发 3 年
数据分析 2 年

证书与认证
AWS Certified Developer
PMP

语言
中文
英文
"""


def test_parse_resume_sections_education():
    sections = parse_resume_sections(SAMPLE, now=REFERENCE_NOW)
    education = sections["education"]
    assert education
    entry = education[0]
    assert entry["school"] == "复旦大学"
    assert entry["degree"] == "学士"
    assert "计算机" in entry["major"]
    assert entry["dates"]


def test_parse_resume_sections_work():
    sections = parse_resume_sections(SAMPLE, now=REFERENCE_NOW)
    work = sections["work"]
    assert len(work) == 2
    first = work[0]
    assert first["company"] == "云启科技"
    assert "工程师" in first["title"]
    assert first["dates"]
    assert first["years"] is not None


def test_parse_resume_sections_projects():
    sections = parse_resume_sections(SAMPLE, now=REFERENCE_NOW)
    projects = sections["projects"]
    assert len(projects) == 2
    assert "小程序" in projects[0]["name"]
    assert projects[1]["role"] == "后端负责人"


def test_parse_resume_sections_skills_with_category():
    sections = parse_resume_sections(SAMPLE, now=REFERENCE_NOW)
    skills = sections["skills"]
    categories = [entry.get("category") for entry in skills]
    assert "backend" in categories
    assert "frontend" in categories
    assert "analytics" in categories
    frontend = next(entry for entry in skills if entry["category"] == "frontend")
    assert frontend["years"] == 3.0


def test_parse_resume_sections_certificates_and_languages():
    sections = parse_resume_sections(SAMPLE, now=REFERENCE_NOW)
    assert "AWS Certified Developer" in sections["certificates"]
    assert "中文" in sections["languages"]
    assert "英文" in sections["languages"]


def test_parse_resume_sections_experience_years():
    sections = parse_resume_sections(SAMPLE, now=REFERENCE_NOW)
    assert sections["experience_years"] == 5.0


def test_parse_resume_sections_empty_input():
    sections = parse_resume_sections("", now=REFERENCE_NOW)
    assert sections["work"] == []
    assert sections["education"] == []
    assert sections["experience_years"] is None


def test_crf_optional_flag_is_boolean():
    assert isinstance(crf_available(), bool)
