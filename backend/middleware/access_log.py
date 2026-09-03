# -*- coding: utf-8 -*-
"""
HTTP 访问日志中间件（纯 ASGI 实现，兼容 SSE 流式响应与 WebSocket）。

每条请求结束（或异常中断）时记录一行访问日志，字段包括：
请求方法、路径（query 自动脱敏）、响应状态码、耗时（毫秒）、
客户端 IP、用户（从 AuthMiddleware 注入的 request.state 读取）、request_id。

request_id 通过 log_setup.current_request_id 注入 contextvars，
使请求处理期间业务模块产生的所有日志都能与访问日志按同一 request_id 串联。

采用纯 ASGI（而非 BaseHTTPMiddleware）实现，避免缓冲/破坏 SSE 流式响应；
WebSocket 连接由 websocket_manager 自行记录，此处直接透传。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from loguru import logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.log_setup import current_request_id, current_user

# 静态资源：全部跳过（噪音太大）
_SKIP_PREFIXES: tuple[str, ...] = ("/static/",)
# 前端高频轮询路径：降为 DEBUG，避免刷屏
_QUIET_PATHS: frozenset = frozenset({"/api/health"})
# query 参数脱敏关键字
_SENSITIVE_KEYS: tuple[str, ...] = ("token", "secret", "password", "key", "authorization", "cookie")


def _client_ip(scope: Scope) -> str:
    """解析客户端 IP（优先 X-Forwarded-For / X-Real-IP，兼容反代部署）。"""
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-for":
            return value.decode("latin-1", errors="ignore").split(",")[0].strip() or "-"
        if name == b"x-real-ip":
            return value.decode("latin-1", errors="ignore").strip() or "-"
    client = scope.get("client")
    return client[0] if client else "-"


def _safe_path(scope: Scope) -> str:
    """路径 + query（query 中的敏感参数替换为 ***）。"""
    path = scope.get("path", "") or ""
    query = scope.get("query_string", b"")
    if not query:
        return path
    parts: list[str] = []
    for pair in query.decode("latin-1", errors="ignore").split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            if any(s in key.lower() for s in _SENSITIVE_KEYS):
                parts.append(f"{key}=***")
            else:
                parts.append(pair)
        else:
            parts.append(pair)
    return f"{path}?{'&'.join(parts)}"


class AccessLogMiddleware:
    """记录每个 HTTP 请求的访问日志（方法/路径/状态/耗时/IP/用户/request_id）。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # WebSocket / lifespan：交给下游处理（连接日志由 websocket_manager 记录）
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        if path.startswith(_SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        ip = _client_ip(scope)
        start = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]
        rid_token = current_request_id.set(request_id)

        status_holder: dict[str, int] = {"status": 0}
        error_during_call = False

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # 异常已由 FastAPI 全局异常处理器记录细节，这里只补访问日志状态
            error_during_call = True
            status_holder["status"] = 500
            raise
        finally:
            # 在 request/user 上下文仍绑定时发出本行访问日志（异常路径同样记录）
            status = status_holder["status"] or (500 if error_during_call else 499)
            duration_ms = (time.perf_counter() - start) * 1000

            # 用户信息（AuthMiddleware 已把用户写入 request.state / scope["state"]）
            user_label = "-"
            try:
                state = scope.get("state")
                if state is not None:
                    username = getattr(state, "username", None)
                    user_id = getattr(state, "user_id", None)
                    if username:
                        user_label = f"{username}({user_id})" if user_id is not None else str(username)
            except Exception:
                user_label = "-"

            user_token = current_user.set(user_label)
            try:
                if status >= 500:
                    logger.error(
                        f"[ACCESS] {method} {_safe_path(scope)} -> {status} "
                        f"{duration_ms:.1f}ms ip={ip} user={user_label} req={request_id}"
                    )
                elif status >= 400:
                    logger.warning(
                        f"[ACCESS] {method} {_safe_path(scope)} -> {status} "
                        f"{duration_ms:.1f}ms ip={ip} user={user_label} req={request_id}"
                    )
                elif path in _QUIET_PATHS:
                    logger.debug(
                        f"[ACCESS] {method} {_safe_path(scope)} -> {status} "
                        f"{duration_ms:.1f}ms ip={ip} user={user_label} req={request_id}"
                    )
                else:
                    logger.info(
                        f"[ACCESS] {method} {_safe_path(scope)} -> {status} "
                        f"{duration_ms:.1f}ms ip={ip} user={user_label} req={request_id}"
                    )
            finally:
                current_user.reset(user_token)
                current_request_id.reset(rid_token)
