from __future__ import annotations

from ..llm_adapter import SmartArticleLLMAdapter
from ..prompts import COMPETITOR_RESEARCH_SYSTEM, PROMPT_VERSIONS, build_competitor_research_prompt
from ..schemas import KnowledgeResult, PlannedQuestion, ProjectContext
from .schemas import CompetitorResearchResult


class CompetitorResearcher:
    """竞品研究角色：给出2~3个真实知名竞品的公开常识层面对比信息。"""

    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def research(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
    ) -> CompetitorResearchResult:
        prompt = build_competitor_research_prompt(
            context, planned, knowledge.status, knowledge.context_text
        )
        last_error: BaseException | None = None
        # 竞品研究偶发返回空数组（模型过度谨慎）或 JSON 解析失败（模型抖动），
        # 重试一次以提高竞品命中率；重试后仍为空则如实返回空结果，由上游简报决定降级写法。
        for _ in range(2):
            try:
                data = await self.llm.json(
                    COMPETITOR_RESEARCH_SYSTEM,
                    prompt,
                    temperature=0.3,
                    max_tokens=2500,
                    stage="研究角色：竞品研究",
                    prompt_version=PROMPT_VERSIONS["competitor_research"],
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            if not isinstance(data, dict):
                last_error = ValueError("竞品研究返回非JSON对象")
                continue
            result = CompetitorResearchResult.from_llm(data, company_name=context.company_name)
            if result.competitors:
                return result
            last_error = None
        # 两次均未拿到竞品：若是因为解析/调用失败，返回 failed 让协调器记录警告；
        # 若模型明确返回空（领域确无公开玩家），返回正常空结果交由上游处理。
        if last_error is not None:
            return CompetitorResearchResult.failed()
        return CompetitorResearchResult(status="ok", competitors=[])
