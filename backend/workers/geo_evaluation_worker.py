# -*- coding: utf-8 -*-
"""Run one GEO evaluation task on the user's computer.

The Electron main process owns task polling and starts one worker process for
each claimed platform run. This module owns all Playwright interaction.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

# ==================== 日志初始化（必须先于任何会触发日志的导入） ====================
# 本模块只由专用 runner（scripts/geo_evaluation_worker_runner.py）作为独立进程导入。
# worker 的 stdout 承载 JSON 事件协议：日志只写文件（auto_geo_worker_*.log），
# 初始化放在模块顶部以捕获导入期的日志（发布器注册等）。
from loguru import logger  # noqa: E402

from backend.log_setup import setup_worker_logging  # noqa: E402

setup_worker_logging()

import httpx  # noqa: E402
from playwright.async_api import Browser, BrowserContext, Page, async_playwright  # noqa: E402

from backend.config import AI_PLATFORMS, BROWSER_ARGS  # noqa: E402
from backend.services.local_browser_bridge import local_browser_bridge  # noqa: E402
from backend.services.playwright.ai_platforms import DeepSeekChecker, DoubaoChecker, QianwenChecker  # noqa: E402
from backend.services.playwright.risk_detector import RiskDetection, risk_detector  # noqa: E402

# worker 日志统一绑定（只写文件，stdout 承载 JSON 事件协议）
log = logger.bind(module="测评Worker")


CHECKERS = {
    "doubao": DoubaoChecker,
    "qianwen": QianwenChecker,
    "deepseek": DeepSeekChecker,
}


class RetryCurrentQuestion(Exception):
    """The browser context changed after manual handling; retry without consuming an attempt."""


class WorkerCancelled(Exception):
    """The backend marked this run as cancelled."""


def emit(event: str, **data: Any) -> None:
    payload = json.dumps({"event": event, **data}, ensure_ascii=False)
    log.debug(f"[worker-event] {event}: {payload[:800]}")
    print(payload, flush=True)


class WorkerApi:
    def __init__(self, server: str, token: str, device_id: str, run_id: int):
        self.device_id = device_id
        self.run_id = run_id
        server_url = server.rstrip("/")
        server_host = (urlsplit(server_url).hostname or "").lower()
        is_local_server = server_host in {"127.0.0.1", "localhost", "::1"}
        self.client = httpx.AsyncClient(
            base_url=server_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
            # Windows proxy tools commonly expose a system HTTP proxy without
            # excluding loopback addresses.  A local worker must reach the
            # local FastAPI service directly; otherwise /payload can be sent to
            # the proxy and time out before it ever reaches port 8001.
            trust_env=not is_local_server,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = None
        for attempt in range(1, 4):
            try:
                response = await self.client.request(method, path, **kwargs)
                break
            except httpx.TransportError as exc:
                if attempt >= 3:
                    raise RuntimeError(f"本地后端请求失败 {method} {path}: {type(exc).__name__}: {exc!r}") from exc
                emit(
                    "backend_request_retry",
                    method=method,
                    path=path,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error=repr(exc),
                )
                await asyncio.sleep(attempt)
        if response is None:
            raise RuntimeError(f"本地后端请求未返回响应 {method} {path}")
        if response.is_error:
            detail = response.text
            try:
                body = response.json()
                detail = body.get("detail") or body.get("message") or detail
            except Exception:
                pass
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")
        body = response.json()
        return body.get("data", body)

    async def payload(self) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/api/client/geo-evaluation/runs/{self.run_id}/payload",
            params={"device_id": self.device_id},
        )

    async def heartbeat(self) -> str:
        data = await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/heartbeat",
            json={"device_id": self.device_id},
        )
        return (data.get("run") or {}).get("status", "")

    async def mark_manual(self, platform: str, detection: RiskDetection) -> None:
        await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/manual-required",
            json={
                "device_id": self.device_id,
                "platform": platform,
                "message": detection.message or "平台需要人工处理",
                "error_code": detection.error_code,
                "risk_type": detection.risk_type,
            },
        )

    async def mark_manual_resolved(self, platform: str) -> None:
        await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/manual-resolved",
            json={"device_id": self.device_id, "platform": platform},
        )

    async def interrupt(self, message: str, reason: str) -> None:
        await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/interrupt",
            json={
                "device_id": self.device_id,
                "message": message,
                "reason": reason,
            },
        )

    async def save_session(self, platform: str, storage_state: dict[str, Any]) -> None:
        await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/session-state",
            json={
                "device_id": self.device_id,
                "platform": platform,
                "storage_state": storage_state,
            },
        )

    async def save_result(
        self,
        platform: str,
        prompt: dict[str, Any],
        round_no: int,
        result: dict[str, Any],
    ) -> None:
        await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/record-result",
            json={
                "device_id": self.device_id,
                "prompt_id": prompt["id"],
                "platform": platform,
                "round_no": round_no,
                "question": prompt["question"],
                "success": result["success"],
                "answer": result.get("answer"),
                "citations": [],
                "error_msg": result.get("error"),
                "context_cleaned": True,
                "capture_method": result.get("method"),
                "attempt_count": result.get("attempt_count", 1),
            },
        )

    async def finish(self, status: str, error: Optional[str] = None) -> None:
        await self.request(
            "POST",
            f"/api/client/geo-evaluation/runs/{self.run_id}/finish",
            json={"device_id": self.device_id, "status": status, "error_msg": error},
        )


class GeoEvaluationWorker:
    def __init__(self, api: WorkerApi, platform: str, default_mode: str, local_session_path: Optional[str] = None):
        self.api = api
        self.platform = platform
        self.default_mode = default_mode
        self.checker = CHECKERS[platform](platform, AI_PLATFORMS[platform])
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.storage_state: Optional[dict[str, Any]] = None
        self.cancelled = False
        self.local_session_path = Path(local_session_path) if local_session_path else None
        self.manual_recheck = asyncio.Event()

    async def run(self) -> None:
        payload = await self.api.payload()
        self.storage_state = (payload.get("platform_sessions") or {}).get(self.platform)
        # 判断服务器 session 是否有效：必须有 cookies 或 origins
        server_session_valid = bool(
            self.storage_state and (self.storage_state.get("cookies") or self.storage_state.get("origins"))
        )
        if not server_session_valid:
            emit(
                "server_session_invalid",
                platform=self.platform,
                has_state=bool(self.storage_state),
                cookie_count=len(self.storage_state.get("cookies", [])) if self.storage_state else 0,
                origin_count=len(self.storage_state.get("origins", [])) if self.storage_state else 0,
            )
        # 服务器 session 无效时，回退读取本地授权会话文件
        if not server_session_valid and self.local_session_path and self.local_session_path.exists():
            try:
                local_state = json.loads(self.local_session_path.read_text(encoding="utf-8"))
                if local_state and (local_state.get("cookies") or local_state.get("origins")):
                    self.storage_state = local_state
                    emit(
                        "session_loaded_from_local",
                        path=str(self.local_session_path),
                        cookie_count=len(local_state.get("cookies", [])),
                        origin_count=len(local_state.get("origins", [])),
                    )
                else:
                    emit("session_local_file_empty", path=str(self.local_session_path))
            except Exception as exc:
                emit("session_local_load_failed", path=str(self.local_session_path), error=str(exc))
        if not self.storage_state or not (self.storage_state.get("cookies") or self.storage_state.get("origins")):
            emit("session_missing", platform=self.platform, reason="server_and_local_both_empty")
        timing = payload.get("timing") or {}
        completed = set(payload.get("completed_keys") or [])
        prompts = payload.get("prompts") or []
        rounds = max(1, int((payload.get("run") or {}).get("rounds") or 1))
        total = len(prompts) * rounds
        done = len(completed)
        emit(
            "worker_started",
            platform=self.platform,
            mode=self.default_mode,
            total=total,
            session_loaded=bool(self.storage_state),
        )

        self.playwright = await async_playwright().start()
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        commands = asyncio.create_task(self._command_loop())
        try:
            await self._start_browser(self.default_mode)
            for round_no in range(1, rounds + 1):
                for prompt in prompts:
                    key = f"{self.api.run_id}:{self.platform}:{round_no}:{prompt['id']}"
                    if key in completed:
                        continue
                    if self.cancelled:
                        emit("cancelled", run_id=self.api.run_id)
                        return
                    emit(
                        "question_started",
                        platform=self.platform,
                        prompt_id=prompt["id"],
                        current=done + 1,
                        total=total,
                        question=prompt["question"][:80],
                    )
                    try:
                        result = await self._ask_with_retries(
                            prompt["question"],
                            max_attempts=int(timing.get("maxAttempts") or 3),
                            retry_min=int(timing.get("retryDelayMinMs") or 10000),
                            retry_max=int(timing.get("retryDelayMaxMs") or 15000),
                        )
                    except WorkerCancelled:
                        emit("cancelled", run_id=self.api.run_id)
                        return
                    await self.api.save_result(self.platform, prompt, round_no, result)
                    done += 1
                    emit(
                        "answer_uploaded",
                        platform=self.platform,
                        prompt_id=prompt["id"],
                        current=done,
                        total=total,
                        success=result["success"],
                        method=result.get("method"),
                    )
                    await self._sleep_interruptible(
                        random.randint(
                            int(timing.get("questionDelayMinMs") or 10000),
                            int(timing.get("questionDelayMaxMs") or 15000),
                        )
                        / 1000
                    )
            await self.api.finish("completed")
            emit("completed", run_id=self.api.run_id, total=total)
        finally:
            heartbeat.cancel()
            commands.cancel()
            await self._close_browser()
            if self.playwright:
                await self.playwright.stop()

    async def _start_browser(self, mode: str) -> None:
        chrome = local_browser_bridge.find_chrome()
        options: dict[str, Any] = {
            "headless": mode == "headless",
            "args": BROWSER_ARGS,
            "timeout": 30000,
        }
        if chrome:
            options["executable_path"] = chrome
        self.browser = await self.playwright.chromium.launch(**options)
        state = self._playwright_storage_state(self.storage_state)
        self.context = await self.browser.new_context(
            storage_state=state,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
        )
        platform_url = urlsplit(AI_PLATFORMS[self.platform]["url"])
        await self.context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin=f"{platform_url.scheme}://{platform_url.netloc}",
        )
        emit("browser_started", platform=self.platform, mode=mode, session_loaded=bool(state))

    async def _close_browser(self) -> None:
        if self.context:
            try:
                self.storage_state = await self.context.storage_state()
            except Exception:
                pass
            await self.context.close()
        if self.browser:
            await self.browser.close()
        self.context = None
        self.browser = None

    @staticmethod
    def _playwright_storage_state(state: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not state:
            return None
        return {
            "cookies": state.get("cookies") if isinstance(state.get("cookies"), list) else [],
            "origins": state.get("origins") if isinstance(state.get("origins"), list) else [],
        }

    async def _ask_with_retries(
        self,
        question: str,
        max_attempts: int,
        retry_min: int,
        retry_max: int,
    ) -> dict[str, Any]:
        last_error = ""
        attempt = 1
        while attempt <= max_attempts:
            if self.cancelled:
                raise WorkerCancelled()
            try:
                result = await self._ask_once(question)
                result["attempt_count"] = attempt
                return result
            except RetryCurrentQuestion:
                emit("question_restarted_after_manual", attempt=attempt)
                continue
            except WorkerCancelled:
                raise
            except Exception as exc:
                last_error = str(exc)
                emit("question_attempt_failed", attempt=attempt, error=last_error)
                if attempt < max_attempts:
                    await self._sleep_interruptible(random.randint(retry_min, retry_max) / 1000)
                attempt += 1
        return {"success": False, "error": last_error or "当前问题执行失败", "attempt_count": max_attempts}

    async def _ask_once(self, question: str) -> dict[str, Any]:
        page = await self.context.new_page()
        try:
            await self.checker.navigate_to_page(page)
            await self._guard(page, "进入平台后")
            input_selector = await self._find_input(page)
            before = await self.checker.get_message_snapshot(page)
            # DeepSeek的 ds-button 是全站通用类，侧栏搜索、模式按钮和发送按钮都会匹配。
            # 输入框保持焦点后直接按Enter，避免误点“搜索对话内容”。
            submit_selector = (
                None if self.platform == "deepseek" else (self.checker.SELECTORS.get("submit_button") or [None])[0]
            )
            if not await self.checker.submit_question(page, question, input_selector, submit_selector):
                raise RuntimeError("发送问题失败")
            await self._confirm_question_sent(page, question, before)
            await self._guard(page, "发送问题后", question=question)
            answer = await self._wait_and_capture(page, question, before)
            if not answer.get("success"):
                raise RuntimeError(answer.get("error_msg") or "未获取到完整回答")
            return {
                "success": True,
                "answer": answer["answer"],
                "method": answer.get("method") or "dom",
            }
        finally:
            await page.close()

    async def _find_input(self, page: Page) -> str:
        if self.platform == "doubao":
            # 豆包页面存在 class/id 带 editor/input 的普通外层 div，不能用于输入。
            # 这里只接受浏览器确认可编辑的真实 textarea/contenteditable。
            candidates = [
                "textarea[placeholder='发消息或按住空格说话']",
                "textarea[placeholder*='发消息']",
                "textarea[placeholder*='输入']",
                "textarea[data-testid*='input']",
                "div[contenteditable='true'][role='textbox']",
                "div[contenteditable='true']",
            ]
            deadline = asyncio.get_running_loop().time() + 20
            while asyncio.get_running_loop().time() < deadline:
                for selector in candidates:
                    elements = page.locator(selector)
                    for index in range(await elements.count()):
                        element = elements.nth(index)
                        if await element.is_visible() and await element.is_editable():
                            emit("input_found", platform=self.platform, selector=selector)
                            return selector
                await asyncio.sleep(0.25)
            raise RuntimeError("未找到豆包可编辑输入框")

        found, selector = await self.checker.wait_for_selector(
            page,
            self.checker.SELECTORS["input_box"],
            timeout=20000,
        )
        if not found or not selector:
            raise RuntimeError("未找到平台输入框")
        return selector

    async def _confirm_question_sent(self, page: Page, question: str, before: Optional[dict[str, Any]] = None) -> None:
        deadline = asyncio.get_running_loop().time() + 30
        exact = page.get_by_text(question, exact=True)
        excerpt = page.get_by_text(question[:40], exact=False)
        while asyncio.get_running_loop().time() < deadline:
            before_url = (before or {}).get("url") or ""
            if self.platform == "doubao" and page.url != before_url and "/chat/" in page.url:
                emit("question_confirmed", platform=self.platform, method="chat_url")
                return
            for locator in (exact, excerpt):
                count = await locator.count()
                for index in range(count - 1, -1, -1):
                    if await locator.nth(index).is_visible():
                        emit("question_confirmed", platform=self.platform)
                        return
            await asyncio.sleep(0.25)
        raise RuntimeError("未在聊天区确认当前问题已发送")

    async def _wait_and_capture(
        self,
        page: Page,
        question: str,
        before: dict[str, Any],
    ) -> dict[str, Any]:
        last_text = ""
        stable = 0
        started_at = asyncio.get_running_loop().time()
        required_stable_checks = 7
        min_wait_seconds = 8
        for _ in range(120):
            if self.cancelled:
                raise WorkerCancelled()
            await asyncio.sleep(1)
            await self._guard(page, "发送问题后", question=question)
            generating = await self._is_generating(page)
            candidate = await self.checker._extract_visible_answer_candidate(
                page,
                question,
                before.get("bodyText") or "",
                int(before.get("messageCount") or 0),
            )
            text = (candidate.get("answer") or "").strip()
            if not text and self.platform != "doubao":
                platform_candidate = await self.checker.get_answer_content(page, question)
                if platform_candidate.get("success"):
                    text = (platform_candidate.get("answer") or "").strip()
            quality = self.checker.validate_answer_quality(text, question) if text else {"valid": False}
            existed_before = bool(text and text in (before.get("bodyText") or ""))
            if text and quality.get("valid") and not existed_before and not generating:
                stable = stable + 1 if text == last_text else 1
                last_text = text
            else:
                stable = 0
                if text:
                    last_text = text
            waited_seconds = asyncio.get_running_loop().time() - started_at
            if stable < required_stable_checks or waited_seconds < min_wait_seconds:
                continue
            await asyncio.sleep(2)
            await self._guard(page, "发送问题后", question=question)
            if await self._is_generating(page):
                stable = 0
                continue
            final_candidate = await self.checker._extract_visible_answer_candidate(
                page,
                question,
                before.get("bodyText") or "",
                int(before.get("messageCount") or 0),
            )
            final_text = (final_candidate.get("answer") or "").strip()
            final_quality = (
                self.checker.validate_answer_quality(final_text, question) if final_text else {"valid": False}
            )
            if final_quality.get("valid") and final_text not in (before.get("bodyText") or ""):
                if len(final_text) > len(text):
                    text = final_text
                    last_text = final_text
                    stable = 1
                    continue
            emit("answer_stable", length=len(text))
            copied = await self._copy_answer(page, question)
            if copied:
                return {"success": True, "answer": copied, "method": "clipboard"}
            dom = await self.checker.get_answer_content(page, question)
            dom_text = (dom.get("answer") or "").strip() if dom.get("success") else ""
            dom_quality = self.checker.validate_answer_quality(dom_text, question) if dom_text else {"valid": False}
            if dom_quality.get("valid") and dom_text not in (before.get("bodyText") or ""):
                return {"success": True, "answer": dom_text, "method": "dom"}
            return {"success": True, "answer": text, "method": "dom-visible-candidate"}
        return await self.checker.capture_answer(page, question, before, timeout_ms=5000)

    async def _copy_answer(self, page: Page, question: str) -> str:
        selectors = {
            "doubao": ".bp5-overflow-list > button",
            "qianwen": '[role="menuitem"]:has-text("复制为Markdown")',
            "deepseek": 'button:has-text("复制"), [role="button"]:has-text("复制")',
        }
        buttons = page.locator(selectors[self.platform])
        button = buttons.first if self.platform == "doubao" else buttons.last
        if await button.count() == 0:
            return ""
        original = ""
        try:
            original = await page.evaluate("navigator.clipboard.readText()")
            await button.click(timeout=3000)
            await asyncio.sleep(0.3)
            text = await page.evaluate("navigator.clipboard.readText()")
            quality = self.checker.validate_answer_quality(text or "", question)
            return text.strip() if quality.get("valid") else ""
        except Exception:
            return ""
        finally:
            try:
                await page.evaluate("(text) => navigator.clipboard.writeText(text)", original)
            except Exception:
                pass

    async def _is_generating(self, page: Page) -> bool:
        return bool(
            await page.evaluate(
                """() => {
                    const text = (document.body?.innerText || '');
                    return ['停止生成', '思考中', '生成中', '正在生成'].some(x => text.includes(x));
                }"""
            )
        )

    async def _guard(self, page: Page, stage: str, question: Optional[str] = None) -> None:
        if self.cancelled:
            raise WorkerCancelled()
        detection = await risk_detector.detect(page, platform=self.platform, stage=stage)
        if not detection.manual_required:
            return
        if detection.risk_type == "account_restricted":
            details = detection.matched_text or detection.message or "平台账号已被限制使用"
            platform_name = {
                "doubao": "豆包",
                "qianwen": "通义千问",
                "deepseek": "DeepSeek",
            }.get(self.platform, self.platform)
            message = f"{platform_name} 遇到账号风控，执行服务已关闭，请处理：{details}"
            await self.api.interrupt(message, "account_restricted")
            emit(
                "task_interrupted",
                platform=self.platform,
                stage=stage,
                error_code=detection.error_code,
                risk_type=detection.risk_type,
                message=message,
            )
            self.cancelled = True
            raise WorkerCancelled()
        if await self._should_ignore_soft_manual_detection(page, detection):
            emit(
                "manual_detection_ignored",
                platform=self.platform,
                stage=stage,
                error_code=detection.error_code,
                risk_type=detection.risk_type,
                matched_text=detection.matched_text,
                reason="authenticated chat surface is usable and no blocking manual surface is visible",
            )
            return
        await self.api.mark_manual(self.platform, detection)
        emit(
            "manual_required",
            platform=self.platform,
            stage=stage,
            error_code=detection.error_code,
            risk_type=detection.risk_type,
            message=detection.message,
            matched_text=detection.matched_text,
        )
        await self._close_browser()
        await self._start_browser("headed")
        manual_page = await self.context.new_page()
        try:
            await self.checker.navigate_to_page(manual_page)
            await self._advance_manual_page_to_risk_stage(manual_page, stage, question)
            while not self.cancelled:
                try:
                    await asyncio.wait_for(self.manual_recheck.wait(), timeout=3)
                except asyncio.TimeoutError:
                    pass
                self.manual_recheck.clear()
                current = await risk_detector.detect(
                    manual_page,
                    platform=self.platform,
                    stage="人工处理",
                )
                authenticated = not current.manual_required and await self._has_authenticated_surface(manual_page)
                emit(
                    "manual_check",
                    platform=self.platform,
                    manual_required=current.manual_required,
                    error_code=current.error_code,
                    authenticated=authenticated,
                )
                if authenticated:
                    state = await self.context.storage_state()
                    state["browser_verified_login"] = {
                        "platform": self.platform,
                        "verified_at": time.time(),
                        "method": "dom",
                        "reason": "manual headed browser confirmed authenticated surface",
                    }
                    await self.api.save_session(self.platform, state)
                    self._save_local_session(state)
                    self.storage_state = state
                    await self.api.mark_manual_resolved(self.platform)
                    emit("manual_resolved", platform=self.platform)
                    break
        finally:
            await manual_page.close()
        if self.default_mode != "headed":
            await self._close_browser()
            await self._start_browser(self.default_mode)
        if self.cancelled:
            raise WorkerCancelled()
        raise RetryCurrentQuestion()

    async def _advance_manual_page_to_risk_stage(
        self,
        page: Page,
        stage: str,
        question: Optional[str],
    ) -> None:
        """Drive the headed manual browser to the same point where risk appeared.

        A challenge often appears only after clicking Send. If we merely open the
        platform and wait, the user sees a normal chat page and has nothing to
        handle. For post-send risk stages, replay the current question in the
        headed browser so the real challenge can surface.
        """
        if not question:
            return
        stage_text = stage or ""
        if "发送" not in stage_text and "回答" not in stage_text:
            return

        initial = await risk_detector.detect(page, platform=self.platform, stage="人工处理-进入平台后")
        if initial.manual_required and await self._has_blocking_manual_surface(page):
            return

        try:
            emit("manual_replay_started", platform=self.platform, stage=stage)
            input_selector = await self._find_input(page)
            submit_selector = (
                None if self.platform == "deepseek" else (self.checker.SELECTORS.get("submit_button") or [None])[0]
            )
            if await self.checker.submit_question(page, question, input_selector, submit_selector):
                try:
                    await self._confirm_question_sent(page, question)
                except Exception as exc:
                    emit("manual_replay_question_unconfirmed", platform=self.platform, error=str(exc))
                await asyncio.sleep(1)
                emit("manual_replay_finished", platform=self.platform, stage=stage)
        except Exception as exc:
            emit("manual_replay_failed", platform=self.platform, stage=stage, error=str(exc))

    async def _should_ignore_soft_manual_detection(self, page: Page, detection: RiskDetection) -> bool:
        """Ignore false-positive AI chat risk markers that do not block automation.

        Doubao/Qianwen/DeepSeek often keep login/captcha/verify class names in
        normal page chrome. If the authenticated chat surface is still usable
        and there is no visible blocking challenge, restarting the browser just
        creates a tight false-positive loop.
        """
        if self.platform not in {"doubao", "qianwen", "deepseek"}:
            return False
        if detection.risk_type in {
            "rate_limited",
            "account_abnormal",
            "account_restricted",
            "sms_verify_required",
        }:
            return False
        if not await self._has_authenticated_surface(page):
            return False
        return not await self._has_blocking_manual_surface(page)

    async def _has_blocking_manual_surface(self, page: Page) -> bool:
        try:
            return bool(
                await page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0
                                && rect.height > 0
                                && style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && Number(style.opacity || '1') > 0.01;
                        };
                        const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        const hasManualText = (text) =>
                            /验证码|安全验证|身份验证|短信验证|手机验证|人机验证|拖动|滑块|扫码|登录后|请登录|captcha|verify|verification|security check/i.test(text);
                        const isBlocking = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            const text = textOf(el);
                            const hasChallengeControl = Boolean(
                                el.querySelector("input[type='password'], input, canvas, iframe[src*='captcha'], iframe[src*='verify'], [class*='geetest'], [class*='captcha'], [class*='verify']")
                            );
                            const dialogLike = Boolean(el.closest("[role='dialog'], [class*='modal'], [class*='mask'], [class*='overlay']"))
                                || el.getAttribute('role') === 'dialog'
                                || /modal|mask|overlay|dialog|captcha|verify/i.test(String(el.className || '') + ' ' + String(el.id || ''));
                            const fixedHighLayer = style.position === 'fixed'
                                && Number.parseInt(style.zIndex || '0', 10) >= 100;
                            const centeredPanel = rect.width >= 260
                                && rect.height >= 120
                                && rect.left > 20
                                && rect.top > 20
                                && rect.right < window.innerWidth - 20;
                            const iframeChallenge = el.tagName.toLowerCase() === 'iframe'
                                && /captcha|verify|geetest|risk/i.test(el.getAttribute('src') || '');
                            return iframeChallenge
                                || ((dialogLike || fixedHighLayer || centeredPanel) && hasManualText(text) && hasChallengeControl);
                        };
                        return Array.from(document.querySelectorAll("body *")).some((el) => visible(el) && isBlocking(el));
                    }"""
                )
            )
        except Exception:
            return True

    def _save_local_session(self, state: dict[str, Any]) -> None:
        if not self.local_session_path:
            return
        self.local_session_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_session_path.with_suffix(f"{self.local_session_path.suffix}.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.local_session_path)

    async def _has_authenticated_surface(self, page: Page) -> bool:
        return bool(
            await page.evaluate(
                """(platform) => {
                    const visible = el => {
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                    };
                    const login = Array.from(document.querySelectorAll('button,a'))
                        .some(el => visible(el) && (el.innerText || '').trim() === '登录');
                    const account = Array.from(document.querySelectorAll(
                        '[data-e2e*="user"], [class*="avatar"], [class*="user-info"], [class*="account"]'
                    )).some(visible);
                    const input = Array.from(document.querySelectorAll(
                        'textarea, [contenteditable="true"], [role="textbox"]'
                    )).some(visible);
                    const bodyText = document.body?.innerText || '';
                    const platformSignal = platform === 'doubao'
                        ? bodyText.includes('新对话')
                        : platform === 'qianwen'
                            ? bodyText.includes('新建对话') || bodyText.includes('历史对话')
                            : bodyText.includes('New chat') || bodyText.includes('新对话');
                    return !login && input && (account || platformSignal);
                }""",
                self.platform,
            )
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                status = await self.api.heartbeat()
                if status in {"cancelled", "interrupted"}:
                    self.cancelled = True
                    return
            except Exception as exc:
                emit("heartbeat_failed", error=str(exc))

    async def _command_loop(self) -> None:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                return
            try:
                command = json.loads(line)
            except json.JSONDecodeError:
                continue
            if command.get("command") == "recheck_manual":
                self.manual_recheck.set()
                emit("manual_recheck_requested")

    async def _sleep_interruptible(self, seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + seconds
        while not self.cancelled and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(min(0.5, deadline - asyncio.get_running_loop().time()))


async def async_main(args: argparse.Namespace) -> int:
    log.info(
        f"[worker] 任务开始: run_id={args.run_id} platform={args.platform} "
        f"mode={args.mode} device={args.device_id} server={args.server}"
    )
    token = os.getenv("AUTOGEO_WORKER_TOKEN", "")
    if not token:
        log.error(f"[worker] 缺少 AUTOGEO_WORKER_TOKEN: run_id={args.run_id}")
        raise RuntimeError("AUTOGEO_WORKER_TOKEN is missing")
    api = WorkerApi(args.server, token, args.device_id, args.run_id)
    worker = GeoEvaluationWorker(api, args.platform, args.mode, args.session_path)
    try:
        await worker.run()
        log.success(f"[worker] 任务完成: run_id={args.run_id}")
        return 0
    except Exception as exc:
        log.exception(f"[worker] 任务执行失败: run_id={args.run_id}, error={exc}")
        emit(
            "worker_failed",
            error=str(exc) or repr(exc),
            error_type=type(exc).__name__,
            traceback="".join(traceback.format_exception(exc))[-4000:],
        )
        try:
            await api.request(
                "POST",
                f"/api/client/geo-evaluation/runs/{args.run_id}/interrupt",
                json={
                    "device_id": args.device_id,
                    "message": str(exc),
                    "reason": "client_error",
                },
            )
        except Exception:
            pass
        return 1
    finally:
        await api.close()
        log.info(f"[worker] API 客户端已关闭: run_id={args.run_id}")


def main() -> None:
    # 日志已在模块顶部初始化（setup_worker_logging）：只写文件，stdout 保持纯 JSON 协议
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--platform", choices=sorted(CHECKERS), required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--mode", choices=["headed", "headless"], default="headed")
    parser.add_argument("--session-path")
    args = parser.parse_args()
    log.info(
        f"[worker] 进程启动: run_id={args.run_id} platform={args.platform} mode={args.mode} device={args.device_id}"
    )
    try:
        code = asyncio.run(async_main(args))
    except Exception as exc:
        log.exception(f"[worker] 进程级崩溃: run_id={args.run_id}")
        emit(
            "worker_failed",
            error=str(exc) or repr(exc),
            error_type=type(exc).__name__,
            traceback="".join(traceback.format_exception(exc))[-4000:],
        )
        code = 1
    log.info(f"[worker] 进程退出: run_id={args.run_id} exit_code={code}")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
