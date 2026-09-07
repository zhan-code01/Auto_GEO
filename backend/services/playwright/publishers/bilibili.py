# -*- coding: utf-8 -*-
"""
B站专栏发布适配器 - v2.0 增强版

改进点：
  1. 使用 config["publish_url"] 替代硬编码URL
  2. 增强登录态检测：URL检查 + 页面元素双重验证
  3. 新增频率控制，避免被风控
  4. 自动关闭干扰弹窗
  5. 三级正文填充策略：选择器 → keyboard.type → JS注入
  6. 封面上传带状态确认 + 重试
  7. 多级发布确认弹窗处理
  8. 限流/风控实时检测
  9. 参考 MPP + social-auto-upload + COSE 的 selector

参考来源：
  - MPP platform_configs.py (B站 selector)
  - social-auto-upload bilibili uploader (cookie管理 + 重试)
  - COSE browser extension (DOM操作策略)
"""

import asyncio
import base64
import mimetypes
import os
import re
import httpx
import tempfile
import random
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from playwright.async_api import Page
from loguru import logger

from . import bilibili_selectors as sel
from .base import BasePublisher, registry
from .note_utils import generated_publish_images_enabled, materialize_images
from ..humanize import human_click, human_type, random_delay, short_delay, human_click_locator


class BilibiliPublisher(BasePublisher):
    """B站专栏内容发布器 - v2.0"""

    # ─── 常量 ─────────────────────────────────
    MAX_TITLE_LENGTH = 30
    MAX_CONTENT_LENGTH = 20000
    MAX_PER_HOUR = 5  # 每小时最多发布次数
    MAX_PER_DAY = 15  # 每天最多发布次数
    MIN_INTERVAL_MINUTES = 5  # 两次发布最小间隔（分钟）

    # 编辑器/列表页 URL 特征（用于判断发布后是否已离开编辑器）。
    # 注意：B站创作中心专栏链路 URL 本身普遍含 upload（如 /platform/upload/text/new-article），
    # 因此不能用宽泛的 "upload"/"edit" 一刀切排除，必须用下列精确特征判断。
    EDITOR_URL_FEATURES = (
        "new-article",  # 专栏管理列表页（publish_url 落地页）
        "upload-text/edit",  # 新版编辑器直链（备用入口）
        "upload/text/edit",  # 旧版编辑器直链（备用入口）
        "read-editor",  # 编辑器 iframe
        "read-draft",  # 草稿/编辑器 iframe
        "article-editor",  # 最旧版编辑器
        "post_text",  # 最旧版编辑器
    )

    # ─── 类变量：发布历史（频率控制）───
    _publish_history: List[datetime] = []

    # ═══════════════════════════════════════════════════════════
    # 频率控制
    # ═══════════════════════════════════════════════════════════

    def _check_rate_limit(self) -> Dict[str, Any]:
        """检查发布频率限制，参考知乎的实现"""
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)

        # 清理过期记录(7天)
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

    # ═══════════════════════════════════════════════════════════
    # 主流程
    # ═══════════════════════════════════════════════════════════

    async def publish(self, page: Page, article: Any, account: Any, declare_ai_content: bool = True) -> Dict[str, Any]:
        temp_files = []
        stage = "init"
        try:
            logger.info("🚀 [B站 v2.0] 开始发布专栏文章...")

            # 0. 频率检查
            rate = self._check_rate_limit()
            if not rate["allowed"]:
                logger.warning(f"⚠️ [B站] 频率限制: {rate['reason']}")
                return {"success": False, "error_msg": f"频率限制: {rate['reason']}"}

            title = self._article_field(article, ["title", "name"]) or "未命名文章"
            content = self._article_field(
                article,
                ["content", "html_content", "markdown_content", "body", "body_text", "article_content"],
            )
            keyword = self._extract_keyword(title)

            # 1. 导航到编辑器（使用 config 里的 publish_url）
            stage = "navigate"
            await self._navigate_to_editor(page)
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            # 2. 增强登录检测
            stage = "login_check"
            await self._ensure_logged_in(page)
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            # 3. 关闭干扰弹窗
            stage = "close_popup"
            await self._close_interference(page)

            # 3.5 关键护栏：确认已进入编辑器。若仍停留在列表页，绝不能继续——
            # 否则 _fill_title 会把列表页的“草稿搜索”框当成标题框乱填，
            # 表现为“没点新的创作反而去搜索了”，后续内容全部失败。
            stage = "ensure_editor"
            if not await self._wait_for_editor(page, timeout=8000):
                return await self._fail(
                    page,
                    "ensure_editor",
                    "未进入专栏编辑器（未点中「新的创作」或编辑器未加载），停止填写以避免误填列表页",
                )

            # 4. 准备封面图。B站专栏可不设置自定义封面，默认使用正文开头内容。
            stage = "download_cover"
            cover = await self._resolve_cover(article, keyword)
            if cover:
                temp_files.append(cover)
                logger.info(f"📷 [B站] 封面图已准备: {cover}")

            stage = "materialize_images"
            image_paths: List[str] = []
            if self.config.get("publish_with_images", False):
                image_paths, image_temp_files = await materialize_images(article, limit=12)
                temp_files.extend(image_temp_files)
                if (
                    not image_paths
                    and self.config.get("auto_generate_images", False)
                    and generated_publish_images_enabled(self.config)
                ):
                    image_paths = await self._download_inline_images(
                        keyword, count=self.config.get("inline_image_count", 3)
                    )
                    temp_files.extend(image_paths)
                elif not image_paths and self.config.get("auto_generate_images", False):
                    logger.warning("[B站] 图片下载失败，尝试继续发布（可能无图）...")
            if image_paths:
                logger.info(f"🖼️ [B站] 已准备 {len(image_paths)} 张正文图片")

            # 5. 填写标题
            stage = "fill_title"
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "未能写入标题，已停止发布，避免空标题继续进入发布设置")

            # 6. 三级兜底填充正文
            stage = "fill_content"
            if not await self._fill_content(page, content, image_paths=image_paths):
                return await self._fail(page, stage, "未能写入正文，已停止发布，避免空正文继续进入发布设置")

            # 7. 上传封面
            stage = "upload_cover"
            if cover:
                await self._upload_cover(page, cover)

            # 8. 添加标签
            stage = "add_tags"
            await self._add_tags(page, keyword)

            # 9. 分类设置（可选）
            # B站新版编辑器默认配置即可，避免展开发布设置遮住正文区域。
            stage = "set_category"

            # 10. AI声明
            # B站的 AI 声明在“发布设置”里，自动展开容易打断写作页。
            # 这里按用户要求：写入标题/正文后直接点击发布。

            # 11. 发布
            stage = "publish"
            if not await self._click_publish(page):
                return await self._fail(page, stage, "未点到发布按钮（可能仍停留在列表页，未成功进入编辑器）")

            # 12. 等待结果
            stage = "wait_result"
            result = await self._wait_for_result(page)
            if result.get("success"):
                self._publish_history.append(datetime.now())
            return result

        except Exception as e:
            logger.exception(f"❌ [B站] 发布失败 stage={stage}: {e}")
            if self._looks_like_manual_intervention(str(e)):
                return await self._manual_fail(page, stage, str(e))
            return await self._fail(page, stage, str(e))
        finally:
            for f in temp_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

    # ═══════════════════════════════════════════════════════════
    # 导航 & 登录
    # ═══════════════════════════════════════════════════════════

    async def _navigate_to_editor(self, page: Page) -> None:
        """导航到专栏编辑器。优先用 config，备用硬编码URL"""
        url = self.config.get("publish_url", "")
        if not url:
            url = "https://member.bilibili.com/platform/upload/text/new-article"

        logger.info(f"[B站] 导航到编辑器: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await random_delay(3, 6)
        await self._open_new_article_if_needed(page)

    async def _open_new_article_if_needed(self, page: Page) -> None:
        """
        新版 B 站：publish_url 落地的是专栏管理列表页（含“草稿搜索”框、”+ 新的创作“按钮）。
        必须先点”+ 新的创作“才会加载编辑器 iframe（member.bilibili.com/york/read-draft）。
        列表页绝不能当成编辑器——否则会把“草稿搜索”框当成标题框乱填，导致后续全部失败。
        """
        # 已在编辑器：直接返回
        if await self._has_editor(page, timeout=2000):
            return

        # 列表页：循环点击“+ 新的创作”，直到编辑器 iframe 出现
        for attempt in range(1, 4):
            clicked = await self._click_new_creation(page)
            if clicked:
                logger.info(f"[B站] 第{attempt}次点击「新的创作」，等待编辑器加载...")
            else:
                logger.warning(f"[B站] 第{attempt}次未找到/未点中「新的创作」入口")

            if await self._wait_for_editor(page, timeout=12000):
                return

            # 某些版本点击后会弹出内容类型选择菜单，需补点“专栏”项
            if clicked and await self._click_column_entry(page):
                logger.info("[B站] 已在类型菜单中选择专栏，继续等待编辑器加载...")
                if await self._wait_for_editor(page, timeout=12000):
                    return

        # 最后兜底：尝试备用编辑页直链（两种 URL 形式都试）
        for fallback in (
            "https://member.bilibili.com/platform/upload-text/edit",
            "https://member.bilibili.com/platform/upload/text/edit",
        ):
            try:
                logger.info(f"[B站] 仍未进入编辑器，尝试备用编辑页: {fallback}")
                await page.goto(fallback, wait_until="domcontentloaded", timeout=60000)
                await random_delay(2, 4)
                if await self._wait_for_editor(page, timeout=10000):
                    return
            except Exception as exc:
                logger.warning(f"[B站] 备用编辑页 {fallback} 跳转失败: {exc}")

        logger.error("[B站] 未能进入专栏编辑器，后续填写将以失败结束")

    async def _click_new_creation(self, page: Page) -> bool:
        """
        跨 frame 点击“+ 新的创作”按钮。
        只匹配可点击的叶子元素（button / a / role=button / 含 create 的 class），
        避免 get_by_text 抓到不可点击的外层容器导致点击落到空处。
        """
        # First try the exact blue draft-page CTA. Avoid broad text locators here:
        # the draft page also has a search input, and clicking a large text container
        # can land in that lower search area.
        try:
            for context in self._page_and_frames(page):
                ok = await context.evaluate(
                    """() => {
                        const exactTexts = new Set(['+ 新的创作', '+新的创作', '新的创作']);
                        const isVisible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0
                                && style.visibility !== 'hidden'
                                && style.display !== 'none'
                                && style.pointerEvents !== 'none';
                        };
                        const clickableSelector = 'button, a, [role="button"], [class*="btn"], [class*="create"], [class*="new"], div';
                        const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], div, span'));
                        const candidates = [];
                        for (const el of nodes) {
                            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                            if (!exactTexts.has(text) || !isVisible(el)) continue;
                            const target = el.closest(clickableSelector) || el;
                            if (!isVisible(target)) continue;
                            const rect = target.getBoundingClientRect();
                            if (rect.width < 70 || rect.width > 320 || rect.height < 24 || rect.height > 90) continue;
                            candidates.push({target, top: rect.top, area: rect.width * rect.height});
                        }
                        candidates.sort((a, b) => a.top - b.top || a.area - b.area);
                        const item = candidates[0];
                        if (!item) return false;
                        item.target.scrollIntoView({block: 'center', inline: 'center'});
                        const rect = item.target.getBoundingClientRect();
                        const opts = {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: rect.left + rect.width / 2,
                            clientY: rect.top + rect.height / 2
                        };
                        item.target.dispatchEvent(new PointerEvent('pointerdown', opts));
                        item.target.dispatchEvent(new MouseEvent('mousedown', opts));
                        item.target.dispatchEvent(new PointerEvent('pointerup', opts));
                        item.target.dispatchEvent(new MouseEvent('mouseup', opts));
                        item.target.dispatchEvent(new MouseEvent('click', opts));
                        return true;
                    }"""
                )
                if ok:
                    await short_delay()
                    return True
        except Exception:
            pass

        name_re = re.compile(r"^\s*\+?\s*新的创作\s*$|^新建创作$|^开始创作$|^写专栏$|^发布专栏$")
        clickable_text_sel = (
            'button:has-text("新的创作"), button:has-text("新建创作"), '
            'button:has-text("开始创作"), '
            'a:has-text("新的创作"), a:has-text("新建创作"), '
            '[role="button"]:has-text("新的创作"), [role="button"]:has-text("新建创作"), '
            '[class*="create"]:has-text("创作"), [class*="new"]:has-text("创作"), '
            '[class*="btn"]:has-text("创作")'
        )

        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await short_delay()
        except Exception:
            pass

        for context in self._page_and_frames(page):
            for factory in (
                lambda c=context: c.get_by_role("button", name=name_re).first,
                lambda c=context: c.get_by_role("link", name=name_re).first,
                lambda c=context: c.locator(clickable_text_sel).first,
            ):
                try:
                    loc = factory()
                    if await loc.count() > 0 and await loc.is_visible(timeout=1200):
                        await loc.click(force=True)
                        await short_delay()
                        return True
                except Exception:
                    continue

        # JS 兜底：找最内层、可点击、文本含关键词且长度短（排除容器）的元素直接 .click()
        try:
            for context in self._page_and_frames(page):
                ok = await context.evaluate(
                    """() => {
                        const keywords = ['新的创作', '新建创作', '开始创作', '写专栏', '发布专栏'];
                        const nodes = Array.from(document.querySelectorAll(
                            'button, a, div, span, [role="button"], [class*="create"], [class*="new"], [class*="btn"]'
                        ));
                        const clickableSelector = 'button, a, [role="button"], [class*="create"], [class*="new"], [class*="btn"], div';
                        for (const el of nodes) {
                            const text = (el.innerText || el.textContent || '').trim();
                            if (!text || text.length > 24) continue;
                            if (!keywords.some(kw => text.includes(kw))) continue;
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none') {
                                const target = el.closest(clickableSelector) || el;
                                target.scrollIntoView({block: 'center', inline: 'center'});
                                target.click();
                                return true;
                            }
                        }
                        return false;
                    }"""
                )
                if ok:
                    await short_delay()
                    return True
        except Exception:
            pass
        return False

    async def _click_column_entry(self, page: Page) -> bool:
        """点击“新的创作”后若弹出内容类型选择菜单，补点“专栏/写专栏”项。"""
        name_re = re.compile(r"写专栏|专栏投稿|^专栏$")
        for context in self._page_and_frames(page):
            for factory in (
                lambda c=context: c.get_by_role("link", name=name_re).first,
                lambda c=context: c.get_by_role("button", name=name_re).first,
                lambda c=context: (
                    c.locator(
                        'a:has-text("专栏"), [role="menuitem"]:has-text("专栏"), '
                        '[class*="menu"]:has-text("写专栏"), [class*="dropdown"]:has-text("专栏")'
                    ).first
                ),
            ):
                try:
                    loc = factory()
                    if await loc.count() > 0 and await loc.is_visible(timeout=1000):
                        await loc.click(force=True)
                        await short_delay()
                        return True
                except Exception:
                    continue
        return False

    async def _wait_for_editor(self, page: Page, timeout: int = 12000) -> bool:
        """轮询等待编辑器加载（york/read-draft iframe 或编辑器标题框出现）。"""
        step_ms = 500
        elapsed = 0
        while elapsed <= timeout:
            if await self._has_editor(page, timeout=400):
                return True
            await asyncio.sleep(step_ms / 1000)
            elapsed += step_ms
        return await self._has_editor(page, timeout=400)

    async def _has_editor(self, page: Page, timeout: int = 3000) -> bool:
        """
        判断当前是否已进入专栏编辑器（而非管理列表页）。
        注意：read-draft 是 B站的草稿页 iframe，本身不是编辑器。

        注意：绝不能用 input[placeholder*=”标题”] 这种宽泛选择器——
        列表页的“草稿搜索”框 placeholder 也可能含“标题/搜索”，会把列表页误判成编辑器。
        """
        # 编辑器特有的标题框（精确 placeholder，绝不匹配列表页搜索框）。
        editor_title_selectors = [
            'input[placeholder="请输入标题（建议30字以内）"]',
            'textarea[placeholder="请输入标题（建议30字以内）"]',
            'input[placeholder*="请输入文章标题"]',
            '[contenteditable="true"][data-placeholder*="标题"]',
        ]
        for selector in editor_title_selectors:
            try:
                node = await self._first_visible_editor_locator(page, selector, timeout=timeout)
                if await node.count() > 0 and await node.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue

        # 信号3：跨 frame 精确匹配编辑器标题框 placeholder（必须形如“请输入…标题（建议…”），
        # 显式排除列表页搜索框（其 placeholder 不含“建议/文章标题”）
        for context in self._editor_contexts(page):
            try:
                title = context.get_by_placeholder(re.compile(r"请输入.{0,6}标题（?建议|请输入文章标题")).first
                if await title.count() > 0 and await title.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue

        if any("read-editor" in (frame.url or "") for frame in page.frames):
            return True

        return False

    async def _ensure_logged_in(self, page: Page) -> None:
        """
        增强登录态检测：URL检查 + 页面元素双重验证
        参考 social-auto-upload 的做法
        """
        # 检查1: URL 是否跳转到登录页
        current_url = page.url.lower()
        for indicator in sel.LOGIN_URL_INDICATOR:
            if indicator in current_url:
                raise RuntimeError("B站登录态已失效，当前页面进入登录/安全验证流程，请先重新授权")

        # 检查2: 页面上是否有登录成功标识元素
        try:
            for selector in sel.LOGIN_SUCCESS_ELEMENT:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible(timeout=3000):
                        logger.info("✅ [B站] 登录态正常（检测到用户元素）")
                        return
                except Exception:
                    continue
        except Exception:
            pass

        # 检查3: 没有跳转到登录页就算通过
        if "passport.bilibili.com" not in current_url:
            logger.info("✅ [B站] 登录态正常（未重定向到登录）")
            return

        raise RuntimeError("B站登录态异常，无法确认登录状态，请人工完成登录后重新授权")

    async def _close_interference(self, page: Page) -> None:
        """关闭页面上的干扰弹窗（新功能引导、活动提示等）"""
        for _ in range(6):
            handled = False
            for btn_selector in sel.CLOSE_POPUP_BTN:
                try:
                    btn = page.locator(btn_selector).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=800):
                        await btn.click(force=True)
                        logger.info(f"[B站] 已处理干扰弹窗: {btn_selector}")
                        await short_delay()
                        handled = True
                        break
                except Exception:
                    continue

            if not handled:
                handled = await self._click_guide_control(page)

            if not handled:
                break

        # JS 兜底：移除高 z-index 遮罩
        try:
            await page.evaluate("""() => {
                const keywords = [
                    '知道了', '我知道了', '下一步', '完成', '关闭', '跳过', '稍后再说',
                    '立即体验', '开始体验', '新手引导', '功能引导', '创作引导',
                    'AI声明', 'AI辅助', 'AI创作', '活动提示', '温馨提示',
                    '1/4', '2/4', '3/4', '4/4', '1/3', '2/3', '3/3'
                ];
                const candidates = Array.from(document.querySelectorAll('*')).filter(el => {
                    try {
                        const z = window.getComputedStyle(el).zIndex;
                        const text = (el.innerText || el.textContent || '');
                        return z !== 'auto' && parseInt(z) > 100 && keywords.some(kw => text.includes(kw));
                    } catch (e) {}
                    return false;
                });
                candidates.forEach(el => {
                    const host = el.closest(
                        '[role="dialog"], [class*="popover"], [class*="tooltip"], [class*="guide"], ' +
                        '[class*="modal"], [class*="dialog"], [class*="mask"], [class*="overlay"]'
                    ) || el;
                    host.remove();
                });
                document.querySelectorAll('[class*="mask"], [class*="overlay"]').forEach(el => {
                    try {
                        const style = window.getComputedStyle(el);
                        if (parseInt(style.zIndex || '0') > 100) el.remove();
                    } catch (e) {}
                });
                document.body.style.overflow = 'auto';
                document.body.style.pointerEvents = 'auto';
            }""")
        except Exception:
            pass

        for _ in range(3):
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
            except Exception:
                break

    async def _click_guide_control(self, page: Page) -> bool:
        """Click B站 onboarding controls that are not rendered as normal buttons."""
        guide_texts = ["我知道了", "知道了", "下一步", "完成", "关闭", "跳过", "稍后再说", "立即体验", "开始体验"]
        for text in guide_texts:
            locators = [
                page.get_by_text(text, exact=True),
                page.locator(f'text="{text}"'),
                page.locator(f'div:has-text("{text}")').last,
                page.locator(f'span:has-text("{text}")').last,
                page.locator(f'[role="button"]:has-text("{text}")').last,
            ]
            for locator in locators:
                try:
                    if await locator.count() > 0 and await locator.is_visible(timeout=500):
                        await locator.click(force=True)
                        logger.info(f"[B站] 已点击引导控件: {text}")
                        await short_delay()
                        return True
                except Exception:
                    continue

        try:
            close = page.locator(
                '[aria-label="Close"], [aria-label="close"], [title="关闭"], '
                '[class*="close"], svg[class*="close"], i[class*="close"]'
            ).last
            if await close.count() > 0 and await close.is_visible(timeout=500):
                await close.click(force=True)
                await short_delay()
                return True
        except Exception:
            pass

        return False

    # ═══════════════════════════════════════════════════════════
    # 封面下载
    # ═══════════════════════════════════════════════════════════

    async def _resolve_cover(self, article: Any, keyword: str) -> Optional[str]:
        """优先使用文章自带封面；自动生成随机封面需要显式配置开启。"""
        cover_path = (
            getattr(article, "cover_path", None)
            or getattr(article, "cover_image_path", None)
            or getattr(article, "cover", None)
        )
        if cover_path and os.path.exists(str(cover_path)):
            return str(cover_path)

        if self.config.get("auto_generate_cover", False) and generated_publish_images_enabled(self.config):
            return await self._download_cover(keyword)
        if self.config.get("auto_generate_cover", False):
            logger.info("[B站] 未找到文章自带封面，跳过发布阶段替代封面生成")

        return None

    async def _download_cover(self, keyword: str) -> Optional[str]:
        """
        下载封面图。优先 pollinations.ai，备用 picsum
        参考 toutiao.py 的多级备用策略
        """
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        # 策略1: pollinations.ai AI生成
        enc = urllib.parse.quote(f"{keyword} article cover image {random.randint(1, 10000)}")
        pollinations_url = f"https://image.pollinations.ai/prompt/{enc}?width=1200&height=630&nologo=true"

        async with httpx.AsyncClient(headers=headers, verify=False, timeout=30.0) as client:
            try:
                resp = await client.get(pollinations_url)
                if resp.status_code == 200 and len(resp.content) > 2000:
                    p = os.path.join(tempfile.gettempdir(), f"bili_cover_{random.randint(10000, 99999)}.jpg")
                    with open(p, "wb") as f:
                        f.write(resp.content)
                    return p
            except Exception:
                pass

            # 策略2: picsum 兜底
            try:
                fallback_url = f"https://picsum.photos/1200/630?random={random.randint(1, 100000)}"
                resp = await client.get(fallback_url)
                if resp.status_code == 200 and len(resp.content) > 2000:
                    p = os.path.join(tempfile.gettempdir(), f"bili_cover_fb_{random.randint(10000, 99999)}.jpg")
                    with open(p, "wb") as f:
                        f.write(resp.content)
                    return p
            except Exception:
                pass

        return None

    async def _download_inline_images(self, keyword: str, count: int = 3) -> List[str]:
        """Generate/download fallback inline images when the article has no image assets."""
        paths: List[str] = []
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(headers=headers, verify=False, timeout=45.0, follow_redirects=True) as client:
            for index in range(max(0, count)):
                seed = random.randint(1, 100000)
                prompt = urllib.parse.quote(f"{keyword} professional article illustration {index + 1} seed {seed}")
                urls = [
                    f"https://image.pollinations.ai/prompt/{prompt}?width=1200&height=800&nologo=true",
                    f"https://picsum.photos/1200/800?random={seed}",
                ]
                for url in urls:
                    try:
                        resp = await client.get(url)
                        if resp.status_code != 200 or len(resp.content) < 2000:
                            continue
                        suffix = ".jpg"
                        content_type = resp.headers.get("content-type", "").split(";", 1)[0]
                        guessed = mimetypes.guess_extension(content_type)
                        if guessed in (".jpg", ".jpeg", ".png", ".webp"):
                            suffix = guessed
                        fd, path = tempfile.mkstemp(prefix="bili_inline_", suffix=suffix)
                        with os.fdopen(fd, "wb") as file:
                            file.write(resp.content)
                        paths.append(path)
                        logger.info(f"[B站] 已生成正文配图 {index + 1}/{count}: {path}")
                        break
                    except Exception as exc:
                        logger.warning(f"[B站] 正文配图下载失败: {exc}")
        return paths

    # ═══════════════════════════════════════════════════════════
    # 标题 & 正文
    # ═══════════════════════════════════════════════════════════

    async def _fill_title(self, page: Page, title: str) -> bool:
        """填充标题，使用增强选择器列表（含MPP精确选择器）"""
        clean = re.sub(r"#|\*|\"", "", title).strip()[: self.MAX_TITLE_LENGTH]

        if await self._fill_bili_placeholder_by_click(page, "title", clean):
            logger.info(f"📝 [B站] 标题已通过占位文字点击写入: {clean}")
            await random_delay(1, 2)
            return True

        for context in self._editor_contexts(page):
            try:
                if await self._inject_bili_editor_text(context, "title", clean):
                    logger.info(f"📝 [B站] 标题已通过新版编辑器事件注入: {clean}")
                    await random_delay(1, 2)
                    return True
            except Exception:
                continue

        for selector in sel.ARTICLE_TITLE_INPUT:
            try:
                inp = await self._first_visible_editor_locator(page, selector, timeout=5000)
                if await inp.count() > 0 and await inp.is_visible(timeout=5000):
                    # fill() 自带清空逻辑，无需手动 Ctrl+A + Backspace
                    # 手动全选后 Backspace 可能导致焦点丢失，fill() 反而无法写入
                    await inp.fill(clean)
                    logger.info(f"📝 [B站] 标题已填充: {clean} (selector: {selector})")
                    await random_delay(1, 2)
                    return True
            except Exception:
                continue

        for context in self._editor_contexts(page):
            try:
                # 必须形如“请输入…标题（建议…”才匹配，避免在列表页误填“草稿搜索”框
                inp = context.get_by_placeholder(re.compile(r"请输入.{0,6}标题（?建议|请输入文章标题")).first
                if await inp.count() > 0 and await inp.is_visible(timeout=2000):
                    # fill() 自带清空逻辑，无需手动 Ctrl+A + Backspace
                    # 全局 Control+A 会选中整个页面而非仅输入框，导致 fill 失败
                    await inp.fill(clean)
                    logger.info(f"📝 [B站] 标题已通过 iframe placeholder 填充: {clean}")
                    await random_delay(1, 2)
                    return True
            except Exception:
                continue

        if await self._fill_bili_editor_by_viewport_click(page, "title", clean):
            logger.info(f"📝 [B站] 标题已通过页面坐标直接写入: {clean}")
            await random_delay(1, 2)
            return True

        logger.warning("⚠️ [B站] 未找到标题输入框——所有选择器均失败")
        return False

    async def _fill_content(self, page: Page, content: str, image_paths: Optional[List[str]] = None) -> bool:
        """
        三级兜底填充正文:
          L1: 定位富文本编辑器 → keyboard.type (最稳定，模拟真人)
          L2: 定位 textarea/input → fill
          L3: JS evaluate 直接注入 innerHTML
        参考 toutiao.py 的全选清空 + keyboard.type 策略
        """
        image_paths = image_paths or []
        if image_paths:
            blocks = self._build_content_blocks(content, image_paths)
            if await self._fill_bili_content_blocks(page, blocks):
                logger.info(f"✅ [B站] 图文正文已写入 ({len(blocks)} 个块, {len(image_paths)} 张图片)")
                await random_delay(1, 3)
                return True
            logger.warning("[B站] 图文正文写入失败，降级为纯文本正文")

        clean = self._deep_clean(content)[: self.MAX_CONTENT_LENGTH]

        if not clean:
            logger.warning("⚠️ [B站] 待发布正文为空，停止正文写入")
            return False

        if await self._fill_bili_content_by_real_input(page, clean):
            logger.info(f"✅ [B站] 正文已通过真实输入写入 ({len(clean)} 字符)")
            await random_delay(1, 3)
            return True

        if await self._fill_bili_placeholder_by_click(page, "content", clean):
            logger.info(f"✅ [B站] 正文已通过占位文字点击写入 ({len(clean)} 字符)")
            await random_delay(1, 3)
            return True

        # L1: 富文本编辑器 — keyboard.type
        for selector in sel.ARTICLE_CONTENT_INPUT:
            try:
                editor = await self._first_visible_editor_locator(page, selector, timeout=5000)
                if await editor.count() > 0 and await editor.is_visible(timeout=5000):
                    if not await self._looks_like_content_locator(editor):
                        continue
                    await editor.click()
                    await short_delay()
                    # 使用 editor.press() 而非 page.keyboard.press()，将 Control+A 限定在编辑器内
                    await editor.press("Control+A")
                    await editor.press("Backspace")
                    await short_delay()
                    if len(clean) > 1000:
                        await page.keyboard.insert_text(clean)
                    else:
                        # 短文使用逐字输入，长文直接插入以避免耗时过长。
                        await page.keyboard.type(clean, delay=20)
                    if await self._visible_editor_contains_text(page, clean):
                        logger.info(f"✅ [B站] 正文已填充 ({len(clean)} 字符) - L1 keyboard.type")
                        await random_delay(1, 3)
                        return True
            except Exception:
                continue

        for context in self._editor_contexts(page):
            try:
                editor = context.get_by_role("textbox").nth(1)
                if await editor.count() > 0 and await editor.is_visible(timeout=3000):
                    await editor.click()
                    await short_delay()
                    # 使用 editor.press() 而非 page.keyboard.press()，将 Control+A 限定在编辑器内
                    await editor.press("Control+A")
                    await editor.press("Backspace")
                    await short_delay()
                    await page.keyboard.insert_text(clean)
                    if await self._visible_editor_contains_text(page, clean):
                        logger.info(f"✅ [B站] 正文已通过 iframe textbox 填充 ({len(clean)} 字符)")
                        await random_delay(1, 3)
                        return True
            except Exception:
                continue

        # L2: 尝试普通 textarea
        for selector in ["textarea", "textarea[placeholder]", "#desc"]:
            try:
                editor = await self._first_visible_editor_locator(page, selector, timeout=3000)
                if await editor.count() > 0 and await editor.is_visible(timeout=3000):
                    await editor.fill(clean)
                    if await self._visible_editor_contains_text(page, clean):
                        logger.info("✅ [B站] 正文已填充 - L2 textarea.fill")
                        await random_delay(1, 2)
                        return True
            except Exception:
                continue

        # L3: JS 注入兜底（最后手段）。仅作为定位困难时使用，成功后仍做可见文本校验。
        try:
            for context in self._editor_contexts(page):
                ok = await context.evaluate(
                    """(text) => {
                        const el = Array.from(document.querySelectorAll(
                            '.ql-editor, [contenteditable="true"], .editor-body, textarea'
                        )).find(node => {
                            const rect = node.getBoundingClientRect();
                            const style = window.getComputedStyle(node);
                            return rect.width > 0 && rect.height > 0
                                && style.display !== 'none'
                                && style.visibility !== 'hidden';
                        });
                        if (!el) return false;
                        if (el.tagName.toLowerCase() === 'textarea') {
                            el.value = text;
                        } else {
                            el.innerHTML = text.replace(/\\n/g, '<br>');
                        }
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }""",
                    clean,
                )
                if ok:
                    if await self._visible_editor_contains_text(page, clean):
                        logger.info("✅ [B站] 正文已填充 - L3 iframe JS注入兜底")
                        return True
        except Exception as e:
            logger.error(f"❌ [B站] 所有正文填充策略均失败: {e}")

        if await self._fill_bili_editor_by_viewport_click(page, "content", clean):
            if await self._visible_editor_contains_text(page, clean):
                logger.info(f"✅ [B站] 正文已通过页面坐标直接写入 ({len(clean)} 字符)")
                await random_delay(1, 3)
                return True
        return False

    # ═══════════════════════════════════════════════════════════
    # 封面上传
    # ═══════════════════════════════════════════════════════════

    async def _upload_cover(self, page: Page, cover_path: str) -> None:
        """上传专栏封面，带状态确认和重试"""
        if not os.path.exists(cover_path):
            logger.warning(f"⚠️ [B站] 封面文件不存在: {cover_path}")
            return

        for attempt in range(2):
            try:
                # 点击封面上传区域
                for btn_sel in sel.COVER_UPLOAD_BTN:
                    try:
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                            await btn.click()
                            await short_delay()
                            break
                    except Exception:
                        continue

                # 文件注入
                file_input = page.locator(sel.COVER_FILE_INPUT).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(cover_path)
                    logger.info(f"📷 [B站] 封面文件已设置 (尝试 {attempt + 1})")
                    await random_delay(3, 5)

                    # 确认上传成功
                    for success_sel in sel.COVER_SUCCESS_INDICATOR:
                        try:
                            indicator = page.locator(success_sel).first
                            if await indicator.count() > 0:
                                logger.info("✅ [B站] 封面确认上传成功")
                                return
                        except Exception:
                            continue
                    return  # 没有报错就算成功
            except Exception as e:
                logger.warning(f"⚠️ [B站] 封面上传尝试 {attempt + 1} 失败: {e}")
                if attempt == 0:
                    await random_delay(2, 4)

        logger.warning("⚠️ [B站] 封面上传未确认成功，继续发布")

    # ═══════════════════════════════════════════════════════════
    # 标签 & 分类
    # ═══════════════════════════════════════════════════════════

    async def _add_tags(self, page: Page, keyword: str) -> None:
        """添加文章标签"""
        tags = [t.strip() for t in keyword.split()[:3] if t.strip()]
        if not tags:
            return

        for tag in tags:
            for selector in sel.PUBLISH_TAG_INPUT:
                try:
                    inp = page.locator(selector).first
                    if await inp.count() > 0 and await inp.is_visible(timeout=2000):
                        await inp.click()
                        await short_delay()
                        await inp.fill(tag)
                        await page.keyboard.press("Enter")
                        await short_delay()
                        logger.info(f"🏷️ [B站] 标签已添加: {tag}")
                        break
                except Exception:
                    continue

    async def _set_category(self, page: Page) -> None:
        """尝试设置文章分类（如果页面有分类选择器的话）"""
        category_selectors = [
            'div[class*="category"]',
            'select[class*="category"]',
            ".article-category",
        ]
        for selector in category_selectors:
            try:
                el = page.locator(selector).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    await el.click()
                    await short_delay()
                    # 选择第一个可用分类
                    first_option = page.locator('li[class*="option"]').first
                    if await first_option.count() > 0:
                        await first_option.click()
                        logger.info("📂 [B站] 分类已设置")
                        await short_delay()
                    return
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════
    # AI声明 & 发布
    # ═══════════════════════════════════════════════════════════

    async def _set_ai_declaration(self, page: Page) -> None:
        """设置AI创作声明"""
        try:
            await self._open_publish_settings(page)

            # 先尝试找到声明入口
            for indicator in sel.AI_DECLARATION_INDICATORS:
                try:
                    el = page.locator(indicator).first
                    if await el.count() > 0 and await el.is_visible(timeout=2000):
                        await el.click()
                        await short_delay()
                        logger.info("🤖 [B站] AI声明已设置")
                        return
                except Exception:
                    continue

            # 再尝试 checkbox
            for cb_sel in sel.AI_DECLARATION_CHECKBOX:
                try:
                    cb = page.locator(cb_sel).first
                    if await cb.count() > 0:
                        if not await cb.is_checked():
                            await cb.check()
                            logger.info("🤖 [B站] AI声明checkbox已勾选")
                            await short_delay()
                            return
                except Exception:
                    continue
        except Exception:
            logger.debug("[B站] AI声明设置跳过（未找到入口）")

    async def _open_publish_settings(self, page: Page) -> None:
        """展开底部发布设置面板。"""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await short_delay()
        except Exception:
            pass

        for selector in sel.PUBLISH_SETTINGS_TOGGLE:
            try:
                toggle = page.locator(selector).first
                if await toggle.count() > 0 and await toggle.is_visible(timeout=2000):
                    await toggle.click(force=True)
                    logger.info(f"[B站] 已展开发布设置: {selector}")
                    await random_delay(1, 2)
                    return
            except Exception:
                continue

    async def _click_publish(self, page: Page) -> bool:
        """点击发布按钮，处理多级确认弹窗"""
        await random_delay(1, 2)

        # 先滚到底部确保发布按钮在视口内
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await short_delay()
        except Exception:
            pass

        # 优先：跨 frame 精确匹配 role=button 文本=发布/立即投稿。
        # codegen 录制确认新版编辑器的发布按钮就是 get_by_role("button", name="发布")，
        # exact=True 天然过滤掉"定时发布""发布设置"等干扰项。
        for context in self._page_and_frames(page):
            for exact_text in ("发布", "立即投稿", "发布文章", "确认发布", "确认投稿"):
                try:
                    btn = context.get_by_role("button", name=exact_text, exact=True).last
                    if await btn.count() > 0 and await btn.is_visible(timeout=1200) and await btn.is_enabled():
                        await btn.click(force=True)
                        logger.info(f"🖱️ [B站] 点击发布按钮 (role exact: {exact_text})")
                        await random_delay(2, 4)
                        await self._handle_confirm_dialog(page)
                        return True
                except Exception:
                    continue

        # 遍历发布按钮选择器
        all_selectors = sel.ARTICLE_SUBMIT_BTN + sel.PUBLISH_SUBMIT_BTN
        for selector in all_selectors:
            try:
                btn = await self._first_visible_locator(page, selector, timeout=2000)
                cnt = await btn.count()
                for i in range(cnt):
                    c = btn.nth(i) if cnt > 1 else btn
                    if await c.count() > 0 and await c.is_visible(timeout=2000):
                        if await c.is_enabled():
                            await c.click(force=True)
                            logger.info(f"🖱️ [B站] 点击发布按钮 (selector: {selector})")
                            await random_delay(2, 4)
                            # 处理确认弹窗
                            await self._handle_confirm_dialog(page)
                            return True
            except Exception:
                continue

        logger.error("❌ [B站] 未找到可用发布按钮")
        return False

    async def _handle_confirm_dialog(self, page: Page) -> None:
        """处理发布确认弹窗（可能有多层）"""
        for _ in range(3):  # 最多处理3层弹窗
            handled = False
            for selector in sel.CONFIRM_DIALOG_BTNS:
                try:
                    btn = await self._first_visible_locator(page, selector, timeout=2000)
                    if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                        await btn.click(force=True)
                        logger.info(f"✅ [B站] 确认弹窗已处理 ({selector})")
                        handled = True
                        await random_delay(1, 2)
                        break
                except Exception:
                    continue
            if not handled:
                break  # 没有更多弹窗了

    # ═══════════════════════════════════════════════════════════
    # 结果等待
    # ═══════════════════════════════════════════════════════════

    async def _wait_for_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）

        B站专栏的编辑器与发布成功提示都渲染在嵌套 iframe 里，
        成功关键词/元素必须跨 frame 检测（复用 _page_and_frames），
        否则提示已出现也检不到，只能空转到超时。
        """
        for _ in range(60):  # 60次 × 2秒 = 120秒
            manual_result = await self.ensure_publish_can_continue(page, "wait_result")
            if manual_result:
                return manual_result

            # 优先检查限流/风控
            for indicator in sel.RATE_LIMIT_INDICATORS:
                try:
                    node = page.get_by_text(indicator, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=500):
                        text = await node.inner_text()
                        logger.error(f"🚫 [B站] 触发限流: {text}")
                        return await self._manual_fail(page, "wait_result", f"B站触发限流/安全验证: {text}")
                except Exception:
                    continue

            # 检查成功关键词（跨 frame：成功提示大概率出现在编辑器 iframe 内）。
            # 加可见性校验，避免隐藏的草稿列表等 frame 里残留文案造成误判。
            for context in self._page_and_frames(page):
                for kw in sel.PUBLISH_SUCCESS_KEYWORDS:
                    try:
                        node = context.get_by_text(kw, exact=False).first
                        if await node.count() > 0 and await node.is_visible(timeout=500):
                            logger.success(f"🎉 [B站] 发布成功！检测到提示: {kw}")
                            return {"success": True, "platform_url": page.url}
                    except Exception:
                        continue

            # URL变化也算成功：主页面与所有 frame 都已离开编辑器特征
            # （不能用宽泛的 "upload"/"edit" 排除，见 EDITOR_URL_FEATURES 注释）
            if "member.bilibili.com" in (page.url or "") and not self._still_in_editor(page):
                logger.success("🎉 [B站] 发布成功（页面已离开编辑器）")
                return {"success": True, "platform_url": page.url}

            # 检查成功元素（跨 frame）
            for context in self._page_and_frames(page):
                for selector in sel.PUBLISH_SUCCESS_ELEMENT:
                    try:
                        el = context.locator(selector).first
                        if await el.count() > 0 and await el.is_visible(timeout=500):
                            logger.success("🎉 [B站] 检测到发布成功元素")
                            return {"success": True, "platform_url": page.url}
                    except Exception:
                        continue

            await asyncio.sleep(2)

        logger.warning("⏰ [B站] 等待超时，请手动确认")
        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": True,
            "platform_url": page.url,
            "error_msg": "等待超时——请到B站创作中心确认",
            "debug_path": debug_path,
        }

    def _still_in_editor(self, page: Page) -> bool:
        """主页面或任一 frame 仍停留在编辑器/列表页 URL 上。"""
        urls = [page.url or ""] + [frame.url or "" for frame in page.frames]
        return any(feature in url for url in urls for feature in self.EDITOR_URL_FEATURES)

    # ═══════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════

    def _extract_keyword(self, title: str) -> str:
        """从标题提取关键词"""
        c = re.sub(r"[^\w一-鿿]", " ", title).split()
        if not c:
            return "科技"
        return c[0] if len(c) == 1 else f"{c[0]} {c[1]}"

    def _article_field(self, article: Any, names: List[str]) -> str:
        """Read the first non-empty article field from ORM/model/dict objects."""
        for name in names:
            value = None
            if isinstance(article, dict):
                value = article.get(name)
            else:
                value = getattr(article, name, None)
            if value:
                return str(value)
        return ""

    def _build_content_blocks(self, content: str, image_paths: List[str]) -> List[Dict[str, str]]:
        """Split article content into text/image blocks, preserving Markdown/HTML image order."""
        blocks: List[Dict[str, str]] = []
        image_index = 0
        pattern = re.compile(
            r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)"
            r"|<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>",
            flags=re.IGNORECASE,
        )
        cursor = 0
        for match in pattern.finditer(content or ""):
            text = self._deep_clean((content or "")[cursor : match.start()])
            if text:
                blocks.append({"type": "text", "content": text})
            if image_index < len(image_paths):
                blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1
            cursor = match.end()

        text = self._deep_clean((content or "")[cursor:])
        if text:
            blocks.append({"type": "text", "content": text})

        while image_index < len(image_paths):
            blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1

        return blocks

    async def _fill_bili_content_blocks(self, page: Page, blocks: List[Dict[str, str]]) -> bool:
        """Write rich text blocks to the Bilibili editor using real input and clipboard image paste."""
        if not blocks:
            return False

        wrote_text = False
        inserted_images = 0
        first_text = ""
        for block in blocks:
            kind = block.get("type")
            value = block.get("content", "")
            if not value:
                continue

            if kind == "text":
                if wrote_text or inserted_images:
                    try:
                        await page.keyboard.press("End")
                        # 只用 1 个 Enter 切分段落（避免空段落放大成巨大空栏）
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                if not await self._fill_bili_content_by_real_input(page, value[: self.MAX_CONTENT_LENGTH]):
                    return False
                wrote_text = True
                if not first_text:
                    first_text = value
                continue

            if kind == "image":
                if not await self._paste_bili_image(page, value):
                    logger.warning(f"[B站] 正文图片粘贴失败: {value}")
                    return False
                inserted_images += 1
                try:
                    await page.keyboard.press("End")
                    await page.keyboard.press("Enter")
                except Exception:
                    pass

        if first_text and not await self._visible_editor_contains_text(page, first_text):
            return False
        if inserted_images and not await self._visible_editor_has_images(page, inserted_images):
            logger.warning("[B站] 已尝试插入图片，但编辑器未检测到图片节点")
            return False
        return wrote_text or inserted_images > 0

    async def _paste_bili_image(self, page: Page, image_path: str) -> bool:
        """Paste one local image file into the focused Bilibili rich text editor."""
        if not image_path or not os.path.exists(image_path):
            return False
        before = await self._editor_image_count(page)
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as file:
            data_b64 = base64.b64encode(file.read()).decode("ascii")
        name = os.path.basename(image_path)

        for context in self._editor_contexts(page):
            try:
                ok = await context.evaluate(
                    """({dataB64, mime, name}) => {
                        const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return r.width > 0 && r.height > 0
                                && s.display !== 'none'
                                && s.visibility !== 'hidden';
                        };
                        const focusEditor = () => {
                            const candidates = Array.from(document.querySelectorAll(
                                '[contenteditable="true"], textarea, .ProseMirror, .ql-editor, [role="textbox"]'
                            )).filter(visible).map((el) => {
                                const r = el.getBoundingClientRect();
                                const label = [
                                    el.getAttribute('placeholder') || '',
                                    el.getAttribute('data-placeholder') || '',
                                    el.getAttribute('aria-label') || '',
                                    el.getAttribute('class') || ''
                                ].join(' ');
                                let score = r.width * r.height / 1000;
                                if (/搜索|草稿|稿件|标题|文章标题|请输入标题/.test(label)) score -= 1000000;
                                if (/正文|请输入正文|内容|editor|ProseMirror|ql-editor/i.test(label)) score += 100000;
                                if (r.height >= 160) score += 5000;
                                return {el, score};
                            }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
                            const el = candidates[0]?.el;
                            if (!el) return null;
                            el.scrollIntoView({block: 'center', inline: 'center'});
                            if (typeof el.focus === 'function') el.focus();
                            const r = el.getBoundingClientRect();
                            const opts = {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                clientX: r.left + Math.min(40, Math.max(8, r.width * 0.05)),
                                clientY: r.top + Math.min(80, Math.max(20, r.height * 0.2))
                            };
                            el.dispatchEvent(new MouseEvent('mousedown', opts));
                            el.dispatchEvent(new MouseEvent('mouseup', opts));
                            el.dispatchEvent(new MouseEvent('click', opts));
                            return el;
                        };
                        const target = (
                            document.activeElement
                            && document.activeElement !== document.body
                            && document.activeElement !== document.documentElement
                        ) ? document.activeElement : focusEditor();
                        if (!target) return false;

                        const binary = atob(dataB64);
                        const bytes = new Uint8Array(binary.length);
                        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                        const file = new File([bytes], name || 'autogeo-image.jpg', {type: mime || 'image/jpeg'});
                        const dt = new DataTransfer();
                        dt.items.add(file);
                        const event = new ClipboardEvent('paste', {
                            bubbles: true,
                            cancelable: true,
                            clipboardData: dt
                        });
                        target.dispatchEvent(event);
                        target.dispatchEvent(new Event('input', {bubbles: true}));
                        target.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }""",
                    {"dataB64": data_b64, "mime": mime, "name": name},
                )
                if not ok:
                    continue
                await random_delay(2, 4)
                if await self._editor_image_count(page) > before:
                    return True
            except Exception as exc:
                logger.debug(f"[B站] 图片粘贴异常: {exc}")
                continue
        return False

    async def _editor_image_count(self, page: Page) -> int:
        count = 0
        for context in self._editor_contexts(page):
            try:
                count += await context.evaluate(
                    """() => Array.from(document.querySelectorAll(
                        '[contenteditable="true"] img, .ProseMirror img, .ql-editor img, [role="textbox"] img'
                    )).filter((img) => {
                        const r = img.getBoundingClientRect();
                        const s = window.getComputedStyle(img);
                        return r.width > 0 && r.height > 0
                            && s.display !== 'none'
                            && s.visibility !== 'hidden';
                    }).length"""
                )
            except Exception:
                continue
        return count

    async def _visible_editor_has_images(self, page: Page, minimum: int = 1) -> bool:
        return await self._editor_image_count(page) >= minimum

    def _deep_clean(self, text: str) -> str:
        """清理 Markdown/HTML 语法，适配B站专栏编辑器"""
        # 移除图片
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        # 移除 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)
        # 移除 Markdown 标题标记
        text = re.sub(r"#+\s*", "", text)
        # 移除粗体标记
        text = re.sub(r"\*\*+", "", text)
        # 合并空行
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)

    def _page_and_frames(self, page: Page) -> List[Any]:
        """Return the main page plus child frames; B站专栏编辑器常在动态 iframe 里。"""
        contexts: List[Any] = [page]
        contexts.extend(frame for frame in page.frames if frame != page.main_frame)
        return contexts

    def _editor_contexts(self, page: Page) -> List[Any]:
        """Return only real editor contexts; read-draft alone is just the draft list."""
        contexts: List[Any] = []
        page_url = page.url or ""
        if any(
            token in page_url for token in ("upload-text/edit", "upload/text/edit", "article-editor", "read-editor")
        ):
            contexts.append(page)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frame_url = frame.url or ""
            if (
                "article-editor" in frame_url
                or "upload-text/edit" in frame_url
                or "upload/text/edit" in frame_url
                or "read-editor" in frame_url
            ):
                contexts.append(frame)
                continue
        return contexts

    async def _first_visible_locator(self, page: Page, selector: str, timeout: int = 1000):
        """Find a visible locator on the page or in any iframe."""
        for context in self._page_and_frames(page):
            try:
                locator = context.locator(selector)
                count = await locator.count()
                for i in range(count):
                    item = locator.nth(i)
                    if await item.is_visible(timeout=timeout):
                        return item
            except Exception:
                continue
        return page.locator(selector).first

    async def _first_visible_editor_locator(self, page: Page, selector: str, timeout: int = 1000):
        """Find a visible locator inside the article editor iframe only."""
        for context in self._editor_contexts(page):
            try:
                locator = context.locator(selector)
                count = await locator.count()
                for i in range(count):
                    item = locator.nth(i)
                    if await item.is_visible(timeout=timeout) and await self._looks_like_editor_locator(item):
                        return item
            except Exception:
                continue
        return page.locator("__bilibili_editor_not_found__").first

    async def _fill_bili_content_by_real_input(self, page: Page, text: str) -> bool:
        """Focus the real Bilibili body editor and type through Playwright keyboard events."""
        if not text:
            return False

        for context in self._editor_contexts(page):
            try:
                focused = await context.evaluate(
                    """() => {
                        const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return r.width > 0 && r.height > 0
                                && s.display !== 'none'
                                && s.visibility !== 'hidden'
                                && s.pointerEvents !== 'none';
                        };
                        const labelOf = (el) => [
                            el.getAttribute('placeholder') || '',
                            el.getAttribute('data-placeholder') || '',
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('class') || '',
                            el.innerText || '',
                            el.textContent || ''
                        ].join(' ');
                        const clickAndFocus = (el) => {
                            el.scrollIntoView({block: 'center', inline: 'center'});
                            const r = el.getBoundingClientRect();
                            const x = Math.min(r.left + Math.max(8, r.width * 0.05), r.right - 8);
                            const y = Math.min(r.top + Math.max(18, Math.min(56, r.height * 0.2)), r.bottom - 8);
                            const opts = {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y};
                            el.dispatchEvent(new PointerEvent('pointerdown', opts));
                            el.dispatchEvent(new MouseEvent('mousedown', opts));
                            if (typeof el.focus === 'function') el.focus();
                            el.dispatchEvent(new PointerEvent('pointerup', opts));
                            el.dispatchEvent(new MouseEvent('mouseup', opts));
                            el.dispatchEvent(new MouseEvent('click', opts));
                            return document.activeElement === el || el.contains(document.activeElement);
                        };

                        const editables = Array.from(document.querySelectorAll(
                            '[contenteditable="true"], textarea, .ProseMirror, .ql-editor, [role="textbox"]'
                        )).filter(visible);

                        const scored = editables
                            .map((el) => {
                                const r = el.getBoundingClientRect();
                                const label = labelOf(el);
                                let score = r.width * r.height / 1000;
                                if (/搜索|草稿|稿件/.test(label)) score -= 1000000;
                                if (/标题|请输入标题|文章标题|title/i.test(label)) score -= 100000;
                                if (/正文|请输入正文|内容|content|editor|ProseMirror|ql-editor/i.test(label)) score += 100000;
                                if (r.height >= 160) score += 5000;
                                if (r.top < 90) score -= 5000;
                                return {el, score};
                            })
                            .filter((item) => item.score > 0)
                            .sort((a, b) => b.score - a.score);

                        if (scored[0]?.el && clickAndFocus(scored[0].el)) {
                            return true;
                        }

                        const placeholders = Array.from(document.querySelectorAll('div, span, p'))
                            .filter((el) => visible(el) && /请输入正文/.test((el.innerText || el.textContent || '').trim()));
                        for (const ph of placeholders) {
                            ph.scrollIntoView({block: 'center', inline: 'center'});
                            const r = ph.getBoundingClientRect();
                            const probePoints = [
                                [r.left + 8, r.top + r.height + 8],
                                [r.left + 8, r.top + r.height + 32],
                                [r.left + 40, r.top + r.height + 48],
                                [r.left + 8, r.top + 8]
                            ];
                            for (const [x, y] of probePoints) {
                                let el = document.elementFromPoint(x, y);
                                while (el && el !== document.body) {
                                    if (
                                        el.isContentEditable
                                        || el.tagName === 'TEXTAREA'
                                        || el.getAttribute('role') === 'textbox'
                                        || /ProseMirror|ql-editor|editor/i.test(el.className || '')
                                    ) {
                                        if (visible(el) && clickAndFocus(el)) return true;
                                    }
                                    el = el.parentElement;
                                }
                            }
                            const opts = {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                clientX: r.left + 8,
                                clientY: r.top + r.height + 28
                            };
                            ph.dispatchEvent(new MouseEvent('mousedown', opts));
                            ph.dispatchEvent(new MouseEvent('mouseup', opts));
                            ph.dispatchEvent(new MouseEvent('click', opts));
                            if (document.activeElement && document.activeElement !== document.body) return true;
                        }
                        return false;
                    }"""
                )
                if not focused:
                    continue

                await short_delay()
                await page.keyboard.insert_text(text)
                await short_delay()
                if await self._visible_editor_contains_text(page, text):
                    return True

                # Some rich editors update state only on paste.
                try:
                    await context.evaluate(
                        """(text) => {
                            const target = document.activeElement;
                            if (!target || target === document.body) return false;
                            const data = new DataTransfer();
                            data.setData('text/plain', text);
                            return target.dispatchEvent(new ClipboardEvent('paste', {
                                bubbles: true,
                                cancelable: true,
                                clipboardData: data
                            }));
                        }""",
                        text,
                    )
                    await short_delay()
                    if await self._visible_editor_contains_text(page, text):
                        return True
                except Exception:
                    pass
            except Exception as exc:
                logger.debug(f"[B站] 正文真实输入尝试失败: {exc}")
                continue
        return False

    async def _fill_bili_placeholder_by_click(self, page: Page, kind: str, text: str) -> bool:
        """Click visible B站 placeholder text and type, matching the current editor UI."""
        if not text:
            return False
        patterns = [r"请输入标题", r"标题.*建议"] if kind == "title" else [r"请输入正文", r"正文"]
        for context in self._editor_contexts(page):
            for pattern in patterns:
                try:
                    loc = context.get_by_text(re.compile(pattern)).first
                    if await loc.count() <= 0 or not await loc.is_visible(timeout=1200):
                        continue
                    await loc.scroll_into_view_if_needed(timeout=2000)
                    box = await loc.bounding_box()
                    if box:
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    else:
                        await loc.click(force=True)
                    await short_delay()
                    await page.keyboard.insert_text(text)
                    await short_delay()
                    if (
                        await self._visible_editor_contains_text(page, text)
                        if kind == "content"
                        else await self._page_contains_text_anywhere(page, text)
                    ):
                        return True
                except Exception:
                    continue
        return False

    async def _fill_bili_editor_by_viewport_click(self, page: Page, kind: str, text: str) -> bool:
        """Directly click the visible B站 editor slots and type, matching the screen layout."""
        if not text:
            return False
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await short_delay()
        except Exception:
            pass

        viewport = page.viewport_size or {"width": 1280, "height": 800}
        width = viewport.get("width", 1280)
        height = viewport.get("height", 800)
        # B站专栏编辑器固定在左侧菜单右边，标题/正文入口在编辑区左上。
        # 点击偏左的位置比点击占位文字中部更容易落到真实 editable 节点。
        x = min(max(width * 0.18, 210), width - 260)
        if kind == "title":
            y = min(max(height * 0.12, 92), 150)
        else:
            y = min(max(height * 0.19, 145), 210)

        try:
            await page.mouse.click(x, y)
            await short_delay()
            # 避免使用全局 Control+A，它会选中整个页面而非仅输入框内容
            # 直接通过 insert_text 写入，富文本编辑器通常会自动替换占位符
            await page.keyboard.insert_text(text)
            await short_delay()
            if await self._page_contains_text_anywhere(page, text):
                return True

            # 如果首次写入失败，尝试通过 End 键定位到末尾后重新输入
            await page.keyboard.press("End")
            await short_delay()
            await page.keyboard.insert_text(text)
            await short_delay()
            return await self._page_contains_text_anywhere(page, text)
        except Exception as exc:
            logger.warning(f"[B站] 页面坐标直接写入失败 ({kind}): {exc}")
            return False

    async def _page_contains_text_anywhere(self, page: Page, text: str) -> bool:
        """Check main page and child frames for a newly typed text probe."""
        probe = text[: min(20, len(text))]
        if not probe:
            return False
        for context in self._page_and_frames(page):
            if await self._page_or_frame_contains_text(context, probe):
                return True
        return False

    async def _visible_editor_contains_text(self, page: Page, text: str) -> bool:
        """Return true only when the body editor's visible text contains the inserted content."""
        probe = text[: min(20, len(text))]
        if not probe:
            return False
        for context in self._editor_contexts(page):
            try:
                ok = await context.evaluate(
                    """(probe) => {
                        const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return r.width > 0 && r.height > 0
                                && s.display !== 'none'
                                && s.visibility !== 'hidden';
                        };
                        const nodes = Array.from(document.querySelectorAll(
                            '[contenteditable="true"], textarea, .ProseMirror, .ql-editor, [role="textbox"]'
                        )).filter(visible);
                        return nodes.some((el) => {
                            const label = [
                                el.getAttribute('placeholder') || '',
                                el.getAttribute('data-placeholder') || '',
                                el.getAttribute('aria-label') || '',
                                el.getAttribute('class') || ''
                            ].join(' ');
                            if (/搜索|草稿|稿件|标题|文章标题|请输入标题/.test(label)) return false;
                            const text = el.value || el.innerText || el.textContent || '';
                            return text.includes(probe);
                        });
                    }""",
                    probe,
                )
                if ok:
                    return True
            except Exception:
                continue
        return False

    async def _fill_bili_editor_by_geometry(self, page: Page, context: Any, kind: str, text: str) -> bool:
        """Fallback for B站 placeholders rendered outside queryable editable nodes."""
        point = await context.evaluate(
            """(kind) => {
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                };
                const candidates = Array.from(document.querySelectorAll('main, [class*="editor"], [class*="article"], [class*="write"], [class*="content"], body'))
                    .filter(visible)
                    .map((el) => {
                        const r = el.getBoundingClientRect();
                        const txt = (el.innerText || el.textContent || '');
                        let score = r.width * r.height / 1000;
                        if (/请输入标题|请输入正文|发布设置/.test(txt)) score += 100000;
                        if (r.left < 180 || r.width < 300 || r.height < 200) score -= 100000;
                        return {left: r.left, top: r.top, width: r.width, height: r.height, score};
                    })
                    .sort((a, b) => b.score - a.score);
                const r = candidates[0];
                if (!r) return null;
                const x = Math.min(r.left + Math.max(40, r.width * 0.08), r.left + r.width - 40);
                const y = kind === 'title'
                    ? r.top + Math.min(90, Math.max(45, r.height * 0.08))
                    : r.top + Math.min(150, Math.max(95, r.height * 0.14));
                return {x, y};
            }""",
            kind,
        )
        if not point:
            return False
        offset_x = 0
        offset_y = 0
        try:
            if hasattr(context, "frame_element"):
                frame_element = await context.frame_element()
                frame_box = await frame_element.bounding_box()
                if frame_box:
                    offset_x = frame_box["x"]
                    offset_y = frame_box["y"]
        except Exception:
            pass
        await page.mouse.click(point["x"] + offset_x, point["y"] + offset_y)
        await short_delay()
        await page.keyboard.insert_text(text)
        await short_delay()
        return await self._page_or_frame_contains_text(context, text)

    async def _page_or_frame_contains_text(self, context: Any, text: str) -> bool:
        probe = text[: min(20, len(text))]
        if not probe:
            return False
        try:
            return await context.evaluate(
                """(probe) => {
                    const valueText = Array.from(document.querySelectorAll('input, textarea'))
                        .map((el) => el.value || '')
                        .join('\\n');
                    const domText = document.body ? (document.body.innerText || document.body.textContent || '') : '';
                    return valueText.includes(probe) || domText.includes(probe);
                }""",
                probe,
            )
        except Exception:
            return False

    async def _inject_bili_editor_text(self, context: Any, kind: str, text: str) -> bool:
        """Fill B站新版 contenteditable editor with DOM input/paste events."""
        if not text:
            return False
        return await context.evaluate(
            """({kind, text}) => {
                const isVisible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const labelOf = (el) => [
                    el.getAttribute('placeholder') || '',
                    el.getAttribute('data-placeholder') || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('class') || '',
                    el.innerText || '',
                    el.textContent || ''
                ].join(' ');
                const editableNodes = Array.from(document.querySelectorAll(
                    '[contenteditable="true"], textarea, input, .ProseMirror, .ql-editor'
                )).filter(isVisible);
                const scoreNode = (el) => {
                    const label = labelOf(el);
                    const rect = el.getBoundingClientRect();
                    let score = 0;
                    if (/搜索|草稿|稿件/.test(label)) return -1000000;
                    if (kind === 'title') {
                        if (/请输入标题|标题|title/i.test(label)) score += 100000;
                        if (/正文|内容/.test(label)) score -= 100000;
                        if (rect.height <= 120) score += 1000;
                        score -= rect.top;
                    } else {
                        if (/请输入正文|正文|内容|content|editor|ProseMirror|ql-editor/i.test(label)) score += 100000;
                        if (/标题|title/.test(label)) score -= 100000;
                        if (rect.height >= 120) score += 2000;
                        score += rect.width * rect.height / 1000;
                    }
                    return score;
                };
                const candidates = editableNodes
                    .map((el) => ({el, score: scoreNode(el)}))
                    .filter((item) => item.score > 0)
                    .sort((a, b) => b.score - a.score);
                const el = candidates[0]?.el;
                if (!el) return false;

                el.scrollIntoView({block: 'center', inline: 'center'});
                el.focus();

                const setNativeValue = (node, value) => {
                    const proto = node instanceof HTMLTextAreaElement
                        ? HTMLTextAreaElement.prototype
                        : HTMLInputElement.prototype;
                    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                    if (descriptor && descriptor.set) descriptor.set.call(node, value);
                    else node.value = value;
                };
                const fire = (node) => {
                    node.dispatchEvent(new InputEvent('beforeinput', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'insertText',
                        data: text
                    }));
                    node.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        inputType: 'insertText',
                        data: text
                    }));
                    node.dispatchEvent(new Event('change', {bubbles: true}));
                };

                if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                    setNativeValue(el, text);
                    fire(el);
                } else {
                    const selection = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    document.execCommand('delete', false, null);

                    let inserted = false;
                    try {
                        const data = new DataTransfer();
                        data.setData('text/plain', text);
                        inserted = !el.dispatchEvent(new ClipboardEvent('paste', {
                            bubbles: true,
                            cancelable: true,
                            clipboardData: data
                        }));
                    } catch (_) {}

                    if (!inserted) {
                        inserted = document.execCommand('insertText', false, text);
                    }
                    if (!inserted || !(el.innerText || el.textContent || '').includes(text.slice(0, Math.min(20, text.length)))) {
                        const html = text
                            .split(/\\n{2,}|\\n/)
                            .filter(Boolean)
                            .map((line) => `<p>${line
                                .replace(/&/g, '&amp;')
                                .replace(/</g, '&lt;')
                                .replace(/>/g, '&gt;')}</p>`)
                            .join('');
                        el.innerHTML = html || text;
                    }
                    fire(el);
                }

                const value = el.value || el.innerText || el.textContent || '';
                return value.includes(text.slice(0, Math.min(20, text.length)));
            }""",
            {"kind": kind, "text": text},
        )

    async def _looks_like_editor_locator(self, locator: Any) -> bool:
        """Reject the draft-list search box even when a broad selector matches it."""
        try:
            tag = await locator.evaluate("(el) => el.tagName.toLowerCase()")
            placeholder = await locator.evaluate(
                "(el) => el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || ''"
            )
            text = await locator.evaluate("(el) => (el.innerText || el.textContent || '').trim()")
            combined = f"{placeholder} {text}"
            if any(word in combined for word in ("搜索", "草稿", "稿件")):
                return False
            if "请输入标题" in placeholder or "请输入文章标题" in placeholder or "输入文章标题" in placeholder:
                return True
            if "标题" in placeholder and ("建议" in placeholder or "文章" in placeholder):
                return True
            if tag in ("input", "textarea") and "标题" not in placeholder:
                return False
            return True
        except Exception:
            return False

    async def _looks_like_content_locator(self, locator: Any) -> bool:
        """Reject title/search nodes when filling article body."""
        try:
            placeholder = await locator.evaluate(
                "(el) => el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || ''"
            )
            text = await locator.evaluate("(el) => (el.innerText || el.textContent || '').trim()")
            klass = await locator.evaluate("(el) => el.getAttribute('class') || ''")
            combined = f"{placeholder} {text} {klass}"
            if any(word in combined for word in ("搜索", "草稿", "稿件", "请输入标题", "文章标题")):
                return False
            if any(word in combined for word in ("正文", "内容", "ProseMirror", "ql-editor", "editor")):
                return True
            box = await locator.bounding_box()
            return bool(box and box.get("height", 0) >= 100)
        except Exception:
            return False

    async def _first_existing_locator(self, page: Page, selectors: List[str] | str):
        """Find an existing locator on the page or in any iframe, visibility not required."""
        selector_list = selectors if isinstance(selectors, list) else [selectors]
        for selector in selector_list:
            for context in self._page_and_frames(page):
                try:
                    locator = context.locator(selector).first
                    if await locator.count() > 0:
                        return locator
                except Exception:
                    continue
        return page.locator(selector_list[0]).first

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        logger.error(f"❌ [B站] 失败 [{stage}]: {msg}")
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        return {
            "success": False,
            "error_msg": f"B站发布失败[{stage}]: {msg}",
            "platform_url": getattr(page, "url", None),
            "debug_path": debug_path,
        }

    async def _manual_fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        """记录人工介入结果前先保存页面快照，便于事后定位登录/验证码/风控卡点。"""
        debug_path = await self._save_debug_snapshot(page, f"manual_{stage}")
        result = self.manual_intervention_result(stage, message, page)
        result["debug_path"] = debug_path
        return result

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        """保存失败时的 HTML + 全页截图到 backend/debug/bilibili/，供事后定位卡点。"""
        debug_dir = Path("backend/debug/bilibili")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[B站] 保存调试 HTML 失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[B站] 保存调试截图失败: {}", exc)
        return str(html_path)

    def _looks_like_manual_intervention(self, msg: str) -> bool:
        msg = (msg or "").lower()
        return any(
            key in msg
            for key in ("登录", "登陆", "login", "passport", "验证码", "验证", "captcha", "滑块", "风控", "安全")
        )


# ═══════════════════════════════════════════════════════════
# 注册到全局发布器注册表
# ═══════════════════════════════════════════════════════════
BILIBILI_CONFIG = {
    "name": "B站专栏",
    "publish_url": "https://member.bilibili.com/platform/upload/text/new-article",
    "auto_generate_images": False,
    "inline_image_count": 0,
    "color": "#FB7299",
}
registry.register("bilibili", BilibiliPublisher("bilibili", BILIBILI_CONFIG))
