from __future__ import annotations

import asyncio

from loguru import logger

from ..llm_adapter import SmartArticleLLMAdapter
from ..schemas import KnowledgeResult, PlannedQuestion, ProjectContext
from .competitor_researcher import CompetitorResearcher
from .industry_researcher import IndustryResearcher
from .metric_researcher import MetricResearcher
from .schemas import (
    CompetitorResearchResult,
    IndustryResearchResult,
    MetricResearchResult,
    ResearchBundle,
    SolutionResearchResult,
)
from .solution_researcher import SolutionResearcher


class SmartArticleResearchCoordinator:
    """并行运行四个研究角色。

    只并行LLM网络调用，不在协程之间共享SQLAlchemy Session。
    单个角色失败时降级为空结果并记录warning，不拖垮整篇文章。
    """

    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        shared_llm = llm or SmartArticleLLMAdapter()
        self.solution = SolutionResearcher(shared_llm)
        self.metric = MetricResearcher(shared_llm)
        self.competitor = CompetitorResearcher(shared_llm)
        self.industry = IndustryResearcher(shared_llm)

    async def run(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
    ) -> ResearchBundle:
        results = await asyncio.gather(
            self.solution.research(context, planned, knowledge),
            self.metric.research(context, planned, knowledge),
            self.competitor.research(context, planned, knowledge),
            self.industry.research(context, planned, knowledge),
            return_exceptions=True,
        )
        warnings: list[str] = []

        solution = results[0]
        if isinstance(solution, BaseException):
            warnings.append(f"方案研究失败，降级为空结果：{solution}")
            logger.warning("智能文章方案研究失败: {}", solution)
            solution = SolutionResearchResult.failed()

        metric = results[1]
        if isinstance(metric, BaseException):
            warnings.append(f"指标研究失败，降级为空结果：{metric}")
            logger.warning("智能文章指标研究失败: {}", metric)
            metric = MetricResearchResult.failed()

        competitor = results[2]
        if isinstance(competitor, BaseException):
            warnings.append(f"竞品研究失败，降级为空结果：{competitor}")
            logger.warning("智能文章竞品研究失败: {}", competitor)
            competitor = CompetitorResearchResult.failed()

        industry = results[3]
        if isinstance(industry, BaseException):
            warnings.append(f"行业研究失败，降级为空结果：{industry}")
            logger.warning("智能文章行业研究失败: {}", industry)
            industry = IndustryResearchResult.failed()

        return ResearchBundle(
            solution=solution,
            metric=metric,
            competitor=competitor,
            industry=industry,
            warnings=warnings,
        )
