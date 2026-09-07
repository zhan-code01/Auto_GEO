# -*- coding: utf-8 -*-
"""
微信公众号发布适配器 - v1.0

发布流程：
1. stealth       注入 localStorage 跳过新手引导
2. navigate      草稿箱入口 → 检测登录态
3. open_editor   点击"写新图文"按钮，等编辑器加载
4. close_popups  关闭弹窗/工具引导
5. fill_title    选择器 → 键盘 → JS 兜底
6. fill_content  富文本编辑器：keyboard.insert_text + JS 注入
7. upload_cover  文章自带封面/正文首图 → set_input_files
8. set_options   可选声明开关（微信一般无）
9. publish       点击"保存并群发" → 处理二次确认弹窗
10. wait_result  检测成功/失败提示或 URL 跳转
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import tempfile
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger
from playwright.async_api import Page

from . import weixin_selectors as sel
from .base import BasePublisher, registry
from .note_utils import generated_publish_images_enabled, materialize_images
from ..humanize import random_delay, short_delay


class WeixinPublisher(BasePublisher):
    """微信公众号图文发布器"""

    MAX_TITLE_LENGTH = 64
    MAX_CONTENT_LENGTH = 20000
    COVER_WIDTH = 900
    COVER_HEIGHT = 383

    # ═══════════════════════════════════════════════════════════
    # 主流程
    # ═══════════════════════════════════════════════════════════

    async def publish(
        self,
        page: Page,
        article: Any,
        account: Any,
        declare_ai_content: bool = True,
    ) -> Dict[str, Any]:
        temp_files: List[str] = []
        cover_path: Optional[str] = None
        stage = "init"
        try:
            logger.info("🚀 [微信 v1.0] 开始发布图文文章")

            title = getattr(article, "title", "") or "未命名文章"
            content = getattr(article, "content", "") or ""

            # 0. 注入隐身疫苗（屏蔽新手引导遮罩）
            stage = "stealth"
            await self._inject_minimal_stealth(page)

            # 1. 导航到草稿箱（带重试）
            stage = "navigate"
            if not await self._navigate_to_draft_box(page):
                return await self._manual_fail(
                    page,
                    stage,
                    "无法进入微信公众号草稿箱，可能登录态失效，请到账号管理重新授权微信公众号",
                )
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            # 2. 登录态检测
            stage = "login_check"
            if not await self._ensure_logged_in(page):
                return await self._manual_fail(
                    page,
                    stage,
                    "微信公众号登录态失效，请到账号管理重新授权",
                )

            # 3. 打开编辑器（点击"写新图文"）
            stage = "open_editor"
            if not await self._open_editor(page):
                return await self._fail(page, stage, "未找到'写新图文'按钮入口")
            await self._close_interference(page)

            # 4. 等待编辑器加载
            stage = "wait_editor"
            await self._wait_editor_ready(page)
            await self._close_interference(page)

            # 5. 准备封面图（优先使用文章图片，默认不在发布阶段生成替代图）
            stage = "prepare_cover"
            cover_path, cover_temp_files = await self._resolve_cover(article, title)
            temp_files.extend(cover_temp_files)
            if not cover_path:
                logger.warning("⚠️ [微信] 未找到文章自带封面，将尝试不带封面发布（可能被微信拦截）")

            # 6. 填写标题
            stage = "fill_title"
            await self._close_interference(page)
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "标题填写失败")

            # 7. 填写正文
            stage = "fill_content"
            await self._close_interference(page)
            if not await self._fill_content(page, content):
                return await self._fail(page, stage, "正文填写失败")

            # 8. 上传封面
            stage = "upload_cover"
            if cover_path:
                await self._upload_cover(page, cover_path)
            await self._close_interference(page)

            # 9. 设置发布选项（微信一般无需设置 AI 声明）
            stage = "set_options"
            await self._set_publish_options(page, declare_ai_content=declare_ai_content)
            await self._close_interference(page)

            # 10. 滚到底部并点击"保存并群发"
            stage = "publish"
            await self._close_interference(page)
            if not await self._click_publish(page):
                return await self._fail(page, stage, "未找到'保存并群发'按钮")

            # 11. 处理二次确认弹窗 / 扫码验证
            stage = "confirm_publish"
            confirm_result = await self._handle_publish_confirm(page)
            if confirm_result is not None:
                # 走人工介入流程（如扫码）
                return confirm_result

            # 12. 等待发布结果
            stage = "wait_result"
            return await self._wait_for_publish_result(page)

        except Exception as e:
            logger.exception(f"❌ [微信] 发布失败 stage={stage}: {e}")
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
    # 错误处理 & 调试快照
    # ═══════════════════════════════════════════════════════════

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        logger.error(f"❌ [微信] stage={stage} 失败: {msg}")
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        return {
            "success": False,
            "error_msg": f"[{stage}] {msg}",
            "platform_url": getattr(page, "url", None),
            "debug_path": debug_path,
        }

    async def _manual_fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        debug_path = await self._save_debug_snapshot(page, f"manual_{stage}")
        result = self.manual_intervention_result(stage, message, page)
        result["debug_path"] = debug_path
        return result

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        """保存失败时的 HTML + 全页截图到 backend/debug/weixin/。"""
        debug_dir = Path("backend/debug/weixin")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[微信] 保存调试 HTML 失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[微信] 保存调试截图失败: {}", exc)
        return str(html_path)

    # ═══════════════════════════════════════════════════════════
    # 隐身疫苗：屏蔽新手引导
    # ═══════════════════════════════════════════════════════════

    async def _inject_minimal_stealth(self, page: Page) -> None:
        """注入 localStorage 屏蔽引导，不动 navigator（避免被反爬识别）。"""
        try:
            await page.add_init_script(
                """() => {
                    try {
                        localStorage.setItem('mpGuideClosed', '1');
                        localStorage.setItem('mp_home_guide', '1');
                        localStorage.setItem('weui_desktop_guide', '1');
                        localStorage.setItem('new_editor_guide', '1');
                    } catch (e) {}
                    window.__autogeoWxCloseGuides = () => {
                        const texts = ['我知道了', '完成', '下一步', '知道了', '关闭', '跳过', '稍后', '不用了', '确定'];
                        const isVisible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0
                                && style.display !== 'none' && style.visibility !== 'hidden';
                        };
                        const score = (el) => {
                            const rect = el.getBoundingClientRect();
                            const tag = el.tagName.toLowerCase();
                            const cls = String(el.className || '').toLowerCase();
                            const role = el.getAttribute('role') || '';
                            let s = 0;
                            if (tag === 'button') s += 100;
                            if (role === 'button') s += 90;
                            if (/btn|button|primary|confirm|next/.test(cls)) s += 60;
                            if (rect.width >= 40 && rect.width <= 180 && rect.height >= 24 && rect.height <= 70) s += 40;
                            s -= Math.min((el.innerText || '').length, 80);
                            return s;
                        };
                        for (const text of texts) {
                            const candidates = Array.from(document.querySelectorAll('button, [role="button"], a, span, div'))
                                .filter(el => isVisible(el) && (el.innerText || '').trim().includes(text))
                                .sort((a, b) => score(b) - score(a));
                            const target = candidates[0];
                            if (target) {
                                try { target.click(); return true; } catch (e) {}
                            }
                        }
                        return false;
                    };
                    window.__autogeoWxGuideTimer = window.__autogeoWxGuideTimer || setInterval(() => {
                        try { window.__autogeoWxCloseGuides(); } catch (e) {}
                    }, 800);
                }"""
            )
            try:
                await page.evaluate(
                    """() => {
                        try {
                            localStorage.setItem('mpGuideClosed', '1');
                            localStorage.setItem('mp_home_guide', '1');
                            localStorage.setItem('weui_desktop_guide', '1');
                            localStorage.setItem('new_editor_guide', '1');
                        } catch (e) {}
                    }"""
                )
            except Exception:
                pass
            logger.info("💉 [微信] 隐身疫苗已注入（localStorage）")
        except Exception as e:
            logger.warning(f"⚠️ [微信] 隐身疫苗注入失败（不阻断）: {e}")

    # ═══════════════════════════════════════════════════════════
    # 导航 & 登录
    # ═══════════════════════════════════════════════════════════

    async def _navigate_to_draft_box(self, page: Page) -> bool:
        """导航到草稿箱。返回 True/False，不抛异常。"""
        draft_url = self.config.get(
            "publish_url",
            sel.DRAFT_BOX_URL,
        )

        last_error = ""
        for attempt in range(3):
            try:
                logger.info(f"[微信] 导航到草稿箱 (尝试 {attempt + 1}/3): {draft_url}")
                await page.goto(draft_url, wait_until="domcontentloaded", timeout=60000)

                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    logger.warning("[微信] networkidle 等待超时，继续检测")

                await asyncio.sleep(2)

                # 检测登录页
                if self._is_login_url(page.url):
                    logger.error(f"❌ [微信] 被重定向到登录页: {page.url}")
                    return False

                # 检测草稿箱页面元素
                if await self._is_draft_box(page):
                    logger.success("✅ [微信] 已进入草稿箱")
                    return True

                # 等待页面渲染
                logger.warning(f"⚠️ [微信] 页面已加载但草稿箱未出现，当前URL: {page.url}")
                await asyncio.sleep(3)
                if await self._is_draft_box(page):
                    logger.success("✅ [微信] 草稿箱在等待后出现")
                    return True

            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ [微信] 导航异常 (尝试 {attempt + 1}/3): {e}")
                await asyncio.sleep(2)

        logger.error(f"❌ [微信] 3 次导航均失败。最后错误: {last_error}")
        return False

    def _is_login_url(self, url: str) -> bool:
        url = (url or "").lower()
        return any(indicator in url for indicator in sel.LOGIN_URL_INDICATOR)

    async def _is_draft_box(self, page: Page) -> bool:
        """检测是否进入了草稿箱：URL 含 appmsg_list，或能找到'写新图文'按钮。"""
        # 先检测页面是否是错误页（session timeout 等），如果是则直接返回 False
        try:
            body_class = await page.locator("body").get_attribute("class") or ""
            if "page_error" in body_class or "page_timeout" in body_class:
                logger.warning(f"[微信] 页面显示错误状态: {body_class}")
                return False
        except Exception:
            pass

        url = (page.url or "").lower()
        if "appmsg_list" in url or "media/appmsg_list" in url:
            return True

        # 兜底：检测"写新图文"按钮存在
        for selector in sel.NEW_ARTICLE_BTN[:4]:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1000):
                    return True
            except Exception:
                continue
        return False

    async def _ensure_logged_in(self, page: Page) -> bool:
        """登录态检测：URL 不在登录页 + 有登录成功标识。"""
        if self._is_login_url(page.url):
            return False

        for selector in sel.LOGIN_SUCCESS_ELEMENT[:5]:
            try:
                el = page.locator(selector).first
                if await el.count() > 0:
                    logger.info("✅ [微信] 检测到登录态标识")
                    return True
            except Exception:
                continue

        # 兜底：在草稿箱/编辑器里就视为已登录
        if await self._is_draft_box(page):
            logger.info("✅ [微信] 已在草稿箱，认为已登录")
            return True

        logger.warning("⚠️ [微信] 无法确认登录态")
        return False

    async def _open_editor(self, page: Page) -> bool:
        """点击'写新图文'按钮，进入编辑器。"""
        # L1: 直接找"写新图文"按钮
        for selector in sel.NEW_ARTICLE_BTN:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    text = (await btn.inner_text()).strip()
                    if text and "写新图文" not in text and "图文" not in text:
                        continue
                    await btn.click(force=True)
                    logger.info(f"[微信] 已点击写新图文按钮: {selector}")
                    await asyncio.sleep(3)
                    return True
            except Exception:
                continue

        # L2: JS 精确匹配
        try:
            clicked = await page.evaluate(
                """() => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], div, span'))
                        .filter(el => visible(el) && (el.innerText || '').trim() === '写新图文');
                    const target = candidates[0];
                    if (!target) return false;
                    target.click();
                    return true;
                }"""
            )
            if clicked:
                logger.info("[微信] 已通过 DOM 精确点击'写新图文'")
                await asyncio.sleep(3)
                return True
        except Exception:
            pass

        # L3: 兜底 - 先点"图文消息"卡片，再找写新图文
        for selector in sel.IMAGE_ARTICLE_ENTRY:
            try:
                entry = page.locator(selector).first
                if await entry.count() > 0 and await entry.is_visible(timeout=1000):
                    await entry.click(force=True)
                    logger.info(f"[微信] 已点击图文消息卡片: {selector}")
                    await asyncio.sleep(2)
                    # 再次尝试找写新图文
                    for sub in sel.NEW_ARTICLE_BTN[:3]:
                        try:
                            btn = page.locator(sub).first
                            if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                                await btn.click(force=True)
                                logger.info(f"[微信] 二级菜单已点击写新图文: {sub}")
                                await asyncio.sleep(3)
                                return True
                        except Exception:
                            continue
            except Exception:
                continue

        return False

    async def _has_editor(self, page: Page, timeout: int = 2000) -> bool:
        """检测编辑器是否已渲染。"""
        for selector in sel.TITLE_INPUT[:5]:
            try:
                node = page.locator(selector).first
                if await node.count() > 0 and await node.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue
        for selector in sel.CONTENT_INPUT[:5]:
            try:
                node = page.locator(selector).first
                if await node.count() > 0 and await node.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue
        for text in ["请输入标题", "请输入正文"]:
            try:
                if await page.get_by_placeholder(text).first.count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def _wait_editor_ready(self, page: Page, max_wait: int = 20) -> None:
        """等待编辑器真正可交互。"""
        for _ in range(max_wait):
            if await self._has_editor(page, timeout=500):
                return
            await asyncio.sleep(1)
        logger.warning(f"⚠️ [微信] 编辑器 {max_wait}s 内未稳定渲染，继续尝试")

    # ═══════════════════════════════════════════════════════════
    # 关闭干扰弹窗
    # ═══════════════════════════════════════════════════════════

    async def _close_interference(self, page: Page) -> None:
        """关闭干扰弹窗（新手引导、活动提示等）。"""
        for _ in range(10):
            handled = False
            try:
                handled = bool(await page.evaluate("window.__autogeoWxCloseGuides && window.__autogeoWxCloseGuides()"))
                if handled:
                    await short_delay()
                    continue
            except Exception:
                pass

            for btn_selector in sel.CLOSE_POPUP_BTN:
                try:
                    btn = page.locator(btn_selector).last
                    if await btn.count() > 0 and await btn.is_visible(timeout=600):
                        await btn.click(force=True)
                        logger.info(f"[微信] 已处理干扰弹窗: {btn_selector}")
                        await short_delay()
                        handled = True
                        break
                except Exception:
                    continue

            if not handled:
                break

        # Esc 关浮层
        for _ in range(3):
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
            except Exception:
                break

    # ═══════════════════════════════════════════════════════════
    # 封面准备
    # ═══════════════════════════════════════════════════════════

    async def _resolve_cover(self, article: Any, title: str) -> tuple[Optional[str], List[str]]:
        """优先使用文章封面字段或正文首图；只有显式开启时才生成替代封面。"""
        for attr in ("cover_path", "cover_image_path", "cover", "cover_image"):
            value = getattr(article, attr, None)
            if isinstance(value, str) and value.strip() and os.path.exists(value):
                logger.info(f"[微信] 使用文章封面字段: {value}")
                return value, []

        try:
            image_paths, temp_files = await materialize_images(article, limit=1)
            if image_paths:
                logger.info(f"[微信] 使用文章内嵌图片作为封面: {image_paths[0]}")
                return image_paths[0], temp_files
        except Exception as exc:
            logger.warning(f"[微信] 提取文章图片失败: {exc}")

        if generated_publish_images_enabled(self.config):
            generated = await self._generate_cover(title)
            return generated, [generated] if generated else []
        logger.info("[微信] 跳过发布阶段替代封面生成")
        return None, []

    async def _generate_cover(self, title: str) -> Optional[str]:
        """显式开启时生成封面图，返回本地路径。"""
        keyword = self._extract_keyword(title)
        encoded = urllib.parse.quote(f"{keyword} WeChat article cover {random.randint(1, 10000)}")

        candidates = [
            f"https://image.pollinations.ai/prompt/{encoded}?width={self.COVER_WIDTH}&height={self.COVER_HEIGHT}&nologo=true",
            f"https://picsum.photos/{self.COVER_WIDTH}/{self.COVER_HEIGHT}?random={random.randint(1, 100000)}",
        ]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(headers=headers, verify=False, timeout=30.0) as client:
            for url in candidates:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.content) > 2000:
                        path = os.path.join(
                            tempfile.gettempdir(),
                            f"wx_cover_{random.randint(10000, 99999)}.jpg",
                        )
                        with open(path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"[微信] AI 封面已下载: {path}")
                        return path
                except Exception as e:
                    logger.warning(f"[微信] AI 封面图源失败 {url[:80]}: {e}")
                    continue
        return None

    def _extract_keyword(self, title: str) -> str:
        """从标题提取关键词。"""
        cleaned = re.sub(r"[^\w一-鿿]", " ", title or "")
        words = [w for w in cleaned.split() if w]
        if not words:
            return "风景"
        return words[0] if len(words) == 1 else f"{words[0]} {words[1]}"

    # ═══════════════════════════════════════════════════════════
    # 标题 & 正文
    # ═══════════════════════════════════════════════════════════

    async def _fill_title(self, page: Page, title: str) -> bool:
        """填写标题：选择器 → JS 兜底。"""
        clean = re.sub(r"[#*`\"<>]", "", title or "").strip()[: self.MAX_TITLE_LENGTH]
        if not clean:
            logger.error("❌ [微信] 标题为空")
            return False

        # L1: 选择器
        for selector in sel.TITLE_INPUT:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible(timeout=3000):
                    await loc.click(force=True)
                    await short_delay()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    try:
                        await loc.fill(clean)
                    except Exception:
                        await page.keyboard.type(clean, delay=20)
                    logger.info(f"✅ [微信] 标题已填写 (selector): {clean}")
                    return True
            except Exception:
                continue

        # L2: JS 兜底
        ok = await page.evaluate(
            """(title) => {
                const candidates = Array.from(
                    document.querySelectorAll('textarea, input, [contenteditable="true"]')
                );
                const el = candidates.find(node => {
                    const ph = node.getAttribute('placeholder')
                        || node.getAttribute('data-placeholder') || '';
                    return ph.includes('标题') || (node.id === 'title');
                });
                if (!el) return false;
                el.focus();
                if ('value' in el) {
                    el.value = title;
                } else {
                    el.innerText = title;
                }
                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true, inputType: 'insertText', data: title
                }));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }""",
            clean,
        )
        if ok:
            logger.info(f"✅ [微信] 标题已填写 (JS 兜底): {clean}")
        return bool(ok)

    async def _fill_content(self, page: Page, content: str) -> bool:
        """填写正文：富文本编辑器 → textarea → JS 注入。"""
        clean = self._deep_clean_content(content or "")
        clean = clean[: self.MAX_CONTENT_LENGTH]
        if not clean.strip():
            logger.error("❌ [微信] 正文为空")
            return False

        # L1: 富文本编辑器
        for selector in sel.CONTENT_INPUT:
            try:
                editor = page.locator(selector).first
                if await editor.count() > 0 and await editor.is_visible(timeout=3000):
                    await editor.click(force=True)
                    await short_delay()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await short_delay()
                    if len(clean) > 1000:
                        try:
                            await page.keyboard.insert_text(clean)
                        except Exception:
                            await page.keyboard.type(clean, delay=10)
                    else:
                        await page.keyboard.type(clean, delay=15)
                    logger.info(f"✅ [微信] 正文已填写 - L1 ({len(clean)} 字符)")
                    return True
            except Exception:
                continue

        # L2: textarea
        for selector in [
            'textarea[placeholder*="请输入正文"]',
            'textarea[placeholder*="正文"]',
            "#desc",
        ]:
            try:
                editor = page.locator(selector).first
                if await editor.count() > 0 and await editor.is_visible(timeout=2000):
                    await editor.fill(clean)
                    logger.info(f"✅ [微信] 正文已填写 - L2 textarea ({len(clean)} 字符)")
                    return True
            except Exception:
                continue

        # L3: JS 注入
        ok = await page.evaluate(
            """(text) => {
                const nodes = Array.from(document.querySelectorAll('[contenteditable="true"]'));
                const scored = nodes.map(el => {
                    const rect = el.getBoundingClientRect();
                    const ph = el.getAttribute('data-placeholder')
                        || el.getAttribute('placeholder') || '';
                    const label = `${ph} ${el.innerText || ''}`;
                    let score = rect.height + rect.width;
                    if (label.includes('请输入正文') || label.includes('正文')) score += 100000;
                    if (label.includes('标题')) score -= 100000;
                    if (rect.height < 80) score -= 50000;
                    return {el, score};
                }).sort((a, b) => b.score - a.score);

                const target = scored.length ? scored[0].el : null;
                if (!target) return false;

                target.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                const html = text
                    .split(/\\n{2,}/)
                    .map(p => `<p>${
                        p.replace(/&/g, '&amp;')
                         .replace(/</g, '&lt;')
                         .replace(/>/g, '&gt;')
                         .replace(/\\n/g, '<br>')
                    }</p>`)
                    .join('');
                document.execCommand('insertHTML', false, html);
                target.dispatchEvent(new InputEvent('input', {
                    bubbles: true, inputType: 'insertText', data: text
                }));
                target.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }""",
            clean,
        )
        if ok:
            logger.info(f"✅ [微信] 正文已填写 - L3 JS 注入 ({len(clean)} 字符)")
        return bool(ok)

    # ═══════════════════════════════════════════════════════════
    # 封面上传
    # ═══════════════════════════════════════════════════════════

    async def _upload_cover(self, page: Page, cover_path: str) -> None:
        """上传封面图。"""
        if not cover_path or not os.path.exists(cover_path):
            logger.warning(f"⚠️ [微信] 封面文件不存在: {cover_path}")
            return

        try:
            # 滚到封面区域
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
            except Exception:
                pass

            # 方案 1：直接给隐藏的 input[type="file"] 注入文件
            for selector in sel.COVER_FILE_INPUT:
                try:
                    file_input = page.locator(selector).first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(cover_path)
                        await asyncio.sleep(2)
                        await self._confirm_cover_dialog(page)
                        logger.info(f"✅ [微信] 封面已通过 input file 注入: {selector}")
                        return
                except Exception:
                    continue

            # 方案 2：点击封面区域，触发 file chooser
            for selector in sel.COVER_BUTTON:
                try:
                    target = page.locator(selector).first
                    if await target.count() == 0:
                        continue
                    if not await target.is_visible(timeout=1500):
                        continue

                    try:
                        async with page.expect_file_chooser(timeout=4000) as fc_info:
                            await target.click(force=True)
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(cover_path)
                        await asyncio.sleep(2)
                        await self._confirm_cover_dialog(page)
                        logger.info("✅ [微信] 封面已通过文件选择器上传")
                        return
                    except Exception:
                        # 不是文件选择器模式，可能是弹窗
                        await target.click(force=True)
                        await asyncio.sleep(1)
                        # 弹窗里再找 file input
                        for sub in sel.COVER_FILE_INPUT:
                            try:
                                fi = page.locator(sub).first
                                if await fi.count() > 0:
                                    await fi.set_input_files(cover_path)
                                    await asyncio.sleep(2)
                                    await self._confirm_cover_dialog(page)
                                    logger.info("✅ [微信] 封面已通过弹窗上传")
                                    return
                            except Exception:
                                continue
                except Exception:
                    continue

            logger.warning("⚠️ [微信] 未找到封面上传入口，继续发布")
        except Exception as e:
            logger.warning(f"⚠️ [微信] 封面上传失败，继续发布: {e}")

    async def _confirm_cover_dialog(self, page: Page) -> None:
        """处理封面弹窗的'完成/确定'按钮。"""
        for selector in sel.COVER_CONFIRM:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    await asyncio.sleep(1)
                    logger.info(f"[微信] 已确认封面弹窗: {selector}")
                    return
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════
    # 发布选项 & 发布按钮
    # ═══════════════════════════════════════════════════════════

    async def _set_publish_options(self, page: Page, declare_ai_content: bool = True) -> None:
        """微信一般无需额外设置，留作扩展。"""
        try:
            # 滚到底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _click_publish(self, page: Page) -> bool:
        """点击'保存并群发'按钮。"""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)

            # 强制启用按钮（防止被灰禁）
            await page.evaluate(
                """() => {
                    document.querySelectorAll('button, a, [role="button"]').forEach(btn => {
                        const text = (btn.innerText || '').trim();
                        if (text.includes('群发') || text === '保存并群发' || text === '发布') {
                            if (btn.disabled !== undefined) btn.disabled = false;
                            btn.removeAttribute('disabled');
                        }
                    });
                }"""
            )

            # 优先精确选择器
            for selector in sel.PUBLISH_BUTTON:
                try:
                    buttons = page.locator(selector)
                    count = await buttons.count()
                    for i in range(count - 1, -1, -1):
                        btn = buttons.nth(i)
                        if not await btn.is_visible(timeout=1000):
                            continue
                        text = (await btn.inner_text()).strip()
                        # 过滤无关按钮
                        if any(bad in text for bad in ["保存为草稿", "保存草稿", "定时", "设置"]):
                            continue
                        if not any(good in text for good in ["群发", "发布", "保存并群发"]):
                            continue
                        await btn.scroll_into_view_if_needed(timeout=3000)
                        await btn.click(force=True)
                        logger.info(f"✅ [微信] 已点击发布按钮: {text} (selector: {selector})")
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue

            return False
        except Exception as e:
            logger.error(f"❌ [微信] 点击发布失败: {e}")
            return False

    async def _handle_publish_confirm(self, page: Page) -> Optional[Dict[str, Any]]:
        """
        处理发布后的二次确认弹窗 / 扫码验证。
        返回 None 表示已处理（继续等待结果）；返回 dict 表示需要人工介入或已失败。
        """
        # 1. 先等弹窗出现（最多 5 秒）
        for tick in range(10):
            # 扫码验证（订阅号 / 风控触发）
            for qr_selector in sel.SCAN_QRCODE:
                try:
                    qr = page.locator(qr_selector).first
                    if await qr.count() > 0 and await qr.is_visible(timeout=300):
                        logger.warning("🚧 [微信] 触发扫码验证，请在 120 秒内在手机微信上确认")
                        # 先保存快照供事后查看
                        await self._save_debug_snapshot(page, "scan_qrcode")
                        # 给用户 120 秒扫码
                        try:
                            await page.wait_for_selector(qr_selector, state="hidden", timeout=120000)
                            logger.info("[微信] 扫码验证完成，继续发布")
                            return None
                        except Exception:
                            return await self._manual_fail(
                                page,
                                "scan_qrcode",
                                "请在手机微信上完成群发扫码确认",
                            )
                except Exception:
                    continue

            # 二次确认弹窗（"确认群发？"）
            for selector in sel.PUBLISH_CONFIRM:
                try:
                    btn = page.locator(selector).last
                    if await btn.count() > 0 and await btn.is_visible(timeout=300):
                        await btn.click(force=True)
                        logger.info(f"[微信] 已确认群发弹窗: {selector}")
                        await asyncio.sleep(1)
                        return None
                except Exception:
                    continue

            # 验证码
            try:
                if await page.locator(sel.CAPTCHA_INDICATOR).count() > 0:
                    logger.warning("🚧 [微信] 触发验证码，请在 60 秒内手动完成")
                    try:
                        await page.wait_for_selector(sel.CAPTCHA_INDICATOR, state="hidden", timeout=60000)
                        return None
                    except Exception:
                        return await self._manual_fail(
                            page,
                            "captcha",
                            "请完成微信公众号验证码后重试发布",
                        )
            except Exception:
                pass

            await asyncio.sleep(0.5)

        # 没有弹窗也没扫码，可能是直接进入下一步，继续等待结果
        return None

    # ═══════════════════════════════════════════════════════════
    # 等待发布结果
    # ═══════════════════════════════════════════════════════════

    async def _wait_for_publish_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果：检测成功/失败提示或 URL 跳转。"""
        last_url = page.url
        for tick in range(60):
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            # 失败检测
            for text in sel.FAIL_TEXT:
                try:
                    node = page.get_by_text(text, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        msg = (await node.inner_text()).strip()
                        logger.error(f"❌ [微信] 检测到失败提示: {msg}")
                        debug_path = await self._save_debug_snapshot(page, "wait_result_fail_text")
                        return {
                            "success": False,
                            "platform_url": page.url,
                            "error_msg": msg,
                            "debug_path": debug_path,
                        }
                except Exception:
                    continue

            # 成功检测
            for text in sel.SUCCESS_TEXT:
                try:
                    node = page.get_by_text(text, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        logger.success(f"🎉 [微信] 检测到成功提示: {text}")
                        return {"success": True, "platform_url": page.url}
                except Exception:
                    continue

            # URL 跳转
            if page.url != last_url:
                for pattern in sel.SUCCESS_URL_PATTERNS:
                    if re.search(pattern, page.url, re.IGNORECASE):
                        logger.success(f"🎉 [微信] 检测到跳转，认为发布成功: {page.url}")
                        return {"success": True, "platform_url": page.url}

            await asyncio.sleep(1)

        # 未检测到明确结果：返回失败，需要人工复核
        logger.warning("⏰ [微信] 60 秒内未检测到明确结果，需要人工复核")
        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": "未检测到明确的发布成功提示，请到微信公众号后台人工确认",
            "debug_path": debug_path,
        }

    # ═══════════════════════════════════════════════════════════
    # 辅助工具
    # ═══════════════════════════════════════════════════════════

    def _deep_clean_content(self, content: str) -> str:
        """清理 Markdown/HTML 内容，输出适合编辑器粘贴的纯文本。"""
        if not content:
            return ""
        text = content
        # 移除 Markdown 图片
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        # 处理 HTML
        # 与 base.markdown_to_plain_text 保持一致：标题/段落前后只留 1 个换行，
        # 不要 \n\n。富文本编辑器段落自带 margin，双换行会被放大成巨大空栏。
        text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n\1\n", text, flags=re.I | re.S)
        text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.I | re.S)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "", text)
        # 处理 Markdown 标题/强调
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # 移除首行 H1
        lines = text.splitlines()
        if lines and re.match(r"^#\s+", lines[0]):
            lines = lines[1:]
        # 折叠连续空行
        cleaned: List[str] = []
        prev_empty = False
        for line in lines:
            line = line.strip()
            if not line:
                if not prev_empty:
                    cleaned.append("")
                prev_empty = True
            else:
                cleaned.append(line)
                prev_empty = False
        return "\n".join(cleaned).strip()

    def _looks_like_manual_intervention(self, msg: str) -> bool:
        msg = (msg or "").lower()
        return any(
            key in msg
            for key in (
                "登录",
                "登陆",
                "login",
                "passport",
                "验证码",
                "验证",
                "captcha",
                "扫码",
                "二维码",
                "风控",
                "安全",
            )
        )


# ═══════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════

WEIXIN_CONFIG = {
    "id": "weixin",
    "name": "微信公众号",
    "code": "WX",
    "login_url": "https://mp.weixin.qq.com/",
    "home_url": "https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN",
    "publish_url": sel.DRAFT_BOX_URL,
    "color": "#07C160",
}

registry.register("weixin", WeixinPublisher("weixin", WEIXIN_CONFIG))
