# -*- coding: utf-8 -*-
"""
CSDN 发布适配器 — codegen 验证版

完全按照 Playwright codegen 录制的操作路径实现，不做过度工程化。

录制路径:
  1. 打开 https://mp.csdn.net/mp_blog/creation/editor
  2. 关闭引导蒙层 + 收起"目录"侧边栏
  3. 填标题: get_by_placeholder("请输入文章标题（5～100个字）")
  4. 填正文: #cke_1_contents iframe -> body (CKEditor)
  5. 添加标签: get_by_role("button", name="添加文章标签")
     -> 输入关键词蒸馏得到的 2~3 个关键词，逐个 Enter
  6. 发布: get_by_role("button", name="发布博客")
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

from loguru import logger
from playwright.async_api import Page

from .base import BasePublisher, registry
from .note_utils import normalize_tags


class CsdnCodegenPublisher(BasePublisher):
    """CSDN 博客发布器 — codegen 验证版"""

    MAX_TITLE_LENGTH = 100

    # ═══════════════════════════════════════════════════════════
    # 发布主流程
    # ═══════════════════════════════════════════════════════════

    async def publish(
        self,
        page: Page,
        article: Any,
        account: Any,
        declare_ai_content: bool = True,
    ) -> Dict[str, Any]:
        logger.info("[CSDN codegen] 开始发布")

        title = getattr(article, "title", "") or "未命名文章"
        content = getattr(article, "content", "") or ""
        keywords = self._derive_keywords(article, title, content)

        if len(title) > self.MAX_TITLE_LENGTH:
            title = title[: self.MAX_TITLE_LENGTH]

        try:
            # 1. 导航
            await self._navigate(page)

            # 2. 关引导蒙层 + 目录侧边栏
            await self._dismiss_guides(page)

            # 3. 填标题
            await self._fill_title(page, title)

            # 4. 填正文
            await self._fill_content(page, content)

            # 5. 添加标签（关键词蒸馏 2~3 个）
            await self._add_tags(page, keywords)

            # 6. 发布
            await self._click_publish(page)

            # 7. 等待结果
            result = await self._wait_result(page)
            return result

        except Exception as e:
            logger.exception(f"[CSDN codegen] 发布失败: {e}")
            return {
                "success": False,
                "error_msg": str(e),
                "platform_url": page.url,
            }

    async def _navigate(self, page: Page):
        url = self.config.get("publish_url", "https://mp.csdn.net/mp_blog/creation/editor")
        logger.info(f"[CSDN] 导航: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(2)

    async def _dismiss_guides(self, page: Page):
        """关闭引导蒙层、目录侧边栏等干扰元素

        codegen 录制时点击了 #el_mcm-id-9988-82 img（随机ID蒙层）和
        目录侧边栏的收起按钮。这里用通用方式替代随机ID。
        """
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        for sel in [
            'div[class*="guide"] button',
            'div[class*="driver"] button',
            'div[class*="mask"]',
            'div[class*="overlay"]',
            'button:has-text("跳过")',
            'button:has-text("我知道了")',
            'button:has-text("知道了")',
            'button:has-text("下一步")',
            'button:has-text("完成")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=1500):
                    await el.click(force=True)
                    logger.info(f"[CSDN] 已关闭引导: {sel}")
                    await asyncio.sleep(0.5)
                    break
            except Exception:
                continue

        try:
            await page.mouse.click(500, 300)
            await asyncio.sleep(0.3)
        except Exception:
            pass

        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass

        try:
            collapse_btn = page.locator('p:has-text("目录")').get_by_role("button").first
            if await collapse_btn.count() > 0 and await collapse_btn.is_visible(timeout=2000):
                await collapse_btn.click()
                logger.info("[CSDN] 已收起目录侧边栏")
                await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _fill_title(self, page: Page, title: str):
        """填写标题 — codegen 录制确认 placeholder='请输入文章标题（5～100个字）'"""
        logger.info(f"[CSDN] 填写标题: {title[:30]}...")

        for placeholder in [
            "请输入文章标题（5～100个字）",
            "输入文章标题",
            "请输入文章标题",
        ]:
            try:
                inp = page.get_by_placeholder(placeholder)
                if await inp.count() > 0 and await inp.is_visible(timeout=2000):
                    await inp.click()
                    await inp.fill("")
                    await inp.fill(title)
                    logger.info(f"[CSDN] 标题已填写: {title}")
                    return
            except Exception as e:
                logger.debug(f"[CSDN] placeholder '{placeholder}' 失败: {e}")

        for sel in [
            'input[placeholder*="文章标题"]',
            'textarea[placeholder*="文章标题"]',
            'input[placeholder*="标题"]',
            'input[name*="title"]',
            "#article-title",
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0 and await inp.is_visible(timeout=2000):
                    await inp.fill("")
                    await inp.fill(title)
                    logger.info(f"[CSDN] 标题已填写 (CSS): {title}")
                    return
            except Exception:
                continue

        logger.warning("[CSDN] 所有标题填写方法均失败")

    async def _fill_content(self, page: Page, content: str):
        """填写正文 — codegen 录制确认 #cke_1_contents iframe -> body (CKEditor)

        注意: codegen 录制的是 .content_frame.locator("body").fill(...)，
        但 fill() 对 contenteditable 无效，所以改用 evaluate 设 innerHTML。
        """
        if not content.strip():
            logger.warning("[CSDN] 正文为空")
            return

        plain = self.markdown_to_plain_text(content, drop_first_h1=True)
        logger.info(f"[CSDN] 填写正文: {len(plain)} 字符")

        iframe_selectors = [
            "#cke_1_contents iframe",
            "#cke_2_contents iframe",
            "#cke_0_contents iframe",
            'div[id*="cke_"] iframe',
        ]

        for sel in iframe_selectors:
            try:
                body = page.frame_locator(sel).locator("body")
                if await body.count() > 0:
                    await body.click()
                    await body.evaluate(
                        "(el, t) => { el.innerHTML = t.replace(/\\n/g, '<br>'); }",
                        plain,
                    )
                    await body.press("Enter")
                    await body.press("Backspace")
                    logger.info(f"[CSDN] 正文已填写 (CKEditor: {sel})")
                    await asyncio.sleep(1)
                    return
            except Exception as e:
                logger.debug(f"[CSDN] iframe {sel} 失败: {e}")
                continue

        for sel in [
            ".ql-editor",
            ".ProseMirror",
            '[contenteditable="true"]',
            'textarea[name*="content"]',
        ]:
            try:
                editor = page.locator(sel).first
                if await editor.count() > 0 and await editor.is_visible(timeout=2000):
                    await editor.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await page.keyboard.insert_text(plain)
                    logger.info(f"[CSDN] 正文已填写 (fallback: {sel})")
                    return
            except Exception:
                continue

        logger.warning("[CSDN] 所有正文填写方法均失败")

    def _derive_keywords(self, article: Any, title: str, content: str) -> List[str]:
        """从文章关键词蒸馏 2~3 个标签

        优先级:
          1. article.tags / article.keywords（文章自身的关键词字段）
          2. 从标题 + 正文蒸馏短词
        """
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
            "这个",
            "什么",
            "怎么",
            "如何",
            "使用",
            "相关",
            "推荐",
            "一些",
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

    async def _add_tags(self, page: Page, keywords: List[str]):
        """添加标签 — codegen 录制确认按钮和输入框 placeholder"""
        keywords = [kw for kw in keywords if kw][:3]
        if not keywords:
            logger.warning("[CSDN] 关键词蒸馏结果为空，跳过标签")
            return

        logger.info(f"[CSDN] 添加标签（关键词蒸馏）: {keywords}")

        try:
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

            tag_input = page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签")
            if await tag_input.count() == 0:
                tag_input = page.locator(
                    'input[placeholder*="搜索"], input[placeholder*="标签"], input[placeholder*="Enter"]'
                ).first
            if await tag_input.count() == 0:
                logger.warning("[CSDN] 未找到标签输入框")
                return

            for kw in keywords:
                await tag_input.click()
                await tag_input.fill("")
                await tag_input.fill(kw)
                await asyncio.sleep(0.3)
                await tag_input.press("Enter")
                await asyncio.sleep(0.5)

            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            logger.info(f"[CSDN] 标签已添加: {keywords}")

        except Exception as e:
            logger.warning(f"[CSDN] 添加标签失败: {e}")

    async def _click_publish(self, page: Page):
        """点击发布按钮 — codegen 录制确认 get_by_role('button', name='发布博客')"""
        logger.info("[CSDN] 点击发布按钮")

        try:
            await page.keyboard.press("Escape")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

        for btn_name in ["发布博客", "发布文章", "立即发布"]:
            try:
                btn = page.get_by_role("button", name=btn_name).last
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click(force=True)
                    logger.info(f"[CSDN] 已点击: {btn_name}")
                    await asyncio.sleep(2)
                    return
            except Exception as e:
                logger.debug(f"[CSDN] 按钮 '{btn_name}' 失败: {e}")

        for sel in [
            'button:has-text("发布博客")',
            'button:has-text("发布文章")',
            'button:has-text("发布")',
            ".publish-btn",
            ".btn-publish",
        ]:
            try:
                btn = page.locator(sel).last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    logger.info(f"[CSDN] 已点击发布 (CSS: {sel})")
                    await asyncio.sleep(2)
                    return
            except Exception:
                continue

        logger.warning("[CSDN] 所有发布按钮点击方法均失败")

    async def _wait_result(self, page: Page) -> Dict[str, Any]:
        """等待发布成功"""
        for i in range(30):
            current_url = page.url
            try:
                for sel in ["text=发布成功", "text=已发布", "text=保存成功"]:
                    elem = page.locator(sel).first
                    if await elem.count() > 0 and await elem.is_visible(timeout=500):
                        logger.success(f"[CSDN] 发布成功: {current_url}")
                        return {"success": True, "platform_url": current_url}
            except Exception:
                pass
            await asyncio.sleep(1)

        logger.error(f"[CSDN] 发布超时: {current_url}")
        return {"success": False, "error_msg": f"发布超时: {current_url}"}


CSDN_CODEGEN_CONFIG = {
    "id": "csdn_codegen",
    "name": "CSDN(Codegen)",
    "publish_url": "https://mp.csdn.net/mp_blog/creation/editor",
    "color": "#FC5531",
    "version": "v1.1-codegen",
}
registry.register("csdn_codegen", CsdnCodegenPublisher("csdn_codegen", CSDN_CODEGEN_CONFIG))
