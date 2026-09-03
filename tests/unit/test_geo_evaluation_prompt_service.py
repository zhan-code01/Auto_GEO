# -*- coding: utf-8 -*-

from backend.services.geo_evaluation_prompt_service import (
    DEFAULT_DISTRIBUTION,
    DEFAULT_PROJECT_TERM_QUESTION_COUNT,
    GeoEvaluationPromptService,
)


def test_default_distribution_prioritizes_company_related_questions():
    assert DEFAULT_DISTRIBUTION == {
        "recommendation": 60,
        "scenario": 15,
        "comparison": 15,
        "business_understanding": 0,
        "brand_awareness": 5,
        "reputation": 5,
    }


def test_project_terms_cover_most_neutral_questions():
    assert DEFAULT_PROJECT_TERM_QUESTION_COUNT == 75


def test_blank_industry_uses_project_terms_instead_of_local_life_fallback():
    service = GeoEvaluationPromptService(db=None)

    questions = service._generate_questions(
        company_name="广东百盛千鲜食品有限公司",
        industry="",
        distribution=DEFAULT_DISTRIBUTION,
        competitors=[],
        project_terms=["鲜食食品", "鹅肝供应商", "法肝供应", "高品质法肝"],
    )

    text = "\n".join(item["question"] for item in questions)
    neutral_questions = [
        item
        for item in questions
        if item["question_type"] in {"recommendation", "scenario", "comparison", "business_understanding"}
    ]
    related_questions = [
        item
        for item in neutral_questions
        if item.get("related_project_name")
        or any(term in item["question"] for term in ["鲜食食品", "鹅肝供应商", "法肝供应", "高品质法肝"])
    ]

    assert "本地生活服务" not in text
    assert len(related_questions) >= 75


def test_default_distribution_generates_six_question_types():
    service = GeoEvaluationPromptService(db=None)

    questions = service._generate_questions(
        company_name="广东百盛千鲜食品有限公司",
        industry="食品供应链",
        distribution=DEFAULT_DISTRIBUTION,
        competitors=[],
        project_terms=["鹅肝供应商", "法肝供应", "鲜食食品"],
    )

    counts = {}
    for item in questions:
        counts[item["question_type"]] = counts.get(item["question_type"], 0) + 1

    assert counts == {key: value for key, value in DEFAULT_DISTRIBUTION.items() if value > 0}
    assert all("广东百盛千鲜食品有限公司" not in item["question"] for item in questions[:75])


def test_default_questions_avoid_pure_knowledge_prompts():
    service = GeoEvaluationPromptService(db=None)

    questions = service._generate_questions(
        company_name="广东百盛千鲜食品有限公司",
        industry="食品供应链",
        distribution=DEFAULT_DISTRIBUTION,
        competitors=[],
        project_terms=["鹅肝供应商", "法肝供应", "鲜食食品"],
    )

    text = "\n".join(item["question"] for item in questions)
    assert "如何判断其品质稳定性" not in text
    assert "品质稳定性怎么评估" not in text
    assert all(
        any(
            token in item["question"]
            for token in ["公司", "服务商", "供应商", "品牌", "企业", "推荐", "哪家", "合作", "采购", "选择", "对比", "口碑"]
        )
        for item in questions
        if item["question_type"] in {"recommendation", "scenario", "comparison", "business_understanding"}
    )


def test_resolve_industry_label_prefers_project_terms_when_industry_missing():
    service = GeoEvaluationPromptService(db=None)

    assert service._resolve_industry_label("", ["鲜食食品", "鹅肝供应商"]) == "鲜食食品"
    assert service._resolve_industry_label("本地生活服务", ["法肝供应"]) == "法肝供应"
    assert service._resolve_industry_label("食品供应链", ["法肝供应"]) == "食品供应链"


def test_comparison_questions_without_competitors_do_not_use_fake_placeholders():
    service = GeoEvaluationPromptService(db=None)

    questions = service._generate_questions(
        company_name="鲲界科技有限公司",
        industry="互联网",
        distribution={"recommendation": 0, "comparison": 2, "scenario": 0, "reputation": 0, "brand_awareness": 0},
        competitors=[],
        project_terms=[],
    )

    assert len(questions) == 2
    assert all(item["question_type"] == "comparison" for item in questions)
    assert all("竞品" not in item["question"] for item in questions)
    assert all("鲲界科技有限公司" not in item["question"] for item in questions)
    assert all(item["competitor_names"] == [] for item in questions)


def test_comparison_questions_ignore_competitors_for_now():
    service = GeoEvaluationPromptService(db=None)

    questions = service._generate_questions(
        company_name="鲲界科技有限公司",
        industry="互联网",
        distribution={"recommendation": 0, "comparison": 1, "scenario": 0, "reputation": 0, "brand_awareness": 0},
        competitors=["星河科技"],
        project_terms=[],
    )

    assert len(questions) == 1
    assert questions[0]["question_type"] == "comparison"
    assert questions[0]["competitor_names"] == ["星河科技"]


def test_location_expands_to_controlled_region_pool():
    service = GeoEvaluationPromptService(db=None)

    profile = service._build_region_profile("广州")

    assert profile["allowed_regions"] == ["广州", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"]
    assert "长三角" in profile["blocked_regions"]
    assert "北京" in profile["blocked_regions"]


def test_region_mapping_covers_all_mainland_provincial_capitals():
    service = GeoEvaluationPromptService(db=None)
    capital_cases = {
        "北京": ["北京", "京津冀", "华北", "全国"],
        "天津": ["天津", "京津冀", "华北", "全国"],
        "上海": ["上海", "长三角", "华东", "全国"],
        "重庆": ["重庆", "成渝", "西南", "全国"],
        "石家庄": ["石家庄", "河北", "京津冀", "华北", "全国"],
        "太原": ["太原", "山西", "华北", "全国"],
        "呼和浩特": ["呼和浩特", "内蒙古", "华北", "全国"],
        "沈阳": ["沈阳", "辽宁", "东北", "全国"],
        "长春": ["长春", "吉林", "东北", "全国"],
        "哈尔滨": ["哈尔滨", "黑龙江", "东北", "全国"],
        "南京": ["南京", "江苏", "长三角", "华东", "全国"],
        "杭州": ["杭州", "浙江", "长三角", "华东", "全国"],
        "合肥": ["合肥", "安徽", "长三角", "华东", "全国"],
        "福州": ["福州", "福建", "海峡西岸", "华东", "全国"],
        "南昌": ["南昌", "江西", "华东", "全国"],
        "济南": ["济南", "山东", "华东", "全国"],
        "郑州": ["郑州", "河南", "中原", "华中", "全国"],
        "武汉": ["武汉", "湖北", "长江中游", "华中", "全国"],
        "长沙": ["长沙", "湖南", "长江中游", "华中", "全国"],
        "广州": ["广州", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"],
        "南宁": ["南宁", "广西", "华南", "全国"],
        "海口": ["海口", "海南", "华南", "全国"],
        "成都": ["成都", "四川", "成渝", "西南", "全国"],
        "贵阳": ["贵阳", "贵州", "西南", "全国"],
        "昆明": ["昆明", "云南", "西南", "全国"],
        "拉萨": ["拉萨", "西藏", "西南", "全国"],
        "西安": ["西安", "陕西", "关中平原", "西北", "全国"],
        "兰州": ["兰州", "甘肃", "西北", "全国"],
        "西宁": ["西宁", "青海", "西北", "全国"],
        "银川": ["银川", "宁夏", "西北", "全国"],
        "乌鲁木齐": ["乌鲁木齐", "新疆", "西北", "全国"],
    }

    for location, expected_regions in capital_cases.items():
        assert service._build_region_profile(location)["allowed_regions"] == expected_regions


def test_region_mapping_handles_province_suffix_and_unknown_city():
    service = GeoEvaluationPromptService(db=None)

    assert service._build_region_profile("广东省")["allowed_regions"] == [
        "广东",
        "粤港澳大湾区",
        "珠三角",
        "华南",
        "全国",
    ]
    assert service._build_region_profile("天津市滨海新区")["allowed_regions"] == ["天津", "京津冀", "华北", "全国"]
    assert service._build_region_profile("未知城")["allowed_regions"] == ["未知城", "全国"]


def test_generated_questions_do_not_use_blocked_regions_for_guangzhou():
    service = GeoEvaluationPromptService(db=None)
    profile = service._build_region_profile("广州")

    questions = service._generate_questions(
        company_name="广州测试科技有限公司",
        industry="GEO优化",
        distribution={"recommendation": 20, "comparison": 10, "scenario": 10, "reputation": 0, "brand_awareness": 0},
        competitors=[],
        project_terms=["AI搜索可见度监控", "内容发布自动化"],
        region_profile=profile,
    )

    text = "\n".join(item["question"] for item in questions)
    assert "长三角" not in text
    assert "北京" not in text
    assert "上海" not in text
    assert any(region in text for region in ["广州", "广东", "粤港澳大湾区", "珠三角", "华南", "全国"])
