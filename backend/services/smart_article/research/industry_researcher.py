from __future__ import annotations

from ..llm_adapter import SmartArticleLLMAdapter
from ..prompts import INDUSTRY_RESEARCH_SYSTEM, PROMPT_VERSIONS, build_industry_research_prompt
from ..schemas import KnowledgeResult, PlannedQuestion, ProjectContext
from .schemas import IndustryResearchResult


class IndustryResearcher:
    """行业研究角色：产出一段50字内、中性的行业近年发展开篇，用于文章首段背景。"""

    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def research(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
    ) -> IndustryResearchResult:
        data = await self.llm.json(
            INDUSTRY_RESEARCH_SYSTEM,
            build_industry_research_prompt(context, planned, knowledge.status, knowledge.context_text),
            temperature=0.4,
            max_tokens=1500,
            stage="研究角色：行业研究",
            prompt_version=PROMPT_VERSIONS["industry_research"],
        )
        if not isinstance(data, dict):
            raise ValueError("行业研究返回非JSON对象")
        return IndustryResearchResult.from_llm(data)
