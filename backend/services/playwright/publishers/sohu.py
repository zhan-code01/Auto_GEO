# -*- coding: utf-8 -*-
"""
搜狐号发布适配器 - v1.0 防闪退版（直接发布）

重写自旧版 v18.6（只存草稿、外部 AI 配图、结果虚报成功、流程脆弱）。

v1.0 目标：真正"发布"图文文章（非草稿），架构对齐头条号 toutiao v1.0 防闪退版：
  1. 导航带重试 + 登录页/安全验证检测（登录态由外层 storage_state 注入，这里只做检测）
  2. firstpage 首页 -> 点"发布内容" -> 等 Quill 编辑器就绪
  3. 移除/关闭新手引导遮罩（introjs / Element overlay），避免挡住发布按钮
  4. 图片来源：文章自带图优先（materialize_images），默认不在发布阶段生成替代图
  5. 标题：input 多级定位（placeholder -> JS 兜底）
  6. 正文：Quill .ql-editor paste 注入（DataTransfer + ClipboardEvent，Quill 唯一可靠手法）
     + 图文穿插（自带图），失败降级纯文字
  7. 封面：独立上传区弹窗 -> set_input_files -> 确定
  8. 发布：点"发布"按钮 -> 二次确认弹窗"确定"
  9. 严格结果验证：先查失败、再查成功/URL 跳转、超时按失败处理（不虚报成功）
 10. 失败/人工介入落 debug 快照到 backend/debug/sohu/，便于事后定位

执行链路：外层（playwright_mgr.execute_publish）用 storage_state 创建已登录的
context 后调 publisher.publish(page, article, account, declare_ai_content=True)。
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

from . import sohu_selectors as sel
from .base import BasePublisher, registry
from .note_utils import clean_title, generated_publish_images_enabled, materialize_images
from ..humanize import random_delay, short_delay


class SohuPublisher(BasePublisher):
    """搜狐号图文发布器 - v1.0 防闪退版（直接发布）"""

    MAX_TITLE_LENGTH = 72  # 搜狐号图文标题 5-72 字
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
            logger.info("🚀 [搜狐号 v1.0] 开始发布图文文章 (防闪退 + 直接发布版)")

            title = getattr(article, "title", "") or "未命名文章"
            content = getattr(article, "content", "") or ""

            # 0. 极简 stealth：只设 localStorage 跳过新手引导（不改 navigator）
            stage = "stealth"
            await self._inject_minimal_stealth(page)

            # 1. 导航到图文编辑器（首页 -> 点"发布内容"，带重试 + 登录页检测）
            stage = "navigate"
            if not await self._navigate_to_editor(page):
                # 拆分模糊判断：确认落到登录页 = 确定登出；其余（网络/安全验证/编辑器迟迟不出现）= 不确定
                if self._is_on_login_page(page):
                    return await self._auth_failure(
                        page,
                        stage,
                        definitive=True,
                        message="无法进入搜狐号图文编辑器，已被重定向到登录页，登录态已失效，请重新授权",
                    )
                return await self._auth_failure(
                    page,
                    stage,
                    definitive=False,
                    message="无法进入搜狐号图文编辑器，疑似网络异常或安全验证，未判定账号失效",
                )

            # 2. 登录态检测
            stage = "login_check"
            if not await self._ensure_logged_in(page):
                return await self._auth_failure(
                    page,
                    stage,
                    definitive=True,
                    message="搜狐号登录态失效，请到账号管理重新授权搜狐号",
                )

            # 3. 等待编辑器完全加载
            stage = "wait_editor"
            await self._wait_editor_ready(page)

            # 3.5 关闭新手引导 / 活动浮层等干扰（在任何编辑器交互前完成）
            stage = "dismiss_interference"
            await self._close_interference(page)

            # 4. 准备封面图：文章自带，默认不生成替代图
            stage = "prepare_cover"
            cover_path = await self._resolve_cover(article, title)
            if cover_path:
                temp_files.append(cover_path)

            # 4.5 准备正文配图：文章自带，默认不生成替代图
            stage = "prepare_content_images"
            content_image_paths, content_temp_files = await self._prepare_content_images(article, title)
            temp_files.extend(content_temp_files)

            # 5. 填写标题
            stage = "fill_title"
            await self._close_interference(page)
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "标题填写失败")

            # 6. 填写正文（图文穿插 / 纯文字）
            stage = "fill_content"
            await self._close_interference(page)
            if not await self._fill_content(page, content, image_paths=content_image_paths):
                return await self._fail(page, stage, "正文填写失败")

            # 7. 上传封面
            stage = "upload_cover"
            if cover_path:
                await self._upload_cover(page, cover_path)
            await self._close_interference(page)

            # 8. AI 内容声明（可选，选择器随版本变化，失败不阻断）
            stage = "set_options"
            if declare_ai_content:
                await self._set_ai_declaration(page)
            await self._close_interference(page)

            # 9. 点击发布 -> 处理二次确认
            stage = "publish"
            await self._close_interference(page)
            if not await self._click_publish(page):
                return await self._fail(page, stage, "未找到可点击的'发布'按钮")

            # 10. 等待发布结果
            stage = "wait_result"
            return await self._wait_for_publish_result(page)

        except Exception as e:
            logger.exception(f"❌ [搜狐号] 发布失败 stage={stage}: {e}")
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
    # 结果封装 & 调试快照
    # ═══════════════════════════════════════════════════════════

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        logger.error(f"❌ [搜狐号] stage={stage} 失败: {msg}")
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        return {
            "success": False,
            "error_msg": f"[{stage}] {msg}",
            "platform_url": getattr(page, "url", None),
            "debug_path": debug_path,
        }

    async def _manual_fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        """人工介入（登录/验证码/风控）结果：先落快照便于事后定位。"""
        debug_path = await self._save_debug_snapshot(page, f"manual_{stage}")
        result = self.manual_intervention_result(stage, message, page)
        result["debug_path"] = debug_path
        return result

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        """保存失败时的 HTML + 全页截图到 backend/debug/sohu/。"""
        debug_dir = Path("backend/debug/sohu")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
            screenshot_path = debug_dir / f"{safe_stage}_{stamp}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as exc:
            logger.warning("[搜狐号] 保存调试快照失败: {}", exc)
        return str(html_path)

    def _looks_like_manual_intervention(self, msg: str) -> bool:
        msg = (msg or "").lower()
        return any(
            key in msg
            for key in ("登录", "登陆", "login", "passport", "验证码", "验证", "captcha", "滑块", "风控", "安全")
        )

    # ═══════════════════════════════════════════════════════════
    # stealth：跳过新手引导（极简，不动 navigator）
    # ═══════════════════════════════════════════════════════════

    async def _inject_minimal_stealth(self, page: Page) -> None:
        try:
            await page.add_init_script(
                """() => {
                    try {
                        localStorage.setItem('sohu_guide_done', '1');
                        localStorage.setItem('introjs_done', '1');
                        localStorage.setItem('new_user_guide_done', '1');
                        localStorage.setItem('first_publish_guide_done', '1');
                    } catch (e) {}
                }"""
            )
            await page.evaluate(
                """() => {
                    try {
                        localStorage.setItem('sohu_guide_done', '1');
                        localStorage.setItem('introjs_done', '1');
                        localStorage.setItem('new_user_guide_done', '1');
                        localStorage.setItem('first_publish_guide_done', '1');
                    } catch (e) {}
                }"""
            )
            logger.info("💉 [搜狐号] 极简 stealth 已注入（仅 localStorage）")
        except Exception as e:
            logger.warning(f"⚠️ [搜狐号] stealth 注入失败（不阻断）: {e}")

    # ═══════════════════════════════════════════════════════════
    # 导航 & 登录
    # ═══════════════════════════════════════════════════════════

    async def _navigate_to_editor(self, page: Page) -> bool:
        """
        导航到图文编辑器：firstpage 首页 -> 点"发布内容" -> 等 Quill 编辑器。
        返回 True/False 不抛异常，让上层决定。
        """
        edit_url = self.config.get("publish_url", sel.PUBLISH_URL)
        last_error = ""
        for attempt in range(3):
            try:
                logger.info(f"[搜狐号] 导航到后台首页 (尝试 {attempt + 1}/3): {edit_url}")
                await page.goto(edit_url, wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    logger.warning("[搜狐号] networkidle 等待超时，继续检测")
                await asyncio.sleep(2)

                if self._is_login_url(page.url):
                    logger.error(f"❌ [搜狐号] 被重定向到登录页: {page.url}")
                    return False

                # 已在编辑器（极少见，首页直接渲染编辑器）则直接成功
                if await self._has_editor(page, timeout=3000):
                    logger.success("✅ [搜狐号] 已进入图文编辑器（直达）")
                    return True

                # 首页加载后点"发布内容"按钮进入编辑器
                clicked = await self._click_publish_entry(page)
                if not clicked:
                    logger.warning(f"[搜狐号] 未找到'发布内容'按钮 (尝试 {attempt + 1}/3)，等待后重试")
                    await asyncio.sleep(3)
                    # 再试一次（页面可能慢渲染）
                    if await self._click_publish_entry(page):
                        if await self._has_editor(page, timeout=15000):
                            logger.success("✅ [搜狐号] 已进入图文编辑器")
                            return True
                    continue

                # 等待编辑器加载
                if await self._wait_editor_ready(page, max_wait=15):
                    logger.success("✅ [搜狐号] 已进入图文编辑器")
                    return True

                if self._is_login_url(page.url):
                    return False
            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ [搜狐号] 导航异常 (尝试 {attempt + 1}/3): {e}")
                await asyncio.sleep(2)

        logger.error(f"❌ [搜狐号] 3 次导航均失败。最后错误: {last_error}")
        return False

    async def _click_publish_entry(self, page: Page) -> bool:
        """点击首页上的"发布内容"按钮（多选择器兜底）。"""
        for selector in sel.PUBLISH_ENTRY_BUTTON:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    logger.info(f"[搜狐号] 已点击'发布内容'按钮 ({selector})")
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue
        # 文本兜底
        try:
            node = page.get_by_text("发布内容", exact=False).first
            if await node.count() > 0 and await node.is_visible(timeout=1500):
                await node.click(force=True)
                logger.info("[搜狐号] 已点击'发布内容'按钮（文本兜底）")
                await asyncio.sleep(2)
                return True
        except Exception:
            pass
        return False

    def _is_login_url(self, url: str) -> bool:
        url = (url or "").lower()
        return any(indicator in url for indicator in sel.LOGIN_URL_INDICATOR)

    async def _has_editor(self, page: Page, timeout: int = 2000) -> bool:
        """检测编辑器是否已渲染（Quill 正文 / 标题 input）。"""
        for selector in sel.EDITOR_READY_SELECTORS:
            try:
                node = page.locator(selector).first
                if await node.count() > 0:
                    if selector in (".ql-editor",) or "contenteditable" in selector:
                        return True
                    if await node.is_visible(timeout=timeout):
                        return True
            except Exception:
                continue
        # 文字兜底
        for text in ("请输入标题", "发布内容"):
            try:
                node = page.get_by_text(text, exact=False).first
                if await node.count() > 0 and await node.is_visible(timeout=500):
                    return True
            except Exception:
                continue
        return False

    async def _wait_editor_ready(self, page: Page, max_wait: int = 20) -> bool:
        for _ in range(max_wait):
            if await self._has_editor(page, timeout=500):
                return True
            await asyncio.sleep(1)
        logger.warning(f"⚠️ [搜狐号] 编辑器 {max_wait}s 内未稳定渲染，继续尝试")
        return False

    async def _ensure_logged_in(self, page: Page) -> bool:
        if self._is_login_url(page.url):
            return False
        for selector in sel.LOGIN_SUCCESS_ELEMENT:
            try:
                el = page.locator(selector).first
                if await el.count() > 0:
                    return True
            except Exception:
                continue
        # 兜底：编辑器存在 = 已登录（搜狐号编辑器必须登录才能看到）
        if await self._has_editor(page, timeout=2000):
            return True
        logger.warning("⚠️ [搜狐号] 无法确认登录态")
        return False

    # ═══════════════════════════════════════════════════════════
    # 干扰弹窗处理
    # ═══════════════════════════════════════════════════════════

    async def _close_interference(self, page: Page) -> None:
        """关闭新手引导 / 活动浮层 / 新功能提醒等。"""
        # 1. 点关闭/知道了等按钮
        for btn_selector in sel.INTERFERENCE_CLOSE_BTN:
            try:
                btn = page.locator(btn_selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=400):
                    await btn.click(force=True)
                    logger.info(f"[搜狐号] 已关闭干扰弹窗: {btn_selector}")
                    await short_delay()
                    break
            except Exception:
                continue

        # 2. 移除遮罩类元素
        await self._force_clear_overlays(page)

        # 3. Esc 关浮层
        for _ in range(3):
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
            except Exception:
                break

        await self._force_clear_overlays(page)

    async def _force_clear_overlays(self, page: Page) -> None:
        """移除遮罩/引导浮层节点（保护编辑器与发布按钮不被误删）。"""
        try:
            removed = await page.evaluate(
                """() => {
                    const removeSelectors = %s;
                    let count = 0;
                    removeSelectors.forEach(s => document.querySelectorAll(s).forEach(el => {
                        try { el.remove(); count++; } catch(e) {}
                    }));
                    // 只移除明确是遮罩/弹窗壳的高 z-index 元素，保护编辑器与按钮
                    const protectRe = /ql-editor|ql-toolbar|editor|title|cover|publish|submit|upload|content/i;
                    document.querySelectorAll('[class*="modal"], [class*="mask"], [class*="overlay"], [class*="guide"], [class*="introjs"]').forEach(el => {
                        try {
                            const cls = String(el.className || '');
                            if (protectRe.test(cls)) return;
                            const z = parseInt(window.getComputedStyle(el).zIndex || '0');
                            if (z > 500) { el.remove(); count++; }
                        } catch(e) {}
                    });
                    document.body.style.overflow = 'auto';
                    document.body.style.pointerEvents = 'auto';
                    return count;
                }"""
                % repr(sel.INTERFERENCE_REMOVE)
            )
            if removed:
                logger.info(f"[搜狐号] 清理遮罩/引导节点: {removed}")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 图片准备（文章自带优先，默认不生成替代图）
    # ═══════════════════════════════════════════════════════════

    async def _resolve_cover(self, article: Any, title: str) -> Optional[str]:
        """封面：文章自带 cover 字段 / 内嵌图，默认不生成替代封面。"""
        for attr in ("cover_path", "cover_image_path", "cover", "cover_image"):
            value = getattr(article, attr, None)
            if isinstance(value, str) and value.strip() and os.path.exists(value):
                logger.info(f"[搜狐号] 使用文章封面字段: {value}")
                return value
        try:
            image_paths, _temp = await materialize_images(article, limit=1)
            if image_paths:
                logger.info(f"[搜狐号] 使用文章内嵌图片作为封面: {image_paths[0]}")
                return image_paths[0]
        except Exception as e:
            logger.warning(f"[搜狐号] 提取内嵌图片失败: {e}")
        if generated_publish_images_enabled(self.config):
            return await self._download_cover_fallback(title)
        logger.info("[搜狐号] 未找到文章自带封面，跳过发布阶段替代封面生成")
        return None

    async def _prepare_content_images(self, article: Any, title: str) -> tuple[List[str], List[str]]:
        """正文配图：文章自带图片，默认不生成替代配图。返回 (image_paths, temp_files)。"""
        try:
            image_paths, temp_files = await materialize_images(article, limit=9)
        except Exception as exc:
            logger.warning(f"[搜狐号] 提取自带图片失败: {exc}")
            image_paths, temp_files = [], []
        if not image_paths and generated_publish_images_enabled(self.config):
            keyword = self._extract_keyword(title)
            ai_paths = await self._download_inline_images(keyword, count=3)
            image_paths = ai_paths
            temp_files = list(ai_paths)
        elif not image_paths:
            logger.warning("[搜狐号] 图片下载失败，尝试继续发布（可能无图）...")
        return image_paths, temp_files

    async def _download_cover_fallback(self, title: str) -> Optional[str]:
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
                        path = os.path.join(tempfile.gettempdir(), f"sohu_cover_{random.randint(10000, 99999)}.jpg")
                        with open(path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"[搜狐号] AI 兜底封面已下载: {path}")
                        return path
                except Exception as e:
                    logger.warning(f"[搜狐号] 兜底图源失败 {url[:80]}: {e}")
        return None

    async def _download_inline_images(self, keyword: str, count: int = 3) -> List[str]:
        """显式开启时，为无图文章生成 N 张正文配图。"""
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
                        fd, path = tempfile.mkstemp(prefix="sohu_inline_", suffix=suffix)
                        with os.fdopen(fd, "wb") as file:
                            file.write(resp.content)
                        paths.append(path)
                        break
                    except Exception as exc:
                        logger.warning(f"[搜狐号] 正文配图下载失败: {exc}")
        return paths

    def _extract_keyword(self, title: str) -> str:
        cleaned = re.sub(r"[^\w一-鿿]", " ", title or "")
        words = [w for w in cleaned.split() if w]
        if not words:
            return "风景"
        return words[0] if len(words) == 1 else f"{words[0]} {words[1]}"

    def _build_content_blocks(self, content: str, image_paths: List[str]) -> List[Dict[str, str]]:
        """把 content 按图片标记切成 text/image 块，保持图文相对顺序。多余的图追加末尾。"""
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
    # 标题
    # ═══════════════════════════════════════════════════════════

    async def _fill_title(self, page: Page, title: str) -> bool:
        """填标题：input 多级定位（placeholder -> JS 兜底）。"""
        clean = clean_title(title, self.MAX_TITLE_LENGTH)
        if not clean:
            logger.error("❌ [搜狐号] 标题为空")
            return False

        # L1：定位 input 并输入（input 用 fill 为主）
        for selector in sel.TITLE_INPUT:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible(timeout=1500):
                    await loc.click(force=True)
                    await short_delay()
                    # 暴力清空
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    try:
                        await loc.fill(clean)
                    except Exception:
                        try:
                            await page.keyboard.insert_text(clean)
                        except Exception:
                            await page.keyboard.type(clean, delay=25)
                    # 唤醒 Vue/Quill 状态
                    await page.keyboard.press("Space")
                    await page.keyboard.press("Backspace")
                    logger.info(f"✅ [搜狐号] 标题已填写 ({selector}): {clean}")
                    return True
            except Exception:
                continue

        # L2：JS 兜底（不依赖具体选择器，按 placeholder 定位）
        ok = await page.evaluate(
            """(title) => {
                const candidates = Array.from(
                    document.querySelectorAll('textarea, input, [contenteditable="true"]')
                );
                let el = candidates.find(node => {
                    const ph = node.getAttribute('placeholder')
                        || node.getAttribute('data-placeholder') || '';
                    return ph.includes('标题');
                });
                if (!el) {
                    el = candidates.find(node => {
                        const rect = node.getBoundingClientRect();
                        return rect.width > 100 && rect.height < 120
                            && rect.height > 10 && node.closest('iframe') === null;
                    });
                }
                if (!el) return false;
                el.focus();
                if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
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
            logger.info(f"✅ [搜狐号] 标题已填写 (JS 兜底): {clean}")
        return bool(ok)

    # ═══════════════════════════════════════════════════════════
    # 正文（Quill .ql-editor）
    # ═══════════════════════════════════════════════════════════

    async def _fill_content(self, page: Page, content: str, image_paths: Optional[List[str]] = None) -> bool:
        """正文：有配图走图文穿插；否则纯文字多级兜底。"""
        valid_images = [p for p in (image_paths or []) if p and os.path.exists(p)]
        if valid_images:
            try:
                if await self._fill_content_with_images(page, content, valid_images):
                    return True
                logger.warning("[搜狐号] 图文穿插写入失败，降级为纯文字正文")
            except Exception as exc:
                logger.warning(f"[搜狐号] 图文穿插异常，降级纯文字: {exc}")

        clean = self._deep_clean_content(content or "")
        clean = clean[: self.MAX_CONTENT_LENGTH]
        if not clean.strip():
            logger.error("❌ [搜狐号] 正文为空")
            return False

        # L1：Quill paste 注入（DataTransfer + ClipboardEvent）
        if await self._paste_text(page, clean, append=False):
            logger.info(f"✅ [搜狐号] 正文已填写 - L1 Quill paste ({len(clean)} 字符)")
            return True

        # L2：keyboard.type 逐字输入（短文）
        try:
            editor = page.locator(sel.CONTENT_EDITOR_PRIMARY).first
            if await editor.count() > 0:
                await editor.click(force=True)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                if len(clean) > 1000:
                    try:
                        await page.keyboard.insert_text(clean)
                    except Exception:
                        await page.keyboard.type(clean, delay=10)
                else:
                    await page.keyboard.type(clean, delay=15)
                logger.info(f"✅ [搜狐号] 正文已填写 - L2 keyboard ({len(clean)} 字符)")
                return True
        except Exception:
            pass

        # L3：通用 contenteditable JS 注入
        ok = await page.evaluate(
            """(text) => {
                const sel = '.ql-editor';
                let target = document.querySelector(sel);
                if (!target) {
                    const nodes = Array.from(document.querySelectorAll('[contenteditable="true"]'));
                    target = nodes.find(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.height > 100 && rect.width > 200;
                    });
                }
                if (!target) return false;
                target.focus();
                target.innerHTML = text.split(/\\n{2,}/).map(p =>
                    '<p>' + p.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>') + '</p>'
                ).join('');
                target.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
                target.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }""",
            clean,
        )
        if ok:
            logger.info(f"✅ [搜狐号] 正文已填写 - L3 JS 注入 ({len(clean)} 字符)")
        return bool(ok)

    async def _fill_content_with_images(self, page: Page, content: str, image_paths: List[str]) -> bool:
        """图文穿插：首块初始化 + 后续逐块追加（文字 paste / 图片 paste 到 Quill）。"""
        blocks = self._build_content_blocks(content, image_paths)
        if not blocks:
            return False
        if not await self._has_editor_loaded(page):
            logger.warning("[搜狐号] 图文穿插：未找到 Quill 编辑器，降级")
            return False

        # 清空编辑器
        await page.evaluate("""() => { const el = document.querySelector('.ql-editor'); if(el) el.innerHTML=''; }""")
        await asyncio.sleep(0.3)

        wrote_text = False
        inserted_images = 0
        first_text = ""
        first = True
        for block in blocks:
            kind = block.get("type")
            value = block.get("content", "") or ""
            if kind == "text":
                if not value.strip():
                    continue
                if first:
                    if not await self._paste_text(page, value, append=False):
                        continue
                    first_text = value
                else:
                    await self._focus_end(page)
                    try:
                        # 只用 1 个 Enter 切分段落（避免空段落放大成巨大空栏）
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                    if not await self._paste_text(page, value, append=True):
                        continue
                    if not first_text:
                        first_text = value
                wrote_text = True
                first = False
            elif kind == "image":
                await self._focus_end(page)
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
                if await self._inject_image(page, value):
                    inserted_images += 1
                    try:
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                else:
                    logger.warning(f"[搜狐号] 正文配图插入失败，跳过: {value}")
                first = False

        # 校验首段文字确实写入
        if first_text and not await self._editor_contains_text(page, first_text):
            logger.warning("[搜狐号] 图文穿插：未检测到首段文字，降级")
            return False
        if inserted_images == 0 and image_paths:
            logger.warning("[搜狐号] 图文穿插：无图片插入成功（保留文字正文）")
        logger.info(f"✅ [搜狐号] 图文正文已写入（文字={wrote_text}, 图片={inserted_images}/{len(image_paths)}）")
        return wrote_text

    async def _has_editor_loaded(self, page: Page) -> bool:
        try:
            return await page.locator(sel.CONTENT_EDITOR_PRIMARY).count() > 0
        except Exception:
            return False

    async def _paste_text(self, page: Page, text: str, append: bool) -> bool:
        """Quill 文字注入：ClipboardEvent paste。append=False 清空后再 paste。"""
        try:
            editor = page.locator(sel.CONTENT_EDITOR_PRIMARY).first
            if await editor.count() == 0:
                return False
            await editor.click(force=True)
            ok = await page.evaluate(
                """({text, append}) => {
                    const el = document.querySelector('.ql-editor');
                    if(!el) return false;
                    el.focus();
                    if(!append) el.innerHTML = '';
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));
                    return true;
                }""",
                {"text": text, "append": append},
            )
            if ok:
                try:
                    await page.keyboard.press("End")
                except Exception:
                    pass
            return bool(ok)
        except Exception as exc:
            logger.debug(f"[搜狐号] paste 文字失败: {exc}")
            return False

    async def _inject_image(self, page: Page, image_path: str) -> bool:
        """Quill 图片注入：构造 File + ClipboardEvent paste。"""
        if not image_path or not os.path.exists(image_path):
            return False
        before = await self._editor_image_count(page)
        try:
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            with open(image_path, "rb") as f:
                data_b64 = base64.b64encode(f.read()).decode("ascii")
            ok = await page.evaluate(
                """({dataB64, mime}) => {
                    const el = document.querySelector('.ql-editor');
                    if(!el) return false;
                    el.focus();
                    const bin = atob(dataB64);
                    const bytes = new Uint8Array(bin.length);
                    for(let i=0;i<bin.length;i++) bytes[i] = bin.charCodeAt(i);
                    const dt = new DataTransfer();
                    dt.items.add(new File([bytes], 'autogeo-image.jpg', {type: mime || 'image/jpeg'}));
                    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));
                    return true;
                }""",
                {"dataB64": data_b64, "mime": mime},
            )
            if not ok:
                return False
            # 等待图片上传完成（搜狐会异步上传）
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await self._editor_image_count(page) > before:
                    return True
            return False
        except Exception as exc:
            logger.debug(f"[搜狐号] 图片注入失败: {exc}")
            return False

    async def _focus_end(self, page: Page) -> None:
        try:
            await page.evaluate(
                """() => {
                    const el = document.querySelector('.ql-editor');
                    if(!el) return;
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    range.collapse(false);
                    if(sel){ sel.removeAllRanges(); sel.addRange(range); }
                }"""
            )
        except Exception:
            pass

    async def _editor_contains_text(self, page: Page, text: str) -> bool:
        if not text:
            return True
        try:
            found = await page.evaluate(
                """(needle) => {
                    const el = document.querySelector('.ql-editor');
                    if(!el) return false;
                    return (el.innerText || '').includes(needle.slice(0, 60));
                }""",
                text,
            )
            return bool(found)
        except Exception:
            return True  # 校验异常不阻断

    async def _editor_image_count(self, page: Page) -> int:
        try:
            count = await page.evaluate(
                """() => {
                    const el = document.querySelector('.ql-editor');
                    if(!el) return 0;
                    return el.querySelectorAll('img').length;
                }"""
            )
            return int(count or 0)
        except Exception:
            return 0

    # ═══════════════════════════════════════════════════════════
    # 封面上传（独立上传区弹窗）
    # ═══════════════════════════════════════════════════════════

    async def _upload_cover(self, page: Page, cover_path: str) -> None:
        """
        搜狐号封面：点"+"图标/区域 -> 弹窗 -> 切"本地上传" -> set_input_files -> 确定。
        上传稳定性优化：直接给弹窗内 input[type=file] 注入文件为主路径，file chooser 降为兜底。
        """
        if not cover_path or not os.path.exists(cover_path):
            logger.warning(f"⚠️ [搜狐号] 封面文件不存在: {cover_path}")
            return
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await self._close_interference(page)

            # 1. 点封面"+"图标（兜底：点封面区域）
            triggered = False
            for selector in sel.COVER_ADD_ICON:
                try:
                    icon = page.locator(selector).first
                    if await icon.count() > 0 and await icon.is_visible(timeout=3000):
                        await icon.click(force=True)
                        triggered = True
                        logger.info(f"[搜狐号] 已点击封面上传图标 ({selector})")
                        break
                except Exception:
                    continue
            if not triggered:
                for selector in sel.COVER_ADD_AREA:
                    try:
                        area = page.locator(selector).first
                        if await area.count() > 0:
                            await area.click(force=True)
                            triggered = True
                            logger.info(f"[搜狐号] 已点击封面区域 ({selector})")
                            break
                    except Exception:
                        continue

            if not triggered:
                logger.warning("⚠️ [搜狐号] 未找到封面入口，尝试直接注入 input[type=file]")
            else:
                # 等待弹窗
                try:
                    await page.wait_for_selector(sel.COVER_DIALOG, timeout=5000)
                    await asyncio.sleep(1)
                    # 切"本地上传"Tab（按文本，data-v 不稳定）
                    await page.evaluate(
                        """(text) => {
                            const headers = Array.from(document.querySelectorAll('h3, div, span, button, li, a'));
                            const tab = headers.find(el => el.innerText && el.innerText.includes(text));
                            if (tab) tab.click();
                        }""",
                        sel.COVER_LOCAL_TAB_TEXT,
                    )
                    await asyncio.sleep(1)
                except Exception:
                    logger.debug("[搜狐号] 封面上传弹窗未出现，尝试直接注入文件")

            # 2. 主路径：直接给弹窗内 input[type=file] 注入文件
            if await self._set_cover_via_input(page, cover_path):
                logger.info("✅ [搜狐号] 封面已通过 input[type=file] 注入")
                await self._confirm_cover_dialog(page)
                await self._wait_cover_uploaded(page)
                return

            # 3. 兜底：点击触发 file chooser
            if await self._set_cover_via_click(page, cover_path):
                logger.info("✅ [搜狐号] 封面已通过文件选择器上传")
                await self._confirm_cover_dialog(page)
                await self._wait_cover_uploaded(page)
                return

            logger.warning("⚠️ [搜狐号] 封面上传未成功，继续发布")
            await self._save_debug_snapshot(page, "cover_upload_warn")
        except Exception as e:
            logger.warning(f"⚠️ [搜狐号] 封面上传失败，继续发布: {e}")
            await self._save_debug_snapshot(page, "cover_upload_fail")

    async def _set_cover_via_input(self, page: Page, cover_path: str) -> bool:
        """主路径：定位弹窗内 input[type=file] 直接 set_input_files。"""
        for selector in sel.COVER_FILE_INPUT:
            try:
                file_input = page.locator(selector).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(cover_path)
                    await asyncio.sleep(2)
                    return True
            except Exception as exc:
                logger.debug(f"[搜狐号] input 注入封面失败 ({selector}): {exc}")
                continue
        return False

    async def _set_cover_via_click(self, page: Page, cover_path: str) -> bool:
        """兜底：点击封面入口触发 file chooser 上传。"""
        targets = list(sel.COVER_ADD_ICON) + list(sel.COVER_ADD_AREA)
        for selector in targets:
            try:
                target = page.locator(selector).first
                if await target.count() == 0:
                    continue
                async with page.expect_file_chooser(timeout=4000) as fc_info:
                    await target.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(cover_path)
                await asyncio.sleep(2)
                return True
            except Exception:
                continue
        return False

    async def _confirm_cover_dialog(self, page: Page) -> None:
        """点击封面上传弹窗的"确定/完成"按钮。"""
        for selector in sel.COVER_CONFIRM:
            try:
                btn = page.locator(selector).last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    logger.info(f"[搜狐号] 已点击封面上传弹窗确认 ({selector})")
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue
        # 兜底：按文本点击
        try:
            for text in ("确定", "完成", "确认"):
                btn = page.get_by_role("button", name=text).last
                if await btn.count() > 0 and await btn.is_visible(timeout=1000):
                    await btn.click(force=True)
                    logger.info(f"[搜狐号] 已点击封面上传弹窗确认（文本兜底: {text}）")
                    await asyncio.sleep(1)
                    return
        except Exception:
            pass

    async def _wait_cover_uploaded(self, page: Page, timeout: int = 12) -> bool:
        for _ in range(max(1, timeout * 2)):
            for selector in sel.COVER_SUCCESS_INDICATOR:
                try:
                    if "text=" in selector:
                        text = selector.replace("text=", "")
                        node = page.get_by_text(text, exact=False).first
                        if await node.count() > 0 and await node.is_visible(timeout=300):
                            return True
                    elif await page.locator(selector).count() > 0:
                        return True
                except Exception:
                    continue
            await asyncio.sleep(0.5)
        return False

    # ═══════════════════════════════════════════════════════════
    # AI 内容声明 & 发布
    # ═══════════════════════════════════════════════════════════

    async def _set_ai_declaration(self, page: Page) -> None:
        """勾选'内容由 AI 生成'声明（选择器随版本变化，失败不阻断）。"""
        try:
            await page.evaluate(
                """(labels) => {
                    const scope = (el) => el.closest('label') || el.parentElement || el;
                    for (const label of labels) {
                        const nodes = Array.from(document.querySelectorAll('label, span, div'))
                            .filter(el => (el.innerText||'').includes(label));
                        for (const node of nodes) {
                            const s = scope(node);
                            const cb = s.querySelector('input[type="checkbox"]')
                                || s.querySelector('[role="checkbox"]')
                                || s.querySelector('[class*="checkbox"]');
                            if (cb) {
                                const checked = cb.checked
                                    || (cb.getAttribute('aria-checked') === 'true')
                                    || String(cb.className||'').includes('checked');
                                if (!checked) cb.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }""",
                sel.AI_DECLARATION_LABELS,
            )
        except Exception:
            pass

    async def _click_publish(self, page: Page) -> bool:
        """点击'发布'按钮，并处理二次确认弹窗。"""
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)

            # 强制启用发布按钮（防灰禁）
            await page.evaluate(
                """() => {
                    document.querySelectorAll('button, li').forEach(btn => {
                        const text = (btn.innerText || '').trim();
                        if (text === '发布' || text === '预览并发布' || text === '确认发布') {
                            if ('disabled' in btn) btn.disabled = false;
                            btn.removeAttribute('disabled');
                            btn.classList.remove('is-disabled');
                            btn.classList.remove('disabled');
                        }
                    });
                }"""
            )

            for selector in sel.PUBLISH_BUTTON:
                try:
                    buttons = page.locator(selector)
                    count = await buttons.count()
                    for i in range(count - 1, -1, -1):
                        btn = buttons.nth(i)
                        try:
                            if not await btn.is_visible(timeout=1000):
                                continue
                        except Exception:
                            continue
                        text = (await btn.inner_text()).strip()
                        if any(bad in text for bad in sel.PUBLISH_BUTTON_EXCLUDE_TEXT):
                            continue
                        if text not in ["发布", "预览并发布", "确认发布", "立即发布"]:
                            continue
                        await btn.scroll_into_view_if_needed(timeout=3000)
                        await btn.click(force=True)
                        logger.info(f"✅ [搜狐号] 已点击发布按钮: {text} ({selector})")
                        await asyncio.sleep(2)
                        await self._handle_publish_confirm(page)
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.error(f"❌ [搜狐号] 点击发布失败: {e}")
            return False

    async def _handle_publish_confirm(self, page: Page) -> None:
        """处理'发布'后的二次确认弹窗。"""
        for text in sel.PUBLISH_CONFIRM:
            try:
                btn = page.locator(f'button:has-text("{text}")').last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    await asyncio.sleep(1)
                    logger.info(f"[搜狐号] 已确认发布弹窗: {text}")
                    return
            except Exception:
                continue

        # 安全验证（滑块/验证码）-> 抛人工介入
        try:
            if await page.locator(sel.CAPTCHA_INDICATOR).count() > 0:
                logger.warning("🚧 [搜狐号] 触发安全验证")
                try:
                    await page.wait_for_selector(sel.CAPTCHA_INDICATOR, state="hidden", timeout=60000)
                except Exception as exc:
                    raise RuntimeError("搜狐号安全验证未完成，请人工处理后重试发布") from exc
                logger.info("[搜狐号] 安全验证已完成，继续发布流程")
        except RuntimeError:
            raise
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 等待发布结果
    # ═══════════════════════════════════════════════════════════

    async def _wait_for_publish_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）"""
        last_url = page.url
        for _ in range(60):  # 60次 × 2秒 = 120秒
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            # 失败检测
            for text in sel.PUBLISH_FAIL_INDICATORS:
                try:
                    clean = text.replace("text=", "")
                    node = page.get_by_text(clean, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        msg = (await node.inner_text()).strip()
                        logger.error(f"❌ [搜狐号] 检测到失败提示: {msg}")
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
            for text in sel.SUCCESS_INDICATOR:
                try:
                    clean = text.replace("text=", "")
                    node = page.get_by_text(clean, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        logger.success(f"🎉 [搜狐号] 检测到成功提示: {clean}")
                        return {"success": True, "platform_url": page.url}
                except Exception:
                    continue

            # URL 跳转检测
            if page.url != last_url and re.search(sel.SUCCESS_URL_PATTERN, page.url, re.IGNORECASE):
                logger.success(f"🎉 [搜狐号] 检测到跳转，认为发布成功: {page.url}")
                return {"success": True, "platform_url": page.url}

            await asyncio.sleep(2)

        logger.warning("⏰ [搜狐号] 120 秒内未检测到明确结果，需要人工复核")
        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": "未检测到明确的发布成功提示，请到搜狐号后台人工确认",
            "debug_path": debug_path,
        }

    # ═══════════════════════════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════════════════════════

    def _deep_clean_content(self, content: str) -> str:
        """清理 Markdown/HTML，输出适合 Quill 粘贴的纯文本。"""
        if not content:
            return ""
        text = content
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        # 与 base.markdown_to_plain_text 保持一致：标题/段落前后只留 1 个换行，
        # 不要 \n\n。富文本编辑器段落自带 margin，双换行会被放大成巨大空栏。
        text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n\1\n", text, flags=re.I | re.S)
        text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.I | re.S)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        lines = text.splitlines()
        if lines and re.match(r"^#\s+", lines[0]):
            lines = lines[1:]
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


# ═══════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════

SOHU_CONFIG = {
    "id": "sohu",
    "name": "搜狐号",
    "code": "SOHU",
    "login_url": "https://mp.sohu.com/",
    "publish_url": "https://mp.sohu.com/mpfe/v4/contentManagement/firstpage",
    "color": "#FF6B00",
}

registry.register("sohu", SohuPublisher("sohu", SOHU_CONFIG))
