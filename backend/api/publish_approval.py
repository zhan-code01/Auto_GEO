# -*- coding: utf-8 -*-
"""
发布审批 API（Phase 1：服务器审批式发布）

客户端在发布的关键步骤前调用此接口申请审批：
  - before_write:       是否可以打开编辑器开始写入
  - before_fill_body:   是否可以填充正文
  - before_submit:      是否可以提交发布

即使客户端 exe 被泄露，没有每次审批通过的令牌，
发布流程也无法推进。令牌一次性、短效、绑定 task+device+record。

接口清单：
  POST /api/client/publish/approve/request      客户端请求审批
  POST /api/client/publish/approve/verify       校验令牌（可选，给客户端在拿到令牌后做最终校验）
  GET  /api/client/publish/approve/logs         查询审批日志（管理后台/调试用）
  GET  /api/client/publish/approve/quota         查询当前用户配额
"""

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.user import get_current_user_from_token
from backend.database import get_db
from backend.database.models import PublishApprovalLog, User, UserPublishQuota
from backend.schemas import ApiResponse
from backend.services.publish_approval_service import (
    ApprovalRequest,
    ApprovalResult,
    PublishApprovalService,
    get_approval_service,
)


router = APIRouter(prefix="/api/client/publish/approve", tags=["发布审批"])


# ==================== 请求模型 ====================


class ApprovalRequestBody(BaseModel):
    """客户端审批请求"""

    device_id: str = Field(..., min_length=1, max_length=64, description="客户端设备ID")
    task_id: int = Field(..., description="自动发布任务ID")
    record_id: int = Field(..., description="子记录ID")
    checkpoint: str = Field(..., description="审批检查点")


class ApprovalVerifyBody(BaseModel):
    """客户端校验审批令牌（可选）"""

    device_id: str = Field(..., min_length=1, max_length=64)
    task_id: int
    record_id: int
    checkpoint: str
    approval_token: str = Field(..., min_length=10, max_length=128)


# ==================== 工具函数 ====================


def _extract_client_meta(request: Request) -> Dict[str, Optional[str]]:
    """从 FastAPI Request 提取客户端元信息（IP/UA）"""
    # 优先取反向代理头，再退到直连 IP
    forwarded_for = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    elif real_ip:
        ip = real_ip.strip()
    else:
        ip = request.client.host if request.client else None

    ua = request.headers.get("user-agent")
    return {"client_ip": ip, "user_agent": (ua[:200] if ua else None)}


# ==================== 接口 ====================


@router.post("/request", response_model=ApiResponse)
async def request_approval(
    body: ApprovalRequestBody,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    客户端请求发布步骤审批。

    流程：
      1. 校验链执行（设备、任务、配额、平台、账号）
      2. 通过 → 返回一次性审批令牌 + 过期时间
      3. 拒绝 → 返回原因码 + 原因描述

    注意：本接口必须登录（Bearer Token）。即使 exe 被拿走，没 Token 也调不通。
    """
    # ---- 1. 校验 checkpoint 取值 ----
    valid_checkpoints = {"before_write", "before_fill_body", "before_submit"}
    if body.checkpoint not in valid_checkpoints:
        raise HTTPException(
            status_code=400,
            detail=f"checkpoint 必须是 {sorted(valid_checkpoints)} 之一",
        )

    # ---- 2. 构造内部请求对象 ----
    meta = _extract_client_meta(http_request)
    req = ApprovalRequest(
        user=current_user,
        task_id=body.task_id,
        record_id=body.record_id,
        device_id=body.device_id,
        checkpoint=body.checkpoint,
        client_ip=meta["client_ip"],
        user_agent=meta["user_agent"],
    )

    # ---- 3. 执行审批 ----
    service: PublishApprovalService = get_approval_service()
    result: ApprovalResult = service.approve(req, db)

    logger.info(
        f"[审批] 请求结果: task_id={body.task_id} record_id={body.record_id} "
        f"checkpoint={body.checkpoint} device={body.device_id} "
        f"approved={result.approved} code={result.reason_code} ip={meta['client_ip']}"
    )
    return ApiResponse(
        success=result.approved,
        message="审批通过" if result.approved else "审批拒绝",
        data=result.to_dict(),
    )


@router.post("/verify", response_model=ApiResponse)
async def verify_approval_token(
    body: ApprovalVerifyBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    校验审批令牌是否有效。

    客户端在拿到令牌后可以再调一次此接口做最终确认（防御性编程）。
    服务端会检查令牌是否存在、是否过期、是否匹配 task/record/device。
    """
    log = (
        db.query(PublishApprovalLog)
        .filter(
            PublishApprovalLog.user_id == current_user.id,
            PublishApprovalLog.task_id == body.task_id,
            PublishApprovalLog.record_id == body.record_id,
            PublishApprovalLog.checkpoint == body.checkpoint,
            PublishApprovalLog.approval_token == body.approval_token,
        )
        .order_by(PublishApprovalLog.created_at.desc())
        .first()
    )

    if not log:
        logger.warning(
            f"[审批] 令牌校验失败（令牌不存在）: task_id={body.task_id} record_id={body.record_id} "
            f"checkpoint={body.checkpoint} device={body.device_id} user={current_user.id}"
        )
        return ApiResponse(success=False, message="令牌不存在", data={"valid": False})
    if not log.approved:
        logger.warning(f"[审批] 令牌校验失败（历史审批被拒绝）: task_id={body.task_id} record_id={body.record_id}")
        return ApiResponse(success=False, message="历史审批被拒绝", data={"valid": False})
    if log.expires_at and log.expires_at < datetime.now():
        logger.warning(
            f"[审批] 令牌校验失败（已过期）: task_id={body.task_id} record_id={body.record_id} "
            f"expires_at={log.expires_at}"
        )
        return ApiResponse(success=False, message="令牌已过期", data={"valid": False})
    if log.device_id != body.device_id:
        logger.warning(
            f"[审批] 令牌校验失败（设备不匹配）: task_id={body.task_id} record_id={body.record_id} "
            f"token_device={log.device_id} request_device={body.device_id}"
        )
        return ApiResponse(success=False, message="令牌与设备不匹配", data={"valid": False})

    logger.debug(
        f"[审批] 令牌校验通过: task_id={body.task_id} record_id={body.record_id} "
        f"checkpoint={body.checkpoint} device={body.device_id}"
    )
    return ApiResponse(
        success=True,
        message="令牌有效",
        data={
            "valid": True,
            "expires_at": log.expires_at.isoformat() if log.expires_at else None,
        },
    )


@router.get("/logs", response_model=ApiResponse)
async def list_approval_logs(
    limit: int = Query(50, ge=1, le=500),
    task_id: Optional[int] = Query(None),
    record_id: Optional[int] = Query(None),
    approved: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """查询当前用户的审批日志（管理后台/排障）"""
    q = db.query(PublishApprovalLog).filter(PublishApprovalLog.user_id == current_user.id)
    if task_id is not None:
        q = q.filter(PublishApprovalLog.task_id == task_id)
    if record_id is not None:
        q = q.filter(PublishApprovalLog.record_id == record_id)
    if approved is not None:
        q = q.filter(PublishApprovalLog.approved == approved)

    logs = q.order_by(PublishApprovalLog.created_at.desc()).limit(limit).all()
    return ApiResponse(
        data={
            "items": [
                {
                    "id": l.id,
                    "task_id": l.task_id,
                    "record_id": l.record_id,
                    "device_id": l.device_id,
                    "checkpoint": l.checkpoint,
                    "approved": l.approved,
                    "reason_code": l.reason_code,
                    "reason": l.reason,
                    "client_ip": l.client_ip,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in logs
            ]
        }
    )


@router.get("/quota", response_model=ApiResponse)
async def get_my_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """查询当前用户的发布配额。无记录视为无限制。"""
    quota = db.query(UserPublishQuota).filter(UserPublishQuota.user_id == current_user.id).first()
    if not quota:
        return ApiResponse(
            data={
                "exists": False,
                "tier": "free",
                "daily_limit": None,
                "monthly_limit": None,
                "used_today": 0,
                "used_this_month": 0,
                "platform_whitelist": None,
            }
        )

    return ApiResponse(
        data={
            "exists": True,
            "tier": quota.tier,
            "daily_limit": quota.daily_limit,
            "monthly_limit": quota.monthly_limit,
            "used_today": quota.used_today,
            "used_this_month": quota.used_this_month,
            "remaining_today": max(0, (quota.daily_limit or 0) - (quota.used_today or 0)),
            "remaining_this_month": max(0, (quota.monthly_limit or 0) - (quota.used_this_month or 0)),
            "platform_whitelist": quota.platform_whitelist,
            "reset_date": quota.reset_date.isoformat() if quota.reset_date else None,
            "month_reset_date": quota.month_reset_date.isoformat() if quota.month_reset_date else None,
        }
    )


# ==================== 管理端：给用户设置配额 ====================


class QuotaUpsertBody(BaseModel):
    """管理员为用户设置配额"""

    user_id: int
    tier: Optional[str] = "free"
    daily_limit: Optional[int] = 100
    monthly_limit: Optional[int] = 3000
    platform_whitelist: Optional[List[str]] = None


@router.post("/admin/quota", response_model=ApiResponse)
async def upsert_quota(
    body: QuotaUpsertBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """设置/更新用户配额（仅管理员）"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可设置配额")

    quota = db.query(UserPublishQuota).filter(UserPublishQuota.user_id == body.user_id).first()
    today = datetime.now().date()
    if quota:
        quota.tier = body.tier or quota.tier
        quota.daily_limit = body.daily_limit or quota.daily_limit
        quota.monthly_limit = body.monthly_limit or quota.monthly_limit
        quota.platform_whitelist = (
            body.platform_whitelist if body.platform_whitelist is not None else quota.platform_whitelist
        )
    else:
        quota = UserPublishQuota(
            user_id=body.user_id,
            tier=body.tier or "free",
            daily_limit=body.daily_limit or 100,
            monthly_limit=body.monthly_limit or 3000,
            platform_whitelist=body.platform_whitelist,
            used_today=0,
            used_this_month=0,
            reset_date=today,
            month_reset_date=today.replace(day=1),
        )
        db.add(quota)

    db.commit()
    db.refresh(quota)
    logger.info(
        f"[审批] 管理员 {current_user.id} 设置用户 {body.user_id} 配额: daily={quota.daily_limit}, monthly={quota.monthly_limit}"
    )
    return ApiResponse(
        message="配额已更新",
        data={
            "user_id": quota.user_id,
            "tier": quota.tier,
            "daily_limit": quota.daily_limit,
            "monthly_limit": quota.monthly_limit,
        },
    )
