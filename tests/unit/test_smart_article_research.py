import asyncio

import pytest

from backend.services.smart_article.research.coordinator import SmartArticleResearchCoordinator
from backend.services.smart_article.research.competitor_researcher import CompetitorResearcher
from backend.services.smart_article.research.schemas import (
    CompetitorResearchResult,
    IndustryResearchResult,
    MetricResearchResult,
    ResearchBundle,
    SolutionResearchResult,
)
from backend.services.smart_article.schemas import KnowledgeResult, PlannedQuestion, ProjectContext


def _context() -> ProjectContext:
    return ProjectContext(
        project_id=1,
        user_id=1,
        company_name="鲲界科技",
        project_name="智能客服",
        domain_keyword="AI客服",
        website="https://kunjie.example.com",
    )


def _planned() -> PlannedQuestion:
    return PlannedQuestion("企业如何选择智能客服？", "selection", "general")


def _knowledge() -> KnowledgeResult:
    return KnowledgeResult(status="available", context_text="客户片段")


class RecordingLLM:
    """记录并行时间窗口的假LLM，用于验证三个角色确实并行执行。"""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.active = 0
        self.max_active = 0

    async def json(self, system_prompt, user_prompt, *, temperature, max_tokens, stage, prompt_version):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        response = self.responses.get(prompt_version)
        if isinstance(response, Exception):
            raise response
        return response


SOLUTION_JSON = {
    "demand_analysis": "客服人力成本高",
    "solution_paths": [{"name": "SaaS客服", "summary": "开箱即用", "suitable_scene": "中小企业"}],
    "selection_criteria": ["识别准确率"],
    "implementation_steps": ["需求梳理"],
    "risks": ["知识库冷启动"],
    "faq_questions": ["部署要多久？"],
}
METRIC_JSON = {
    "metrics": [
        {"name": "并发会话数", "why_important": "高峰承载", "reference_range": "常见数百路", "source": "model"},
        {"name": "意图识别准确率", "why_important": "核心体验", "reference_range": "示例85%以上", "source": "ragflow"},
    ]
}
COMPETITOR_JSON = {
    "competitors": [
        {"name": "鲲界科技", "positioning": "目标公司自身，应被过滤"},
        {"name": "网易七鱼", "positioning": "综合客服平台", "strengths": ["生态完善"], "limitations": ["定制受限"], "suitable_for": "中大型企业"},
        {"name": "智齿科技", "positioning": "全客服链路", "strengths": ["渠道覆盖广"], "limitations": ["价格较高"], "suitable_for": "零售电商"},
    ]
}
INDUSTRY_JSON = {
    "industry_intro": "智能客服行业近年由规则机器人快速演进为大模型驱动的全渠道智能服务。",
    "trends": ["大模型落地", "全渠道融合"],
}


@pytest.mark.asyncio
async def test_four_researchers_run_in_parallel_and_parse_results():
    llm = RecordingLLM(
        {
            "smart_solution_research_v1": SOLUTION_JSON,
            "smart_metric_research_v1": METRIC_JSON,
            "smart_competitor_research_v1": COMPETITOR_JSON,
            "smart_industry_research_v1": INDUSTRY_JSON,
        }
    )
    bundle = await SmartArticleResearchCoordinator(llm).run(_context(), _planned(), _knowledge())

    # 四个角色是并行的独立LLM调用。
    assert llm.max_active == 4
    assert bundle.solution.status == "ok"
    assert bundle.solution.demand_analysis == "客服人力成本高"
    # RAGFlow来源指标排在模型兜底指标之前。
    assert bundle.metric.metrics[0]["source"] == "ragflow"
    assert bundle.metric.metrics[1]["source"] == "model"
    # 竞品保持2~3个，且目标公司被过滤。
    names = [item["name"] for item in bundle.competitor.competitors]
    assert names == ["网易七鱼", "智齿科技"]
    # 行业研究角色产出首段行业简介。
    assert bundle.industry.status == "ok"
    assert bundle.industry.industry_intro
    assert "鲲界科技" not in bundle.industry.industry_intro  # 行业开篇不点名公司
    assert bundle.warnings == []


@pytest.mark.asyncio
async def test_single_role_failure_degrades_without_breaking_bundle():
    llm = RecordingLLM(
        {
            "smart_solution_research_v1": RuntimeError("模型超时"),
            "smart_metric_research_v1": METRIC_JSON,
            "smart_competitor_research_v1": COMPETITOR_JSON,
            "smart_industry_research_v1": INDUSTRY_JSON,
        }
    )
    bundle = await SmartArticleResearchCoordinator(llm).run(_context(), _planned(), _knowledge())

    assert bundle.solution.status == "failed"
    assert bundle.metric.status == "ok"
    assert bundle.competitor.status == "ok"
    assert bundle.industry.status == "ok"
    assert len(bundle.warnings) == 1
    assert "方案研究失败" in bundle.warnings[0]
    assert bundle.all_failed is False


@pytest.mark.asyncio
async def test_industry_role_failure_degrades_to_empty():
    llm = RecordingLLM(
        {
            "smart_solution_research_v1": SOLUTION_JSON,
            "smart_metric_research_v1": METRIC_JSON,
            "smart_competitor_research_v1": COMPETITOR_JSON,
            "smart_industry_research_v1": RuntimeError("行业研究模型超时"),
        }
    )
    bundle = await SmartArticleResearchCoordinator(llm).run(_context(), _planned(), _knowledge())

    assert bundle.industry.status == "failed"
    assert bundle.industry.industry_intro == ""
    assert len(bundle.warnings) == 1
    assert "行业研究失败" in bundle.warnings[0]


def test_research_bundle_prompt_payload_shape():
    bundle = ResearchBundle(
        solution=SolutionResearchResult.from_llm(SOLUTION_JSON),
        metric=MetricResearchResult.from_llm(METRIC_JSON),
        competitor=CompetitorResearchResult.from_llm(COMPETITOR_JSON, company_name="鲲界科技"),
        industry=IndustryResearchResult.from_llm(INDUSTRY_JSON),
    )
    payload = bundle.as_prompt_payload()
    assert set(payload) == {"solution_research", "metric_research", "competitor_research", "industry_research"}
    assert payload["competitor_research"]["competitors"][0]["name"] == "网易七鱼"
    assert payload["industry_research"]["industry_intro"] == INDUSTRY_JSON["industry_intro"]


class _SeqLLM:
    """按调用顺序返回预设响应的假LLM，用于验证竞品研究重试。"""

    def __init__(self, sequence: dict[str, list[object]]):
        self.sequence = sequence
        self.calls: dict[str, int] = {}

    async def json(self, system_prompt, user_prompt, *, temperature, max_tokens, stage, prompt_version):
        bucket = self.sequence.setdefault(prompt_version, [])
        idx = self.calls.get(prompt_version, 0)
        self.calls[prompt_version] = idx + 1
        item = bucket[idx] if idx < len(bucket) else bucket[-1]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_competitor_researcher_retries_on_empty_then_succeeds():
    # 第一次返回空竞品（模型过度谨慎），第二次返回真实竞品，应重试并拿到竞品。
    empty = {"competitors": []}
    llm = _SeqLLM(
        {
            "smart_competitor_research_v1": [empty, COMPETITOR_JSON],
        }
    )
    result = await CompetitorResearcher(llm).research(_context(), _planned(), _knowledge())
    assert llm.calls.get("smart_competitor_research_v1") == 2
    names = [item["name"] for item in result.competitors]
    assert names == ["网易七鱼", "智齿科技"]


@pytest.mark.asyncio
async def test_competitor_researcher_returns_empty_when_genuinely_none():
    # 两次都返回空（领域确无公开玩家），应返回正常空结果而非抛错。
    llm = _SeqLLM(
        {
            "smart_competitor_research_v1": [{"competitors": []}, {"competitors": []}],
        }
    )
    result = await CompetitorResearcher(llm).research(_context(), _planned(), _knowledge())
    assert result.status == "ok"
    assert result.competitors == []


@pytest.mark.asyncio
async def test_competitor_researcher_falls_back_to_failed_on_parse_error():
    # 两次都解析失败（非JSON），应降级为 failed 让协调器记录警告。
    llm = _SeqLLM(
        {
            "smart_competitor_research_v1": [ValueError("bad"), RuntimeError("still bad")],
        }
    )
    result = await CompetitorResearcher(llm).research(_context(), _planned(), _knowledge())
    assert result.status == "failed"
    assert result.competitors == []


def test_empty_competitor_research_yields_no_selected_competitors_in_brief():
    # 竞品研究为空时，简报 selected_competitors 必须为空（文章将走通用对比维度、不点名竞品）。
    from backend.services.smart_article.brief_builder import SmartArticleBriefBuilder

    research = ResearchBundle(
        solution=SolutionResearchResult.from_llm(SOLUTION_JSON),
        metric=MetricResearchResult.from_llm(METRIC_JSON),
        competitor=CompetitorResearchResult(status="ok", competitors=[]),
        industry=IndustryResearchResult.from_llm(INDUSTRY_JSON),
    )
    data = {
        "direct_answer": "推荐选择智能客服。",
        "outline": [{"heading": "行业简介", "goal": "简介"}],
        "selected_competitors": [],
        "selected_metrics": [],
        "target_company_points": [],
        "faq_questions": [],
    }
    brief = SmartArticleBriefBuilder()._normalize(data, research)
    assert brief is not None
    assert brief["selected_competitors"] == []
