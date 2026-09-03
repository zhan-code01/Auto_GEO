from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.playwright.publishers import weibo as weibo_module
from backend.services.playwright.publishers.weibo import ArticleBlock, WeiboPublisher, parse_article_blocks


def test_parse_article_blocks_preserves_markdown_image_order():
    content = "第一段文字\n![图片1](https://img.test/1.png)\n第二段文字\n![图片2](https://img.test/2.jpg)"

    assert parse_article_blocks(content) == [
        ArticleBlock("text", "第一段文字"),
        ArticleBlock("image", "https://img.test/1.png"),
        ArticleBlock("text", "第二段文字"),
        ArticleBlock("image", "https://img.test/2.jpg"),
    ]


def test_parse_article_blocks_supports_html_images():
    content = "<p>第一段</p><img src='https://img.test/a.png'><p>第二段</p>"

    assert parse_article_blocks(content) == [
        ArticleBlock("text", "第一段"),
        ArticleBlock("image", "https://img.test/a.png"),
        ArticleBlock("text", "第二段"),
    ]


@pytest.mark.asyncio
async def test_auto_attempt_reports_risk_without_waiting(monkeypatch):
    ensure = AsyncMock(return_value=SimpleNamespace(handled=False, timed_out=False))
    monkeypatch.setattr(weibo_module, "ensure_no_manual_challenge", ensure)
    monkeypatch.setattr(
        weibo_module,
        "manual_required_result",
        lambda _: {"manual_required": True, "error_code": "CAPTCHA_REQUIRED"},
    )
    publisher = WeiboPublisher("weibo", {})

    result = await publisher._guard(AsyncMock(), "security_verification")

    assert result["manual_required"] is True
    assert ensure.await_args.kwargs["wait_for_resolution"] is False


@pytest.mark.asyncio
async def test_manual_handoff_waits_without_timeout(monkeypatch):
    ensure = AsyncMock(return_value=SimpleNamespace(handled=True, timed_out=False))
    monkeypatch.setattr(weibo_module, "ensure_no_manual_challenge", ensure)
    publisher = WeiboPublisher("weibo", {})
    publisher.set_attempt_mode("manual_handoff")

    result = await publisher._guard(AsyncMock(), "security_verification")

    assert result is None
    assert ensure.await_args.kwargs["wait_for_resolution"] is True
    assert ensure.await_args.kwargs["timeout_seconds"] == 0
