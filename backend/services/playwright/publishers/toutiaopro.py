# -*- coding: utf-8 -*-
"""Toutiao Pro publisher.

This is a clean implementation of the Toutiao article publishing flow.  It is
kept separate from ``toutiao.py`` so we can test and compare it without
touching the existing adapter.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import Page

from .base import BasePublisher, registry
from .note_utils import clean_title, generated_publish_images_enabled, materialize_images


TOUTIAO_PRO_CONFIG = {
    "id": "toutiaopro",
    "name": "头条号 Pro",
    "code": "TT_PRO",
    "login_url": "https://mp.toutiao.com/",
    "publish_url": "https://mp.toutiao.com/profile_v4/graphic/publish?is_new_connect=0&is_new_user=0",
    "color": "#F85959",
}


class ToutiaoProPublisher(BasePublisher):
    """Readable Toutiao publisher focused on the current graphic article page."""

    MAX_TITLE_LENGTH = 30
    MAX_CONTENT_LENGTH = 20000
    PUBLISH_URL = TOUTIAO_PRO_CONFIG["publish_url"]

    TITLE_SELECTORS = [
        'textarea[placeholder="请输入文章标题（2～30个字）"]',
        'textarea[placeholder*="请输入文章标题"]',
        'textarea[placeholder*="标题"]',
        ".publish-editor-title textarea",
        ".assistant-title textarea",
        "textarea.byte-input__inner",
    ]

    CONTENT_SELECTORS = [
        ".ProseMirror",
        '[contenteditable="true"][data-placeholder*="正文"]',
        "div[class*='editor'] [contenteditable='true']",
        '[contenteditable="true"]',
    ]

    COVER_ADD_SELECTORS = [
        'div:has-text("展示封面") .add-icon',
        'div:has-text("展示封面") [class*="add"]',
        '[class*="cover"] .add-icon',
        '[class*="cover"] [class*="add"]',
        ".article-cover-add",
        ".add-icon",
    ]

    FREE_IMAGE_ITEMS = [
        ".wall-rows > div > .list > li",
        ".wall-rows li",
        '[class*="wall"] li',
        '[class*="image"] li',
    ]

    CONFIRM_TEXTS = ["确定", "完成", "确认"]
    PUBLISH_TEXTS = ["预览并发布", "发布"]
    PUBLISH_CONFIRM_TEXTS = ["确认发布", "确定发布", "继续发布", "确认"]

    FAIL_TEXTS = [
        "请设置封面",
        "请选择封面",
        "请输入文章标题",
        "请输入正文",
        "正文不能为空",
        "发布失败",
        "上传失败",
        "内容违规",
        "操作频繁",
        "安全验证",
    ]

    SUCCESS_TEXTS = ["发布成功", "提交成功", "审核中", "已发布"]

    async def publish(
        self,
        page: Page,
        article: Any,
        account: Any,
        declare_ai_content: bool = True,
    ) -> dict[str, Any]:
        temp_files: list[str] = []
        stage = "init"
        try:
            title = clean_title(getattr(article, "title", "") or "未命名文章", self.MAX_TITLE_LENGTH)
            content = (getattr(article, "content", "") or "")[: self.MAX_CONTENT_LENGTH]

            stage = "navigate"
            await self._goto_editor(page)

            stage = "manual_check"
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            stage = "ready"
            if not await self._wait_editor_ready(page):
                return await self._fail(page, stage, "未检测到头条图文编辑器")

            await self._close_interference(page)

            stage = "images"
            image_paths, image_temp_files = await materialize_images(article, limit=9)
            temp_files.extend(image_temp_files)

            stage = "fill_title"
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "标题填写失败")

            stage = "fill_content"
            if not await self._fill_content(page, content, image_paths):
                return await self._fail(page, stage, "正文填写失败")

            stage = "cover"
            if not await self._ensure_cover(page, image_paths):
                return await self._manual_fail(
                    page,
                    stage,
                    "展示封面未设置成功。请检查头条号封面弹窗是否改版，或手动选择封面后重试。",
                )

            stage = "ai_declaration"
            if declare_ai_content:
                await self._set_ai_declaration(page)

            stage = "publish"
            if not await self._click_publish(page):
                return await self._fail(page, stage, "未能点击预览并发布")

            stage = "wait_result"
            return await self._wait_result(page)
        except Exception as exc:
            logger.exception("[头条号 Pro] 发布异常 stage={}: {}", stage, exc)
            return await self._fail(page, stage, str(exc))
        finally:
            for path in temp_files:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass

    async def _goto_editor(self, page: Page) -> None:
        await page.goto(self.PUBLISH_URL, wait_until="domcontentloaded", timeout=45000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            logger.info("[头条号 Pro] networkidle 超时，继续检测编辑器")

    async def _wait_editor_ready(self, page: Page, timeout: int = 30) -> bool:
        for _ in range(timeout * 2):
            for selector in [*self.TITLE_SELECTORS, *self.CONTENT_SELECTORS]:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible(timeout=300):
                        return True
                except Exception:
                    continue
            await asyncio.sleep(0.5)
        return False

    async def _close_interference(self, page: Page) -> None:
        """Close visible assistant/guide overlays without removing editor content."""
        close_selectors = [
            'button:has-text("知道了")',
            'button:has-text("我知道了")',
            'button:has-text("跳过")',
            'button:has-text("稍后再说")',
            '[aria-label="Close"]',
            '[aria-label="close"]',
            ".byte-icon--close",
            ".byte-modal__close",
        ]
        for selector in close_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible(timeout=500):
                    await locator.click(force=True)
                    await asyncio.sleep(0.3)
            except Exception:
                continue

        # Codegen showed a "头条创作助手" heading with a close svg.
        try:
            assistant = page.get_by_role("heading", name="头条创作助手").locator("svg").first
            if await assistant.count() > 0 and await assistant.is_visible(timeout=500):
                await assistant.click(force=True)
        except Exception:
            pass

    async def _fill_title(self, page: Page, title: str) -> bool:
        for selector in self.TITLE_SELECTORS:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0 or not await locator.is_visible(timeout=1200):
                    continue
                await locator.click(force=True)
                await locator.fill(title)
                if await self._locator_contains(locator, title[: min(8, len(title))]):
                    logger.info("[头条号 Pro] 标题已填写: {}", title)
                    return True
            except Exception:
                continue
        return False

    async def _fill_content(self, page: Page, content: str, image_paths: list[str]) -> bool:
        blocks = self._build_content_blocks(content, image_paths)
        if not blocks:
            return False

        if not await self._focus_content_editor(page):
            return False

        await page.evaluate(
            """() => {
                const editor = document.querySelector(".ProseMirror")
                    || Array.from(document.querySelectorAll('[contenteditable="true"]'))
                        .find(el => el.getBoundingClientRect().height > 80);
                if (editor) editor.innerHTML = "";
            }"""
        )

        wrote_text = False
        inserted_images = 0
        first_text = ""
        for block in blocks:
            if block["type"] == "text":
                text = block["content"].strip()
                if not text:
                    continue
                await self._focus_editor_end(page)
                if wrote_text:
                    # 只用 1 个 Enter 切分段落。文本块内部由 markdown_to_plain_text
                    # 提供的单个换行已经够用；多按一次 Enter 会在编辑器里再生成一个
                    # 空段落，叠加段间距后变成"段落中间巨大空栏"。
                    await page.keyboard.press("Enter")
                if await self._paste_text(page, text):
                    wrote_text = True
                    first_text = first_text or text
            elif block["type"] == "image":
                await self._focus_editor_end(page)
                if await self._paste_image(page, block["content"]):
                    inserted_images += 1
                    await page.keyboard.press("Enter")

        if first_text and not await self._editor_contains_text(page, first_text):
            return False

        logger.info("[头条号 Pro] 正文已填写，图片 {}/{}", inserted_images, len(image_paths))
        return wrote_text

    def _build_content_blocks(self, content: str, image_paths: list[str]) -> list[dict[str, str]]:
        blocks: list[dict[str, str]] = []
        image_index = 0
        pattern = re.compile(
            r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>",
            flags=re.IGNORECASE,
        )
        cursor = 0
        for match in pattern.finditer(content or ""):
            text = self.markdown_to_plain_text((content or "")[cursor : match.start()])
            if text:
                blocks.append({"type": "text", "content": text})
            if image_index < len(image_paths):
                blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1
            cursor = match.end()

        tail = self.markdown_to_plain_text((content or "")[cursor:])
        if tail:
            blocks.append({"type": "text", "content": tail})

        while image_index < len(image_paths):
            blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1

        return blocks

    async def _focus_content_editor(self, page: Page) -> bool:
        for selector in self.CONTENT_SELECTORS:
            try:
                locator = page.locator(selector).first
                if await locator.count() > 0 and await locator.is_visible(timeout=1000):
                    await locator.click(force=True)
                    return True
            except Exception:
                continue
        return False

    async def _focus_editor_end(self, page: Page) -> None:
        await page.evaluate(
            """() => {
                const editor = document.querySelector(".ProseMirror")
                    || Array.from(document.querySelectorAll('[contenteditable="true"]'))
                        .find(el => el.getBoundingClientRect().height > 80);
                if (!editor) return;
                editor.focus();
                const selection = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(editor);
                range.collapse(false);
                selection.removeAllRanges();
                selection.addRange(range);
            }"""
        )

    async def _paste_text(self, page: Page, text: str) -> bool:
        """Insert text into the ProseMirror editor reliably.

        优先使用真实键盘输入 ``page.keyboard.insert_text``：它派发的是受信任的
        input 事件，头条（字节 syl-editor / ProseMirror）在有头浏览器里能稳定接收。
        合成 ``ClipboardEvent`` 粘贴在本地客户端浏览器中经常被编辑器忽略，因此只作为
        最后的兜底手段。
        """
        # 1) 把光标移动到编辑器末尾，保证文字落在正确位置。
        await self._focus_editor_end(page)
        await asyncio.sleep(0.15)

        # 2) 主路径：真实键盘输入（有头浏览器可靠）。
        try:
            await page.keyboard.insert_text(text)
            await asyncio.sleep(0.25)
            if await self._editor_contains_text(page, text):
                return True
        except Exception as exc:
            logger.warning("[头条号 Pro] 正文键盘输入失败，改用粘贴兜底: {}", exc)

        # 3) 兜底：合成 ClipboardEvent（可能被编辑器忽略，仅作最后尝试）。
        try:
            await page.evaluate(
                """(text) => {
                    const editor = document.querySelector(".ProseMirror")
                        || document.activeElement;
                    if (!editor) return false;
                    editor.focus();
                    const dt = new DataTransfer();
                    dt.setData("text/plain", text);
                    editor.dispatchEvent(new ClipboardEvent("paste", {
                        clipboardData: dt, bubbles: true, cancelable: true
                    }));
                    return true;
                }""",
                text,
            )
            await asyncio.sleep(0.25)
            return await self._editor_contains_text(page, text)
        except Exception as exc:
            logger.warning("[头条号 Pro] 正文粘贴兜底失败: {}", exc)
        return False

    async def _paste_image(self, page: Page, image_path: str) -> bool:
        if not image_path or not os.path.exists(image_path):
            return False
        before = await self._editor_image_count(page)
        try:
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            with open(image_path, "rb") as file:
                data_b64 = base64.b64encode(file.read()).decode("ascii")
            ok = await page.evaluate(
                """({ dataB64, mime }) => {
                    const editor = document.querySelector(".ProseMirror")
                        || document.activeElement;
                    if (!editor) return false;
                    editor.focus();
                    const bin = atob(dataB64);
                    const bytes = new Uint8Array(bin.length);
                    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                    const dt = new DataTransfer();
                    dt.items.add(new File([bytes], "autogeo-image.jpg", { type: mime }));
                    editor.dispatchEvent(new ClipboardEvent("paste", {
                        clipboardData: dt, bubbles: true, cancelable: true
                    }));
                    return true;
                }""",
                {"dataB64": data_b64, "mime": mime},
            )
            if not ok:
                return False
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await self._editor_image_count(page) > before:
                    return True
        except Exception as exc:
            logger.warning("[头条号 Pro] 正文图片粘贴失败: {}", exc)
        return False

    async def _ensure_cover(self, page: Page, image_paths: list[str]) -> bool:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.8)

        if await self._wait_auto_cover_selected(page):
            logger.info("[头条号 Pro] 已检测到展示封面")
            return True

        # When the article has body images, Toutiao usually auto-populates the
        # cover thumbnails from those images. In that case do not open the
        # "free licensed images" dialog; wait a little longer and only fail
        # clearly if the page still has no usable cover.
        if image_paths:
            await self._select_cover_mode_from_article_images(page, image_count=len(image_paths))
            if await self._wait_auto_cover_selected(page):
                logger.info("[头条号 Pro] 已使用正文图片作为展示封面")
                return True
            logger.warning("[头条号 Pro] 正文有图片，但未检测到自动展示封面")
            return False

        if not generated_publish_images_enabled(self.config):
            logger.info("[头条号 Pro] 无正文图片，跳过免费正版图片替代封面")
            return False

        if await self._set_cover_via_free_image(page):
            logger.info("[头条号 Pro] 已通过免费正版图片设置封面")
            return True

        logger.warning("[头条号 Pro] 免费正版图片封面设置失败，尝试本地上传兜底")
        return await self._set_cover_via_local_upload(page)

    async def _wait_auto_cover_selected(self, page: Page, timeout: int = 10) -> bool:
        for _ in range(max(1, timeout * 2)):
            if await self._has_cover_selected(page):
                return True
            await asyncio.sleep(0.5)
        return False

    async def _has_cover_selected(self, page: Page) -> bool:
        try:
            return bool(
                await page.evaluate(
                    """() => {
                        const visible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0
                                && style.display !== "none"
                                && style.visibility !== "hidden"
                                && Number(style.opacity || "1") > 0;
                        };
                        const labels = Array.from(document.querySelectorAll("*"))
                            .filter(el => visible(el) && (el.innerText || "").trim() === "展示封面");
                        for (const label of labels) {
                            let scope = label.parentElement;
                            for (let i = 0; i < 10 && scope; i++, scope = scope.parentElement) {
                                const text = scope.innerText || "";
                                if (!text.includes("展示封面")) continue;
                                const imgs = Array.from(scope.querySelectorAll("img")).filter(visible);
                                if (imgs.length > 0) return true;
                                if (text.includes("编辑") && text.includes("替换")) return true;
                                if (text.includes("预览") && (text.includes("JPEG") || text.includes("PNG"))) return true;
                            }
                        }
                        return false;
                    }"""
                )
            )
        except Exception:
            return False

    async def _select_cover_mode_from_article_images(self, page: Page, image_count: int) -> None:
        """Use Toutiao's auto cover generated from body images.

        If three or more body images exist, the page often selects "三图" itself.
        Otherwise "单图" is enough. This method only nudges the radio mode and
        never opens the image-source dialog.
        """
        target = "三图" if image_count >= 3 else "单图"
        try:
            ok = await page.evaluate(
                """(target) => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden";
                    };
                    const radios = Array.from(document.querySelectorAll('label, [role="radio"], [class*="radio"]'))
                        .filter(el => visible(el) && (el.innerText || "").includes(target));
                    const radio = radios.find(el => {
                        let scope = el;
                        for (let i = 0; i < 8 && scope; i++, scope = scope.parentElement) {
                            if ((scope.innerText || "").includes("展示封面")) return true;
                        }
                        return false;
                    }) || radios[0];
                    if (!radio) return false;
                    const cls = String(radio.className || "");
                    const checked = cls.includes("checked")
                        || cls.includes("active")
                        || radio.getAttribute("aria-checked") === "true"
                        || radio.querySelector('input:checked');
                    if (!checked) radio.click();
                    return true;
                }""",
                target,
            )
            if ok:
                logger.info("[头条号 Pro] 已确认展示封面模式: {}", target)
                await asyncio.sleep(0.8)
        except Exception:
            pass

    async def _set_cover_via_free_image(self, page: Page) -> bool:
        if not await self._open_cover_dialog(page):
            return False

        try:
            await page.get_by_text("免费正版图片", exact=False).click(timeout=5000)
        except Exception:
            return False

        item = await self._first_visible_locator(page, self.FREE_IMAGE_ITEMS, timeout=12000)
        if item is None:
            return False
        await item.click(force=True)

        if not await self._click_button_by_text(page, self.CONFIRM_TEXTS, timeout=8000):
            return False

        for _ in range(20):
            await asyncio.sleep(0.5)
            if await self._has_cover_selected(page):
                return True
        return False

    async def _set_cover_via_local_upload(self, page: Page) -> bool:
        """Reserved fallback: use only when a file input is already available."""
        try:
            file_input = page.locator('input[type="file"][accept*="image"], input[type="file"]').last
            if await file_input.count() == 0:
                return False
            # The pro flow intentionally does not invent a local cover here.  The
            # article image is already used in the body; free-image cover is the
            # stable first target from codegen.
            return False
        except Exception:
            return False

    async def _open_cover_dialog(self, page: Page) -> bool:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.5)
        for selector in self.COVER_ADD_SELECTORS:
            try:
                locator = page.locator(selector).last
                if await locator.count() == 0 or not await locator.is_visible(timeout=1200):
                    continue
                await locator.click(force=True)
                await asyncio.sleep(1)
                if await page.get_by_text("免费正版图片", exact=False).count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def _set_ai_declaration(self, page: Page) -> None:
        labels = ["内容由 AI 生成", "AI 生成", "人工智能生成", "声明为 AI 生成"]
        try:
            await page.evaluate(
                """(labels) => {
                    for (const label of labels) {
                        const node = Array.from(document.querySelectorAll("label, span, div"))
                            .find(el => (el.innerText || "").includes(label));
                        if (!node) continue;
                        const scope = node.closest("label") || node.parentElement || node;
                        const checkbox = scope.querySelector('input[type="checkbox"], [role="checkbox"], [class*="checkbox"]');
                        if (!checkbox) continue;
                        const checked = checkbox.checked
                            || checkbox.getAttribute("aria-checked") === "true"
                            || String(checkbox.className || "").includes("checked");
                        if (!checked) checkbox.click();
                        return true;
                    }
                    return false;
                }""",
                labels,
            )
        except Exception:
            pass

    async def _click_publish(self, page: Page) -> bool:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.8)

        if not await self._click_button_by_text(page, self.PUBLISH_TEXTS, timeout=5000):
            return False

        # 头条预览弹窗有时加载较慢，确认发布按钮可能十几秒后才出现。
        # 这里尽力等待并点击确认发布；即便本阶段没点中也不直接判失败，
        # 交给下方的 _wait_result 在等待期间继续补点。
        await self._confirm_publish_with_retry(page)
        return True

    async def _confirm_publish_with_retry(self, page: Page) -> bool:
        """等待并点击预览弹窗里的『确认发布』按钮，最多尝试两轮。

        第一轮直接轮询等待确认发布（延长超时到 25s）；若仍不可见，
        说明预览弹窗可能未真正打开，重新点击一次『预览并发布』后再等 20s。
        """
        if await self._click_publish_confirm(page, timeout=25000):
            return True

        logger.warning("[头条号 Pro] 首轮未检测到确认发布，尝试重新打开预览弹窗")
        await asyncio.sleep(1)
        await self._click_button_by_text(page, self.PUBLISH_TEXTS, timeout=5000)
        await asyncio.sleep(2)
        if await self._click_publish_confirm(page, timeout=20000):
            return True

        logger.warning("[头条号 Pro] 仍未检测到确认发布按钮，将由等待阶段兜底或转人工接管")
        return False

    async def _click_publish_confirm(self, page: Page, timeout: int = 25000) -> bool:
        if await self._click_button_by_text(page, self.PUBLISH_CONFIRM_TEXTS, timeout=timeout):
            logger.info("[头条号 Pro] 已点击确认发布")
            return True

        # Preview overlay buttons are sometimes plain div/span styled as a
        # button. Use a scoped text fallback after the semantic button attempts.
        try:
            ok = await page.evaluate(
                """(texts) => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden";
                    };
                    const candidates = Array.from(document.querySelectorAll("button, div, span, a"))
                        .filter(el => visible(el) && texts.some(t => (el.innerText || "").trim() === t));
                    const primary = candidates.reverse().find(el => {
                        const style = window.getComputedStyle(el);
                        const bg = style.backgroundColor || "";
                        const cls = String(el.className || "");
                        return bg.includes("248") || bg.includes("89") || cls.includes("primary") || cls.includes("confirm");
                    }) || candidates[candidates.length - 1];
                    if (!primary) return false;
                    primary.click();
                    return true;
                }""",
                self.PUBLISH_CONFIRM_TEXTS,
            )
            if ok:
                logger.info("[头条号 Pro] 已通过 DOM 兜底点击确认发布")
                return True
        except Exception:
            pass

        return False

    async def _wait_result(self, page: Page) -> dict[str, Any]:
        start_url = page.url
        for _ in range(60):
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            for text in self.FAIL_TEXTS:
                if await self._visible_text(page, text):
                    return await self._fail(page, "wait_result", text)

            for text in self.SUCCESS_TEXTS:
                if await self._visible_text(page, text):
                    return {"success": True, "platform_url": page.url, "error_msg": None}

            if page.url != start_url and re.search(r"(article|content|manage|home|graphic)", page.url, re.I):
                return {"success": True, "platform_url": page.url, "error_msg": None}

            # 兜底：若预览确认弹窗仍开着（确认发布按钮可见），自动补点确认发布，
            # 避免预览弹窗延迟渲染时漏掉发布动作导致进入人工接管。
            # 仅匹配明确的发布确认文案，不使用宽泛的『确认』以防误点失败弹窗。
            try:
                await self._click_button_by_text(
                    page, ["确认发布", "确定发布", "继续发布"], timeout=1200
                )
            except Exception:
                pass

            await asyncio.sleep(1)

        return await self._manual_fail(page, "wait_result", "未检测到明确发布结果，请到头条号后台人工确认")

    async def _click_button_by_text(self, page: Page, texts: list[str], timeout: int = 3000) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout / 1000
        while asyncio.get_event_loop().time() < deadline:
            for text in texts:
                try:
                    button = page.get_by_role("button", name=re.compile(re.escape(text))).last
                    if await button.count() > 0 and await button.is_visible(timeout=300):
                        await button.click(force=True)
                        logger.info("[头条号 Pro] 已点击按钮: {}", text)
                        return True
                except Exception:
                    pass
                try:
                    button = page.locator(f'button:has-text("{text}")').last
                    if await button.count() > 0 and await button.is_visible(timeout=300):
                        await button.click(force=True)
                        logger.info("[头条号 Pro] 已点击按钮: {}", text)
                        return True
                except Exception:
                    pass
                try:
                    ok = await page.evaluate(
                        """(text) => {
                            const visible = (el) => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                return rect.width > 0
                                    && rect.height > 0
                                    && style.display !== "none"
                                    && style.visibility !== "hidden"
                                    && style.pointerEvents !== "none";
                            };
                            const disabled = (el) => {
                                const cls = String(el.className || "");
                                return el.disabled
                                    || el.getAttribute("aria-disabled") === "true"
                                    || cls.includes("disabled")
                                    || cls.includes("is-disabled");
                            };
                            const normalize = (value) => String(value || "").replace(/\\s+/g, "");
                            const target = normalize(text);
                            const nodes = Array.from(document.querySelectorAll(
                                'button, [role="button"], a, div, span'
                            ));
                            const candidates = nodes
                                .filter((el) => visible(el) && !disabled(el))
                                .filter((el) => normalize(el.innerText) === target)
                                .map((el) => {
                                    const rect = el.getBoundingClientRect();
                                    const style = window.getComputedStyle(el);
                                    const cls = String(el.className || "");
                                    const primary = cls.includes("primary")
                                        || cls.includes("confirm")
                                        || style.backgroundColor.includes("248")
                                        || style.backgroundColor.includes("89")
                                        || style.color.includes("255");
                                    const bottom = rect.top > window.innerHeight * 0.55;
                                    const right = rect.left > window.innerWidth * 0.45;
                                    return { el, score: (primary ? 8 : 0) + (bottom ? 4 : 0) + (right ? 2 : 0) + rect.width / 1000 };
                                })
                                .sort((a, b) => a.score - b.score);
                            const chosen = candidates[candidates.length - 1]?.el;
                            if (!chosen) return false;
                            chosen.scrollIntoView({ block: "center", inline: "center" });
                            chosen.click();
                            return true;
                        }""",
                        text,
                    )
                    if ok:
                        logger.info("[头条号 Pro] 已通过文本兜底点击按钮: {}", text)
                        return True
                except Exception:
                    pass
            await asyncio.sleep(0.3)
        return False

    async def _first_visible_locator(self, page: Page, selectors: list[str], timeout: int = 5000):
        deadline = asyncio.get_event_loop().time() + timeout / 1000
        while asyncio.get_event_loop().time() < deadline:
            for selector in selectors:
                try:
                    locators = page.locator(selector)
                    count = await locators.count()
                    for index in range(count):
                        item = locators.nth(index)
                        if await item.is_visible(timeout=300):
                            return item
                except Exception:
                    continue
            await asyncio.sleep(0.3)
        return None

    async def _visible_text(self, page: Page, text: str) -> bool:
        try:
            node = page.get_by_text(text, exact=False).first
            return await node.count() > 0 and await node.is_visible(timeout=300)
        except Exception:
            return False

    async def _locator_contains(self, locator, text: str) -> bool:
        if not text:
            return True
        try:
            actual = await locator.input_value(timeout=500)
        except Exception:
            try:
                actual = await locator.inner_text(timeout=500)
            except Exception:
                actual = ""
        return text in actual

    async def _editor_contains_text(self, page: Page, text: str) -> bool:
        probe = re.sub(r"\s+", "", text[: min(30, len(text))])
        if not probe:
            return True
        try:
            actual = await page.evaluate(
                """() => {
                    const editor = document.querySelector(".ProseMirror")
                        || Array.from(document.querySelectorAll('[contenteditable="true"]'))
                            .find(el => el.getBoundingClientRect().height > 80);
                    return editor ? (editor.innerText || "") : "";
                }"""
            )
            return probe in re.sub(r"\s+", "", actual or "")
        except Exception:
            return False

    async def _editor_image_count(self, page: Page) -> int:
        try:
            return int(
                await page.evaluate(
                    """() => {
                        const editor = document.querySelector(".ProseMirror")
                            || Array.from(document.querySelectorAll('[contenteditable="true"]'))
                                .find(el => el.getBoundingClientRect().height > 80);
                        return editor ? editor.querySelectorAll("img").length : 0;
                    }"""
                )
            )
        except Exception:
            return 0

    async def _fail(self, page: Page, stage: str, message: str) -> dict[str, Any]:
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        logger.error("[头条号 Pro] stage={} 失败: {}", stage, message)
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": f"[{stage}] {message}",
            "debug_path": debug_path,
        }

    async def _manual_fail(self, page: Page, stage: str, message: str) -> dict[str, Any]:
        debug_path = await self._save_debug_snapshot(page, f"manual_{stage}")
        result = self.manual_intervention_result(stage, message, page)
        result["debug_path"] = debug_path
        return result

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        # 使用基于模块位置的绝对路径，避免 exe 在其它工作目录运行时快照丢失。
        project_root = Path(__file__).resolve().parents[4]
        debug_dir = project_root / "backend" / "debug" / "toutiaopro"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[头条号 Pro] 保存 debug HTML 失败: {}", exc)
        try:
            await page.screenshot(path=str(html_path.with_suffix(".png")), full_page=True)
        except Exception:
            pass
        return str(html_path)


registry.register("toutiaopro", ToutiaoProPublisher("toutiaopro", TOUTIAO_PRO_CONFIG))
registry.register(
    "toutiao",
    ToutiaoProPublisher(
        "toutiao",
        {
            **TOUTIAO_PRO_CONFIG,
            "id": "toutiao",
            "name": "头条号",
        },
    ),
)
