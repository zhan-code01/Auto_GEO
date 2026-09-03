# -*- coding: utf-8 -*-
"""
授权相关的API端点
处理AI平台的授权流程
"""

import time
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Query, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from loguru import logger

import bcrypt

from backend.database.models import User, Project, Account, ExtensionPairingCode, BrowserExtensionBinding
from backend.database import get_db
from backend.services.auth_service import auth_service
from backend.services.session_manager import secure_session_manager
from backend.services.crypto import decrypt_storage_state, encrypt_cookies, encrypt_storage_state
from backend.services.cookie_validator import cookie_validator
from backend.services.local_browser_bridge import local_browser_bridge
from backend.api.user import get_current_user_from_token
from backend.config import AI_PLATFORMS

# extension_token 依赖
import hashlib
import secrets
import string

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
    responses={404: {"description": "Not found"}},
)


from pydantic import BaseModel


class AuthStartFlowRequest(BaseModel):
    user_id: int
    project_id: Optional[int] = None
    platforms: List[str]


async def _sync_ai_session_from_account(
    db: Session, user_id: int, project_id: Optional[int], platform: str
) -> bool:
    """Backfill AI evaluation session from account auth storage_state."""
    if platform not in {"doubao", "qianwen", "deepseek"}:
        return False

    account = (
        db.query(Account)
        .filter(
            Account.user_id == user_id,
            Account.platform == platform,
            Account.status == 1,
            Account.deleted_at.is_(None),
            Account.storage_state.isnot(None),
        )
        .order_by(Account.updated_at.desc(), Account.id.desc())
        .first()
    )
    if not account:
        return False

    storage_state = decrypt_storage_state(account.storage_state)
    if not storage_state:
        logger.warning(f"AI session backfill failed: storage_state decrypt empty, user_id={user_id}, platform={platform}")
        return False

    is_valid, reason, _probe_info = await cookie_validator.validate(platform=platform, storage_state=storage_state)
    if not is_valid:
        logger.warning(
            f"AI session backfill skipped: stored account auth invalid, "
            f"user_id={user_id}, platform={platform}, account_id={account.id}, reason={reason}"
        )
        return False

    ok = await secure_session_manager.save_session(
        user_id=user_id,
        project_id=project_id,
        platform=platform,
        storage_state=storage_state,
        is_new_login=False,
    )
    if ok:
        logger.info(f"AI session backfilled from account: user_id={user_id}, platform={platform}, account_id={account.id}")
    return ok


@router.post("/start-flow")
async def start_auth_flow(request: Request, db: Session = Depends(get_db)):
    """
    开始授权流程

    Args:
        request: Request对象
        db: 数据库会话

    Returns:
        授权流程信息
    """
    try:
        # 手动解析参数，避免 Pydantic 422 错误，并打印日志
        try:
            body = await request.json()
            logger.info(f"收到授权请求数据: {body}")
        except Exception as e:
            logger.error(f"解析请求体失败: {e}")
            raise HTTPException(status_code=400, detail="无效的 JSON 数据")

        user_id = body.get("user_id")
        project_id = body.get("project_id")
        platforms = body.get("platforms")

        # 🔒 安全修复：优先从已认证的 JWT 中获取 user_id，忽略前端传入的值
        jwt_user_id = getattr(getattr(request, 'state', None), 'user_id', None)
        if jwt_user_id:
            # 中间件已验证 JWT，使用真实 user_id
            if user_id is not None and user_id != jwt_user_id:
                logger.warning(
                    f"⚠️ 安全告警: JWT user_id={jwt_user_id} 与请求体 user_id={user_id} 不匹配，已拒绝"
                )
                raise HTTPException(
                    status_code=403,
                    detail="安全告警：user_id 与登录身份不匹配"
                )
            user_id = jwt_user_id
        else:
            # 无 JWT 上下文（理论上中间件会拦截），拒绝请求
            raise HTTPException(
                status_code=401,
                detail="未认证：需要有效登录会话"
            )

        # 简单的参数校验
        if user_id is None:
            error_msg = f"缺少 user_id. 收到数据: {body}"
            logger.error(error_msg)
            raise HTTPException(status_code=400, detail=error_msg)

        if not platforms or not isinstance(platforms, list):
            raise HTTPException(status_code=400, detail="platforms 必须是非空列表")

        # 🔒 安全修复：移除"用户不存在则自动创建"的危险逻辑
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"用户不存在 (user_id={user_id})，请先注册"
            )

        if project_id is not None:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail=f"项目不存在(project_id={project_id})")

        # 开始授权流程
        result = await auth_service.start_auth_flow(user_id=user_id, project_id=project_id, platforms=platforms)

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "开始授权流程失败"),
                headers={"X-Error-Code": result.get("error_code", "UNKNOWN_ERROR")},
            )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"授权流程异常: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.get("/status/{auth_session_id}")
async def get_auth_status(auth_session_id: str):
    """
    获取授权状态

    Args:
        auth_session_id: 授权会话ID

    Returns:
        授权状态
    """
    try:
        result = await auth_service.get_auth_status(auth_session_id)

        if not result.get("success"):
            raise HTTPException(
                status_code=404,
                detail=result.get("error", "授权会话不存在"),
                headers={"X-Error-Code": result.get("error_code", "SESSION_NOT_FOUND")},
            )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.post("/start-platform/{auth_session_id}")
async def start_platform_auth(auth_session_id: str, platform: str = Query(..., description="平台标识")):
    """
    开始单个平台的授权

    Args:
        auth_session_id: 授权会话ID
        platform: 平台标识

    Returns:
        授权URL和状态
    """
    try:
        result = await auth_service.start_platform_auth(auth_session_id=auth_session_id, platform=platform)

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "开始平台授权失败"),
                headers={"X-Error-Code": result.get("error_code", "INTERNAL_ERROR")},
            )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.post("/complete-platform/{auth_session_id}")
async def complete_platform_auth(auth_session_id: str, platform: str = Query(..., description="平台标识")):
    """
    完成平台授权

    Args:
        auth_session_id: 授权会话ID
        platform: 平台标识

    Returns:
        授权结果
    """
    try:
        result = await auth_service.complete_platform_auth(auth_session_id=auth_session_id, platform=platform)

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "完成平台授权失败"),
                headers={"X-Error-Code": result.get("error_code", "INTERNAL_ERROR")},
            )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.post("/cancel/{auth_session_id}")
async def cancel_auth_flow(auth_session_id: str):
    """
    取消授权流程

    Args:
        auth_session_id: 授权会话ID

    Returns:
        取消结果
    """
    try:
        result = await auth_service.cancel_auth_flow(auth_session_id)

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "取消授权流程失败"),
                headers={"X-Error-Code": result.get("error_code", "INTERNAL_ERROR")},
            )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.get("/sessions")
async def list_sessions(
    user_id: int = Query(..., description="用户ID"), project_id: int = Query(None, description="项目ID")
):
    """
    列出用户/项目的所有会话

    Args:
        user_id: 用户ID
        project_id: 项目ID（可选）

    Returns:
        会话列表
    """
    try:
        result = await secure_session_manager.list_sessions(user_id=user_id, project_id=project_id)

        return JSONResponse(content={"success": True, "data": result})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.get("/session/status")
async def get_session_status(
    user_id: Optional[int] = Query(None, description="用户ID（兼容旧前端；实际以当前登录用户为准）"),
    project_id: Optional[int] = Query(None, description="项目ID（已废弃，授权会话现按用户级隔离，可不传）"),
    platform: str = Query(..., description="平台标识"),
    fast: bool = Query(False, description="是否快速检查（仅检查文件存在性）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取单个平台的会话状态

    会话已改为用户级隔离，project_id 仅作兼容保留、不再参与定位。
    user_id 仅为兼容旧调用保留，实际始终使用当前 JWT 用户，避免跨用户读取/操作授权态。

    Args:
        user_id: 用户ID（兼容旧前端；实际以当前登录用户为准）
        project_id: 项目ID（已废弃，可不传）
        platform: 平台标识
        fast: 是否快速检查

    Returns:
        会话状态详情
    """
    try:
        effective_user_id = current_user.id
        if user_id is not None and user_id != effective_user_id:
            logger.warning(
                f"忽略与 JWT 不一致的授权状态 user_id: query={user_id}, jwt={effective_user_id}, platform={platform}"
            )

        if fast:
            result = await secure_session_manager.get_session_status_fast(
                user_id=effective_user_id, project_id=project_id, platform=platform
            )
        else:
            result = await secure_session_manager.get_session_status(
                user_id=effective_user_id, project_id=project_id, platform=platform
            )

        if result.get("status") == "invalid":
            synced = await _sync_ai_session_from_account(
                db=db, user_id=effective_user_id, project_id=project_id, platform=platform
            )
            if synced:
                result = await secure_session_manager.get_session_status_fast(
                    user_id=effective_user_id, project_id=project_id, platform=platform
                )

        return JSONResponse(content={"success": True, "data": result})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@router.delete("/session")
async def delete_session(
    user_id: Optional[int] = Query(None, description="用户ID（兼容旧前端；实际以当前登录用户为准）"),
    project_id: Optional[int] = Query(None, description="项目ID（已废弃，授权会话现按用户级隔离，可不传）"),
    platform: str = Query(..., description="平台标识"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除会话

    会话已改为用户级隔离，project_id 仅作兼容保留、不再参与定位。
    同时清理由账号授权回填的 Account.storage_state，避免状态接口再次从账号表自动恢复为“已授权”。

    Args:
        user_id: 用户ID（兼容旧前端；实际以当前登录用户为准）
        project_id: 项目ID（已废弃，可不传）
        platform: 平台标识

    Returns:
        删除结果
    """
    try:
        effective_user_id = current_user.id
        if user_id is not None and user_id != effective_user_id:
            logger.warning(
                f"忽略与 JWT 不一致的删除会话 user_id: query={user_id}, jwt={effective_user_id}, platform={platform}"
            )

        result = await secure_session_manager.delete_session(
            user_id=effective_user_id, project_id=project_id, platform=platform
        )

        if not result:
            raise HTTPException(status_code=400, detail="删除会话失败")

        updated = (
            db.query(Account)
            .filter(
                Account.user_id == effective_user_id,
                Account.platform == platform,
                Account.deleted_at.is_(None),
            )
            .update(
                {
                    Account.cookies: None,
                    Account.storage_state: None,
                    Account.status: 0,
                    Account.last_auth_time: None,
                    Account.auth_expires_at: None,
                    Account.health_score: 0,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        logger.info(f"授权取消完成: user_id={effective_user_id}, platform={platform}, accounts_cleared={updated}")

        return JSONResponse(content={"success": True, "message": "会话删除成功"})

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


# 全局存储：扩展 ID（浏览器扩展启动时注册）
_extension_id: str = ""
# 同步请求：前端点"刷新状态"时设为 True，扩展轮询后设为 False
_sync_requested: bool = False
_sync_request_time: float = 0.0


@router.post("/register-extension")
async def register_extension_id(request: Request):
    """浏览器扩展启动时注册自己的 ID"""
    global _extension_id
    try:
        body = await request.json()
        _extension_id = body.get("extension_id", "")
        logger.info(f"扩展 ID 已注册: {_extension_id}")
        return JSONResponse(content={"success": True})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/extension-id")
async def get_extension_id():
    """前端查询已注册的扩展 ID"""
    return JSONResponse(content={"success": True, "extension_id": _extension_id})


@router.get("/request-sync")
async def request_sync():
    """前端点"刷新状态"时调用，设置同步请求标记"""
    global _sync_requested, _sync_request_time
    _sync_requested = True
    _sync_request_time = time.time()
    logger.info("收到前端同步请求")
    return JSONResponse(content={"success": True, "message": "同步请求已记录"})


# ==================== 插件绑定码接口 ====================


def _generate_pair_code(length: int = 6) -> str:
    """生成随机绑定码（仅字母数字）"""
    chars = string.ascii_uppercase + string.digits
    # 排除易混淆字符
    chars = chars.replace("O", "").replace("0", "").replace("I", "").replace("1", "")
    return "".join(secrets.choice(chars) for _ in range(length))


@router.post("/extension/pair-code")
async def create_pair_code(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    为已登录用户创建短期插件绑定码
    """
    from backend.api.user import get_current_user_from_token
    from fastapi.security import HTTPBearer

    # 解析用户 JWT
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header.replace("Bearer ", "").strip()
    try:
        from backend.config import JWT_SECRET_KEY, JWT_ALGORITHM
        import jwt
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效令牌")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌")

    # 解析请求体
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON")
    platform = body.get("platform")
    scene = body.get("scene", "account_auth")

    # 使该用户的旧绑定码失效
    old_codes = db.query(ExtensionPairingCode).filter(
        ExtensionPairingCode.user_id == user_id,
        ExtensionPairingCode.status == 0,
    ).all()
    for c in old_codes:
        c.status = -1
    db.commit()

    # 生成新绑定码
    pair_code = _generate_pair_code()
    code_hash = hashlib.sha256(pair_code.encode()).hexdigest()
    expires_at = datetime.now() + timedelta(minutes=5)

    db_code = ExtensionPairingCode(
        code=code_hash,
        user_id=user_id,
        platform=platform,
        scene=scene,
        status=0,
        expires_at=expires_at,
    )
    db.add(db_code)
    db.commit()

    logger.info(f"插件绑定码已生成: user_id={user_id}, platform={platform}")
    return JSONResponse(content={
        "success": True,
        "pair_code": pair_code,  # 明文返回给前端展示
        "expires_in": 300,
    })


@router.post("/extension/bind")
async def bind_extension(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    插件使用绑定码完成与用户的绑定，返回 extension_token
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON")

    pair_code = body.get("pair_code", "").strip()
    extension_id = body.get("extension_id", "").strip()
    device_name = body.get("device_name", "Unknown Device")

    if not pair_code or not extension_id:
        raise HTTPException(status_code=400, detail="pair_code 和 extension_id 不能为空")

    # 查找并校验绑定码（用 hash 匹配）
    code_hash = hashlib.sha256(pair_code.encode()).hexdigest()
    db_code = db.query(ExtensionPairingCode).filter(
        ExtensionPairingCode.code == code_hash,
        ExtensionPairingCode.status == 0,
    ).first()

    if not db_code:
        raise HTTPException(status_code=400, detail="无效或已过期的绑定码")

    if db_code.expires_at < datetime.now():
        db_code.status = -1
        db.commit()
        raise HTTPException(status_code=400, detail="绑定码已过期")

    user_id = db_code.user_id

    # 标记绑定码已使用
    db_code.status = 1
    db_code.used_at = datetime.now()

    # 生成 extension_token
    raw_token = f"ext_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # 保存绑定关系（同一 extension_id 只能绑定一个用户）
    existing = db.query(BrowserExtensionBinding).filter(
        BrowserExtensionBinding.extension_id == extension_id,
        BrowserExtensionBinding.revoked_at.is_(None),
    ).first()
    if existing:
        # 复用但重新生成 token
        existing.user_id = user_id
        existing.token_hash = token_hash
        existing.device_name = device_name
        existing.last_seen_at = datetime.now()
        binding = existing
    else:
        binding = BrowserExtensionBinding(
            user_id=user_id,
            extension_id=extension_id,
            device_name=device_name,
            token_hash=token_hash,
            last_seen_at=datetime.now(),
        )
        db.add(binding)

    db.commit()
    logger.info(f"插件绑定成功: user_id={user_id}, extension_id={extension_id}")

    return JSONResponse(content={
        "success": True,
        "extension_token": raw_token,  # 明文返回给插件保存
        "user_id": user_id,
    })


# ==================== extension_token 鉴权依赖 ====================

async def get_binding_from_token(
    request: Request,
    db: Session = Depends(get_db),
) -> BrowserExtensionBinding:
    """从 Authorization: Bearer <ext_xxx> 解析插件绑定关系"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供插件令牌", headers={"WWW-Authenticate": "Bearer ext_xxx"})

    token = auth_header.replace("Bearer ", "").strip()
    if not token.startswith("ext_"):
        raise HTTPException(status_code=401, detail="无效的插件令牌格式")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    binding = db.query(BrowserExtensionBinding).filter(
        BrowserExtensionBinding.token_hash == token_hash,
    ).first()

    if not binding:
        raise HTTPException(status_code=401, detail="插件令牌无效")

    if binding.revoked_at is not None:
        raise HTTPException(status_code=403, detail="插件授权已被撤销")

    # 更新最后活跃时间
    binding.last_seen_at = datetime.now()
    db.commit()

    return binding


# ==================== Cookie 同步接口（改造） ====================


class SyncCookiesRequest(BaseModel):
    user_id: int = 1
    project_id: int = 1
    platform: str
    cookies: list = []
    local_storage: dict = {}
    fingerprint: dict = {}


class SyncLocalStorageStateRequest(BaseModel):
    project_id: Optional[int] = None
    platform: str
    storage_state: dict
    account_name: Optional[str] = None
    account_id: Optional[int] = None
    login_verified: bool = False
    verification_method: Optional[str] = None


class StartLocalBrowserAuthRequest(BaseModel):
    project_id: Optional[int] = None
    platform: str
    timeout_seconds: int = 180


async def _validate_ai_storage_state(platform: str, storage_state: dict) -> tuple[bool, str]:
    is_valid, reason, _probe_info = await cookie_validator.validate(platform=platform, storage_state=storage_state)
    return is_valid, reason


async def _probe_ai_page_login_state(page, platform: str) -> tuple[bool, str]:
    """Validate login state from the currently visible auth browser page."""
    if platform not in {"doubao", "deepseek"}:
        return False, "unsupported page probe"

    if platform == "deepseek":
        try:
            result = await page.evaluate(
                """async () => {
                    const isVisible = (element) => {
                        if (!element) return false;
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const anyVisible = (selector) => Array.from(document.querySelectorAll(selector)).some(isVisible);
                    const bodyText = document.body?.innerText || '';
                    const hasLoginPrompt =
                        /登录|注册|验证码|手机号|邮箱登录|扫码登录|sign in|sign up|log in/i.test(bodyText) &&
                        anyVisible('input[type="password"], input[type="tel"], input[type="email"], [class*="login"], [class*="signin"]');
                    const hasChatShell =
                        /开启新对话|新对话|快速模式|专家模式|联网搜索|使用快速模式开始对话|Start a new chat|DeepThink|深度思考/i.test(bodyText) ||
                        anyVisible('textarea, [contenteditable="true"], [role="textbox"], [id*="chat-input"], [class*="chat-input"], [class*="new-chat"]');
                    const hasConversationUi =
                        anyVisible('[class*="conversation"], [class*="chat-session"], [class*="message"], [class*="sidebar"], [data-testid*="conversation"]') ||
                        /历史对话|暂无历史对话|新对话|Start a new chat|DeepThink|深度思考/.test(bodyText);

                    const hasUserIdentity = (value, depth = 0) => {
                        if (!value || typeof value !== 'object' || depth > 5) return false;
                        if (Array.isArray(value)) return value.some(item => hasUserIdentity(item, depth + 1));
                        if (
                            value.id || value.uid || value.user_id || value.userId ||
                            value.username || value.email || value.phone || value.name ||
                            value.nickname || value.avatar
                        ) return true;
                        return Object.values(value).some(item => hasUserIdentity(item, depth + 1));
                    };

                    try {
                        const response = await fetch('/api/v0/users/current', {
                            credentials: 'include',
                            headers: { accept: 'application/json' },
                        });
                        const text = await response.text();
                        if (response.ok) {
                            let data = null;
                            try { data = JSON.parse(text); } catch { data = null; }
                            if (hasUserIdentity(data)) {
                                return { ok: true, method: 'api', reason: 'deepseek current-user api confirmed' };
                            }
                        }
                        return {
                            ok: !hasLoginPrompt && hasChatShell && hasConversationUi,
                            method: 'dom',
                            reason: `deepseek dom probe: login=${hasLoginPrompt}, shell=${hasChatShell}, conversation=${hasConversationUi}, status=${response.status}`,
                        };
                    } catch {
                        return {
                            ok: !hasLoginPrompt && hasChatShell && hasConversationUi,
                            method: 'dom',
                            reason: `deepseek dom probe: login=${hasLoginPrompt}, shell=${hasChatShell}, conversation=${hasConversationUi}, api=failed`,
                        };
                    }
                }"""
            )
            return bool(result.get("ok")), result.get("reason") or "deepseek page probe"
        except Exception as e:
            return False, f"deepseek page probe failed: {e}"

    try:
        result = await page.evaluate(
            """async () => {
                const isVisible = (element) => {
                    if (!element) return false;
                    const style = window.getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                };
                const bodyText = document.body?.innerText || '';
                const hasLoginPrompt =
                    /登录|手机号|验证码|\\+86|下一步|用户协议|隐私政策|扫码登录|抖音一键登录/i.test(bodyText) &&
                    Array.from(document.querySelectorAll('input, button, [class*="login"], [class*="passport"]')).some(isVisible);
                const hasChatInput = Array.from(
                    document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [class*="chat-input"], [class*="editor"]')
                ).some(isVisible);
                const hasConversationUi =
                    Array.from(document.querySelectorAll('[data-foundation-type="receive-message-action-bar"], [data-message-id]')).some(isVisible) ||
                    /历史对话|新对话/.test(bodyText);

                try {
                    const response = await fetch('/api/user/info', {
                        credentials: 'include',
                        headers: { accept: 'application/json' },
                    });
                    const text = await response.text();
                    if (response.ok) {
                        let data = null;
                        try { data = JSON.parse(text); } catch { data = null; }
                        const hasUserIdentity = (value, depth = 0) => {
                            if (!value || typeof value !== 'object' || depth > 5) return false;
                            if (Array.isArray(value)) return value.some(item => hasUserIdentity(item, depth + 1));
                            if (
                                value.uid || value.user_id || value.userId || value.id ||
                                value.name || value.nickname || value.avatar || value.phone || value.email
                            ) return true;
                            return Object.values(value).some(item => hasUserIdentity(item, depth + 1));
                        };
                        if (hasUserIdentity(data)) {
                            return { ok: true, reason: 'doubao api user info confirmed' };
                        }
                    }
                    return {
                        ok: !hasLoginPrompt && hasChatInput && hasConversationUi,
                        reason: `doubao dom probe: login=${hasLoginPrompt}, input=${hasChatInput}, conversation=${hasConversationUi}, status=${response.status}`,
                    };
                } catch {
                    return {
                        ok: !hasLoginPrompt && hasChatInput && hasConversationUi,
                        reason: `doubao dom probe: login=${hasLoginPrompt}, input=${hasChatInput}, conversation=${hasConversationUi}, api=failed`,
                    };
                }
            }"""
        )
        return bool(result.get("ok")), result.get("reason") or "doubao page probe"
    except Exception as e:
        return False, f"doubao page probe failed: {e}"


async def _wait_for_ai_platform_login(page, platform: str, timeout_seconds: int) -> tuple[bool, dict, str]:
    deadline = time.time() + max(30, min(timeout_seconds, 300))
    last_reason = "waiting"
    while time.time() < deadline:
        await page.wait_for_timeout(2000)
        storage_state = await page.context.storage_state()
        if platform in {"doubao", "deepseek"}:
            page_ok, page_reason = await _probe_ai_page_login_state(page, platform)
            last_reason = page_reason
            if page_ok:
                storage_state["browser_verified_login"] = {
                    "platform": platform,
                    "verified_at": time.time(),
                    "method": "api" if "api confirmed" in page_reason else "dom",
                    "reason": page_reason,
                }
                return True, storage_state, page_reason
            continue
        is_valid, reason = await cookie_validator.validate_fast(platform=platform, storage_state=storage_state)
        last_reason = reason
        if not is_valid:
            continue

        return True, storage_state, reason
    return False, {}, last_reason


@router.post("/sync-local-storage-state")
async def sync_local_storage_state(
    request: SyncLocalStorageStateRequest,
    current_user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_db),
):
    """
    接收 Electron/开发端本机浏览器授权得到的 Playwright storage_state，
    保存到 GEO 测评读取的 AI 平台会话存储中。
    """
    try:
        if request.platform not in {"doubao", "qianwen", "deepseek"}:
            raise HTTPException(status_code=400, detail=f"不支持的 AI 平台: {request.platform}")
        if not request.storage_state or not request.storage_state.get("cookies"):
            raise HTTPException(status_code=400, detail="storage_state 为空或缺少 cookies")

        is_valid, reason = await _validate_ai_storage_state(request.platform, request.storage_state)
        cookies = request.storage_state.get("cookies", [])
        origins = request.storage_state.get("origins", [])
        has_deepseek_state = (
            any("deepseek" in (cookie.get("domain") or "") for cookie in cookies)
            and any("chat.deepseek.com" in (origin.get("origin") or "") for origin in origins)
        )
        has_doubao_state = any("doubao.com" in (cookie.get("domain") or "") for cookie in cookies)
        browser_verified = (
            request.platform in {"deepseek", "doubao"}
            and request.login_verified
            and request.verification_method in {"api", "dom"}
            and (
                (request.platform == "deepseek" and has_deepseek_state)
                or (request.platform == "doubao" and has_doubao_state)
            )
        )
        explicit_auth_failure = (
            request.platform == "deepseek"
            and any(marker in reason.lower() for marker in ["invalid token", "token expired", "认证失败"])
        )
        if explicit_auth_failure:
            browser_verified = False
        if request.platform == "doubao" and not browser_verified:
            raise HTTPException(
                status_code=400,
                detail="豆包Cookie存在，但浏览器页面未确认真实登录；请完成登录直到页面“登录”按钮消失",
            )
        if not is_valid and not browser_verified:
            raise HTTPException(status_code=400, detail=f"未检测到有效登录态: {reason}")
        if not is_valid and browser_verified:
            logger.info(
                f"{request.platform} storage_state accepted by browser-side verification: "
                f"method={request.verification_method}, api_reason={reason}"
            )
            if request.platform in {"doubao", "deepseek"}:
                request.storage_state["browser_verified_login"] = {
                    "platform": request.platform,
                    "verified_at": time.time(),
                    "method": request.verification_method,
                    "reason": reason,
                }

        ok = await secure_session_manager.save_session(
            user_id=current_user.id,
            project_id=request.project_id,
            platform=request.platform,
            storage_state=request.storage_state,
            is_new_login=True,
        )
        if not ok:
            raise HTTPException(status_code=500, detail="保存本机浏览器授权会话失败")

        now = datetime.now()
        account = None
        if request.account_id:
            account = (
                db.query(Account)
                .filter(
                    Account.id == request.account_id,
                    Account.user_id == current_user.id,
                    Account.deleted_at.is_(None),
                )
                .first()
            )
            if not account:
                raise HTTPException(status_code=404, detail="账号不存在")
            if account.platform != request.platform:
                raise HTTPException(status_code=400, detail="账号平台不匹配")

        if not account:
            account_name = request.account_name or f"{AI_PLATFORMS[request.platform]['name']}账号"
            account = (
                db.query(Account)
                .filter(
                    Account.user_id == current_user.id,
                    Account.platform == request.platform,
                    Account.account_name == account_name,
                    Account.deleted_at.is_(None),
                )
                .first()
            )

        cookies = request.storage_state.get("cookies", [])
        if account:
            if request.account_name:
                account.account_name = request.account_name
            account.cookies = encrypt_cookies(cookies)
            account.storage_state = encrypt_storage_state(request.storage_state)
            account.status = 1
            account.last_auth_time = now
            account.health_score = 100
            account.auth_mode = "cloud_browser"
            account.session_location = "server"
        else:
            account = Account(
                user_id=current_user.id,
                platform=request.platform,
                account_name=request.account_name or f"{AI_PLATFORMS[request.platform]['name']}账号",
                cookies=encrypt_cookies(cookies),
                storage_state=encrypt_storage_state(request.storage_state),
                status=1,
                last_auth_time=now,
                health_score=100,
                auth_mode="cloud_browser",
                session_location="server",
            )
            db.add(account)
        db.commit()
        db.refresh(account)

        return JSONResponse(
            content={
                "success": True,
                "message": "本机浏览器授权会话已同步",
                "platform": request.platform,
                "account_id": account.id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"本机浏览器授权会话同步异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


class RoamSessionUploadRequest(BaseModel):
    """本地客户端内容平台漫游会话上传请求"""

    platform: str
    account_id: int
    storage_state: dict
    account_name: Optional[str] = None


@router.post("/roam-session/upload")
async def upload_roaming_session(
    request: RoamSessionUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """本地客户端绑定内容平台后，把登录态加密上传服务器（会话漫游）。

    用途：同一账号在 A 电脑绑定知乎/抖音等平台后，B 电脑登录同一账号即可直接发布
    （B 发布时若本机无会话，会调用下载接口拉取）。只影响 local_only 内容平台，
    不改变账号的 session_location / auth_mode（发布仍走各电脑本地浏览器）。
    """
    account = (
        db.query(Account)
        .filter(Account.id == request.account_id, Account.deleted_at.is_(None))
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该账号")
    if account.platform != request.platform:
        raise HTTPException(status_code=400, detail="账号平台不匹配")
    if not request.storage_state or not request.storage_state.get("cookies"):
        raise HTTPException(status_code=400, detail="storage_state 为空或缺少 cookies")

    ok = await secure_session_manager.save_roaming_session(request.account_id, request.storage_state)
    if not ok:
        raise HTTPException(status_code=500, detail="保存漫游会话失败")
    account.last_auth_time = datetime.now()
    db.commit()
    logger.info(f"漫游会话上传: user_id={current_user.id} account_id={request.account_id} platform={request.platform}")
    return JSONResponse(content={"success": True, "account_id": request.account_id})


@router.get("/roam-session/{account_id}")
async def download_roaming_session(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """拉取当前用户某账号的漫游会话（供本机无会话时发布使用）。"""
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.deleted_at.is_(None))
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    if getattr(current_user, "role", None) != "admin" and account.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该账号会话")

    state = await secure_session_manager.load_roaming_session(account_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail="服务器上没有该账号的漫游会话，请先在任一台电脑完成登录授权",
        )
    return JSONResponse(
        content={"success": True, "platform": account.platform, "storage_state": state}
    )


@router.post("/start-local-browser-auth")
async def start_local_browser_auth(
    request: StartLocalBrowserAuthRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    if request.platform not in {"doubao", "qianwen", "deepseek"}:
        raise HTTPException(status_code=400, detail=f"Unsupported AI platform: {request.platform}")

    platform_config = AI_PLATFORMS.get(request.platform) or {}
    login_url = platform_config.get("login_url") or platform_config.get("url")
    if not login_url:
        raise HTTPException(status_code=400, detail=f"Missing login URL for platform: {request.platform}")

    context_id = f"geo_auth_{current_user.id}_{request.platform}_{uuid.uuid4().hex[:8]}"
    context = None
    try:
        if not local_browser_bridge.is_running:
            start_result = await local_browser_bridge.start(headless=False)
            if not start_result.get("success"):
                raise HTTPException(status_code=500, detail=start_result.get("error") or "Start local browser failed")

        context = await local_browser_bridge.create_context(context_id=context_id)
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

        logged_in, storage_state, reason = await _wait_for_ai_platform_login(
            page=page,
            platform=request.platform,
            timeout_seconds=request.timeout_seconds,
        )
        if not logged_in:
            raise HTTPException(status_code=408, detail=f"Login state not detected for {request.platform}: {reason}")

        ok = await secure_session_manager.save_session(
            user_id=current_user.id,
            project_id=request.project_id,
            platform=request.platform,
            storage_state=storage_state,
            is_new_login=True,
        )
        if not ok:
            raise HTTPException(status_code=500, detail="Save local browser session failed")

        return JSONResponse(
            content={
                "success": True,
                "platform": request.platform,
                "message": "Local browser session saved",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GEO local browser auth failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"GEO local browser auth failed: {str(e)}")
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
            try:
                local_browser_bridge._contexts.pop(context_id, None)
            except Exception:
                pass


@router.post("/sync-cookies")
async def sync_cookies_from_extension(
    request: SyncCookiesRequest,
    binding: BrowserExtensionBinding = Depends(get_binding_from_token),
    db: Session = Depends(get_db),
):
    """
    接收浏览器扩展同步的 Cookie + LocalStorage + 指纹数据

    改造：改用 extension_token 鉴权，不再信任请求体里的 user_id
    """
    try:
        # 使用 token 绑定的真实 user_id，忽略请求体里的 user_id
        real_user_id = binding.user_id

        result = await secure_session_manager.sync_cookies_from_extension(
            user_id=real_user_id,
            project_id=request.project_id,  # project_id 仅作兼容保留
            platform=request.platform,
            cookies=request.cookies,
            local_storage=request.local_storage,
            fingerprint=request.fingerprint,
        )

        if not result.get("success"):
            error_code = result.get("error_code", "SYNC_FAILED")
            status_map = {
                "INVALID_PARAMS": 400,
                "UNKNOWN_PLATFORM": 400,
                "CONFIG_ERROR": 400,
                "SAVE_FAILED": 500,
            }
            raise HTTPException(
                status_code=status_map.get(error_code, 400),
                detail=result.get("error", "同步失败"),
                headers={"X-Error-Code": error_code},
            )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cookie同步异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


# ==================== 插件设备管理接口 ====================


@router.get("/extension/devices")
async def list_extension_devices(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    获取当前用户的所有已绑定插件设备
    """
    from fastapi.security import HTTPBearer

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header.replace("Bearer ", "").strip()
    try:
        from backend.config import JWT_SECRET_KEY, JWT_ALGORITHM
        import jwt
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效令牌")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌")

    bindings = db.query(BrowserExtensionBinding).filter(
        BrowserExtensionBinding.user_id == user_id,
    ).order_by(BrowserExtensionBinding.last_seen_at.desc()).all()

    devices = []
    for b in bindings:
        devices.append({
            "id": b.id,
            "extension_id": b.extension_id,
            "device_name": b.device_name,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "last_seen_at": b.last_seen_at.isoformat() if b.last_seen_at else None,
            "revoked": b.revoked_at is not None,
        })

    return JSONResponse(content={"success": True, "devices": devices})


@router.post("/extension/revoke")
async def revoke_extension_device(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    撤销指定插件设备的授权
    """
    from fastapi.security import HTTPBearer

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header.replace("Bearer ", "").strip()
    try:
        from backend.config import JWT_SECRET_KEY, JWT_ALGORITHM
        import jwt
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效令牌")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON")

    binding_id = body.get("binding_id")
    if not binding_id:
        raise HTTPException(status_code=400, detail="binding_id 不能为空")

    binding = db.query(BrowserExtensionBinding).filter(
        BrowserExtensionBinding.id == binding_id,
        BrowserExtensionBinding.user_id == user_id,
    ).first()

    if not binding:
        raise HTTPException(status_code=404, detail="未找到该插件设备")

    binding.revoked_at = datetime.now()
    db.commit()
    logger.info(f"插件设备已撤销: binding_id={binding_id}, user_id={user_id}")

    return JSONResponse(content={"success": True, "message": "插件授权已撤销"})


@router.get("/sync-requests")
async def get_sync_requests(since: float = 0):
    """扩展轮询此接口，检查是否有待处理的同步请求"""
    global _sync_requested
    if _sync_requested and _sync_request_time > since:
        _sync_requested = False
        return JSONResponse(content={"sync_all": True, "time": _sync_request_time})
    return JSONResponse(content={"sync_all": False})


@router.post("/cleanup")
async def cleanup_auth_sessions():
    """
    清理过期的授权会话

    Returns:
        清理结果
    """
    try:
        await auth_service.cleanup_expired_sessions()

        return JSONResponse(content={"success": True, "message": "过期会话清理完成"})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")
