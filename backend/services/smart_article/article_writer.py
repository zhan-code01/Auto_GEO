from __future__ import annotations

from typing import Any

from .llm_adapter import SmartArticleLLMAdapter
from .prompts import ARTICLE_SYSTEM, PROMPT_VERSIONS, build_article_prompt
from .schemas import GeneratedArticle, PlannedQuestion, ProjectContext, KnowledgeResult
from .validator import validate_generated_article


class SmartArticleWriter:
    def __init__(self, llm: SmartArticleLLMAdapter | None = None):
        self.llm = llm or SmartArticleLLMAdapter()

    async def write(
        self,
        context: ProjectContext,
        planned: PlannedQuestion,
        knowledge: KnowledgeResult,
        feedback: str = "",
        brief: dict[str, Any] | None = None,
    ) -> GeneratedArticle:
        data = await self.llm.json(
            ARTICLE_SYSTEM,
            build_article_prompt(
                context,
                planned,
                knowledge.status,
                knowledge.context_text,
                knowledge.chunks,
                feedback,
                brief=brief,
            ),
            temperature=0.65,
            # 推理模型(deepseek-v4-flash)会消耗大量 reasoning_tokens，
            # 8000 上限时推理占 7500+ 导致 JSON 输出被截断。
            # 提高到 16000 确保推理 + 完整 JSON 输出都有足够空间。
            max_tokens=16000,
            stage="最终写作：GEO图文文章生成",
            prompt_version=PROMPT_VERSIONS["article"],
        )
        return validate_generated_article(data, len(knowledge.chunks))

    @property
    def version(self) -> str:
        return PROMPT_VERSIONS["article"]
