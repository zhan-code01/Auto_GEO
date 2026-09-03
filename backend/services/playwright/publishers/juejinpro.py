# -*- coding: utf-8 -*-
"""掘金（juejin.cn）发布适配器（codegen 稳定路径版）。

用户 codegen 录制路径要点：
1. 打开掘金首页 → 点「创作者中心」→ 点「写文章」（弹出新标签页的 markdown 编辑器）。
   本实现优先直接导航到 /editor/drafts/new 创建空白草稿（更稳、绝不覆盖旧草稿），
   编辑器未出现再回退 codegen 的「创作者中心 → 写文章」弹窗路径。
2. 用占位符「输入文章标题」的输入框填标题。
3. 编辑器是 **CodeMirror markdown 源码编辑器**（左边源码 / 右边实时预览）：
   - 文字：page.keyboard.insert_text 真实键入（合成 paste 写不进 CodeMirror，会假成功）；
   - 图片：构造带真实文件的合成 paste 事件派发给 .CodeMirror，触发掘金上传，
     在光标处插入 ![name](url) markdown（与简书同机制）。
4. **关键难点（用户特别强调）**：掘金图片 URL 极长（带一大串签名参数），插入后会在
   源码里折成很多可视行，光标停在图片语法内部；不把光标移出图片、落到下方新行，
   下一段/下一张就会嵌进上一张的括号里。用户手法是「粘贴图片后连按多次 ↓ + 一个回车」。
   由于 URL 折行行数不定，逐下 ArrowDown 不可靠，本实现以「CodeMirror 实例 setCursor
   到文末 + 换行」为主（不受折行影响），键盘 Ctrl/Cmd+End+回车、多次 ArrowDown+回车为兜底。
5. 发布弹窗：点「发布」→ 固定选分类「阅读」→ 在「添加标签」输入 SaaS 并回车
   → 确认标签已生成 → 点「确定并发布」。

约束（与简书一致的坑）：
- CodeMirror 只认真实键盘输入写文字；图片走合成 paste。
- 图片是 markdown 文本 ![](url) 不是 <img>，用 ![]( 出现次数判断是否插入成功。
- 分类、标签是掘金发布的必填项；任一项未确认成功时必须停止，不能继续点击「确定并发布」。
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


class JuejinProPublisher(BasePublisher):
    """掘金发布器：复用简书 CodeMirror 图文混排机制，适配掘金入口/标题/发布弹窗。"""

    MAX_TITLE_LENGTH = 50
    MAX_CONTENT_LENGTH = 30000
    MAX_IMAGES = 9
    HOME_URL = "https://juejin.cn/"
    EDITOR_URL = "https://juejin.cn/editor/drafts/new"

    DEFAULT_CATEGORY = "阅读"
    DEFAULT_TAG = "SaaS"

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

            logger.info("[掘金] 开始发布: {}", title)

            stage = "open_editor"
            active_page = await self._open_editor(active_page)
            manual_msg = await self._detect_manual_checkpoint(active_page)
            if manual_msg:
                return await self._manual_fail(active_page, stage, manual_msg)

            stage = "wait_editor"
            await self._wait_for_editor(active_page)

            stage = "materialize_images"
            image_paths, image_temp_files = await materialize_images(article, limit=self.MAX_IMAGES)
            temp_files.extend(image_temp_files)
            if image_paths:
                logger.info("[掘金] 已准备 {} 张图片", len(image_paths))

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
            if not await self._click_publish(active_page, article, image_paths):
                manual_msg = await self._detect_manual_checkpoint(active_page)
                if manual_msg:
                    return await self._manual_fail(active_page, stage, manual_msg)
                return await self._fail(active_page, stage, "发布流程未完成（分类/标签/确定并发布）")

            stage = "wait_result"
            return await self._wait_for_result(active_page)

        except Exception as exc:
            logger.exception("[掘金] 发布失败 stage={}: {}", stage, exc)
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

    # ------------------------------------------------------------------ 入口

    async def _open_editor(self, page: Page) -> Page:
        """进入掘金 markdown 编辑器。

        优先直接导航到 /editor/drafts/new 建空白草稿（最稳、绝不覆盖旧草稿）；
        编辑器没出现再回退 codegen 路径：首页 → 创作者中心 → 写文章（弹新标签）。
        """
        await self._goto_soft(page, self.config.get("publish_url", self.EDITOR_URL))
        await self._dismiss_common_popups(page)
        if await self._find_editor(page) is not None:
            return page

        # 回退：codegen 弹窗路径
        await self._goto_soft(page, self.HOME_URL)
        await self._dismiss_common_popups(page)

        creator = page.get_by_role("button", name=re.compile("创作者中心")).first
        if await self._is_visible(creator, timeout=4000):
            try:
                await creator.click(force=True)
                await asyncio.sleep(1.0)
            except Exception:
                pass

        write_btn = page.get_by_role("button", name=re.compile("写文章")).first
        if await self._is_visible(write_btn, timeout=4000):
            try:
                async with page.expect_popup(timeout=8000) as popup_info:
                    await write_btn.click(force=True)
                writer_page = await popup_info.value
                await writer_page.bring_to_front()
                await writer_page.wait_for_load_state("domcontentloaded", timeout=20000)
                await self._wait_after_navigation(writer_page)
                return writer_page
            except PlaywrightTimeoutError:
                logger.info("[掘金] 写文章未弹新标签，继续用当前页")
            except Exception as exc:
                logger.warning("[掘金] 点击写文章异常: {}", exc)

        # 最后再直连一次编辑器
        await self._goto_soft(page, self.config.get("publish_url", self.EDITOR_URL))
        return page

    # ------------------------------------------------------------------ 标题

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
            logger.info("[掘金] 标题已写入: {}", title[:30])
            return True
        except Exception as exc:
            logger.warning("[掘金] 标题写入失败: {}", exc)
            return False

    async def _find_title_input(self, page: Page) -> Locator | None:
        candidates = [
            page.get_by_placeholder(re.compile("输入文章标题|标题")).first,
            page.locator('input[placeholder*="标题"], textarea[placeholder*="标题"]').first,
            page.get_by_role("textbox").first,
        ]
        for candidate in candidates:
            if await self._is_visible(candidate, timeout=1500):
                return candidate
        return None

    # ------------------------------------------------------------------ 正文（图文混排）

    async def _fill_body(self, page: Page, content: str, image_paths: list[str], raw_content: str = "") -> bool:
        """图文混排写正文：逐段真实键入文字，按原文图片标记位置在段后粘贴图片。

        与简书同机制：文字必须 keyboard.insert_text 真键入，图片只用「复制粘贴」，
        每粘一张图后无条件把光标移出图片语法、落到下方新行（掘金 URL 超长，重点在这）。
        图片位置优先跟随原文标记（raw_content 中的 ![](...) / <img>）；原文没有图片标记
        时退回下方均匀分布兜底，保证老行为不被破坏。
        """
        image_paths = image_paths[: self.MAX_IMAGES]

        editor = await self._find_editor(page)
        if editor is None:
            await self._log_editables(page)
            return False

        if not await self._focus_editor_end(page, editor):
            logger.warning("[掘金] 无法聚焦正文编辑器")
            return False
        try:
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.press("Backspace")
        except Exception:
            pass

        paragraphs = self._split_paragraphs(content)
        if not paragraphs and not image_paths:
            logger.warning("[掘金] 正文与图片均为空，跳过")
            return True

        blocks = self.build_content_blocks_by_markers(raw_content or content, image_paths, max_chars=self.MAX_CONTENT_LENGTH)
        if blocks is not None:
            inserted_images = await self._fill_body_from_blocks(page, editor, blocks)
            logger.info(
                "[掘金] 正文按原文位置写入完成：{} 个文本/图片块，{}/{} 张图片已插入",
                len(blocks), inserted_images, len(image_paths),
            )

            # 文字自检：读不到只告警不判失败（CodeMirror 虚拟滚动/偶发读空），成败以 verify + 发布结果为准。
            needle = next((p.strip() for p in paragraphs if p.strip()), "")
            if needle:
                norm_text = re.sub(r"\s+", "", await self._editor_text(page))
                norm_needle = re.sub(r"\s+", "", needle[:20])
                if norm_needle and norm_needle not in norm_text:
                    logger.warning(
                        "[掘金] 正文自检未读到首段（needle={}），可能是编辑器虚拟滚动/读取偶发，"
                        "继续走 verify 阶段复核", needle[:20],
                    )
            return True

        plan = self._distribute_image_positions(len(paragraphs), len(image_paths))
        logger.info(
            "[掘金] 图文混排：{} 段文字 / {} 张图 → 段后插图计划 {}",
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
                        logger.warning("[掘金] 第 {} 段文字写入失败: {}", index + 1, exc)
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
                    logger.warning("[掘金] 第 {} 张图粘贴失败: {}", img_cursor, path)

        # 图多于段 / 无正文：剩余图片追加到末尾
        while img_cursor < len(image_paths):
            path = image_paths[img_cursor]
            img_cursor += 1
            if await self._paste_image_at_cursor(page, editor, path):
                inserted_images += 1
            else:
                logger.warning("[掘金] 末尾第 {} 张图粘贴失败: {}", img_cursor, path)

        logger.info(
            "[掘金] 正文写入完成：{} 段文字，{}/{} 张图片已插入",
            len(paragraphs), inserted_images, len(image_paths),
        )

        # 文字自检：读不到只告警不判失败（CodeMirror 虚拟滚动/偶发读空），成败以 verify + 发布结果为准。
        needle = next((p.strip() for p in paragraphs if p.strip()), "")
        if needle:
            norm_text = re.sub(r"\s+", "", await self._editor_text(page))
            norm_needle = re.sub(r"\s+", "", needle[:20])
            if norm_needle and norm_needle not in norm_text:
                logger.warning(
                    "[掘金] 正文自检未读到首段（needle={}），可能是编辑器虚拟滚动/读取偶发，"
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
                                logger.warning("[掘金] 段落文字写入失败: {}", exc)
                    for _ in range(1):  # 段间只留 1 个换行（双换行会放大成巨大空栏）
                        try:
                            await page.keyboard.press("Enter")
                        except Exception:
                            pass
            else:
                if await self._paste_image_at_cursor(page, editor, block["content"]):
                    inserted_images += 1
                else:
                    logger.warning("[掘金] 按原文位置粘贴图片失败: {}", block["content"])
        return inserted_images

    def _split_paragraphs(self, text: str) -> list[str]:
        """把已清洗正文切成段落。清洗后段落以空行分隔，无空行则退回按行切。"""
        parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
        if not parts:
            parts = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
        return parts or ([text.strip()] if text and text.strip() else [])

    def _distribute_image_positions(self, num_paragraphs: int, num_images: int) -> Dict[int, int]:
        """返回 {段落索引: 该段之后插入的图片数}，把图片尽量均匀铺到各段之后。"""
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

        构造带真实图片文件的合成 paste 事件派发给 CodeMirror，触发掘金上传，
        上传后编辑器 markdown 里会多出一个 ![](url)。只用这一种方式，避免重复插图。
        """
        try:
            mime = mimetypes.guess_type(image_path)[0] or "image/png"
            suffix = Path(image_path).suffix or ".png"
            with open(image_path, "rb") as image_file:
                payload = base64.b64encode(image_file.read()).decode("ascii")
        except Exception as exc:
            logger.warning("[掘金] 读取图片失败: {} {}", image_path, exc)
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
                        // 优先命中它 → CodeMirror 容器 → 当前聚焦元素。
                        let target = document.querySelector('.CodeMirror textarea')
                            || document.querySelector('.CodeMirror');
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
            logger.warning("[掘金] 图片 paste 派发失败: {}", exc)
            return False

        if not dispatched:
            return False

        # 等上传落地（markdown 图片计数增加）。即便没等到，只要已派发就必须把光标移出图片语法，
        # 否则下一张会嵌进上一张括号里形成 ![a](url1)\n](url2) 坏图。
        confirmed = await self._wait_markdown_image_increase(page, before)

        # 关键：把光标挪到图片下方新行（掘金 URL 超长会折行，重点在此）。无条件执行。
        await self._move_cursor_below_image(page)

        if not confirmed:
            logger.warning(
                "[掘金] 图片已粘贴但未在 ~20s 内读到计数增加（可能读取偶发或上传较慢）: {}",
                Path(image_path).name,
            )
        return True

    async def _move_cursor_below_image(self, page: Page) -> None:
        """把光标移出刚粘贴的图片语法、落到下方新行。

        掘金图片 URL 极长，插入后会在源码里折成很多可视行；逐下 ArrowDown 的行数不定、
        不可靠。优先用 CodeMirror 实例把光标 setCursor 到文档末尾并换行（不受折行影响）；
        实例拿不到时用键盘 Ctrl/Cmd+End+回车（跳文末，同样不受折行影响）；再不行才复刻
        用户手法：连续多次 ↓ + 回车。
        """
        # 1) CodeMirror 实例 API：光标跳到文档末尾并换行（最稳）
        try:
            moved = bool(
                await page.evaluate(
                    """() => {
                        const holders = Array.from(document.querySelectorAll('.CodeMirror'));
                        for (const el of holders) {
                            const cm = el.CodeMirror
                                || (el.querySelector && el.querySelector('.CodeMirror') && el.querySelector('.CodeMirror').CodeMirror);
                            if (cm && typeof cm.setCursor === 'function') {
                                const last = cm.lineCount() - 1;
                                cm.setCursor({ line: last, ch: cm.getLine(last).length });
                                cm.replaceSelection('\\n');
                                cm.focus();
                                return true;
                            }
                        }
                        return false;
                    }"""
                )
            )
            if moved:
                await asyncio.sleep(0.2)
                return
        except Exception as exc:
            logger.debug("[掘金] CM 光标下移失败，回退键盘: {}", exc)

        # 2) 键盘兜底：Ctrl/Cmd+End 跳文末 + 回车
        try:
            await page.keyboard.press("ControlOrMeta+End")
            await page.keyboard.press("Enter")
            return
        except Exception as exc:
            logger.debug("[掘金] 键盘 Ctrl+End 下移失败，回退 ArrowDown: {}", exc)

        # 3) 最后兜底：复刻用户手法（多次 ArrowDown + 回车）
        try:
            for _ in range(20):
                await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
        except Exception:
            pass

    async def _editor_text(self, page: Page) -> str:
        """读取编辑器当前 markdown 文本。

        CodeMirror5 真实源码只在实例 .getValue() 里；DOM .CodeMirror-code 因虚拟滚动只
        渲染可视行（长文读不全）。优先 CM 实例 API，再回退 innerText。
        """
        try:
            return str(
                await page.evaluate(
                    """() => {
                        const holders = Array.from(document.querySelectorAll('.CodeMirror'));
                        for (const el of holders) {
                            const cm = el.CodeMirror
                                || (el.querySelector && el.querySelector('.CodeMirror') && el.querySelector('.CodeMirror').CodeMirror);
                            if (cm && typeof cm.getValue === 'function') {
                                const v = cm.getValue();
                                if (v) return v;
                            }
                        }
                        const code = document.querySelector('.CodeMirror-code');
                        if (code && (code.innerText || code.textContent)) {
                            return code.innerText || code.textContent;
                        }
                        const ta = document.querySelector('.CodeMirror textarea');
                        if (ta && ta.value) return ta.value;
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
        """等待编辑器 markdown 图片数超过 before_count（覆盖上传网络耗时，最长 ~20s）。"""
        for _ in range(40):
            if self._count_markdown_images(await self._editor_text(page)) > before_count:
                await self._wait_upload_settle(page)
                return True
            await asyncio.sleep(0.5)
        return False

    async def _find_editor(self, page: Page) -> Locator | None:
        candidates = [
            page.locator(".CodeMirror").first,
            page.locator(".CodeMirror-scroll").first,
            page.locator(".bytemd-editor .CodeMirror").first,
            page.locator('[contenteditable="true"]').first,
        ]
        for candidate in candidates:
            if await self._is_visible(candidate, timeout=1500):
                box = await candidate.bounding_box()
                if box and box.get("width", 0) > 120 and box.get("height", 0) > 60:
                    return candidate
        return None

    # ------------------------------------------------------------------ 发布弹窗

    async def _click_publish(self, page: Page, article: Any, image_paths: list[str] | None = None) -> bool:
        await self._dismiss_common_popups(page)

        # 兜底护栏：任何时候误触发原生文件选择器（如误点「上传封面」），都自动关闭，
        # 绝不让原生弹窗把整个发布流程卡死（用户实测正是被此卡住）。封面上传另有专门逻辑，
        # 走 expect_file_chooser 精确处理时会临时置 _cover_upload_active，让本兜底让位。
        self._cover_upload_active = False
        page.on("filechooser", lambda fc: asyncio.create_task(self._dismiss_stray_file_chooser(fc)))

        # 1) 点「发布」打开发布弹窗
        publish_btn = None
        for candidate in [
            page.get_by_role("button", name=re.compile("^发布$|发布文章|立即发布")).last,
            page.locator('button:has-text("发布")').last,
            page.get_by_text("发布", exact=True).last,
        ]:
            if await self._is_visible(candidate, timeout=2500):
                publish_btn = candidate
                break
        if publish_btn is None:
            logger.warning("[掘金] 未找到「发布」按钮")
            return False
        try:
            await publish_btn.click(force=True)
        except Exception as exc:
            logger.warning("[掘金] 点击发布按钮失败: {}", exc)
            return False
        await asyncio.sleep(1.5)  # 等发布弹窗渲染

        # 2) 选分类（必填）——未选中时禁止继续发布
        if not await self._select_category(page, article):
            logger.warning("[掘金] 固定分类「{}」选择失败，停止发布", self.DEFAULT_CATEGORY)
            return False

        # 3) 加标签（必填）——未确认标签胶囊时禁止继续发布
        if not await self._select_tag(page, article):
            logger.warning("[掘金] 固定标签「{}」添加失败，停止发布", self.DEFAULT_TAG)
            return False

        # 4) 上传封面（用文章第一张图；封面非必填，失败不阻断发布）
        await self._upload_cover(page, image_paths[0] if image_paths else None)

        # 5) 点「确定并发布」
        if await self._click_confirm_publish(page):
            return True
        logger.warning("[掘金] 未找到「确定并发布」按钮")
        return False

    async def _click_confirm_publish(self, page: Page) -> bool:
        """点击发布弹窗的「确定并发布」按钮，带滚动、JS 兜底和多候选选择器。

        用户实测曾卡在此步骤：弹窗内容长、按钮在可视区底部时 Playwright 的 click(force=True)
        可能点不到真实按钮。因此增加「滚动到视口 → 常规点击 → JS 兜底点击」三层保障。
        """
        # 先等弹窗稳定：用最有代表性的文案轮询，最多等 8s
        for _ in range(16):
            has_dialog = await page.evaluate(
                """() => !!Array.from(document.querySelectorAll('button, span, div, a'))
                    .find(el => /确定并发布|确认并发布|确定发布/.test((el.textContent || '').trim()))"""
            )
            if has_dialog:
                break
            await asyncio.sleep(0.5)

        candidates = [
            page.get_by_role("button", name=re.compile("确定并发布|确认并发布|确定发布")).last,
            page.locator('button:has-text("确定并发布"), button:has-text("确认并发布"), button:has-text("确定发布")').last,
            page.locator('div[role="button"]:has-text("确定并发布"), div[role="button"]:has-text("确认并发布")').last,
            page.locator('[role="button"]:has-text("确定并发布"), [role="button"]:has-text("确认并发布")').last,
            page.get_by_text("确定并发布", exact=True).last,
        ]

        for candidate in candidates:
            if not await self._is_visible(candidate, timeout=3000):
                continue
            try:
                await candidate.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await candidate.click(force=True)
                await asyncio.sleep(1.0)
                logger.info("[掘金] 已点击确定并发布")
                return True
            except Exception as exc:
                logger.warning("[掘金] Playwright 点击确定并发布失败: {}", exc)

            # JS 兜底：直接调用元素 click()，绕过 actionability 与遮挡检查
            try:
                await candidate.evaluate("el => el.click()")
                await asyncio.sleep(1.0)
                logger.info("[掘金] 已使用 JS 兜底点击确定并发布")
                return True
            except Exception as exc:
                logger.debug("[掘金] JS 兜底点击失败: {}", exc)

        return False

    async def _upload_cover(self, page: Page, image_path: str | None) -> bool:
        """上传文章封面 = 文章第一张图（用户要求）。封面非必填，失败只告警不阻断。

        首选：直接给封面区的隐藏 <input type=file> set_input_files —— 不触发原生对话框、最稳，
        也不会像“点上传封面文字”那样因未触发 filechooser 而干等 6s 超时。
        兜底：点入口 + expect_file_chooser 捕获原生弹窗（缩短超时，快速失败）。
        """
        if not image_path or not os.path.exists(image_path):
            logger.info("[掘金] 无可用封面图，跳过封面上传（封面非必填）")
            return False

        # 首选：定位封面区隐藏 file input 直传（JS 标记离「文章封面/上传封面」最近的 input[type=file]）
        try:
            marked = bool(await page.evaluate(
                """() => {
                    document.querySelectorAll('[data-autogeo-juejin-cover]')
                        .forEach(el => el.removeAttribute('data-autogeo-juejin-cover'));
                    let ly = null;
                    for (const el of document.querySelectorAll('label, span, div, p')) {
                        const t = (el.textContent || '').trim();
                        if (t.length <= 8 && (/文章封面|上传封面|封面$/.test(t))) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) { ly = r.top; break; }
                        }
                    }
                    const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
                    if (!inputs.length) return false;
                    let best = inputs[0], bestDy = 1e9;
                    if (ly !== null) {
                        for (const el of inputs) {
                            const r = el.getBoundingClientRect();
                            const dy = Math.abs((r.top || 0) - ly);
                            if (dy < bestDy) { bestDy = dy; best = el; }
                        }
                    } else {
                        best = inputs[inputs.length - 1];  // 无标签时取最后一个（发布弹窗里通常是封面）
                    }
                    best.setAttribute('data-autogeo-juejin-cover', '1');
                    return true;
                }"""
            ))
            if marked:
                await page.locator('[data-autogeo-juejin-cover="1"]').set_input_files(image_path)
                await asyncio.sleep(1.5)
                await self._confirm_cover_crop(page)
                logger.info("[掘金] 已上传封面（文章首图，input 直传）: {}", Path(image_path).name)
                return True
        except Exception as exc:
            logger.debug("[掘金] 封面 input 直传失败，改用 file_chooser: {}", exc)

        # 兜底：点入口 + expect_file_chooser
        cover_entry = None
        for candidate in [
            page.get_by_text("上传封面", exact=False).first,
            page.locator('[class*="cover"] [class*="upload"], [class*="upload"][class*="cover"]').first,
        ]:
            if await self._is_visible(candidate, timeout=1200):
                cover_entry = candidate
                break
        if cover_entry is None:
            logger.info("[掘金] 未找到封面上传入口，跳过（封面非必填）")
            return False

        self._cover_upload_active = True
        try:
            async with page.expect_file_chooser(timeout=4000) as fc_info:
                await cover_entry.click(force=True)
            chooser = await fc_info.value
            await chooser.set_files(image_path)
            await asyncio.sleep(1.5)
            await self._confirm_cover_crop(page)
            logger.info("[掘金] 已上传封面（文章首图，file_chooser）: {}", Path(image_path).name)
            return True
        except Exception as exc:
            logger.warning("[掘金] 封面上传失败（不阻断发布，封面非必填）: {}", exc)
            return False
        finally:
            self._cover_upload_active = False

    async def _confirm_cover_crop(self, page: Page) -> bool:
        """封面上传后若弹裁剪/确认框，点确认；无弹窗则忽略。"""
        for text in ("确定", "确认", "完成", "保存", "裁剪"):
            button = page.get_by_role("button", name=re.compile(text)).last
            if await self._is_visible(button, timeout=800):
                try:
                    await button.click(force=True)
                    await asyncio.sleep(0.5)
                    return True
                except Exception:
                    continue
        return False

    async def _dismiss_stray_file_chooser(self, file_chooser) -> None:
        """兜底关闭意外触发的原生文件选择器：塞一个空列表让它立即关闭，避免卡死。

        注意：封面上传时会置 _cover_upload_active=True，此时让位给专门的 expect_file_chooser，
        本兜底不动手；只兜住「非预期」的文件选择器（如误点到某个隐藏上传入口）。
        """
        if getattr(self, "_cover_upload_active", False):
            return
        try:
            await file_chooser.set_files([])
            logger.warning("[掘金] 检测到非预期的文件选择器，已自动关闭以防卡死")
        except Exception:
            pass

    async def _select_category(self, page: Page, _article: Any) -> bool:
        """选择固定分类「阅读」，不使用文章分类、行业或关键词。"""
        chip = page.get_by_text(self.DEFAULT_CATEGORY, exact=True).first
        if not await self._is_visible(chip, timeout=2000):
            logger.warning("[掘金] 未找到固定分类: {}", self.DEFAULT_CATEGORY)
            return False
        try:
            await chip.click(force=True)
            await asyncio.sleep(0.4)
            logger.info("[掘金] 已选分类: {}", self.DEFAULT_CATEGORY)
            return True
        except Exception as exc:
            logger.warning("[掘金] 固定分类「{}」点击失败: {}", self.DEFAULT_CATEGORY, exc)
            return False

    async def _select_tag(self, page: Page, _article: Any) -> bool:
        """只添加固定标签 SaaS，不使用文章行业、关键词或标题生成候选标签。"""
        return await self._add_tag(page, self.DEFAULT_TAG)

    async def _add_tag(self, page: Page, tag: str) -> bool:
        """把固定标签写进「添加标签」并提交：清空 → 键入 → 回车。

        - SaaS 是掘金已有标签，输入后按一次回车选择。
        - 定位输入框对「有残留文本/旧标签致占位符消失」健壮（见 _find_tag_input）。
        - 只以标签胶囊出现为成功标准，避免输入文字存在但实际未选中的假成功。
        """
        tag_input = await self._find_tag_input(page)
        if tag_input is None:
            logger.warning("[掘金] 未定位到标签输入框，放弃本次以免误写其它字段")
            return False

        # 硬护栏：确认目标不是 textarea（编辑摘要）
        try:
            tag_name = str(await tag_input.evaluate("el => (el.tagName || '').toLowerCase()"))
        except Exception:
            tag_name = ""
        if tag_name == "textarea":
            logger.warning("[掘金] 标签目标疑似 textarea（编辑摘要），放弃键入以保护摘要")
            return False

        try:
            await tag_input.click(force=True)
            await self._clear_tag_input(page, tag_input)
            await page.keyboard.type(tag, delay=40)
            await asyncio.sleep(0.8)
        except Exception as exc:
            logger.warning("[掘金] 标签键入失败: {}", exc)
            return False

        try:
            await page.keyboard.press("Enter")
        except Exception as exc:
            logger.warning("[掘金] 标签「{}」回车提交失败: {}", tag, exc)
            return False
        await asyncio.sleep(0.8)
        if await self._tag_chip_exists(page, tag):
            logger.info("[掘金] 已添加标签: {}", tag)
            return True

        # 本候选没成：清掉残留文本，避免堵住下一个候选的定位/键入。
        # 注意：不按 Escape——在标签输入框按 Escape 可能连整个发布弹窗一起关掉。
        try:
            await self._clear_tag_input(page, tag_input)
        except Exception:
            pass
        logger.warning("[掘金] 标签「{}」回车后未形成标签胶囊", tag)
        return False

    async def _clear_tag_input(self, page: Page, tag_input: Locator) -> None:
        """清空标签输入框内尚未提交的文本。"""
        try:
            await tag_input.click(force=True)
        except Exception:
            pass
        try:
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.press("Delete")
        except Exception:
            pass

    async def _find_tag_input(self, page: Page) -> Locator | None:
        """定位「添加标签」输入框——对「有残留文本/已有标签致占位符消失」健壮。

        锚点用三种（任一）：标签占位符「请搜索添加标签」、「还能添加 N 个标签」计数、「添加标签」标签。
        在锚点纵向附近找可见的 input/contenteditable（排除 textarea=编辑摘要），dy 放宽到 220，
        兼容输入框因长文本换行变高/位移的情况。定位不到返回 None，绝不乱写其它字段。
        """
        # 先试占位符/属性直连（空标签字段时最快）
        for candidate in [
            page.get_by_placeholder(re.compile("添加标签")).first,
            page.locator('input[placeholder*="标签"]').first,
        ]:
            if await self._is_visible(candidate, timeout=600):
                return candidate

        try:
            marked = bool(await page.evaluate(
                """() => {
                    document.querySelectorAll('[data-autogeo-juejin-taginput]')
                        .forEach(el => el.removeAttribute('data-autogeo-juejin-taginput'));
                    const anchorRe = /(请搜索添加标签|还能添加\\s*\\d+\\s*个?标签|^\\*?\\s*添加标签)/;
                    let ay = null;
                    for (const el of document.querySelectorAll('label, span, div, p, i')) {
                        const t = (el.textContent || '').trim();
                        if (t.length <= 14 && anchorRe.test(t)) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) { ay = r.top; break; }
                        }
                    }
                    if (ay === null) return false;
                    let best = null, bestDy = 1e9;
                    for (const el of document.querySelectorAll('input, [contenteditable="true"]')) {
                        if ((el.tagName || '').toLowerCase() === 'textarea') continue;
                        const ph = (el.getAttribute && (el.getAttribute('placeholder') || '')) || '';
                        if (/摘要/.test(ph)) continue;  // 明确排除编辑摘要
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        if (r.width < 40 || r.height < 8 || s.display === 'none' || s.visibility === 'hidden') continue;
                        const dy = Math.abs(r.top - ay);
                        if (dy < bestDy) { bestDy = dy; best = el; }
                    }
                    if (best && bestDy < 220) {
                        best.setAttribute('data-autogeo-juejin-taginput', '1');
                        return true;
                    }
                    return false;
                }"""
            ))
        except Exception:
            marked = False
        return page.locator('[data-autogeo-juejin-taginput="1"]').first if marked else None

    async def _tag_chip_exists(self, page: Page, tag: str) -> bool:
        """校验「添加标签」行附近是否已出现文本等于该标签的胶囊（排除别行的分类 chip）。"""
        try:
            return bool(await page.evaluate(
                """(tag) => {
                    const norm = s => (s || '').replace(/\\s+/g, '').replace(/[×✕╳✖xX]/g, '');
                    const t = norm(tag);
                    if (!t) return false;
                    // 锚点：标签行 label（兼容「* 添加标签：」带星号/冒号）或占位符/计数
                    const anchorRe = /(请搜索添加标签|还能添加\\s*\\d+\\s*个?标签|添加标签)/;
                    let ly = null;
                    for (const el of document.querySelectorAll('label, span, div, p, i')) {
                        const tx = (el.textContent || '').trim();
                        if (tx.length <= 14 && anchorRe.test(tx)) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) { ly = r.top; break; }
                        }
                    }
                    for (const el of document.querySelectorAll('span, div, li, a')) {
                        if (norm(el.textContent) !== t) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width <= 0 || r.height <= 0 || r.width > 260) continue;
                        // 标签胶囊只会在「添加标签」label 同排或其下方；分类 chip 在其上方，须排除
                        // （否则默认标签「人工智能」会因上方同名的分类 chip 而误判成功）。
                        if (ly !== null && (r.top < ly - 30 || r.top > ly + 140)) continue;
                        return true;
                    }
                    return false;
                }""",
                tag,
            ))
        except Exception:
            return False

    # ------------------------------------------------------------------ 结果

    async def _wait_for_result(self, page: Page) -> Dict[str, Any]:
        """等待发布结果，最长120秒（60次×2秒）。"""
        for _ in range(60):
            manual_msg = await self._detect_manual_checkpoint(page)
            if manual_msg:
                return await self._manual_fail(page, "wait_result", manual_msg)

            current_url = page.url or ""
            if re.search(r"juejin\.cn/post/\d+", current_url):
                logger.success("[掘金] 发布成功: {}", current_url)
                return {"success": True, "platform_url": current_url, "error_msg": None}

            for text in ("发布成功", "审核中", "已发布", "发布完成"):
                node = page.get_by_text(text, exact=False).first
                if await self._is_visible(node, timeout=300):
                    logger.success("[掘金] 检测到成功提示: {}", text)
                    return {"success": True, "platform_url": current_url, "error_msg": None}

            for text in ("发布失败", "标题不能为空", "请选择分类", "请添加标签", "请选择标签",
                         "至少添加一个标签", "标签不能为空", "内容不能为空", "操作频繁", "内容违规"):
                node = page.get_by_text(text, exact=False).first
                if await self._is_visible(node, timeout=300):
                    message = (await node.inner_text()).strip() or text
                    return await self._fail(page, "wait_result", message)

            await asyncio.sleep(2)

        return await self._fail(page, "wait_result", "发布结果未确认，请到掘金后台人工确认（已等待120秒）")

    # ------------------------------------------------------------------ 通用

    async def _verify_written(self, page: Page, title: str, content: str) -> bool:
        """校验标题/正文确已写入——宽松策略：标题在 或 首段在 即通过，两者都读不到才判失败。"""
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
            if not needle:
                return bool(title_ok)
            if title_ok or content_ok:
                return True
            logger.warning(
                "[掘金] verify 未读到标题也未读到首段（title_ok={} content_ok={}），判失败",
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
        if any(part in url for part in ("/login", "passport", "captcha", "verify")):
            return "掘金进入登录或安全验证页面，请重新授权后再发布"

        checks = [
            ("扫码登录", "掘金需要扫码登录，请重新授权后再发布"),
            ("验证码", "掘金需要验证码验证，请人工完成后再发布"),
            ("安全验证", "掘金需要安全验证，请人工完成后再发布"),
            ("操作频繁", "掘金提示操作频繁，请稍后重试"),
            ("请先登录", "掘金账号未登录，请重新授权后再发布"),
        ]
        for text, message in checks:
            node = page.get_by_text(text, exact=False).first
            if await self._is_visible(node, timeout=300):
                return message
        return None

    async def _dismiss_common_popups(self, page: Page) -> None:
        for _ in range(2):
            for text in ("知道了", "我知道了", "关闭", "跳过", "确定", "以后再说", "不用了", "取消"):
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
        logger.error("[掘金] stage={} 失败: {}", stage, message)
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
        debug_dir = Path("backend/debug/juejin")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stage = re.sub(r"[^A-Za-z0-9_-]+", "_", stage)
        html_path = debug_dir / f"{safe_stage}_{stamp}.html"
        png_path = debug_dir / f"{safe_stage}_{stamp}.png"
        try:
            html_path.write_text(await page.content(), encoding="utf-8")
        except Exception as exc:
            logger.warning("[掘金] 保存 HTML 调试快照失败: {}", exc)
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception as exc:
            logger.warning("[掘金] 保存截图失败: {}", exc)
        return str(html_path)

    async def _log_editables(self, page: Page) -> None:
        try:
            info = await page.evaluate(
                """() => Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], .CodeMirror'))
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
            logger.warning("[掘金] 可编辑元素调试信息: {}", info)
        except Exception:
            pass

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"[#*`\"<>]", "", title or "").strip()
        return cleaned[: self.MAX_TITLE_LENGTH] or "未命名文章"


JuejinPublisher = JuejinProPublisher


JUEJIN_CONFIG = {
    "name": "掘金",
    "publish_url": JuejinProPublisher.EDITOR_URL,
    "color": "#1E80FF",
    "version": "pro-codegen",
}
registry.register("juejin", JuejinProPublisher("juejin", JUEJIN_CONFIG))
