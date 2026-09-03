from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.playwright.publishers import juejinpro
from backend.services.playwright.publishers.juejinpro import JuejinProPublisher


@pytest.fixture
def publisher() -> JuejinProPublisher:
    return JuejinProPublisher("juejin", {"name": "掘金"})


@pytest.mark.asyncio
async def test_category_is_always_reading(publisher, monkeypatch):
    page = MagicMock()
    chip = MagicMock()
    chip.click = AsyncMock()
    page.get_by_text.return_value.first = chip
    publisher._is_visible = AsyncMock(return_value=True)
    monkeypatch.setattr(juejinpro.asyncio, "sleep", AsyncMock())

    article = SimpleNamespace(category="人工智能", industry="食品", keywords=["鹅肝供应商"])

    assert await publisher._select_category(page, article) is True
    page.get_by_text.assert_called_once_with("阅读", exact=True)
    chip.click.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
async def test_tag_is_always_saas(publisher):
    publisher._add_tag = AsyncMock(return_value=True)
    page = MagicMock()
    article = SimpleNamespace(industry="食品", keyword="鹅肝供应商", tags=["餐饮"])

    assert await publisher._select_tag(page, article) is True
    publisher._add_tag.assert_awaited_once_with(page, "SaaS")


@pytest.mark.asyncio
async def test_add_tag_types_saas_and_presses_enter_once(publisher, monkeypatch):
    page = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    tag_input = MagicMock()
    tag_input.click = AsyncMock()
    tag_input.evaluate = AsyncMock(return_value="input")
    publisher._find_tag_input = AsyncMock(return_value=tag_input)
    publisher._tag_chip_exists = AsyncMock(return_value=True)
    monkeypatch.setattr(juejinpro.asyncio, "sleep", AsyncMock())

    assert await publisher._add_tag(page, "SaaS") is True
    page.keyboard.type.assert_awaited_once_with("SaaS", delay=40)
    assert [call.args[0] for call in page.keyboard.press.await_args_list] == [
        "ControlOrMeta+A",
        "Delete",
        "Enter",
    ]


@pytest.mark.asyncio
async def test_publish_stops_when_required_tag_fails(publisher, monkeypatch):
    page = MagicMock()
    publish_button = MagicMock()
    publish_button.click = AsyncMock()
    page.get_by_role.return_value.last = publish_button
    publisher._is_visible = AsyncMock(return_value=True)
    publisher._dismiss_common_popups = AsyncMock()
    publisher._select_category = AsyncMock(return_value=True)
    publisher._select_tag = AsyncMock(return_value=False)
    publisher._upload_cover = AsyncMock()
    monkeypatch.setattr(juejinpro.asyncio, "sleep", AsyncMock())

    article = SimpleNamespace(category="人工智能", industry="食品")

    assert await publisher._click_publish(page, article, ["cover.jpg"]) is False
    publisher._upload_cover.assert_not_awaited()
    publish_button.click.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
async def test_confirm_publish_falls_back_to_js_click(publisher, monkeypatch):
    """确认「确定并发布」：Playwright click 失败时，应回退到 JS el.click() 兜底。"""
    from unittest.mock import AsyncMock

    page = MagicMock()
    confirm_btn = MagicMock()
    # Playwright click 抛异常（如按钮被遮挡/不在视口）→ 必须走 JS 兜底
    confirm_btn.click = AsyncMock(side_effect=Exception("intercepts fail"))
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn.evaluate = AsyncMock()

    # 第一个候选按钮可见且就是上面的 confirm_btn
    page.get_by_role.return_value.last = confirm_btn
    page.locator.return_value.last = confirm_btn
    page.get_by_text.return_value.last = confirm_btn
    publisher._is_visible = AsyncMock(return_value=True)
    monkeypatch.setattr(juejinpro.asyncio, "sleep", AsyncMock())
    # 弹窗稳定轮询：evaluate 直接返回 True，避免额外等待
    page.evaluate = AsyncMock(return_value=True)

    assert await publisher._click_confirm_publish(page) is True
    confirm_btn.click.assert_awaited()  # 尝试过 Playwright click
    confirm_btn.evaluate.assert_awaited()  # 回退到 JS click


@pytest.mark.asyncio
async def test_confirm_publish_clicks_first_visible_candidate(publisher, monkeypatch):
    """确认「确定并发布」：可见候选应被常规 click 命中并立即返回。"""
    from unittest.mock import AsyncMock

    page = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()

    page.get_by_role.return_value.last = confirm_btn
    page.locator.return_value.last = confirm_btn
    page.get_by_text.return_value.last = confirm_btn
    publisher._is_visible = AsyncMock(return_value=True)
    monkeypatch.setattr(juejinpro.asyncio, "sleep", AsyncMock())
    page.evaluate = AsyncMock(return_value=True)

    assert await publisher._click_confirm_publish(page) is True
    confirm_btn.click.assert_awaited_once_with(force=True)
