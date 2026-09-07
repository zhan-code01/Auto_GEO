# -*- coding: utf-8 -*-
"""
抖音发布适配器 - v2.0 Content Pilot 优化版

变更记录:
v2.0: 移植 Content Pilot (MIT) 的选择器体系和 humanize 模拟真人操作
      - selectors 集中到 douyin_selectors.py
      - humanize 模块替代硬编码 asyncio.sleep
      - 多重回退：文本定位 + CSS选择器 + JS注入
      - 更完整的登录态检测
      - 增加图文模式切换（发布图文内容）
"""

import asyncio
import os
import re
import random
import tempfile
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
from playwright.async_api import Page
from loguru import logger

from . import douyin_selectors as sel
from .base import BasePublisher, registry
from ..humanize import human_click, human_type, random_delay, short_delay
from .note_utils import materialize_images, normalize_tags, plain_note_from_article


class DouyinPublisher(BasePublisher):
    """
    抖音发布适配器 - v2.0

    发布流程:
    1. 导航到创作者平台
    2. 检测并切换到图文模式
    3. 上传图片
    4. 填充描述文本
    5. 添加话题标签
    6. 发布
    """

    MAX_TITLE_LENGTH = 50
    MAX_DESC_LENGTH = 980

    async def publish(self, page: Page, article: Any, account: Any, declare_ai_content: bool = True) -> Dict[str, Any]:
        temp_files = []
        stage = "init"
        try:
            logger.info("🚀 [抖音 v2.0] 开始发布流程...")

            # 1. 提取标题和内容
            safe_title = self._clean_title(getattr(article, "title", "") or "未命名")
            content = getattr(article, "content", "") or ""
            keyword = self._extract_keyword(safe_title)

            # 2. 导航到发布页
            stage = "navigate"
            await self._navigate_to_publish(page)

            # 3. 检测登录态
            stage = "login_check"
            await self._ensure_logged_in(page)

            # 4. 准备图文图片：优先使用文章里的 Markdown/HTML 图片或显式图片字段
            stage = "materialize_images"
            image_paths, materialized_temp_files = await materialize_images(article, limit=9)
            temp_files.extend(materialized_temp_files)
            if not image_paths:
                raise RuntimeError("图片上传失败：文章中的图片无法下载，请检查网络后重试。如问题持续，请重新生成文章。")
            logger.info(f"[抖音] 已准备 {len(image_paths)} 张图文图片")

            # 5. 切换到图文模式
            stage = "switch_image_mode"
            await self._switch_to_image_mode(page)

            # 6. 上传图片
            stage = "upload_images"
            await self._upload_images(page, image_paths)

            # 7. 填充标题（codegen: placeholder="添加作品标题"）
            stage = "fill_title"
            await self._fill_title(page, safe_title)

            # 8. 填充描述
            stage = "fill_description"
            tags = normalize_tags(article, safe_title, max_tags=5)
            await self._fill_description(page, self._compose_limited_description(article, tags))

            # 9. 话题已纳入 980 字描述内，避免二次追加后超过平台限制
            logger.info("[抖音] 话题已随描述一次性写入，跳过二次追加")

            # 10. AI声明（可选）
            if declare_ai_content:
                stage = "declare_ai"
                await self._try_declare_ai(page)

            # 11. 发布
            stage = "publish"
            if not await self._click_publish(page):
                raise RuntimeError("未找到或无法点击抖音发布按钮")

            # 12. 等待结果
            stage = "wait_result"
            return await self._wait_for_publish_result(page)

        except Exception as e:
            logger.exception(f"[抖音] 发布失败 stage={stage}: {e}")
            return await self._fail(page, stage, str(e))
        finally:
            for f in temp_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

    # ==================== 导航 & 登录 ====================

    async def _navigate_to_publish(self, page: Page) -> None:
        publish_url = self.config.get(
            "publish_url",
            "https://creator.douyin.com/creator-micro/content/upload?default-tab=3",
        )
        logger.info(f"[抖音] 导航到发布页: {publish_url}")
        await self._prepare_browser_permissions(page)
        await page.goto(publish_url, wait_until="domcontentloaded", timeout=60000)
        await random_delay(2, 4)
        await self._dismiss_permission_prompt(page)

        if not await self._wait_for_image_publish_surface(page, timeout_ms=12000):
            await self._click_high_quality_publish(page)
            await random_delay(1, 2)
            await self._open_image_publish_mode(page)

        if not await self._wait_for_image_publish_surface(page, timeout_ms=30000):
            debug_path = await self._save_debug_snapshot(page, "navigate")
            raise RuntimeError(f"未进入抖音图文发布页，当前可能停在创作者中心首页。debug={debug_path}")

    async def _prepare_browser_permissions(self, page: Page) -> None:
        """预处理浏览器权限，避免 Chromium 原生定位弹窗挡住页面操作。"""
        try:
            await page.context.set_geolocation({"latitude": 31.2304, "longitude": 121.4737})
            await page.context.grant_permissions(["geolocation"], origin="https://creator.douyin.com")
            logger.info("[抖音] 已预授权 creator.douyin.com 定位权限")
        except Exception as exc:
            logger.warning("[抖音] 预授权定位权限失败，将尝试页面级关闭: {}", exc)

    async def _dismiss_permission_prompt(self, page: Page) -> None:
        try:
            await page.keyboard.press("Escape")
            await short_delay()
        except Exception:
            pass

    async def _ensure_logged_in(self, page: Page) -> None:
        if "login" in page.url.lower():
            raise RuntimeError("抖音登录态已失效，请重新授权")
        logger.info("[抖音] 登录态正常")

    async def _has_image_publish_surface(self, page: Page) -> bool:
        if "content/post/image" in page.url:
            try:
                if await page.locator('input[type="file"]').count() > 0:
                    return True
            except Exception:
                pass
        if "content/upload" in page.url:
            try:
                if await page.locator('input[type="file"][accept*="image"]').count() > 0:
                    return True
            except Exception:
                pass

        for selector in [
            'input[type="file"][accept*="image"]',
            "text=发布图文",
            "text=上传图片",
            "text=点击上传",
            "text=拖拽上传",
            "text=作品描述",
        ]:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible(timeout=800):
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_image_publish_surface(self, page: Page, timeout_ms: int = 15000) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while asyncio.get_running_loop().time() < deadline:
            if await self._has_image_publish_surface(page):
                return True
            await asyncio.sleep(0.8)
        return False

    async def _click_high_quality_publish(self, page: Page) -> bool:
        try:
            locator = page.get_by_text("高清发布", exact=True).first
            if await locator.count() and await locator.is_visible(timeout=1500):
                await locator.click(force=True)
                logger.info("[抖音] 已点击高清发布入口: text=高清发布")
                return True
        except Exception:
            pass

        for selector in [
            'button:has-text("高清发布")',
            'div:has-text("高清发布")',
            'span:has-text("高清发布")',
            "text=高清发布",
        ]:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible(timeout=1500):
                    await locator.click(force=True)
                    logger.info(f"[抖音] 已点击高清发布入口: {selector}")
                    return True
            except Exception:
                continue
        return False

    async def _open_image_publish_mode(self, page: Page) -> bool:
        for text in ["发布图文", "图文", "图片", "上传图片"]:
            try:
                locator = page.get_by_text(text, exact=True).first
                if await locator.count() and await locator.is_visible(timeout=1500):
                    await locator.click(force=True)
                    logger.info(f"[抖音] 已选择图文发布入口: text={text}")
                    await random_delay(1, 2)
                    return True
            except Exception:
                continue

        for selector in [
            'button:has-text("发布图文")',
            'div:has-text("发布图文")',
            'span:has-text("发布图文")',
            'a:has-text("发布图文")',
            'button:has-text("图文")',
            'div:has-text("图文")',
            'span:has-text("图文")',
            'button:has-text("图片")',
            'div:has-text("图片")',
            'span:has-text("图片")',
        ]:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible(timeout=1500):
                    await locator.click(force=True)
                    logger.info(f"[抖音] 已选择图文发布入口: {selector}")
                    await random_delay(1, 2)
                    return True
            except Exception:
                continue
        return False

    # ==================== 图片下载 ====================

    async def _download_images(self, keyword: str, count: int = 4) -> List[str]:
        paths = []
        used_seeds = set()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        async with httpx.AsyncClient(headers=headers, verify=False, timeout=30.0) as client:
            for i in range(count):
                while True:
                    seed = random.randint(1, 10000)
                    if seed not in used_seeds:
                        used_seeds.add(seed)
                        break

                encoded_kw = urllib.parse.quote(f"high quality photo of {keyword} aesthetic {seed}")
                url = f"https://image.pollinations.ai/prompt/{encoded_kw}?width=1080&height=1440&nologo=true"

                for attempt in range(2):
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200 and len(resp.content) > 2000:
                            tmp = os.path.join(tempfile.gettempdir(), f"dy_v2_{random.randint(10000, 99999)}.jpg")
                            with open(tmp, "wb") as f:
                                f.write(resp.content)
                            paths.append(tmp)
                            logger.info(f"[抖音] 图片 {i + 1} 下载成功 ({len(resp.content)} bytes)")
                            break
                    except Exception as e:
                        logger.warning(f"[抖音] 图片 {i + 1} 下载失败 (尝试 {attempt + 1}): {e}")

                if len(paths) <= i:
                    # 兜底
                    fallback = f"https://picsum.photos/1080/1440?random={seed}"
                    try:
                        resp = await client.get(fallback)
                        if resp.status_code == 200 and len(resp.content) > 2000:
                            tmp = os.path.join(tempfile.gettempdir(), f"dy_v2_fb_{random.randint(10000, 99999)}.jpg")
                            with open(tmp, "wb") as f:
                                f.write(resp.content)
                            paths.append(tmp)
                            logger.info(f"[抖音] 图片 {i + 1} 兜底图片下载成功")
                    except Exception:
                        pass

        return paths

    # ==================== 图文模式切换 ====================

    async def _switch_to_image_mode(self, page: Page) -> None:
        """切换到图文发布模式（抖音默认可能是视频模式）"""
        logger.info("[抖音] 检查图片模式...")

        if "content/post/image" not in page.url:
            image_url = self.config.get(
                "image_publish_url",
                "https://creator.douyin.com/creator-micro/content/post/image?default-tab=3&enter_from=publish_page&media_type=image&type=new",
            )
            try:
                logger.info("[抖音] 尝试直接进入图文发布页: {}", image_url)
                await page.goto(image_url, wait_until="domcontentloaded", timeout=60000)
                await random_delay(2, 4)
                await self._dismiss_permission_prompt(page)
                if await self._has_image_publish_surface(page):
                    return
            except Exception as exc:
                logger.warning("[抖音] 直接进入图文发布页失败，继续尝试页面入口: {}", exc)

        for selector in sel.IMAGE_MODE_SWITCH:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await human_click(page, selector)
                    logger.info(f"[抖音] 切换到图文模式 (selector: {selector})")
                    await random_delay(2, 4)
                    return
            except Exception:
                continue

        if await self._open_image_publish_mode(page):
            return

        if await self._has_image_publish_surface(page):
            logger.info("[抖音] 未检测到图文模式切换按钮，当前已在可上传页面")
            return

        debug_path = await self._save_debug_snapshot(page, "switch_image_mode")
        raise RuntimeError(f"未找到抖音图文模式入口。debug={debug_path}")

    # ==================== 图片上传 ====================

    async def _upload_images(self, page: Page, image_paths: List[str]) -> None:
        """上传图片到抖音发布页"""
        try:
            upload_btn = page.get_by_role("button", name="上传图文").first
            if await upload_btn.count() > 0:
                await upload_btn.set_input_files(image_paths)
                logger.info(f"[抖音] 已按 codegen 路径上传 {len(image_paths)} 张图片 (button=上传图文)")
                await self._wait_for_image_editor(page)
                return
        except Exception as exc:
            logger.debug("[抖音] codegen 上传图文按钮路径不可用，尝试 input 兜底: {}", exc)

        # 尝试找到图片上传 input
        for selector in [sel.PUBLISH_IMAGE_UPLOAD, 'input[type="file"][accept*="image"]']:
            try:
                file_input = page.locator(selector).first
                if await file_input.count() > 0:
                    await file_input.set_input_files(image_paths)
                    logger.info(f"[抖音] 已上传 {len(image_paths)} 张图片 (selector: {selector})")
                    await self._wait_for_image_editor(page)
                    return
            except Exception:
                continue

        # 兜底：只使用明确支持图片，或没有声明 accept 的 file input；避免把图片塞进视频上传框。
        all_inputs = page.locator('input[type="file"]')
        count = await all_inputs.count()
        for index in range(count):
            current = all_inputs.nth(index)
            accept = ""
            try:
                accept = (await current.get_attribute("accept")) or ""
            except Exception:
                pass
            accept_lower = accept.lower()
            if accept_lower and "image" not in accept_lower:
                continue
            try:
                await current.set_input_files(image_paths)
                logger.info(f"[抖音] 兜底方式上传图片: {len(image_paths)} 张 (accept={accept})")
                await self._wait_for_image_editor(page)
                return
            except Exception:
                continue

        chooser_targets = [
            "text=点击上传",
            "text=直接将图片文件拖入此区域",
            "text=上传图片",
            'div:has-text("点击上传")',
            'div:has-text("上传图片")',
            'div:has-text("直接将图片文件拖入此区域")',
        ]
        for selector in chooser_targets:
            try:
                locator = page.locator(selector).first
                if not await locator.count() or not await locator.is_visible(timeout=1500):
                    continue
                async with page.expect_file_chooser(timeout=8000) as fc_info:
                    await locator.click(force=True)
                file_chooser = await fc_info.value
                await file_chooser.set_files(image_paths)
                logger.info(f"[抖音] 通过上传区域选择图片: {len(image_paths)} 张 (selector: {selector})")
                await self._wait_for_image_editor(page)
                return
            except Exception:
                continue

        debug_path = await self._save_debug_snapshot(page, "upload_images")
        raise RuntimeError(f"未找到抖音图片上传 input。debug={debug_path}")

    # ==================== 描述填充 ====================

    async def _wait_for_image_editor(self, page: Page) -> None:
        """等待上传后进入图文编辑页。"""
        try:
            await page.wait_for_url("**/creator-micro/content/post/image**", timeout=45000)
        except Exception:
            pass
        try:
            await page.get_by_placeholder("添加作品标题").wait_for(state="visible", timeout=20000)
            return
        except Exception:
            pass
        try:
            await page.locator(".zone-container").first.wait_for(state="visible", timeout=15000)
        except Exception:
            await random_delay(3, 5)

    async def _fill_title(self, page: Page, title: str) -> None:
        clean_title = self._clean_title(title)
        candidates = [
            page.get_by_placeholder("添加作品标题"),
            page.locator('input[placeholder*="添加作品标题"]'),
            page.locator('textarea[placeholder*="添加作品标题"]'),
            page.locator('input[placeholder*="作品标题"]'),
            page.locator('textarea[placeholder*="作品标题"]'),
        ]

        for locator in candidates:
            try:
                target = locator.first
                if await target.count() > 0 and await target.is_visible(timeout=5000):
                    await target.click()
                    await target.fill(clean_title)
                    logger.info("[抖音] 标题已填充")
                    await short_delay()
                    return
            except Exception:
                continue

        debug_path = await self._save_debug_snapshot(page, "fill_title")
        raise RuntimeError(f"未找到抖音标题输入框。debug={debug_path}")

    async def _fill_description(self, page: Page, content: str) -> None:
        """填充作品描述"""
        clean_content = self._deep_clean_content(content)

        for selector in [".zone-container", *sel.PUBLISH_DESC_INPUT]:
            try:
                desc_el = page.locator(selector).first
                if await desc_el.count() > 0 and await desc_el.is_visible(timeout=5000):
                    await desc_el.click()
                    await short_delay()

                    if selector == ".zone-container":
                        await desc_el.fill(clean_content)
                        logger.info("[抖音] 正文已填充 (selector: .zone-container)")
                        await random_delay(1, 3)
                        return

                    # 使用 DataTransfer 模拟粘贴（更可靠）
                    await page.evaluate(
                        """(text) => {
                            const dt = new DataTransfer();
                            dt.setData("text/plain", text);
                            const ev = new ClipboardEvent("paste", {
                                clipboardData: dt, bubbles: true, cancelable: true
                            });
                            document.activeElement.dispatchEvent(ev);
                        }""",
                        clean_content,
                    )
                    await random_delay(1, 3)
                    logger.info(f"[抖音] 描述已填充 (selector: {selector})")
                    return
            except Exception:
                continue

        # 兜底
        logger.warning("[抖音] 未找到描述输入框，尝试直接键盘输入...")
        try:
            await page.keyboard.type(clean_content, delay=30)
            logger.info("[抖音] 描述已通过键盘输入")
        except Exception as e:
            logger.warning(f"[抖音] 键盘输入描述失败: {e}")

    async def _add_topics(self, page: Page, title: str, tags: Optional[List[str]] = None) -> None:
        """在描述中添加话题标签"""
        topics = tags or []
        if not topics:
            topic = title[:8] if len(title) > 8 else title
            topic = re.sub(r"[^\w\u4e00-\u9fff]", "", topic)
            topics = [topic] if topic else []
        if not topics:
            return

        try:
            for selector in sel.PUBLISH_DESC_INPUT:
                try:
                    desc_el = page.locator(selector).first
                    if await desc_el.count() > 0 and await desc_el.is_visible():
                        await desc_el.click()
                        await short_delay()
                        await page.keyboard.press("End")
                        await short_delay()
                        topic_text = " " + " ".join(f"#{topic}" for topic in topics)
                        await page.keyboard.type(topic_text, delay=50)
                        logger.info(f"[抖音] 话题已添加: {topic_text.strip()}")
                        await short_delay()
                        return
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"[抖音] 添加话题标签失败: {e}")

    async def _try_declare_ai(self, page: Page) -> None:
        """尝试设置AI声明"""
        try:
            ai_selectors = [
                "text=AI声明",
                "text=AI创作",
                "text=AI生成",
                '[class*="ai"]',
            ]
            for selector in ai_selectors:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                        await btn.click(force=True)
                        logger.info("[抖音] AI声明已设置")
                        await short_delay()
                        return
                except Exception:
                    continue
        except Exception:
            logger.debug("[抖音] 未找到AI声明入口，跳过")

    # ==================== 发布 ====================

    async def _click_publish(self, page: Page) -> bool:
        """点击发布按钮"""
        await random_delay(1, 3)

        exact_publish = re.compile(r"^\s*发布\s*$")
        candidates = [
            page.get_by_role("button", name=exact_publish),
            page.locator("button").filter(has_text=exact_publish),
            page.locator('[role="button"]').filter(has_text=exact_publish),
        ]

        for btn in candidates:
            try:
                count = await btn.count()
                for i in range(count):
                    current = btn.nth(i)
                    if not await current.count() or not await current.is_visible(timeout=2000):
                        continue

                    text = (await current.inner_text()).strip()
                    if text != "发布":
                        continue

                    in_side_publish = await current.evaluate(
                        """el => Boolean(el.closest(
                            'aside, [class*="sider"], [id*="side-upload"], [class*="header-button"]'
                        ))"""
                    )
                    if in_side_publish:
                        logger.debug("[抖音] 跳过侧边栏发布入口: {}", text)
                        continue

                    if await current.is_enabled():
                        await current.click(force=True)
                        logger.info("[抖音] 已点击底部发布按钮")
                        await random_delay(2, 4)
                        return await self._handle_confirm(page)
            except Exception:
                continue

        logger.error("[抖音] 未找到可点击的发布按钮")
        return False

    async def _handle_confirm(self, page: Page) -> bool:
        """处理发布后的确认弹窗"""
        confirm_selectors = [
            'button:has-text("确认")',
            'button:has-text("确定")',
            'button:has-text("确认发布")',
            'button:has-text("仍要发布")',
            ".confirm-btn",
        ]
        for selector in confirm_selectors:
            try:
                confirm_btn = page.locator(selector).first
                if await confirm_btn.count() > 0 and await confirm_btn.is_visible(timeout=3000):
                    await confirm_btn.click(force=True)
                    logger.info(f"[抖音] 确认发布 (selector: {selector})")
                    await random_delay(2, 4)
                    return True
            except Exception:
                continue
        return True

    # ==================== 结果检测 ====================

    async def _wait_for_publish_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）"""
        success_keywords = ["发布成功", "提交成功", "发布完成", "作品已发布"]
        fail_keywords = ["发布失败", "违规", "失败", "请上传", "未上传", "上传失败"]

        for _ in range(60):  # 60次 × 2秒 = 120秒
            manual_result = await self.ensure_publish_can_continue(page, "wait_result")
            if manual_result:
                debug_path = await self._save_debug_snapshot(page, "manual_wait_result")
                manual_result["error_msg"] = (
                    f"{manual_result.get('error_msg') or '抖音发布触发人工验证'} debug={debug_path}"
                )
                return manual_result

            for kw in success_keywords:
                try:
                    node = page.get_by_text(kw, exact=False).first
                    if await node.count() > 0 and await node.is_visible():
                        logger.success(f"[抖音] 发布成功: 检测到 '{kw}'")
                        return {"success": True, "platform_url": page.url}
                except Exception:
                    continue

            for kw in fail_keywords:
                try:
                    node = page.get_by_text(kw, exact=False).first
                    if await node.count() > 0 and await node.is_visible():
                        text = await node.inner_text()
                        logger.error(f"[抖音] 发布失败: {text}")
                        return {"success": False, "error_msg": f"抖音提示: {text}"}
                except Exception:
                    continue

            # Do not treat creator-center navigation text such as "作品管理" as
            # success. It is present on normal backend pages even when submit did
            # not complete. A real success must come from an explicit result
            # prompt or a post-publish redirect away from the creator backend.
            if "creator" not in page.url and "douyin.com" in page.url:
                return {"success": True, "platform_url": page.url}

            await asyncio.sleep(2)

        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": f"超时未检测到抖音发布结果提示，请到抖音创作者后台确认。debug={debug_path}",
        }

    # ==================== 工具方法 ====================

    def _clean_title(self, title: str) -> str:
        text = re.sub(r"#|\*|\"", "", title).strip()
        return text[: self.MAX_TITLE_LENGTH] if len(text) > self.MAX_TITLE_LENGTH else text

    def _extract_keyword(self, title: str) -> str:
        cleaned = re.sub(r"[^\w\u4e00-\u9fff]", " ", title)
        words = cleaned.split()
        if words:
            return words[0] if len(words) == 1 else f"{words[0]} {words[1]}"
        return "科技 AI"

    def _deep_clean_content(self, content: str) -> str:
        """清理HTML/markdown内容"""
        content = re.sub(r"!\[.*?\]\(.*?\)", "", content)  # 移除图片
        content = re.sub(r"<[^>]+>", "", content)  # 移除HTML
        content = re.sub(r"#+\s*", "", content)  # 移除markdown标题
        content = re.sub(r"\*\*+", "", content)  # 移除加粗
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        return "\n\n".join(lines)[: self.MAX_DESC_LENGTH]

    def _compose_limited_description(self, article: Any, tags: Optional[List[str]] = None) -> str:
        tag_text = " ".join(f"#{tag}" for tag in (tags or []) if tag)
        suffix = f" {tag_text}" if tag_text else ""
        available = self.MAX_DESC_LENGTH - len(suffix)
        note = plain_note_from_article(article, limit=max(0, available)).strip()
        return f"{note}{suffix}".strip()[: self.MAX_DESC_LENGTH]

    async def _fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        logger.error(f"[抖音] 发布失败 [{stage}]: {message}")
        return {"success": False, "error_msg": f"抖音发布失败[{stage}]: {message}", "debug_path": debug_path}

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        debug_dir = Path("backend/debug/douyin")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[抖音] 保存调试 HTML 失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[抖音] 保存调试截图失败: {}", exc)
        return str(html_path)


# 注册
DOUYIN_CONFIG = {
    "name": "抖音",
    "publish_url": "https://creator.douyin.com/creator-micro/content/upload?default-tab=3",
    "image_publish_url": "https://creator.douyin.com/creator-micro/content/post/image?default-tab=3&enter_from=publish_page&media_type=image&type=new",
    "color": "#000000",
}
registry.register("douyin", DouyinPublisher("douyin", DOUYIN_CONFIG))
