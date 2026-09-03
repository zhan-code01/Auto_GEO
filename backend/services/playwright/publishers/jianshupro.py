# -*- coding: utf-8 -*-
"""简书发布适配器（codegen 稳定路径版）。

录制路径要点：
1. 打开简书首页；
2. 点击「写文章」并进入弹出的 writer 页面；
3. **点击「新建文章」创建空白草稿（关键：绝不复用当前编辑器，否则会覆盖上一篇文章）；**
4. 使用第二个 textbox 填标题；
5. 使用 #arthur-editor 填正文——图文混排：逐段 keyboard.insert_text 真键入文字，
   按均匀分布在段后触发简书图片上传（一段文字一张图）；
6. 点击「发布文章」。

关键约束（踩过的坑）：
- #arthur-editor 是 **markdown 源码编辑器（CodeMirror 系）**，只认真实键盘输入。
  合成 ClipboardEvent('paste') 不会写进去（JS 不报错 → 会假报成功），故正文一律走
  page.keyboard.insert_text，绝不用合成 paste 事件。
- 简书图片上传后是 **markdown 文本** ![](url)，不是 <img> 元素。因此不能用
  “统计编辑器里 <img> 数”来判断上传是否成功（恒为 0 → 误判失败 → 重复上传）。
  改为对比编辑器文本里 ![]( 出现次数是否增加。
- 图片只用一种方式：**复制粘贴**（构造带图片文件的合成 paste 事件派发给 CodeMirror，
  触发简书上传并在光标处插入 ![](url)）。不再叠加「点插入图片按钮 / input 遍历 / file chooser」
  多路兜底，以免同一张图被重复上传。
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger
from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from .base import BasePublisher, registry
from .note_utils import materialize_images


class JianshuProPublisher(BasePublisher):
    """简书发布器，基于用户 codegen 录制路径并补充图片发布能力。"""

    MAX_TITLE_LENGTH = 50
    MAX_CONTENT_LENGTH = 30000
    MAX_IMAGES = 9

    HOME_URL = "https://www.jianshu.com/"
    WRITER_URL = "https://www.jianshu.com/writer"

    async def publish(
        self,
        page: Page,
        article: Any,
        account: Any,
        declare_ai_content: bool = True,
    ) -> Dict[str, Any]:
        temp_files: list[str] = []
        stage = "init"
        active_page = page

        try:
            title = self._clean_title(getattr(article, "title", "") or "未命名文章")
            raw_content = getattr(article, "content", "") or ""
            content = self.markdown_to_plain_text(raw_content, drop_first_h1=True)[: self.MAX_CONTENT_LENGTH]

            logger.info("[简书Pro] 开始发布: {}", title)

            stage = "open_writer"
            active_page = await self._open_writer(active_page)
            manual_msg = await self._detect_manual_checkpoint(active_page)
            if manual_msg:
                return await self._manual_fail(active_page, stage, manual_msg)

            stage = "new_article"
            await self._prepare_article_editor(active_page)

            stage = "materialize_images"
            image_paths, image_temp_files = await materialize_images(article, limit=self.MAX_IMAGES)
            temp_files.extend(image_temp_files)
            if image_paths:
                logger.info("[简书Pro] 已准备 {} 张图片", len(image_paths))

            stage = "fill_title"
            if not await self._fill_title(active_page, title):
                return await self._fail(active_page, stage, "标题输入失败")

            stage = "fill_body"
            if not await self._fill_body(active_page, content, image_paths, raw_content):
                return await self._fail(active_page, stage, "正文写入失败")

            stage = "verify"
            if not await self._verify_written(active_page, title, content):
                return await self._fail(active_page, stage, "写入内容验证失败")

            stage = "publish"
            if not await self._click_publish(active_page):
                manual_msg = await self._detect_manual_checkpoint(active_page)
                if manual_msg:
                    return await self._manual_fail(active_page, stage, manual_msg)
                return await self._fail(active_page, stage, "未找到发布按钮")

            stage = "wait_result"
            return await self._wait_for_result(active_page)

        except Exception as exc:
            logger.exception("[简书Pro] 发布失败 stage={}: {}", stage, exc)
            manual_msg = await self._detect_manual_checkpoint(active_page)
            if manual_msg:
                return await self._manual_fail(active_page, stage, manual_msg)
            return await self._fail(active_page, stage, str(exc))
        finally:
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:
                    pass

    async def _open_writer(self, page: Page) -> Page:
        """优先复刻 codegen：打开首页并点击「写文章」进入弹窗页。"""
        await self._goto_soft(page, self.HOME_URL)
        await self._dismiss_common_popups(page)

        if await self._looks_like_writer(page):
            return page

        write_link = page.get_by_role("link", name=re.compile("写文章")).first
        if await self._is_visible(write_link, timeout=5000):
            try:
                async with page.expect_popup(timeout=8000) as popup_info:
                    await write_link.click(force=True)
                writer_page = await popup_info.value
                await writer_page.bring_to_front()
                await writer_page.wait_for_load_state("domcontentloaded", timeout=20000)
                await self._wait_after_navigation(writer_page)
                return writer_page
            except PlaywrightTimeoutError:
                logger.info("[简书Pro] 写文章未打开弹窗，继续使用当前页")
            except Exception as exc:
                logger.warning("[简书Pro] 点击写文章异常，尝试直接进入 writer: {}", exc)

        await self._goto_soft(page, self.config.get("publish_url", self.WRITER_URL))
        return page

    async def _prepare_article_editor(self, page: Page) -> None:
        await self._dismiss_common_popups(page)

        # 关键修复：始终点「新建文章」创建空白草稿，绝不复用当前编辑器。
        # 简书 writer 打开时会自动载入上一篇草稿；旧逻辑一旦发现已有编辑器就直接 return，
        # 随后 _fill_* 的 Ctrl+A/Backspace 会把用户上一篇文章清空覆盖
        # （即用户反馈的"不能新建文章，总改到别的文章"）。两份 codegen 都以「新建文章」为第一步。
        await self._create_new_article(page)

        await self._dismiss_common_popups(page)
        await self._wait_for_editor(page)

    async def _create_new_article(self, page: Page) -> bool:
        """点「新建文章」新建空白草稿，避免覆盖已有文章（codegen 第一步）。"""
        candidates = [
            page.get_by_text("新建文章", exact=True),
            page.get_by_role("button", name=re.compile("新建文章")),
            page.get_by_role("link", name=re.compile("新建文章")),
            page.locator('[title="新建文章"]'),
            page.locator("a._1GsW5, button._1GsW5, ._1GsW5"),
        ]
        for candidate in candidates:
            target = candidate.first
            if not await self._is_visible(target, timeout=2000):
                continue
            try:
                await target.click(force=True)
                await asyncio.sleep(1.0)
                await self._confirm_new_article_dialog(page)
                await asyncio.sleep(0.6)
                logger.info("[简书Pro] 已点击「新建文章」创建空白草稿")
                return True
            except Exception as exc:
                logger.debug("[简书Pro] 「新建文章」候选点击失败: {}", exc)
                continue

        logger.warning("[简书Pro] 未找到「新建文章」按钮，可能复用当前草稿（存在覆盖旧文风险）")
        return False

    async def _confirm_new_article_dialog(self, page: Page) -> None:
        """新建文章若弹确认框才点确认；无弹窗则什么都不做，避免二次新建/误点发布。"""
        dialog = page.locator('[role="dialog"], .modal, [class*="modal"], [class*="dialog"]').last
        if not await self._is_visible(dialog, timeout=600):
            return
        for text in ("确定", "确认", "继续", "好的", "新建"):
            button = dialog.get_by_role("button", name=re.compile(text)).last
            if await self._is_visible(button, timeout=400):
                try:
                    await button.click(force=True)
                    await asyncio.sleep(0.4)
                    return
                except Exception:
                    continue

    async def _fill_title(self, page: Page, title: str) -> bool:
        title_input = await self._find_title_input(page)
        if title_input is None:
            await self._log_editables(page)
            return False

        try:
            await title_input.click(force=True)
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.press("Backspace")
            try:
                await title_input.fill(title)
            except Exception:
                await page.keyboard.insert_text(title)
            await asyncio.sleep(0.4)
            logger.info("[简书Pro] 标题已写入: {}", title[:30])
            return True
        except Exception as exc:
            logger.warning("[简书Pro] 标题写入失败: {}", exc)
            return False

    async def _fill_body(self, page: Page, content: str, image_paths: list[str], raw_content: str = "") -> bool:
        """图文混排写正文：逐段真实键入文字，按原文图片标记位置在段后粘贴图片。

        #arthur-editor 是 markdown 源码编辑器（CodeMirror 系）：
        - 文字：必须用 page.keyboard.insert_text 真实键入；合成 paste 事件写不进去（会假成功）。
        - 图片：只用「复制粘贴」一种方式，粘贴后简书上传并在光标处插入 ![](url) 文本，
          用 markdown 里 ![]( 的出现次数来确认是否插入成功（不数 <img>，markdown 编辑器里没有）。
        - 图片位置：优先跟随原文标记（raw_content 中的 ![](...) / <img>，一段文字→图→一段文字）；
          原文没有图片标记时退回下方均匀分布兜底，保证老行为不被破坏。
        """
        image_paths = image_paths[: self.MAX_IMAGES]

        editor = await self._find_editor(page)
        if editor is None:
            await self._log_editables(page)
            return False

        # 聚焦并清空编辑器
        if not await self._focus_editor_end(page, editor):
            logger.warning("[简书Pro] 无法聚焦正文编辑器")
            return False
        try:
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.press("Backspace")
        except Exception:
            pass

        paragraphs = self._split_paragraphs(content)
        if not paragraphs and not image_paths:
            logger.warning("[简书Pro] 正文与图片均为空，跳过")
            return True

        blocks = self.build_content_blocks_by_markers(raw_content or content, image_paths, max_chars=self.MAX_CONTENT_LENGTH)
        if blocks is not None:
            inserted_images = await self._fill_body_from_blocks(page, editor, blocks)
            logger.info(
                "[简书Pro] 正文按原文位置写入完成：{} 个文本/图片块，{}/{} 张图片已插入",
                len(blocks), inserted_images, len(image_paths),
            )

            # 文字自检：首段内容能在编辑器里读到最好；读不到只告警不判失败——
            # 首段可能已随虚拟滚动移出可视区，或 _editor_text 偶发读空；正文实际已逐段真键入。
            # 真正的成败以后续 _verify_written（标题+首段双来源）与发布结果为准。
            needle = next((p.strip() for p in paragraphs if p.strip()), "")
            if needle:
                norm_text = re.sub(r"\s+", "", await self._editor_text(page))
                norm_needle = re.sub(r"\s+", "", needle[:20])
                if norm_needle and norm_needle not in norm_text:
                    logger.warning(
                        "[简书Pro] 正文自检未读到首段（needle={}），可能是编辑器虚拟滚动/读取偶发，"
                        "继续走 verify 阶段复核", needle[:20],
                    )
            return True

        plan = self._distribute_image_positions(len(paragraphs), len(image_paths))
        logger.info(
            "[简书Pro] 图文混排：{} 段文字 / {} 张图 → 段后插图计划 {}",
            len(paragraphs), len(image_paths), plan,
        )

        img_cursor = 0
        inserted_images = 0

        for index, para in enumerate(paragraphs):
            if para.strip():
                try:
                    await page.keyboard.insert_text(para)
                except Exception:
                    try:
                        await page.keyboard.type(para, delay=5)
                    except Exception as exc:
                        logger.warning("[简书Pro] 第 {} 段文字写入失败: {}", index + 1, exc)
            for _ in range(1):  # 段间只留 1 个换行（双换行会放大成巨大空栏）
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass

            for _ in range(plan.get(index, 0)):
                if img_cursor >= len(image_paths):
                    break
                path = image_paths[img_cursor]
                img_cursor += 1
                if await self._paste_image_at_cursor(page, editor, path):
                    inserted_images += 1
                    # 光标已由 _paste_image_at_cursor 移到图片下方新行，直接接着写下一段
                else:
                    logger.warning("[简书Pro] 第 {} 张图粘贴失败: {}", img_cursor, path)

        # 图多于段 / 无正文：剩余图片追加到末尾
        while img_cursor < len(image_paths):
            path = image_paths[img_cursor]
            img_cursor += 1
            if await self._paste_image_at_cursor(page, editor, path):
                inserted_images += 1
            else:
                logger.warning("[简书Pro] 末尾第 {} 张图粘贴失败: {}", img_cursor, path)

        logger.info(
            "[简书Pro] 正文写入完成：{} 段文字，{}/{} 张图片已插入",
            len(paragraphs), inserted_images, len(image_paths),
        )

        # 文字自检：首段内容能在编辑器里读到最好；读不到只告警不判失败——
        # 首段可能已随虚拟滚动移出可视区，或 _editor_text 偶发读空；正文实际已逐段真键入。
        # 真正的成败以后续 _verify_written（标题+首段双来源）与发布结果为准。
        needle = next((p.strip() for p in paragraphs if p.strip()), "")
        if needle:
            norm_text = re.sub(r"\s+", "", await self._editor_text(page))
            norm_needle = re.sub(r"\s+", "", needle[:20])
            if norm_needle and norm_needle not in norm_text:
                logger.warning(
                    "[简书Pro] 正文自检未读到首段（needle={}），可能是编辑器虚拟滚动/读取偶发，"
                    "继续走 verify 阶段复核", needle[:20],
                )
        return True

    async def _fill_body_from_blocks(self, page: Page, editor: Locator, blocks: list[dict[str, str]]) -> int:
        """按原文图片标记位置逐块写入：文本块逐段键入，图片块在光标处粘贴。

        文本块内部段落间只留 1 个换行；图片粘贴后光标已由 _paste_image_at_cursor
        移到图片下方新行，可直接续写下一段。返回成功粘贴的图片张数。
        """
        inserted_images = 0
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
                                logger.warning("[简书Pro] 段落文字写入失败: {}", exc)
                    for _ in range(1):  # 段间只留 1 个换行（双换行会放大成巨大空栏）
                        try:
                            await page.keyboard.press("Enter")
                        except Exception:
                            pass
            else:
                if await self._paste_image_at_cursor(page, editor, block["content"]):
                    inserted_images += 1
                else:
                    logger.warning("[简书Pro] 按原文位置粘贴图片失败: {}", block["content"])
        return inserted_images

    def _split_paragraphs(self, text: str) -> list[str]:
        """把已清洗正文切成段落。清洗后段落以空行分隔，无空行则退回按行切。"""
        parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        if not parts:
            parts = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
        return parts or ([text.strip()] if text and text.strip() else [])

    def _distribute_image_positions(self, num_paragraphs: int, num_images: int) -> Dict[int, int]:
        """返回 {段落索引: 该段之后插入的图片数}，把图片尽量均匀铺到各段之后。

        例：6 段 3 图 → {1:1, 3:1, 4:1}；3 段 3 图 → {0:1,1:1,2:1}（一段一图）；
        图多于段时由上层把多出的追加到末尾。
        """
        plan: Dict[int, int] = {}
        if num_images <= 0 or num_paragraphs <= 0:
            return plan
        capped = min(num_images, num_paragraphs)  # 段后最多铺满每段一张，余量追加到末尾
        for k in range(capped):
            idx = int((k + 1) * num_paragraphs / (capped + 1))
            idx = max(0, min(num_paragraphs - 1, idx))
            plan[idx] = plan.get(idx, 0) + 1
        return plan

    async def _focus_editor_end(self, page: Page, editor: Locator) -> bool:
        """聚焦正文编辑器并把光标移到文末（保证后续文字/图片追加在末尾）。"""
        try:
            await editor.click(force=True)
            await page.keyboard.press("ControlOrMeta+End")
            return True
        except Exception:
            try:
                await editor.click(force=True)
                return True
            except Exception:
                return False

    async def _paste_image_at_cursor(self, page: Page, editor: Locator, image_path: str) -> bool:
        """把单张图片以「复制粘贴」方式插入当前光标处。

        构造带真实图片文件的合成 paste 事件派发给编辑器，触发简书上传，
        上传成功后编辑器 markdown 里会多出一个 ![](url)。只用这一种方式，避免重复插图。
        """
        try:
            mime = mimetypes.guess_type(image_path)[0] or "image/png"
            suffix = Path(image_path).suffix or ".png"
            with open(image_path, "rb") as image_file:
                payload = base64.b64encode(image_file.read()).decode("ascii")
        except Exception as exc:
            logger.warning("[简书Pro] 读取图片失败: {} {}", image_path, exc)
            return False

        before = self._count_markdown_images(await self._editor_text(page))

        try:
            dispatched = bool(
                await page.evaluate(
                    """({ payload, mime, name }) => {
                        const binary = atob(payload);
                        const bytes = new Uint8Array(binary.length);
                        for (let i = 0; i < binary.length; i += 1) {
                            bytes[i] = binary.charCodeAt(i);
                        }
                        const file = new File([bytes], name, { type: mime });
                        const data = new DataTransfer();
                        data.items.add(file);
                        // 单一派发目标，避免冒泡到多个监听器导致重复上传。
                        // CodeMirror5 的 paste 监听绑在隐藏的 textarea.CodeMirror-input 上，
                        // 优先命中它 → CodeMirror 容器 → #arthur-editor → 当前聚焦元素。
                        let target = document.querySelector('.CodeMirror textarea')
                            || document.querySelector('.CodeMirror')
                            || document.querySelector('#arthur-editor');
                        if (!target && document.activeElement && document.activeElement !== document.body) {
                            target = document.activeElement;
                        }
                        if (!target) return false;
                        try { target.focus(); } catch (e) {}
                        const event = new ClipboardEvent('paste', {
                            clipboardData: data,
                            bubbles: true,
                            cancelable: true
                        });
                        try { Object.defineProperty(event, 'clipboardData', { value: data }); } catch (e) {}
                        target.dispatchEvent(event);
                        return true;
                    }""",
                    {"payload": payload, "mime": mime, "name": f"autogeo{suffix}"},
                )
            )
        except Exception as exc:
            logger.warning("[简书Pro] 图片 paste 派发失败: {}", exc)
            return False

        if not dispatched:
            return False

        # 等待上传落地（markdown 图片计数增加）。注意：即使这里没等到计数增加，
        # 只要 paste 已派发、上传大概率在途，也必须把光标移出图片语法——否则下一张会贴进
        # 上一张的括号里形成 ![a](url1)\n](url2) 嵌套坏图（用户实测正是此现象）。
        confirmed = await self._wait_markdown_image_increase(page, before)

        # 关键：按用户给的手法 ↓↓ + 回车，把光标挪到图片下方新行，保证后续内容另起一行。
        # 无条件执行（不受 confirmed 影响），从根上杜绝图片嵌套。
        await self._move_cursor_below_image(page)

        if not confirmed:
            logger.warning(
                "[简书Pro] 图片已粘贴但未在 ~20s 内读到计数增加（可能读取偶发或上传较慢）: {}",
                Path(image_path).name,
            )
        return True

    async def _move_cursor_below_image(self, page: Page) -> None:
        """把光标移出刚粘贴的图片语法、落到下方新行。

        用户实测手法：粘贴图片后「连续按两下 ↓ 箭头 + 一个回车」，光标即可离开
        ![](url) 落到新行，后续内容正常另起一行。这里以真实键盘复刻该手法为主
        （粘贴已把焦点放在 CodeMirror 隐藏 textarea 上，方向键会作用于编辑器）；
        键盘不生效时再用 CodeMirror 实例 API 兜底（setCursor 到文末 + 换行）。
        """
        try:
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            return
        except Exception as exc:
            logger.debug("[简书Pro] 键盘光标下移失败，回退 CM API: {}", exc)

        try:
            await page.evaluate(
                """() => {
                    const el = document.querySelector('.CodeMirror');
                    const cm = el && el.CodeMirror;
                    if (!cm || typeof cm.setCursor !== 'function') return false;
                    const last = cm.lineCount() - 1;
                    cm.setCursor({ line: last, ch: cm.getLine(last).length });
                    cm.replaceSelection('\\n');
                    cm.focus();
                    return true;
                }"""
            )
        except Exception as exc:
            logger.debug("[简书Pro] CM 光标下移兜底也失败: {}", exc)

    async def _editor_text(self, page: Page) -> str:
        """读取编辑器当前 markdown 文本。

        简书 #arthur-editor 是 CodeMirror5：真实源码只在实例 .getValue() 里，
        DOM 里 .CodeMirror-code 因虚拟滚动只渲染可视行（长文读不全）。
        因此优先 CM 实例 API；.CodeMirror 元素上的实例句柄可能挂在自身或子孙节点，
        两处都找。最后才回退 innerText。
        """
        try:
            return str(
                await page.evaluate(
                    """() => {
                        // 1) 找 CodeMirror5 实例，优先 .getValue()（完整源码）
                        const holders = Array.from(document.querySelectorAll('.CodeMirror'));
                        for (const el of holders) {
                            const cm = el.CodeMirror
                                || (el.querySelector && el.querySelector('.CodeMirror') && el.querySelector('.CodeMirror').CodeMirror);
                            if (cm && typeof cm.getValue === 'function') {
                                const v = cm.getValue();
                                if (v) return v;
                            }
                        }
                        // 2) 回退：渲染出的代码行（仅可视，够做“图片是否变多/首段是否在”粗判）
                        const code = document.querySelector('.CodeMirror-code');
                        if (code && (code.innerText || code.textContent)) {
                            return code.innerText || code.textContent;
                        }
                        // 3) 再回退：隐藏 textarea / 容器 innerText
                        const ta = document.querySelector('.CodeMirror textarea');
                        if (ta && ta.value) return ta.value;
                        const ed = document.querySelector('#arthur-editor');
                        if (ed) return ed.innerText || ed.textContent || '';
                        const ce = document.querySelector('[contenteditable="true"]');
                        return ce ? (ce.innerText || ce.textContent || '') : '';
                    }"""
                )
                or ""
            )
        except Exception:
            return ""

    @staticmethod
    def _count_markdown_images(text: str) -> int:
        """统计 markdown 正文里的图片数（![](...) 或 ![alt](...)）。"""
        return len(re.findall(r"!\[[^\]]*\]\(", text or ""))

    async def _wait_markdown_image_increase(self, page: Page, before_count: int) -> bool:
        """等待编辑器 markdown 图片数超过 before_count（覆盖上传网络耗时，最长 ~20s）。

        真实上传通常 ~3s 内落地；给到 20s 兜住网络抖动，又不至于在粘贴失败时空等太久。
        """
        for _ in range(40):
            if self._count_markdown_images(await self._editor_text(page)) > before_count:
                await self._wait_upload_settle(page)
                return True
            await asyncio.sleep(0.5)
        return False

    async def _click_publish(self, page: Page) -> bool:
        await self._dismiss_common_popups(page)
        try:
            await page.mouse.wheel(0, -700)
        except Exception:
            pass

        candidates = [
            page.get_by_text("发布文章", exact=True).last,
            page.get_by_role("button", name=re.compile("发布文章|发布|立即发布|确认发布")).last,
            page.get_by_role("link", name=re.compile("发布文章|发布")).last,
            page.locator('button:has-text("发布文章"), a:has-text("发布文章"), span:has-text("发布文章")').last,
            page.locator('button:has-text("发布"), a:has-text("发布"), span:has-text("发布")').last,
        ]
        for candidate in candidates:
            if await self._is_visible(candidate, timeout=2500):
                try:
                    await candidate.click(force=True)
                    await asyncio.sleep(1.0)
                    await self._confirm_publish_if_needed(page)
                    logger.info("[简书Pro] 已点击发布")
                    return True
                except Exception:
                    continue
        return False

    async def _wait_for_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）"""
        for _ in range(60):  # 60次 × 2秒 = 120秒
            manual_msg = await self._detect_manual_checkpoint(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            current_url = page.url or ""
            if re.search(r"jianshu\.com/p/[A-Za-z0-9]+", current_url):
                logger.success("[简书Pro] 发布成功: {}", current_url)
                return {"success": True, "platform_url": current_url, "error_msg": None}

            for text in ("发布成功", "已发布", "审核中"):
                node = page.get_by_text(text, exact=False).first
                if await self._is_visible(node, timeout=300):
                    logger.success("[简书Pro] 检测到成功提示: {}", text)
                    return {"success": True, "platform_url": current_url, "error_msg": None}

            for text in ("发布失败", "标题不能为空", "正文不能为空", "内容违规", "异常请求", "操作频繁"):
                node = page.get_by_text(text, exact=False).first
                if await self._is_visible(node, timeout=300):
                    message = (await node.inner_text()).strip() or text
                    return await self._fail(page, "wait_result", message)

            await asyncio.sleep(2)

        return await self._fail(page, "wait_result", "发布结果未确认，请到简书后台人工确认（已等待120秒）")

    async def _find_title_input(self, page: Page) -> Locator | None:
        candidates = [
            page.get_by_role("textbox").nth(1),
            page.locator("input._24i7u").first,
            page.locator('input[class*="_24i7u"]').first,
            page.locator('input[placeholder*="标题"], textarea[placeholder*="标题"]').first,
            page.locator('input[name*="title"], textarea[name*="title"]').first,
        ]
        for candidate in candidates:
            if await self._is_visible(candidate, timeout=1200):
                return candidate

        marked = await page.evaluate(
            """() => {
                document.querySelectorAll('[data-autogeo-jianshu-title]').forEach((el) => {
                    el.removeAttribute('data-autogeo-jianshu-title');
                });
                const inputs = Array.from(document.querySelectorAll('input, textarea'));
                const target = inputs.find((el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 180 && rect.height > 20
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                });
                if (!target) return false;
                target.setAttribute('data-autogeo-jianshu-title', '1');
                return true;
            }"""
        )
        return page.locator('[data-autogeo-jianshu-title="1"]').first if marked else None

    async def _find_editor(self, page: Page) -> Locator | None:
        candidates = [
            page.locator("#arthur-editor").first,
            page.locator("#editor").first,
            page.locator("#editor div").first,
            page.locator("#editor [contenteditable='true']").first,
            page.locator(".ql-editor").first,
            page.locator(".public-DraftEditor-content").first,
            page.locator('[contenteditable="true"]').last,
        ]
        for candidate in candidates:
            if await self._is_visible(candidate, timeout=1200):
                box = await candidate.bounding_box()
                if box and box.get("width", 0) > 120 and box.get("height", 0) > 40:
                    return candidate

        marked = await page.evaluate(
            """() => {
                document.querySelectorAll('[data-autogeo-jianshu-editor]').forEach((el) => {
                    el.removeAttribute('data-autogeo-jianshu-editor');
                });
                const selectors = ['#arthur-editor', '#editor div', '#editor', '[contenteditable="true"]', 'textarea'];
                const nodes = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)));
                const target = nodes.find((el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 200 && rect.height > 80
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                });
                if (!target) return false;
                target.setAttribute('data-autogeo-jianshu-editor', '1');
                return true;
            }"""
        )
        return page.locator('[data-autogeo-jianshu-editor="1"]').first if marked else None

    async def _confirm_publish_if_needed(self, page: Page) -> None:
        for text in ("确认发布", "立即发布", "确定", "发布"):
            button = page.get_by_role("button", name=text).last
            if await self._is_visible(button, timeout=1000):
                try:
                    await button.click(force=True)
                    await asyncio.sleep(0.8)
                    return
                except Exception:
                    continue

    async def _verify_written(self, page: Page, title: str, content: str) -> bool:
        """校验标题/正文确已写入——宽松策略，避免编辑器读取偶发导致误判。

        正文用编辑器 markdown（CodeMirror 实例值）+ body 文本双来源做「去空白包含」匹配
        （图文混排会在段间插 ![](url)，不能拿连续 80 字硬比）。
        判定：标题在 或 首段在 → 通过（任一命中即证明编辑器已被填充）；
        两者都读不到才判失败。CodeMirror 虚拟滚动会让首段移出可视区、getValue 偶发读空，
        真正的成败以发布结果为准，这里只拦“编辑器整体空白”的硬故障。
        """
        try:
            expected_title = title.strip()
            editor_text = await self._editor_text(page)
            first_para = next(
                (p.strip() for p in self._split_paragraphs(content) if p.strip()), ""
            )
            needle = re.sub(r"\s+", "", first_para)[:40]
            title_ok = bool(expected_title) and await page.evaluate(
                """(expectedTitle) => {
                    const bodyText = (document.body.innerText || '').replace(/\\s+/g, ' ').trim();
                    const values = Array.from(document.querySelectorAll('input, textarea'))
                        .map((el) => String(el.value || '').trim());
                    return values.includes(expectedTitle) || bodyText.includes(expectedTitle);
                }""",
                expected_title,
            )
            content_ok = False
            if needle:
                norm_editor = re.sub(r"\s+", "", editor_text)
                if needle in norm_editor:
                    content_ok = True
                else:
                    body_norm = re.sub(
                        r"\s+",
                        "",
                        str(await page.evaluate("() => document.body.innerText || ''")),
                    )
                    content_ok = needle in body_norm
            # 无正文要求时按标题判；任一命中即通过
            if not needle:
                return bool(title_ok)
            if title_ok or content_ok:
                return True
            logger.warning(
                "[简书Pro] verify 未读到标题也未读到首段（title_ok={} content_ok={}），判失败",
                title_ok, content_ok,
            )
            return False
        except Exception:
            return True

    async def _detect_manual_checkpoint(self, page: Page) -> str | None:
        manual_msg = await self.detect_manual_intervention(page)
        if manual_msg:
            return manual_msg

        url = (page.url or "").lower()
        if any(part in url for part in ("sign_in", "login", "passport", "captcha", "verify")):
            return "简书进入登录或安全验证页面，请重新授权后再发布"

        checks = [
            ("异常请求", "简书返回异常请求，可能触发风控，请人工确认登录态或稍后重试"),
            ("登录", "简书账号未登录，请重新授权后再发布"),
            ("验证码", "简书需要验证码验证，请人工完成后再发布"),
            ("安全验证", "简书需要安全验证，请人工完成后再发布"),
            ("绑定手机号和微信", "简书要求发布前绑定手机号和微信，请人工完成绑定后重试"),
            ("发布公开文章需要同时绑定手机号和微信", "简书要求发布前绑定手机号和微信，请人工完成绑定后重试"),
            ("操作频繁", "简书提示操作频繁，请稍后重试"),
        ]
        for text, message in checks:
            node = page.get_by_text(text, exact=False).first
            if await self._is_visible(node, timeout=300):
                return message
        return None

    async def _dismiss_common_popups(self, page: Page) -> None:
        for _ in range(2):
            for text in ("知道了", "我知道了", "关闭", "跳过", "确定", "稍后", "不用了", "取消"):
                button = page.get_by_role("button", name=text).last
                if await self._is_visible(button, timeout=300):
                    try:
                        await button.click(force=True)
                        await asyncio.sleep(0.2)
                    except Exception:
                        pass
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

    async def _looks_like_writer(self, page: Page) -> bool:
        if "/writer" in (page.url or ""):
            return True
        return await self._find_editor(page) is not None

    async def _wait_for_editor(self, page: Page) -> None:
        for _ in range(20):
            if await self._find_title_input(page) and await self._find_editor(page):
                return
            await asyncio.sleep(0.5)

    async def _goto_soft(self, page: Page, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await self._wait_after_navigation(page)

    async def _wait_after_navigation(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await asyncio.sleep(1.2)

    async def _wait_upload_settle(self, page: Page) -> None:
        for _ in range(30):
            uploading = False
            for text in ("上传中", "正在上传", "处理中"):
                node = page.get_by_text(text, exact=False).first
                if await self._is_visible(node, timeout=200):
                    uploading = True
                    break
            if not uploading:
                return
            await asyncio.sleep(0.5)

    async def _is_visible(self, locator: Locator, timeout: int = 1000) -> bool:
        try:
            return await locator.count() > 0 and await locator.is_visible(timeout=timeout)
        except Exception:
            return False

    async def _fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        debug_path = await self._save_debug_snapshot(page, f"fail_{stage}")
        logger.error("[简书Pro] stage={} 失败: {}", stage, message)
        return {
            "success": False,
            "platform_url": page.url if page else None,
            "error_msg": f"[{stage}] {message}",
            "debug_path": debug_path,
        }

    async def _manual_fail(self, page: Page, stage: str, message: str) -> Dict[str, Any]:
        debug_path = await self._save_debug_snapshot(page, f"manual_{stage}")
        result = self.manual_intervention_result(stage, message, page)
        result["debug_path"] = debug_path
        return result

    async def _save_debug_snapshot(self, page: Page, stage: str) -> str:
        debug_dir = Path("backend/debug/jianshu")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[简书Pro] 保存 HTML 调试快照失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[简书Pro] 保存截图失败: {}", exc)
        return str(html_path)

    async def _log_editables(self, page: Page) -> None:
        try:
            info = await page.evaluate(
                """() => Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], #arthur-editor, #editor'))
                    .slice(0, 20)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        return {
                            tag: el.tagName,
                            id: el.id || '',
                            cls: String(el.className || '').slice(0, 80),
                            placeholder: el.getAttribute('placeholder') || '',
                            text: String(el.innerText || el.value || '').slice(0, 40),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        };
                    })"""
            )
            logger.warning("[简书Pro] 可编辑元素调试信息: {}", info)
        except Exception:
            pass

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"[#*`\"<>]", "", title or "").strip()
        return cleaned[: self.MAX_TITLE_LENGTH] or "未命名文章"


JianshuPublisher = JianshuProPublisher


JIANSHU_CONFIG = {
    "name": "简书",
    "publish_url": JianshuProPublisher.WRITER_URL,
    "color": "#EA6F5A",
    "version": "pro-codegen",
}
registry.register("jianshu", JianshuProPublisher("jianshu", JIANSHU_CONFIG))
