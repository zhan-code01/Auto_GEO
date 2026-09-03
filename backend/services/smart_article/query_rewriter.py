from __future__ import annotations

from .llm_adapter import SmartArticleLLMAdapter
from .prompts import QUERY_REWRITE_SYSTEM, PROMPT_VERSIONS, build_query_rewrite_prompt
from .query_builder import build_queries
from .schemas import ProjectContext, PlannedQuestion, QuerySpec


class QueryRewriteError(ValueError):
    pass


class SmartArticleQueryRewriter:
    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def rewrite(self, context: ProjectContext, planned: PlannedQuestion, initial: list[QuerySpec]) -> list[QuerySpec]:
        data = await self.llm.json(
            QUERY_REWRITE_SYSTEM,
            build_query_rewrite_prompt(context, planned.question, planned.intent_type, [item.as_dict() for item in initial]),
            temperature=0.2,
            max_tokens=800,
            stage="Prompt R：知识库Query兜底改写",
            prompt_version=PROMPT_VERSIONS["query_rewrite"],
        )
        raw = data.get("queries")
        if not isinstance(raw, list):
            raise QueryRewriteError("Prompt R返回缺少queries数组")
        existing = {item.text.casefold() for item in initial}
        result: list[QuerySpec] = []
        for item in raw[:5]:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get("text") or "").split()).strip()
            if not text or text.casefold() in existing or len(text) > 120:
                continue
            result.append(QuerySpec(text=text, kind="capability_match", purpose=str(item.get("purpose") or "补充检索产品资料")))
            existing.add(text.casefold())
        if not 3 <= len(result) <= 5:
            raise QueryRewriteError("Prompt R返回的Query数量或内容不合格")
        return result

    @staticmethod
    def fallback(context: ProjectContext, planned: PlannedQuestion) -> list[QuerySpec]:
        base = [
            QuerySpec(f"{context.company_name} {context.project_name}", "project_identity", "宽检索公司和项目"),
            QuerySpec(f"{context.company_name} {context.domain_keyword}", "capability_match", "宽检索领域资料"),
            QuerySpec(f"{context.project_name} 产品 服务", "capability_match", "宽检索项目产品服务"),
        ]
        initial = {item.text.casefold() for item in build_queries(context, planned)}
        return [item for item in base if item.text.casefold() not in initial]

    @property
    def version(self) -> str:
        return PROMPT_VERSIONS["query_rewrite"]
