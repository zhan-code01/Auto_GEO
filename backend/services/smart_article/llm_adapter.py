from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger

from backend.services.ai_generation_service import get_ai_service


class SmartArticleLLMAdapter:
    """Thin adapter over the existing configured model transport."""

    @staticmethod
    def _debug_enabled() -> bool:
        return os.getenv("SMART_ARTICLE_PROMPT_DEBUG", "1").strip().lower() not in {"0", "false", "off", "no"}

    @staticmethod
    def _print_block(title: str, content: str) -> None:
        border = "=" * 96
        # DEBUG 级：同时落控制台（LOG_LEVEL=DEBUG 时）与按日期命名的本地日志文件
        logger.debug(f"\n{border}\n[智能文章生成] {title}\n{border}\n{content}\n{border}")

    async def json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 4000,
        stage: str = "未命名阶段",
        prompt_version: str = "unknown",
    ) -> dict[str, Any]:
        if self._debug_enabled():
            self._print_block(
                f"AI请求 | 阶段={stage} | Prompt版本={prompt_version} | temperature={temperature} | max_tokens={max_tokens}",
                f"--- System Prompt ---\n{system_prompt}\n\n--- User Prompt ---\n{user_prompt}",
            )

        service = get_ai_service()
        result = await service.chat_json(
            system_prompt,
            user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if self._debug_enabled():
            self._print_block(
                f"AI响应 | 阶段={stage} | Prompt版本={prompt_version}",
                json.dumps(result, ensure_ascii=False, indent=2),
            )
        return result
