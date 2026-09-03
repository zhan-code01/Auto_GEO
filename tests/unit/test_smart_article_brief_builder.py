import pytest

from backend.services.smart_article.brief_builder import DEFAULT_OUTLINE, SmartArticleBriefBuilder
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
        project_description="面向中小企业的智能客服系统",
    )


def _planned() -> PlannedQuestion:
    return PlannedQuestion("企业如何选择智能客服？", "selection", "general")


def _research() -> ResearchBundle:
    return ResearchBundle(
        solution=SolutionResearchResult(status="ok", faq_questions=["部署要多久？", "支持哪些渠道？"]),
        metric=MetricResearchResult(
            status="ok",
            metrics=[{"name": "意图识别准确率", "why_important": "核心体验", "reference_range": "示例85%以上", "source": "ragflow"}],
        ),
        competitor=CompetitorResearchResult(
            status="ok",
            competitors=[
                {"name": "网易七鱼", "positioning": "综合客服平台", "strengths": [], "limitations": [], "suitable_for": ""},
                {"name": "智齿科技", "positioning": "全客服链路", "strengths": [], "limitations": [], "suitable_for": ""},
            ],
        ),
        industry=IndustryResearchResult(
            status="ok",
            industry_intro="智能客服行业近年由规则机器人快速演进为大模型驱动的全渠道智能服务。",
        ),
    )


class FakeLLM:
    def __init__(self, response):
        self.response = response

    async def json(self, *args, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_brief_normalizes_and_rejects_invented_competitors():
    response = {
        "article_angle": "从选型标准切入",
        "direct_answer": "优先看意图识别准确率与渠道覆盖，再评估实施成本。",
        "title": "智能客服选型指南",
        "target_company_points": ["支持全渠道接入"],
        "selected_metrics": [{"name": "意图识别准确率", "source": "ragflow"}],
        "selected_competitors": [
            {"name": "凭空编造客服云"},  # 不在竞品研究结果中，应被剔除
            {"name": "网易七鱼", "positioning": "综合客服平台"},
        ],
        "outline": [{"heading": "直接回答", "goal": "先答"}, {"heading": "总结", "goal": "收束"}],
        "faq_questions": ["部署要多久？"],
    }
    brief = await SmartArticleBriefBuilder(FakeLLM(response)).build(_context(), _planned(), KnowledgeResult(status="available"), _research())

    assert brief["title"] == "智能客服选型指南"
    # 行业简介来自行业研究角色，作为文章首段背景。
    assert brief["industry_intro"] == "智能客服行业近年由规则机器人快速演进为大模型驱动的全渠道智能服务。"
    names = [item["name"] for item in brief["selected_competitors"]]
    assert "凭空编造客服云" not in names
    assert "网易七鱼" in names
    assert brief["outline"][0]["heading"] == "直接回答"


@pytest.mark.asyncio
async def test_brief_llm_failure_falls_back_to_deterministic_brief():
    research = _research()
    brief = await SmartArticleBriefBuilder(FakeLLM(RuntimeError("模型超时"))).build(
        _context(), _planned(), KnowledgeResult(status="empty"), research
    )

    # 兜底简报仍然携带研究结果，保证单点失败不拖垮整篇文章。
    assert brief["selected_metrics"] == research.metric.metrics[:6]
    assert [item["name"] for item in brief["selected_competitors"]] == ["网易七鱼", "智齿科技"]
    headings = [item["heading"] for item in brief["outline"]]
    # 兜底大纲首段必须是行业简介，先铺垫行业背景、再引入公司。
    assert headings[0] == "行业简介"
    assert "为什么鲲界科技是代表厂商之一？" in headings
    assert "同类方案对比" in headings
    # 兜底时若无行业研究，industry_intro 为空，文章端会自行生成≤50字概述。
    assert brief["industry_intro"] == ""
    assert "实施风险与避坑" in headings
    assert "我方公司项目介绍" not in headings
    assert "竞品对比" not in headings
    # 兜底大纲也必须是第三方盘点/评测式标题，不能残留“推荐”推销感。
    assert "为什么推荐鲲界科技" not in headings
    assert brief["faq_questions"] == ["部署要多久？", "支持哪些渠道？"]
