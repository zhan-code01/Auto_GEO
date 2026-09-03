# -*- coding: utf-8 -*-
"""
AI平台检测器基类
用这个抽象基类定义检测器的统一接口！
"""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Dict, Any, List, Optional
from playwright.async_api import Page, Response
from loguru import logger
import asyncio
import json
import re
import time
import random


class AIPlatformChecker(ABC):
    """
    AI平台检测器基类

    注意：所有AI平台检测器都要继承这个类！
    """

    def __init__(self, platform_id: str, config: Dict[str, Any]):
        """
        初始化检测器

        Args:
            platform_id: 平台ID
            config: 平台配置
        """
        self.platform_id = platform_id
        self.config = config
        self.name = config.get("name", platform_id)
        self.url = config.get("url", "")
        self.color = config.get("color", "#333333")
        self.retry_count = 3
        self.retry_delay = 2
        self.operation_log = []

    def _log(self, level: str, message: str, **kwargs):
        """
        增强的日志记录方法

        Args:
            level: 日志级别 (info, warning, error, debug)
            message: 日志消息
            **kwargs: 额外的上下文信息
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {"timestamp": timestamp, "platform": self.name, "level": level, "message": message, **kwargs}
        self.operation_log.append(log_entry)

        if level == "info":
            logger.info(f"[{self.name}] {message}")
        elif level == "warning":
            logger.warning(f"[{self.name}] {message}")
        elif level == "error":
            logger.error(f"[{self.name}] {message}")
        elif level == "debug":
            logger.debug(f"[{self.name}] {message}")

    async def _retry_operation(
        self, operation, operation_name: str, max_retries: int = None, retry_delay: int = None
    ) -> Dict[str, Any]:
        """
        通用重试机制

        Args:
            operation: 异步操作函数
            operation_name: 操作名称（用于日志）
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）

        Returns:
            操作结果
        """
        max_retries = max_retries or self.retry_count
        retry_delay = retry_delay or self.retry_delay

        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                self._log("info", f"开始执行: {operation_name} (尝试 {attempt}/{max_retries})")
                result = await operation()

                if result.get("success"):
                    self._log("info", f"操作成功: {operation_name}")
                    return result
                else:
                    error_msg = result.get("error_msg", "未知错误")
                    self._log("warning", f"操作失败: {operation_name}, 错误: {error_msg}")

                    if attempt < max_retries:
                        delay = retry_delay + random.uniform(0, 1)
                        self._log("info", f"等待 {delay:.2f} 秒后进行第 {attempt + 1} 次重试")
                        await asyncio.sleep(delay)
                    else:
                        self._log("error", f"操作最终失败: {operation_name}, 错误: {error_msg}")
                        return result

            except Exception as e:
                last_error = str(e)
                self._log("error", f"操作异常: {operation_name}, 错误: {e}")

                if attempt < max_retries:
                    delay = retry_delay + random.uniform(0, 1)
                    self._log("info", f"等待 {delay:.2f} 秒后进行第 {attempt + 1} 次重试")
                    await asyncio.sleep(delay)

        return {"success": False, "error_msg": last_error or f"操作失败，已重试 {max_retries} 次"}

    @abstractmethod
    async def check(self, page: Page, question: str, keyword: str, company: str) -> Dict[str, Any]:
        """
        检测AI平台收录情况

        Args:
            page: Playwright Page对象
            question: 检测使用的问题
            keyword: 目标关键词
            company: 公司名称

        Returns:
            检测结果：
            {
                "success": bool,
                "answer": str,
                "keyword_found": bool,
                "company_found": bool,
                "error_msg": str
            }
        """
        pass

    async def navigate_to_page(self, page: Page) -> bool:
        """
        增强的导航到AI平台页面
        优化：如果已加载 storageState 则跳过登录等待
        """
        try:
            self._log("info", f"正在导航到平台页面: {self.url}")

            await page.goto(
                self.url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # 智能等待关键元素
            try:
                await page.wait_for_selector(
                    "textarea, input[type='text'], [contenteditable='true'], [class*='chat'], [class*='login'], button",
                    timeout=8000,
                    state="visible",
                )
            except Exception:
                pass

            self._log("info", f"页面加载完成: {self.name}")

            # 检查是否已登录（优先检测输入框等登录后元素）
            logged_in_indicators = [
                "textarea[placeholder*='输入']",
                "textarea[placeholder*='Message']",
                "textarea[placeholder*='发消息']",
                "div[contenteditable='true']",
                "[class*='chat-input']",
                "[class*='editor']",
            ]
            for indicator in logged_in_indicators:
                try:
                    el = await page.query_selector(indicator)
                    if el and await el.is_visible():
                        self._log("info", f"已登录，检测到输入框: {indicator}")
                        return True
                except Exception:
                    continue

            # 没检测到输入框 → 检查是否在登录页
            login_indicators = [
                "[class*='login']",
                "[id*='login']",
                "[class*='auth']",
                "[id*='auth']",
                "button:has-text('登录')",
                "button:has-text('Sign in')",
                "text='登录'",
                "text='Sign in'",
            ]

            has_login = False
            for indicator in login_indicators:
                try:
                    # 使用 query_selector 而不是 query_selector_all，并检查可见性
                    element = await page.query_selector(indicator)
                    if element and await element.is_visible():
                        has_login = True
                        break
                except Exception:
                    continue

            if has_login:
                self._log("warning", "检测到登录页面，等待用户登录...")
                # 轮询检测登录完成（最多等 120 秒，每 3 秒检查一次）
                for _wait in range(40):
                    await asyncio.sleep(3)
                    # 检查 URL 是否已跳转
                    cur_url = page.url.lower()
                    if not any(x in cur_url for x in ['login', 'signin', 'sign_in', 'passport']):
                        # URL 跳转了，检查输入框
                        for ind in logged_in_indicators:
                            try:
                                el = await page.query_selector(ind)
                                if el and await el.is_visible():
                                    self._log("info", f"登录成功，检测到输入框: {ind}")
                                    return True
                            except Exception:
                                continue
                self._log("warning", "登录等待超时（120s），继续尝试...")
                await page.wait_for_load_state("domcontentloaded", timeout=30000)

            return True
        except Exception as e:
            self._log("error", f"导航失败: {e}")
            return False

    async def wait_for_selector(self, page: Page, selectors: List[str], timeout: int = 20000) -> tuple:
        """
        增强的智能等待选择器出现（支持多个备选选择器）
        优化：并行等待所有选择器，而不是分批次

        Args:
            page: Playwright Page对象
            selectors: 选择器列表（按优先级排序）
            timeout: 最大等待时间（毫秒）

        Returns:
            (成功标志, 匹配到的选择器)
        """
        start_time = time.time()
        self._log("info", f"等待选择器: {selectors}, 超时时间: {timeout}ms")

        # 增加更多通用选择器
        enhanced_selectors = selectors + [
            "input[type='text']",
            "input[type='textarea']",
            "[contenteditable='true']",
            "[class*='message-input']",
            "[class*='user-input']",
            "[class*='chat-box']",
            "[id*='input']",
            "[name*='input']",
        ]

        # 去重
        unique_selectors = []
        seen = set()
        for s in enhanced_selectors:
            if s not in seen:
                unique_selectors.append(s)
                seen.add(s)

        # 1. 快速检查是否已经存在
        for selector in unique_selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    self._log("info", f"选择器快速匹配成功: {selector}")
                    return True, selector
            except Exception:
                continue

        # 2. 并行等待策略
        # 创建一个复合选择器，用逗号分隔，这样只要任意一个出现就会触发
        # Playwright 支持逗号分隔的选择器列表
        combined_selector = ", ".join(unique_selectors)

        try:
            self._log("debug", "尝试并行等待选择器组合")
            # 等待任意一个选择器出现
            element = await page.wait_for_selector(combined_selector, state="visible", timeout=timeout)

            if element:
                # 找出具体是哪个选择器匹配了（反向查找略复杂，这里只要确认匹配即可）
                # 为了返回具体的selector，我们再次遍历检查哪个是可见的
                for selector in unique_selectors:
                    try:
                        el = await page.query_selector(selector)
                        if el and await el.is_visible():
                            self._log("info", f"选择器匹配成功: {selector}")
                            return True, selector
                    except Exception:
                        continue

                # 如果找不到具体的，就返回组合选择器或第一个
                self._log("info", "选择器组合匹配成功")
                return True, unique_selectors[0]

        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            self._log("warning", f"等待选择器超时或失败: {e}, 耗时: {elapsed_time:.0f}ms")

            # 最后的兜底策略：查找任意可见的 textarea 或 contenteditable
            # 修复：增加更多通用选择器，提高成功率
            try:
                self._log("info", "尝试兜底策略：查找页面上任意可见的输入框")
                fallback_selector = await page.evaluate("""() => {
                    // 辅助函数：获取元素的CSS选择器
                    function getSelector(el) {
                        if (el.id) return '#' + el.id;
                        if (el.className) {
                            const classes = el.className.split(' ').filter(c => c.trim().length > 0);
                            if (classes.length > 0) return el.tagName.toLowerCase() + '.' + classes.join('.');
                        }
                        return el.tagName.toLowerCase();
                    }

                    // 1. 查找所有 textarea
                    const textareas = Array.from(document.querySelectorAll('textarea'));
                    for (const el of textareas) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null) {
                            return getSelector(el);
                        }
                    }

                    // 2. 查找 contenteditable
                    const editables = Array.from(document.querySelectorAll('[contenteditable="true"]'));
                    for (const el of editables) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null) {
                            return getSelector(el);
                        }
                    }

                    // 3. 查找 input[type=text]
                    const textInputs = Array.from(document.querySelectorAll('input[type="text"]'));
                    for (const el of textInputs) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null) {
                            return getSelector(el);
                        }
                    }

                    // 4. 查找带 placeholder 的元素
                    const withPlaceholder = Array.from(document.querySelectorAll('[placeholder*="输入"], [placeholder*="提问"], [placeholder*="发送"]'));
                    for (const el of withPlaceholder) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null) {
                            return getSelector(el);
                        }
                    }

                    return null;
                }""")

                if fallback_selector:
                    self._log("info", f"兜底策略成功，找到输入框: {fallback_selector}")
                    return True, fallback_selector
            except Exception as fallback_e:
                self._log("warning", f"兜底策略失败: {fallback_e}")

            return False, None

        return False, None

    async def wait_for_answer_generation(
        self,
        page: Page,
        initial_content: str,
        selector: str = "body",
        timeout: int = 60000,
        check_interval: float = 1.0,
    ) -> Dict[str, Any]:
        """
        增强的智能等待AI回答生成完成

        Args:
            page: Playwright Page对象
            initial_content: 初始页面内容
            selector: 要监控的选择器
            timeout: 最大等待时间（毫秒）
            check_interval: 检查间隔（秒）

        Returns:
            等待结果信息
        """
        self._log("info", f"开始智能等待回答生成, 超时时间: {timeout}ms")

        start_time = time.time()
        last_content = initial_content
        stable_count = 0
        content_changed = False
        required_stable_checks = 5  # 增加稳定检查次数，防止回答还在生成中就截断
        min_content_length = 100  # 增加最小内容长度要求

        while (time.time() - start_time) < timeout / 1000:
            try:
                current_content = await page.inner_text(selector)

                content_length = len(current_content.strip())

                if content_length > min_content_length and current_content != last_content:
                    self._log("debug", f"检测到内容更新, 长度: {content_length} 字符")

                    stable_count = 0
                    content_changed = True

                    last_content = current_content

                    await asyncio.sleep(check_interval)

                elif content_length > min_content_length and current_content == last_content and content_changed:
                    stable_count += 1
                    self._log("debug", f"内容稳定检查: {stable_count}/{required_stable_checks}")

                    if stable_count >= required_stable_checks:
                        elapsed_time = (time.time() - start_time) * 1000
                        self._log("info", f"回答生成完成, 耗时: {elapsed_time:.0f}ms, 内容长度: {content_length}")

                        return {
                            "success": True,
                            "content_length": content_length,
                            "elapsed_time": elapsed_time,
                            "stable": True,
                            "content_changed": content_changed,
                        }

                    await asyncio.sleep(check_interval)

                else:
                    await asyncio.sleep(check_interval * 0.5)

            except Exception as e:
                self._log("warning", f"等待回答时发生异常: {e}")
                await asyncio.sleep(check_interval)

        elapsed_time = (time.time() - start_time) * 1000
        current_content = await page.inner_text(selector)
        content_length = len(current_content.strip())

        self._log("warning", f"等待回答超时, 耗时: {elapsed_time:.0f}ms, 内容长度: {content_length}")

        return {
            "success": content_length > min_content_length and content_changed,
            "content_length": content_length,
            "elapsed_time": elapsed_time,
            "stable": stable_count >= required_stable_checks,
            "content_changed": content_changed,
        }

    async def wait_for_valid_answer(
        self,
        page: Page,
        question: str,
        extractor: Optional[Callable[[Page, str], Awaitable[Dict[str, Any]]]] = None,
        timeout: int = 60000,
        check_interval: float = 1.0,
        required_stable_checks: int = 3,
    ) -> Dict[str, Any]:
        """Wait until a platform-specific answer candidate appears and becomes stable."""
        self._log("info", f"开始等待有效 AI 回答候选，超时时间: {timeout}ms")
        start_time = time.time()
        stable_count = 0
        last_answer = ""
        last_result: Dict[str, Any] = {}
        answer_extractor = extractor or self.get_answer_content

        while (time.time() - start_time) < timeout / 1000:
            try:
                result = await answer_extractor(page, question)
                candidate = (result.get("answer") or "").strip() if result.get("success") else ""
                quality = self.validate_answer_quality(candidate, question) if candidate else {
                    "valid": False,
                    "reason": "empty candidate",
                }

                if candidate and quality.get("valid"):
                    if candidate == last_answer:
                        stable_count += 1
                    else:
                        last_answer = candidate
                        stable_count = 1

                    last_result = result
                    self._log(
                        "debug",
                        f"有效回答稳定检查: {stable_count}/{required_stable_checks}, 长度: {len(candidate)}",
                    )
                    if stable_count >= required_stable_checks:
                        elapsed_time = (time.time() - start_time) * 1000
                        return {
                            "success": True,
                            "content_length": len(candidate),
                            "elapsed_time": elapsed_time,
                            "stable": True,
                            "answer": candidate,
                            "selector": result.get("selector"),
                            "method": result.get("method") or result.get("selector"),
                            "quality_check": quality,
                        }
                elif candidate:
                    self._log("debug", f"忽略无效回答候选: {quality.get('reason')}")

                await asyncio.sleep(check_interval)
            except Exception as e:
                self._log("debug", f"等待有效回答时轮询失败: {e}")
                await asyncio.sleep(check_interval)

        elapsed_time = (time.time() - start_time) * 1000
        return {
            "success": False,
            "content_length": len(last_answer),
            "elapsed_time": elapsed_time,
            "stable": stable_count >= required_stable_checks,
            "answer": last_answer,
            "selector": last_result.get("selector"),
            "error_msg": "未等待到稳定且有效的 AI 回答",
        }

    async def dismiss_obstructive_popups(self, page: Page) -> bool:
        """Close non-verification popups that block chat content, such as download-app ads."""
        try:
            closed = await page.evaluate(
                """() => {
                    const popupMarkers = [
                        '\\u4e0b\\u8f7d\\u7535\\u8111\\u7248',
                        '\\u4e0b\\u8f7d\\u7535\\u8111\\u7aef',
                        '\\u4e0b\\u8f7d\\u684c\\u9762\\u7248',
                        '\\u8c46\\u5305\\u7535\\u8111\\u7248',
                        '\\u4f7f\\u7528\\u5b8c\\u6574\\u529f\\u80fd',
                        '\\u684c\\u9762\\u52a9\\u624b',
                        '\\u4e0b\\u8f7dAPP',
                        '\\u4e0b\\u8f7d App',
                        '\\u4e0b\\u8f7d\\u5ba2\\u6237\\u7aef'
                    ];
                    const riskMarkers = [
                        '\\u9a8c\\u8bc1\\u7801',
                        '\\u4eba\\u673a\\u9a8c\\u8bc1',
                        '\\u5b89\\u5168\\u9a8c\\u8bc1',
                        '\\u626b\\u7801\\u767b\\u5f55',
                        '\\u8eab\\u4efd\\u9a8c\\u8bc1',
                        '\\u62d6\\u52a8',
                        '\\u6ed1\\u5757'
                    ];
                    const visible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && style.opacity !== '0';
                    };
                    const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    const scopes = Array.from(document.querySelectorAll([
                        '[role="dialog"]',
                        '[class*="modal"]',
                        '[class*="dialog"]',
                        '[class*="popup"]',
                        '[class*="download"]',
                        '[class*="desktop"]',
                        'body > div'
                    ].join(','))).filter(visible);

                    for (const scope of scopes) {
                        const text = textOf(scope);
                        if (!text || !popupMarkers.some(marker => text.includes(marker))) continue;
                        if (riskMarkers.some(marker => text.includes(marker))) continue;

                        const buttons = Array.from(scope.querySelectorAll('button, [role="button"], svg, [aria-label], [class*="close"]'))
                            .filter(visible);
                        const closeButton = buttons.find((el) => {
                            const label = [
                                el.getAttribute && el.getAttribute('aria-label'),
                                el.getAttribute && el.getAttribute('title'),
                                textOf(el)
                            ].filter(Boolean).join(' ');
                            const cls = el.className && String(el.className);
                            return /\\u5173\\u95ed|close|\\u53d6\\u6d88|×|x/i.test(label) || /close/i.test(cls || '');
                        }) || buttons[buttons.length - 1];

                        if (closeButton) {
                            closeButton.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            if closed:
                self._log("info", "closed obstructive download/client popup")
                await asyncio.sleep(0.5)
            return bool(closed)
        except Exception as exc:
            self._log("debug", f"dismiss obstructive popup failed: {exc}")
            return False

    @staticmethod
    def validate_answer_quality(text: str, question: str) -> Dict[str, Any]:
        """
        校验采集到的文本是否为真实的 AI 回答（而非 UI 元素/搜索推荐）

        在存储到数据库和送入 LLM judge 之前调用。

        Returns:
            {"valid": bool, "quality": "good"|"suspicious"|"invalid", "reason": str}
        """
        if not text or not text.strip():
            return {"valid": False, "quality": "invalid", "reason": "回答为空"}

        cleaned = text.strip()

        # ── 1. 排除：就是问题原文 ──
        if cleaned == question.strip():
            return {"valid": False, "quality": "invalid", "reason": "回答等于问题原文"}

        # ── 2. 排除：纯 UI 按钮列表 ──
        ui_button_keywords = [
            "快速", "新", "编程", "帮我写作", "图像生成", "音乐生成",
            "翻译", "更多", "AI 创作", "深度思考", "联网搜索",
            "PPT 生成", "文档处理", "网页摘要", "视频理解", "图片理解",
            "录音笔", "下载", "APP", "手机版", "登录", "注册",
        ]
        lines = [l.strip() for l in cleaned.split("\n") if l.strip()]
        answer_signal_keywords = [
            "核心", "标准", "建议", "推荐", "优势", "原因", "如下", "包括",
            "参考", "搜索", "资料", "公司", "产品", "业务", "场景", "结论",
            "首先", "其次", "最后", "适合", "能力", "方案", "信息", "分析",
        ]
        structure_prefixes = (
            "一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、",
            "1.", "2.", "3.", "4.", "5.", "1、", "2、", "3、", "4、", "5、",
            "（一）", "（二）", "（三）", "(一)", "(二)", "(三)",
        )
        has_answer_signal = any(kw in cleaned for kw in answer_signal_keywords)
        has_structured_answer = any(l.startswith(structure_prefixes) for l in lines)
        has_long_content_line = any(len(l) >= 70 for l in lines)
        has_paragraph_punct = sum(cleaned.count(p) for p in "。，！？；：、,.!?;:") >= 3
        looks_like_real_answer = (
            len(cleaned) >= 180
            and (
                has_long_content_line
                or has_structured_answer
                or (has_answer_signal and has_paragraph_punct)
            )
        )
        if lines:
            ui_line_count = sum(
                1 for l in lines
                if any(l == kw or l.startswith(kw) for kw in ui_button_keywords)
            )
            if ui_line_count >= 3:
                return {
                    "valid": False, "quality": "invalid",
                    "reason": f"疑似UI按钮列表（{ui_line_count}/{len(lines)} 行匹配UI关键词）",
                }

        # ── 3. 排除：搜索推荐/联想query（短行列表，无标点结尾）──
        suggestion_keywords = ["推荐", "指南", "排名", "选型", "哪家好", "怎么选", "厂家"]
        if len(lines) >= 3:
            short_no_punct = sum(
                1 for l in lines
                if len(l) < 50 and not l.endswith(("。", "！", "？", ".", "!", "?"))
            )
            has_suggestion = any(
                any(kw in l for kw in suggestion_keywords) for l in lines[:5]
            )
            if short_no_punct / len(lines) > 0.6 and has_suggestion and not looks_like_real_answer:
                return {
                    "valid": False, "quality": "invalid",
                    "reason": f"疑似搜索推荐列表（{short_no_punct}/{len(lines)} 行为短行无标点，含推荐关键词）",
                }

        # ── 4. 排除：长度异常（太短不像回答，或太长像全页抓取）──
        if len(cleaned) < 30:
            return {"valid": False, "quality": "invalid", "reason": f"回答过短（{len(cleaned)}字）"}
        if len(cleaned) > 8000:
            return {
                "valid": False, "quality": "suspicious",
                "reason": f"回答过长（{len(cleaned)}字），疑似全页抓取",
            }

        # ── 5. 检查自然语言特征（长文本但几乎没有中文标点 → 大概率是列表/菜单）──
        if len(cleaned) > 150:
            chinese_punct = sum(cleaned.count(p) for p in "。，！？；：、")
            if chinese_punct < 2 and not looks_like_real_answer:
                return {
                    "valid": False, "quality": "suspicious",
                    "reason": f"{len(cleaned)}字但中文标点仅{chinese_punct}个，疑似非自然语言",
                }

        # ── 6. 排除：包含用户名/UI 路径等噪声开头 ──
        noise_starts = [
            "本地自动化", "国内工业", "蓝海智造",
        ]
        # 检查前3行是否都是搜索推荐风格（名词短语 + 推荐/指南 + 无标点）
        first_few = lines[:min(4, len(lines))]
        if len(first_few) >= 3:
            noise_pattern_count = sum(
                1 for l in first_few
                if (len(l) < 40 and not l.endswith(("。", "！", "？")))
            )
            if noise_pattern_count == len(first_few) and not looks_like_real_answer:
                return {
                    "valid": False, "quality": "suspicious",
                    "reason": f"前{len(first_few)}行均为短词组（无标点），疑似搜索推荐/菜单",
                }

        return {"valid": True, "quality": "good", "reason": "通过所有校验"}

    # ═══════════════════════════════════════════════════════════
    # 引用来源提取
    # ═══════════════════════════════════════════════════════════

    async def extract_citations_from_page(self, page: Page) -> List[Dict[str, str]]:
        """
        从当前页面提取 AI 回答中的引用来源链接。

        各平台引用区域通常包含“参考”、“来源”、“References”等关键词，
        下方是 <a href> 链接列表。此方法做通用提取，子类可覆盖以适配特定平台。

        Returns:
            [{"url": "...", "domain": "...", "title": "..."}, ...]
        """
        self._log("info", "开始提取引用来源")
        try:
            citations = await page.evaluate("""() => {
                const results = [];

                // ── 1. 查找引用/参考区域 ──
                const citationKeywords = [
                    '参考来源', '参考', '来源', '引用', 'References',
                    'Sources', '参考资料', '信息来源', '相关来源',
                    'search-results', 'reference-list', 'citation'
                ];

                let citationContainer = null;

                // 方式A：通过文本关键词定位引用区域
                const allElements = document.querySelectorAll(
                    'div, section, aside, footer, [class*="reference"], [class*="citation"], [class*="source"]'
                );
                for (const el of allElements) {
                    if (el.offsetParent === null) continue;  // 不可见跳过
                    const text = (el.innerText || '').trim().slice(0, 100);
                    if (text.length < 200 && citationKeywords.some(kw => text.includes(kw))) {
                        // 确认这个区域里有链接
                        const links = el.querySelectorAll('a[href]');
                        if (links.length > 0) {
                            citationContainer = el;
                            break;
                        }
                    }
                }

                // 方式B：通过 class/id 定位引用区域
                if (!citationContainer) {
                    const selectors = [
                        '[class*="reference"]',
                        '[class*="citation"]',
                        '[class*="source"]',
                        '[class*="search-result"]',
                        '[data-testid*="citation"]',
                        '[class*="referred"]',
                        '#references',
                        '#sources',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.offsetParent !== null) {
                            const links = el.querySelectorAll('a[href]');
                            if (links.length > 0) {
                                citationContainer = el;
                                break;
                            }
                        }
                    }
                }

                if (!citationContainer) {
                    // 方式C：在回答区域附近查找链接组
                    const answerArea = document.querySelector(
                        '[class*="message-card"], [class*="answer"], [class*="assistant"], [class*="markdown-body"]'
                    );
                    if (answerArea) {
                        // 在回答区域之后查找
                        let sibling = answerArea.nextElementSibling;
                        let checks = 0;
                        while (sibling && checks < 5) {
                            const links = sibling.querySelectorAll('a[href]');
                            if (links.length >= 1) {
                                const siblingText = (sibling.innerText || '').trim().slice(0, 50);
                                if (citationKeywords.some(kw => siblingText.includes(kw))) {
                                    citationContainer = sibling;
                                    break;
                                }
                            }
                            sibling = sibling.nextElementSibling;
                            checks++;
                        }
                    }
                }

                if (!citationContainer) return results;

                // ── 2. 提取链接 ──
                const links = citationContainer.querySelectorAll('a[href]');
                for (const link of links) {
                    const href = link.href;
                    if (!href || href.startsWith('javascript:') || href.startsWith('#')) continue;
                    const title = (link.innerText || link.title || '').trim();
                    let domain = '';
                    try {
                        domain = new URL(href).hostname;
                    } catch (e) {}
                    results.push({ url: href, domain: domain, title: title });
                }

                return results;
            }""")

            if citations:
                self._log("info", f"提取到 {len(citations)} 条引用来源")
            else:
                self._log("info", "未找到引用来源")

            return citations or []

        except Exception as e:
            self._log("warning", f"提取引用来源失败: {e}")
            return []

    # ═══════════════════════════════════════════════════════════
    # API 响应拦截 — 从网络层直接获取 AI 完整回复
    # ═══════════════════════════════════════════════════════════

    # 各平台的聊天 API URL 匹配规则（子类可覆盖）
    # 注意：豆包用 GET 请求（参数在 query string），通义/DeepSeek 用 POST
    CHAT_API_PATTERNS = [
        # 豆包（GET 请求，参数在 URL 中）
        r"doubao\.com/chat/completion",
        r"doubao\.com/.*chat.*completion",
        r"doubao.*chat",
        # 通义千问
        r"/v1/chat/completions",
        r"/api/knowledge.*chat",     # 通义千问知识库对话
        # DeepSeek
        r"/chat/completion",
        r"/conversation/.*",
        r"/v1.*message",           # DeepSeek 消息 API
        # 通用（放在最后，更严格）
        r"/api/v\d+/chat",
        r"/api/v\d+/completion",
        r"/v\d+/chat.*completions",
    ]

    # 需要排除的 API 路径黑名单（知识库/文件上传等）
    API_BLACKLIST_PATTERNS = [
        r"/upload",
        r"/file",
        r"/document",
        r"/dataset",
        r"/knowledge",              # 排除知识库 API
        r"/rag",
        r"/upload.*file",
        r"/import",
        r"/parse",
        r"/extract",
        r"/embedding",
        r"/index",
        r"/search.*document",
        r"\.(css|js|png|jpg|jpeg|gif|woff|woff2|ico)",  # 静态资源
        r"analytics",
        r"telemetry",
        r"monitor",
        r"health",
    ]

    # 需要排除的响应内容（知识库/系统提示等）
    RESPONSE_BLACKLIST_PATTERNS = [
        "文件数量",
        "文件类型",
        "最多",
        "pdf",
        "txt",
        "csv",
        "docx",
        "doc",
        "xlsx",
        "xls",
        "pptx",
        "ppt",
        "md",
        "mobi",
        "epub",
        "上传文件",
        "知识库",
        "RAG",
    ]

    async def intercept_answer(self, page: Page, timeout_ms: int = 120000,
                              collector: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        通过拦截 API 响应获取 AI 完整回复。

        支持两种调用模式：
        1. 传统模式（collector=None）：自动注册监听器 → 等待 → 清理
        2. 预注册模式（collector 预填）：监听器已由调用方提前注册，此方法只负责等待

        collector 由 _prepare_intercept_collector() 创建，调用方负责：
            page.on("response", collector["handler"])
            try: ... await intercept_answer(page, collector=collector)
            finally: page.remove_listener(...)

        Returns:
            {"success": bool, "answer": str, "method": str}
        """
        if collector is not None:
            # 预注册模式：监听器已由调用方注册，只负责等待
            return await self._wait_for_intercept_chunks(
                collector["chunks"], timeout_ms,
                raw_bodies=collector.get("raw_bodies"),
            )
        else:
            # 传统模式：自行注册 + 等待 + 清理
            collector = self._prepare_intercept_collector()
            page.on("response", collector["handler"])
            try:
                return await self._wait_for_intercept_chunks(
                    collector["chunks"], timeout_ms,
                    raw_bodies=collector.get("raw_bodies"),
                )
            finally:
                page.remove_listener("response", collector["handler"])

    async def race_for_answer(
        self,
        page: Page,
        question: str,
        intercept_collector: Dict[str, Any],
        timeout_ms: int = 15000,
    ) -> Dict[str, Any]:
        """
        并发竞速：同时启动 API 拦截收集和 MutationObserver 轮询，
        谁先拿到有效回答就用谁。

        Args:
            page: Playwright Page
            question: 用户问题
            intercept_collector: API 拦截收集器（已预注册）
            timeout_ms: 最大等待时间

        Returns:
            第一个成功的方案结果
        """
        self._log("info", f"[竞速] 启动并发方案，timeout={timeout_ms}ms")

        async def api_collector():
            """API 拦截收集器（异步轮询 collected_chunks）"""
            start = time.time()
            last_count = 0
            while time.time() - start < timeout_ms / 1000:
                await asyncio.sleep(0.5)
                chunks = intercept_collector.get("chunks", [])
                raw_bodies = intercept_collector.get("raw_bodies", [])
                if len(chunks) > last_count:
                    # 有新数据到达
                    last_count = len(chunks)
                    self._log("info", f"[竞速-API] 已收集 {len(chunks)} 个片段，raw_bodies={len(raw_bodies)}")
                    # 等待一小段时间看是否还有更多数据（流式响应）
                    await asyncio.sleep(1)
                elif chunks:
                    # 已有数据且稳定了
                    break
            if chunks:
                full_text = "\n".join(chunks)
                self._log("info", f"[竞速-API] ✅ 成功获取 {len(full_text)} 字符")
                # 质量验证：检查是否是真的 AI 回答
                quality = self.validate_answer_quality(full_text, question)
                if not quality["valid"]:
                    self._log("warning", f"[竞速-API] 回答质量验证失败: {quality['reason']}")
                    return None
                return {
                    "success": True,
                    "answer": full_text[:10000],
                    "selector": "api-intercept",
                    "length": len(full_text),
                    "method": "api-intercept",
                }
            elif raw_bodies:
                # 有原始响应但解析失败，尝试兜底
                self._log("warning", "[竞速-API] 收集到原始响应但解析失败，尝试兜底")
                fallback_text = self._try_fallback_parsing(raw_bodies)
                if fallback_text:
                    # 质量验证
                    quality = self.validate_answer_quality(fallback_text, question)
                    if not quality["valid"]:
                        self._log("warning", f"[竞速-API] 兜底回答质量验证失败: {quality['reason']}")
                        return None
                    return {
                        "success": True,
                        "answer": fallback_text[:10000],
                        "selector": "api-intercept-fallback",
                        "length": len(fallback_text),
                        "method": "api-intercept-fallback",
                    }
            return None

        async def mutation_tracker():
            """MutationObserver 轮询（异步执行 JS）"""
            try:
                result = await self.track_answer_via_mutation(page, question, timeout_ms=timeout_ms)
                if result and result.get("success"):
                    self._log("info", f"[竞速-Mutation] ✅ 成功获取 {result.get('length', 0)} 字符")
                    return result
                return None
            except Exception as e:
                self._log("warning", f"[竞速-Mutation] 异常: {e}")
                return None

        # 并发执行两个方案（兼容 Python 3.10）
        start_time = time.time()

        async def wait_with_timeout(coro, timeout: float):
            """兼容 Python 3.10 的超时包装"""
            task = asyncio.create_task(coro)
            try:
                while time.time() - start_time < timeout:
                    done, _ = await asyncio.wait([task], timeout=0.1)
                    if done:
                        return task.result()
                    if not task.done():
                        continue
                # 超时，返回 None
                return None
            except Exception:
                return None
            finally:
                if not task.done():
                    task.cancel()

        # 同时启动两个任务
        api_task = asyncio.create_task(api_collector())
        mutation_task = asyncio.create_task(mutation_tracker())

        # 等待其中一个完成或全部超时
        winner = None
        completed_count = 0

        while time.time() - start_time < timeout_ms / 1000:
            done, pending = await asyncio.wait(
                [api_task, mutation_task],
                timeout=0.5,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                completed_count += 1
                try:
                    result = task.result()
                    if result and result.get("success"):
                        winner = result
                        # 找到赢家，取消另一个任务
                        for p in pending:
                            p.cancel()
                        break
                except Exception:
                    pass

            if winner:
                break

            # 如果两个任务都完成了但没有赢家
            if not pending and completed_count == 2 and not winner:
                break

        remaining_time = timeout_ms / 1000 - (time.time() - start_time)
        if not winner and remaining_time > 0:
            # 还有时间，尝试从 raw_bodies 兜底
            raw_bodies = intercept_collector.get("raw_bodies", [])
            if raw_bodies:
                fallback_text = self._try_fallback_parsing(raw_bodies)
                if fallback_text:
                    self._log("info", f"[竞速] 兜底解析成功，获取 {len(fallback_text)} 字符")
                    winner = {
                        "success": True,
                        "answer": fallback_text[:10000],
                        "selector": "api-intercept-fallback",
                        "length": len(fallback_text),
                        "method": "api-intercept-fallback",
                    }

        # 清理：取消未完成的任务
        for task in [api_task, mutation_task]:
            if not task.done():
                task.cancel()

        if winner:
            self._log("info", f"[竞速] 🏆 获胜方案: {winner.get('method')}, 长度={winner.get('length')}")
            return winner

        # 全部失败，返回 MutationObserver 的最终结果（即使不完美）
        self._log("warning", "[竞速] 两个方案都未成功，尝试 MutationObserver 最终结果")
        try:
            final = await self.track_answer_via_mutation(page, question, timeout_ms=5000)
            if final and final.get("length", 0) > 50:
                return {
                    "success": True,
                    "answer": final.get("answer", "")[:10000],
                    "selector": "mutation-final",
                    "length": final.get("length", 0),
                    "method": "mutation-final",
                }
        except Exception:
            pass

        return {"success": False, "answer": "", "selector": None, "length": 0, "method": "none"}

    async def get_message_snapshot(self, page: Page) -> Dict[str, Any]:
        """Capture page state before submitting a question."""
        try:
            return await page.evaluate(
                """() => {
                    const messageSelector = [
                        '[data-role="assistant"]',
                        '[data-testid*="message"]',
                        '[class*="assistant"]',
                        '[class*="bot"]',
                        '[class*="answer"]',
                        '[class*="message"]',
                        '[class*="markdown"]',
                        '[role="article"]'
                    ].join(',');
                    const visible = (el) => {
                        const style = window.getComputedStyle(el);
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && el.offsetParent !== null;
                    };
                    const messages = Array.from(document.querySelectorAll(messageSelector)).filter(visible);
                    return {
                        url: location.href,
                        bodyText: (document.body.innerText || '').trim(),
                        messageCount: messages.length,
                    };
                }"""
            )
        except Exception as e:
            self._log("warning", f"[AnswerCapture] snapshot failed: {e}")
            return {"url": page.url, "bodyText": "", "messageCount": 0}

    async def capture_answer(
        self,
        page: Page,
        question: str,
        before_snapshot: Optional[Dict[str, Any]] = None,
        intercept_collector: Optional[Dict[str, Any]] = None,
        timeout_ms: int = 45000,
        stable_checks: int = 3,
        check_interval_ms: int = 800,
    ) -> Dict[str, Any]:
        """Capture the browser-rendered answer for the current question."""
        before_snapshot = before_snapshot or {}
        before_text = before_snapshot.get("bodyText") or ""
        before_count = int(before_snapshot.get("messageCount") or 0)
        start = time.time()
        last_text = ""
        stable_count = 0
        best_result: Dict[str, Any] = {}

        self._log("info", f"[AnswerCapture] start visible capture, timeout={timeout_ms}ms")

        while time.time() - start < timeout_ms / 1000:
            await asyncio.sleep(check_interval_ms / 1000)
            candidate = await self._extract_visible_answer_candidate(page, question, before_text, before_count)
            text = (candidate.get("answer") or "").strip()
            if not text:
                continue

            quality = self.validate_answer_quality(text, question)
            best_result = {**candidate, "quality_check": quality}
            if not quality["valid"]:
                continue

            if text == last_text:
                stable_count += 1
            else:
                last_text = text
                stable_count = 1

            if stable_count >= stable_checks:
                self._log("info", f"[AnswerCapture] stable method={candidate.get('method')} length={len(text)}")
                return {
                    "success": True,
                    "answer": text[:10000],
                    "selector": candidate.get("selector"),
                    "length": len(text),
                    "method": candidate.get("method"),
                    "quality_check": quality,
                }

        platform_result = await self.extract_platform_answer_capability(page, question)
        if platform_result.get("success"):
            return platform_result

        if intercept_collector is not None:
            self._log("warning", "[AnswerCapture] visible capture failed, trying API fallback")
            api_result = await self.intercept_answer(page, timeout_ms=5000, collector=intercept_collector)
            if api_result.get("success"):
                api_result["selector"] = api_result.get("selector") or "api-intercept-fallback"
                api_result["method"] = api_result.get("method") or "api-intercept-fallback"
                return api_result

        reason = best_result.get("quality_check", {}).get("reason") or "visible answer not found"
        return {
            "success": False,
            "answer": (best_result.get("answer") or "")[:5000],
            "selector": best_result.get("selector"),
            "length": len(best_result.get("answer") or ""),
            "method": "visible-capture-failed",
            "error_msg": reason,
        }

    async def extract_platform_answer_capability(self, page: Page, question: str) -> Dict[str, Any]:
        """Optional platform-specific answer extraction hook."""
        return {"success": False, "answer": "", "selector": None, "length": 0, "method": "unsupported"}

    async def _extract_visible_answer_candidate(
        self,
        page: Page,
        question: str,
        before_text: str,
        before_count: int,
    ) -> Dict[str, Any]:
        return await page.evaluate(
            """([question, beforeText, beforeCount]) => {
                const rootSelector = [
                    'main',
                    '[role="main"]',
                    '[class*="chat"]',
                    '[class*="conversation"]',
                    '[class*="message-list"]',
                    '[class*="dialog"]'
                ].join(',');
                const messageSelector = [
                    '[data-role="assistant"]',
                    '[data-testid*="message"]',
                    '[class*="assistant"]',
                    '[class*="bot"]',
                    '[class*="answer"]',
                    '[class*="message"]',
                    '[class*="markdown"]',
                    '[role="article"]'
                ].join(',');
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0'
                        && el.offsetParent !== null;
                };
                const clean = (text) => (text || '').replace(/\\u00a0/g, ' ').replace(/[ \\t]+\\n/g, '\\n').trim();
                const uiWords = [
                    '新对话', '历史对话', '帮我写作', 'AI 创作', '云盘', '登录', '注册',
                    '设置', '退出', '复制', '点赞', '点踩', '重新生成', '停止生成',
                    'PPT 生成', '图像生成', '下载APP', '智能体', '发现'
                ];
                const validText = (text) => {
                    const t = clean(text);
                    if (t.length < 30 || t.length > 8000) return false;
                    if (t === question) return false;
                    if (t.includes(question) && t.length < question.length + 120) return false;
                    const lines = t.split('\\n').map(x => x.trim()).filter(Boolean);
                    if (lines.length <= 12) {
                        const uiCount = lines.filter(line => uiWords.some(w => line === w || line.startsWith(w))).length;
                        if (uiCount >= 3) return false;
                    }
                    return true;
                };
                const scoreText = (text, index) => {
                    const t = clean(text);
                    const punct = (t.match(/[。！？；：，,.!?]/g) || []).length;
                    return Math.min(t.length, 3000) + punct * 25 + index * 2;
                };

                const roots = Array.from(document.querySelectorAll(rootSelector)).filter(visible);
                if (!roots.length) roots.push(document.body);

                let messages = [];
                for (const root of roots) {
                    messages = messages.concat(Array.from(root.querySelectorAll(messageSelector)).filter(visible));
                }
                messages = Array.from(new Set(messages));
                const newMessages = messages.length > beforeCount ? messages.slice(beforeCount) : messages;

                let best = null;
                newMessages.forEach((el, idx) => {
                    const text = clean(el.innerText || el.textContent || '');
                    if (!validText(text)) return;
                    const score = scoreText(text, idx);
                    if (!best || score > best.score) {
                        best = { answer: text, selector: 'message-node', length: text.length, method: 'message-node', score };
                    }
                });
                if (best) return best;

                const bodyText = clean(document.body.innerText || '');
                const baseText = clean(beforeText || '');
                if (baseText && bodyText.startsWith(baseText)) {
                    const delta = clean(bodyText.slice(baseText.length));
                    if (validText(delta)) {
                        return { answer: delta, selector: 'body-delta', length: delta.length, method: 'body-delta' };
                    }
                }

                return { answer: '', selector: null, length: 0, method: 'none' };
            }""",
            [question, before_text, before_count],
        )

    def _prepare_intercept_collector(self) -> Dict[str, Any]:
        """
        创建 API 响应拦截收集器（供调用方在提问前预注册）。

        返回 {"chunks": list, "raw_bodies": list, "handler": callable}
        - chunks: 提取到的文本列表
        - raw_bodies: 原始响应体列表（用于调试和兜底解析）
        - handler: 传给 page.on("response", handler) 的回调
        """
        collected_chunks: List[str] = []
        raw_bodies: List[str] = []
        # 用于去重，避免同一个响应被处理多次
        seen_urls: set = set()

        def _is_blacklisted(url: str) -> bool:
            """检查 URL 是否在黑名单中"""
            url_lower = url.lower()
            for pattern in self.API_BLACKLIST_PATTERNS:
                if re.search(pattern, url_lower):
                    return True
            return False

        def _is_valid_response(body: str) -> bool:
            """检查响应体是否是有效的聊天响应（排除知识库提示等）"""
            if not body or len(body) < 20:
                return False
            body_lower = body.lower()
            # 检查是否匹配黑名单内容
            match_count = 0
            for pattern in self.RESPONSE_BLACKLIST_PATTERNS:
                if pattern.lower() in body_lower:
                    match_count += 1
            # 如果超过 3 个黑名单词匹配，很可能是错误的响应
            if match_count >= 3:
                return False
            return True

        def _is_chat_api(url: str) -> bool:
            """检查 URL 是否是聊天 API"""
            return any(re.search(p, url) for p in self.CHAT_API_PATTERNS)

        async def _on_response(response: Response):
            url = response.url.lower()
            # 检查黑名单
            if _is_blacklisted(url):
                self._log("debug", f"[拦截] 跳过黑名单API: {url[:80]}")
                return
            # 检查是否是聊天 API
            if not _is_chat_api(url):
                return
            # 去重
            if url in seen_urls:
                return
            seen_urls.add(url)

            method = response.request.method
            self._log("info", f"[拦截] 捕获 API: {method} {response.url[:80]}")

            try:
                # 尝试获取响应体
                body = None
                content_type = response.headers.get("content-type", "")

                if "application/json" in content_type or "text/" in content_type:
                    body = await response.text()
                elif method == "GET" and "text/event-stream" not in content_type:
                    # GET 请求且非流式，尝试获取 body
                    try:
                        body = await response.text()
                    except Exception:
                        pass

                if not body:
                    # 尝试从 buffer 获取
                    try:
                        body_bytes = await response.body()
                        body = body_bytes.decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                if not body or len(body) < 10:
                    self._log("debug", "[拦截] 响应体为空或太短")
                    return

                # 先记录原始响应体
                raw_bodies.append(body)
                self._log("info", f"[拦截] 响应长度={len(body)}, content-type={content_type}")

                # 检查响应体是否有效
                if not _is_valid_response(body):
                    self._log("warning", "[拦截] 响应体疑似知识库提示，跳过")
                    return

                # 尝试提取文本
                text = self._extract_text_from_response(body)
                if text and len(text) > 20:
                    collected_chunks.append(text)
                    self._log("info", f"[拦截] 提取文本 {len(text)} 字符")
                else:
                    # 调试：打印响应体前200字符
                    self._log("debug", f"[拦截] 未提取到文本，响应体前200字符: {body[:200]}")

            except Exception as e:
                self._log("debug", f"[拦截] 响应解析异常: {e}")

        def _on_response_sync(response: Response):
            asyncio.ensure_future(_on_response(response))

        return {"chunks": collected_chunks, "raw_bodies": raw_bodies, "handler": _on_response_sync}

    async def _wait_for_intercept_chunks(
        self, collected_chunks: List[str], timeout_ms: int,
        raw_bodies: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        等待 collected_chunks 积累到稳定，然后返回结果。

        如果 collected_chunks 为空但有 raw_bodies，尝试多种解析策略进行兜底。
        """
        start = time.time()
        while time.time() - start < timeout_ms / 1000:
            await asyncio.sleep(2)
            if collected_chunks:
                prev_count = len(collected_chunks)
                await asyncio.sleep(5)
                if len(collected_chunks) == prev_count:
                    break

        if collected_chunks:
            full_text = "\n".join(collected_chunks)
            self._log("info", f"[拦截] 最终获取 {len(full_text)} 字符")
            return {
                "success": True,
                "answer": full_text[:10000],
                "selector": "api-intercept",
                "length": len(full_text),
                "method": "api-intercept",
            }
        elif raw_bodies:
            # collected_chunks 为空，但有原始响应体 → 尝试兜底解析
            self._log("warning", f"[拦截] collected_chunks 为空，尝试从 {len(raw_bodies)} 个原始响应体兜底解析")
            fallback_text = self._try_fallback_parsing(raw_bodies)
            if fallback_text:
                self._log("info", f"[拦截] 兜底解析成功，获取 {len(fallback_text)} 字符")
                return {
                    "success": True,
                    "answer": fallback_text[:10000],
                    "selector": "api-intercept-fallback",
                    "length": len(fallback_text),
                    "method": "api-intercept-fallback",
                }
            else:
                self._log("warning", "[拦截] 兜底解析也失败了")
                return {"success": False, "answer": "", "selector": None, "length": 0, "method": "none"}
        else:
            self._log("warning", "[拦截] 未捕获到任何 API 响应")
            return {"success": False, "answer": "", "selector": None, "length": 0, "method": "none"}

    def _try_fallback_parsing(self, raw_bodies: List[str]) -> str:
        """
        兜底解析策略：尝试多种方式从原始响应体提取文本。

        策略顺序：
        1. 如果响应是纯文本/HTML，提取其中的文本内容
        2. 尝试 JSON.parse 后遍历所有可能的文本字段
        3. 正则提取常见的文本字段值
        """
        for body in raw_bodies:
            if not body or len(body) < 10:
                continue

            # 策略 1：如果是普通文本（不是 JSON），尝试提取文本内容
            if not body.strip().startswith(('{', '[')) and 'data:' not in body[:20]:
                # 可能是纯文本响应
                cleaned = body.strip()
                if len(cleaned) > 50:
                    self._log("info", f"[兜底] 尝试解析为纯文本，长度={len(cleaned)}")
                    return cleaned

            # 策略 2：如果是 HTML 响应（豆包有时会返回 HTML）
            if '<html' in body.lower() or '<!doctype' in body.lower():
                self._log("info", "[兜底] 响应是 HTML，提取文本内容")
                text = self._extract_text_from_html(body)
                if text and len(text) > 50:
                    return text

            # 策略 3：JSON 解析后遍历所有值
            try:
                data = json.loads(body)
                text = self._deep_extract_all_text(data)
                if text and len(text) > 50:
                    self._log("info", f"[兜底] JSON 深遍历提取到 {len(text)} 字符")
                    return text
            except (json.JSONDecodeError, TypeError):
                pass

            # 策略 4：正则提取所有可能的文本字段
            text = self._regex_extract_text(body)
            if text and len(text) > 50:
                self._log("info", f"[兜底] 正则提取到 {len(text)} 字符")
                return text

        return ""

    def _deep_extract_all_text(self, data: Any, depth: int = 0) -> str:
        """深度遍历 JSON，提取所有可能的文本内容（用于兜底）"""
        if depth > 10:  # 防止无限递归
            return ""

        if isinstance(data, str):
            # 只返回有意义的文本（排除短字段名、URL 等）
            if len(data) > 30 and not data.startswith('http'):
                return data
            return ""

        if isinstance(data, dict):
            parts = []
            for key, val in data.items():
                # 跳过明显的非内容字段
                skip_keys = ('id', 'url', 'href', 'src', 'type', 'role', 'class', 'style', 'name')
                if key.lower() in skip_keys:
                    continue
                text = self._deep_extract_all_text(val, depth + 1)
                if text:
                    parts.append(text)
            return "\n".join(parts)

        if isinstance(data, list):
            for item in data:
                text = self._deep_extract_all_text(item, depth + 1)
                if text:
                    return text  # 返回第一个找到的有意义文本
        return ""

    def _regex_extract_text(self, body: str) -> str:
        """正则表达式兜底提取"""
        # 提取各种可能的文本字段值
        patterns = [
            r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'"delta"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"',
            # SSE data 块
            r'data:\s*(\{[^}]+\})',
        ]
        parts = []
        for pattern in patterns:
            matches = re.findall(pattern, body, re.DOTALL)
            for match in matches:
                # 解码转义字符
                try:
                    decoded = match.encode().decode('unicode_escape', errors='ignore')
                    if len(decoded) > 30:
                        parts.append(decoded)
                except Exception:
                    if len(match) > 30:
                        parts.append(match)
        return "\n".join(parts)

    def _extract_text_from_html(self, html: str) -> str:
        """从 HTML 中提取纯文本"""
        # 移除 script 和 style 标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 解码 HTML 实体
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
        # 清理空白
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _extract_text_from_response(self, body: str) -> str:
        """
        从 API 响应体中提取纯文本。
        支持多种格式：
        1. SSE 流式（data: {json}\n）
        2. 普通 JSON（OpenAI 兼容格式）
        3. 豆包格式（data 字段在 JSON 中）
        4. 正则兜底提取
        """
        if not body or len(body) < 10:
            return ""

        parts: List[str] = []

        # ── 1. SSE 流式解析 ──
        if body.startswith("data:") or "\ndata:" in body:
            for line in body.split("\n"):
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    text = self._extract_from_json(data)
                    if text and len(text) > 5:
                        parts.append(text)
                except (json.JSONDecodeError, TypeError):
                    # 可能不是完整 JSON，尝试直接提取
                    text = self._extract_text_from_raw_string(data_str)
                    if text and len(text) > 10:
                        parts.append(text)

        # ── 2. 普通 JSON 解析 ──
        if not parts:
            try:
                data = json.loads(body)
                text = self._extract_from_json(data)
                if text and len(text) > 5:
                    parts.append(text)
            except (json.JSONDecodeError, TypeError):
                pass

        # ── 3. 正则兜底提取 ──
        # 注意：JSON 字符串中的引号会被转义为 \"，需要处理
        if not parts:
            # 尝试提取各种可能的文本字段
            patterns = [
                # 标准 OpenAI 格式: "choices":[{"message":{"content":"..."}}]
                r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"',
                r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"',
                # 豆包格式: "data":"..." 或 "msg":"..."
                r'"(?:data|msg|answer|response)"\s*:\s*"((?:[^"\\]|\\.)*)"',
                # 增量格式: "delta":{"content":"..."}
                r'"delta"\s*:\s*"((?:[^"\\]|\\.)*)"',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, body, re.DOTALL)
                for match in matches:
                    # 处理转义字符
                    try:
                        text = match.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
                        if len(text) > 10:
                            parts.append(text)
                    except Exception:
                        pass

        # ── 4. 豆包特殊格式：直接提取 "..." 中的内容 ──
        if not parts:
            # 豆包可能返回纯文本或特殊格式
            # 尝试匹配 "text":"..." 但忽略短响应
            matches = re.findall(r'"[^"]+"\s*:\s*"([^"]{20,})"', body)
            for match in matches:
                if len(match) > 20:
                    parts.append(match)

        # ── 5. 去重并合并 ──
        if parts:
            # 去重
            seen = set()
            unique_parts = []
            for p in parts:
                # 归一化比较
                normalized = p.strip().lower()
                if normalized not in seen and len(p.strip()) > 10:
                    seen.add(normalized)
                    unique_parts.append(p)

            if unique_parts:
                # 选择最长的那个（通常最完整）
                best = max(unique_parts, key=len)
                self._log("info", f"[拦截] 提取到 {len(unique_parts)} 个文本片段，最长 {len(best)} 字符")
                return best.strip()

        return ""

    def _extract_text_from_raw_string(self, s: str) -> str:
        """从原始字符串中提取文本内容"""
        if not s or len(s) < 10:
            return ""
        # 尝试匹配被引号包围的长文本
        match = re.search(r'"([^"]{20,})"', s)
        if match:
            return match.group(1)
        return ""

    def _extract_from_json(self, data: Any) -> str:
        """
        递归从 JSON 结构中提取回复文本。
        支持常见的嵌套结构：
        - {"content": "..."}
        - {"choices": [{"message": {"content": "..."}}]}
        - {"choices": [{"delta": {"content": "..."}}]}  (流式)
        - {"data": [{"text": "..."}]}
        """
        if isinstance(data, str):
            return data if len(data) > 10 else ""
        if isinstance(data, dict):
            # 常见字段名（优先级从高到低）
            for key in ("content", "text", "answer", "message", "delta", "response", "reply", "output"):
                val = data.get(key)
                if isinstance(val, str) and len(val) > 0:
                    return val
                if isinstance(val, dict):
                    # 嵌套，如 {choices: [{message: {content: "..."}}]}
                    extracted = self._extract_from_json(val)
                    if extracted:
                        return extracted
                if isinstance(val, list):
                    # 遍历列表找第一个有文本的
                    for item in val:
                        extracted = self._extract_from_json(item)
                        if extracted:
                            return extracted
            # 递归搜索所有值
            for val in data.values():
                extracted = self._extract_from_json(val)
                if extracted:
                    return extracted
        if isinstance(data, list):
            for item in data:
                extracted = self._extract_from_json(item)
                if extracted:
                    return extracted
        return ""

    async def track_answer_via_mutation(
        self,
        page: Page,
        question: str,
        timeout_ms: int = 90000,
        stable_checks: int = 5,
        check_interval_ms: int = 800,
    ) -> Dict[str, Any]:
        """
        稳健回答追踪：定时轮询扫描 + 辅助 MutationObserver。

        从独立 JS 文件加载跟踪代码，避免 Python 字符串转义问题。
        """
        self._log("info", f"[AnswerTracker] 启动轮询追踪, 超时={timeout_ms}ms")

        import os
        tracker_js_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "answer_tracker.js"
        )
        with open(tracker_js_path, "r", encoding="utf-8") as f:
            tracker_js = f.read()

        try:
            result = await page.evaluate(
                tracker_js,
                [timeout_ms, stable_checks, check_interval_ms, question],
            )

            if result and result.get("success"):
                self._log(
                    "info",
                    f"[AnswerTracker] 追踪成功 method={result['method']} "
                    f"length={result['length']}",
                )
                return result
            else:
                self._log("warning", "[AnswerTracker] 轮询超时未找到有效回答")
                return {"success": False, "answer": "", "selector": None, "length": 0, "method": "none"}

        except Exception as e:
            self._log("error", f"[AnswerTracker] 异常: {e}")
            return {"success": False, "answer": "", "selector": None, "length": 0, "method": "error", "error": str(e)}

    async def get_answer_content(self, page: Page, question: str) -> Dict[str, Any]:
        """
        增强的获取AI回答内容

        Args:
            page: Playwright Page对象
            question: 用户问题（用于过滤）

        Returns:
            获取结果
        """
        self._log("info", "开始获取AI回答内容")

        answer_selectors = [
            "[class*='assistant']",
            "[class*='ai-message']",
            "[data-role='assistant']",
            "[class*='answer-content']",
            "[class*='chat-answer']",
            ".markdown-body",
            "[class*='response']",
            "[class*='result']",
            "[class*='content-body']",
            "[class*='message-content']",
            "[class*='bot-message']",
            "[class*='reply-content']",
            "[class*='conversation-turn']",
            "[class*='chat-message']:last-of-type",
            "[class*='message-item']:last-child [class*='content']",
        ]

        answer_text = ""
        matched_selector = None

        for selector in answer_selectors:
            try:
                self._log("debug", f"尝试选择器: {selector}")

                elements = await page.query_selector_all(selector)

                if elements:
                    self._log("debug", f"选择器 {selector} 找到 {len(elements)} 个元素")

                    for element in reversed(elements):
                        try:
                            element_text = await element.inner_text()
                            element_text = element_text.strip()

                            if len(element_text) > 100:
                                if question not in element_text[:50]:
                                    answer_text = element_text
                                    matched_selector = selector
                                    self._log("info", f"找到AI回答, 选择器: {selector}, 长度: {len(answer_text)}")
                                    break

                        except Exception as e:
                            self._log("debug", f"获取元素文本失败: {e}")
                            continue

                    if answer_text:
                        break

            except Exception as e:
                self._log("debug", f"选择器 {selector} 处理失败: {e}")
                continue

        if not answer_text:
            self._log("warning", "标准选择器未找到回答, 尝试备用方法")

            # 获取页面所有文本
            page_text = await page.inner_text("body")

            # 分割成行
            lines = [line.strip() for line in page_text.split("\n") if line.strip()]

            # 过滤掉常见的菜单和无关内容
            ignored_keywords = [
                "AI回答",
                "豆包",
                "新对话",
                "帮我写作",
                "AI 创作",
                "云盘",
                "更多",
                "历史对话",
                "登录",
                "注册",
                "关于",
                "帮助",
                "设置",
                "退出",
                "反馈",
                "Terms",
                "Privacy",
                "最近对话",
                "对话分组",
                "我的空间",
                "手机版",
                "下载",
                "APP",
                "智能体",
                "发现",
                "深度思考",
                "联网搜索",
                "重新生成",
                "复制",
                "点赞",
                "点踩",
                "分享",
                "PPT 生成",
                "图像生成",
                "AI 写作",
                "文档处理",
                "网页摘要",
                "视频理解",
                "图片理解",
                "录音笔",
                "快捷方式",
                "正在思考",
                "参考来源",
            ]

            potential_answers = []
            current_block = []
            consecutive_short = 0

            for line in lines:
                # 过滤极短行
                if len(line) < 5:
                    consecutive_short += 1
                    continue

                # 检测是否为 UI 菜单项（短行 + 匹配忽略关键词）
                is_ignored = False
                if len(line) < 100:
                    for keyword in ignored_keywords:
                        if keyword in line:
                            is_ignored = True
                            break

                # 检测是否为纯 UI 元素：很短（< 20 字符）且看起来像菜单项
                is_ui_element = False
                if len(line) < 20 and not any(c in line for c in '，。！？；：、'):
                    # 中文短词组，大概率是菜单/按钮
                    is_ui_element = True

                if is_ignored or is_ui_element:
                    consecutive_short += 1
                    # 连续超过 3 个 UI 行 → 分割块
                    if consecutive_short >= 3 and current_block:
                        potential_answers.append("\n".join(current_block))
                        current_block = []
                    continue

                consecutive_short = 0

                # 过滤掉包含问题的行
                if question in line:
                    continue

                current_block.append(line)

            # 添加最后一个块
            if current_block:
                potential_answers.append("\n".join(current_block))

            # 寻找最长且质量最好的文本块
            longest_block = ""
            for block in potential_answers:
                lines_in_block = block.split("\n")
                # 跳过疑似侧边栏/菜单块
                if len(lines_in_block) > 5:
                    avg_len = sum(len(l) for l in lines_in_block) / len(lines_in_block)
                    if avg_len < 30:
                        self._log("debug", f"跳过疑似侧边栏块: 行数={len(lines_in_block)}, 平均长度={avg_len:.1f}")
                        continue

                if len(block) > len(longest_block):
                    longest_block = block

            if len(longest_block) > 100:
                answer_text = longest_block
                matched_selector = "body-text-filtered"
                self._log("info", f"使用过滤后的备用方法找到回答, 长度: {len(answer_text)}")

        if answer_text:
            self._log("info", f"成功获取回答内容, 长度: {len(answer_text)} 字符")
            return {
                "success": True,
                "answer": answer_text[:5000],
                "selector": matched_selector,
                "length": len(answer_text),
            }
        else:
            self._log("warning", "未能获取到回答内容")
            return {"success": False, "answer": "", "selector": None, "length": 0}

    @staticmethod
    def _extract_company_layers(company: str):
        """从完整公司名提取分层匹配词"""
        locations = [
            "北京", "上海", "深圳", "广州", "杭州", "南京", "成都", "武汉",
            "重庆", "西安", "天津", "苏州", "东莞", "佛山", "合肥", "长沙",
            "郑州", "济南", "青岛", "大连", "厦门", "福州", "无锡", "宁波",
            "温州", "石家庄", "哈尔滨", "沈阳", "昆明", "贵阳", "南宁",
            "海口", "珠海", "惠州", "中山", "中国", "香港", "澳门", "台湾",
        ]
        suffixes = [
            "股份有限公司", "有限责任公司", "集团有限公司",
            "科技有限公司", "信息技术有限公司", "网络技术有限公司",
            "实业有限公司", "贸易有限公司", "投资有限公司", "控股有限公司",
            "发展有限公司", "有限公司",
        ]
        industries = [
            "信息技术", "网络技术", "生物医药", "新能源",
            "科技", "实业", "贸易", "投资", "控股", "发展",
            "信息", "软件", "数据", "智能", "互联", "电子", "通信",
            "医药", "医疗", "教育", "文化", "传媒", "广告", "咨询",
            "服务", "房地产", "建筑", "装饰", "环保", "农业",
            "食品", "餐饮", "旅游", "物流", "金融", "保险", "证券",
        ]

        name = company.strip()
        core = name
        for loc in sorted(locations, key=len, reverse=True):
            if core.startswith(loc):
                core = core[len(loc):]
                break
        for suf in sorted(suffixes, key=len, reverse=True):
            if core.endswith(suf):
                core = core[:-len(suf)]
                break
        industry_matched = ""
        for ind in sorted(industries, key=len, reverse=True):
            if core.endswith(ind):
                industry_matched = ind
                core = core[:-len(ind)]
                break

        core = core.strip()
        layers = []
        seen = set()
        def add(s):
            if s and len(s) >= 2 and s not in seen:
                seen.add(s); layers.append(s)
        add(core)
        if core and industry_matched:
            add(core + industry_matched)
        add(name)
        return layers

    def check_keywords_in_text(self, text: str, keyword: str, company: str) -> Dict[str, Any]:
        """
        检查文本中是否包含关键词和公司名

        Args:
            text: 待检测文本
            keyword: 目标关键词
            company: 公司名称

        Returns:
            检测结果详细信息
        """
        self._log("info", f"开始关键词检测, 文本长度: {len(text)}")

        import re

        def clean_str(s: str) -> str:
            # 统一清理逻辑：替换非字字符为空格，合并空格，转小写
            s = re.sub(r"[^\w\s\u4e00-\u9fa5]", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s.lower()

        text_lower = clean_str(text)
        keyword_lower = clean_str(keyword)

        keyword_count = text_lower.count(keyword_lower)
        keyword_positions = [m.start() for m in re.finditer(re.escape(keyword_lower), text_lower)]

        # 公司名分层匹配
        company_layers = self._extract_company_layers(company)
        self._log("info", f"公司名分层: {' > '.join(company_layers)}")

        company_found = False
        company_count = 0
        company_matched = ""
        company_positions = []

        for layer in company_layers:
            layer_lower = clean_str(layer)
            if len(layer_lower) < 2:
                continue
            count = text_lower.count(layer_lower)
            if count > 0:
                company_found = True
                company_count = count
                company_matched = layer
                company_positions = [m.start() for m in re.finditer(re.escape(layer_lower), text_lower)]
                self._log("info", f"公司名命中: '{layer}' (第{company_layers.index(layer)+1}/{len(company_layers)}层)")
                break

        result = {
            "keyword_found": keyword_count > 0,
            "keyword_count": keyword_count,
            "keyword_positions": keyword_positions[:5],
            "company_found": company_found,
            "company_count": company_count,
            "company_matched": company_matched,
            "confidence": 0.0,
            "reason": "",
        }

        if keyword_count > 0:
            result["keyword_found"] = True
            result["confidence"] = min(0.5 + keyword_count * 0.1, 0.9)
            result["reason"] = f"关键词'{keyword}'出现{keyword_count}次"

        if company_found:
            result["confidence"] = min(result["confidence"] + 0.2, 0.95)
            note = f" (匹配为'{company_matched}')" if company_matched != company else ""
            result["reason"] += f", 公司名出现{company_count}次{note}"

        if len(text) < 100 and keyword_count > 0:
            result["confidence"] = min(result["confidence"] + 0.1, 0.85)

        self._log(
            "info",
            f"检测完成: 关键词={result['keyword_found']}({keyword_count}次), "
            f"公司={result['company_found']}({company_count}次, 层:'{company_matched}'), "
            f"置信度={result['confidence']:.2f}",
        )

        return result

    async def clear_chat_history(self, page: Page) -> bool:
        """
        清理聊天历史记录（如果支持）

        Returns:
            是否成功清理
        """
        self._log("info", "尝试清理聊天历史")

        try:
            clear_selectors = [
                "[class*='new-chat']",
                "[class*='new-conversation']",
                "[class*='clear-history']",
                "button[title*='新对话']",
                "[class*='refresh'] button",
            ]

            for selector in clear_selectors:
                try:
                    elements = await page.query_selector_all(selector)

                    if elements:
                        for element in elements[:1]:
                            try:
                                await element.click(timeout=3000)
                                await asyncio.sleep(1)
                                self._log("info", f"成功点击清理按钮: {selector}")
                                return True
                            except Exception:
                                continue
                except Exception:
                    continue

            self._log("info", "未找到清理按钮或无需清理")
            return True

        except Exception as e:
            self._log("error", f"清理聊天历史失败: {e}")
            return False

    def get_operation_log(self) -> List[Dict]:
        """
        获取操作日志

        Returns:
            操作日志列表
        """
        return self.operation_log.copy()

    async def clear_operation_log(self):
        """
        清空操作日志
        """
        self.operation_log.clear()

    async def submit_question(
        self, page: Page, question: str, input_selector: str, submit_button_selector: str = None
    ) -> bool:
        """
        稳健的提问提交方法
        优化：优先使用模拟键盘输入，解决React/Vue组件状态同步问题

        Args:
            page: Playwright页面对象
            question: 问题内容
            input_selector: 输入框选择器
            submit_button_selector: 提交按钮选择器（可选）

        Returns:
            是否成功提交
        """
        try:
            self._log("info", f"开始输入问题，长度: {len(question)}")

            # 1. 聚焦并点击输入框 (确保激活)
            try:
                await page.focus(input_selector)
                await page.click(input_selector)
                await asyncio.sleep(0.5)
            except Exception as e:
                self._log("warning", f"聚焦/点击输入框失败: {e}")

            # 2. 模拟真实键盘输入 (最稳健的方式)
            # 避免使用 fill，因为它可能不会触发某些前端框架的 change 事件
            try:
                # 先尝试清空内容 (如果是 input/textarea)
                await page.evaluate(
                    """(selector) => {
                    const el = document.querySelector(selector);
                    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
                        el.value = '';
                    } else if (el) {
                        el.innerText = '';
                    }
                }""",
                    input_selector,
                )

                # 模拟打字
                await page.keyboard.type(question, delay=30)

            except Exception as e:
                self._log("error", f"模拟输入失败: {e}")
                return False

            # 3. 验证输入结果
            input_value = await page.evaluate(
                """(selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                return el.value || el.innerText || el.textContent;
            }""",
                input_selector,
            )

            if not input_value or len(input_value.strip()) == 0:
                self._log("warning", "检测到输入框为空，尝试使用 fill 作为回退方案")
                await page.fill(input_selector, question)

            await asyncio.sleep(0.5)
            self._log("info", "问题输入完成，准备提交")

            # 4. 提交
            submitted = False

            # 方案A: 点击发送按钮 (如果存在且可见)
            if submit_button_selector:
                try:
                    # 使用 wait_for_selector 确保按钮出现 (短超时)
                    btn = await page.wait_for_selector(submit_button_selector, state="visible", timeout=2000)
                    if btn and await btn.is_enabled():
                        self._log("info", "点击发送按钮提交")
                        await btn.click()
                        submitted = True
                except Exception:
                    self._log("debug", "发送按钮不可用或未找到")

            # 方案B: 回车提交
            if not submitted:
                self._log("info", "使用回车键提交")
                await page.press(input_selector, "Enter")

            return True

        except Exception as e:
            self._log("error", f"提问提交失败: {e}")
            return False
