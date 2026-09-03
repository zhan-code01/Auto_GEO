# -*- coding: utf-8 -*-
"""
全局认证中间件
================

职责：
1. 拦截所有 /api/* 请求，强制验证 JWT Token（白名单除外）
2. 解码 Token，将当前用户信息注入 request.state
3. 将 user_id 存入 contextvars，供 SQLAlchemy 事件监听器自动填充 user_id

设计原则：
- 不修改任何已有路由处理函数的代码
- 白名单端点（login/register/health等）不受影响
- 管理员可跨用户查看数据（由路由层自行决定）
"""

import contextvars
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from backend.api.user import decode_token
from backend.database import SessionLocal
from backend.database.models import User
from backend.log_setup import current_user as log_current_user

# ==================== 白名单配置 ====================

# 精确匹配：这些路径完全不需要认证
PUBLIC_PATHS: set = {
    "/",
    "/api/health",
    "/api/platforms",
    "/api/users/register",
    "/api/users/login",
    # Chrome 扩展 cookie-sync 使用的内部端点（浏览器扩展不带用户 JWT）
    "/api/auth/request-sync",
    "/api/auth/sync-requests",
    # 飞书机器人 Webhook 回调（飞书服务器推送，不带用户 JWT）
    "/api/feishu/webhook",
    # 客户端安装包下载（浏览器直接导航下载，不带用户 JWT）
    "/api/client/latest",
    "/api/client/download",
    # 智能建站 /api/sites/build、/api/sites/deploy 已改为需要登录：
    # 前端统一走 services/api 封装自动带 JWT，避免部署接口被匿名刷。
    # 预览与图片等静态资源仍通过下方 PUBLIC_PREFIXES 的 /static 公开访问。
}

# 前缀匹配：以这些前缀开头的路径不需要认证
PUBLIC_PREFIXES: tuple = (
    "/static",
    "/ws",
    "/docs",
    "/openapi.json",
    "/redoc",
    # 外部集成回调（由外部服务调用，不带用户 JWT）
    "/api/v1/collect",
    "/api/integrations",
)

# ==================== 用户上下文（contextvars） ====================

# 当前请求的用户 ID —— 供 SQLAlchemy 事件监听器等底层代码使用
# 用法: current_user_id.get() → Optional[int]
current_user_id: contextvars.ContextVar = contextvars.ContextVar("current_user_id", default=None)

# 当前请求的用户名
current_username: contextvars.ContextVar = contextvars.ContextVar("current_username", default=None)


# ==================== 中间件 ====================


class AuthMiddleware(BaseHTTPMiddleware):
    """
    全局认证中间件

    对 /api/* 路径强制执行 JWT 验证。
    白名单内的路径直接放行。
    验证通过后将用户信息写入 request.state 和 contextvars。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # ---- 1. 白名单精确匹配 ----
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # ---- 2. 白名单前缀匹配 ----
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # ---- 3. CORS 预检请求直接放行（OPTIONS 不带 Authorization） ----
        if request.method == "OPTIONS":
            return await call_next(request)

        # ---- 4. 只拦截 /api/ 路径 ----
        if not path.startswith("/api/"):
            return await call_next(request)

        # ---- 5. 提取并验证 Token ----
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(f"[Auth] 缺少 Token: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "请先登录",
                    "detail": "未提供认证令牌",
                },
            )

        token = auth_header.replace("Bearer ", "").strip()
        payload = decode_token(token)
        if not payload:
            logger.warning(f"[Auth] Token 无效: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "登录已过期，请重新登录",
                    "detail": "无效或过期的认证令牌",
                },
            )

        user_id = payload.get("user_id")
        username = payload.get("username", "unknown")
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "请重新登录",
                    "detail": "无效的令牌内容",
                },
            )

        # ---- 5. 验证用户状态（快速 DB 查询） ----
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                logger.warning(f"[Auth] 用户不存在: user_id={user_id}")
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "message": "用户不存在",
                        "detail": "用户已被删除",
                    },
                )

            if not user.is_active:
                logger.warning(f"[Auth] 用户已禁用: {username}")
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "message": "账户已被禁用",
                        "detail": "用户已被禁用，请联系管理员",
                    },
                )

            # ---- 6. 注入用户信息到 request.state ----
            request.state.user = user
            request.state.user_id = user.id
            request.state.username = user.username
            request.state.is_admin = user.role == "admin"

        finally:
            db.close()

        # ---- 7. 设置 contextvars（供 SQLAlchemy 事件 / 日志 patcher 使用） ----
        token_ctx = current_user_id.set(user_id)
        name_ctx = current_username.set(username)
        user_log_ctx = log_current_user.set(f"{username}({user_id})")

        try:
            response = await call_next(request)
        finally:
            # 恢复 contextvars 避免泄漏到下一个请求
            current_user_id.reset(token_ctx)
            current_username.reset(name_ctx)
            log_current_user.reset(user_log_ctx)

        return response
