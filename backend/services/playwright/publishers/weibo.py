# -*- coding: utf-8 -*-
"""微博头条文章发布适配器。"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Page

from . import weibo_selectors as sel
from .base import BasePublisher, registry
from .note_utils import materialize_image_sources
from ..humanize import random_delay, short_delay
from ..manual_guard import ensure_no_manual_challenge, manual_required_result, manual_timeout_result


@dataclass(frozen=True)
class ArticleBlock:
    kind: str
    value: str


MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMAGE_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)


def parse_article_blocks(content: str) -> list[ArticleBlock]:
    """按 Markdown/HTML 原始顺序解析文字与图片。"""
    matches = [(m.start(), m.end(), m.group(1)) for m in MARKDOWN_IMAGE_RE.finditer(content or "")]
    matches.extend((m.start(), m.end(), m.group(1)) for m in HTML_IMAGE_RE.finditer(content or ""))
    matches.sort(key=lambda item: item[0])

    blocks: list[ArticleBlock] = []
    cursor = 0
    for start, end, source in matches:
        if start < cursor:
            continue
        text = _clean_article_text((content or "")[cursor:start])
        if text:
            blocks.append(ArticleBlock("text", text))
        blocks.append(ArticleBlock("image", source.strip()))
        cursor = end
    tail = _clean_article_text((content or "")[cursor:])
    if tail:
        blocks.append(ArticleBlock("text", tail))
    return blocks


def _clean_article_text(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|h[1-6])>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class WeiboPublisher(BasePublisher):
    """发布带独立标题、交错图文和正文封面的微博文章。"""

    MAX_TITLE_LENGTH = 32

    async def publish(self, page: Page, article: Any, account: Any, declare_ai_content: bool = True) -> dict[str, Any]:
        temp_files: list[str] = []
        stage = "init"
        editor_page = page
        start_time = time.time()
        article_id = getattr(article, "id", None)
        logger.info(
            f"[微博文章] 开始发布: article_id={article_id} title={getattr(article, 'title', '')[:20]!r}"
        )
        try:
            title = (getattr(article, "title", "") or "未命名")[: self.MAX_TITLE_LENGTH]
            content = getattr(article, "content", "") or ""
            blocks = parse_article_blocks(content)
            image_sources = [block.value for block in blocks if block.kind == "image"]
            if not image_sources:
                raise RuntimeError("微博文章正文至少需要一张图片用于封面")
            logger.debug(f"[微博文章] 解析完成: article_id={article_id} blocks={len(blocks)} images={len(image_sources)}")

            stage = "materialize_images"
            image_paths, image_temp_files = await materialize_image_sources(image_sources, limit=len(image_sources))
            temp_files.extend(image_temp_files)
            if len(image_paths) < len(image_sources):
                raise RuntimeError("正文中的部分图片无法下载，已停止发布以避免图文错位")
            logger.debug(f"[微博文章] 图片就绪: {len(image_paths)}/{len(image_sources)}")

            stage = "navigate_home"
            await page.goto("https://weibo.com/", wait_until="domcontentloaded", timeout=60000)
            await random_delay(2, 4)
            if manual := await self._guard(page, stage):
                logger.warning(f"[微博文章] 人工介入: stage={stage}")
                return manual

            stage = "open_article_editor"
            editor_page = await self._open_article_editor(page)
            if manual := await self._guard(editor_page, stage):
                logger.warning(f"[微博文章] 人工介入: stage={stage}")
                return manual

            stage = "fill_title"
            await self._fill_first(editor_page, sel.TITLE_INPUT, title)

            stage = "fill_content"
            manual = await self._fill_article(editor_page, blocks, image_paths)
            if manual:
                return manual

            stage = "select_cover"
            await self._select_first_cover(editor_page)

            stage = "publish_settings"
            await self._disable_followers_only(editor_page)
            await self._click_named_button(editor_page, "下一步")

            stage = "security_verification"
            await asyncio.sleep(1)
            if manual := await self._guard(editor_page, stage):
                logger.warning(f"[微博文章] 人工介入: stage={stage}")
                return manual

            stage = "final_publish"
            await self._click_final_publish(editor_page)

            stage = "wait_result"
            result = await self._wait_for_result(editor_page)
            elapsed = time.time() - start_time
            if result.get("success"):
                logger.success(
                    f"[微博文章] 发布成功: article_id={article_id} url={result.get('platform_url')} "
                    f"elapsed={elapsed:.1f}s"
                )
            else:
                logger.error(
                    f"[微博文章] 发布未确认: article_id={article_id} error={result.get('error_msg')} "
                    f"elapsed={elapsed:.1f}s"
                )
            return result
        except Exception as exc:
            elapsed = time.time() - start_time
            logger.exception(f"[微博文章] 发布失败 stage={stage} elapsed={elapsed:.1f}s: {exc}")
            return {"success": False, "error_msg": f"微博文章发布失败[{stage}]: {exc}"}
        finally:
            for path in temp_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

    async def _guard(self, page: Page, stage: str) -> dict[str, Any] | None:
        resolution = await ensure_no_manual_challenge(
            page,
            platform="weibo",
            stage=stage,
            timeout_seconds=0 if self.is_manual_handoff() else None,
            wait_for_resolution=self.is_manual_handoff(),
            on_event=self._manual_event_callback,
        )
        if not resolution or resolution.handled:
            return None
        return manual_timeout_result(resolution) if resolution.timed_out else manual_required_result(resolution)

    async def _open_article_editor(self, page: Page) -> Page:
        for selector in sel.ARTICLE_ENTRY:
            entry = page.locator(selector).first
            try:
                if not await entry.count() or not await entry.is_visible(timeout=1500):
                    continue
                async with page.expect_popup(timeout=10000) as popup_info:
                    await entry.click(force=True)
                popup = await popup_info.value
                await popup.wait_for_load_state("domcontentloaded")
                await self._click_optional(popup, sel.WRITE_ARTICLE_BUTTON)
                return popup
            except Exception:
                continue
        raise RuntimeError("未找到微博文章入口或文章编辑器未弹出")

    async def _fill_article(
        self, page: Page, blocks: list[ArticleBlock], image_paths: list[str]
    ) -> dict[str, Any] | None:
        editor = await self._first_visible(page, sel.EDITOR, timeout=8000)
        if editor is None:
            raise RuntimeError("未找到微博文章正文编辑器")
        await editor.click()
        await editor.fill("")

        image_index = 0
        for block in blocks:
            if block.kind == "text":
                await page.keyboard.insert_text(block.value)
                # 只用 1 个 Enter 切分段落（避免空段落放大成巨大空栏）
                await page.keyboard.press("Enter")
                continue
            before = await editor.locator("img").count()
            await self._paste_image(page, image_paths[image_index])
            image_index += 1
            await self._wait_for_image(editor, before)
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            if manual := await self._guard(page, f"paste_image_{image_index}"):
                return manual
        return None

    async def _paste_image(self, page: Page, path: str) -> None:
        mime = mimetypes.guess_type(path)[0] or "image/png"
        payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        await page.evaluate(
            """({data, mime, name}) => {
                const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
                const file = new File([bytes], name, {type: mime});
                const transfer = new DataTransfer();
                transfer.items.add(file);
                const target = document.activeElement;
                if (!target) throw new Error('editor is not focused');
                target.dispatchEvent(new ClipboardEvent('paste', {
                    clipboardData: transfer, bubbles: true, cancelable: true
                }));
            }""",
            {"data": payload, "mime": mime, "name": Path(path).name},
        )

    async def _wait_for_image(self, editor, previous_count: int) -> None:
        for _ in range(60):
            count = await editor.locator("img").count()
            uploading = await editor.locator('[class*="uploading"], [class*="loading"]').count()
            if count > previous_count and uploading == 0:
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("正文图片粘贴上传超时")

    async def _select_first_cover(self, page: Page) -> None:
        await self._click_optional(page, sel.COVER_ENTRY)
        candidate = await self._first_visible(page, sel.COVER_CANDIDATES, timeout=8000)
        if candidate is None:
            raise RuntimeError("未找到正文封面候选图片")
        await candidate.click(force=True)
        await self._click_named_button(page, "下一步", dialog_only=True)
        await self._click_named_button(page, "确定")

    async def _disable_followers_only(self, page: Page) -> None:
        label = page.get_by_text(sel.FOLLOWERS_ONLY_LABEL, exact=False).first
        if not await label.count():
            return
        checkbox = label.locator("xpath=ancestor-or-self::label[1]//input[@type='checkbox']")
        if not await checkbox.count():
            checkbox = label.locator("xpath=preceding::input[@type='checkbox'][1]")
        if await checkbox.count() and await checkbox.is_checked():
            await checkbox.uncheck(force=True)

    async def _click_final_publish(self, page: Page) -> None:
        button = await self._first_visible(page, sel.FINAL_PUBLISH_BUTTON, timeout=15000)
        if button is None:
            raise RuntimeError("人工验证完成后未找到最终发布按钮")
        await button.click(force=True)

    async def _wait_for_result(self, page: Page) -> dict[str, Any]:
        for _ in range(60):
            if manual := await self._guard(page, "wait_result"):
                return manual
            for keyword in sel.SUCCESS_TEXT:
                node = page.get_by_text(keyword, exact=False).first
                if await node.count() and await node.is_visible():
                    return {"success": True, "platform_url": page.url}
            await asyncio.sleep(2)
        return {"success": False, "error_msg": "未检测到微博文章发布成功提示", "platform_url": page.url}

    async def _fill_first(self, page: Page, selectors: list[str], value: str) -> None:
        locator = await self._first_visible(page, selectors, timeout=8000)
        if locator is None:
            raise RuntimeError("未找到微博文章标题输入框")
        await locator.fill(value)

    async def _click_optional(self, page: Page, selectors: list[str]) -> bool:
        locator = await self._first_visible(page, selectors, timeout=3000)
        if locator is None:
            return False
        await locator.click(force=True)
        await short_delay()
        return True

    async def _click_named_button(self, page: Page, name: str, dialog_only: bool = False) -> None:
        scope = page.get_by_role("dialog") if dialog_only else page
        button = scope.get_by_role("button", name=name).first
        try:
            visible = await button.count() and await button.is_visible(timeout=5000)
        except Exception:
            visible = False
        if not visible:
            button = scope.get_by_text(name, exact=True).first
        if not await button.count() or not await button.is_visible(timeout=5000):
            raise RuntimeError(f"未找到按钮：{name}")
        await button.click(force=True)
        await short_delay()

    async def _first_visible(self, page: Page, selectors: list[str], timeout: int):
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible(timeout=timeout):
                    return locator
            except Exception:
                continue
        return None


WEIBO_CONFIG = {"name": "微博", "publish_url": "https://weibo.com/", "color": "#E6162D"}
registry.register("weibo", WeiboPublisher("weibo", WEIBO_CONFIG))
