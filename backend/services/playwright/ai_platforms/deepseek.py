# -*- coding: utf-8 -*-
"""
DeepSeek checker.

This keeps the successful capture strategy from the earlier working version:
submit the question, confirm the current question appears in the page, wait for
content changes, then extract the answer after the current question. The final
text is cleaned to remove DeepSeek web-search citation noise.
"""

import asyncio
from typing import Any, Dict

from playwright.async_api import Page

from .base import AIPlatformChecker


class DeepSeekChecker(AIPlatformChecker):
    """DeepSeek checker."""

    SELECTORS = {
        "input_box": [
            "textarea[id='chat-input']",
            "textarea[placeholder*='Message']",
            "textarea[placeholder*='DeepSeek']",
            "textarea[placeholder*='输入']",
            "textarea",
            "[contenteditable='true']",
        ],
        # `ds-button` 是全站通用类，不能作为全局发送选择器，会误点侧栏搜索。
        "submit_button": ["button[type='submit']", "[class*='send-button']"],
        "new_chat": ["div[class*='new-chat']", "[class*='new-chat']"],
    }

    async def navigate_to_page(self, page: Page) -> bool:
        try:
            url = "https://chat.deepseek.com"
            self._log("info", f"正在导航到DeepSeek页面: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            try:
                indicators = ["textarea[placeholder*='输入']", "[class*='login']", "button:has-text('登录')"]
                await self.wait_for_selector(page, indicators, timeout=10000)
            except Exception:
                pass

            login_indicators = ["[class*='login']", "button:has-text('登录')", "[class*='auth']"]
            has_login = False
            for indicator in login_indicators:
                try:
                    element = await page.query_selector(indicator)
                    if element and await element.is_visible():
                        has_login = True
                        break
                except Exception:
                    continue

            if has_login:
                self._log("info", "检测到登录页面，请手动完成登录")
                await asyncio.sleep(90)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)

            return True
        except Exception as exc:
            self._log("error", f"DeepSeek导航失败: {exc}")
            return False

    async def get_answer_content(self, page: Page, question: str) -> Dict[str, Any]:
        self._log("info", "使用DeepSeek专用逻辑获取回答")

        body_text = ""
        try:
            body_text = await page.inner_text("body")
        except Exception:
            body_text = ""

        current_answer = self._extract_answer_after_question(body_text, question)
        if self._looks_like_current_answer(current_answer, question):
            return {
                "success": True,
                "answer": current_answer[:5000],
                "selector": "body-after-current-question",
                "length": len(current_answer),
            }

        deepseek_selectors = [
            "[class*='ds-message']",
            "[class*='chat-response']",
            "[class*='assistant-message']",
            "[class*='markdown']",
        ]
        for selector in deepseek_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in reversed(elements):
                    text = await element.inner_text()
                    text = self._extract_answer_after_question(text, question)
                    if self._looks_like_current_answer(text, question):
                        return {
                            "success": True,
                            "answer": text[:5000],
                            "selector": selector,
                            "length": len(text),
                        }
            except Exception:
                continue

        self._log("warning", "DeepSeek未能定位到本次问题后的AI回答，拒绝使用历史/侧栏文本")
        return {"success": False, "answer": "", "selector": None, "length": 0}

    def _extract_answer_after_question(self, text: str, question: str) -> str:
        text = (text or "").strip()
        question = (question or "").strip()
        if not text:
            return ""
        if question:
            question_end_index = self._find_question_end_index(text, question)
            if question_end_index < 0:
                return ""
            text = text[question_end_index:]
        return self._clean_deepseek_answer(text, question)

    @staticmethod
    def _find_question_end_index(text: str, question: str) -> int:
        exact_index = text.rfind(question)
        if exact_index >= 0:
            return exact_index + len(question)

        compact_chars = []
        index_map = []
        for index, char in enumerate(text):
            if char.isspace():
                continue
            compact_chars.append(char)
            index_map.append(index)

        compact_text = "".join(compact_chars)
        compact_question = "".join(char for char in question if not char.isspace())
        if not compact_text or not compact_question:
            return -1

        compact_index = compact_text.rfind(compact_question)
        if compact_index < 0:
            return -1

        compact_end_index = compact_index + len(compact_question) - 1
        if compact_end_index >= len(index_map):
            return -1
        return index_map[compact_end_index] + 1

    async def _wait_for_current_question_visible(self, page: Page, question: str, timeout_ms: int = 10000) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            try:
                body_text = await page.inner_text("body")
                if self._find_question_end_index(body_text, question) >= 0:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    @staticmethod
    def _clean_deepseek_answer(text: str, question: str = "") -> str:
        ignored_exact = {
            "开启新对话",
            "新对话",
            "暂无历史对话",
            "快速模式",
            "专家模式",
            "识图模式",
            "深度思考",
            "智能搜索",
            "复制",
            "重新生成",
            "点赞",
            "点踩",
            "分享",
            "停止生成",
            "登录",
            "注册",
        }
        ignored_contains = (
            "内容由 AI 生成",
            "使用快速模式开始对话",
        )

        lines = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if question and line == question:
                continue
            if line in ignored_exact:
                continue
            if any(token in line for token in ignored_contains):
                continue
            if line.startswith("已阅读") and line.endswith("个网页"):
                continue
            if line.isdigit():
                continue
            if all(char in "-–—·•。." for char in line):
                continue

            # DeepSeek web-search citations often leave dangling hyphens after
            # the sentence when extracted via innerText.
            if line.endswith("-"):
                line = line[:-1].rstrip()
            lines.append(line)

        return "\n".join(lines).strip()

    @staticmethod
    def _looks_like_current_answer(text: str, question: str = "") -> bool:
        text = (text or "").strip()
        if len(text) < 30:
            return False
        if question and text == question.strip():
            return False
        history_markers = (
            "Correcting Python Tensor Reshaping Syntax",
            "def InfoNCE",
            "import pandas as pd",
            "Kaggle",
            "GRU4Rec",
            "Caser",
        )
        return not any(marker in text for marker in history_markers)

    async def check(self, page: Page, question: str, keyword: str, company: str) -> Dict[str, Any]:
        self._log("info", f"开始检测, 问题: {question[:50]}...")
        self._log("info", f"目标关键词: {keyword}, 公司: {company}")

        try:

            async def navigate_operation():
                if await self.navigate_to_page(page):
                    return {"success": True}
                return {"success": False, "error_msg": "导航失败"}

            nav_result = await self._retry_operation(navigate_operation, "导航到DeepSeek", max_retries=2)
            if not nav_result["success"]:
                return {
                    "success": False,
                    "answer": None,
                    "keyword_found": False,
                    "company_found": False,
                    "error_msg": nav_result.get("error_msg", "导航失败"),
                }

            async def clear_operation():
                if await self.clear_chat_history(page):
                    return {"success": True}
                return {"success": False, "error_msg": "清理失败"}

            await self._retry_operation(clear_operation, "清理聊天历史", max_retries=1)

            await self.dismiss_obstructive_popups(page)
            success, matched_selector = await self.wait_for_selector(page, self.SELECTORS["input_box"], timeout=20000)
            if not success:
                self._log("error", "未找到输入框")
                return {
                    "success": False,
                    "answer": None,
                    "keyword_found": False,
                    "company_found": False,
                    "error_msg": "输入框未找到",
                }

            self._log("info", f"找到输入框: {matched_selector}")

            await self.dismiss_obstructive_popups(page)
            submitted = await self.submit_question(
                page=page,
                question=question,
                input_selector=matched_selector,
                submit_button_selector=None,
            )
            if not submitted:
                return {
                    "success": False,
                    "answer": None,
                    "keyword_found": False,
                    "company_found": False,
                    "error_msg": "问题提交失败，未进入回答等待阶段",
                }

            if not await self._wait_for_current_question_visible(page, question):
                return {
                    "success": False,
                    "answer": None,
                    "keyword_found": False,
                    "company_found": False,
                    "error_msg": "DeepSeek未确认收到本次问题，页面仍停留在历史/首页内容",
                }

            self._log("info", "已提交问题")
            initial_content = await page.inner_text("body")
            wait_result = await self.wait_for_answer_generation(
                page,
                initial_content,
                timeout=60000,
                check_interval=2.0,
            )

            if wait_result["success"]:
                self._log("info", f"回答生成成功, 长度: {wait_result['content_length']} 字符")
            else:
                self._log("warning", f"回答生成未完成, 长度: {wait_result.get('content_length', 0)} 字符")

            await self.dismiss_obstructive_popups(page)
            answer_result = await self.get_answer_content(page, question)
            answer_text = answer_result.get("answer", "")
            if not answer_text.strip():
                return {
                    "success": False,
                    "answer": None,
                    "keyword_found": False,
                    "company_found": False,
                    "error_msg": "未能获取到本次DeepSeek回答",
                    "wait_info": wait_result,
                }

            check_result = self.check_keywords_in_text(answer_text, keyword, company)
            operation_logs = self.get_operation_log()

            return {
                "success": True,
                "answer": answer_text[:5000],
                "keyword_found": check_result["keyword_found"],
                "company_found": check_result["company_found"],
                "keyword_count": check_result.get("keyword_count", 0),
                "company_count": check_result.get("company_count", 0),
                "confidence": check_result.get("confidence", 0.0),
                "answer_length": len(answer_text),
                "wait_info": wait_result,
                "answer_selector": answer_result.get("selector"),
                "operation_logs": operation_logs,
                "error_msg": None,
            }

        except Exception as exc:
            self._log("error", f"检测过程中发生异常: {exc}")
            return {
                "success": False,
                "answer": None,
                "keyword_found": False,
                "company_found": False,
                "error_msg": str(exc),
            }
