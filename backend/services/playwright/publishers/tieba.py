# -*- coding: utf-8 -*-
"""
百度贴吧 (tieba.baidu.com) 发布适配器 - v1.0

图文主题帖发布。架构对齐 toutiao.py v1.0（防闪退版）：
  1. 导航到贴吧首页（带重试 + 百度 passport 登录/安全验证检测）
  2. 登录态检测（登录态由外层 storage_state 注入 BDUSS/STOKEN，这里只检测不登录）
  3. 点"发贴"进入发帖面板 → 等编辑器就绪
  4. 【贴吧独有】选择吧：吧名来自账号绑定时配置（Account.tags "吧:xxx" / target_forum）
     —— 未配置目标吧则直接失败并提示，不静默、不瞎发
  5. 标题：#tb-editor-title（contenteditable div）多级兜底 + JS 兜底
  6. 正文：#tb-editor-content（contenteditable div）文字 + 尽力插图（图文帖）
  7. 发布：点"发布" → 处理二次确认
  8. 严格结果验证：先查失败、再查成功/URL 跳转，超时按失败处理（不虚报成功）
  9. 失败/人工介入落 debug 快照到 backend/debug/tieba/

执行链路：外层（auto_publish / local_client_publish_runner）用 storage_state 创建已登录
context 后调 publisher.publish(page, article, account, declare_ai_content=True)。

⚠️ 图片上传 DOM 首版为"常见模式 + 工具栏推断"，真机联调后按实际校准
   （见 _insert_content_images / tieba_selectors.IMAGE_*）。图片插不进不阻断整篇发布。
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from playwright.async_api import Page

from . import tieba_selectors as sel
from .base import BasePublisher, registry
from .note_utils import clean_title, materialize_images
from ..humanize import random_delay, short_delay
from ...tieba_forum import default_forum_from_tags, normalize_forum


class TiebaPublisher(BasePublisher):
    """百度贴吧图文主题帖发布器 - v1.0"""

    MAX_TITLE_LENGTH = 27  # 贴吧主题帖标题上限约 27~30 字，保守取 27
    # 贴吧正文硬上限 2000 字（编辑器显示“最多可输入2000字”，超出则发布按钮置灰）。
    # 按业务要求把内容长度拦截在 1900 字，留 100 字余量（防字数统计口径差异）；
    # 超长必须截断，否则发布按钮置灰无法发布。纯文字/图文混排两条路径都走此常量。
    MAX_CONTENT_LENGTH = 1900

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
            logger.info("🚀 [贴吧 v1.0] 开始发布图文主题帖")

            title = getattr(article, "title", "") or "未命名文章"
            content = getattr(article, "content", "") or ""

            # 0. 解析目标吧（吧名来自账号绑定时配置）—— 空则直接失败，别进流程
            stage = "resolve_forum"
            forum = self._resolve_forum(account)
            if not forum:
                return await self._fail(
                    page,
                    stage,
                    "该贴吧账号未配置目标吧，请到账号管理为其设置“目标吧”后再发布",
                )
            logger.info(f"[贴吧] 目标吧: {forum}")

            # 1. 导航到贴吧首页（带重试 + 登录页检测）
            stage = "navigate"
            if not await self._navigate_to_home(page):
                # 拆分模糊判断：确认落到百度登录页 = 确定登出；其余（网络/安全验证/首页迟迟不出现）= 不确定
                if self._is_on_login_page(page):
                    return await self._auth_failure(
                        page, stage, definitive=True,
                        message="无法进入贴吧，已被重定向到百度登录页，登录态已失效，请重新授权",
                    )
                return await self._auth_failure(
                    page, stage, definitive=False,
                    message="无法进入贴吧，疑似网络异常或安全验证，未判定账号失效",
                )

            # 2. 登录态检测
            stage = "login_check"
            if not await self._ensure_logged_in(page):
                return await self._auth_failure(
                    page, stage, definitive=True,
                    message="贴吧登录态失效，请到账号管理重新授权百度贴吧",
                )

            # 2.5 提前准备正文配图（图片下载可能很慢，2026-07-13 实测 loremflickr 3 张耗时 26s）。
            #     ⚠️ 关键时序：必须在打开发帖面板【之前】就把图下好——贴吧发帖面板会因
            #     长时间空闲被自动收起。历史事故：选吧成功后才下图，26s 空档里面板消失，
            #     导致随后填标题失败。照 codegen 的节奏，打开面板后要“选吧→标题→正文”一气呵成。
            stage = "prepare_images"
            content_image_paths, image_temp_files = await self._prepare_content_images(article)
            temp_files.extend(image_temp_files)

            # 3. 点"发贴"进入发帖面板
            stage = "open_post"
            if not await self._open_post_panel(page):
                return await self._fail(page, stage, "未能进入贴吧发帖面板（未找到“发贴”入口或面板未就绪）")

            # 4. 【贴吧独有】选择目标吧
            #    ⚠️ 面板就绪后不再统一“关干扰弹窗”——见 fill_title 处说明（2026-07-13 事故）。
            #       若确有浮层挡住选吧/发布，_close_interference 已带“面板存活”护栏，
            #       只在被挡的那一步按需、安全地调用。
            stage = "select_forum"
            if not await self._select_forum(page, forum):
                return await self._fail(page, stage, f"未能在发帖面板选中目标吧「{forum}」")

            # 5. 填写标题（图已提前备好，此处紧接选吧，无空档）
            #    ⚠️ 面板就绪后不再调 _close_interference：面板是 body 末尾的 modal，
            #       此处再“关弹窗”极易误伤面板自己的关闭按钮（2026-07-13 事故根因）。
            stage = "fill_title"
            if not await self._fill_title(page, title):
                return await self._fail(page, stage, "标题填写失败")

            # 6. 填写正文（文字 + 尽力插图）
            stage = "fill_content"
            if not await self._fill_content(page, content, image_paths=content_image_paths):
                return await self._fail(page, stage, "正文填写失败")

            # 7. 点击发布 → 处理二次确认
            stage = "publish"
            await self._close_interference(page)
            if not await self._click_publish(page):
                return await self._fail(page, stage, "未找到可点击的“发布”按钮")

            # 8. 等待发布结果
            stage = "wait_result"
            return await self._wait_for_publish_result(page)

        except Exception as e:
            logger.exception(f"❌ [贴吧] 发布失败 stage={stage}: {e}")
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
    # 目标吧解析（吧名跟着账号走：Account.tags "吧:xxx" / target_forum）
    # ═══════════════════════════════════════════════════════════

    def _resolve_forum(self, account: Any) -> str:
        """解析该账号的默认目标吧。

        优先级：
          1. 服务端已解析好的干净字段 target_forum / forum / forum_name
             （local_client 路径由 client_publish.py 解析后透传，避免 JSON 丢 tags）
          2. Account.tags 列表里以 "吧:" 前缀编码的项（第一条 = 默认吧）
             （cloud_browser 路径直接拿到 ORM Account，tags 原样可读）
          3. remark 里的 "吧:xxx" 兜底
        统一走 services/tieba_forum 的编码约定。找不到返回空串（上层据此失败并提示）。
        """
        # 1. 干净字段优先
        for attr in ("target_forum", "forum", "forum_name"):
            value = getattr(account, attr, None)
            if isinstance(value, str) and value.strip():
                return normalize_forum(value)

        # 2. tags 列表解析（单一事实源）
        forum = default_forum_from_tags(getattr(account, "tags", None))
        if forum:
            return forum

        # 3. remark 兜底
        forum = default_forum_from_tags(getattr(account, "remark", None))
        if forum:
            return forum

        return ""

    # ═══════════════════════════════════════════════════════════
    # 结果封装 & 调试快照
    # ═══════════════════════════════════════════════════════════

    async def _fail(self, page: Page, stage: str, msg: str) -> Dict[str, Any]:
        logger.error(f"❌ [贴吧] stage={stage} 失败: {msg}")
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
        """保存失败时的 HTML 到 backend/debug/tieba/。

        另存一份 shadow DOM 深度 dump（.editors.json）——因为贴吧发帖 modal 在
        shadow DOM 里，page.content() 抓不到编辑器；这份 dump 递归穿透所有 shadow
        root，列出全部输入型元素的真实标签/属性/占位符，供事后精准校准选择器。
        """
        debug_dir = Path("backend/debug/tieba")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[贴吧] 保存调试 HTML 失败: {}", exc)
        # shadow DOM 深度 dump：所有输入型元素的真实结构
        try:
            editors = await page.evaluate(
                """() => {
                    const out = [];
                    const walk = (root, depth) => {
                        if (!root || !root.querySelectorAll) return;
                        for (const n of root.querySelectorAll('*')) {
                            const tag = n.tagName;
                            const editable = tag === 'INPUT' || tag === 'TEXTAREA'
                                || n.isContentEditable
                                || n.getAttribute('contenteditable') !== null;
                            if (editable) {
                                out.push({
                                    tag,
                                    depth,
                                    id: n.id || '',
                                    cls: (n.className && n.className.toString().slice(0,120)) || '',
                                    placeholder: n.getAttribute('placeholder') || '',
                                    ariaPlaceholder: n.getAttribute('aria-placeholder') || '',
                                    dataPlaceholder: n.getAttribute('data-placeholder') || '',
                                    type: n.getAttribute('type') || '',
                                    contenteditable: n.getAttribute('contenteditable'),
                                    inShadow: depth > 0,
                                });
                            }
                            if (n.shadowRoot) walk(n.shadowRoot, depth + 1);
                        }
                    };
                    walk(document, 0);
                    return out;
                }"""
            )
            import json as _json
            json_path = debug_dir / f"{safe_stage}_{stamp}.editors.json"
            json_path.write_text(_json.dumps(editors, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"[贴吧] 编辑器结构 dump（含 shadow）已存: {json_path}（{len(editors)} 个输入元素）")
        except Exception as exc:
            logger.warning("[贴吧] shadow DOM dump 失败: {}", exc)
        return str(html_path)

    def _looks_like_manual_intervention(self, msg: str) -> bool:
        msg = (msg or "").lower()
        return any(
            key in msg
            for key in ("登录", "登陆", "login", "passport", "验证码", "验证", "滑块", "风控", "安全", "帐号异常")
        )

    # ═══════════════════════════════════════════════════════════
    # 导航 & 登录
    # ═══════════════════════════════════════════════════════════

    async def _navigate_to_home(self, page: Page) -> bool:
        """导航到贴吧首页。返回 True/False 不抛异常，让上层决定。"""
        home_url = self.config.get("login_url", sel.HOME_URL)
        last_error = ""
        for attempt in range(3):
            try:
                logger.info(f"[贴吧] 导航到首页 (尝试 {attempt + 1}/3): {home_url}")
                await page.goto(home_url, wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    logger.warning("[贴吧] networkidle 等待超时，继续检测")
                await asyncio.sleep(2)

                if self._is_login_url(page.url):
                    logger.error(f"❌ [贴吧] 被重定向到登录页: {page.url}")
                    return False

                # 首页可交互（出现"发贴"入口或用户信息）即成功
                if await self._home_ready(page):
                    logger.success("✅ [贴吧] 已进入贴吧首页")
                    return True

                await asyncio.sleep(2)
                if await self._home_ready(page):
                    logger.success("✅ [贴吧] 首页在等待后就绪")
                    return True
            except Exception as e:
                last_error = str(e)
                logger.warning(f"⚠️ [贴吧] 导航异常 (尝试 {attempt + 1}/3): {e}")
                await asyncio.sleep(2)

        logger.error(f"❌ [贴吧] 3 次导航均失败。最后错误: {last_error}")
        return False

    def _is_login_url(self, url: str) -> bool:
        url = (url or "").lower()
        return any(indicator in url for indicator in sel.LOGIN_URL_INDICATOR)

    async def _home_ready(self, page: Page) -> bool:
        """首页是否可交互（"发贴"入口存在，或用户信息存在）。"""
        for selector in sel.POST_ENTRY_BTN:
            try:
                node = page.locator(selector).first
                if await node.count() > 0:
                    return True
            except Exception:
                continue
        for selector in sel.LOGIN_SUCCESS_ELEMENT:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def _ensure_logged_in(self, page: Page) -> bool:
        """检测百度登录态。被跳登录 URL 或只见"登录"入口 = 未登录。"""
        if self._is_login_url(page.url):
            return False
        for selector in sel.LOGIN_SUCCESS_ELEMENT:
            try:
                el = page.locator(selector).first
                if await el.count() > 0:
                    return True
            except Exception:
                continue

        # 兜底：页面顶部若仍是"登录"入口且无用户信息，判未登录
        try:
            for text in sel.LOGGED_OUT_TEXT:
                node = page.get_by_text(text, exact=True).first
                if await node.count() > 0 and await node.is_visible(timeout=500):
                    logger.warning(f"⚠️ [贴吧] 检测到未登录入口: {text}")
                    return False
        except Exception:
            pass

        # 找不到明确未登录标识，且能进首页，宽松认为已登录（后续选吧/发布仍会二次校验）
        logger.info("[贴吧] 未见明确未登录标识，继续流程")
        return True

    # ═══════════════════════════════════════════════════════════
    # 进入发帖面板
    # ═══════════════════════════════════════════════════════════

    async def _open_post_panel(self, page: Page) -> bool:
        """点"发贴"进入发帖面板，等编辑器/选择吧就绪。"""
        clicked = False
        for selector in sel.POST_ENTRY_BTN:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await btn.click(force=True)
                    logger.info(f"[贴吧] 已点击发帖入口: {selector}")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # 兜底：get_by_text 精确匹配（codegen 路径）
            try:
                btn = page.get_by_text("发贴", exact=True).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await btn.click(force=True)
                    logger.info("[贴吧] 已点击发帖入口 (get_by_text 发贴)")
                    clicked = True
            except Exception:
                pass

        if not clicked:
            logger.error("❌ [贴吧] 未找到“发贴”入口")
            return False

        await random_delay(1.5, 3.0)
        return await self._wait_post_panel_ready(page)

    async def _wait_post_panel_ready(self, page: Page, max_wait: int = 15) -> bool:
        """等待发帖面板就绪。

        真机 modal 在 shadow DOM，CSS 探不到，故用 _post_panel_present
        （占位符/文字优先，穿透 shadow DOM）判断就绪。
        """
        for _ in range(max_wait):
            if await self._post_panel_present(page):
                return True
            await asyncio.sleep(1)
        logger.warning(f"⚠️ [贴吧] 发帖面板 {max_wait}s 内未就绪")
        return False

    # ═══════════════════════════════════════════════════════════
    # 选择吧（贴吧独有）
    # ═══════════════════════════════════════════════════════════

    async def _select_forum(self, page: Page, forum: str) -> bool:
        """选择目标吧：输入吧名 → 点中下拉候选确认（照 codegen）。

        ⚠️ 真机关键（2026-07-13）：贴吧标题/正文编辑器是在**吧被真正确认选中之后**
        才渲染激活的。必须真正点中下拉里的“吧名”候选（codegen: get_by_text(forum).click()），
        而不是靠 CSS + force-click 假点——假点会让下拉不关、吧未确认、编辑器不出现，
        随后填标题瞬间失败。
        """
        # 1. 定位"选择吧"输入框（codegen: get_by_placeholder("选择吧")）
        forum_input = None
        try:
            ph = page.get_by_placeholder("选择吧").first
            if await ph.count() > 0 and await ph.is_visible(timeout=2000):
                forum_input = ph
        except Exception:
            pass
        if forum_input is None:
            for selector in sel.FORUM_INPUT:
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible(timeout=1500):
                        forum_input = loc
                        break
                except Exception:
                    continue

        if forum_input is None:
            logger.warning("[贴吧] 未找到“选择吧”输入框，可能已在目标吧内，跳过选吧")
            return True

        # 2. 输入吧名
        try:
            await forum_input.click()
            await short_delay()
            try:
                await forum_input.fill("")
            except Exception:
                pass
            try:
                await forum_input.fill(forum)
            except Exception:
                await page.keyboard.type(forum, delay=60)
            logger.info(f"[贴吧] 已输入吧名: {forum}")
        except Exception as e:
            logger.error(f"❌ [贴吧] 吧名输入失败: {e}")
            return False

        # 3. 等下拉候选浮出，点中"吧名"这条确认选择
        await random_delay(1.2, 2.2)
        if await self._click_forum_suggestion(page, forum):
            logger.success(f"✅ [贴吧] 已点选目标吧: {forum}")
            await short_delay()
            return True

        logger.error(f"❌ [贴吧] 下拉候选未点中，吧可能未确认: {forum}")
        return False

    async def _click_forum_suggestion(self, page: Page, forum: str) -> bool:
        """点中下拉里的"吧名"候选以确认选择。

        照 codegen 用 get_by_text 正常点击（自动等待可交互，会触发选中 handler）；
        force-click / CSS 假点是历史事故根因，仅作最后兜底。
        """
        # A. codegen 主路径：get_by_text(forum) 正常点击（先非精确=codegen 原样，再精确）
        for getter in (
            lambda: page.get_by_text(forum),
            lambda: page.get_by_text(forum, exact=True),
        ):
            try:
                item = getter().first
                if await item.count() > 0 and await item.is_visible(timeout=2500):
                    await item.click(timeout=4000)  # 正常点击：自动等待、滚动到视区、真实触发
                    return True
            except Exception:
                continue
        # B. 键盘兜底：自动完成输入框常可 ArrowDown 选中第一条 + Enter 确认
        try:
            await page.keyboard.press("ArrowDown")
            await short_delay()
            await page.keyboard.press("Enter")
            await short_delay()
            return True
        except Exception:
            pass
        # C. CSS 候选容器兜底（最后手段，可能假成功）
        return await self._pick_forum_suggestion(page, forum)

    async def _pick_forum_suggestion(self, page: Page, forum: str) -> bool:
        """从下拉候选容器里选中：优先文本精确等于吧名/吧名+吧的项，否则第一项。"""
        for container_sel in sel.FORUM_SUGGEST_ITEM:
            try:
                items = page.locator(container_sel)
                count = await items.count()
                if count == 0:
                    continue
                # 优先精确匹配
                for i in range(min(count, 12)):
                    item = items.nth(i)
                    try:
                        if not await item.is_visible(timeout=300):
                            continue
                        text = (await item.inner_text()).strip()
                    except Exception:
                        continue
                    if text in (forum, f"{forum}吧") or text.startswith(forum):
                        await item.click(force=True)
                        return True
                # 无精确匹配 → 首个可见项
                for i in range(min(count, 12)):
                    item = items.nth(i)
                    try:
                        if await item.is_visible(timeout=300):
                            await item.click(force=True)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    # ═══════════════════════════════════════════════════════════
    # 干扰弹窗
    # ═══════════════════════════════════════════════════════════

    async def _post_panel_present(self, page: Page) -> bool:
        """发帖面板是否仍在页面上（标题编辑器 或 选择吧输入框 存在）。

        用于 _close_interference 的护栏：关“干扰弹窗”前后各探一次，
        一旦点击后面板消失，说明点到了面板自己的关闭按钮，需回退/告警。

        真机 modal 在 shadow DOM 里，CSS 选择器探不到，故**优先用占位符文字**
        （get_by_placeholder / get_by_text 穿透 shadow DOM）。
        """
        # 占位符优先（真机可靠）
        for ph in (sel.TITLE_PLACEHOLDER_TEXTS + sel.CONTENT_PLACEHOLDER_TEXTS):
            try:
                if await page.get_by_placeholder(ph, exact=False).count() > 0:
                    return True
            except Exception:
                continue
        # “发布到吧/选择吧”这类 modal 文字兜底
        for text in ("发布到吧", "选择吧", "全场景可见"):
            try:
                if await page.get_by_text(text, exact=False).count() > 0:
                    return True
            except Exception:
                continue
        # CSS 选择器兜底（其他版本/非 shadow 场景）
        try:
            if await page.locator(sel.TITLE_EDITOR).count() > 0:
                return True
        except Exception:
            pass
        for selector in sel.FORUM_INPUT:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        for selector in sel.CONTENT_INPUT:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        return False

    async def _close_interference(self, page: Page) -> None:
        """关闭活动浮层 / 客户端引导 / 登录引导等。

        安全护栏（2026-07-13 事故后加）：只点“文字明确=消除提示”的按钮，
        且点击前后校验发帖面板是否还在——若一点就把面板点没了，说明误伤了
        面板自己的关闭按钮，不再继续点其余候选。发帖面板一旦就绪，
        绝不允许被“关干扰弹窗”这一步搞消失。
        """
        panel_before = await self._post_panel_present(page)
        for btn_selector in sel.INTERFERENCE_CLOSE_BTN:
            try:
                btn = page.locator(btn_selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=400):
                    await btn.click(force=True)
                    await short_delay()
                    # 护栏：面板本来在、点完没了 = 误伤，立即停手并告警
                    if panel_before and not await self._post_panel_present(page):
                        logger.warning(
                            f"⚠️ [贴吧] 关闭“{btn_selector}”后发帖面板消失，判为误点，停止关弹窗"
                        )
                        return
                    logger.info(f"[贴吧] 已关闭干扰弹窗: {btn_selector}")
                    break
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════
    # 图片准备（文章自带优先，默认不生成替代图）
    # ═══════════════════════════════════════════════════════════

    async def _prepare_content_images(self, article: Any) -> tuple[List[str], List[str]]:
        """正文配图：文章自带图片，默认不生成替代图。返回 (image_paths, temp_files)。"""
        try:
            image_paths, temp_files = await materialize_images(article, limit=9)
        except Exception as exc:
            logger.warning(f"[贴吧] 提取自带图片失败: {exc}")
            image_paths, temp_files = [], []
        if not image_paths:
            logger.info("[贴吧] 文章无自带图片，发布纯文字主题帖")
        return image_paths, temp_files

    # ═══════════════════════════════════════════════════════════
    # 标题（#tb-editor-title，contenteditable div）
    # ═══════════════════════════════════════════════════════════

    async def _fill_editor_codegen(
        self, page: Page, editor_id: str, text: str, label: str = ""
    ) -> bool:
        """按 codegen 实录方式填写贴吧富文本编辑器（标题/正文通用）。

        真机结论（2026-07-13）：编辑器 `#tb-editor-title` / `#tb-editor-content` 在
        **open shadow DOM** 里——`page.content()` / `document.querySelector` 都拿不到，
        但 Playwright 的 locator 引擎能穿透 open shadow DOM。codegen 实录的可靠序列：
            page.locator("#tb-editor-title").get_by_role("paragraph").click()   # 聚焦内部 <p>
            page.locator("#tb-editor-title div").fill("...")                    # 向内层 div 填字
        校验也必须用 locator（inner_text），不能用 document.querySelector（穿不透 shadow）。
        """
        editor = page.locator(editor_id).first
        # 等编辑器渲染出来（吧确认后才激活；codegen 靠 .click() 自动等待，这里显式 wait_for）
        try:
            await editor.wait_for(state="visible", timeout=10000)
        except Exception:
            logger.debug(f"[贴吧] {label} 编辑器 {editor_id} 10s 内未出现（吧可能未确认/面板未激活）")
            return False

        # 1) 聚焦：优先点内部 paragraph（codegen 路径），失败退而点编辑器本身
        clicked = False
        try:
            para = editor.get_by_role("paragraph").first
            if await para.count() > 0:
                await para.click(timeout=3000)
                clicked = True
        except Exception:
            pass
        if not clicked:
            try:
                await editor.click(timeout=3000)
                clicked = True
            except Exception as exc:
                logger.debug(f"[贴吧] {label} 聚焦编辑器失败: {exc}")
        if not clicked:
            return False
        await short_delay()

        # 2) 填字：严格照 codegen 只 fill `#tb-editor-title div`（.first）。
        #    ⚠️ 不要“对多个目标依次 fill”——contenteditable 上多次 fill 可能叠加，
        #    导致标题/正文重复出现两遍（2026-07-14 事故：标题上传两次）。
        #    fill 前先清空一次，成功即返回；失败才走键盘兜底（键盘前也清空）。
        inner_div = page.locator(f"{editor_id} div").first
        target = inner_div if await inner_div.count() > 0 else editor
        try:
            await target.fill("", timeout=2000)  # 先清空，避免叠加
        except Exception:
            pass
        try:
            await target.fill(text, timeout=5000)
            if await self._editor_has_text_locator(editor, text):
                return True
        except Exception as exc:
            logger.debug(f"[贴吧] {label} fill 失败，转键盘兜底: {exc}")

        # 3) 键盘兜底（编辑器已聚焦）：先全选清空，再输入，避免与已填内容叠加
        try:
            await target.click(timeout=2000)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.insert_text(text)
            if await self._editor_has_text_locator(editor, text):
                return True
        except Exception:
            pass
        return False

    async def _editor_has_text_locator(self, editor, text: str) -> bool:
        """用 locator.inner_text 校验编辑器是否已含目标文本（穿透 shadow DOM）。"""
        if not text:
            return True
        needle = text[:20]
        try:
            inner = await editor.inner_text(timeout=1000)
            return bool(inner and needle in inner)
        except Exception:
            return True  # 校验异常不阻断（宁可放行也别误杀成功写入）

    async def _fill_title(self, page: Page, title: str) -> bool:
        clean = clean_title(title, self.MAX_TITLE_LENGTH)
        if not clean:
            logger.error("❌ [贴吧] 标题为空")
            return False
        # 1. 首选：codegen 实录方式（#tb-editor-title 在 open shadow DOM，Playwright locator 能穿透）
        if await self._fill_editor_codegen(page, sel.TITLE_EDITOR, clean, label="标题"):
            logger.info(f"✅ [贴吧] 标题已填写: {clean}")
            return True
        # 2. 占位符文字定位兜底
        if await self._type_by_placeholder(page, sel.TITLE_PLACEHOLDER_TEXTS, clean, label="标题"):
            logger.info(f"✅ [贴吧] 标题已填写(占位符): {clean}")
            return True
        # 3. CSS 选择器兜底
        if await self._type_into_editable(page, sel.TITLE_INPUT, clean, label="标题"):
            logger.info(f"✅ [贴吧] 标题已填写(CSS): {clean}")
            return True
        # 4. Shadow DOM 深度穿透兜底
        if await self._deep_set_by_placeholder(page, sel.TITLE_PLACEHOLDER_TEXTS, clean):
            logger.info(f"✅ [贴吧] 标题已填写 (shadow 穿透): {clean}")
            return True
        # 5. JS 容器兜底
        if await self._js_set_editable(page, sel.TITLE_EDITOR, clean):
            logger.info(f"✅ [贴吧] 标题已填写 (JS 兜底): {clean}")
            return True
        return False

    # ═══════════════════════════════════════════════════════════
    # 正文（#tb-editor-content，contenteditable div）
    # ═══════════════════════════════════════════════════════════

    async def _fill_content(
        self, page: Page, content: str, image_paths: Optional[List[str]] = None
    ) -> bool:
        clean = self._deep_clean_content(content or "")
        original_len = len(clean)
        if original_len > self.MAX_CONTENT_LENGTH:
            clean = self._truncate_content(clean, self.MAX_CONTENT_LENGTH)
            logger.warning(
                f"[贴吧] 正文 {original_len} 字超出上限 {self.MAX_CONTENT_LENGTH}，"
                f"已截断为 {len(clean)} 字（贴吧硬上限 2000 字，按业务要求拦截在 1900）"
            )
        if not clean.strip():
            logger.error("❌ [贴吧] 正文为空")
            return False

        valid_images = [p for p in (image_paths or []) if p and os.path.exists(p)]

        # 0. 优先：原文带图片标记时，严格按原文位置图文混排（几段文字→图→几段文字），
        #    发布器不再自行均匀分布图片位置；原文无标记时走下方均匀分布 / 末尾插图兜底。
        blocks = self.build_content_blocks_by_markers(content or "", valid_images, max_chars=self.MAX_CONTENT_LENGTH)
        if blocks is not None:
            inserted = await self._fill_content_blocks(page, blocks)
            if inserted is not None:
                logger.info(
                    f"✅ [贴吧] 正文按原文位置图文混排完成（{len(blocks)} 个文本/图片块，"
                    f"插图 {inserted}/{len(valid_images)} 张）"
                )
                return True
            logger.warning("[贴吧] 原文位置混排未能聚焦编辑器，降级为纯文字 + 末尾插图")

        # 1. 首选：图文混排（逐段 insert_text + 段后按均匀分布插图）——满足"一段文字一张图"。
        #    只有连编辑器都聚焦不了才返回 None，此时降级到纯文字路径（避免半途叠加）。
        if valid_images:
            paragraphs = self._split_paragraphs(clean)
            inserted = await self._fill_content_interleaved(page, paragraphs, valid_images)
            if inserted is not None:
                logger.info(
                    f"✅ [贴吧] 正文图文混排完成（{len(clean)} 字，{len(paragraphs)} 段，"
                    f"插图 {inserted}/{len(valid_images)} 张）"
                )
                return True
            logger.warning("[贴吧] 图文混排未能聚焦编辑器，降级为纯文字 + 末尾插图")

        # 2. 降级：纯文字 .fill()（稳妥，已验证）——首选 codegen 实录方式
        ok = await self._fill_editor_codegen(page, sel.CONTENT_EDITOR, clean, label="正文")
        if not ok:
            ok = await self._type_by_placeholder(page, sel.CONTENT_PLACEHOLDER_TEXTS, clean, label="正文")
        if not ok:
            ok = await self._type_into_editable(page, sel.CONTENT_INPUT, clean, label="正文")
        if not ok:
            ok = await self._deep_set_by_placeholder(page, sel.CONTENT_PLACEHOLDER_TEXTS, clean)
        if not ok:
            ok = await self._js_set_editable(page, sel.CONTENT_EDITOR, clean)
        if not ok:
            logger.error("❌ [贴吧] 正文文字填写失败")
            return False
        logger.info(f"✅ [贴吧] 正文文字已填写 ({len(clean)} 字符)")

        # 3. 纯文字路径下的插图：末尾追加（降级形态，失败不阻断）
        if valid_images:
            inserted = await self._insert_content_images(page, valid_images)
            logger.info(f"[贴吧] 正文配图插入 {inserted}/{len(valid_images)} 张（末尾）")
        return True

    # ═══════════════════════════════════════════════════════════
    # 图文混排（逐段填字 + 段后按分布插图）—— 满足"一段文字一张图"
    # ═══════════════════════════════════════════════════════════

    def _split_paragraphs(self, text: str) -> List[str]:
        """把已清洗正文切成段落列表。清洗后段落以空行分隔，无空行则退回按行切。"""
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not parts:
            parts = [ln.strip() for ln in text.split("\n") if ln.strip()]
        return parts or ([text.strip()] if text.strip() else [])

    def _distribute_image_positions(self, num_paragraphs: int, num_images: int) -> Dict[int, int]:
        """返回 {段落索引: 该段之后插入的图片数}，把 num_images 张图尽量均匀铺到各段之后。

        例：6 段 3 图 → {1:1, 3:1, 4:1}；3 段 3 图 → {0:1,1:1,2:1}（一段一图）；
        图多于段时后段可承接多张。始终恰好安排 num_images 张（除非上层预算提前中止）。
        """
        plan: Dict[int, int] = {}
        if num_images <= 0 or num_paragraphs <= 0:
            return plan
        for k in range(num_images):
            idx = int((k + 1) * num_paragraphs / (num_images + 1))
            idx = max(0, min(num_paragraphs - 1, idx))
            plan[idx] = plan.get(idx, 0) + 1
        return plan

    async def _fill_content_blocks(
        self, page: Page, blocks: List[Dict[str, str]]
    ) -> Optional[int]:
        """按原文图片标记位置逐块写入：文本块逐段 insert_text，图片块在光标处插入。

        文本块内部段落间只留 1 个换行；每插一张图后 Ctrl+End 把光标移回正文末尾，
        保证后续文字/图片接在图后面。返回插图张数；连编辑器都聚焦不了、或写完
        校验不到文字时返回 None（上层降级到纯文字 + 末尾插图）。
        """
        editor = page.locator(sel.CONTENT_EDITOR).first
        try:
            await editor.wait_for(state="visible", timeout=10000)
        except Exception:
            logger.debug("[贴吧] 原文混排：正文编辑器 10s 未出现")
            return None

        # 聚焦 + 清空
        if not await self._focus_editor_end(page, editor):
            logger.debug("[贴吧] 原文混排：无法聚焦正文编辑器")
            return None
        try:
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        except Exception:
            pass

        inserted = 0
        for block in blocks:
            if block["type"] == "text":
                for para in self._split_paragraphs(block["content"]):
                    if para.strip():
                        try:
                            await page.keyboard.insert_text(para)
                        except Exception:
                            try:
                                await page.keyboard.type(para, delay=5)
                            except Exception as exc:
                                logger.debug(f"[贴吧] 原文混排：段落写入失败: {exc}")
                    try:
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
            else:
                if await self._insert_image_at_cursor(page, block["content"]):
                    inserted += 1
                    await self._focus_editor_end(page, editor)  # 光标移回末尾，接着写下一块
                    try:
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                else:
                    logger.warning("[贴吧] 按原文位置插图失败，跳过该图")

        # 校验文字确已写入（穿透 shadow）——没写进去让上层降级重填
        needle = ""
        for block in blocks:
            if block["type"] == "text" and block["content"].strip():
                needle = block["content"].strip()[:20]
                break
        if needle and not await self._editor_has_text_locator(editor, needle):
            logger.debug("[贴吧] 原文混排：写完未校验到文字，回退让上层重填")
            return None
        return inserted

    async def _fill_content_interleaved(
        self, page: Page, paragraphs: List[str], image_paths: List[str]
    ) -> Optional[int]:
        """逐段写文字，按分布在段后插图。返回插图张数；连编辑器都聚焦不了则返回 None（上层降级）。

        真机路径：#tb-editor-content 在 open shadow DOM，locator 可穿透。
        用 keyboard.insert_text 逐段追加（不走 .fill——.fill 会整体替换，无法与图片交错），
        每次插图后 Ctrl+End 把光标移回正文末尾，保证后续文字接在图后面。
        """
        editor = page.locator(sel.CONTENT_EDITOR).first
        try:
            await editor.wait_for(state="visible", timeout=10000)
        except Exception:
            logger.debug("[贴吧] 混排：正文编辑器 10s 未出现")
            return None

        # 聚焦 + 清空
        if not await self._focus_editor_end(page, editor):
            logger.debug("[贴吧] 混排：无法聚焦正文编辑器")
            return None
        try:
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        except Exception:
            pass

        plan = self._distribute_image_positions(len(paragraphs), len(image_paths))
        logger.info(f"[贴吧] 图文混排布局：{len(paragraphs)} 段 / {len(image_paths)} 图 → 插入计划 {plan}")

        img_cursor = 0
        inserted = 0
        budget_s = 45  # 插图总预算，超了停止插图但文字已写完
        loop = asyncio.get_event_loop()
        start = loop.time()

        for i, para_text in enumerate(paragraphs):
            if para_text.strip():
                try:
                    await page.keyboard.insert_text(para_text)
                except Exception:
                    try:
                        await page.keyboard.type(para_text, delay=5)
                    except Exception as exc:
                        logger.debug(f"[贴吧] 混排：第 {i} 段写入失败: {exc}")
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass

            for _ in range(plan.get(i, 0)):
                if img_cursor >= len(image_paths):
                    break
                if loop.time() - start > budget_s:
                    logger.warning(f"[贴吧] 混排插图预算 {budget_s}s 用尽，剩余图跳过（已插 {inserted} 张）")
                    break
                path = image_paths[img_cursor]
                img_cursor += 1
                if await self._insert_image_at_cursor(page, path):
                    inserted += 1
                    await self._focus_editor_end(page, editor)  # 光标移回末尾，接着写下一段
                    try:
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                else:
                    logger.debug(f"[贴吧] 混排：第 {img_cursor} 张图插入失败，跳过")
            else:
                continue
            if loop.time() - start > budget_s:
                break

        # 校验文字确已写入（穿透 shadow）——没写进去让上层降级重填
        needle = ""
        for p in paragraphs:
            if p.strip():
                needle = p.strip()[:20]
                break
        if needle and not await self._editor_has_text_locator(editor, needle):
            logger.debug("[贴吧] 混排：写完未校验到文字，回退让上层重填")
            return None
        return inserted

    async def _focus_editor_end(self, page: Page, editor) -> bool:
        """聚焦正文编辑器并把光标移到末尾（保证后续内容追加在末尾）。"""
        try:
            para = editor.get_by_role("paragraph").last
            if await para.count() > 0:
                await para.click(timeout=2500)
            else:
                await editor.click(timeout=2500)
            await page.keyboard.press("Control+End")
            return True
        except Exception:
            try:
                await editor.click(timeout=2500)
                await page.keyboard.press("Control+End")
                return True
            except Exception:
                return False

    async def _insert_image_at_cursor(self, page: Page, image_path: str) -> bool:
        """在当前光标位置插入一张图片：点工具栏图片按钮→文件选择器（codegen 路径），
        兜底直接注入 input[type=file]。插入后自动关裁剪/封面确认框（普通图通常无框）。"""
        if not image_path or not os.path.exists(image_path):
            return False
        before = await self._content_image_count(page)

        # A. codegen 路径：点工具栏图片按钮 → 弹文件选择器 → 选文件
        for selector in sel.CONTENT_IMAGE_TOOLBAR_BTN:
            try:
                btn = page.locator(selector).first
                if await btn.count() == 0 or not await btn.is_visible(timeout=600):
                    continue
                async with page.expect_file_chooser(timeout=4000) as fc_info:
                    await btn.click()
                chooser = await fc_info.value
                await chooser.set_files(image_path)
                await self._confirm_image_crop(page, max_wait=3)
                if await self._wait_image_uploaded(page, before, timeout=12):
                    logger.debug(f"[贴吧] 已插入配图(工具栏): {os.path.basename(image_path)}")
                    return True
            except Exception:
                continue

        # B. 兜底：直接注入 input[type=file]
        try:
            file_input = page.locator(sel.IMAGE_FILE_INPUT).first
            if await file_input.count() == 0:
                file_input = page.locator(sel.IMAGE_ALL_FILE_INPUT).last
            if await file_input.count() > 0:
                await file_input.set_input_files(image_path)
                await self._confirm_image_crop(page, max_wait=3)
                if await self._wait_image_uploaded(page, before, timeout=12):
                    logger.debug(f"[贴吧] 已插入配图(注入): {os.path.basename(image_path)}")
                    return True
        except Exception as exc:
            logger.debug(f"[贴吧] 注入图片失败: {exc}")
        return False


    async def _type_by_placeholder(
        self, page: Page, placeholder_texts: List[str], text: str, label: str = ""
    ) -> bool:
        """用占位符文字定位输入框并写入（穿透 shadow DOM）。

        真机证据：贴吧发帖 modal 在 Shadow DOM 里，CSS/id 选择器（#tb-editor-*）
        定位不到；但 Playwright 的 get_by_placeholder 走可访问性树，能穿透 open
        shadow DOM。placeholder_texts 用子串匹配（exact=False），抗“(5-31个字)”
        这类括号变化。input / textarea / contenteditable 三种形态都尝试写入并校验。
        """
        for ph in placeholder_texts:
            try:
                loc = page.get_by_placeholder(ph, exact=False).first
                if await loc.count() == 0 or not await loc.is_visible(timeout=1200):
                    continue
                await loc.click(force=True)
                await short_delay()
                # 清空已有内容
                try:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                except Exception:
                    pass
                # 优先 fill（input/textarea 最稳），失败降级键盘输入（contenteditable/IME）
                wrote = False
                try:
                    await loc.fill(text)
                    wrote = True
                except Exception:
                    try:
                        await page.keyboard.insert_text(text)
                        wrote = True
                    except Exception:
                        try:
                            await page.keyboard.type(text, delay=8)
                            wrote = True
                        except Exception:
                            wrote = False
                if not wrote:
                    continue
                # 校验：input.value 或 元素文本里确有内容
                if await self._placeholder_field_has_text(loc, text):
                    return True
                logger.debug(f"[贴吧] {label} 占位符“{ph}”写入后未校验到文本，尝试下一候选")
            except Exception as exc:
                logger.debug(f"[贴吧] {label} 占位符“{ph}”输入失败: {exc}")
                continue
        return False

    async def _deep_set_by_placeholder(
        self, page: Page, placeholder_texts: List[str], text: str
    ) -> bool:
        """Shadow DOM 深度穿透兜底：递归遍历所有 shadow root，按占位符文字
        （placeholder / aria-placeholder / data-placeholder）找到输入框，
        input/textarea 设 value、contenteditable 设文本，并 dispatch 事件。

        对付“modal 在 shadow DOM、CSS/get_by_placeholder 都够不到”的终极手段。
        """
        try:
            ok = await page.evaluate(
                """({needles, text}) => {
                    const getPh = (el) =>
                        (el.getAttribute && (el.getAttribute('placeholder')
                          || el.getAttribute('aria-placeholder')
                          || el.getAttribute('data-placeholder'))) || '';
                    const all = [];
                    const walk = (root) => {
                        if (!root) return;
                        const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                        for (const n of nodes) {
                            all.push(n);
                            if (n.shadowRoot) walk(n.shadowRoot);
                        }
                    };
                    walk(document);
                    const isEditable = (el) =>
                        el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
                        || el.isContentEditable
                        || el.getAttribute('contenteditable') === 'true'
                        || el.getAttribute('contenteditable') === '';
                    let target = null;
                    for (const el of all) {
                        const ph = getPh(el);
                        if (ph && needles.some(nd => ph.includes(nd)) && isEditable(el)) {
                            target = el; break;
                        }
                    }
                    if (!target) {
                        for (const el of all) {
                            const ph = getPh(el);
                            if (ph && needles.some(nd => ph.includes(nd))) {
                                const cand = el.querySelector
                                    ? el.querySelector('input,textarea,[contenteditable]') : null;
                                if (cand) { target = cand; break; }
                            }
                        }
                    }
                    if (!target) return false;
                    target.focus();
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
                        const proto = target.tagName === 'INPUT'
                            ? window.HTMLInputElement.prototype
                            : window.HTMLTextAreaElement.prototype;
                        const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                        setter.call(target, text);
                        target.dispatchEvent(new Event('input', {bubbles: true}));
                        target.dispatchEvent(new Event('change', {bubbles: true}));
                    } else {
                        const paras = text.split(/\\n{1,}/).filter(Boolean);
                        target.innerHTML = paras.map(p =>
                            '<p>' + p.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</p>'
                        ).join('') || '<p><br></p>';
                        target.dispatchEvent(new InputEvent('input',
                            {bubbles: true, inputType: 'insertText', data: text}));
                        target.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    return true;
                }""",
                {"needles": placeholder_texts, "text": text},
            )
            return bool(ok)
        except Exception as exc:
            logger.debug(f"[贴吧] shadow 穿透写入失败: {exc}")
            return False

    async def _placeholder_field_has_text(self, loc, text: str) -> bool:
        """校验通过占位符定位到的字段是否已含目标文本（input.value / textContent 双查）。"""
        if not text:
            return True
        needle = text[:20]
        try:
            val = await loc.input_value(timeout=800)
            if val and needle in val:
                return True
        except Exception:
            pass  # 非 input 元素没有 input_value
        try:
            inner = await loc.inner_text(timeout=800)
            if inner and needle in inner:
                return True
        except Exception:
            pass
        try:
            txt = await loc.text_content(timeout=800)
            if txt and needle in txt:
                return True
        except Exception:
            pass
        return False

    async def _type_into_editable(
        self, page: Page, selectors: List[str], text: str, label: str = ""
    ) -> bool:
        """向 contenteditable div 输入文本：click 聚焦 → 清空 → insert_text（失败降级 type）。"""
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if await loc.count() == 0 or not await loc.is_visible(timeout=1200):
                    continue
                await loc.click(force=True)
                await short_delay()
                # 清空（聚焦编辑器后 Control+A 作用域即编辑器）
                try:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                except Exception:
                    pass
                # 优先 insert_text（对 contenteditable/IME 最稳），长文分段避免卡顿
                try:
                    await page.keyboard.insert_text(text)
                except Exception:
                    await page.keyboard.type(text, delay=8)
                # 校验：编辑器确有文字
                if await self._editable_has_text(page, selector, text):
                    return True
                logger.debug(f"[贴吧] {label} 写入后未校验到文本，尝试下一选择器: {selector}")
            except Exception as exc:
                logger.debug(f"[贴吧] {label} 输入失败 ({selector}): {exc}")
                continue
        return False

    async def _editable_has_text(self, page: Page, selector: str, text: str) -> bool:
        if not text:
            return True
        try:
            found = await page.evaluate(
                """({selector, needle}) => {
                    const el = document.querySelector(selector);
                    if (!el) return false;
                    return (el.innerText || el.textContent || '').includes(needle.slice(0, 30));
                }""",
                {"selector": selector, "needle": text},
            )
            return bool(found)
        except Exception:
            return True  # 校验异常不阻断

    async def _js_set_editable(self, page: Page, container_selector: str, text: str) -> bool:
        """JS 兜底：定位容器内 contenteditable，设 innerText 并 dispatch input 事件。"""
        try:
            ok = await page.evaluate(
                """({container, text}) => {
                    const root = document.querySelector(container);
                    if (!root) return false;
                    let el = root.matches('[contenteditable]') ? root
                        : root.querySelector('[contenteditable="true"], [contenteditable]');
                    if (!el) el = root;
                    el.focus();
                    // contenteditable：用 <p> 分段还原换行
                    const paras = text.split(/\\n{1,}/).filter(Boolean);
                    el.innerHTML = paras.map(p =>
                        '<p>' + p.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</p>'
                    ).join('') || '<p><br></p>';
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }""",
                {"container": container_selector, "text": text},
            )
            return bool(ok)
        except Exception as exc:
            logger.debug(f"[贴吧] JS 兜底写入失败 ({container_selector}): {exc}")
            return False

    # ═══════════════════════════════════════════════════════════
    # 正文配图（⚠️ 真机待校准）
    # ═══════════════════════════════════════════════════════════

    async def _insert_content_images(self, page: Page, image_paths: List[str]) -> int:
        """在正文里插入配图——用【上传按钮/文件注入】方式 + 自动关裁剪确认框。

        真机结论（2026-07-14）：合成 ClipboardEvent('paste') 贴吧编辑器读不到（0/3）；
        而“文件注入到 input[type=file]”实测能传成（曾 1/3），卡点在**上传后弹的裁剪/
        封面确认框**没点确认 → 一直卡。故本版：注入文件 → 自动点掉裁剪框“确定/完成” →
        等正文出现新 img。全程带单张超时 + 总预算，失败不阻断发布（降级纯文字帖）。
        """
        inserted = 0
        image_budget_s = 40  # 插图总预算，超了停止继续发布，避免拖垮 180s 总超时
        loop = asyncio.get_event_loop()
        start = loop.time()
        for path in image_paths:
            if loop.time() - start > image_budget_s:
                logger.warning(f"[贴吧] 插图总预算 {image_budget_s}s 用尽，停止插图，已插 {inserted} 张，继续发布")
                break
            try:
                before = await self._content_image_count(page)
                if await self._upload_one_image(page, path):
                    if await self._wait_image_uploaded(page, before, timeout=12):
                        inserted += 1
                        await random_delay(0.6, 1.2)
                    else:
                        logger.debug(f"[贴吧] 上传后 12s 未见新图，跳过：{os.path.basename(path)}")
            except Exception as exc:
                logger.debug(f"[贴吧] 配图插入异常，跳过: {exc}")
        if inserted == 0 and image_paths:
            # 一张都没成，dump 一份 DOM 便于校准图片上传/裁剪框选择器
            await self._save_debug_snapshot(page, "image_upload_none")
        return inserted

    async def _upload_one_image(self, page: Page, image_path: str) -> bool:
        """上传单张图片：优先文件注入 input[type=file]，兜底点工具栏图片按钮触发 file chooser；
        随后自动关掉裁剪/封面确认框。"""
        if not image_path or not os.path.exists(image_path):
            return False

        uploaded_action = False
        # A. 直接注入 input[type=file]（最稳，不弹系统文件框）
        try:
            file_input = page.locator(sel.IMAGE_FILE_INPUT).first
            if await file_input.count() == 0:
                file_input = page.locator(sel.IMAGE_ALL_FILE_INPUT).last
            if await file_input.count() > 0:
                await file_input.set_input_files(image_path)
                uploaded_action = True
                logger.debug(f"[贴吧] 已注入图片文件: {os.path.basename(image_path)}")
        except Exception as exc:
            logger.debug(f"[贴吧] input 注入图片失败: {exc}")

        # B. 兜底：点工具栏“图片”按钮触发 file chooser
        if not uploaded_action:
            for selector in sel.CONTENT_IMAGE_TOOLBAR_BTN:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() == 0 or not await btn.is_visible(timeout=800):
                        continue
                    async with page.expect_file_chooser(timeout=4000) as fc_info:
                        await btn.click(force=True)
                    chooser = await fc_info.value
                    await chooser.set_files(image_path)
                    uploaded_action = True
                    logger.debug(f"[贴吧] 已通过工具栏上传图片: {os.path.basename(image_path)}")
                    break
                except Exception:
                    continue

        if not uploaded_action:
            return False

        # C. 关掉上传后可能弹出的裁剪/封面确认框（不点确认会一直卡）
        await self._confirm_image_crop(page)
        return True

    async def _confirm_image_crop(self, page: Page, max_wait: int = 8) -> None:
        """自动点掉图片上传后的裁剪/封面确认框的“确定/完成/上传”按钮。"""
        for _ in range(max_wait):
            clicked = False
            for selector in sel.IMAGE_CROP_CONFIRM_BTN:
                try:
                    btn = page.locator(selector).last
                    if await btn.count() > 0 and await btn.is_visible(timeout=300):
                        await btn.click(timeout=2000)
                        logger.info(f"[贴吧] 已确认图片裁剪/上传框: {selector}")
                        clicked = True
                        await short_delay()
                        break
                except Exception:
                    continue
            if clicked:
                return
            await asyncio.sleep(0.5)

    async def _content_image_count(self, page: Page) -> int:
        for selector in sel.IMAGE_SUCCESS_INDICATOR:
            try:
                count = await page.locator(selector).count()
                if count:
                    return count
            except Exception:
                continue
        return 0

    async def _wait_image_uploaded(self, page: Page, before: int, timeout: int = 12) -> bool:
        for _ in range(max(1, timeout * 2)):
            await asyncio.sleep(0.5)
            if await self._content_image_count(page) > before:
                return True
        return False

    # ═══════════════════════════════════════════════════════════
    # 发布
    # ═══════════════════════════════════════════════════════════

    async def _click_publish(self, page: Page) -> bool:
        """点击"发布"，并处理二次确认。"""
        try:
            # 强制启用发布按钮（防灰禁）
            await page.evaluate(
                """() => {
                    document.querySelectorAll('button').forEach(btn => {
                        const t = (btn.innerText || '').trim();
                        if (t === '发布' || t === '发表' || t === '确认发布') {
                            btn.disabled = false;
                            btn.removeAttribute('disabled');
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
                        if not await btn.is_visible(timeout=1000):
                            continue
                        text = (await btn.inner_text()).strip()
                        if any(bad in text for bad in ["定时", "草稿", "预览"]):
                            continue
                        if text not in ["发布", "发表", "确认发布", "立即发布"]:
                            continue
                        await btn.scroll_into_view_if_needed(timeout=3000)
                        await btn.click(force=True)
                        logger.info(f"✅ [贴吧] 已点击发布按钮: {text} ({selector})")
                        await asyncio.sleep(2)
                        await self._handle_publish_confirm(page)
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.error(f"❌ [贴吧] 点击发布失败: {e}")
            return False

    async def _handle_publish_confirm(self, page: Page) -> None:
        """处理发布二次确认 / 协议弹窗（若有）。"""
        for text in sel.PUBLISH_CONFIRM:
            try:
                btn = page.locator(f'button:has-text("{text}")').last
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await btn.click(force=True)
                    await asyncio.sleep(1)
                    logger.info(f"[贴吧] 已确认发布弹窗: {text}")
                    return
            except Exception:
                continue

        # 安全验证（滑块/字符验证码）→ 抛人工介入
        try:
            if await page.locator(sel.CAPTCHA_INDICATOR).count() > 0:
                logger.warning("🚧 [贴吧] 触发安全验证")
                try:
                    await page.wait_for_selector(sel.CAPTCHA_INDICATOR, state="hidden", timeout=60000)
                except Exception as exc:
                    raise RuntimeError("贴吧安全验证未完成，请人工处理后重试发布") from exc
                logger.info("[贴吧] 安全验证已完成，继续发布流程")
        except RuntimeError:
            raise
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    # 等待发布结果
    # ═══════════════════════════════════════════════════════════

    async def _wait_for_publish_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果。严格顺序：先查失败提示，再判成功。

        ⚠️ 主成功信号 = **发帖面板消失**（点发布成功后 modal 关闭，回落首页；
        贴吧从首页发帖成功通常 URL 不变、成功 toast 一闪而过——只认文字/跳转会漏判，
        导致“其实发出去了却报超时失败”，2026-07-14 事故）。面板连续两次探测都不在 = 成功。
        发布失败时面板会留在原地报错，所以“面板消失”不会误判失败为成功。
        """
        last_url = page.url
        gone_streak = 0
        for i in range(45):  # 最长 ~45s；成功通常几秒内面板即关
            manual_msg = await self.detect_manual_intervention(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            # 1. 失败提示优先（面板会留在原地报错）
            for text in sel.PUBLISH_FAIL_INDICATORS:
                try:
                    clean = text.replace("text=", "")
                    node = page.get_by_text(clean, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        msg = (await node.inner_text()).strip()
                        logger.error(f"❌ [贴吧] 检测到失败提示: {msg}")
                        debug_path = await self._save_debug_snapshot(page, "wait_result_fail_text")
                        return {
                            "success": False,
                            "platform_url": page.url,
                            "error_msg": msg,
                            "debug_path": debug_path,
                        }
                except Exception:
                    continue

            # 2. 成功文字提示（若正好抓到）
            for text in sel.SUCCESS_INDICATOR:
                try:
                    clean = text.replace("text=", "")
                    node = page.get_by_text(clean, exact=False).first
                    if await node.count() > 0 and await node.is_visible(timeout=300):
                        logger.success(f"🎉 [贴吧] 检测到成功提示: {clean}")
                        return {"success": True, "platform_url": page.url}
                except Exception:
                    continue

            # 3. 跳转帖子详情 /p/{tid}
            if page.url != last_url and re.search(sel.SUCCESS_URL_PATTERN, page.url, re.IGNORECASE):
                logger.success(f"🎉 [贴吧] 检测到跳转，认为发布成功: {page.url}")
                return {"success": True, "platform_url": page.url}

            # 4. 主信号：发帖面板消失 = 发布成功（连续 2 次确认，避开提交瞬间的抖动）
            #    前几秒给提交留缓冲，从第 2 轮起才判（i>=1）
            if i >= 1 and not await self._post_panel_present(page):
                gone_streak += 1
                if gone_streak >= 2:
                    logger.success("🎉 [贴吧] 发帖面板已关闭，判定发布成功")
                    return {"success": True, "platform_url": page.url}
            else:
                gone_streak = 0

            await asyncio.sleep(1)

        logger.warning("⏰ [贴吧] 45 秒内未检测到明确结果，需要人工复核")
        debug_path = await self._save_debug_snapshot(page, "wait_result_timeout")
        return {
            "success": False,
            "platform_url": page.url,
            "error_msg": "未检测到明确的发布成功提示，请到贴吧人工确认",
            "debug_path": debug_path,
        }

    # ═══════════════════════════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════════════════════════

    def _truncate_content(self, text: str, limit: int) -> str:
        """把正文截断到 limit 字以内，尽量在句末/段末断开，避免切在半句。

        贴吧正文硬上限 2000 字，超出发布按钮置灰；业务上统一拦截在 1900 字。
        留 3 字给省略号。
        """
        if len(text) <= limit:
            return text
        budget = max(1, limit - 3)
        head = text[:budget]
        # 优先在最后一个句末标点处断开（中英文句号/问号/感叹号/换行）
        cut = max(
            head.rfind("。"), head.rfind("！"), head.rfind("？"),
            head.rfind("\n"), head.rfind("."), head.rfind("!"), head.rfind("?"),
        )
        # 断点不能太靠前（至少保留 60% 内容），否则宁可硬切
        if cut >= int(budget * 0.6):
            return head[: cut + 1] + "…"
        return head + "…"

    def _deep_clean_content(self, content: str) -> str:
        """清理 Markdown/HTML，输出适合贴吧编辑器的纯文本（图片标记单独走插图，这里剥离）。"""
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

TIEBA_CONFIG = {
    "id": "tieba",
    "name": "百度贴吧",
    "code": "TB",
    "login_url": "https://tieba.baidu.com/",
    "publish_url": "https://tieba.baidu.com/",
    "color": "#3388FF",
}

registry.register("tieba", TiebaPublisher("tieba", TIEBA_CONFIG))
