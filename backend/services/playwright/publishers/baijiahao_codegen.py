# -*- coding: utf-8 -*-
"""
百家号发布适配器 v3.3 — codegen 验证版

完全按照 Playwright codegen 录制的操作路径实现，不做过度工程化。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from loguru import logger
from playwright.async_api import Page

from .base import BasePublisher, registry


class BaijiahaoCodegenPublisher(BasePublisher):
    """百家号图文发布器 — codegen 验证版"""

    MAX_TITLE_LENGTH = 64

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
        logger.info("🚀 [百家号 v3.3 codegen] 开始发布")

        title = self._clean_title(getattr(article, "title", "") or "未命名文章")
        content = getattr(article, "content", "") or ""
        keywords = self._get_keywords(article)

        try:
            # 1-2. 导航 + 快速关引导
            await self._navigate(page)
            await self._dismiss_all_guides(page)

            # 3-4. 填标题 + 正文
            await self._fill_title_codegen(page, title)
            await self._fill_content_codegen(page, content)

            # 5. 图库搜图做封面
            await self._insert_cover_from_library(page, keywords)

            # 6-7. 发布 + 确认
            await self._dismiss_all_guides(page)
            await self._click_publish_codegen(page)
            await self._confirm_publish(page)

            logger.success("✅ [百家号 v3.3] 发布流程完成")
            return {
                "success": True,
                "platform_url": page.url,
                "message": "发布成功",
            }

        except Exception as e:
            logger.exception(f"❌ [百家号 v3.3] 发布失败: {e}")
            return {
                "success": False,
                "error_msg": str(e),
                "platform_url": page.url,
            }

    # ═══════════════════════════════════════════════════════════
    # 导航
    # ═══════════════════════════════════════════════════════════

    async def _navigate(self, page: Page):
        url = "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1"
        logger.info(f"[百家号] 导航: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 引导弹窗
    # ═══════════════════════════════════════════════════════════

    async def _dismiss_all_guides(self, page: Page):
        """关闭所有引导弹窗、AI 助手、提示框

        按用户 codegen 顺序：立即创作 → 下一步×3 → 我知道了 → 完成
        每步都尝试按 Esc + 找按钮关闭。
        """
        close_texts = [
            # codegen 验证过的顺序
            "立即创作",
            "下一步",
            "我知道了",
            "完成",
            # 其他可能出现的
            "知道了",
            "关闭",
            "跳过",
            "不用了",
            "确定",
            "稍后再说",
            "开始体验",
        ]

        for round_i in range(6):  # 最多6轮（从10轮减少）
            closed_any = False

            # 1. Esc 关闭浮层
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.15)
            except Exception:
                pass

            # 2. 查找并点击关闭按钮
            for text in close_texts:
                try:
                    btn = page.get_by_role("button", name=text).first
                    count = await btn.count()
                    if count > 0:
                        try:
                            is_visible = await btn.is_visible(timeout=300)
                        except Exception:
                            is_visible = False
                        if is_visible:
                            await btn.click(force=True)
                            logger.info(f"[百家号] 已点击: {text}")
                            closed_any = True
                            await asyncio.sleep(0.3)
                            break
                except Exception:
                    continue

            # 3. 文字兜底
            if not closed_any:
                for text in ["我知道了", "完成", "下一步", "知道了"]:
                    try:
                        el = page.get_by_text(text, exact=True).first
                        if await el.count() > 0 and await el.is_visible(timeout=300):
                            await el.click(force=True)
                            logger.info(f"[百家号] 文字点击: {text}")
                            closed_any = True
                            await asyncio.sleep(0.3)
                            break
                    except Exception:
                        continue

            if not closed_any:
                break

    # ═══════════════════════════════════════════════════════════
    # 标题填写（codegen 验证）
    # ═══════════════════════════════════════════════════════════

    async def _fill_title_codegen(self, page: Page, title: str):
        """完全按照 codegen 录制的方式填写标题"""
        logger.info(f"[百家号] 填写标题: {title[:30]}...")

        # 方法1: get_by_test_id (codegen 首选)
        try:
            title_el = page.get_by_test_id("news-title-input")
            if await title_el.count() > 0 and await title_el.is_visible(timeout=2000):
                await title_el.get_by_role("paragraph").first.click(force=True)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await title_el.locator("div").nth(1).fill(title)
                logger.info(f"✅ [百家号] 标题已填写 (testId): {title}")
                return
        except Exception as e:
            logger.debug(f"[百家号] testId 标题填写失败: {e}")

        # 方法2: contenteditable div
        try:
            editor = page.locator('[data-lexical-editor="true"]').first
            if await editor.count() > 0 and await editor.is_visible(timeout=2000):
                await editor.click(force=True)
                await asyncio.sleep(0.3)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.1)
                await page.keyboard.insert_text(title)
                await asyncio.sleep(0.3)
                logger.info(f"✅ [百家号] 标题已填写 (Lexical): {title}")
                return
        except Exception as e:
            logger.debug(f"[百家号] Lexical 标题填写失败: {e}")

        # 方法3: 通用 input/textarea
        await self._fill_title_fallback(page, title)

    async def _fill_title_fallback(self, page: Page, title: str):
        """标题兜底方案"""
        selectors = [
            'textarea[placeholder*="标题"]',
            'input[placeholder*="标题"]',
            '[contenteditable="true"]',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    await el.click(force=True)
                    await asyncio.sleep(0.3)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await el.fill(title)
                    logger.info(f"✅ [百家号] 标题已填写 (fallback): {title}")
                    return
            except Exception:
                continue
        logger.warning("⚠️ [百家号] 所有标题填写方法均失败")

    # ═══════════════════════════════════════════════════════════
    # 正文填写
    # ═══════════════════════════════════════════════════════════

    async def _fill_content_codegen(self, page: Page, content: str):
        """填写正文 — 一次性粘贴，不用逐段输入"""
        if not content.strip():
            logger.warning("[百家号] 正文为空")
            return

        clean = self._strip_markdown(content)[:10000]
        logger.info(f"[百家号] 填写正文: {len(clean)} 字符")

        # 点击正文编辑器
        for sel in ['[data-testid="content-editor"]', '[class*="FeEditorApp"]']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    await el.click(force=True)
                    break
            except Exception:
                continue
        else:
            try:
                await page.mouse.click(400, 300)
            except Exception:
                pass

        # 一次性粘贴（比逐段输入快10倍）
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.insert_text(clean)

        logger.info("✅ [百家号] 正文已填写")

    # ═══════════════════════════════════════════════════════════
    # 封面图 — 免费正版图库搜图 (codegen 验证)
    # ═══════════════════════════════════════════════════════════

    def _get_keywords(self, article: Any) -> List[str]:
        """提取文章关键词"""
        keywords = []
        kw = getattr(article, "keyword", None)
        if kw and hasattr(kw, "keyword"):
            keywords.append(str(kw.keyword).strip())

        title = getattr(article, "title", "") or ""
        cn = re.findall(r"[\u4e00-\u9fff]{2,8}", title)
        stop = {"可以", "这个", "什么", "怎么", "如何", "使用", "相关", "推荐", "一个", "一些"}
        for w in cn:
            if w not in stop and w not in keywords:
                keywords.append(w)
                if len(keywords) >= 3:
                    break

        if not keywords:
            keywords = ["科技", "人工智能"]
        logger.info(f"[百家号] 搜图关键词: {keywords[:3]}")
        return keywords[:3]

    async def _insert_cover_from_library(self, page: Page, keywords: List[str]):
        """从免费正版图库搜图并插入正文（第一张自动成为封面）"""
        logger.info(f"[百家号] 开始从免费正版图库搜图: {keywords}")

        # 0. 关键：先确保光标在正文编辑器，否则图片不知道插到哪
        await self._focus_content_editor(page)
        await asyncio.sleep(0.5)

        # 1. 切换到免费正版图库
        try:
            tab = page.get_by_role("tab", name="免费正版图库")
            if await tab.count() > 0 and await tab.is_visible(timeout=3000):
                await tab.click(force=True)
                logger.info("[百家号] 已切换到免费正版图库")
                await asyncio.sleep(1)
            else:
                logger.warning("[百家号] 未找到免费正版图库标签，跳过搜图")
                return
        except Exception as e:
            logger.warning(f"[百家号] 切换图库失败: {e}")
            return

        # 2. 搜索 + 选图
        inserted = 0
        for kw in keywords[:2]:
            if inserted >= 1:  # 先确保至少插入1张
                break
            try:
                # 搜索框
                search = page.get_by_placeholder("请输入关键词，查找相关图片素材")
                if not (await search.count() > 0 and await search.is_visible(timeout=2000)):
                    search = page.locator('input[placeholder*="关键词"]').first
                if not (await search.count() > 0):
                    search = page.locator('input[placeholder*="素材"]').first
                if await search.count() > 0:
                    await search.click(force=True)
                    await search.fill(kw)
                    await search.press("Enter")
                    logger.info(f"[百家号] 搜索图库: {kw}")
                    await asyncio.sleep(1.5)
                else:
                    continue

                # 选择第1张
                for img_sel in [
                    "div:nth-child(1) > .image-wrapper-checkbox",
                    "div:nth-child(1) [class*='checkbox']",
                    ".image-wrapper-checkbox",
                ]:
                    try:
                        img = page.locator(img_sel).first
                        if await img.count() > 0 and await img.is_visible(timeout=3000):
                            await img.click(force=True)
                            inserted += 1
                            logger.info(f"[百家号] 已选图 for '{kw}'")
                            await asyncio.sleep(0.3)
                            break
                    except Exception:
                        continue

                if inserted == 0:
                    continue

                # 确认插入（宽松匹配，不依赖具体数字）
                for cf_sel in [
                    'button:has-text("确定")',
                    'button:has-text("确认")',
                    'button[class*="primary"]:has-text("确定")',
                ]:
                    try:
                        cf_btn = page.locator(cf_sel).last
                        if await cf_btn.count() > 0 and await cf_btn.is_visible(timeout=2000):
                            await cf_btn.click(force=True)
                            logger.info(f"[百家号] 已确认插入 {inserted} 张图")
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        continue

            except Exception as e:
                logger.warning(f"[百家号] 关键词 '{kw}' 搜图失败: {e}")
                continue

        if inserted == 0:
            logger.warning("[百家号] 图库搜图未插入任何图片，文章将无配图")
        else:
            logger.info(f"[百家号] 图库搜图完成，共插入 {inserted} 张")

    async def _focus_content_editor(self, page: Page):
        """确保光标在正文编辑器中"""
        for sel in [
            '[data-testid="content-editor"]',
            '[class*="FeEditorApp"]',
            "iframe#ueditor_0",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click(force=True)
                    await asyncio.sleep(0.3)
                    return
            except Exception:
                continue
        # 兜底：点击页面中间区域
        try:
            await page.mouse.click(500, 400)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 发布
    # ═══════════════════════════════════════════════════════════

    async def _click_publish_codegen(self, page: Page):
        """点击发布按钮"""
        logger.info("[百家号] 点击发布按钮")

        # 方法1: testId
        try:
            btn = page.get_by_test_id("publish-btn")
            if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                await btn.click(force=True)
                logger.info("[百家号] 已点击发布 (testId)")
                return
        except Exception:
            pass

        # 方法2: 通用按钮
        for sel in [
            'button:has-text("发布")',
            'button[class*="publish"]',
            '[class*="publish-btn"]',
        ]:
            try:
                btn = page.locator(sel).last
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click(force=True)
                    logger.info(f"[百家号] 已点击发布: {sel}")
                    return
            except Exception:
                continue

        logger.warning("[百家号] 未找到发布按钮")

    async def _confirm_publish(self, page: Page):
        """确认发布弹窗"""
        confirm_texts = ["保持图文发布", "确认发布", "确定发布", "继续发布", "确认"]

        for text in confirm_texts:
            try:
                btn = page.get_by_role("button", name=text)
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await btn.click(force=True)
                    logger.info(f"[百家号] 已确认发布: {text}")
                    return
            except Exception:
                continue

        # 文字匹配
        for text in confirm_texts:
            try:
                el = page.get_by_text(text, exact=False).first
                if await el.count() > 0 and await el.is_visible(timeout=1000):
                    await el.click(force=True)
                    logger.info(f"[百家号] 文字确认: {text}")
                    return
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════════════════════════

    def _clean_title(self, title: str) -> str:
        return re.sub(r"[#*`\"<>]", "", title or "").strip()[: self.MAX_TITLE_LENGTH]

    def _strip_markdown(self, text: str) -> str:
        """简单去掉 markdown 标记"""
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"`(.+?)`", r"\1", text)
        text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
        return text


# ═══════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════

BAIJIAHAO_CODEGEN_CONFIG = {
    "id": "baijiahao_codegen",
    "name": "百家号(Codegen)",
    "code": "BJH2",
    "login_url": "https://baijiahao.baidu.com/builder/theme/bjh/login",
    "home_url": "https://baijiahao.baidu.com/builder/rc/home",
    "publish_url": "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1",
    "color": "#E53935",
}

registry.register("baijiahao_codegen", BaijiahaoCodegenPublisher("baijiahao_codegen", BAIJIAHAO_CODEGEN_CONFIG))
