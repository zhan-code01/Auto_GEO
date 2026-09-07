# -*- coding: utf-8 -*-
"""
百家号发布适配器 - v3.1 防闪退版

修复记录:
v3.1 (防闪退):
1. 移除 set_extra_http_headers 调用 —— 不再污染请求头，避免被反爬识别
2. 移除修改 navigator 的 stealth_vaccine —— 反而触发百家号反爬检测
3. 简化导航：一次 page.goto(networkidle) 到位，失败清晰提示
4. 登录态检测更宽容：等待页面稳定再判断，避免误判为闪退
5. 加入页面崩溃/多次重定向恢复机制
6. 关键操作加重试：导航、登录、封面、发布都允许重试

v3.0:
1. 删除 v17.0 老版本死代码 (重复方法定义)
2. 使用文章自带图片 (cover_path / 文章内嵌图片)，默认不在发布阶段生成替代图
3. 多级兜底：选择器 → 物理键盘 → JS 注入
4. 严格的发布结果验证
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
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

from . import baijiahao_selectors as sel
from .base import BasePublisher, registry
from .note_utils import generated_publish_images_enabled, materialize_images
from ..humanize import random_delay, short_delay


class BaijiahaoPublisher(BasePublisher):
    """百家号图文发布器 - v3.0"""

    MAX_TITLE_LENGTH = 64
    MAX_CONTENT_LENGTH = 20000

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
        stage = "init"
        try:
            logger.info("🚀 [百家号 v3.1] 开始发布图文文章 (防闪退版)")

            title = getattr(article, "title", "") or "未命名文章"
            content = getattr(article, "content", "") or ""

            # 0. 关键：注入极简 stealth（只设置 localStorage，不动 navigator）
            # 否则百家号会立即识别 Playwright 并跳登录页 = "闪退"
            stage = "stealth"
            await self._inject_minimal_stealth(page)

            # 1. 导航到编辑器（带重试）
            stage = "navigate"
            if not await self._navigate_to_editor(page):
                # 拆分模糊判断：确认落到登录页 = 确定登出；其余（网络/安全验证/编辑器迟迟不出现）= 不确定
                if self._is_on_login_page(page):
                    return await self._auth_failure(
                        page,
                        stage,
                        definitive=True,
                        message="无法进入百家号编辑器，已被重定向到登录页，登录态已失效，请重新授权",
                    )
                return await self._auth_failure(
                    page,
                    stage,
                    definitive=False,
                    message="无法进入百家号编辑器，疑似网络异常或安全验证，未判定账号失效",
                )
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            # 2. 登录态检测（更宽容）
            stage = "login_check"
            if not await self._ensure_logged_in(page):
                return await self._auth_failure(
                    page,
                    stage,
                    definitive=True,
                    message="百家号登录态失效，请到账号管理重新授权百家号",
                )
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, stage, manual_msg)

            # 3. 等待编辑器完全加载
            stage = "wait_editor"
            await self._wait_editor_ready(page)

            # 3.5 处理百家号写作引导流程（cheetah-tour 多步骤引导）
            # 必须在任何编辑器交互之前完成，否则遮罩会阻断所有操作
            stage = "dismiss_onboarding"
            await self._close_interference(page)

            # 4. 填写标题：先写入用户最关心的文本，不被封面/配图准备阻塞
            stage = "fill_title"
            await self._close_interference(page)
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "标题填写失败")

            # 5. 填写正文：默认纯文本最快；仅在文章本身带图时穿插图片
            stage = "prepare_content_images"
            content_image_paths, content_temp_files = await self._prepare_content_images(article, title)
            temp_files.extend(content_temp_files)
            if content_image_paths:
                logger.info(f"🖼️ [百家号] 已准备 {len(content_image_paths)} 张正文配图")

            # 6. 填写正文
            stage = "fill_content"
            await self._close_interference(page)
            if not await self._fill_content(page, content, image_paths=content_image_paths):
                return await self._fail(page, stage, "正文填写失败")

            # 7. 上传封面：放到标题/正文之后，避免封面图片下载拖慢首屏输入
            stage = "prepare_cover"
            cover_path = await self._resolve_cover(article, title)
            if cover_path:
                temp_files.append(cover_path)
                logger.info(f"📷 [百家号] 封面已准备: {cover_path}")

            stage = "upload_cover"
            if cover_path:
                await self._upload_cover(page, cover_path)
            await self._close_interference(page)

            # 8. 设置发布选项 (AI 声明等)
            stage = "set_options"
            await self._close_interference(page)
            await self._set_publish_options(page, declare_ai_content=declare_ai_content)
            await self._close_interference(page)

            # 9. 点击发布
            stage = "publish"
            await self._close_interference(page)
            if not await self._click_publish(page):
                return await self._fail(page, stage, "未找到可点击的发布按钮")

            # 10. 等待发布结果
            stage = "wait_result"
            return await self._wait_for_publish_result(page)

        except Exception as e:
            logger.exception(f"❌ [百家号] 发布失败 stage={stage}: {e}")
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

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        logger.error(f"❌ [百家号] stage={stage} 失败: {msg}")
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        return {
            "success": False,
            "error_msg": f"[{stage}] {msg}",
            "platform_url": getattr(page, "url", None),
            "debug_path": debug_path,
        }

    async def _manual_fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        """记录人工介入结果前先保存页面快照，便于事后定位登录/验证码/反爬卡点。"""
        debug_path = await self._save_debug_snapshot(page, f"manual_{stage}")
        result = self.manual_intervention_result(stage, message, page)
        result["debug_path"] = debug_path
        return result

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        """保存失败时的 HTML + 全页截图到 backend/debug/baijiahao/，供事后定位卡点。"""
        debug_dir = Path("backend/debug/baijiahao")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[百家号] 保存调试 HTML 失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[百家号] 保存调试截图失败: {}", exc)
        return str(html_path)

    # ═══════════════════════════════════════════════════════════
    # 防闪退：极简隐身疫苗
    # ═══════════════════════════════════════════════════════════

    async def _inject_minimal_stealth(self, page: Page) -> None:
        """
        极简隐身疫苗：只设置引导状态 localStorage，避免新手引导遮罩。
        不修改 navigator.webdriver 等属性 —— 那反而会被百家号检测到。
        """
        try:
            await page.add_init_script(
                """() => {
                    try {
                        // 跳过百家号的新手引导、AI 工具引导等弹窗
                        localStorage.setItem('BAIDU_BJ_GUIDE_STATE', 'true');
                        localStorage.setItem('BJ_TOUR_COMPLETED', 'true');
                        localStorage.setItem('ai_tool_guide_status', '1');
                        localStorage.setItem('first_login_flag', 'true');
                        localStorage.setItem('BJH_AI_ASSISTANT_GUIDE_DONE', '1');
                        localStorage.setItem('BJH_AI_TOOL_TOUR_DONE', '1');
                        localStorage.setItem('BJH_MATERIAL_RECOMMEND_GUIDE_DONE', '1');
                        localStorage.setItem('BJH_ONE_KEY_FILL_GUIDE_DONE', '1');
                        localStorage.setItem('BJH_AI_COVER_GUIDE_DONE', '1');
                    } catch (e) {}
                    window.__autogeoBjhCloseGuides = () => {
                        const texts = ['我知道了', '完成', '下一步', '知道了', '关闭', '跳过', '稍后再说', '不用了', '确定'];
                        const isVisible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
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
                                try {
                                    target.click();
                                    return true;
                                } catch (e) {}
                            }
                        }
                        return false;
                    };
                    window.__autogeoBjhGuideTimer = window.__autogeoBjhGuideTimer || setInterval(() => {
                        try { window.__autogeoBjhCloseGuides(); } catch (e) {}
                    }, 800);
                }"""
            )
            try:
                await page.evaluate(
                    """() => {
                        try {
                            localStorage.setItem('BAIDU_BJ_GUIDE_STATE', 'true');
                            localStorage.setItem('BJ_TOUR_COMPLETED', 'true');
                            localStorage.setItem('ai_tool_guide_status', '1');
                            localStorage.setItem('first_login_flag', 'true');
                            localStorage.setItem('BJH_AI_ASSISTANT_GUIDE_DONE', '1');
                            localStorage.setItem('BJH_AI_TOOL_TOUR_DONE', '1');
                            localStorage.setItem('BJH_MATERIAL_RECOMMEND_GUIDE_DONE', '1');
                            localStorage.setItem('BJH_ONE_KEY_FILL_GUIDE_DONE', '1');
                            localStorage.setItem('BJH_AI_COVER_GUIDE_DONE', '1');
                        } catch (e) {}
                        if (!window.__autogeoBjhCloseGuides) {
                            window.__autogeoBjhCloseGuides = () => {
                                const texts = ['我知道了', '完成', '下一步', '知道了', '关闭', '跳过', '稍后再说', '不用了', '确定'];
                                const isVisible = (el) => {
                                    const rect = el.getBoundingClientRect();
                                    const style = window.getComputedStyle(el);
                                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
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
                                        try {
                                            target.click();
                                            return true;
                                        } catch (e) {}
                                    }
                                }
                                return false;
                            };
                        }
                        window.__autogeoBjhGuideTimer = window.__autogeoBjhGuideTimer || setInterval(() => {
                            try { window.__autogeoBjhCloseGuides(); } catch (e) {}
                        }, 800);
                        const style = document.createElement('style');
                        style.setAttribute('data-autogeo-guide-hide', '1');
                        style.textContent = `
                            [class*="guide"], [class*="Guide"], [class*="tour"], [class*="Tour"],
                            [class*="coach"], [class*="Coach"], [class*="survey"], [class*="Survey"] {
                                pointer-events: none !important;
                            }
                        `;
                        document.head && document.head.appendChild(style);
                    }"""
                )
            except Exception:
                pass
            logger.info("💉 [百家号] 极简隐身疫苗已注入（仅 localStorage）")
        except Exception as e:
            logger.warning(f"⚠️ [百家号] 隐身疫苗注入失败（不阻断）: {e}")

    # ═══════════════════════════════════════════════════════════
    # 导航 & 登录（防闪退版）
    # ═══════════════════════════════════════════════════════════

    async def _navigate_to_editor(self, page: Page) -> bool:
        """
        导航到编辑器。返回 True/False，不抛异常 —— 让上层决定如何处理。
        防闪退策略：
          1. 不调用 set_extra_http_headers（污染请求头会被反爬识别）
          2. 直接 goto publish_url，networkidle 等页面完全加载
          3. 加载失败重试 2 次
          4. 检测到登录页立即返回 False，给用户清晰提示
        """
        edit_url = self.config.get(
            "publish_url",
            "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1",
        )

        last_error = ""
        for attempt in range(3):
            try:
                logger.info(f"[百家号] 导航到编辑器 (尝试 {attempt + 1}/3): {edit_url}")
                await page.goto(edit_url, wait_until="domcontentloaded", timeout=60000)

                # 等页面网络空闲（编辑器 SPA 需要时间初始化）
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    # networkidle 超时不致命，继续往下
                    logger.warning("[百家号] networkidle 等待超时，继续检测")

                await asyncio.sleep(2)

                await self._open_image_article_entry_if_needed(page)
                if await self._has_editor(page, timeout=3000):
                    logger.success("✅ [百家号] 已通过发布图文入口进入编辑器")
                    return True

                # 检测登录页（百家号反爬或 cookies 失效会跳登录）
                if self._is_login_url(page.url):
                    logger.error(f"❌ [百家号] 被重定向到登录页: {page.url}")
                    last_error = "登录态失效或被反爬拦截，请重新授权"
                    # 不再重试 goto，登录态不会因为重试就恢复
                    return False

                # 检测编辑器是否就位
                if await self._has_editor(page, timeout=3000):
                    logger.success("✅ [百家号] 已进入图文编辑器")
                    return True

                # 没到登录页但也没编辑器，可能是页面渲染慢，再等一轮
                logger.warning(f"⚠️ [百家号] 页面已加载但编辑器未出现，当前URL: {page.url}")
                await asyncio.sleep(3)
                if await self._has_editor(page, timeout=3000):
                    logger.success("✅ [百家号] 编辑器在等待后出现")
                    return True

            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ [百家号] 导航异常 (尝试 {attempt + 1}/3): {e}")
                await asyncio.sleep(2)

        logger.error(f"❌ [百家号] 3 次导航均失败。最后错误: {last_error}")
        return False

    async def _open_image_article_entry_if_needed(self, page: Page) -> None:
        """Click the '发布图文' entry only if we're on a landing page, not already in the editor."""
        # 如果已经在编辑页 URL，不需要找入口
        if "/builder/rc/edit" in page.url:
            return

        # 如果编辑器已加载，不需要
        if await self._has_editor(page, timeout=1000):
            return

        for selector in sel.IMAGE_ARTICLE_ENTRY:
            try:
                entry = page.locator(selector).first
                if await entry.count() > 0 and await entry.is_visible(timeout=1200):
                    text = (await entry.inner_text()).strip()
                    if text and "发布图文" not in text:
                        continue
                    await entry.click(force=True)
                    logger.info(f"[百家号] 已点击发布图文入口: {selector}")
                    await asyncio.sleep(2)
                    await self._close_interference(page)
                    return
            except Exception:
                continue

        try:
            clicked = await page.evaluate(
                """() => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden';
                    };
                    const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], div, span'))
                        .filter(el => visible(el) && (el.innerText || '').trim() === '发布图文');
                    const target = candidates[0];
                    if (!target) return false;
                    target.click();
                    return true;
                }"""
            )
            if clicked:
                logger.info("[百家号] 已通过 DOM 精确点击发布图文入口")
                await asyncio.sleep(2)
                await self._close_interference(page)
        except Exception:
            pass

    def _is_login_url(self, url: str) -> bool:
        url = (url or "").lower()
        return any(indicator in url for indicator in sel.LOGIN_URL_INDICATOR)

    async def _has_editor(self, page: Page, timeout: int = 2000) -> bool:
        """检测编辑器是否已渲染（支持 Lexical 标题 + UEditor 正文）"""
        # 当前版 (2026): Lexical 标题编辑器
        lexical_selectors = [
            '[data-lexical-editor="true"]',
            '[data-testid="news-title-input"]',
        ]
        for selector in lexical_selectors:
            try:
                node = page.locator(selector).first
                if await node.count() > 0 and await node.is_visible(timeout=timeout):
                    return True
            except Exception:
                continue

        # 当前版 (2026): UEditor 容器
        ueditor_selectors = [
            "iframe#ueditor_0",
            "#ueditor",
            "#edui1_iframeholder",
        ]
        for selector in ueditor_selectors:
            try:
                node = page.locator(selector).first
                if await node.count() > 0:
                    return True
            except Exception:
                continue

        # 旧版兼容: 标题 textarea/input
        for selector in sel.TITLE_INPUT[3:]:
            try:
                node = page.locator(selector).first
                if await node.count() > 0 and await node.is_visible(timeout=500):
                    return True
            except Exception:
                continue

        # 旧版兼容: 正文 textarea/contenteditable
        for selector in sel.CONTENT_INPUT[3:]:
            try:
                node = page.locator(selector).first
                if await node.count() > 0 and await node.is_visible(timeout=500):
                    return True
            except Exception:
                continue

        # 文字兜底: 页面中是否包含"请输入标题"或"请输入正文"
        for text in ["请输入标题", "请输入正文"]:
            try:
                node = page.get_by_text(text, exact=False).first
                if await node.count() > 0 and await node.is_visible(timeout=500):
                    return True
            except Exception:
                continue

        # 检测"发布"按钮存在 + URL 正确 → 编辑器已加载
        try:
            url = page.url
            if "baijiahao.baidu.com/builder/rc/edit" in url:
                publish_btn = page.locator('[data-testid="publish-btn"]').first
                if await publish_btn.count() > 0:
                    return True
        except Exception:
            pass

        return False

    async def _wait_editor_ready(self, page: Page, max_wait: int = 20) -> None:
        """等待编辑器真正可交互（防闪退：给页面充足时间）"""
        for tick in range(max_wait):
            if await self._has_editor(page, timeout=500):
                return
            await asyncio.sleep(1)
        logger.warning(f"⚠️ [百家号] 编辑器 {max_wait}s 内未稳定渲染，继续尝试")

    async def _ensure_logged_in(self, page: Page) -> bool:
        """
        登录态检测（宽容版）：
          1. URL 跳到登录页 → 失败
          2. 有任何登录成功标识 → 通过
          3. 既没跳登录页，编辑器又存在 → 通过
        """
        if self._is_login_url(page.url):
            return False

        # 检查登录成功标识（任意一个匹配就 OK）
        for selector in sel.LOGIN_SUCCESS_ELEMENT[:6]:
            try:
                el = page.locator(selector).first
                if await el.count() > 0:
                    logger.info("✅ [百家号] 检测到登录态标识")
                    return True
            except Exception:
                continue

        # 兜底：编辑器存在意味着已登录（百家号编辑器必须登录才能看到）
        if await self._has_editor(page, timeout=2000):
            logger.info("✅ [百家号] 编辑器存在，认为已登录")
            return True

        logger.warning("⚠️ [百家号] 无法确认登录态")
        return False

    async def _dismiss_onboarding_tour(self, page: Page) -> bool:
        """
        专门处理百家号 cheetah-tour 多步骤引导流程（1/4 → 2/4 → 3/4 → 4/4）。

        百家号的写作引导流程特点：
          - 全屏半透明遮罩 (cheetah-tour-mask) z-index 1001 阻断所有交互
          - 多步骤：每步有"下一步"/"上一步"/"完成"按钮
          - 步骤指示器显示 "1/4", "2/4" 等
          - 引导结束后可能弹出 cheetah-popconfirm（功能提示）

        Returns:
            True 如果成功处理了引导流程，False 如果没有检测到引导
        """
        max_rounds = 8  # 最多处理 8 轮引导（每轮可能包含多步）
        total_steps_clicked = 0

        for round_idx in range(max_rounds):
            # 先检测是否还有引导浮层
            has_tour, has_popconfirm = await self._detect_onboarding(page)
            if not has_tour and not has_popconfirm:
                if round_idx == 0:
                    logger.info("[百家号] 未检测到引导流程，跳过")
                    return False
                else:
                    logger.success(f"[百家号] 引导流程已全部处理完成 (共 {total_steps_clicked} 步)")
                    return True

            if has_tour:
                logger.info(f"[百家号] 第 {round_idx + 1} 轮: 检测到 cheetah-tour 引导浮层")
                steps_in_round = await self._click_through_tour_steps(page)
                total_steps_clicked += steps_in_round
                if steps_in_round == 0:
                    # 点击失败，尝试暴力移除遮罩
                    await self._remove_tour_mask(page)

            if has_popconfirm:
                logger.info(f"[百家号] 第 {round_idx + 1} 轮: 检测到 popconfirm 功能提示")
                await self._dismiss_popconfirm(page)

            # 等待动画
            await asyncio.sleep(0.8)

            # 如果这轮什么都没处理掉，尝试强制移除
            still_has_tour, still_has_popconfirm = await self._detect_onboarding(page)
            if still_has_tour:
                await self._remove_tour_mask(page)
            if still_has_popconfirm:
                await self._dismiss_popconfirm(page, force=True)

        # 最后再检查一次
        has_tour, has_popconfirm = await self._detect_onboarding(page)
        if has_tour:
            await self._remove_tour_mask(page)
            await asyncio.sleep(0.5)
        if has_popconfirm:
            await self._dismiss_popconfirm(page, force=True)

        logger.info(f"[百家号] 引导流程处理完毕，共点击 {total_steps_clicked} 步")
        return total_steps_clicked > 0

    async def _detect_onboarding(self, page: Page) -> tuple:
        """检测当前页面是否有 cheetah-tour 遮罩或 popconfirm"""
        has_tour = False
        has_popconfirm = False

        # 检测 cheetah-tour-mask
        try:
            mask = page.locator(sel.CHEETAH_TOUR_MASK)
            count = await mask.count()
            if count > 0:
                for i in range(count):
                    if await mask.nth(i).is_visible(timeout=300):
                        has_tour = True
                        break
        except Exception:
            pass

        # 检测 cheetah-popconfirm
        try:
            popconfirm = page.locator(sel.CHEETAH_POPCONFIRM)
            count = await popconfirm.count()
            if count > 0:
                for i in range(count):
                    if await popconfirm.nth(i).is_visible(timeout=300):
                        has_popconfirm = True
                        break
        except Exception:
            pass

        # 文字兜底检测
        if not has_tour:
            for text in sel.GUIDE_INDICATOR_TEXTS:
                try:
                    node = page.get_by_text(text, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=200):
                        # 确认文字在 tour/popconfirm 容器内
                        parent_class = await node.evaluate(
                            "el => (el.closest('.cheetah-tour, .cheetah-popconfirm, .cheetah-tour-mask') || {}).className || ''"
                        )
                        if parent_class:
                            has_tour = True
                            break
                except Exception:
                    continue

        return has_tour, has_popconfirm

    async def _click_through_tour_steps(self, page: Page) -> int:
        """
        点击引导流程的每一步，直到没有更多步骤。
        返回点击的步数。
        """
        steps_clicked = 0
        max_steps = 10  # 单轮最多 10 步

        for _ in range(max_steps):
            # 每步操作前先短暂等待，让动画完成
            await asyncio.sleep(0.4)

            # 先尝试点击"完成"/"我知道了"（结束引导）
            clicked_done = await self._click_tour_button(page, sel.CHEETAH_TOUR_DONE_BTN, "完成")
            if clicked_done:
                steps_clicked += 1
                await asyncio.sleep(0.6)
                # 检查引导是否已消失
                has_tour, _ = await self._detect_onboarding(page)
                if not has_tour:
                    return steps_clicked
                continue

            # 尝试点击关闭按钮
            clicked_close = await self._click_tour_button(page, sel.CHEETAH_TOUR_CLOSE_BTN, "关闭")
            if clicked_close:
                steps_clicked += 1
                await asyncio.sleep(0.6)
                has_tour, _ = await self._detect_onboarding(page)
                if not has_tour:
                    return steps_clicked
                continue

            # 点击"下一步"
            clicked_next = await self._click_tour_button(page, sel.CHEETAH_TOUR_NEXT_BTN, "下一步")
            if clicked_next:
                steps_clicked += 1
                continue

            # 如果"下一步"也点击不了，尝试"上一步"然后"下一步"（某些步骤可能卡住）
            clicked_prev = await self._click_tour_button(page, sel.CHEETAH_TOUR_PREV_BTN, "上一步")
            if clicked_prev:
                steps_clicked += 1
                continue

            # 都没点到，可能引导已经消失或按钮不可见
            break

        return steps_clicked

    async def _click_tour_button(self, page: Page, selectors: List[str], label: str) -> bool:
        """尝试点击 tour 相关的按钮"""
        for selector in selectors:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=500):
                    await btn.click(force=True)
                    logger.info(f"[百家号] 已点击引导按钮: {label} ({selector})")
                    return True
            except Exception:
                continue

        # JS 兜底：直接在 DOM 中查找并点击
        try:
            clicked = await page.evaluate(
                """(label) => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && style.opacity !== '0';
                    };
                    const tourFooter = document.querySelector('.cheetah-tour-footer');
                    if (!tourFooter || !visible(tourFooter)) return false;
                    const buttons = tourFooter.querySelectorAll('button');
                    for (const btn of buttons) {
                        if (!visible(btn)) continue;
                        const text = (btn.innerText || '').trim();
                        if (text === label || (label === '完成' && ['完成', '我知道了', '知道了'].includes(text))) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                label,
            )
            if clicked:
                logger.info(f"[百家号] 已通过 JS 点击引导按钮: {label}")
                return True
        except Exception:
            pass

        return False

    async def _dismiss_popconfirm(self, page: Page, force: bool = False) -> bool:
        """关闭 popconfirm 弹窗"""
        for selector in sel.CHEETAH_POPCONFIRM_CONFIRM_BTN:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=500):
                    await btn.click(force=True)
                    logger.info(f"[百家号] 已关闭 popconfirm: {selector}")
                    await asyncio.sleep(0.5)
                    return True
            except Exception:
                continue

        # JS 兜底
        try:
            clicked = await page.evaluate(
                """() => {
                    const popconfirm = document.querySelector('.cheetah-popconfirm');
                    if (!popconfirm) return false;
                    const style = window.getComputedStyle(popconfirm);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const buttons = popconfirm.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = (btn.innerText || '').trim();
                        if (['我知道了', '知道了', '确定'].includes(text)) {
                            btn.click();
                            return true;
                        }
                    }
                    // 点击最后一个按钮
                    if (buttons.length > 0) {
                        buttons[buttons.length - 1].click();
                        return true;
                    }
                    return false;
                }"""
            )
            if clicked:
                logger.info("[百家号] 已通过 JS 关闭 popconfirm")
                await asyncio.sleep(0.5)
                return True
        except Exception:
            pass

        if force:
            # 暴力移除 popconfirm 元素
            try:
                await page.evaluate(
                    """() => {
                        const popconfirms = document.querySelectorAll('.cheetah-popconfirm');
                        popconfirms.forEach(el => { try { el.remove(); } catch(e) {} });
                    }"""
                )
                logger.info("[百家号] 已强制移除 popconfirm 元素")
            except Exception:
                pass

        return False

    async def _remove_tour_mask(self, page: Page) -> None:
        """强制移除 cheetah-tour-mask 遮罩（当点击按钮无效时的兜底方案）"""
        try:
            removed = await page.evaluate(
                """() => {
                    let count = 0;
                    // 移除所有 tour mask
                    document.querySelectorAll('.cheetah-tour-mask').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    // 移除所有 tour 浮层（保留可能含有的编辑器内容）
                    document.querySelectorAll('.cheetah-tour[class*="placement"]').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    // 移除 target placeholder
                    document.querySelectorAll('.cheetah-tour-target-placeholder').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    // 恢复 body 滚动和交互
                    document.body.style.overflow = '';
                    document.body.style.pointerEvents = '';
                    document.documentElement.style.overflow = '';
                    return count;
                }"""
            )
            if removed:
                logger.info(f"[百家号] 已强制移除 {removed} 个 tour 遮罩/浮层元素")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"[百家号] 移除 tour mask 失败: {e}")

    async def _close_interference(self, page: Page) -> None:
        """关闭干扰弹窗（新手引导、活动提示等）"""
        # 先尝试专门处理 cheetah-tour 引导流程
        await self._dismiss_onboarding_tour(page)

        # 百家号 AI 工具引导通常是 1/4 多步浮层，按钮不一定是 button。
        for _ in range(18):
            handled = False
            try:
                handled = bool(
                    await page.evaluate("window.__autogeoBjhCloseGuides && window.__autogeoBjhCloseGuides()")
                )
                if handled:
                    logger.info("[百家号] 已通过页面脚本处理引导控件")
                    await short_delay()
                    continue
            except Exception:
                pass

            if not handled:
                handled = await self._click_guide_control(page)

            if handled:
                continue

            for btn_selector in sel.CLOSE_POPUP_BTN:
                try:
                    btn = page.locator(btn_selector).last
                    if await btn.count() > 0 and await btn.is_visible(timeout=800):
                        await btn.click(force=True)
                        logger.info(f"[百家号] 已处理干扰弹窗: {btn_selector}")
                        await short_delay()
                        handled = True
                        break
                except Exception:
                    continue

            if not handled:
                break

        # JS 兜底：移除高 z-index 遮罩
        await self._force_clear_guides(page)

        # Esc 关闭浮层
        for _ in range(3):
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
            except Exception:
                break

        await self._force_clear_guides(page)

        # 最后再检查一次 cheetah-tour 遮罩
        await self._dismiss_onboarding_tour(page)

    async def _click_guide_control(self, page: Page) -> bool:
        """Click non-button controls in Baijiahao's onboarding popovers."""
        guide_texts = [
            "我知道了",
            "完成",
            "下一步",
            "知道了",
            "关闭",
            "跳过",
            "不用了",
            "稍后再说",
            "确定",
            "开始体验",
            "立即体验",
            "收起",
        ]
        component_selectors = [
            ".cheetah-tour-footer .cheetah-btn-primary",
            ".cheetah-tour-footer button",
            ".cheetah-tour-close",
            ".cheetah-popover button",
            ".cheetah-tooltip button",
            ".cheetah-modal-close",
            '[class*="tour"] [class*="close"]',
            '[class*="popover"] [class*="close"]',
        ]
        for selector in component_selectors:
            try:
                locator = page.locator(selector).last
                if await locator.count() > 0 and await locator.is_visible(timeout=500):
                    await locator.click(force=True)
                    logger.info(f"[百家号] 已点击引导组件控件: {selector}")
                    await short_delay()
                    return True
            except Exception:
                continue

        for text in guide_texts:
            try:
                clicked = await page.evaluate(
                    """(text) => {
                        const isVisible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0
                                && style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && style.opacity !== '0';
                        };
                        const score = (el) => {
                            const rect = el.getBoundingClientRect();
                            const tag = el.tagName.toLowerCase();
                            const cls = String(el.className || '').toLowerCase();
                            const role = el.getAttribute('role') || '';
                            let s = 0;
                            if (tag === 'button') s += 100;
                            if (role === 'button') s += 90;
                            if (/btn|button|primary|confirm|next|footer/.test(cls)) s += 60;
                            if (rect.width >= 36 && rect.width <= 220 && rect.height >= 22 && rect.height <= 80) s += 40;
                            if (rect.left > window.innerWidth * 0.15 && rect.top > window.innerHeight * 0.1) s += 10;
                            if (/tour|popover|tooltip|modal/.test(cls)) s += 40;
                            s -= Math.min((el.innerText || '').length, 100);
                            return s;
                        };
                        const candidates = Array.from(document.querySelectorAll('button, [role="button"], a, span, div'))
                            .filter(el => {
                                const value = (el.innerText || el.textContent || '').trim();
                                if (!isVisible(el) || !value.includes(text)) return false;
                                const cls = String(el.className || '').toLowerCase();
                                const parentCls = String(el.parentElement && el.parentElement.className || '').toLowerCase();
                                const compact = value.length <= Math.max(text.length + 8, 20);
                                const inGuide = /tour|popover|tooltip|modal|guide|coach/.test(cls + ' ' + parentCls);
                                return compact || inGuide;
                            })
                            .sort((a, b) => score(b) - score(a));
                        const target = candidates[0];
                        if (!target) return false;
                        target.scrollIntoView({block: 'center', inline: 'center'});
                        target.click();
                        return true;
                    }""",
                    text,
                )
                if clicked:
                    logger.info(f"[百家号] 已通过 DOM 点击引导控件: {text}")
                    await short_delay()
                    return True
            except Exception:
                pass

            locators = [
                page.locator(f'[role="button"]:has-text("{text}")').last,
                page.locator(f'button:has-text("{text}")').last,
                page.locator(f'a:has-text("{text}")').last,
                page.locator(f'span:has-text("{text}")').last,
                page.locator(f'div:has-text("{text}")').last,
                page.get_by_text(text, exact=True).last,
                page.locator(f'text="{text}"').last,
            ]
            for locator in locators:
                try:
                    if await locator.count() > 0 and await locator.is_visible(timeout=500):
                        box = await locator.bounding_box()
                        if box:
                            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        else:
                            await locator.click(force=True)
                        logger.info(f"[百家号] 已点击引导控件: {text}")
                        await short_delay()
                        return True
                except Exception:
                    continue

        try:
            close = page.locator(
                '[aria-label="Close"], [aria-label="close"], '
                '[class*="close"], svg[class*="close"], i[class*="close"], '
                '.client_layouts_fixedBottom [alt="Collapse"], .ai_func_fixed_bottom_mark [class*="close"]'
            ).last
            if await close.count() > 0 and await close.is_visible(timeout=500):
                await close.click(force=True)
                await short_delay()
                return True
        except Exception:
            pass

        return False

    async def _force_clear_guides(self, page: Page) -> None:
        """Aggressively remove Baijiahao onboarding/survey overlays and cheetah-tour masks."""
        try:
            removed = await page.evaluate(
                """() => {
                    // 优先移除 cheetah-tour-mask (全屏遮罩 z-index:1001)
                    let count = 0;
                    document.querySelectorAll('.cheetah-tour-mask').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    // 移除 cheetah-tour 浮层
                    document.querySelectorAll('.cheetah-tour[class*="placement"]').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    // 移除 target placeholder
                    document.querySelectorAll('.cheetah-tour-target-placeholder').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    // 移除 popconfirm
                    document.querySelectorAll('.cheetah-popconfirm').forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    });
                    if (count > 0) return count;

                    const keywords = [
                        '下一步', '上一步', '完成', '知道了', '我知道了', '新手引导', '开始创作',
                        'AI工具', 'AI工具收起', '升级为AI封面', '新增智能配图',
                        '续写与润色', '点击展开', '引导', '1/4', '2/4', '3/4', '4/4',
                        '操作成功', '热点创作', '有奖调研', '非常不同意', '非常认同',
                        '推荐素材', '检测建议', '手机查看', '规则中心', '一键填写功能', '一键填写'
                    ];
                    const protectedSelectors = [
                        'textarea', 'input', '[contenteditable="true"]', 'form',
                        '#formMain', '#desc', '[data-testid="publish-btn"]',
                        '.editor-component-operator', '.left-area-content-box'
                    ];
                    const removed_el = new Set();
                    const markRemove = (el) => {
                        if (!el || el === document.body || el === document.documentElement) return;
                        if (protectedSelectors.some(selector => el.matches?.(selector) || el.querySelector?.(selector))) return;
                        removed_el.add(el);
                    };
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const meaningfulAncestor = (el) => {
                        let cur = el;
                        for (let i = 0; i < 6 && cur && cur.parentElement; i += 1) {
                            const style = window.getComputedStyle(cur);
                            const rect = cur.getBoundingClientRect();
                            const cls = String(cur.className || '').toLowerCase();
                            const role = cur.getAttribute('role') || '';
                            const positioned = ['fixed', 'absolute', 'sticky'].includes(style.position);
                            const named = /cheetah-tour|cheetah-popover|popover|tooltip|guide|modal|dialog|mask|overlay|tour|coach|drawer/.test(cls);
                            if (role === 'dialog' || named || positioned || parseInt(style.zIndex || '0') > 50) {
                                return cur;
                            }
                            if (rect.width > 120 && rect.height > 80 && rect.width < window.innerWidth * 0.95) {
                                return cur;
                            }
                            cur = cur.parentElement;
                        }
                        return el;
                    };

                    Array.from(document.querySelectorAll('*')).forEach(el => {
                        try {
                            if (!isVisible(el)) return;
                            const text = (el.innerText || el.textContent || '').trim();
                            if (!text || !keywords.some(kw => text.includes(kw))) return;
                            markRemove(meaningfulAncestor(el));
                        } catch (e) {}
                    });

                    Array.from(document.querySelectorAll('*')).forEach(el => {
                        try {
                            if (!isVisible(el)) return;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            const z = parseInt(style.zIndex || '0');
                            const bg = style.backgroundColor || '';
                            const fullScreen = rect.width >= window.innerWidth * 0.75 && rect.height >= window.innerHeight * 0.75;
                            const blocker = fullScreen && ['fixed', 'absolute'].includes(style.position)
                                && (z > 10 || bg.includes('rgba') || bg.includes('rgb(0'));
                            const cls = String(el.className || '').toLowerCase();
                            if (blocker || /cheetah-tour|cheetah-popover|mask|overlay|modal|guide|tour|coach/.test(cls)) {
                                markRemove(el);
                            }
                        } catch (e) {}
                    });

                    removed_el.forEach(el => {
                        try { el.remove(); } catch (e) {}
                    });
                    document.body.style.overflow = 'auto';
                    document.body.style.pointerEvents = 'auto';
                    document.documentElement.style.overflow = 'auto';
                    return removed_el.size + count;
                }"""
            )
            if removed:
                logger.info(f"[百家号] 强制清理引导/遮罩节点: {removed}")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 封面准备
    # ═══════════════════════════════════════════════════════════

    async def _resolve_cover(self, article: Any, title: str) -> Optional[str]:
        """
        优先使用文章自带图片：
          1. article.cover_path / cover_image_path / cover
          2. 文章内容里嵌入的图片 (Markdown / HTML)
          3. 显式开启时兜底：pollinations.ai 生成
        """
        # 1. 显式封面字段
        for attr in ("cover_path", "cover_image_path", "cover", "cover_image"):
            value = getattr(article, attr, None)
            if isinstance(value, str) and value.strip() and os.path.exists(value):
                logger.info(f"[百家号] 使用文章封面字段: {value}")
                return value

        # 2. 文章内嵌图片
        try:
            image_paths, _temp = await materialize_images(article, limit=1)
            if image_paths:
                logger.info(f"[百家号] 使用文章内嵌图片作为封面: {image_paths[0]}")
                return image_paths[0]
        except Exception as e:
            logger.warning(f"[百家号] 提取内嵌图片失败: {e}")

        # 3. 默认不在线生成封面，避免发布页首屏长时间等待网络图片。
        if self.config.get("auto_generate_cover", False) and generated_publish_images_enabled(self.config):
            return await self._download_cover_fallback(title)
        if self.config.get("auto_generate_cover", False):
            logger.info("[百家号] 未找到文章自带封面，跳过发布阶段替代封面生成")
        logger.info("[百家号] 未找到文章自带封面，跳过封面上传")
        return None

    async def _download_cover_fallback(self, title: str) -> Optional[str]:
        """AI 生成封面图作为兜底"""
        keyword = self._extract_keyword(title)
        encoded = urllib.parse.quote(f"{keyword} article cover {random.randint(1, 10000)}")

        candidates = [
            f"https://image.pollinations.ai/prompt/{encoded}?width=1200&height=630&nologo=true",
            f"https://picsum.photos/1200/630?random={random.randint(1, 100000)}",
        ]

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(headers=headers, verify=False, timeout=30.0) as client:
            for url in candidates:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.content) > 2000:
                        path = os.path.join(
                            tempfile.gettempdir(),
                            f"bjh_cover_{random.randint(10000, 99999)}.jpg",
                        )
                        with open(path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"[百家号] AI 兜底封面已下载: {path}")
                        return path
                except Exception as e:
                    logger.warning(f"[百家号] 兜底图源失败 {url[:80]}: {e}")
                    continue
        return None

    def _extract_keyword(self, title: str) -> str:
        cleaned = re.sub(r"[^\w一-鿿]", " ", title or "")
        words = [w for w in cleaned.split() if w]
        if not words:
            return "风景"
        return words[0] if len(words) == 1 else f"{words[0]} {words[1]}"

    # ═══════════════════════════════════════════════════════════
    # 正文配图准备
    # ═══════════════════════════════════════════════════════════

    async def _prepare_content_images(self, article: Any, title: str) -> tuple[List[str], List[str]]:
        """
        准备正文配图：文章自带图，默认不生成替代配图。
        返回 (image_paths, temp_files_to_cleanup)。
        """
        # 1. 文章自带图（content 内嵌 Markdown/HTML 图、article 字段、本地/外链/base64 均已处理）
        try:
            image_paths, temp_files = await materialize_images(article, limit=9)
        except Exception as exc:
            logger.warning(f"[百家号] 提取自带图片失败: {exc}")
            image_paths, temp_files = [], []

        # 2. 默认不在线生成正文配图，避免第一个输入页长时间等待。
        if (
            not image_paths
            and self.config.get("auto_generate_inline_images", False)
            and generated_publish_images_enabled(self.config)
        ):
            keyword = self._extract_keyword(title)
            ai_paths = await self._download_inline_images(keyword, count=3)
            image_paths = ai_paths
            temp_files = list(ai_paths)
        elif not image_paths and self.config.get("auto_generate_inline_images", False):
            logger.warning("[百家号] 图片下载失败，尝试继续发布（可能无图）...")

        return image_paths, temp_files

    async def _download_inline_images(self, keyword: str, count: int = 3) -> List[str]:
        """文章无自带图时，用 pollinations.ai + picsum 生成 N 张正文配图（兜底）。"""
        paths: List[str] = []
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(headers=headers, verify=False, timeout=45.0, follow_redirects=True) as client:
            for index in range(max(0, count)):
                seed = random.randint(1, 100000)
                prompt = urllib.parse.quote(f"{keyword} article illustration {index + 1} seed {seed}")
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
                        fd, path = tempfile.mkstemp(prefix="bjh_inline_", suffix=suffix)
                        with os.fdopen(fd, "wb") as file:
                            file.write(resp.content)
                        paths.append(path)
                        logger.info(f"[百家号] 已生成正文配图 {index + 1}/{count}: {path}")
                        break
                    except Exception as exc:
                        logger.warning(f"[百家号] 正文配图下载失败: {exc}")
        return paths

    def _build_content_blocks(self, content: str, image_paths: List[str]) -> List[Dict[str, str]]:
        """
        把 content 按图片标记位置切成 text/image 块，保持图文相对顺序。
        多于标记位的图片追加到末尾（移植自 bilibili._build_content_blocks）。
        """
        blocks: List[Dict[str, str]] = []
        image_index = 0
        pattern = re.compile(
            r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)"
            r"|<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>",
            flags=re.IGNORECASE,
        )
        cursor = 0
        for match in pattern.finditer(content or ""):
            text = self._deep_clean_content((content or "")[cursor : match.start()])
            if text:
                blocks.append({"type": "text", "content": text})
            if image_index < len(image_paths):
                blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1
            cursor = match.end()

        text = self._deep_clean_content((content or "")[cursor:])
        if text:
            blocks.append({"type": "text", "content": text})

        while image_index < len(image_paths):
            blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1

        return blocks

    # ═══════════════════════════════════════════════════════════
    # 标题 & 正文
    # ═══════════════════════════════════════════════════════════

    async def _fill_title(self, page: Page, title: str) -> bool:
        """填写标题：Lexical 编辑器 → 旧版选择器 → JS 注入"""
        clean = re.sub(r"[#*`\"<>]", "", title or "").strip()[: self.MAX_TITLE_LENGTH]
        if not clean:
            logger.error("❌ [百家号] 标题为空")
            return False

        # L0: 当前版 Lexical 编辑器 (2026) — contenteditable div
        lexical_selectors = [
            '[data-lexical-editor="true"]',
            '[data-testid="news-title-input"] [contenteditable="true"]',
            'div[class*="titleInput"] [contenteditable="true"]',
        ]
        for selector in lexical_selectors:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                    await loc.click(force=True)
                    await short_delay()
                    # 全选 + 删除现有内容
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await short_delay()
                    # 使用 insert_text 输入（支持中文）
                    try:
                        await page.keyboard.insert_text(clean)
                    except Exception:
                        await page.keyboard.type(clean, delay=20)
                    await short_delay()
                    logger.info(f"✅ [百家号] 标题已填写 (Lexical): {clean}")
                    return True
            except Exception:
                continue

        # L1: 旧版选择器定位
        for selector in sel.TITLE_INPUT[3:]:  # 跳过 Lexical 选择器
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
                    logger.info(f"✅ [百家号] 标题已填写 (selector): {clean}")
                    return True
            except Exception:
                continue

        # L2: JS 兜底（增强：不依赖 placeholder 属性，也检查相邻文本）
        ok = await page.evaluate(
            """(title) => {
                // 优先查找 Lexical 编辑器
                const lexical = document.querySelector('[data-lexical-editor="true"]');
                if (lexical) {
                    lexical.focus();
                    lexical.innerHTML = '';
                    const p = document.createElement('p');
                    p.setAttribute('dir', 'auto');
                    p.innerHTML = '<span data-lexical-text="true">' + title + '</span>';
                    lexical.appendChild(p);
                    lexical.dispatchEvent(new InputEvent('input', {
                        bubbles: true, inputType: 'insertText', data: title
                    }));
                    lexical.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
                // 旧版兼容: 查找带 placeholder 的元素
                const candidates = Array.from(
                    document.querySelectorAll('textarea, input, [contenteditable="true"]')
                );
                // 尝试通过 placeholder 属性匹配
                let el = candidates.find(node => {
                    const ph = node.getAttribute('placeholder')
                        || node.getAttribute('data-placeholder') || '';
                    return ph.includes('标题');
                });
                // 尝试通过相邻文本节点匹配
                if (!el) {
                    el = candidates.find(node => {
                        const prev = node.previousElementSibling;
                        const parent = node.parentElement;
                        const nearbyText = (prev ? prev.innerText : '')
                            + (parent ? parent.innerText : '');
                        return nearbyText.includes('标题') && nearbyText.length < 50;
                    });
                }
                // 最后尝试: 取第一个可见的 contenteditable（非 iframe 内）
                if (!el) {
                    el = candidates.find(node => {
                        const rect = node.getBoundingClientRect();
                        return rect.width > 100 && rect.height > 20
                            && rect.height < 100
                            && node.closest('iframe') === null;
                    });
                }
                if (!el) return false;
                el.focus();
                if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
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
            logger.info(f"✅ [百家号] 标题已填写 (JS 兜底): {clean}")
        return bool(ok)

    async def _fill_content(self, page: Page, content: str, image_paths: Optional[List[str]] = None) -> bool:
        """
        正文填充：
          - 有配图：图文穿插（_fill_content_with_images），失败降级到纯文字
          - 无配图 / 降级：四级纯文字填充
            L0: UEditor API (当前版 2026) → setContent(html)
            L1: iframe body 直接注入 innerHTML
            L2: 旧版富文本编辑器 → keyboard.insert_text / type
            L3: textarea → fill
            L4: JS evaluate 注入 innerHTML
        """
        # 过滤掉不存在的图片（下载/物化失败）
        valid_images = [p for p in (image_paths or []) if p and os.path.exists(p)]
        if valid_images:
            try:
                if await self._fill_content_with_images(page, content, valid_images):
                    return True
                logger.warning("[百家号] 图文穿插写入失败，降级为纯文字正文")
            except Exception as exc:
                logger.warning(f"[百家号] 图文穿插异常，降级为纯文字正文: {exc}")
                await self._save_debug_snapshot(page, "content_with_images_fallback")

        clean = self._deep_clean_content(content or "")
        clean = clean[: self.MAX_CONTENT_LENGTH]
        if not clean.strip():
            logger.error("❌ [百家号] 正文为空")
            return False

        # 构建 HTML：段落用 <p> 包裹
        paragraphs = clean.split("\n\n") if "\n\n" in clean else clean.split("\n")
        html_content = "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
        if not html_content:
            html_content = f"<p>{clean}</p>"

        # ═══ L0: UEditor API (当前版 2026) ═══
        try:
            ue_ok = await page.evaluate(
                """(html) => {
                    try {
                        // 标准 UEditor API
                        const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
                        if (ue && typeof ue.setContent === 'function') {
                            ue.setContent(html);
                            // 触发 ready 事件让编辑器同步
                            ue.fireEvent && ue.fireEvent('contentchange');
                            return true;
                        }
                    } catch(e) {}
                    return false;
                }""",
                html_content,
            )
            if ue_ok:
                await short_delay()
                logger.info(f"✅ [百家号] 正文已填写 - L0 UEditor API ({len(clean)} 字符)")
                return True
        except Exception as e:
            logger.debug(f"[百家号] UEditor API 不可用: {e}")

        # ═══ L1: iframe body 直接注入 ═══
        try:
            iframe_ok = await page.evaluate(
                """(html) => {
                    try {
                        const iframe = document.querySelector('iframe#ueditor_0');
                        if (!iframe || !iframe.contentDocument) return false;
                        const body = iframe.contentDocument.body;
                        if (!body) return false;
                        body.innerHTML = html;
                        // 触发 input 事件让 UEditor 感知变化
                        body.dispatchEvent(new InputEvent('input', {
                            bubbles: true, inputType: 'insertText'
                        }));
                        body.dispatchEvent(new Event('change', {bubbles: true}));
                        // 同步到 UEditor
                        try {
                            const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
                            if (ue && typeof ue.sync === 'function') ue.sync('iframebody');
                        } catch(e) {}
                        return true;
                    } catch(e) { return false; }
                }""",
                html_content,
            )
            if iframe_ok:
                await short_delay()
                logger.info(f"✅ [百家号] 正文已填写 - L1 iframe body ({len(clean)} 字符)")
                return True
        except Exception as e:
            logger.debug(f"[百家号] iframe body 注入失败: {e}")

        # ═══ L2: 旧版富文本编辑器 ═══
        for selector in sel.CONTENT_INPUT[3:]:  # 跳过 iframe/#ueditor 选择器
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
                    logger.info(f"✅ [百家号] 正文已填写 - L2 ({len(clean)} 字符)")
                    return True
            except Exception:
                continue

        # ═══ L3: textarea ═══
        for selector in [
            'textarea[placeholder*="请输入正文"]',
            'textarea[placeholder*="正文"]',
            "#desc",
        ]:
            try:
                editor = page.locator(selector).first
                if await editor.count() > 0 and await editor.is_visible(timeout=2000):
                    await editor.fill(clean)
                    logger.info(f"✅ [百家号] 正文已填写 - L3 textarea ({len(clean)} 字符)")
                    return True
            except Exception:
                continue

        # ═══ L4: JS 注入（增强：优先查找 iframe body） ═══
        ok = await page.evaluate(
            """(text) => {
                // 优先尝试 iframe body
                try {
                    const iframe = document.querySelector('iframe#ueditor_0');
                    if (iframe && iframe.contentDocument && iframe.contentDocument.body) {
                        const body = iframe.contentDocument.body;
                        body.innerHTML = text.split(/\\n{2,}/).map(p =>
                            '<p>' + p.replace(/&/g, '&amp;').replace(/</g, '&lt;')
                                   .replace(/>/g, '&gt;').replace(/\\n/g, '<br>') + '</p>'
                        ).join('');
                        body.dispatchEvent(new InputEvent('input', {
                            bubbles: true, inputType: 'insertText', data: text
                        }));
                        body.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    }
                } catch(e) {}

                // 回退到主文档 contenteditable 元素
                const nodes = Array.from(document.querySelectorAll('[contenteditable="true"]'));
                const scored = nodes.map(el => {
                    const rect = el.getBoundingClientRect();
                    const ph = el.getAttribute('data-placeholder')
                        || el.getAttribute('placeholder') || '';
                    const label = ph + ' ' + (el.innerText || '');
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
                    .map(p => '<p>' +
                        p.replace(/&/g, '&amp;')
                         .replace(/</g, '&lt;')
                         .replace(/>/g, '&gt;')
                         .replace(/\\n/g, '<br>') +
                    '</p>')
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
            logger.info(f"✅ [百家号] 正文已填写 - L4 JS 注入 ({len(clean)} 字符)")
        return bool(ok)

    # ═══════════════════════════════════════════════════════════
    # 图文穿插（正文配图）
    # ═══════════════════════════════════════════════════════════

    async def _fill_content_with_images(self, page: Page, content: str, image_paths: List[str]) -> bool:
        """
        图文穿插写入正文：首块 setContent 初始化 + 后续键盘追加 + 逐张工具栏插图。
        单张图失败跳过，不阻断；只要写过至少一段文字即视为正文写入成功。
        """
        blocks = self._build_content_blocks(content, image_paths)
        if not blocks:
            return False

        # 确保 UEditor 正文 iframe 就绪
        if await self._get_ueditor_frame(page) is None:
            logger.warning("[百家号] 图文穿插：未找到 UEditor iframe，降级")
            return False

        wrote_text = False
        inserted_images = 0
        first_text = ""

        # 写第一个块：文字块直接写，图片块先写空段落占位
        head = blocks[0]
        rest = blocks[1:]
        if head["type"] == "text":
            first_text = head["content"][: self.MAX_CONTENT_LENGTH]
            if not await self._write_first_text_block(page, first_text):
                logger.warning("[百家号] 图文穿插：首段文字写入失败，降级")
                return False
            wrote_text = True
        else:
            if not await self._write_first_text_block(page, ""):
                logger.warning("[百家号] 图文穿插：初始化空段落失败，降级")
                return False
            rest = blocks  # 首块图片放到循环里处理

        # 后续逐块追加
        for block in rest:
            kind = block.get("type")
            value = block.get("content", "") or ""
            if kind == "text":
                await self._focus_ueditor_end(page)
                try:
                    await page.keyboard.press("End")
                    # 只用 1 个 Enter 切分：文本块内部已由 markdown_to_plain_text
                    # 提供单个换行，多按一次会生成空段落放大成巨大空栏。
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
                value = value[: self.MAX_CONTENT_LENGTH]
                if not await self._type_into_ueditor(page, value):
                    logger.warning("[百家号] 图文穿插：某段文字追加失败，跳过该段")
                    continue
                wrote_text = True
                if not first_text:
                    first_text = value
            elif kind == "image":
                await self._focus_ueditor_end(page)
                try:
                    await page.keyboard.press("End")
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
                if await self._insert_image_to_ueditor(page, value):
                    inserted_images += 1
                    try:
                        await page.keyboard.press("End")
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                else:
                    logger.warning(f"[百家号] 正文配图插入失败，跳过: {value}")

        # 校验：首段文字确实写入了（图文穿插成功的最低保障）
        if first_text and not await self._ueditor_contains_text(page, first_text):
            logger.warning("[百家号] 图文穿插：编辑器未检测到首段文字，降级")
            return False
        if inserted_images == 0 and image_paths:
            logger.warning("[百家号] 图文穿插：无一张图片插入成功（仍保留文字正文）")
        logger.info(f"✅ [百家号] 图文正文已写入（文字={wrote_text}, 图片={inserted_images}/{len(image_paths)}）")
        return wrote_text

    async def _get_ueditor_frame(self, page: Page):
        """获取 UEditor iframe 的 Frame 对象，失败返回 None。"""
        for selector in ("iframe#ueditor_0", "#ueditor iframe", sel.UEDITOR_IFRAME):
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    frame = await loc.content_frame()
                    if frame is not None:
                        return frame
            except Exception:
                continue
        return None

    async def _write_first_text_block(self, page: Page, text: str) -> bool:
        """写入首块文字：UEditor setContent → iframe body innerHTML。"""
        html = "".join(f"<p>{p.strip()}</p>" for p in (text or "").split("\n\n") if p.strip()) or "<p></p>"
        # L0: UEditor API
        try:
            ok = await page.evaluate(
                """(html) => {
                    try {
                        const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
                        if (ue && typeof ue.setContent === 'function') {
                            ue.setContent(html);
                            ue.fireEvent && ue.fireEvent('contentchange');
                            return true;
                        }
                    } catch(e) {}
                    return false;
                }""",
                html,
            )
            if ok:
                await short_delay()
                return True
        except Exception as exc:
            logger.debug(f"[百家号] 首块 setContent 失败: {exc}")
        # L1: iframe body innerHTML
        try:
            ok = await page.evaluate(
                """(html) => {
                    try {
                        const iframe = document.querySelector('iframe#ueditor_0');
                        if (!iframe || !iframe.contentDocument) return false;
                        const body = iframe.contentDocument.body;
                        if (!body) return false;
                        body.innerHTML = html;
                        body.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));
                        body.dispatchEvent(new Event('change', {bubbles: true}));
                        try {
                            const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
                            if (ue && typeof ue.sync === 'function') ue.sync('iframebody');
                        } catch(e) {}
                        return true;
                    } catch(e) { return false; }
                }""",
                html,
            )
            return bool(ok)
        except Exception as exc:
            logger.debug(f"[百家号] 首块 iframe innerHTML 失败: {exc}")
            return False

    async def _type_into_ueditor(self, page: Page, text: str) -> bool:
        """在 UEditor 当前光标处追加文字（insert_text 支持中文，长文用它）。"""
        if not text:
            return True
        try:
            if len(text) > 1000:
                try:
                    await page.keyboard.insert_text(text)
                except Exception:
                    await page.keyboard.type(text, delay=10)
            else:
                await page.keyboard.type(text, delay=15)
            return True
        except Exception as exc:
            logger.debug(f"[百家号] 追加文字失败: {exc}")
            return False

    async def _focus_ueditor_end(self, page: Page) -> None:
        """focus UEditor body 并把光标移到文档末尾。"""
        try:
            await page.evaluate(
                """() => {
                    try {
                        const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
                        if (ue && typeof ue.focus === 'function') ue.focus();
                    } catch(e) {}
                    try {
                        const iframe = document.querySelector('iframe#ueditor_0');
                        const doc = iframe && iframe.contentDocument;
                        if (!doc || !doc.body) return;
                        const body = doc.body;
                        body.focus();
                        const sel = doc.getSelection ? doc.getSelection() : null;
                        const range = doc.createRange();
                        range.selectNodeContents(body);
                        range.collapse(false);
                        if (sel) {
                            sel.removeAllRanges();
                            sel.addRange(range);
                        }
                    } catch(e) {}
                }"""
            )
        except Exception:
            pass

    async def _ueditor_contains_text(self, page: Page, text: str) -> bool:
        """校验 UEditor body 是否包含某段文字（取前 60 字，避免长文匹配误差）。"""
        if not text:
            return True
        try:
            found = await page.evaluate(
                """(needle) => {
                    try {
                        const iframe = document.querySelector('iframe#ueditor_0');
                        const doc = iframe && iframe.contentDocument;
                        if (!doc || !doc.body) return false;
                        return (doc.body.innerText || '').includes(needle.slice(0, 60));
                    } catch(e) { return false; }
                }""",
                text,
            )
            return bool(found)
        except Exception:
            return True  # 校验异常不阻断

    async def _ueditor_image_count(self, page: Page) -> int:
        """统计 UEditor body 内 <img> 数（src 存在即算，兼容未渲染宽高的新插入图）。"""
        try:
            count = await page.evaluate(
                """() => {
                    try {
                        const iframe = document.querySelector('iframe#ueditor_0');
                        const doc = iframe && iframe.contentDocument;
                        if (!doc) return 0;
                        return Array.from(doc.querySelectorAll('img')).filter(img => {
                            const r = img.getBoundingClientRect();
                            return img.getAttribute('src') || r.width > 0 || r.height > 0;
                        }).length;
                    } catch(e) { return 0; }
                }"""
            )
            return int(count or 0)
        except Exception:
            return 0

    async def _insert_image_to_ueditor(self, page: Page, image_path: str) -> bool:
        """
        向 UEditor 正文插入一张本地图片：工具栏上传（方式 A）→ 粘贴兜底（方式 B）。
        成功返回 True；失败返回 False（上层跳过该图，不阻断发布）。
        """
        if not image_path or not os.path.exists(image_path):
            return False

        before = await self._ueditor_image_count(page)

        # 方式 A：工具栏上传
        if await self._upload_image_via_toolbar(page, image_path, before):
            logger.info(f"✅ [百家号] 正文配图已通过工具栏上传: {os.path.basename(image_path)}")
            return True

        # 方式 B：粘贴兜底
        if await self._paste_image_to_ueditor(page, image_path, before):
            logger.info(f"✅ [百家号] 正文配图已通过粘贴插入: {os.path.basename(image_path)}")
            return True

        await self._save_debug_snapshot(page, "ueditor_insert_image_fail")
        return False

    async def _upload_image_via_toolbar(self, page: Page, image_path: str, before: int) -> bool:
        """方式 A：点工具栏图片按钮 → 本地上传 input set_input_files → 等图出现。"""
        # 1. 点工具栏「图片」按钮
        if not await self._click_ueditor_image_button(page):
            return False
        await asyncio.sleep(1)
        await self._close_interference(page)

        # 2. 切到「本地上传」tab（点不到也继续，可能默认就是）
        for selector in sel.UEDITOR_LOCAL_UPLOAD_TAB:
            try:
                tab = page.locator(selector).first
                if await tab.count() > 0 and await tab.is_visible(timeout=800):
                    await tab.click(force=True)
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                continue

        # 3. 弹窗内 file input 上传
        uploaded = False
        try:
            file_input = page.locator(sel.UEDITOR_IMAGE_FILE_INPUT).first
            if await file_input.count() > 0:
                await file_input.set_input_files(image_path)
                uploaded = True
                logger.info(f"[百家号] 已选择正文配图文件: {os.path.basename(image_path)}")
        except Exception as exc:
            logger.debug(f"[百家号] 正文配图 file input 上传失败: {exc}")

        if not uploaded:
            await self._close_ueditor_image_dialog(page)
            return False

        # 4. 等待图片出现在正文（最多 12s）
        if await self._wait_for_image_inserted(page, before, timeout=12):
            await self._confirm_ueditor_image_dialog(page)
            return True

        await self._close_ueditor_image_dialog(page)
        return False

    async def _click_ueditor_image_button(self, page: Page) -> bool:
        """点击 UEditor 工具栏「图片」按钮：静态选择器 → DOM 评分点击。"""
        # 静态选择器
        for selector in sel.UEDITOR_IMAGE_BUTTON:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=800):
                    await btn.click(force=True)
                    logger.info(f"[百家号] 已点击工具栏图片按钮: {selector}")
                    return True
            except Exception:
                continue
        # DOM 评分点击：title/aria-label/class 含 image/图片 且非"网络图片/视频"的工具栏按钮
        try:
            clicked = await page.evaluate(
                """() => {
                    const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width > 0 && r.height > 0
                            && s.display !== 'none' && s.visibility !== 'hidden';
                    };
                    const candidates = Array.from(document.querySelectorAll(
                        'div, button, a, span, [role="button"]'
                    )).filter(el => {
                        if (!visible(el)) return false;
                        const attrs = [
                            el.getAttribute('title') || '',
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('data-id') || '',
                            String(el.className || '')
                        ].join(' ').toLowerCase();
                        if (!attrs.includes('image') && !attrs.includes('图片')) return false;
                        if (attrs.includes('网络') || attrs.includes('remote') || attrs.includes('video') || attrs.includes('视频')) return false;
                        const r = el.getBoundingClientRect();
                        // 工具栏按钮通常较小且位于页面上半部
                        return r.width <= 80 && r.height <= 80 && r.top < window.innerHeight * 0.6;
                    });
                    if (!candidates.length) return false;
                    candidates[0].scrollIntoView({block: 'center'});
                    candidates[0].click();
                    return true;
                }"""
            )
            if clicked:
                logger.info("[百家号] 已通过 DOM 评分点击工具栏图片按钮")
                return True
        except Exception:
            pass
        return False

    async def _close_ueditor_image_dialog(self, page: Page) -> None:
        """关闭 UEditor 图片弹窗（取消/关闭按钮 + Esc）。"""
        for selector in [
            ".edui-dialog-close",
            'div[class*="edui-dialog"] [class*="close"]',
            'button:has-text("取消")',
            'span[class*="close"]',
        ]:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=400):
                    await btn.click(force=True)
                    break
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _confirm_ueditor_image_dialog(self, page: Page) -> None:
        """点弹窗的确定/完成（若存在）。"""
        for selector in sel.UEDITOR_IMAGE_CONFIRM:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=800):
                    await btn.click(force=True)
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                continue

    async def _wait_for_image_inserted(self, page: Page, before: int, timeout: int = 12) -> bool:
        """等待 UEditor body 内 <img> 数量增加。"""
        for _ in range(max(1, timeout * 2)):
            await asyncio.sleep(0.5)
            if await self._ueditor_image_count(page) > before:
                return True
        return False

    async def _paste_image_to_ueditor(self, page: Page, image_path: str, before: int) -> bool:
        """方式 B：构造 File + ClipboardEvent('paste') 派发给 UEditor body，等图出现。"""
        try:
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            with open(image_path, "rb") as file:
                data_b64 = base64.b64encode(file.read()).decode("ascii")
            name = os.path.basename(image_path)
            await self._focus_ueditor_end(page)
            ok = await page.evaluate(
                """({dataB64, mime, name}) => {
                    try {
                        const iframe = document.querySelector('iframe#ueditor_0');
                        const doc = iframe && iframe.contentDocument;
                        if (!doc || !doc.body) return false;
                        const target = doc.body;
                        target.focus();
                        const binary = atob(dataB64);
                        const bytes = new Uint8Array(binary.length);
                        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                        const file = new File([bytes], name || 'autogeo-image.jpg', {type: mime || 'image/jpeg'});
                        const dt = new DataTransfer();
                        dt.items.add(file);
                        const ev = new ClipboardEvent('paste', {
                            bubbles: true, cancelable: true, clipboardData: dt
                        });
                        target.dispatchEvent(ev);
                        doc.dispatchEvent(ev);
                        target.dispatchEvent(new Event('input', {bubbles: true}));
                        return true;
                    } catch(e) { return false; }
                }""",
                {"dataB64": data_b64, "mime": mime, "name": name},
            )
            if not ok:
                return False
            await random_delay(2, 4)
            return await self._ueditor_image_count(page) > before
        except Exception as exc:
            logger.debug(f"[百家号] 正文配图粘贴失败: {exc}")
            return False

    # ═══════════════════════════════════════════════════════════
    # 封面上传
    # ═══════════════════════════════════════════════════════════

    async def _upload_cover(self, page: Page, cover_path: str) -> None:
        """上传底部"选择封面"的单图封面"""
        if not cover_path or not os.path.exists(cover_path):
            logger.warning(f"⚠️ [百家号] 封面文件不存在: {cover_path}")
            return

        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)

            # 方案 1：直接点击触发 file chooser
            for selector in sel.COVER_BUTTON:
                try:
                    target = page.locator(selector).last
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
                        logger.info("✅ [百家号] 封面已通过文件选择器上传")
                        return
                    except Exception:
                        # 没有直接触发 file chooser，可能是弹窗模式
                        await target.click(force=True)
                        await asyncio.sleep(1)
                        if await self._click_local_upload_and_set_file(page, cover_path):
                            await self._confirm_cover_dialog(page)
                            logger.info("✅ [百家号] 封面已通过弹窗上传")
                            return
                except Exception:
                    continue

            # 方案 2：直接给隐藏的 input[type="file"] 注入文件
            file_input = page.locator(sel.COVER_FILE_INPUT).first
            if await file_input.count() == 0:
                file_input = page.locator(sel.COVER_ALL_FILE_INPUT).first
            if await file_input.count() > 0:
                await file_input.set_input_files(cover_path)
                await asyncio.sleep(2)
                await self._confirm_cover_dialog(page)
                logger.info("✅ [百家号] 封面已通过 input file 注入")
                return

            logger.warning("⚠️ [百家号] 未找到封面上传入口，继续发布")
            await self._save_debug_snapshot(page, "cover_upload_fail")
        except Exception as e:
            logger.warning(f"⚠️ [百家号] 封面上传失败，继续发布: {e}")
            await self._save_debug_snapshot(page, "cover_upload_fail")

    async def _click_local_upload_and_set_file(self, page: Page, image_path: str) -> bool:
        for selector in [
            "text=本地上传",
            'button:has-text("本地上传")',
            'div:has-text("本地上传")',
            'span:has-text("本地上传")',
        ]:
            try:
                btn = page.locator(selector).last
                if await btn.count() == 0 or not await btn.is_visible(timeout=1000):
                    continue
                async with page.expect_file_chooser(timeout=5000) as fc_info:
                    await btn.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(image_path)
                await asyncio.sleep(2)
                return True
            except Exception:
                continue
        return False

    async def _confirm_cover_dialog(self, page: Page) -> None:
        """处理封面弹窗的"确定/完成/确认"按钮"""
        for selector in sel.COVER_CONFIRM:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    await asyncio.sleep(1)
                    logger.info(f"[百家号] 已确认封面弹窗: {selector}")
                    return
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════
    # 发布选项 & 发布按钮
    # ═══════════════════════════════════════════════════════════

    async def _set_publish_options(self, page: Page, declare_ai_content: bool = True) -> None:
        """设置创作声明、AI 声明等选项"""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)
            # 这些选项可能不存在，失败不阻断主流程
            await self._set_checkbox_by_label(page, "自动生成播客", checked=False)
            await self._set_checkbox_by_label(page, "图文转动态", checked=False)
            if declare_ai_content:
                await self._set_checkbox_by_label(page, "AI生成", checked=True)
                await self._set_checkbox_by_label(page, "人工智能", checked=True)
        except Exception as e:
            logger.warning(f"⚠️ [百家号] 发布选项设置跳过: {e}")

    async def _set_checkbox_by_label(self, page: Page, label: str, checked: bool) -> bool:
        try:
            return await page.evaluate(
                """({label, checked}) => {
                    const labels = Array.from(document.querySelectorAll('label, span, div'));
                    const node = labels.find(el => (el.innerText || '').includes(label));
                    if (!node) return false;
                    const scope = node.closest('label') || node.parentElement || node;
                    const input = scope.querySelector('input[type="checkbox"]')
                        || (node.parentElement && node.parentElement.querySelector('input[type="checkbox"]'));
                    if (input) {
                        if (input.checked !== checked) input.click();
                        return true;
                    }
                    const box = scope.querySelector('[class*="checkbox"], [role="checkbox"]') || node;
                    const cls = `${box.className || ''} ${box.getAttribute('aria-checked') || ''}`;
                    const isChecked = cls.includes('checked') || cls.includes('true');
                    if (isChecked !== checked) box.click();
                    return true;
                }""",
                {"label": label, "checked": checked},
            )
        except Exception:
            return False

    async def _click_publish(self, page: Page) -> bool:
        """点击底部右侧蓝色"发布"按钮，过滤掉"定时发布"等无关按钮"""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)

            # 强制启用按钮（防止被灰禁）
            await page.evaluate(
                """() => {
                    document.querySelectorAll('button').forEach(btn => {
                        const text = (btn.innerText || '').trim();
                        if (text === '发布' || text === '确认发布') {
                            btn.disabled = false;
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
                    # 倒序：通常主"发布"按钮在右侧靠后
                    for i in range(count - 1, -1, -1):
                        btn = buttons.nth(i)
                        if not await btn.is_visible(timeout=1000):
                            continue
                        text = (await btn.inner_text()).strip()
                        # 过滤无关按钮
                        if any(bad in text for bad in ["定时发布", "发布设置", "发布作品", "发布图文", "发布视频"]):
                            continue
                        if text not in ["发布", "确认发布", "发布文章", "立即发布"]:
                            continue
                        await btn.scroll_into_view_if_needed(timeout=3000)
                        await btn.click(force=True)
                        logger.info(f"✅ [百家号] 已点击发布按钮: {text} (selector: {selector})")
                        await asyncio.sleep(2)
                        await self._handle_publish_confirm(page)
                        return True
                except Exception:
                    continue

            return False
        except Exception as e:
            logger.error(f"❌ [百家号] 点击发布失败: {e}")
            return False

    async def _handle_publish_confirm(self, page: Page) -> None:
        """处理发布后的二次确认弹窗"""
        for text in sel.PUBLISH_CONFIRM:
            try:
                btn = page.locator(f'button:has-text("{text}")').last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    await asyncio.sleep(1)
                    logger.info(f"[百家号] 已确认发布弹窗: {text}")
                    break
            except Exception:
                continue

        # 安全验证（滑块）
        try:
            if await page.locator(sel.CAPTCHA_INDICATOR).count() > 0:
                logger.warning("🚧 [百家号] 触发安全验证，请在 60 秒内手动完成")
                try:
                    await page.wait_for_selector(sel.CAPTCHA_INDICATOR, state="hidden", timeout=60000)
                except Exception as exc:
                    raise RuntimeError("百家号安全验证未完成，请人工处理后重试发布") from exc
                logger.info("[百家号] 安全验证已完成，继续发布流程")
        except RuntimeError:
            raise
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 等待发布结果
    # ═══════════════════════════════════════════════════════════

    async def _wait_for_publish_result(self, page: Page) -> Dict[str, Any]:
        """
        等待发布结果，最长120秒（60次×2秒）：
          - 优先检测明确的失败提示
          - 检测成功提示或 URL 跳转
          - 都没检测到则返回 success=False（不再误报成功）
        """
        success_texts = ["发布成功", "提交成功", "审核中", "作品管理", "内容管理"]
        fail_texts = [
            "发布失败",
            "内容违规",
            "敏感词",
            "请设置封面",
            "请输入标题",
            "请输入正文",
            "不符合规范",
            "包含敏感",
            "上传失败",
        ]

        last_url = page.url
        for tick in range(60):  # 60次 × 2秒 = 120秒
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            # 失败检测
            for text in fail_texts:
                try:
                    node = page.get_by_text(text, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        msg = (await node.inner_text()).strip()
                        logger.error(f"❌ [百家号] 检测到失败提示: {msg}")
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
            for text in success_texts:
                try:
                    node = page.get_by_text(text, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        logger.success(f"🎉 [百家号] 检测到成功提示: {text}")
                        return {"success": True, "platform_url": page.url}
                except Exception:
                    continue

            # URL 跳转
            if page.url != last_url and re.search(
                r"(success|content|works|manage|home|article)", page.url, re.IGNORECASE
            ):
                logger.success(f"🎉 [百家号] 检测到跳转，认为发布成功: {page.url}")
                return {"success": True, "platform_url": page.url}

            await asyncio.sleep(2)

        # 未检测到明确结果：返回失败，需要人工复核
        logger.warning("⏰ [百家号] 120 秒内未检测到明确结果，需要人工复核")
        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": "未检测到明确的发布成功提示，请到百家号后台人工确认",
            "debug_path": debug_path,
        }

    # ═══════════════════════════════════════════════════════════
    # 辅助工具
    # ═══════════════════════════════════════════════════════════

    async def _click_by_text(self, page: Page, texts: List[str]) -> bool:
        """按文本内容查找并点击元素"""
        for text in texts:
            locators = [
                page.get_by_text(text, exact=True),
                page.get_by_text(text, exact=False),
                page.locator(f'button:has-text("{text}")'),
                page.locator(f'div:has-text("{text}")'),
                page.locator(f'span:has-text("{text}")'),
                page.locator(f'[role="button"]:has-text("{text}")'),
            ]
            for locator in locators:
                try:
                    count = min(await locator.count(), 5)
                    for i in range(count):
                        item = locator.nth(i)
                        if await item.is_visible(timeout=500):
                            await item.click(force=True)
                            return True
                except Exception:
                    continue
        return False

    def _deep_clean_content(self, content: str) -> str:
        """清理 Markdown/HTML 内容，输出适合编辑器粘贴的纯文本"""
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
        # 移除首行 H1 (常见模式)
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
            for key in ("登录", "登陆", "login", "passport", "验证码", "验证", "captcha", "滑块", "风控", "安全")
        )

    # ═══════════════════════════════════════════════════════════
    # 免费正版图库搜图（v3.2 新增）
    # ═══════════════════════════════════════════════════════════

    def _extract_article_keywords(self, article: Any) -> List[str]:
        """从文章中提取 2-3 个用于搜图的关键词

        优先级：article 的 keyword 字段 > 标题分词 > 项目关键词
        """
        keywords = []

        # 1. 文章关联的 keyword
        kw = getattr(article, "keyword", None)
        if kw and hasattr(kw, "keyword"):
            keywords.append(str(kw.keyword).strip())

        # 2. 从 title 提取有意义的关键词
        title = getattr(article, "title", "") or ""
        # 提取中文词汇和英文单词
        import re as _re

        cn_words = _re.findall(r"[\u4e00-\u9fff]{2,8}", title)
        en_words = _re.findall(r"[a-zA-Z]{2,20}", title)
        # 过滤通用词
        stop_words = {
            "可以",
            "这个",
            "什么",
            "这个",
            "那个",
            "怎么",
            "如何",
            "使用",
            "应用",
            "相关",
            "推荐",
            "一个",
            "一些",
        }
        for w in cn_words:
            if w not in stop_words and w not in keywords:
                keywords.append(w)
                if len(keywords) >= 3:
                    break
        for w in en_words:
            if w.lower() not in {"the", "for", "and", "with"} and w not in keywords:
                keywords.append(w)
                if len(keywords) >= 3:
                    break

        # 3. 兜底
        if not keywords:
            keywords = ["科技", "人工智能"]

        logger.info(f"[百家号] 提取搜图关键词: {keywords[:3]}")
        return keywords[:3]

    async def _click_free_image_library_tab(self, page: Page) -> bool:
        """切换到'免费正版图库'标签页"""
        tab_selectors = [
            'role=tab[name="免费正版图库"]',
            '[class*="freeImage"]',
            '[class*="free-image"]',
            'text="免费正版图库"',
        ]
        for selector in tab_selectors:
            try:
                tab = page.locator(selector).first
                if await tab.count() > 0 and await tab.is_visible(timeout=3000):
                    await tab.click(force=True)
                    logger.info("[百家号] 已切换到免费正版图库")
                    await asyncio.sleep(1)
                    return True
            except Exception:
                continue
        logger.warning("[百家号] 未找到免费正版图库标签")
        return False

    async def _insert_images_from_library(self, page: Page, keywords: List[str], count: int = 2) -> bool:
        """从百家号免费正版图库搜图并插入正文

        Args:
            page: Playwright Page
            keywords: 搜索关键词列表（2-3 个）
            count: 每个关键词插入的图片数

        Returns:
            是否成功插入至少一张图片
        """
        inserted = 0
        total_to_insert = min(len(keywords) * count, 3)  # 最多3张

        # 先点击正文编辑器获得焦点
        try:
            editor_selectors = [
                '[data-testid="content-editor"]',
                '[class*="FeEditorApp"]',
                "iframe#ueditor_0",
            ]
            for sel in editor_selectors:
                editor = page.locator(sel).first
                if await editor.count() > 0 and await editor.is_visible(timeout=2000):
                    await editor.click(force=True)
                    await short_delay()
                    break
        except Exception:
            pass

        # 切换到免费正版图库
        if not await self._click_free_image_library_tab(page):
            return False

        for kw in keywords[:3]:
            if inserted >= total_to_insert:
                break

            try:
                # 搜索关键词
                search_input_sel = 'placeholder="请输入关键词，查找相关图片素材"'
                search_input = page.locator(search_input_sel).first

                if not (await search_input.count() > 0 and await search_input.is_visible(timeout=3000)):
                    # 尝试其他选择器
                    for alt in ['input[placeholder*="关键词"]', 'input[placeholder*="素材"]']:
                        search_input = page.locator(alt).first
                        if await search_input.count() > 0 and await search_input.is_visible(timeout=1000):
                            break

                if await search_input.count() > 0:
                    await search_input.click(force=True)
                    await short_delay()
                    await search_input.fill(kw)
                    await short_delay()
                    await page.keyboard.press("Enter")
                    logger.info(f"[百家号] 搜索图库关键词: {kw}")
                    await asyncio.sleep(2)

                # 选择图片（选第1-2张）
                for img_idx in range(min(count, 2)):
                    if inserted >= total_to_insert:
                        break

                    # 尝试定位图片复选框
                    img_selectors = [
                        f"div:nth-child({img_idx + 1}) > .image-wrapper-checkbox",
                        f"div:nth-child({img_idx + 1}) [class*='checkbox']",
                        f"div:nth-child({img_idx + 1}) img",
                    ]
                    selected = False
                    for img_sel in img_selectors:
                        try:
                            img_item = page.locator(img_sel).first
                            if await img_item.count() > 0 and await img_item.is_visible(timeout=3000):
                                await img_item.click(force=True)
                                logger.info(f"[百家号] 已选择图片 {img_idx + 1} for '{kw}'")
                                selected = True
                                inserted += 1
                                await asyncio.sleep(0.3)
                                break
                        except Exception:
                            continue

                    if not selected:
                        logger.warning(f"[百家号] 未找到可选的图片 {img_idx + 1} for '{kw}'")

                # 确认选择
                if inserted > 0:
                    confirm_selectors = [
                        f'role=button[name="确定 ({inserted})"]',
                        'role=button[name^="确定"]',
                        'button:has-text("确定")',
                    ]
                    for conf_sel in confirm_selectors:
                        try:
                            conf_btn = page.locator(conf_sel).first
                            if await conf_btn.count() > 0 and await conf_btn.is_visible(timeout=2000):
                                await conf_btn.click(force=True)
                                logger.info(f"[百家号] 已确认插入 {inserted} 张图片")
                                await asyncio.sleep(1)
                                break
                        except Exception:
                            continue

            except Exception as e:
                logger.warning(f"[百家号] 搜索关键词 '{kw}' 失败: {e}")
                continue

        return inserted > 0

    async def _fill_title_lexical_v2(self, page: Page, title: str) -> bool:
        """使用 codegen 验证过的 Lexical 编辑器选择器填写标题（v3.2）

        优先使用 getByTestId 定位，确保与最新百家号页面兼容。
        """
        clean = re.sub(r"[#*`\"<>]", "", title or "").strip()[: self.MAX_TITLE_LENGTH]
        if not clean:
            return False

        # L0: getByTestId (codegen-verified)
        try:
            title_input = page.get_by_test_id("news-title-input")
            if await title_input.count() > 0:
                # 点击标题编辑器获得焦点
                await title_input.get_by_role("paragraph").first.click(force=True)
                await short_delay()
                # 全选删除
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await short_delay()
                # 使用 locator div:nth(1) 精确定位输入区域
                input_area = title_input.locator("div").nth(1)
                if await input_area.count() > 0:
                    await input_area.fill(clean)
                    logger.info(f"✅ [百家号] 标题已填写 (testId): {clean}")
                    return True
        except Exception as e:
            logger.debug(f"[百家号] testId 标题填写失败: {e}")

        # 回退到现有逻辑
        return await self._fill_title(page, clean)


# ═══════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════

BAIJIAHAO_CONFIG = {
    "id": "baijiahao",
    "name": "百家号",
    "code": "BJH",
    "login_url": "https://baijiahao.baidu.com/builder/rc/static/login/index",
    "home_url": "https://baijiahao.baidu.com/builder/rc/home",
    "publish_url": "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1",
    "auto_generate_cover": False,
    "auto_generate_inline_images": False,
    "color": "#E53935",
}

registry.register("baijiahao", BaijiahaoPublisher("baijiahao", BAIJIAHAO_CONFIG))
