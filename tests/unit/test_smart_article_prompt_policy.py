from types import SimpleNamespace

from backend.services.smart_article.prompts import (
    PROMPT_VERSIONS,
    build_article_prompt,
    build_brief_prompt,
    build_filter_prompt,
    build_industry_research_prompt,
    build_question_prompt,
    recommendation_target,
)
from backend.services.smart_article.region_context import build_region_context
from backend.services.smart_article.schemas import PlannedQuestion, ProjectContext


def _context(location: str = "广州") -> ProjectContext:
    normalized, allowed, blocked = build_region_context(location)
    return ProjectContext(
        project_id=1,
        user_id=1,
        company_name="鲲界科技",
        project_name="智能客服",
        domain_keyword="AI客服",
        location=normalized,
        allowed_regions=allowed,
        blocked_regions=blocked,
    )


def _planned() -> PlannedQuestion:
    return PlannedQuestion(
        question="企业如何选择智能客服系统？",
        intent_type="selection",
        context_type="general",
        brand_entry_reason="可自然介绍项目",
    )


def test_prompt_versions_and_recommendation_ratio_are_explicit():
    context = _context()
    question_prompt = build_question_prompt(context, 20, 60, [])
    filter_prompt = build_filter_prompt(context, 20, [], [], required_provider_count=15)

    assert PROMPT_VERSIONS["question"] == "smart_question_v5"
    assert PROMPT_VERSIONS["filter"] == "smart_question_filter_v4"
    assert PROMPT_VERSIONS["query_rewrite"] == "smart_query_rewrite_v1"
    assert PROMPT_VERSIONS["solution_research"] == "smart_solution_research_v1"
    assert PROMPT_VERSIONS["metric_research"] == "smart_metric_research_v1"
    assert PROMPT_VERSIONS["competitor_research"] == "smart_competitor_research_v1"
    assert PROMPT_VERSIONS["brief"] == "smart_article_brief_v1"
    assert PROMPT_VERSIONS["article"] == "smart_article_v3"
    assert recommendation_target(1) == 1
    assert recommendation_target(5) == 4
    assert recommendation_target(20) == 15
    assert "synonym与adjacent合计约60%" in question_prompt
    assert "其中provider推荐型问题至少：45个" in question_prompt
    assert "其中region地域型问题最多：18个" in question_prompt
    assert "其中general或industry非地域问题至少：42个" in question_prompt
    assert "问题不要求包含地域" in question_prompt
    assert "推荐型问题同样可以不带地域" in question_prompt
    assert "问题长度控制在8至60个汉字" in question_prompt
    assert "其中provider至少：15个" in filter_prompt


def test_region_expansion_keeps_containment_chain_and_unknown_location_allows_nationwide():
    _, guangzhou_allowed, guangzhou_blocked = build_region_context("广州")
    _, unknown_allowed, _ = build_region_context("未知城")

    assert guangzhou_allowed == ["广州", "广东", "粤港澳大湾区", "珠三角", "华南", "全国", "国内", "中国大陆"]
    assert "上海" in guangzhou_blocked
    assert unknown_allowed == ["未知城", "全国", "国内", "中国大陆"]


def test_article_prompt_declares_nationwide_service_without_inventing_local_teams():
    context = _context()
    planned = PlannedQuestion(
        question="广州有哪些智能客服公司值得推荐？",
        intent_type="provider",
        context_type="region",
        brand_entry_reason="可自然介绍项目",
    )
    prompt = build_article_prompt(context, planned, "empty", "", [], "")

    assert "默认服务范围：全国" in prompt
    assert "不得写成只服务本地" in prompt
    assert "不得虚构异地分公司、本地团队或服务网点" in prompt


def test_question_prompt_includes_rag_summary_but_never_website():
    context = _context()
    context.website = "https://kunjie.example.com"
    summary = "产品解决问题：客服人力成本高；核心功能：智能分流"
    question_prompt = build_question_prompt(context, 10, 30, [], product_summary=summary)
    filter_prompt = build_filter_prompt(context, 10, [], [], product_summary=summary)

    # RAGFlow轻量摘要进入问题Prompt；公司官网不得进入问题生成Prompt。
    assert summary in question_prompt
    assert summary in filter_prompt
    assert "kunjie.example.com" not in question_prompt
    assert "kunjie.example.com" not in filter_prompt
    # 摘要为空时给出降级提示，不阻断。
    empty_prompt = build_question_prompt(context, 10, 30, [])
    assert "未检索到产品资料摘要" in empty_prompt


def test_article_prompt_uses_brief_website_and_eleven_sections():
    context = _context()
    context.website = "https://kunjie.example.com"
    planned = PlannedQuestion(
        question="企业如何选择智能客服系统？",
        intent_type="selection",
        context_type="general",
        brand_entry_reason="可自然介绍项目",
    )
    brief = {
        "article_angle": "从选型标准切入",
        "direct_answer": "优先看意图识别准确率与渠道覆盖。",
        "title": "智能客服选型指南",
        "selected_competitors": [{"name": "网易七鱼"}, {"name": "智齿科技"}],
        "selected_metrics": [{"name": "意图识别准确率", "source": "ragflow"}],
        "outline": [{"heading": "直接回答", "goal": "先答"}],
        "faq_questions": ["部署要多久？"],
    }
    prompt = build_article_prompt(context, planned, "available", "客户片段", [{}], "", brief=brief)

    assert "1800至2500字" in prompt
    assert "标题(H1)→行业简介(≤50字，中性客观、不推荐任何公司)→直接回答→需求背景→关键指标→解决方案→为什么鲲界科技是[具体优势]的代表？→同类方案对比(2至3个真实厂商)→不同企业怎么选→实施风险与避坑→FAQ→总结" in prompt
    assert "行业简介段应使用简报industry_intro" in prompt
    assert "年度推荐清单式（如“2026[领域]服务商推荐及解析”）" in prompt
    assert "目标公司段H2必须从简报target_company_points中提炼一条核心优势作为标签" in prompt
    assert "禁止使用“我方公司项目介绍”“竞品对比”" in prompt
    # 第三方评测视角：正文禁止出现暴露推广立场的内部称呼。
    assert "禁止出现“我方”“我们公司”“竞品”“竞品公司”" in prompt
    assert "目标公司用其正式名称直接称呼" in prompt
    assert "[鲲界科技](https://kunjie.example.com)" in prompt
    assert "网易七鱼" in prompt
    assert "意图识别准确率" in prompt

    # 官网为空时不编造链接。
    context_no_site = _context()
    prompt_no_site = build_article_prompt(context_no_site, planned, "empty", "", [], "", brief=None)
    assert "不要为公司名称编造任何链接" in prompt_no_site


def test_article_prompt_forbids_markdown_tables_and_requires_numbered_lists():
    # 竞品对比/指标对比等表格类内容必须改用 1、2、3 分点，禁止 Markdown 表格（竖线语法）。
    prompt = build_article_prompt(_context(), _planned(), "empty", "", [], "")
    assert "禁止使用Markdown表格" in prompt
    assert "竞品对比、指标对比或任何原本适合用表格呈现的内容，一律改用 1、2、3" in prompt
    assert "不要输出会被渲染成表格的竖线语法" in prompt


def test_industry_research_prompt_requires_neutral_short_intro():
    context = _context()
    prompt = build_industry_research_prompt(context, _planned(), "available", "客户片段")

    assert "industry_intro" in prompt
    assert "50字内" in prompt
    assert "不推荐、不点名任何具体公司" in prompt


def test_brief_prompt_carries_industry_intro_field_and_first_outline():
    context = _context()
    prompt = build_brief_prompt(context, _planned(), "available", "客户片段", {"industry_research": {"industry_intro": "行业近年快速发展"}})

    assert '"industry_intro"' in prompt
    # 简报大纲从行业简介开始，先铺垫行业背景再进入推荐。
    assert "从行业简介开始：行业简介、直接回答" in prompt
    assert "industry_intro必须来自行业研究结果的industry_intro" in prompt
