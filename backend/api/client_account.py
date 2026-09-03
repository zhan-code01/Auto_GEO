# -*- coding: utf-8 -*-
"""
本地客户端账号绑定 API（文档 §6.1.2 / §5.2 / §7.3）

与服务器浏览器授权（/api/accounts/auth/*，会保存 storage_state/cookies）不同：
本地客户端授权后，第三方平台登录态只保存在用户本机；服务器只保存账号「绑定元信息」，
且明确标记 auth_mode=local_client、session_location=local_only、不落任何 Cookie/storage_state。

第一阶段（本模块）只提供绑定契约：客户端完成本机扫码/登录后，调用 bind/confirm 上报元信息。
实际「打开本机浏览器 + 登录检测 + 本地会话落盘」属 Phase 2（Node Playwright）范畴。
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.client_device import get_owned_device  # 复用设备归属校验，保持单一实现
from backend.api.user import get_current_user_from_token
from backend.config import PLATFORMS
from backend.database import get_db
from backend.database.models import Account, User
from backend.middleware.user_isolation import require_owner, scoped_query
from backend.schemas import ApiResponse


router = APIRouter(prefix="/api/client/accounts", tags=["本地客户端账号绑定"])


class BindStartRequest(BaseModel):
    """开始绑定：服务器只校验平台与设备，返回登录页地址供客户端在本机打开。"""

    platform: str = Field(..., description="平台ID，需存在于 PLATFORMS")
    device_id: str = Field(..., min_length=1, max_length=64)
    account_id: Optional[int] = Field(None, description="重新授权时传已绑定的账号ID")


class BindConfirmRequest(BaseModel):
    """绑定确认：客户端完成本机登录后上报元信息。不传任何 Cookie/storage_state。"""

    platform: str = Field(...)
    account_name: str = Field(..., min_length=1, max_length=100, description="平台账号昵称")
    device_id: str = Field(..., min_length=1, max_length=64)
    username: Optional[str] = Field(None, max_length=100)
    remote_account_id: Optional[str] = Field(None, max_length=100, description="平台侧账号ID（可选）")
    account_id: Optional[int] = Field(None, description="重新授权时传已绑定的账号ID")


def _serialize_account(account: Account) -> Dict[str, Any]:
    return {
        "id": account.id,
        "platform": account.platform,
        "platform_name": PLATFORMS.get(account.platform, {}).get("name", account.platform),
        "account_name": account.account_name,
        "username": account.username,
        "status": account.status,
        "auth_mode": account.auth_mode,
        "device_id": account.device_id,
        "session_location": account.session_location,
        "last_auth_time": account.last_auth_time.isoformat() if account.last_auth_time else None,
        "last_check_time": account.last_check_time.isoformat() if account.last_check_time else None,
    }


@router.get("", response_model=ApiResponse)
async def list_bound_accounts(
    platform: Optional[str] = Query(None, description="平台ID"),
    status: Optional[int] = Query(None, description="账号状态"),
    device_id: Optional[str] = Query(None, description="本地客户端设备ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """列出当前用户通过本地客户端绑定的账号。"""
    query = (
        scoped_query(db, Account, current_user)
        .filter(
            Account.deleted_at.is_(None),
            Account.auth_mode == "local_client",
        )
    )

    if platform:
        query = query.filter(Account.platform == platform)
    if status is not None:
        query = query.filter(Account.status == status)
    if device_id:
        query = query.filter(Account.device_id == device_id)

    accounts = query.order_by(Account.created_at.desc()).all()
    return ApiResponse(data={"items": [_serialize_account(account) for account in accounts], "total": len(accounts)})


@router.post("/bind/start", response_model=ApiResponse)
async def bind_start(
    request: BindStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """开始本地绑定：返回平台登录页地址，客户端据此在本机打开浏览器（Phase 2 实现）。"""
    if request.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {request.platform}")
    # 校验设备归属（设备必须在场，登录态要落在它上面）
    get_owned_device(db, request.device_id, current_user)

    if request.account_id:
        account = db.query(Account).filter(Account.id == request.account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="账号不存在")
        require_owner(account, current_user, name="账号")
        if account.platform != request.platform:
            raise HTTPException(status_code=400, detail="平台不匹配")

    cfg = PLATFORMS[request.platform]
    logger.info(
        f"[ClientAccount] 本地绑定开始: platform={request.platform} device_id={request.device_id} "
        f"account_id={request.account_id} user_id={current_user.id}"
    )
    return ApiResponse(
        data={
            "platform": request.platform,
            "login_url": cfg.get("login_url", ""),
            "home_url": cfg.get("home_url"),
            "publish_url": cfg.get("publish_url", ""),
            "account_id": request.account_id,
            "note": "请在客户端本机完成扫码/登录后调用 bind/confirm 上报元信息",
        }
    )


@router.post("/bind/confirm", response_model=ApiResponse)
async def bind_confirm(
    request: BindConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    确认本地绑定：创建/更新一个 local_client 账号，仅保存元信息。

    服务器不保存平台 Cookie / storage_state / 浏览器 Profile（session_location=local_only）。
    """
    if request.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {request.platform}")
    get_owned_device(db, request.device_id, current_user)

    now = datetime.now()
    account: Optional[Account] = None
    if request.account_id:
        account = db.query(Account).filter(Account.id == request.account_id).first()
        if account:
            require_owner(account, current_user, name="账号")

    if not account:
        # 同用户同平台同昵称视为复用，避免重复绑定
        account = (
            scoped_query(db, Account, current_user)
            .filter(
                Account.platform == request.platform,
                Account.account_name == request.account_name,
                Account.deleted_at.is_(None),
            )
            .first()
        )

    if account:
        account.account_name = request.account_name
        account.username = request.username or account.username
        account.auth_mode = "local_client"
        account.session_location = "local_only"
        account.device_id = request.device_id
        account.status = 1  # 激活
        account.last_auth_time = now
        # 显式清空任何历史云端会话残留（防御：本账号曾走过 cloud_browser）
        account.cookies = None
        account.storage_state = None
    else:
        account = Account(
            user_id=current_user.id,
            platform=request.platform,
            account_name=request.account_name,
            username=request.username,
            status=1,
            auth_mode="local_client",
            session_location="local_only",
            device_id=request.device_id,
            last_auth_time=now,
        )
        db.add(account)

    db.commit()
    db.refresh(account)
    logger.info(
        f"本地账号绑定: user_id={current_user.id} platform={account.platform} "
        f"account_id={account.id} device_id={request.device_id}"
    )
    return ApiResponse(data={"account": _serialize_account(account)})


@router.post("/{account_id}/verify-result", response_model=ApiResponse)
async def verify_result(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    查询账号绑定/校验结果。

    本地客户端可据此判断账号是否仍 active（status=1）或需要重新授权（status=-1）。
    真正的「登录态是否失效」检测在客户端本机完成（Phase 2），服务器只回放元信息状态。
    """
    account = db.query(Account).filter(Account.id == account_id, Account.deleted_at.is_(None)).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    require_owner(account, current_user, name="账号")
    return ApiResponse(
        data={
            "account": _serialize_account(account),
            "active": account.status == 1,
            "requires_reauth": account.status == -1,
        }
    )
