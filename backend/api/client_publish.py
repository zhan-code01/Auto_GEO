# -*- coding: utf-8 -*-
"""
本地客户端发布任务路由 API（文档 §6.1.3 / §6.1.4 / §6.1.5）

服务器只负责任务编排与结果落库，发布动作在用户本机客户端执行。
协议基于既有的 AutoPublishTask（批任务，含路由字段）+ AutoPublishRecord（每对文章×账号子记录）：

    pending → claimed(running) → manual_required → running → success/failed
                                   ↘ failed
                                   ↘ cancelled

客户端流程：poll → claim → payload（拉取文章内容）→ 本机发布 → result（回传每条结果）。
任务在执行期间需要周期性 heartbeat 续租领取锁，超时可被重新领取。

按用户隔离 + 设备归属校验：只能领取/操作自己名下设备收到的任务。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from backend.api.client_device import get_owned_device, is_device_online
from backend.api.user import get_current_user_from_token
from backend.config import PLATFORMS
from backend.database import get_db
from backend.database.models import (
    Account,
    AutoPublishRecord,
    AutoPublishTask,
    ClientDevice,
    GeoArticle,
    User,
)
from backend.middleware.user_isolation import require_owner
from backend.schemas import ApiResponse
from backend.services.tieba_forum import default_forum_from_tags
from backend.utils.time_utils import beijing_now
from backend.api.auto_publish import rearm_interval_task


router = APIRouter(prefix="/api/client/publish/tasks", tags=["本地客户端发布"])


# 领取锁有效期：客户端需在此时间内完成或续租，超时后任务可被重新领取。
CLAIM_TTL_MINUTES = 10
# 终态集合（已结算，不可再 claim/result）
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
# 子记录结算终态。manual_required 是暂停态，后续人工接管可继续转 success/failed。
RECORD_TERMINAL = {"success", "failed", "skipped"}


def _fail_interrupted_batch(db: Session, task: AutoPublishTask, message: str) -> None:
    """Terminally fail a local-client batch when its executor disappears.

    The product rule is deliberately fail-closed: do not re-queue after the
    client closes, because a browser may already have submitted the article.
    """
    now = datetime.now()
    records = db.query(AutoPublishRecord).filter(
        AutoPublishRecord.task_id == task.id,
        AutoPublishRecord.status.in_(["pending", "publishing", "manual_required"]),
    ).all()
    affected_article_ids = {record.article_id for record in records}
    for record in records:
        record.status = "failed"
        record.error_msg = message
        record.completed_at = now
    task.failed_count = (task.failed_count or 0) + len(records)
    task.status = "failed"
    task.error_msg = message
    task.completed_at = now
    task.manual_required = False
    task.manual_message = None
    task.claimed_by_device_id = None
    task.claim_expires_at = None
    db.commit()

    # Do not overwrite a successfully published article when it has another
    # target in this batch that already succeeded.  Otherwise clear the stale
    # aggregate "publishing" state so the article list accurately shows failure.
    for article_id in affected_article_ids:
        has_success = db.query(AutoPublishRecord.id).filter(
            AutoPublishRecord.article_id == article_id,
            AutoPublishRecord.status == "success",
        ).first()
        article = db.query(GeoArticle).filter(GeoArticle.id == article_id).first()
        if article and not has_success and article.publish_status == "publishing":
            article.publish_status = "failed"
            article.error_msg = message
    db.commit()


def _resolve_account_target_forum(account: Optional[Account]) -> Optional[str]:
    """从 Account.tags（list）解析贴吧默认目标吧，返回规范化吧名。

    仅贴吧需要；其它平台 tags 里不含 "吧:" 前缀，返回 None 不影响。编码约定与发布器
    共用 services/tieba_forum（单一事实源），服务端先解析成干净字段透传给客户端 runner，
    避免 local_client JSON 序列化后丢失吧名。
    """
    if account is None:
        return None
    return default_forum_from_tags(getattr(account, "tags", None))


def _resolve_article_keyword(article: Optional[GeoArticle]) -> Optional[str]:
    """取文章关键词，用作发布时的「添加标签」（掘金等平台标签必填）。

    优先 GeoArticle.keyword 关联对象的 .keyword 文本；关联缺失/未加载时静默返回 None，
    发布器会回退默认标签，绝不因取标签失败而中断发布。
    """
    if article is None:
        return None
    try:
        keyword_obj = getattr(article, "keyword", None)
        text = getattr(keyword_obj, "keyword", None) if keyword_obj is not None else None
        if isinstance(text, str) and text.strip():
            return text.strip()[:20]
    except Exception:
        pass
    return None


def _resolve_article_industry(article: Optional[GeoArticle]) -> Optional[str]:
    """取文章所属公司/项目的行业，用作发布时的「添加标签」首选。

    行业是短词（如「餐饮」「AI客服」），比整句关键词更适合做掘金等平台的标签。
    路径：GeoArticle.keyword.project.industry，其次 project.client.industry。
    关联缺失/未加载静默返回 None，发布器再回退关键词/默认标签。
    """
    if article is None:
        return None
    try:
        keyword_obj = getattr(article, "keyword", None)
        project = getattr(keyword_obj, "project", None) if keyword_obj is not None else None
        if project is not None:
            text = getattr(project, "industry", None)
            if isinstance(text, str) and text.strip():
                return text.strip()[:20]
            client = getattr(project, "client", None)
            if client is not None:
                text = getattr(client, "industry", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()[:20]
    except Exception:
        pass
    return None


# ==================== 请求模型 ====================


class ClaimRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


class HeartbeatRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


class TaskResultRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    record_id: int = Field(..., description="本次回传结果对应的子记录ID")
    status: str = Field(..., description="success | failed | manual_required")
    platform_url: Optional[str] = Field(None, max_length=500)
    error_code: Optional[str] = Field(None, max_length=50)
    error_msg: Optional[str] = None
    auth_status: Optional[str] = Field(
        None,
        description="publisher 显式鉴权判定：logged_out | manual_intervention | unknown。"
        "优先于 error_msg 关键词推断，用于决定是否把账号标为失效。",
    )
    requires_reauth: Optional[bool] = Field(None, description="是否需要重新授权（登录态失效）")


class ManualRequiredRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1)
    record_id: Optional[int] = None


class ResumeManualRecordRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


# ==================== 内部工具 ====================


def _ensure_online(device: ClientDevice) -> None:
    if not is_device_online(device):
        raise HTTPException(status_code=400, detail="DEVICE_OFFLINE：设备离线，请先心跳上线")


def _load_claimable_task(db: Session, task_id: int, current_user: User) -> AutoPublishTask:
    """加载任务并做本地客户端可执行性校验。"""
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")
    if task.execution_mode != "local_client":
        raise HTTPException(status_code=400, detail="该任务不是 local_client 模式，不可由本地客户端执行")
    return task


def _serialize_task_summary(task: AutoPublishTask) -> Dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "execution_mode": task.execution_mode,
        "assigned_device_id": task.assigned_device_id,
        "claimed_by_device_id": task.claimed_by_device_id,
        "claim_expires_at": task.claim_expires_at.isoformat() if task.claim_expires_at else None,
        "manual_required": bool(task.manual_required),
        "manual_message": task.manual_message,
        "total_count": task.total_count,
        "completed_count": task.completed_count,
        "failed_count": task.failed_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _task_platforms(db: Session, task: AutoPublishTask) -> List[str]:
    """任务涉及的平台集合（由其账号决定）。"""
    accounts = db.query(Account).filter(Account.id.in_(task.account_ids or [])).all()
    return sorted({a.platform for a in accounts})


def _settle_task_if_no_open_records(db: Session, task: AutoPublishTask) -> bool:
    """If a local-client task has no runnable records left, settle it and remove it from the queue."""
    if task.status in TERMINAL_STATUSES:
        return True

    now = datetime.now()
    if task.claim_expires_at and task.claim_expires_at < now:
        _fail_interrupted_batch(db, task, "发布客户端已关闭或连接中断，当前及后续发布任务已终止。")
        logger.warning(f"local_client 任务 {task.id} 领取锁过期，已按客户端中断规则终止整批任务")
        return True

    manual_count = (
        db.query(AutoPublishRecord.id)
        .filter(AutoPublishRecord.task_id == task.id, AutoPublishRecord.status == "manual_required")
        .count()
    )
    if manual_count > 0:
        task.status = "manual_required"
        task.manual_required = True
        task.claimed_by_device_id = None
        task.claim_expires_at = None
        db.commit()
        logger.info(f"local_client 任务 {task.id} 等待人工接管，已从自动领取队列移除")
        return True

    open_count = (
        db.query(AutoPublishRecord.id)
        .filter(AutoPublishRecord.task_id == task.id, AutoPublishRecord.status.in_(["pending", "publishing"]))
        .count()
    )
    if open_count > 0:
        return False

    if task.exec_type == "interval" and rearm_interval_task(db, task):
        logger.info(f"local_client 间隔任务 {task.id} 本轮完成，将于 {task.scheduled_at} 再次执行")
        return True

    task.status = "failed" if (task.failed_count or 0) > 0 else "completed"
    task.completed_at = task.completed_at or now
    task.manual_required = False
    task.claimed_by_device_id = None
    task.claim_expires_at = None
    db.commit()
    logger.info(
        f"local_client 任务 {task.id} 无待执行子记录，自动结算为 {task.status} "
        f"({task.completed_count or 0}/{task.total_count or 0}, failed={task.failed_count or 0})"
    )
    return True


# ==================== 接口 ====================


@router.get("/poll", response_model=ApiResponse)
async def poll_tasks(
    device_id: str = Query(..., min_length=1, max_length=64, description="领取设备ID"),
    platform: Optional[str] = Query(None, description="只看指定平台"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    轮询当前用户可领取的 local_client 发布任务。

    返回 execution_mode=local_client 且处于 pending（或已被领取但锁过期）的任务。
    可用 assigned_device_id 限定到本设备，或派发到任一在线设备。
    """
    device = get_owned_device(db,device_id, current_user)
    now = datetime.now()

    query = (
        db.query(AutoPublishTask)
        .filter(
            AutoPublishTask.user_id == current_user.id,
            AutoPublishTask.execution_mode == "local_client",
            AutoPublishTask.status.in_(["pending", "running"]),
            # 定时/间隔任务（exec_type='scheduled'/'interval'）在到达 scheduled_at 之前不暴露给
            # 本地客户端领取，到点后由客户端正常领取执行；非定时任务不受影响。
            or_(
                AutoPublishTask.scheduled_at.is_(None),
                AutoPublishTask.scheduled_at <= now,
            ),
        )
    )
    # 只看派发给本设备、或未指定设备的任务
    query = query.filter(
        or_(
            AutoPublishTask.assigned_device_id.is_(None),
            AutoPublishTask.assigned_device_id == device_id,
        )
    )

    tasks = query.order_by(AutoPublishTask.created_at.asc()).limit(limit).all()

    items = []
    for task in tasks:
        if _settle_task_if_no_open_records(db, task):
            continue
        # 跳过正被其它设备持有且未过期的领取
        held_by_other = (
            task.claimed_by_device_id
            and task.claimed_by_device_id != device_id
            and task.claim_expires_at
            and task.claim_expires_at > now
        )
        if held_by_other:
            continue
        if platform and platform not in _task_platforms(db, task):
            continue
        items.append(_serialize_task_summary(task))

    return ApiResponse(data={"device_online": is_device_online(device, now=now), "items": items})


@router.post("/{task_id}/claim", response_model=ApiResponse)
async def claim_task(
    task_id: int,
    request: ClaimRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    领取任务：原子地把任务锁定到本设备。

    - 未被领取 / 本设备已领取 / 旧领取已过期 → 领取成功
    - 被其它设备持有且未过期 → 409
    """
    task = _load_claimable_task(db, task_id, current_user)
    if task.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="任务已结束，无法领取")

    # 硬校验：任务已指定执行设备时，只允许该设备领取（多机同账号场景下
    # 即使绕过 poll 直接 claim，其它设备也无法抢走本机创建的任务）
    if task.assigned_device_id and task.assigned_device_id != request.device_id:
        raise HTTPException(
            status_code=403,
            detail="该任务已指定由其它设备执行，本机无法领取",
        )

    device = get_owned_device(db,request.device_id, current_user)
    _ensure_online(device)

    if _settle_task_if_no_open_records(db, task):
        return ApiResponse(
            data={
                "task": _serialize_task_summary(task),
                "record_ids": [],
                "claim_expires_at": None,
                "settled": True,
            }
        )

    now = datetime.now()
    expires_at = now + timedelta(minutes=CLAIM_TTL_MINUTES)

    # 原子条件更新：仅当未被「其它有效领取」持有时才锁定
    stmt = (
        update(AutoPublishTask)
        .where(
            AutoPublishTask.id == task_id,
            or_(
                AutoPublishTask.claimed_by_device_id.is_(None),
                AutoPublishTask.claimed_by_device_id == request.device_id,
                AutoPublishTask.claim_expires_at < now,
            ),
        )
        .values(claimed_by_device_id=request.device_id, claim_expires_at=expires_at, status="running")
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="任务已被其它设备领取")

    db.commit()
    db.refresh(task)
    # 首次领取记录开始时间
    if not task.started_at:
        task.started_at = now
        db.commit()
        db.refresh(task)

    record_ids = [
        r.id
        for r in db.query(AutoPublishRecord.id)
        .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.status == "pending")
        .all()
    ]

    # No pending record but publishing remains means the previous client died.
    # Product policy is to fail the whole batch instead of re-claiming it.
    if not record_ids:
        stale_ids = [
            r.id
            for r in db.query(AutoPublishRecord.id)
            .filter(
                AutoPublishRecord.task_id == task_id,
                AutoPublishRecord.status == "publishing",
            )
            .all()
        ]
        if stale_ids:
            _fail_interrupted_batch(db, task, "发布客户端已关闭或连接中断，当前及后续发布任务已终止。")
            db.refresh(task)
            logger.warning(
                f"任务 {task_id} 领取时发现 {len(stale_ids)} 条中断 publishing 记录，已终止整批任务"
            )
            return ApiResponse(
                data={
                    "task": _serialize_task_summary(task),
                    "record_ids": [],
                    "claim_expires_at": None,
                    "settled": True,
                }
            )

    logger.info(
        f"任务 {task_id} 被设备 {request.device_id} 领取，锁至 {expires_at.isoformat()}，"
        f"待执行子记录 {len(record_ids)} 条"
    )
    return ApiResponse(
        data={
            "task": _serialize_task_summary(task),
            "record_ids": record_ids,
            "claim_expires_at": expires_at.isoformat(),
        }
    )


@router.post("/{task_id}/heartbeat", response_model=ApiResponse)
async def heartbeat_task(
    task_id: int,
    request: HeartbeatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """续租领取锁。仅当前领取设备可续。"""
    task = _load_claimable_task(db, task_id, current_user)
    if task.claimed_by_device_id != request.device_id:
        raise HTTPException(status_code=403, detail="只有领取该任务的设备可以续租")

    get_owned_device(db,request.device_id, current_user)  # 归属校验
    expires_at = datetime.now() + timedelta(minutes=CLAIM_TTL_MINUTES)
    task.claim_expires_at = expires_at
    db.commit()
    return ApiResponse(data={"task_id": task_id, "claim_expires_at": expires_at.isoformat()})


@router.post("/{task_id}/terminate", response_model=ApiResponse)
async def terminate_task(
    task_id: int,
    request: HeartbeatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Fail the active batch when the local publishing client exits normally."""
    task = _load_claimable_task(db, task_id, current_user)
    get_owned_device(db, request.device_id, current_user)
    if task.claimed_by_device_id != request.device_id:
        raise HTTPException(status_code=403, detail="只有领取该任务的设备可以终止")
    _fail_interrupted_batch(db, task, "发布客户端已关闭，当前及后续发布任务已终止。")
    return ApiResponse(data={"task_id": task_id, "status": "failed"})


@router.get("/{task_id}/payload", response_model=ApiResponse)
async def get_task_payload(
    task_id: int,
    device_id: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取任务执行所需的全部素材：每条子记录对应文章标题/正文 + 账号信息 + 发布选项。

    素材临时下载 URL（图片等）属 Phase 3 范畴，本期返回文章内联正文，不涉及短期 token 下载。
    """
    task = _load_claimable_task(db, task_id, current_user)
    get_owned_device(db,device_id, current_user)

    # 硬校验：任务指定了执行设备时，只有该设备能拉取素材
    if task.assigned_device_id and task.assigned_device_id != device_id:
        raise HTTPException(status_code=403, detail="该任务已指定由其它设备执行，本机无法获取内容")

    records = (
        db.query(AutoPublishRecord)
        .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.status == "pending")
        .order_by(AutoPublishRecord.id.asc())
        .all()
    )

    # 预取文章与账号，避免 N+1
    article_ids = {r.article_id for r in records}
    account_ids = {r.account_id for r in records}
    articles = {a.id: a for a in db.query(GeoArticle).filter(GeoArticle.id.in_(article_ids)).all()}
    accounts = {a.id: a for a in db.query(Account).filter(Account.id.in_(account_ids)).all()}

    payload_records = []
    for r in records:
        account = accounts.get(r.account_id)
        article = articles.get(r.article_id)
        platform = account.platform if account else None
        payload_records.append(
            {
                "record_id": r.id,
                "status": r.status,
                "article_id": r.article_id,
                "account_id": r.account_id,
                "platform": platform,
                "platform_name": PLATFORMS.get(platform, {}).get("name", platform) if platform else None,
                "account_name": account.account_name if account else None,
                "auth_mode": account.auth_mode if account else None,
                # 贴吧默认目标吧（仅贴吧非空）：服务端从 Account.tags 解析成干净字段，
                # 客户端 runner 透传给 TiebaPublisher，避免 local_client JSON 丢失吧名。
                "target_forum": _resolve_account_target_forum(account),
                "article": {
                    "id": article.id if article else None,
                    "title": article.title if article else None,
                    "content": article.content if article else None,
                    # 文章关键词：掘金等平台发布时用作「添加标签」。取自 GeoArticle.keyword 关联。
                    "keyword": _resolve_article_keyword(article),
                    # 所属行业：短词，作为「添加标签」的首选（比整句关键词更适合做标签）。
                    "industry": _resolve_article_industry(article),
                    "cover_path": getattr(article, "cover_path", None) if article else None,
                    "cover_image_path": getattr(article, "cover_image_path", None) if article else None,
                    "cover_url": getattr(article, "cover_url", None) if article else None,
                    "image_paths": getattr(article, "image_paths", None) if article else None,
                    "image_urls": getattr(article, "image_urls", None) if article else None,
                },
            }
        )

    return ApiResponse(
        data={
            "task": _serialize_task_summary(task),
            "publish_options": {"declare_ai_content": bool(task.declare_ai_content)},
            "records": payload_records,
        }
    )


@router.post("/{task_id}/records/{record_id}/start", response_model=ApiResponse)
async def start_record(
    task_id: int,
    record_id: int,
    request: HeartbeatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Move exactly one queued record into publishing before invoking its publisher."""
    task = _load_claimable_task(db, task_id, current_user)
    get_owned_device(db, request.device_id, current_user)
    now = datetime.now()
    if task.claimed_by_device_id != request.device_id or (task.claim_expires_at and task.claim_expires_at < now):
        raise HTTPException(status_code=410, detail="TASK_CLAIM_EXPIRED：领取锁已过期，请重新领取")
    record = db.query(AutoPublishRecord).filter(
        AutoPublishRecord.task_id == task_id, AutoPublishRecord.id == record_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="子记录不存在")
    if record.status == "pending":
        record.status = "publishing"
        record.started_at = now
        db.commit()
    elif record.status != "publishing":
        raise HTTPException(status_code=400, detail=f"子记录当前状态为 {record.status}，无法开始")
    return ApiResponse(data={"record_id": record.id, "status": record.status})


def _is_login_expired_error(msg: str | None) -> bool:
    """判断发布失败是否由"确定登录过期"引起。

    保守策略：只有错误信息明确指向登录失效、且不含反爬/风控/验证码等不确定因素时，
    才返回 True。风控、反爬、网络、内容审核、频率限制等一律返回 False——绝不据此把账号标为失效。
    """
    if not msg:
        return False
    # 明确排除"非登录过期"的不确定因素
    if any(k in msg for k in ("反爬", "安全验证", "验证码", "风控", "滑块", "人工", "扫码", "频率", "内容", "审核", "网络", "超时", "异常")):
        return False
    # 明确的登录过期信号
    return any(k in msg for k in ("未登录", "登录态失效", "登录会话已过期", "请重新授权", "请重新登录", "账号未登录", "登录失效", "会话已过期"))


def _sync_account_auth_state(account, status: str, error_msg: str | None, now, auth_status: str | None = None) -> None:
    """发布结果回写账号授权状态（唯一允许改写 status 的位置之一）。

    优先级：publisher 显式 auth_status > error_msg 关键词推断。
    - auth_status == "logged_out"：确定登出 → status=-1，并刷新 last_check_time（浏览器已确证）。
    - auth_status == "unknown" / "manual_intervention"：不确定或风控/验证码 → 绝不推断失效。
    - 未提供 auth_status 时回退到关键词推断（_is_login_expired_error）。
    - 发布成功：证明会话确实有效 → 刷新 last_check_time；若此前被标 -1 则恢复为 1。
      不覆盖用户主动禁用（status=0）。
    """
    if account is None:
        return
    # 1) 优先采用 publisher 显式信号
    if auth_status == "logged_out":
        account.status = -1
        account.last_check_time = now
        return
    if auth_status in ("unknown", "manual_intervention"):
        # 不确定 / 风控 / 验证码：绝不据此推断账号失效
        return
    # 2) 回退：关键词推断（仅在未提供显式 auth_status 时）
    if status == "success":
        account.last_check_time = now
        if account.status == -1:
            account.status = 1
    elif status == "failed" and _is_login_expired_error(error_msg):
        account.status = -1


@router.post("/{task_id}/result", response_model=ApiResponse)
async def report_result(
    task_id: int,
    request: TaskResultRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    回传单条子记录的发布结果。

    success/failed 推进任务计数；manual_required 仅标记人工接管，不计入完成/失败。
    全部子记录结算后任务自动转入 completed/failed。
    """
    task = _load_claimable_task(db, task_id, current_user)
    get_owned_device(db,request.device_id, current_user)

    # 必须由本设备持有有效领取
    now = datetime.now()
    if task.claimed_by_device_id != request.device_id:
        raise HTTPException(status_code=403, detail="只有领取该任务的设备可以回传结果")
    if task.claim_expires_at and task.claim_expires_at < now:
        raise HTTPException(status_code=410, detail="TASK_CLAIM_EXPIRED：领取锁已过期，请重新领取")

    record = (
        db.query(AutoPublishRecord)
        .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.id == request.record_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="子记录不存在")

    # 预取账号，用于发布成功后回写授权状态（刷新验证时间 / 恢复有效 / 确定过期标 -1）
    account = db.query(Account).filter(Account.id == record.account_id).first()

    if request.status not in {"success", "failed", "manual_required"}:
        raise HTTPException(status_code=400, detail="status 只能是 success/failed/manual_required")

    # 发布结果时间统一用北京时间落库（completed_at / publish_time / last_check_time），
    # 与首页「今日发布」统计窗口（beijing_today_start）口径一致，避免服务器 TZ 漂移。
    now = beijing_now()

    if request.status == "manual_required":
        task.manual_required = True
        task.manual_message = request.error_msg or "发布过程需要人工接管"
        task.status = "manual_required"
        record.status = "manual_required"
        record.error_msg = task.manual_message
        db.commit()
        logger.info(f"任务 {task_id} 子记录 {record.id} 标记人工接管")
        return ApiResponse(data={"task": _serialize_task_summary(task), "settled": False})

    # 幂等：子记录已结算则不重复计数
    already_settled = record.status in RECORD_TERMINAL
    if not already_settled:
        if request.status == "success":
            record.status = "success"
            record.platform_url = request.platform_url
            task.completed_count = (task.completed_count or 0) + 1
        else:  # failed
            record.status = "failed"
            code = f"[{request.error_code}] " if request.error_code else ""
            record.error_msg = f"{code}{request.error_msg or '未知错误'}".strip()
            task.failed_count = (task.failed_count or 0) + 1
        record.completed_at = now

    # 发布结果回写账号授权状态（成功刷新验证时间/恢复有效；确定登录过期标 -1；其余不动）
    _sync_account_auth_state(account, request.status, request.error_msg, now, request.auth_status)
    db.commit()

    # ---- 同步 GeoArticle 发布状态 ----
    # local_client 发布结果回传后，同步更新文章 publish_status，使文章列表页能正确展示。
    # 此前该步骤缺失，导致「文章实际已发布成功，但文章列表页仍显示发布失败」的问题。
    article = db.query(GeoArticle).filter(GeoArticle.id == record.article_id).first()
    if article and request.status in ("success", "failed") and not already_settled:
        account = db.query(Account).filter(Account.id == record.account_id).first()
        platform_name = PLATFORMS.get(account.platform, {}).get("name", account.platform) if account else None
        if request.status == "success":
            article.publish_status = "published"
            article.publish_time = now
            if request.platform_url:
                article.platform_url = request.platform_url
            if account:
                article.platform = account.platform
                article.account_id = account.id
            article.error_msg = None
        else:
            article.publish_status = "failed"
            code = f"[{request.error_code}] " if request.error_code else ""
            article.error_msg = f"{code}{request.error_msg or '未知错误'}".strip()
            if account:
                article.platform = account.platform
                article.account_id = account.id
        db.commit()

        # 推送 WebSocket 通知，让前端文章列表页实时更新
        try:
            import asyncio
            from backend.api.publish import get_ws_manager
            ws_mgr = get_ws_manager()
            if ws_mgr:
                asyncio.ensure_future(ws_mgr.broadcast({
                    "type": "auto_publish_progress",
                    "task_id": task_id,
                    "data": {
                        "record_id": record.id,
                        "article_id": article.id,
                        "article_title": article.title,
                        "account_id": record.account_id,
                        "account_name": account.account_name if account else None,
                        "platform": account.platform if account else None,
                        "platform_name": platform_name,
                        "publish_status": article.publish_status,
                        "status": record.status,
                        "platform_url": article.platform_url,
                        "error_msg": article.error_msg,
                        "completed_count": task.completed_count,
                        "failed_count": task.failed_count,
                        "total_count": task.total_count,
                    },
                }))
        except Exception:
            pass

    completed_count = task.completed_count or 0
    failed_count = task.failed_count or 0
    settled_total = completed_count + failed_count

    task_just_settled = False
    rearmed = False
    if settled_total >= (task.total_count or 0):
        if task.exec_type == "interval" and rearm_interval_task(db, task):
            rearmed = True
            task_just_settled = True
        else:
            task.status = "failed" if failed_count > 0 else "completed"
            task.completed_at = now
            task.manual_required = False
            task_just_settled = True

    db.commit()
    db.refresh(task)

    # 清晰地打印最终判定结果
    if task_just_settled:
        if rearmed:
            logger.success(
                f"⏳ 间隔任务 {task_id} 本轮完成：成功 {completed_count}/{task.total_count}，"
                f"失败 {failed_count}；将于 {task.scheduled_at.strftime('%Y-%m-%d %H:%M')} 再次执行"
            )
        elif task.status == "completed":
            logger.success(
                f"✅ 任务 {task_id} 全部完成：成功 {task.completed_count}/{task.total_count}，"
                f"失败 {task.failed_count}"
            )
        else:
            # 失败时把各子记录的失败原因一并打出，避免只能翻 exe 日志。
            try:
                failed_records = (
                    db.query(AutoPublishRecord)
                    .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.status == "failed")
                    .all()
                )
                reasons = "; ".join(
                    f"#{r.id}:{r.error_msg}" for r in failed_records if r.error_msg
                )
                reason_text = f"；原因: {reasons}" if reasons else ""
            except Exception:
                reason_text = ""
            logger.warning(
                f"⚠️ 任务 {task_id} 已结束（含失败）：成功 {task.completed_count}/{task.total_count}，"
                f"失败 {task.failed_count}{reason_text}"
            )
    else:
        extra = (
            f"，原因: {record.error_msg}"
            if request.status == "failed" and record.error_msg
            else ""
        )
        logger.info(
            f"任务 {task_id} 子记录 {record.id} 回传 {request.status}；"
            f"进度 {settled_total}/{task.total_count}{extra}"
        )
    return ApiResponse(data={"task": _serialize_task_summary(task), "settled": task_just_settled})


@router.post("/{task_id}/records/{record_id}/resume-manual", response_model=ApiResponse)
async def resume_manual_record(
    task_id: int,
    record_id: int,
    request: ResumeManualRecordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """将 manual_required 子记录恢复为 publishing，供本地 headed 接管继续执行。"""
    task = _load_claimable_task(db, task_id, current_user)
    get_owned_device(db, request.device_id, current_user)

    now = datetime.now()
    if task.claimed_by_device_id != request.device_id:
        raise HTTPException(status_code=403, detail="只有领取该任务的设备可以恢复人工接管记录")
    if task.claim_expires_at and task.claim_expires_at < now:
        raise HTTPException(status_code=410, detail="TASK_CLAIM_EXPIRED：领取锁已过期，请重新领取")

    record = (
        db.query(AutoPublishRecord)
        .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="子记录不存在")
    if record.status != "manual_required":
        return ApiResponse(data={"task": _serialize_task_summary(task), "record_status": record.status})

    task.status = "running"
    task.manual_required = False
    task.manual_message = None
    record.status = "publishing"
    db.commit()
    logger.info(f"任务 {task_id} 子记录 {record.id} 从人工接管恢复为 publishing")
    return ApiResponse(data={"task": _serialize_task_summary(task), "record_status": record.status})


@router.post("/{task_id}/manual-required", response_model=ApiResponse)
async def mark_manual_required(
    task_id: int,
    request: ManualRequiredRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """标记任务需要人工接管（验证码/扫码/风控等），不判定失败。"""
    task = _load_claimable_task(db, task_id, current_user)
    get_owned_device(db,request.device_id, current_user)

    task.manual_required = True
    task.manual_message = request.message
    db.commit()
    db.refresh(task)
    logger.info(f"任务 {task_id} 标记人工接管：{request.message}")
    return ApiResponse(data={"task": _serialize_task_summary(task)})
