# -*- coding: utf-8 -*-
"""
博客园发布适配器

博客园平台: https://i.cnblogs.com/EditPosts.aspx
博客园是国内知名的IT技术博客社区。
"""

import asyncio
import base64
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from loguru import logger
from playwright.async_api import Page

from .base import BasePublisher, registry
from .note_utils import materialize_images


class CnblogsPublisher(BasePublisher):
    """博客园文章发布器"""

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
                return {"allowed": False, "reason": f"距上次发布仅{int(minutes)}分钟，需≥{self.MIN_INTERVAL_MINUTES}分钟"}

        return {"allowed": True, "reason": "频率检查通过"}

    async def publish(self, page: Page, article: Any, account: Any, declare_ai_content: bool = True) -> Dict[str, Any]:
        temp_files = []
        stage = "init"

        try:
            logger.info("🚀 [博客园] 开始发布文章...")

            rate = self._check_rate_limit()
            if not rate["allowed"]:
                logger.warning(f"⚠️ [博客园] 频率限制: {rate['reason']}")
                return {"success": False, "error_msg": f"频率限制: {rate['reason']}"}

            title = getattr(article, "title", "") or "未命名文章"
            content = getattr(article, "content", "") or ""

            if len(title) > self.MAX_TITLE_LENGTH:
                title = title[:self.MAX_TITLE_LENGTH]

            if len(content) > self.MAX_CONTENT_LENGTH:
                logger.warning(f"⚠️ [博客园] 正文{len(content)}字，超过限制{self.MAX_CONTENT_LENGTH}字，将截断")
                content = content[:self.MAX_CONTENT_LENGTH]

            stage = "navigate"
            publish_url = self.config.get("publish_url", "https://i.cnblogs.com/EditPosts.aspx")
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
            logger.info(f"📷 [博客园] 已准备 {len(image_paths)} 张图片")

            stage = "fill_title"
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "填充标题失败")

            stage = "fill_content"
            if not await self._fill_content_with_images(page, content, image_paths):
                return await self._fail(page, stage, "填充正文失败")

            stage = "publish"
            if not await self._click_publish(page):
                return await self._fail(page, stage, "点击发布按钮失败")

            stage = "wait_result"
            result = await self._wait_for_result(page)
            if result.get("success"):
                self._publish_history.append(datetime.now())
            return result

        except Exception as e:
            logger.exception(f"❌ [博客园] 发布失败 stage={stage}: {e}")
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
            raise RuntimeError("博客园账号未登录，请重新授权")

        login_markers = ["text=登录", "text=立即登录", "text=账号登录"]
        for selector in login_markers:
            try:
                marker = page.locator(selector).first
                if await marker.count() > 0 and await marker.is_visible(timeout=2000):
                    raise RuntimeError("博客园账号未登录，请重新授权")
            except RuntimeError:
                raise
            except Exception:
                continue

    async def _close_popups(self, page: Page) -> None:
        """关闭弹窗"""
        close_selectors = ['button:has-text("知道了")', 'button:has-text("关闭")', '.close-btn', '[class*="close"]']
        for _ in range(3):
            for selector in close_selectors:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=1000):
                        await btn.click()
                        await asyncio.sleep(0.5)
                except:
                    pass

    async def _fill_title(self, page: Page, title: str) -> bool:
        """填充标题"""
        title_selectors = [
            'input[placeholder*="标题"]',
            'input[name*="title"]',
            '#post-title',
            'input#txtTitle',
            '#txtTitle',
        ]
        for selector in title_selectors:
            try:
                inp = page.locator(selector).first
                if await inp.count() > 0 and await inp.is_visible(timeout=3000):
                    await inp.fill("")
                    await inp.fill(title)
                    logger.info(f"✅ [博客园] 标题已填充: {title[:30]}...")
                    return True
            except Exception as e:
                logger.debug(f"[博客园] 标题选择器 {selector} 失败: {e}")
                continue
        return False

    async def _fill_content_with_images(self, page: Page, content: str, image_paths: List[str]) -> bool:
        """填充正文内容（支持图片）"""
        content_selectors = [
            '#post-body',
            '#txtContent',
            'textarea[name*="content"]',
            '.editor-view',
            '.markdown-body',
            '[contenteditable="true"]',
        ]

        plain_content = self.markdown_to_plain_text(content, drop_first_h1=True)

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
                        const target = document.querySelector('#post-body, #txtContent, .editor-view, .markdown-body, [contenteditable="true"]');
                        if (target) target.dispatchEvent(ev);
                    }""",
                        plain_content,
                    )
                    logger.info(f"✅ [博客园] 正文已填充: {len(plain_content)} 字符")
                    await asyncio.sleep(1)

                    if image_paths:
                        await self._upload_images(page, image_paths)

                    return True
            except Exception as e:
                logger.debug(f"[博客园] 内容选择器 {selector} 失败: {e}")
                continue

        return False

    async def _upload_images(self, page: Page, image_paths: List[str]) -> bool:
        """上传图片到博客园"""
        try:
            upload_selectors = [
                'button[title*="图片"]',
                'button[title*="上传"]',
                '.upload-btn',
                'input[type="file"][accept*="image"]',
            ]

            for i, img_path in enumerate(image_paths[:50]):
                logger.info(f"📷 [博客园] 上传第 {i+1}/{len(image_paths)} 张图片...")

                uploaded = False
                for selector in upload_selectors:
                    try:
                        file_input = page.locator(selector).last
                        if await file_input.count() > 0 and await file_input.is_visible(timeout=2000):
                            await file_input.set_input_files(img_path)
                            uploaded = True
                            logger.success(f"✅ [博客园] 第 {i+1} 张图片上传成功")
                            await asyncio.sleep(2)
                            break
                    except Exception as e:
                        logger.debug(f"[博客园] 上传选择器 {selector} 失败: {e}")
                        continue

                if not uploaded:
                    try:
                        await self._paste_image_via_clipboard(page, img_path)
                        logger.success(f"✅ [博客园] 第 {i+1} 张图片粘贴成功")
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.warning(f"⚠️ [博客园] 第 {i+1} 张图片上传失败: {e}")

        except Exception as e:
            logger.warning(f"⚠️ [博客园] 图片上传流程异常: {e}")

        return True

    async def _paste_image_via_clipboard(self, page: Page, image_path: str) -> bool:
        """通过剪贴板粘贴图片"""
        try:
            with open(image_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            await page.evaluate(
                """(data) => {
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
                const target = document.querySelector('#post-body, #txtContent, .editor-view, .markdown-body, [contenteditable="true"]');
                if (target) {
                    const event = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
                    target.dispatchEvent(event);
                }
            }""",
                {"b64": b64_data},
            )
            return True
        except Exception as e:
            logger.warning(f"[博客园] 剪贴板粘贴图片失败: {e}")
            return False

    async def _click_publish(self, page: Page) -> bool:
        """点击发布按钮"""
        publish_selectors = [
            'button:has-text("发布")',
            'button:has-text("立即发布")',
            'button:has-text("保存")',
            'input:has-text("发布")',
            '#btnPublish',
            '.btn-publish',
        ]

        for selector in publish_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    logger.info("✅ [博客园] 已点击发布按钮")
                    await asyncio.sleep(2)
                    return True
            except Exception as e:
                logger.debug(f"[博客园] 发布按钮 {selector} 失败: {e}")
                continue

        return False

    async def _wait_for_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）"""
        for i in range(60):  # 60次 × 2秒 = 120秒
            current_url = page.url
            logger.debug(f"[博客园] 第{(i+1)*2}秒, URL: {current_url}")

            try:
                success_selectors = ["text=发布成功", "text=已发布", "text=保存成功"]
                for sel in success_selectors:
                    elem = page.locator(sel).first
                    if await elem.count() > 0 and await elem.is_visible(timeout=500):
                        logger.success("🎉 [博客园] 检测到发布成功提示")
                        return {"success": True, "platform_url": page.url}
            except:
                pass

            await asyncio.sleep(2)

        logger.error(f"❌ [博客园] 发布超时（已等待120秒）: {page.url}")
        return {"success": False, "error_msg": f"发布超时: {page.url}"}

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        """失败处理"""
        return {
            "success": False,
            "error_msg": f"[博客园] {stage}失败: {msg}",
            "platform_url": page.url if page else None,
        }

    async def _manual_fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        """需要人工干预的处理"""
        return {
            "success": False,
            "platform_url": page.url if page else None,
            "error_msg": f"[博客园] {stage}: {msg}",
            "requires_manual_intervention": True,
            "manual_intervention_stage": stage,
        }


# 注册博客园发布器
CNBLOGS_CONFIG = {
    "name": "博客园",
    "publish_url": "https://i.cnblogs.com/EditPosts.aspx",
    "color": "#2A6E3F",
    "version": "v1.1",
}
registry.register("cnblogs", CnblogsPublisher("cnblogs", CNBLOGS_CONFIG))
