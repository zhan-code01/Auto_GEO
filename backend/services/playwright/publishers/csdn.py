# -*- coding: utf-8 -*-
"""
CSDN发布适配器

CSDN创作平台: https://mp.csdn.net/console/editor/html
CSDN是中国最大的IT技术社区，支持Markdown编辑。
"""

import asyncio
import base64
import os
import re
import struct
import tempfile
import zlib
from datetime import datetime, timedelta
from typing import Any, Dict, List

from loguru import logger
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .base import BasePublisher, registry
from .note_utils import generated_publish_images_enabled, materialize_images, normalize_tags


class CsdnPublisher(BasePublisher):
    """CSDN博客发布器"""

    MAX_TITLE_LENGTH = 100
    MAX_CONTENT_LENGTH = 100000
    MAX_PER_HOUR = 10
    MAX_PER_DAY = 50
    MIN_INTERVAL_MINUTES = 1

    _publish_history: List[datetime] = []

    def _check_rate_limit(self) -> Dict[str, Any]:
        """检查发布频率限制"""
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)

        self._publish_history = [t for t in self._publish_history if t > now - timedelta(days=7)]

        count_hour = len([t for t in self._publish_history if t > one_hour_ago])
        if count_hour >= self.MAX_PER_HOUR:
            return {"allowed": False, "reason": f"过去1小时已发布{count_hour}次，超过{self.MAX_PER_HOUR}次限制"}

        count_day = len([t for t in self._publish_history if t > one_day_ago])
        if count_day >= self.MAX_PER_DAY:
            return {"allowed": False, "reason": f"过去24小时已发布{count_day}次，超过{self.MAX_PER_DAY}次限制"}

        if self._publish_history:
            minutes = (now - self._publish_history[-1]).total_seconds() / 60
            if minutes < self.MIN_INTERVAL_MINUTES:
                return {
                    "allowed": False,
                    "reason": f"距上次发布仅{int(minutes)}分钟，需≥{self.MIN_INTERVAL_MINUTES}分钟",
                }

        return {"allowed": True, "reason": "频率检查通过"}

    async def publish(self, page: Page, article: Any, account: Any, declare_ai_content: bool = True) -> Dict[str, Any]:
        temp_files = []
        stage = "init"

        try:
            logger.info("🚀 [CSDN] 开始发布文章...")

            rate = self._check_rate_limit()
            if not rate["allowed"]:
                logger.warning(f"⚠️ [CSDN] 频率限制: {rate['reason']}")
                return {"success": False, "error_msg": f"频率限制: {rate['reason']}"}

            title = getattr(article, "title", "") or "未命名文章"
            content = getattr(article, "content", "") or ""
            tags = self._derive_tags(article, title, content)

            if len(title) > self.MAX_TITLE_LENGTH:
                title = title[: self.MAX_TITLE_LENGTH]

            if len(content) > self.MAX_CONTENT_LENGTH:
                logger.warning(f"⚠️ [CSDN] 正文{len(content)}字，超过限制{self.MAX_CONTENT_LENGTH}字，将截断")
                content = content[: self.MAX_CONTENT_LENGTH]

            stage = "navigate"
            publish_url = self.config.get("publish_url", "https://mp.csdn.net/mp_blog/creation/editor")
            await page.goto(publish_url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)

            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            stage = "login_check"
            await self._ensure_logged_in(page)
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            stage = "close_popup"
            await self._close_popups(page)

            # ===== 图片处理 =====
            stage = "materialize_images"
            image_paths, image_temp_files = await materialize_images(article, limit=50)
            temp_files.extend(image_temp_files)
            if not image_paths and generated_publish_images_enabled(self.config):
                fallback_image = self._create_fallback_image(title, tags)
                if fallback_image:
                    image_paths.append(fallback_image)
                    temp_files.append(fallback_image)
                    logger.info(f"📷 [CSDN] 外链图片不可用，已生成本地兜底配图: {fallback_image}")
                else:
                    logger.warning("[CSDN] 图片下载失败且兜底生成失败，尝试继续发布...")
            elif not image_paths:
                logger.warning("[CSDN] 图片下载失败，尝试继续发布（可能无图）...")
            logger.info(f"📷 [CSDN] 已准备 {len(image_paths)} 张图片")

            stage = "fill_title"
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "填充标题失败")

            stage = "fill_content"
            if not await self._fill_content_with_images(page, content, image_paths):
                return await self._fail(page, stage, "填充正文失败")

            stage = "add_tags"
            await self._add_tags(page, tags)

            # 滚到底部确保发布设置区可见
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await self._close_unwanted_markdown_pages(page)

            stage = "publish"
            clicked, popup = await self._click_publish_and_capture_popup(page)
            if not clicked:
                return await self._fail(page, stage, "点击发布按钮失败")

            stage = "wait_result"
            if popup:
                result = await self._handle_popup_after_publish(popup, page, title, content, image_paths, tags)
            else:
                await self._close_unwanted_markdown_pages(page)
                result = await self._wait_for_result(page)
            if result.get("success"):
                self._publish_history.append(datetime.now())
            return result

        except Exception as e:
            logger.exception(f"❌ [CSDN] 发布失败 stage={stage}: {e}")
            return await self._fail(page, stage, str(e))
        finally:
            for f in temp_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass

    async def _ensure_logged_in(self, page: Page) -> None:
        """检查登录状态"""
        current_url = page.url.lower()
        if "login" in current_url or "signin" in current_url:
            raise RuntimeError("CSDN账号未登录，请重新授权")

        login_markers = ["text=登录", "text=登录CSDN", "text=立即登录"]
        for selector in login_markers:
            try:
                marker = page.locator(selector).first
                if await marker.count() > 0 and await marker.is_visible(timeout=2000):
                    raise RuntimeError("CSDN账号未登录，请重新授权")
            except RuntimeError:
                raise
            except Exception:
                continue

    async def _close_popups(self, page: Page) -> None:
        """关闭弹窗 — 含CSDN特定引导遮罩、目录侧边栏、AI助手"""

        # 1) 按 Escape 关闭大部分弹窗/引导遮罩
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except:
            pass

        # 2) CSDN 引导遮罩 — 点击蒙层或关闭按钮（替代 codegen 里那个随机ID的img）
        guide_close = [
            'div[class*="guide"] button',
            'div[class*="driver"] button',
            'div[class*="mask"]',
            'div[class*="overlay"]',
            'span[class*="skip"]',
            'button:has-text("跳过")',
            'button:has-text("知道了")',
            'button:has-text("下一步")',
        ]
        for sel in guide_close:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(0.5)
                    break
            except:
                pass

        # 3) 点击页面主体区域，有时能触发遮罩消失
        try:
            await page.mouse.click(500, 300)
            await asyncio.sleep(0.3)
        except:
            pass

        # 4) 再按一次 Escape
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except:
            pass

        # 5) CSDN 左侧"目录"侧边栏 — 点击收起
        try:
            collapse_btns = [
                page.locator('[class*="collapse"]').filter(has=page.locator("text=目录")).first,
                page.locator('div:has-text("目录")')
                .locator('button, [class*="toggle"], [class*="arrow"], svg, i')
                .first,
            ]
            for btn in collapse_btns:
                try:
                    if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                        await btn.click()
                        await asyncio.sleep(0.5)
                        break
                except:
                    pass
        except:
            pass

        # 6) 通用弹窗关闭
        close_selectors = [
            'button:has-text("知道了")',
            'button:has-text("关闭")',
            'button:has-text("跳过")',
            'button:has-text("确定")',
            ".modal-close",
            ".ant-modal-close",
            ".close-btn",
            '[class*="close"]',
            '[aria-label="Close"]',
        ]
        for _ in range(3):
            for selector in close_selectors:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=1000):
                        await btn.click()
                        await asyncio.sleep(0.5)
                except:
                    pass

    def _derive_tags(self, article: Any, title: str, content: str) -> List[str]:
        """优先用文章关键词；没有时从标题/正文蒸馏 2~3 个短标签。"""
        tags = normalize_tags(article, title, max_tags=3)
        if len(tags) >= 2:
            return tags[:3]

        text = f"{title}\n{self.markdown_to_plain_text(content, drop_first_h1=True)}"
        candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", text)
        stop_words = {
            "我们",
            "他们",
            "一个",
            "一种",
            "可以",
            "通过",
            "进行",
            "实现",
            "提升",
            "降低",
            "系统",
            "企业",
            "用户",
            "文章",
            "详解",
            "分析",
        }
        seen = set(tags)
        for word in candidates:
            if word in stop_words or word in seen:
                continue
            tags.append(word[:12])
            seen.add(word)
            if len(tags) >= 3:
                break
        return tags[:3]

    def _create_fallback_image(self, title: str, tags: List[str]) -> str | None:
        """用标准库生成一张轻量 PNG，避免外链图片失败时正文无图。"""
        try:
            width, height = 1200, 630
            seed = sum(ord(ch) for ch in f"{title}{''.join(tags)}") or 1
            palettes = [
                ((245, 247, 250), (40, 92, 166), (250, 173, 20)),
                ((248, 250, 252), (28, 122, 120), (239, 68, 68)),
                ((247, 249, 245), (90, 101, 70), (14, 165, 233)),
            ]
            bg, primary, accent = palettes[seed % len(palettes)]
            rows: list[bytes] = []
            for y in range(height):
                row = bytearray()
                for x in range(width):
                    t = x / max(1, width - 1)
                    wave = ((x * 3 + y * 5 + seed) % 97) / 97
                    r = int(bg[0] * (1 - t * 0.18) + primary[0] * t * 0.18 + wave * 8)
                    g = int(bg[1] * (1 - t * 0.18) + primary[1] * t * 0.18 + wave * 8)
                    b = int(bg[2] * (1 - t * 0.18) + primary[2] * t * 0.18 + wave * 8)

                    if 90 < x < 1110 and 110 < y < 520:
                        r = int(r * 0.96)
                        g = int(g * 0.96)
                        b = int(b * 0.96)
                    if 170 < x < 1030 and 230 < y < 255:
                        r, g, b = primary
                    if 170 < x < 820 and 295 < y < 315:
                        r, g, b = accent
                    if 170 < x < 930 and 355 < y < 370:
                        r = int(primary[0] * 0.55 + bg[0] * 0.45)
                        g = int(primary[1] * 0.55 + bg[1] * 0.45)
                        b = int(primary[2] * 0.55 + bg[2] * 0.45)

                    row.extend((min(r, 255), min(g, 255), min(b, 255)))
                rows.append(b"\x00" + bytes(row))

            def chunk(kind: bytes, payload: bytes) -> bytes:
                return (
                    struct.pack(">I", len(payload))
                    + kind
                    + payload
                    + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
                )

            raw = b"".join(rows)
            png = (
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6))
                + chunk(b"IEND", b"")
            )
            fd, path = tempfile.mkstemp(prefix="csdn_fallback_", suffix=".png")
            with os.fdopen(fd, "wb") as file:
                file.write(png)
            return path
        except Exception as exc:
            logger.warning(f"[CSDN] 生成兜底配图失败: {exc}")
            return None

    async def _click_publish_and_capture_popup(self, page: Page) -> tuple[bool, Page | None]:
        """点击发布，并捕获 CSDN 可能新开的 editor.csdn.net 标签页。"""
        clicked = False
        try:
            async with page.context.expect_page(timeout=5000) as popup_info:
                clicked = await self._click_publish(page)
            popup = await popup_info.value
            try:
                await popup.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(1)
            logger.info(f"[CSDN] 检测到新标签页: {popup.url}")
            return clicked, popup
        except PlaywrightTimeoutError:
            return clicked, None

    async def _close_unwanted_markdown_pages(self, keep_page: Page) -> None:
        """Close CSDN's accidental Markdown editor tabs and keep publishing on the original page."""
        for candidate in list(keep_page.context.pages):
            if candidate == keep_page:
                continue
            try:
                if await self._looks_like_markdown_editor(candidate):
                    logger.warning(f"[CSDN] 关闭干扰 Markdown 标签页: {candidate.url}")
                    await candidate.close()
            except Exception as exc:
                logger.debug(f"[CSDN] 关闭干扰标签页失败: {exc}")
        try:
            await keep_page.bring_to_front()
        except Exception:
            pass

    async def _handle_popup_after_publish(
        self,
        popup: Page,
        original: Page,
        title: str,
        content: str,
        image_paths: List[str],
        tags: List[str],
    ) -> Dict[str, Any]:
        """Handle new pages opened during publish without abandoning the original editor."""
        if await self._looks_like_markdown_editor(popup):
            logger.warning(f"[CSDN] 发布过程中出现干扰 Markdown 标签页，已忽略: {popup.url}")
            try:
                await popup.close()
            except Exception:
                pass
            try:
                await original.bring_to_front()
            except Exception:
                pass
            return await self._wait_for_result(original)

        logger.info("[CSDN] 新标签页不是 Markdown 干扰页，等待新页发布结果")
        return await self._wait_for_result(popup or original)

    async def _looks_like_markdown_editor(self, page: Page) -> bool:
        url = (page.url or "").lower()
        if "editor.csdn.net" in url or "/md" in url or "not_checkout" in url:
            return True
        try:
            markers = ["Markdown", "使用富文本编辑器", "这里写自定义目录标题", "欢迎使用Markdown编辑器"]
            for text in markers:
                node = page.get_by_text(text, exact=False).first
                if await node.count() > 0 and await node.is_visible(timeout=500):
                    return True
        except Exception:
            pass
        return False

    async def _fill_title(self, page: Page, title: str) -> bool:
        """填充标题 — 截图确认 placeholder='输入文章标题 (5 ~ 100个字)'"""
        # 优先用 get_by_placeholder 做语义匹配（比CSS属性选择准）
        try:
            inp = page.get_by_placeholder("输入文章标题")
            if await inp.count() > 0:
                await inp.click()
                await inp.fill("")
                await inp.fill(title)
                logger.info(f"✅ [CSDN] 标题已填充 (getByPlaceholder): {title[:30]}...")
                return True
        except Exception as e:
            logger.debug(f"[CSDN] get_by_placeholder 失败: {e}")

        # CSS 兜底
        title_selectors = [
            'input[placeholder*="输入文章标题"]',
            'input[placeholder*="请输入文章标题"]',
            'textarea[placeholder*="输入文章标题"]',
            'textarea[placeholder*="请输入文章标题"]',
            'input[placeholder*="文章标题"]',
            'textarea[placeholder*="文章标题"]',
            '[contenteditable="true"][data-placeholder*="标题"]',
            '[contenteditable="true"][placeholder*="标题"]',
            '[contenteditable="true"]:has-text("无标题")',
            'input[name*="title"]',
            "#article-title",
        ]
        for selector in title_selectors:
            try:
                inp = page.locator(selector).first
                if await inp.count() > 0 and await inp.is_visible(timeout=3000):
                    await inp.fill("")
                    await inp.fill(title)
                    logger.info(f"✅ [CSDN] 标题已填充: {title[:30]}...")
                    return True
            except Exception as e:
                logger.debug(f"[CSDN] 标题选择器 {selector} 失败: {e}")
                continue
        try:
            filled = await page.evaluate(
                """(title) => {
                    const nodes = Array.from(document.querySelectorAll(
                        'input, textarea, [contenteditable="true"]'
                    ));
                    const scored = nodes.map((node) => {
                        const rect = node.getBoundingClientRect();
                        const text = [
                            node.getAttribute('placeholder') || '',
                            node.getAttribute('data-placeholder') || '',
                            node.getAttribute('aria-label') || '',
                            node.innerText || '',
                            node.value || '',
                        ].join(' ');
                        let score = 0;
                        if (/标题|无标题|title/i.test(text)) score += 6;
                        if (rect.top >= 0 && rect.top < 180) score += 3;
                        if (rect.width > 160) score += 1;
                        if (node.offsetParent !== null) score += 1;
                        return { node, score };
                    }).filter(item => item.score >= 5)
                      .sort((a, b) => b.score - a.score);
                    const target = scored[0]?.node;
                    if (!target) return false;
                    target.focus();
                    if ('value' in target) {
                        target.value = title;
                    } else {
                        target.textContent = title;
                    }
                    target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: title }));
                    target.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }""",
                title,
            )
            if filled:
                logger.info(f"✅ [CSDN] 标题已填充 (JS兜底): {title[:30]}...")
                return True
        except Exception as e:
            logger.debug(f"[CSDN] 标题 JS 兜底失败: {e}")
        return False

    async def _fill_content_with_images(self, page: Page, content: str, image_paths: List[str]) -> bool:
        """填充正文 — 优先 CKEditor iframe，codegen录制确认"""
        plain_content = self.markdown_to_plain_text(content, drop_first_h1=True)

        if await self._looks_like_markdown_editor(page):
            if await self._fill_markdown_editor(page, plain_content):
                logger.info(f"✅ [CSDN] 正文已填充: {len(plain_content)} 字符 (Markdown编辑器)")
                await asyncio.sleep(1)
                if image_paths:
                    await self._upload_images(page, image_paths)
                return True

        # 1) CKEditor iframe（CSDN 当前编辑器）
        iframe_selectors = [
            "#cke_1_contents iframe",
            "#cke_2_contents iframe",
            "#cke_0_contents iframe",
            'div[id*="cke_"] iframe',
        ]
        for sel in iframe_selectors:
            try:
                iframe_locator = page.frame_locator(sel)
                body = iframe_locator.locator("body")
                if await body.count() > 0:
                    await body.click()
                    await body.evaluate("(el, t) => { el.innerHTML = t.replace(/\\n/g, '<br>'); }", plain_content)
                    await body.press("Enter")
                    await body.press("Backspace")
                    logger.info(f"✅ [CSDN] 正文已填充: {len(plain_content)} 字符 (CKEditor iframe)")
                    await asyncio.sleep(1)
                    if image_paths:
                        await self._upload_images(page, image_paths)
                    return True
            except Exception as e:
                logger.debug(f"[CSDN] iframe {sel} 失败: {e}")
                continue

        # 2) 兜底 — 常规编辑区
        content_selectors = [
            '.cm-content[contenteditable="true"]',
            ".CodeMirror textarea",
            ".CodeMirror-code",
            ".editor-view",
            ".CodeMirror-scroll",
            ".ql-editor",
            ".ProseMirror",
            ".markdown-body",
            '[contenteditable="true"]',
            'textarea[name*="content"]',
            "#content",
        ]
        for selector in content_selectors:
            try:
                editor = page.locator(selector).first
                if await editor.count() > 0 and await editor.is_visible(timeout=3000):
                    await editor.click()
                    await page.evaluate(
                        """(text) => {
                        const dt = new DataTransfer();
                        dt.setData("text/plain", text);
                        const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true });
                        const target = document.querySelector('.editor-view, .CodeMirror-scroll, .ql-editor, [contenteditable="true"]');
                        if (target) target.dispatchEvent(ev);
                    }""",
                        plain_content,
                    )
                    logger.info(f"✅ [CSDN] 正文已填充: {len(plain_content)} 字符")
                    await asyncio.sleep(1)
                    if image_paths:
                        await self._upload_images(page, image_paths)
                    return True
            except Exception as e:
                logger.debug(f"[CSDN] 内容选择器 {selector} 失败: {e}")
                continue

        return False

    async def _fill_markdown_editor(self, page: Page, plain_content: str) -> bool:
        """填写 CSDN 新版 Markdown/CodeMirror 编辑器。"""
        selectors = [
            ".CodeMirror",
            ".CodeMirror-scroll",
            ".cm-editor",
            '.cm-content[contenteditable="true"]',
            "textarea",
            '[contenteditable="true"]',
        ]
        for selector in selectors:
            try:
                editor = page.locator(selector).first
                if await editor.count() > 0 and await editor.is_visible(timeout=3000):
                    await editor.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.insert_text(plain_content)
                    await asyncio.sleep(0.5)
                    return True
            except Exception as exc:
                logger.debug(f"[CSDN] Markdown编辑器 {selector} 填充失败: {exc}")

        try:
            filled = await page.evaluate(
                """(text) => {
                    const selectors = [
                        '.CodeMirror textarea',
                        '.cm-content[contenteditable="true"]',
                        'textarea',
                        '[contenteditable="true"]'
                    ];
                    for (const selector of selectors) {
                        const target = document.querySelector(selector);
                        if (!target) continue;
                        target.focus();
                        if ('value' in target) {
                            target.value = text;
                        } else {
                            target.textContent = text;
                        }
                        target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
                        target.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                    return false;
                }""",
                plain_content,
            )
            return bool(filled)
        except Exception as exc:
            logger.debug(f"[CSDN] Markdown编辑器 JS 兜底失败: {exc}")
            return False

    async def _upload_images(self, page: Page, image_paths: List[str]) -> bool:
        """上传图片到CSDN"""
        try:
            for i, img_path in enumerate(image_paths[:50]):
                logger.info(f"📷 [CSDN] 上传第 {i + 1}/{len(image_paths)} 张图片...")

                uploaded = False
                try:
                    if await self._paste_image_via_clipboard(page, img_path):
                        uploaded = True
                        logger.success(f"✅ [CSDN] 第 {i + 1} 张图片已粘贴到正文编辑器")
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.debug(f"[CSDN] 正文粘贴图片失败: {e}")

                if not uploaded:
                    upload_buttons = [
                        'button[title*="图片"]',
                        'button[title*="图像"]',
                        'button[aria-label*="图片"]',
                        'button[aria-label*="图像"]',
                        '[class*="toolbar"] button:has-text("图像")',
                        '[class*="toolbar"] button:has-text("图片")',
                        'span:has-text("图像")',
                        'span:has-text("图片")',
                    ]
                    for selector in upload_buttons:
                        try:
                            trigger = page.locator(selector).first
                            if await trigger.count() > 0 and await trigger.is_visible(timeout=1500):
                                async with page.expect_file_chooser(timeout=3000) as chooser_info:
                                    await trigger.click()
                                chooser = await chooser_info.value
                                await chooser.set_files(img_path)
                                uploaded = True
                                logger.success(f"✅ [CSDN] 第 {i + 1} 张图片已通过上传按钮上传")
                                await asyncio.sleep(2)
                                break
                        except PlaywrightTimeoutError:
                            continue
                        except Exception as e:
                            logger.debug(f"[CSDN] 上传按钮 {selector} 失败: {e}")
                            continue

                if not uploaded:
                    logger.warning(f"⚠️ [CSDN] 第 {i + 1} 张图片未能插入正文，跳过该图以避免上传弹层挡住发布按钮")

        except Exception as e:
            logger.warning(f"⚠️ [CSDN] 图片上传流程异常: {e}")

        return True

    async def _paste_image_via_clipboard(self, page: Page, image_path: str) -> bool:
        """通过剪贴板粘贴图片"""
        try:
            with open(image_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            script = """(el, data) => {
                const { b64 } = data;
                const byteCharacters = atob(b64);
                const byteNumbers = new Array(byteCharacters.length);
                for (let i = 0; i < byteCharacters.length; i++) {
                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                }
                const byteArray = new Uint8Array(byteNumbers);
                const blob = new Blob([byteArray], { type: 'image/jpeg' });
                const file = new File([blob], "image.jpg", { type: 'image/jpeg' });
                const dt = new DataTransfer();
                dt.items.add(file);
                const target = el || document.activeElement || document.querySelector('.editor-view, .CodeMirror-scroll, .ql-editor, [contenteditable="true"], textarea');
                if (target) {
                    target.focus();
                    const event = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
                    target.dispatchEvent(event);
                    return true;
                }
                return false;
            }"""

            iframe_selectors = [
                "#cke_1_contents iframe",
                "#cke_2_contents iframe",
                "#cke_0_contents iframe",
                'div[id*="cke_"] iframe',
            ]
            for selector in iframe_selectors:
                try:
                    body = page.frame_locator(selector).locator("body")
                    if await body.count() > 0:
                        await body.click()
                        pasted = await body.evaluate(script, {"b64": b64_data})
                        if pasted:
                            return True
                except Exception:
                    continue

            target = page.locator(
                '.cm-content[contenteditable="true"], .CodeMirror-scroll, .editor-view, .ql-editor, [contenteditable="true"], textarea'
            ).first
            if await target.count() > 0:
                await target.click()
                return bool(await target.evaluate(script, {"b64": b64_data}))
            return False
        except Exception as e:
            logger.warning(f"[CSDN] 剪贴板粘贴图片失败: {e}")
            return False

    async def _click_publish(self, page: Page) -> bool:
        """点击发布按钮 — codegen 录制确认"""
        try:
            await page.keyboard.press("Escape")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # 先尝试最精确的底部按钮（录制确认）
        try:
            btn = page.get_by_role("button", name="发布博客").last
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                if await self._is_disabled(btn):
                    logger.warning("[CSDN] 发布博客按钮当前不可用，可能是标题/正文/标签尚未被页面识别")
                    return False
                await btn.click(force=True)
                logger.info("✅ [CSDN] 已点击发布博客按钮")
                await asyncio.sleep(2)
                return True
        except:
            pass
        try:
            btn = page.get_by_role("button", name="发布文章").last
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                if await self._is_disabled(btn):
                    logger.warning("[CSDN] 发布文章按钮当前不可用，可能是标题/正文/标签尚未被页面识别")
                    return False
                await btn.click(force=True)
                logger.info("✅ [CSDN] 已点击发布文章按钮")
                await asyncio.sleep(2)
                return True
        except:
            pass

        publish_selectors = [
            'button:has-text("发布博客")',
            'button:has-text("发布文章")',
            'button:has-text("立即发布")',
            'button:has-text("发布")',
            ".publish-btn",
            ".btn-publish",
        ]

        for selector in publish_selectors:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    if await self._is_disabled(btn):
                        logger.warning(f"[CSDN] 发布按钮不可用: {selector}")
                        return False
                    await btn.click(force=True)
                    logger.info("✅ [CSDN] 已点击发布按钮")
                    await asyncio.sleep(2)
                    return True
            except Exception as e:
                logger.debug(f"[CSDN] 发布按钮 {selector} 失败: {e}")
                continue

        return False

    async def _is_disabled(self, locator) -> bool:
        try:
            return bool(
                await locator.evaluate(
                    """(el) => {
                        const disabled = el.disabled
                            || el.getAttribute('disabled') !== null
                            || el.getAttribute('aria-disabled') === 'true'
                            || /disabled|is-disabled/.test(String(el.className || ''));
                        return disabled;
                    }"""
                )
            )
        except Exception:
            return False

    async def _add_tags(self, page: Page, tags: List[str]) -> None:
        """添加文章标签 — 使用文章关键词/蒸馏关键词，保持 2~3 个。"""
        tags = [tag for tag in tags if tag][:3]
        if not tags:
            return

        try:
            try:
                label = page.get_by_text("文章标签", exact=False).first
                if await label.count() > 0:
                    await label.scroll_into_view_if_needed(timeout=3000)
                    await asyncio.sleep(0.3)
            except Exception:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)

            # 点击"添加文章标签"按钮
            add_btn = page.get_by_role("button", name="添加文章标签").first
            if await add_btn.count() == 0:
                add_btn = page.locator('button:has-text("添加文章标签"), span:has-text("添加文章标签")').first
            if await add_btn.count() > 0:
                await add_btn.scroll_into_view_if_needed(timeout=3000)
                await add_btn.click()
                await asyncio.sleep(0.5)
            else:
                logger.warning("[CSDN] 未找到添加文章标签按钮")
                return

            # 逐个输入标签
            tag_input = page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签")
            if await tag_input.count() == 0:
                tag_input = page.locator(
                    'input[placeholder*="搜索"], input[placeholder*="标签"], input[placeholder*="Enter"]'
                ).first
            if await tag_input.count() == 0:
                logger.warning("[CSDN] 未找到文章标签输入框")
                return

            for tag in tags:
                await tag_input.click()
                await tag_input.fill("")
                await tag_input.fill(tag)
                await asyncio.sleep(0.3)
                await tag_input.press("Enter")
                await asyncio.sleep(0.5)

            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            logger.info(f"✅ [CSDN] 已添加标签: {tags}")
        except Exception as e:
            logger.warning(f"[CSDN] 添加标签失败: {e}")

    async def _wait_for_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）"""
        for i in range(60):  # 60次 × 2秒 = 120秒
            await self._close_unwanted_markdown_pages(page)
            current_url = page.url
            logger.debug(f"[CSDN] 第{(i + 1) * 2}秒, URL: {current_url}")
            if self._is_publish_success_url(current_url):
                logger.success(f"🎉 [CSDN] 检测到发布成功页: {current_url}")
                return {"success": True, "platform_url": current_url}

            manual_result = await self.ensure_publish_can_continue(page, "wait_result")
            if manual_result:
                return manual_result
            manual_result = await self._detect_manual_on_context_pages(page, "wait_result")
            if manual_result:
                return manual_result

            try:
                success_selectors = ["text=发布成功", "text=已发布", "text=保存成功"]
                for sel in success_selectors:
                    elem = page.locator(sel).first
                    if await elem.count() > 0 and await elem.is_visible(timeout=500):
                        logger.success("🎉 [CSDN] 检测到发布成功提示")
                        return {"success": True, "platform_url": page.url}
            except:
                pass

            if await self._click_publish_confirmation_if_present(page):
                await asyncio.sleep(2)
                continue

            await asyncio.sleep(2)

        logger.error(f"❌ [CSDN] 发布超时: {page.url}")
        return {"success": False, "error_msg": f"发布超时: {page.url}"}

    async def _detect_manual_on_context_pages(self, page: Page, stage: str) -> Dict[str, Any] | None:
        """Detect CSDN verification pages that may open outside the original editor tab."""
        for candidate in list(page.context.pages):
            if candidate == page or candidate.is_closed():
                continue
            try:
                if await self._looks_like_markdown_editor(candidate):
                    continue
                result = await self.ensure_publish_can_continue(candidate, stage)
                if result:
                    logger.warning(f"[CSDN] 在附加页面检测到人工验证: {candidate.url}")
                    return result
            except Exception as exc:
                logger.debug(f"[CSDN] 附加页面人工验证检测失败: {exc}")
        return None

    @staticmethod
    def _is_publish_success_url(url: str) -> bool:
        lowered = (url or "").lower()
        return "mp.csdn.net/mp_blog/creation/success/" in lowered

    async def _click_publish_confirmation_if_present(self, page: Page) -> bool:
        """Click the final publish confirmation only inside a visible dialog/drawer."""
        try:
            clicked = await page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                            && style.pointerEvents !== "none";
                    };
                    const scopes = Array.from(document.querySelectorAll([
                        "[role='dialog']",
                        ".el-dialog",
                        ".el-drawer",
                        "[class*='modal']",
                        "[class*='dialog']",
                        "[class*='drawer']"
                    ].join(","))).filter(visible);
                    const labels = ["确认发布", "立即发布", "发布文章", "发布博客", "发布"];
                    for (const scope of scopes) {
                        const buttons = Array.from(scope.querySelectorAll("button, [role='button']"))
                            .filter(visible);
                        const target = buttons.find((button) => {
                            const text = (button.innerText || button.textContent || "").replace(/\\s+/g, "").trim();
                            if (!labels.includes(text)) return false;
                            const disabled = button.disabled
                                || button.getAttribute("disabled") !== null
                                || button.getAttribute("aria-disabled") === "true"
                                || /disabled|is-disabled/.test(String(button.className || ""));
                            return !disabled;
                        });
                        if (target) {
                            target.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            if clicked:
                logger.info("[CSDN] 已点击发布确认弹窗按钮")
            return bool(clicked)
        except Exception as exc:
            logger.debug(f"[CSDN] 发布确认弹窗处理失败: {exc}")
            return False

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        """失败处理"""
        return {
            "success": False,
            "error_msg": f"[CSDN] {stage}失败: {msg}",
            "platform_url": page.url if page else None,
        }

    async def _manual_fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        """需要人工干预的处理"""
        return {
            "success": False,
            "platform_url": page.url if page else None,
            "error_msg": f"[CSDN] {stage}: {msg}",
            "requires_manual_intervention": True,
            "manual_intervention_stage": stage,
        }


# 注册CSDN发布器
CSDN_CONFIG = {
    "name": "CSDN",
    "publish_url": "https://mp.csdn.net/mp_blog/creation/editor",
    "color": "#FC5531",
    "version": "v1.1",
}
registry.register("csdn", CsdnPublisher("csdn", CSDN_CONFIG))
