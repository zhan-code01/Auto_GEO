from __future__ import annotations

from ..llm_adapter import SmartArticleLLMAdapter
from ..prompts import PROMPT_VERSIONS, SOLUTION_RESEARCH_SYSTEM, build_solution_research_prompt
from ..schemas import KnowledgeResult, PlannedQuestion, ProjectContext
from .schemas import SolutionResearchResult


class SolutionResearcher:
    """方案研究角色：分析需求场景、解决思路、选型标准、实施步骤与风险。"""

    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def research(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
    ) -> SolutionResearchResult:
        data = await self.llm.json(
            SOLUTION_RESEARCH_SYSTEM,
            build_solution_research_prompt(context, planned, knowledge.status, knowledge.context_text),
            temperature=0.5,
            max_tokens=3000,
            stage="研究角色：方案研究",
            prompt_version=PROMPT_VERSIONS["solution_research"],
        )
        if not isinstance(data, dict):
            raise ValueError("方案研究返回非JSON对象")
        return SolutionResearchResult.from_llm(data)
