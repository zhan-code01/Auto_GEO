# -*- coding: utf-8 -*-
"""
Playwright发布适配器
用适配器模式实现各平台发布，开闭原则！
"""

from abc import ABC, abstractmethod
import html
import re
from re import Match
from typing import Dict, Any, Iterator, Optional
from playwright.async_api import Page
from loguru import logger

from backend.services.playwright.manual_guard import (
    ManualEventCallback,
    ensure_no_manual_challenge,
    manual_required_result,
    manual_timeout_result,
)


class BasePublisher(ABC):
    """
    基础发布适配器
    注意：所有平台适配器都要继承这个类！
    """

    def __init__(self, platform_id: str, config: Dict[str, Any]):
        self.platform_id = platform_id
        self.config = config
        self.name = config.get("name", platform_id)
        self.color = config.get("color", "#333333")
        self._manual_event_callback: Optional[ManualEventCallback] = None
        self.attempt_mode = "auto_attempt"

    def set_manual_event_callback(self, callback: Optional[ManualEventCallback]) -> None:
        self._manual_event_callback = callback

    def set_attempt_mode(self, mode: str) -> None:
        self.attempt_mode = mode if mode in {"auto_attempt", "manual_handoff"} else "auto_attempt"

    def is_manual_handoff(self) -> bool:
        return self.attempt_mode == "manual_handoff"

    def manual_intervention_result(
        self,
        stage: str,
        message: str,
        page: Optional[Page] = None,
    ) -> Dict[str, Any]:
        """Return a structured result when login/captcha must be completed by a person."""
        return {
            "success": False,
            "platform_url": page.url if page else None,
            "error_msg": message,
            "requires_manual_intervention": True,
            "manual_intervention_stage": stage,
            # 风控/验证码不属于"登录过期"，绝不允许据此把账号标为失效
            "auth_status": "manual_intervention",
        }

    def login_expired_result(
        self,
        message: str,
        page: Optional[Page] = None,
    ) -> Dict[str, Any]:
        """Return a structured result when the session is *definitively* logged out.

        仅当确定被弹回登录页 / 看到登录入口时才调用。返回值会被上游用来把账号标记为
        ``status = -1``（需重新授权）。风控、反爬、网络、内容审核等不确定情况请改用
        ``manual_intervention_result`` 或返回 ``auth_status="unknown"``，切勿据此标失效。
        """
        return {
            "success": False,
            "platform_url": page.url if page else None,
            "error_msg": message,
            "auth_status": "logged_out",
        }

    def unknown_auth_result(
        self,
        message: str,
        page: Optional[Page] = None,
    ) -> Dict[str, Any]:
        """登录态不确定（疑似反爬/网络抖动等），不判断是否失效，只上报。"""
        return {
            "success": False,
            "platform_url": page.url if page else None,
            "error_msg": message,
            "auth_status": "unknown",
        }

    # 通用「是否落在登录页」判定（URL 维度，确定性强、零副作用）。
    # 覆盖各平台被踢回登录页的常见形态：login / passport / signin / sso / qrlogin 等。
    _LOGIN_PAGE_RE = re.compile(
        r"(login|passport|sign[-_]?in|sso|qrlogin|logout|/auth/|account/login|login\.html)",
        re.IGNORECASE,
    )

    def _is_on_login_page(self, page: Optional[Page]) -> bool:
        """仅依据当前 URL 判断是否被弹回登录页。**不**做内容探测，避免误判。"""
        if page is None:
            return False
        try:
            url = page.url or ""
        except Exception:
            return False
        return bool(self._LOGIN_PAGE_RE.search(url))

    async def _auth_failure(
        self,
        page: Page,
        stage: str,
        *,
        definitive: bool,
        message: str,
    ) -> Dict[str, Any]:
        """统一出口：确定性登出 / 不确定，分别落到 login_expired_result / unknown_auth_result。

        - definitive=True  （如确认被重定向到登录页）：auth_status="logged_out"，上游据此标 -1。
        - definitive=False （如网络异常、疑似安全验证、编辑器迟迟不出现）：auth_status="unknown"，
          绝不据此推断账号失效。
        尽量保留失败快照（各 publisher 自带 _save_debug_snapshot），便于事后定位。
        """
        snapshot = None
        try:
            save = getattr(self, "_save_debug_snapshot", None)
            if callable(save):
                snapshot = await save(page, f"auth_{stage}")
        except Exception as exc:  # 快照失败不阻断主流程
            logger.warning("[BasePublisher] 保存鉴权失败快照失败: {}", exc)

        result = (
            self.login_expired_result(message, page)
            if definitive
            else self.unknown_auth_result(message, page)
        )
        if snapshot:
            result["debug_path"] = snapshot
        return result

    async def detect_manual_intervention(self, page: Page) -> Optional[str]:
        """Detect manual challenges, wait for user handling, then continue or fail.

        Existing publishers call this method at key checkpoints. Returning None
        means automation can continue; returning text means the user did not
        clear the challenge before the manual timeout.
        """
        resolution = await ensure_no_manual_challenge(
            page,
            platform=self.platform_id,
            stage="publish",
            wait_for_resolution=self.is_manual_handoff(),
            on_event=self._manual_event_callback,
        )
        if not resolution or resolution.handled:
            return None
        if resolution.timed_out:
            return manual_timeout_result(resolution)["error_msg"]
        return manual_required_result(resolution)["error_msg"]

    async def ensure_publish_can_continue(self, page: Page, stage: str) -> Optional[Dict[str, Any]]:
        resolution = await ensure_no_manual_challenge(
            page,
            platform=self.platform_id,
            stage=stage,
            wait_for_resolution=self.is_manual_handoff(),
            on_event=self._manual_event_callback,
        )
        if not resolution or resolution.handled:
            return None
        return manual_timeout_result(resolution) if resolution.timed_out else manual_required_result(resolution)

    @abstractmethod
    async def publish(self, page: Page, article: Any, account: Any, declare_ai_content: bool = True) -> Dict[str, Any]:
        """
        发布文章到目标平台

        Args:
            page: Playwright Page对象
            article: 文章对象（title, content等）
            account: 账号对象
            declare_ai_content: 是否勾选AI创作内容声明 (默认True)

        Returns:
            发布结果：{
                "success": bool,
                "platform_url": str,
                "error_msg": str
            }
        """
        pass

    async def navigate_to_publish_page(self, page: Page) -> bool:
        """
        导航到发布页面

        Returns:
            是否成功导航
        """
        try:
            await page.goto(self.config["publish_url"], wait_until="networkidle")
            logger.info(f"导航到发布页面: {self.name}")
            return True
        except Exception as e:
            logger.error(f"导航失败: {self.name}, {e}")
            return False

    async def wait_for_selector(self, page: Page, selector: str, timeout: int = 10000) -> bool:
        """
        等待选择器出现

        注意：各平台页面加载速度不同，需要耐心等待！
        """
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception as e:
            logger.warning(f"等待选择器超时: {selector}, {e}")
            return False

    async def fill_title(self, page: Page, title: str, title_selector: str) -> bool:
        """
        填充标题
        """
        try:
            # 先清空再填充
            await page.fill(title_selector, "")
            await page.fill(title_selector, title)
            logger.info(f"标题已填充: {title[:20]}...")
            return True
        except Exception as e:
            logger.error(f"填充标题失败: {e}")
            return False

    async def fill_content(self, page: Page, content: str, content_selector: str) -> bool:
        """
        填充正文
        """
        try:
            await page.fill(content_selector, content)
            logger.info(f"正文已填充: {len(content)} 字符")
            return True
        except Exception as e:
            logger.error(f"填充正文失败: {e}")
            return False

    def extract_image_urls(self, content: str) -> list[str]:
        """
        从 Markdown/HTML 内容中提取图片 URL。
        文章生成模块目前主要输出 Markdown 图片语法，发布器不能只识别 <img>。
        """
        if not content:
            return []

        urls: list[str] = []
        for match in re.findall(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", content):
            urls.append(match.strip())

        for match in re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE):
            urls.append(html.unescape(match.strip()))

        deduped: list[str] = []
        seen = set()
        for url in urls:
            if url and url not in seen:
                deduped.append(url)
                seen.add(url)
        return deduped

    def iter_image_markers(self, content: str) -> Iterator[Match[str]]:
        """按原文顺序扫描图片标记，同时支持 Markdown ![](...) 与 HTML <img> 两种形态。

        生成器与 HTML 入库格式都从这里走：文章内容既可能是 LLM 中间态的
        Markdown（![alt](url)），也可能是已转成 HTML 的 <img src="url">。
        """
        pattern = re.compile(
            r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)"
            r"|<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>",
            flags=re.IGNORECASE,
        )
        return pattern.finditer(content or "")

    def image_url_from_marker(self, match: Match[str]) -> str:
        """从图片标记的匹配对象中提取图片 URL。"""
        return html.unescape((match.group(1) or match.group(2) or "").strip())

    def build_content_blocks_by_markers(
        self,
        content: str,
        image_paths: list[str],
        max_chars: int = 0,
    ) -> Optional[list[dict[str, str]]]:
        """按原文图片标记位置把内容切成「文本 / 图片」块，保留生成时的图文排版顺序。

        生成内容里的图片位置是固定的（几段文字→图→几段文字），发布器应严格跟随
        原文标记位置配图，而不是自己重新均匀分布。这里先在原文中逐个定位图片标记，
        把标记前的文本清洗成纯文本块、标记本身按顺序映射到已物化的本地图片路径，
        最后补上尾部文本块与多余的图片。

        返回形如 [{"type": "text", "content": str} | {"type": "image", "content": str}]；
        原文没有图片标记、或没有可用图片时返回 None，由调用方回退到原有
        均匀分布 / 文末插图逻辑，保证老行为不被破坏。

        max_chars > 0 时对文本块总字符数做截断（从最后一个文本块尾部削减），
        图片位置不受影响。
        """
        if not content or not image_paths:
            return None
        markers = list(self.iter_image_markers(content))
        if not markers:
            return None

        blocks: list[dict[str, str]] = []
        image_index = 0
        last_end = 0
        seen_urls: set[str] = set()
        for match in markers:
            before = content[last_end : match.start()]
            clean_before = self.markdown_to_plain_text(before, drop_first_h1=not blocks)
            if clean_before:
                blocks.append({"type": "text", "content": clean_before})

            url = self.image_url_from_marker(match)
            if url:
                if url in seen_urls:
                    last_end = match.end()
                    continue
                seen_urls.add(url)
                if image_index < len(image_paths):
                    blocks.append({"type": "image", "content": image_paths[image_index]})
                image_index += 1
            last_end = match.end()

        after = (content or "")[last_end:]
        clean_after = self.markdown_to_plain_text(after, drop_first_h1=not blocks)
        if clean_after:
            blocks.append({"type": "text", "content": clean_after})

        while image_index < len(image_paths):
            blocks.append({"type": "image", "content": image_paths[image_index]})
            image_index += 1

        if not blocks:
            return None

        if max_chars and max_chars > 0:
            total_text = sum(len(b["content"]) for b in blocks if b["type"] == "text")
            if total_text > max_chars:
                for i in range(len(blocks) - 1, -1, -1):
                    if blocks[i]["type"] != "text":
                        continue
                    keep = max_chars - (total_text - len(blocks[i]["content"]))
                    if keep <= 0:
                        blocks.pop(i)
                    else:
                        blocks[i]["content"] = blocks[i]["content"][:keep]
                    break

        if not blocks:
            return None
        return blocks

    def markdown_to_plain_text(self, content: str, drop_first_h1: bool = True) -> str:
        """
        将 Markdown/简单 HTML 清理成适合平台编辑器粘贴的正文。
        这里输出纯文本，避免平台不解析 Markdown 时把 #、**、![图](url) 原样发布出去。
        """
        if not content:
            return ""

        text = content
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

        # 注意：标题/段落前后只保留 1 个换行，不要 \n\n。
        # 富文本编辑器（头条 ProseMirror、百家号 UEditor、知乎 Draft、搜狐 Quill 等）
        # 每个段落节点自带 margin；若这里再塞双换行，进入编辑器后会被解析成
        # 「空段落 + 硬换行」叠加，放大成页面上"段落中间巨大空栏"。
        # 历史上这里用的是 \n\n\1\n\n / \1\n\n，正是发布后空行过大的根因。
        text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n\1\n", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)

        lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                lines.append("")
                continue

            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading:
                if drop_first_h1 and not lines and len(heading.group(1)) == 1:
                    continue
                line = heading.group(2).strip()

            line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            line = re.sub(r"__(.*?)__", r"\1", line)
            line = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", line)
            line = re.sub(r"`([^`]+)`", r"\1", line)
            line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
            lines.append(line)

        cleaned: list[str] = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty:
                    cleaned.append("")
                prev_empty = True
            else:
                cleaned.append(line)
                prev_empty = False

        text = "\n".join(cleaned).strip()

        # 【最终兜底】不论前面规则怎么塞换行，最终输出里绝对不允许出现连续 2 个以上 \n。
        # 这是一道硬保险：即使某个调用方传入了奇葩 HTML、或 zhihu/xhs/... 各家内联旧版
        # 也漏了清理，最终进入平台编辑器（Draft.js / ProseMirror / Quill / Tiptap）的纯文本
        # 都只有单换行，杜绝"段落中间巨大空栏"再次出现。
        text = re.sub(r"\n{2,}", "\n", text)
        return text

    async def click_publish_button(self, page: Page, publish_selector: str) -> bool:
        """
        点击发布按钮
        """
        try:
            await page.click(publish_selector)
            logger.info(f"已点击发布按钮: {self.name}")
            return True
        except Exception as e:
            logger.error(f"点击发布按钮失败: {e}")
            return False

    async def wait_for_publish_result(self, page: Page, timeout: int = 30000) -> Dict[str, Any]:
        """
        等待发布结果

        Returns:
            发布结果
        """
        # 默认实现：等待一段时间后检查URL是否变化
        await page.wait_for_timeout(3000)

        result = {"success": True, "platform_url": page.url, "error_msg": None}

        return result


class PublisherRegistry:
    """
    发布器注册表
    用这个来管理所有平台的发布器！
    """

    def __init__(self):
        self._publishers: Dict[str, BasePublisher] = {}

    def register(self, platform_id: str, publisher: BasePublisher):
        """注册发布器。

        重复注册（如模块导入时已注册、启动时 register_publishers 再次注册）时
        静默覆盖，避免启动日志重复输出「发布器已注册: xxx」。
        """
        is_new = platform_id not in self._publishers
        self._publishers[platform_id] = publisher
        if is_new:
            logger.info(f"发布器已注册: {platform_id}")
        else:
            logger.debug(f"发布器已重新注册(覆盖): {platform_id}")

    def get(self, platform_id: str) -> Optional[BasePublisher]:
        """获取发布器"""
        return self._publishers.get(platform_id)

    def list_all(self) -> Dict[str, BasePublisher]:
        """列出所有发布器"""
        return self._publishers.copy()


# 全局注册表
registry = PublisherRegistry()


def get_publisher(platform_id: str) -> Optional[BasePublisher]:
    """
    获取平台发布器
    注意：这是对外暴露的主要接口！
    """
    return registry.get(platform_id)


def list_publishers() -> Dict[str, BasePublisher]:
    """列出所有发布器"""
    return registry.list_all()
