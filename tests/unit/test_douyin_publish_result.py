# -*- coding: utf-8 -*-

import asyncio
import inspect

from backend.services.playwright.publishers.douyin import DouyinPublisher


class FakeLocator:
    def __init__(self, visible: bool = False, text: str = ""):
        self.visible = visible
        self.text = text

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self.visible else 0

    async def is_visible(self):
        return self.visible

    async def inner_text(self):
        return self.text


class FakePage:
    url = "https://creator.douyin.com/creator-micro/content/manage"

    def __init__(self, visible_texts=None):
        self.visible_texts = set(visible_texts or [])
        self.queries = []

    def get_by_text(self, text, exact=False):
        self.queries.append(text)
        return FakeLocator(text in self.visible_texts, text)


def test_douyin_work_management_text_is_not_publish_success(monkeypatch):
    publisher = DouyinPublisher("douyin", {})
    page = FakePage({"作品管理"})

    async def no_sleep(_seconds):
        return None

    async def fake_snapshot(_page, _stage):
        return "backend/debug/douyin/wait_result_timeout_test.html"

    monkeypatch.setattr("backend.services.playwright.publishers.douyin.asyncio.sleep", no_sleep)
    monkeypatch.setattr(publisher, "_save_debug_snapshot", fake_snapshot)

    result = asyncio.run(publisher._wait_for_publish_result(page))

    assert result["success"] is False
    assert "作品管理" not in page.queries
    assert "超时未检测到抖音发布结果提示" in result["error_msg"]


def test_douyin_explicit_success_prompt_is_publish_success(monkeypatch):
    publisher = DouyinPublisher("douyin", {})
    page = FakePage({"发布成功"})

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("backend.services.playwright.publishers.douyin.asyncio.sleep", no_sleep)

    result = asyncio.run(publisher._wait_for_publish_result(page))

    assert result["success"] is True
    assert result["platform_url"] == page.url


def test_douyin_final_publish_click_uses_exact_publish_button():
    source = inspect.getsource(DouyinPublisher._click_publish)

    assert 'exact_publish = re.compile(r"^\\s*发布\\s*$")' in source
    assert "sel.PUBLISH_SUBMIT_BTN" not in source
    assert "高清发布" not in source


def test_douyin_confirm_does_not_click_generic_publish_button():
    source = inspect.getsource(DouyinPublisher._handle_confirm)

    assert 'button:has-text("发布")' not in source
    assert 'button:has-text("确认发布")' in source
