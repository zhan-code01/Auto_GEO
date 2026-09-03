from __future__ import annotations

from ..llm_adapter import SmartArticleLLMAdapter
from ..prompts import METRIC_RESEARCH_SYSTEM, PROMPT_VERSIONS, build_metric_research_prompt
from ..schemas import KnowledgeResult, PlannedQuestion, ProjectContext
from .schemas import MetricResearchResult


class MetricResearcher:
    """指标研究角色：提炼选型关键指标，RAGFlow来源优先，模型通用指标兜底。"""

    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def research(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
    ) -> MetricResearchResult:
        data = await self.llm.json(
            METRIC_RESEARCH_SYSTEM,
            build_metric_research_prompt(context, planned, knowledge.status, knowledge.context_text),
            temperature=0.4,
            max_tokens=2500,
            stage="研究角色：指标研究",
            prompt_version=PROMPT_VERSIONS["metric_research"],
        )
        if not isinstance(data, dict):
            raise ValueError("指标研究返回非JSON对象")
        return MetricResearchResult.from_llm(data)
