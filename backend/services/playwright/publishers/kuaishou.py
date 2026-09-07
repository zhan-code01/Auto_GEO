# -*- coding: utf-8 -*-
"""Kuaishou image-text publisher.

Adapted from the open-source social-auto-upload Kuaishou note flow, integrated
with AutoGEO's existing BasePublisher registry and account storage_state flow.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger
from playwright.async_api import Page

from .base import BasePublisher, registry
from .note_utils import clean_title, materialize_images, normalize_tags, plain_note_from_article


KUAISHOU_UPLOAD_URL = "https://cp.kuaishou.com/article/publish/video"
KUAISHOU_MANAGE_URL_PATTERN = "**/article/manage/video?status=2&from=publish**"


class KuaishouPublisher(BasePublisher):
    MAX_TITLE_LENGTH = 30
    MAX_NOTE_LENGTH = 2000
    MAX_DESCRIPTION_LENGTH = 480

    async def publish(
        self,
        page: Page,
        article: Any,
        account: Any,
        declare_ai_content: bool = True,
    ) -> Dict[str, Any]:
        temp_files: list[str] = []
        stage = "init"
        try:
            title = clean_title(getattr(article, "title", "") or "未命名图文", self.MAX_TITLE_LENGTH)
            note = plain_note_from_article(article, limit=self.MAX_NOTE_LENGTH)
            tags = normalize_tags(article, title, max_tags=3)

            stage = "materialize_images"
            image_paths, materialized_temp_files = await materialize_images(article, limit=9)
            temp_files.extend(materialized_temp_files)
            if not image_paths:
                raise RuntimeError("图片上传失败：文章中的图片无法下载，请检查网络后重试。如问题持续，请重新生成文章。")
            logger.info("[快手] 已准备 {} 张图文图片", len(image_paths))

            stage = "navigate"
            await self._navigate_to_publish(page)
            await self._ensure_logged_in(page)
            manual_result = await self.ensure_publish_can_continue(page, "navigate")
            if manual_result:
                return manual_result

            stage = "switch_note_tab"
            await self._switch_to_note_tab(page)

            stage = "upload_images"
            await self._upload_images(page, image_paths)
            await self._dismiss_known_dialogs(page)

            stage = "fill_note"
            await self._fill_note(page, title, note, tags)

            stage = "wait_upload"
            await self._wait_upload_finished(page)

            stage = "publish"
            await self._click_publish(page)

            stage = "wait_result"
            return await self._wait_for_result(page)
        except Exception as exc:
            logger.exception("[快手] 图文发布失败 stage={}: {}", stage, exc)
            debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
            return {"success": False, "error_msg": f"快手图文发布失败[{stage}]: {exc}", "debug_path": debug_path}
        finally:
            for path in temp_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

    async def _navigate_to_publish(self, page: Page) -> None:
        await page.goto(
            self.config.get("publish_url", KUAISHOU_UPLOAD_URL),
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(1500)

        if await self._has_server_busy(page):
            logger.warning("[快手] 页面提示服务器繁忙，改为重新直达发布页")
            await page.goto(KUAISHOU_UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

        if not await self._has_publish_surface(page):
            await self._open_publish_from_home(page)

        try:
            await page.wait_for_url("**/article/publish/video**", timeout=15000)
        except Exception:
            if not await self._has_publish_surface(page):
                raise RuntimeError(f"未进入快手发布页，当前页面: {page.url}")

    async def _ensure_logged_in(self, page: Page) -> None:
        login_markers = [
            "text=登录",
            "text=扫码登录",
            "main#login-form",
        ]
        for selector in login_markers:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible(timeout=1500):
                    raise RuntimeError("快手登录态已失效，请重新授权账号")
            except RuntimeError:
                raise
            except Exception:
                continue

    async def _has_publish_surface(self, page: Page) -> bool:
        for selector in [
            'div[role="tab"]:has-text("图文")',
            'button:has-text("上传图片")',
            "text=上传图片",
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
            "text=描述",
        ]:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible(timeout=1000):
                    return True
            except Exception:
                continue
        return False

    async def _has_server_busy(self, page: Page) -> bool:
        for text in ("服务器繁忙", "系统繁忙", "稍后再试", "service unavailable"):
            try:
                marker = page.get_by_text(text, exact=False).first
                if await marker.count() and await marker.is_visible(timeout=500):
                    return True
            except Exception:
                continue
        return False

    async def _open_publish_from_home(self, page: Page) -> None:
        for selector in [
            'a[href*="/article/publish/video"]',
            'a[href*="/rest/infra/logout"][href*="article"]',
            'a:has-text("去上传")',
            'a:has-text("视频上传")',
        ]:
            try:
                link = page.locator(selector).first
                if await link.count() and await link.is_visible(timeout=1000):
                    href = await link.get_attribute("href")
                    if href and "/rest/infra/logout" in href:
                        continue
                    await link.click(force=True)
                    await page.wait_for_timeout(2500)
                    return
            except Exception:
                continue

        await page.goto(KUAISHOU_UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)

    async def _switch_to_note_tab(self, page: Page) -> None:
        selectors = [
            'div[role="tablist"] div[role="tab"]:has-text("图文")',
            'div[role="tab"]:has-text("图文")',
            'button:has-text("图文")',
            'span:has-text("图文")',
        ]
        for selector in selectors:
            try:
                tab = page.locator(selector).first
                if await tab.count() and await tab.is_visible(timeout=5000):
                    await tab.click(force=True)
                    await page.wait_for_timeout(1000)
                    logger.info("[快手] 已切换到图文发布")
                    return
            except Exception:
                continue
        raise RuntimeError("未找到快手图文发布 Tab")

    async def _upload_images(self, page: Page, image_paths: list[str]) -> None:
        button_selectors = [
            'button[class^="_upload-btn"]:has-text("上传图片")',
            'button:has-text("上传图片")',
            'div:has-text("上传图片") input[type="file"]',
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ]

        for selector in button_selectors:
            try:
                locator = page.locator(selector).first
                if not await locator.count():
                    continue
                tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "input":
                    await locator.set_input_files(image_paths)
                else:
                    async with page.expect_file_chooser(timeout=10000) as fc_info:
                        await locator.click(force=True)
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(image_paths)
                logger.info("[快手] 已上传 {} 张图片", len(image_paths))
                await page.wait_for_timeout(1500)
                return
            except Exception:
                continue
        raise RuntimeError("未找到快手图片上传入口")

    async def _dismiss_known_dialogs(self, page: Page) -> None:
        for selector in [
            'button[type="button"] span:text("我知道了")',
            'button:has-text("我知道了")',
            '[aria-label="Skip"]',
            '[data-action="skip"]',
        ]:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible(timeout=1000):
                    await locator.click(force=True)
                    await page.wait_for_timeout(500)
            except Exception:
                continue

    async def _fill_note(self, page: Page, title: str, note: str, tags: list[str]) -> None:
        text = self._compose_limited_note_text(title, note, tags)

        description_targets = [
            page.get_by_text("描述").locator("xpath=following-sibling::div").first,
            page.locator('[contenteditable="true"]').first,
            page.locator("textarea").first,
        ]

        for target in description_targets:
            try:
                if await target.count() and await target.is_visible(timeout=5000):
                    await target.click(force=True)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                    await page.keyboard.type(text, delay=20)
                    logger.info("[快手] 图文描述和话题已填写，长度={}", len(text))
                    return
            except Exception:
                continue
        raise RuntimeError("未找到快手图文描述输入框")

    def _compose_limited_note_text(self, title: str, note: str, tags: list[str]) -> str:
        tag_text = " ".join(f"#{tag}" for tag in tags if tag)
        prefix = f"{title}\n" if title else ""
        suffix = f"\n{tag_text}" if tag_text else ""
        available = self.MAX_DESCRIPTION_LENGTH - len(prefix) - len(suffix)

        if available <= 0:
            fallback = f"{title} {tag_text}".strip()
            return fallback[: self.MAX_DESCRIPTION_LENGTH]

        clean_note = (note or "").strip()
        if len(clean_note) > available:
            clean_note = clean_note[: max(0, available - 1)].rstrip() + "…"

        text = f"{prefix}{clean_note}{suffix}".strip()
        return text[: self.MAX_DESCRIPTION_LENGTH]

    async def _wait_upload_finished(self, page: Page) -> None:
        for index in range(60):
            try:
                if await page.locator("text=上传失败").count():
                    raise RuntimeError("快手提示图片上传失败")
                uploading = await page.locator("text=上传中").count()
                if uploading == 0 and index >= 2:
                    logger.info("[快手] 图文素材上传完成")
                    return
            except RuntimeError:
                raise
            except Exception:
                pass
            await asyncio.sleep(2)
        logger.warning("[快手] 等待上传完成超时，将继续尝试发布")

    async def _click_publish(self, page: Page) -> None:
        for _ in range(20):
            try:
                publish_button = page.get_by_text("发布", exact=True).first
                if await publish_button.count() and await publish_button.is_visible(timeout=2000):
                    await publish_button.click(force=True)
                    await page.wait_for_timeout(1000)
                    confirm_button = page.get_by_text("确认发布").first
                    if await confirm_button.count() and await confirm_button.is_visible(timeout=2000):
                        await confirm_button.click(force=True)
                    return
            except Exception:
                pass
            await asyncio.sleep(1)
        raise RuntimeError("未找到快手发布按钮")

    async def _wait_for_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）"""
        for _ in range(60):  # 60次 × 2秒 = 120秒
            manual_result = await self.ensure_publish_can_continue(page, "wait_result")
            if manual_result:
                return manual_result

            try:
                await page.wait_for_url(KUAISHOU_MANAGE_URL_PATTERN, timeout=1000)
                return {"success": True, "platform_url": page.url}
            except Exception:
                pass

            for text in ("发布成功", "已发布", "审核中"):
                try:
                    marker = page.get_by_text(text, exact=False).first
                    if await marker.count() and await marker.is_visible(timeout=1000):
                        return {"success": True, "platform_url": page.url}
                except Exception:
                    continue

            for text in ("发布失败", "违规", "失败"):
                try:
                    marker = page.get_by_text(text, exact=False).first
                    if await marker.count() and await marker.is_visible(timeout=1000):
                        error_text = await marker.inner_text()
                        return {"success": False, "error_msg": f"快手提示: {error_text}"}
                except Exception:
                    continue

            await asyncio.sleep(2)

        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": f"超时未检测到快手发布结果提示，请到快手创作者后台确认。debug={debug_path}",
        }

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        debug_dir = Path("backend/debug/kuaishou")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[快手] 保存调试 HTML 失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[快手] 保存调试截图失败: {}", exc)
        return str(html_path)


KUAISHOU_CONFIG = {
    "name": "快手",
    "publish_url": KUAISHOU_UPLOAD_URL,
    "color": "#FF4500",
}
registry.register("kuaishou", KuaishouPublisher("kuaishou", KUAISHOU_CONFIG))
