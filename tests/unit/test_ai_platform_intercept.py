# -*- coding: utf-8 -*-
"""AI platform response interception tests."""

import inspect

import pytest

from backend.services.playwright.ai_platforms.base import AIPlatformChecker


class DummyChecker(AIPlatformChecker):
    async def check(self, page, question: str, keyword: str, company: str):
        return {"success": True}


@pytest.mark.asyncio
async def test_intercept_answer_awaits_chunk_waiter():
    checker = DummyChecker("dummy", {"name": "Dummy"})
    collector = {
        "chunks": ["这是一段已经捕获到的 AI 回答内容，长度足够通过拦截结果判断。"],
        "handler": lambda response: None,
    }

    result = await checker.intercept_answer(page=None, timeout_ms=100, collector=collector)

    assert not inspect.iscoroutine(result)
    assert result["success"] is True
    assert result["method"] == "api-intercept"
