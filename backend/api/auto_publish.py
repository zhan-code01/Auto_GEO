# -*- coding: utf-8 -*-
"""
自动发布任务管理 API
实现后台任务队列管理系统
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from loguru import logger

from backend.database import get_db
from backend.database.models import (
    AutoPublishTask,
    AutoPublishRecord,
    Account,
    GeoArticle,
    User,
)
from backend.schemas import (
    ApiResponse,
    AutoPublishTaskCreate,
    AutoPublishTaskUpdate,
    AutoPublishTaskResponse,
    AutoPublishTaskDetailResponse,
    AutoPublishRecordResponse,
)
from backend.config import PLATFORMS
from backend.api.user import get_current_user_from_token
from backend.middleware.user_isolation import scoped_query, require_owner
from backend.utils.time_utils import beijing_now


router = APIRouter(prefix="/api/auto-publish", tags=["自动发布任务管理"])


# ==================== 全局任务执行管理器 ====================


class AutoPublishTaskExecutor:
    """
    自动发布任务执行器
    管理后台任务的执行、重试和状态更新
    """

    def __init__(self):
        self._running_tasks: dict = {}  # task_id -> task_info

    def start_task(self, task_id: int):
        """标记任务开始执行"""
        self._running_tasks[task_id] = {
            "status": "running",
            "started_at": datetime.now(),
        }

    def complete_task(self, task_id: int, success: bool = True, error_msg: str = None):
        """标记任务完成"""
        if task_id in self._running_tasks:
            self._running_tasks[task_id]["status"] = "completed" if success else "failed"
            self._running_tasks[task_id]["completed_at"] = datetime.now()
            if error_msg:
                self._running_tasks[task_id]["error_msg"] = error_msg

    def is_task_running(self, task_id: int) -> bool:
        """检查任务是否正在运行"""
        return self._running_tasks.get(task_id, {}).get("status") == "running"


# 全局执行器实例
task_executor = AutoPublishTaskExecutor()


def rearm_interval_task(db: Session, task: AutoPublishTask) -> bool:
    """
    间隔执行（interval）任务一轮结束后，重武装下一次执行时间并复位子记录。

    返回 True 表示任务将继续周期执行（status 已复位 pending，scheduled_at 已顺延）；
    返回 False 表示本轮全部失败，任务保持 failed 终态，不再循环，避免无意义重试。
    """
    interval_minutes = task.interval_minutes or 0
    if interval_minutes <= 0:
        return False
    if (task.failed_count or 0) >= (task.total_count or 0):
        return False

    now = datetime.now()
    task.status = "pending"
    task.scheduled_at = now + timedelta(minutes=interval_minutes)
    task.started_at = None
    task.completed_at = None
    task.error_msg = None
    task.manual_required = False
    task.manual_message = None
    task.completed_count = 0
    task.failed_count = 0
    task.claimed_by_device_id = None
    task.claim_expires_at = None

    records = db.query(AutoPublishRecord).filter(AutoPublishRecord.task_id == task.id).all()
    for record in records:
        record.status = "pending"
        record.started_at = None
        record.completed_at = None
        record.platform_url = None
        record.error_msg = None
    db.commit()
    logger.info(
        f"⏳ 间隔任务 {task.id} 本轮完成，已重武装，将于 "
        f"{task.scheduled_at.strftime('%Y-%m-%d %H:%M')} 再次执行"
    )
    return True


def get_playwright_mgr():
    """延迟导入，避免循环依赖"""
    from backend.services.playwright_mgr import playwright_mgr

    return playwright_mgr


def get_ws_manager():
    """获取WebSocket管理器"""
    from backend.api.publish import get_ws_manager

    return get_ws_manager()


# ==================== API接口 ====================


@router.get("/tasks", response_model=ApiResponse)
async def get_auto_publish_tasks(
    status: Optional[str] = Query(None, description="任务状态过滤，支持逗号分隔多值：completed,failed,cancelled"),
    platform: Optional[str] = Query(None, description="平台过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取自动发布任务列表

    用于展示用户创建的所有后台发布任务
    支持按状态和平台筛选。status 支持逗号分隔多值，例如 status=failed,cancelled
    表示筛选「失败或已取消」的任务。
    """
    # 按当前用户隔离：普通用户只看自己创建的任务，admin 可见全部
    query = scoped_query(db, AutoPublishTask, current_user).order_by(
        AutoPublishTask.created_at.desc()
    )

    if status:
        # 支持逗号分隔的多值筛选
        status_values = [s.strip() for s in status.split(",") if s.strip()]
        if len(status_values) == 1:
            query = query.filter(AutoPublishTask.status == status_values[0])
        else:
            query = query.filter(AutoPublishTask.status.in_(status_values))

    # 如果指定了平台筛选，使用持久化的 platforms 列在 Python 层过滤
    if platform:
        matched_tasks = [
            task
            for task in query.all()
            if platform in (task.platforms or [])
        ]
        total = len(matched_tasks)
        tasks = matched_tasks[offset : offset + limit]
    else:
        total = query.count()
        tasks = query.offset(offset).limit(limit).all()

    # 转换为响应格式
    task_list = []
    for task in tasks:
        task_list.append(
            {
                "id": task.id,
                "name": task.name,
                "description": task.description,
                "article_ids": task.article_ids or [],
                "account_ids": task.account_ids or [],
                "platforms": task.platforms or [],
                "status": task.status,
                "exec_type": task.exec_type,
                "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
                "interval_minutes": task.interval_minutes,
                "total_count": task.total_count,
                "completed_count": task.completed_count,
                "failed_count": task.failed_count,
                "error_msg": task.error_msg,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
        )

    return ApiResponse(
        data={
            "total": total,
            "items": task_list,
        }
    )


@router.get("/tasks/{task_id}", response_model=ApiResponse)
async def get_auto_publish_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取自动发布任务详情（含子任务记录）

    用于查看任务的详细执行进度和结果
    """
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")

    # 获取子任务记录
    records = (
        db.query(AutoPublishRecord)
        .filter(AutoPublishRecord.task_id == task_id)
        .order_by(AutoPublishRecord.created_at.desc())
        .all()
    )

    # 转换记录为响应格式
    record_list = []
    for record in records:
        # 获取关联信息
        article = db.query(GeoArticle).filter(GeoArticle.id == record.article_id).first()
        account = db.query(Account).filter(Account.id == record.account_id).first()

        record_list.append(
            {
                "id": record.id,
                "task_id": record.task_id,
                "article_id": record.article_id,
                "account_id": record.account_id,
                "status": record.status,
                "platform_url": record.platform_url,
                "error_msg": record.error_msg,
                "retry_count": record.retry_count,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "started_at": record.started_at.isoformat() if record.started_at else None,
                "completed_at": record.completed_at.isoformat() if record.completed_at else None,
                # 关联信息
                "article_title": article.title if article else None,
                "account_name": account.account_name if account else None,
                "platform": account.platform if account else None,
            }
        )

    return ApiResponse(
        data={
            "task": {
                "id": task.id,
                "name": task.name,
                "description": task.description,
                "article_ids": task.article_ids or [],
                "account_ids": task.account_ids or [],
                "platforms": task.platforms or [],
                "status": task.status,
                "exec_type": task.exec_type,
                "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
                "interval_minutes": task.interval_minutes,
                "total_count": task.total_count,
                "completed_count": task.completed_count,
                "failed_count": task.failed_count,
                "error_msg": task.error_msg,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            },
            "records": record_list,
        }
    )


@router.post("/tasks", response_model=ApiResponse)
async def create_auto_publish_task(
    request: AutoPublishTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    创建自动发布任务

    用户选择文章和账号后，创建一个后台发布任务
    """
    # Explicit targets are the source of truth for batch publishing.  Keep the
    # legacy article_ids/account_ids fields for old callers and scheduled tasks.
    targets = request.targets or [
        {"article_id": article_id, "account_id": account_id}
        for article_id in request.article_ids
        for account_id in request.account_ids
    ]
    seen_targets = set()
    normalized_targets = []
    for target in targets:
        article_id = int(target.article_id if hasattr(target, "article_id") else target["article_id"])
        account_id = int(target.account_id if hasattr(target, "account_id") else target["account_id"])
        key = (article_id, account_id)
        if key not in seen_targets:
            seen_targets.add(key)
            normalized_targets.append(key)
    article_ids = sorted({article_id for article_id, _ in normalized_targets})
    account_ids = sorted({account_id for _, account_id in normalized_targets})

    # 1. 验证文章和账号是否存在，且必须属于当前用户
    #    （防 IDOR：禁止用他人的文章/账号发起发布任务）
    articles = (
        scoped_query(db, GeoArticle, current_user)
        .filter(GeoArticle.id.in_(article_ids))
        .all()
    )
    if len(articles) != len(article_ids):
        # 模糊消息：不区分"不存在"与"无权"，避免被用于探测他人数据
        raise HTTPException(status_code=403, detail="部分文章不存在或无权使用")

    accounts = (
        scoped_query(db, Account, current_user)
        .filter(Account.id.in_(account_ids))
        .all()
    )
    if len(accounts) != len(account_ids):
        raise HTTPException(status_code=403, detail="部分账号不存在或无权使用")

    # 2. 检查账号状态
    disabled_accounts = [a.account_name for a in accounts if a.status != 1]
    if disabled_accounts:
        raise HTTPException(status_code=400, detail=f"以下账号未授权或已禁用: {', '.join(disabled_accounts)}")

    # 2.1 检查账号登录态：status=1 只代表"启用"，不代表已登录。
    #     判据统一走 Account.is_authorized（按 session_location 分流）：
    #       - local_only（本地客户端）：以已绑定设备 device_id 为准；
    #       - server（云端浏览器）：以 cookies + storage_state 为准。
    #     否则会出现"未登录也能选择发布"→ 打开浏览器跳登录页 → 白白转人工介入；
    #     或反过来把本地客户端已授权账号误判未登录而挡下。
    def _platform_label(acc) -> str:
        meta = PLATFORMS.get(acc.platform) or {}
        return meta.get("name") or acc.platform

    unauthorized = [
        f"{a.account_name}（{_platform_label(a)}）"
        for a in accounts
        if not a.is_authorized
    ]
    if unauthorized:
        raise HTTPException(
            status_code=400,
            detail=f"以下账号尚未登录，请先在「账号管理」完成授权登录后再发布: {', '.join(unauthorized)}",
        )

    # 3. 检查文章状态（移除限制，允许重复发布）
    # 之前的逻辑：只能发布状态为 completed/scheduled/failed 的文章
    # 新逻辑：允许任何文章重新发布（支持重复发布到不同平台）
    # 只要文章内容存在即可发布
    invalid_articles = [a.title for a in articles if not a.content]
    if invalid_articles:
        raise HTTPException(
            status_code=400,
            detail=f"以下文章内容为空，无法发布: {', '.join(invalid_articles[:3])}{'...' if len(invalid_articles) > 3 else ''}",
        )

    # 4. 验证执行类型和配置
    if request.exec_type == "scheduled" and not request.scheduled_at:
        raise HTTPException(status_code=400, detail="定时执行必须指定执行时间")

    if request.exec_type == "interval" and not request.interval_minutes:
        raise HTTPException(status_code=400, detail="间隔执行必须指定间隔分钟数")

    # 5. 解析定时时间
    scheduled_at = None
    if request.scheduled_at:
        try:
            scheduled_at = datetime.fromisoformat(request.scheduled_at.replace("Z", "+00:00"))
            if scheduled_at <= datetime.now():
                raise HTTPException(status_code=400, detail="定时执行时间必须晚于当前时间")
        except ValueError:
            raise HTTPException(status_code=400, detail="时间格式错误")

    # 5.1 interval 任务未指定首次执行时间时，默认 N 分钟后开始首轮执行（分钟级粒度）
    if request.exec_type == "interval" and scheduled_at is None and request.interval_minutes:
        scheduled_at = datetime.now() + timedelta(minutes=request.interval_minutes)

    # 6. 创建自动发布任务
    total_count = len(normalized_targets)
    # 本地客户端模式：任务保持 pending，等待在线客户端 poll/claim，不由服务器执行
    execution_mode = request.execution_mode or "local_client"

    # 持久化任务涉及的平台列表（从账号反查，避免账号被删后丢失平台信息）
    platforms = sorted({a.platform for a in accounts})

    task = AutoPublishTask(
        name=request.name,
        description=request.description,
        article_ids=article_ids,
        account_ids=account_ids,
        platforms=platforms,
        exec_type=request.exec_type,
        scheduled_at=scheduled_at,
        interval_minutes=request.interval_minutes,
        declare_ai_content=request.declare_ai_content,
        total_count=total_count,
        completed_count=0,
        failed_count=0,
        status="pending",
        execution_mode=execution_mode,
        assigned_device_id=request.assigned_device_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 7. 创建子任务记录
    for article_id, account_id in normalized_targets:
        db.add(AutoPublishRecord(task_id=task.id, article_id=article_id, account_id=account_id, status="pending"))
    db.commit()

    # 8. 根据执行类型启动任务
    # local_client 模式不在服务器执行：任务保持 pending，由在线客户端轮询领取。
    #   - immediate：客户端立即领取执行；
    #   - scheduled/interval：客户端轮询接口已加时间闸门（scheduled_at <= now 才返回该任务），
    #     未到点前不会被领取，到点后由客户端正常领取执行（见 client_publish.py 的 poll_tasks）。
    # cloud_browser / api 模式走服务器 Playwright 执行链路。
    server_executable = execution_mode in ("cloud_browser", "api")
    if server_executable and request.exec_type == "immediate":
        # 立即执行：启动后台任务（通过 BackgroundTaskManager 保护，防止 SSE 取消）
        from backend.services.background_task_manager import background_task_manager
        background_task_manager.submit(
            execute_auto_publish_task(task.id),
            task_name=f"auto_publish_{task.id}",
        )
    elif request.exec_type in ("scheduled", "interval"):
        # 定时/间隔执行：任务保持 pending，等待到点触发。
        #   - local_client：由本地客户端轮询到点领取（时间闸门放行）；
        #   - cloud_browser/api：由调度中心 auto_publish_scheduler 每分钟扫描触发
        #     （分钟级精度，见 scheduler_service.auto_publish_scheduler_job）。
        logger.info(f"任务 {task.id} 为 {request.exec_type} 类型，保持 pending 等待到点触发执行")

    logger.info(f"自动发布批次已创建: {task.id}, 子任务数: {total_count}")

    return ApiResponse(
        data={
            "task_id": task.id,
            "total_count": total_count,
            "message": "自动发布任务已创建",
        }
    )


@router.put("/tasks/{task_id}", response_model=ApiResponse)
async def update_auto_publish_task(
    task_id: int,
    request: AutoPublishTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    更新自动发布任务

    支持修改任务配置或取消任务
    """
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")

    # 如果任务正在运行，不允许修改
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务正在执行中，无法修改")

    # 更新字段
    if request.name is not None:
        task.name = request.name
    if request.description is not None:
        task.description = request.description
    if request.status is not None:
        # 状态转换验证
        valid_transitions = {
            "pending": ["running", "cancelled"],
            "running": ["completed", "failed", "cancelled"],
            "failed": ["pending"],  # 失败任务可以重置为待执行
        }
        current_status = task.status
        if request.status not in valid_transitions.get(current_status, []):
            raise HTTPException(
                status_code=400,
                detail=f"不允许从状态 {current_status} 转换到 {request.status}",
            )
        task.status = request.status

        # 如果取消任务，更新完成时间
        if request.status == "cancelled":
            task.completed_at = datetime.now()

    if request.scheduled_at is not None:
        try:
            scheduled_at = datetime.fromisoformat(request.scheduled_at.replace("Z", "+00:00"))
            if scheduled_at <= datetime.now():
                raise HTTPException(status_code=400, detail="定时执行时间必须晚于当前时间")
            task.scheduled_at = scheduled_at
        except ValueError:
            raise HTTPException(status_code=400, detail="时间格式错误")

    if request.interval_minutes is not None:
        task.interval_minutes = request.interval_minutes

    db.commit()

    return ApiResponse(data={"task_id": task.id, "message": "任务已更新"})


@router.delete("/tasks/{task_id}", response_model=ApiResponse)
async def delete_auto_publish_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除自动发布任务

    只能删除已完成或已取消的任务
    """
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")

    # 不允许删除正在执行的任务
    if task.status == "running":
        raise HTTPException(status_code=400, detail="无法删除正在执行的任务")

    # 先删除关联的子任务记录，再删除任务主记录
    # （SQLite 默认未启用外键级联，故显式删除 records，避免留下孤儿数据）
    db.query(AutoPublishRecord).filter(AutoPublishRecord.task_id == task_id).delete(
        synchronize_session=False
    )
    db.delete(task)
    db.commit()

    logger.info(f"自动发布任务已删除: {task_id}")

    return ApiResponse(data={"message": "任务已删除"})


@router.post("/tasks/{task_id}/start", response_model=ApiResponse)
async def start_auto_publish_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    手动启动自动发布任务

    用于立即执行待执行或失败的任务
    """
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")

    # 检查任务状态
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务正在执行中")

    if task.status not in ["pending", "failed"]:
        raise HTTPException(status_code=400, detail=f"当前任务状态为 {task.status}，无法启动")

    # 启动后台执行任务
    if task.execution_mode == "local_client":
        task.status = "pending"
        task.claimed_by_device_id = None
        task.claim_expires_at = None
        task.manual_required = False
        task.manual_message = None
        task.error_msg = None
        # 手动「启动」= 立即执行：清除原定 scheduled_at，避免轮询时间闸门仍把它
        # 挡到原定时间之后（否则对 pending 的定时任务点「启动」等于空操作）。
        task.scheduled_at = None
        for record in task.records:
            if record.status in ("failed", "manual_required"):
                record.status = "pending"
                record.error_msg = None
        db.commit()
        logger.info(f"local_client publish task is ready for client claim: {task_id}")
        return ApiResponse(data={"task_id": task_id, "message": "任务已准备好，等待本地客户端执行"})

    from backend.services.background_task_manager import background_task_manager
    background_task_manager.submit(
        execute_auto_publish_task(task_id),
        task_name=f"auto_publish_manual_{task_id}",
    )

    logger.info(f"自动发布任务已手动启动: {task_id}")

    return ApiResponse(data={"task_id": task_id, "message": "任务已启动"})


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse)
async def cancel_auto_publish_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    取消正在执行的自动发布任务

    用于停止正在运行的任务
    """
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")

    if task.status != "running":
        raise HTTPException(status_code=400, detail="只能取消正在执行的任务")

    # 更新任务状态
    task.status = "cancelled"
    task.completed_at = datetime.now()
    db.commit()

    # 从执行器中移除
    task_executor.complete_task(task_id, success=False, error_msg="任务已取消")

    logger.info(f"自动发布任务已取消: {task_id}")

    return ApiResponse(data={"task_id": task_id, "message": "任务已取消"})


@router.post("/tasks/{task_id}/retry", response_model=ApiResponse)
async def retry_auto_publish_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    重试失败的自动发布任务

    重新执行任务中失败的子任务
    """
    task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    require_owner(task, current_user, name="自动发布任务")

    if task.status != "failed":
        raise HTTPException(status_code=400, detail="只能重试失败的任务")

    # 重置任务状态
    task.status = "pending"
    task.error_msg = None
    task.failed_count = 0
    task.completed_count = 0
    db.commit()

    # 重置失败的子任务记录
    failed_records = (
        db.query(AutoPublishRecord)
        .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.status == "failed")
        .all()
    )
    for record in failed_records:
        record.status = "pending"
        record.error_msg = None
        record.retry_count = 0
    db.commit()

    # local_client 模式不在服务器执行：复位为待领取，由本地客户端轮询领取后执行。
    if task.execution_mode == "local_client":
        task.claimed_by_device_id = None
        task.claim_expires_at = None
        task.manual_required = False
        task.manual_message = None
        db.commit()
        logger.info(f"local_client 发布任务已重试，等待本地客户端执行: {task_id}")
        return ApiResponse(data={"task_id": task_id, "message": "任务已重试，等待本地客户端执行"})

    # 启动后台执行任务（通过 BackgroundTaskManager 保护，防止 SSE 取消）
    from backend.services.background_task_manager import background_task_manager
    background_task_manager.submit(
        execute_auto_publish_task(task_id),
        task_name=f"auto_publish_retry_{task_id}",
    )

    logger.info(f"自动发布任务已重试: {task_id}")

    return ApiResponse(data={"task_id": task_id, "message": "任务已重试"})


@router.get("/records", response_model=ApiResponse)
async def get_auto_publish_records(
    status: Optional[str] = Query(None, description="子任务状态过滤: pending/publishing/success/failed/skipped"),
    limit: int = Query(20, ge=1, le=200, description="返回数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取自动发布子任务记录

    按当前用户隔离，用于首页「最近活动」等场景展示最近发布结果。
    """
    query = (
        db.query(AutoPublishRecord)
        .join(AutoPublishTask, AutoPublishRecord.task_id == AutoPublishTask.id)
        .filter(AutoPublishTask.user_id == current_user.id)
    )

    if status:
        query = query.filter(AutoPublishRecord.status == status)

    records = (
        query.order_by(AutoPublishRecord.completed_at.desc().nullslast(), AutoPublishRecord.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for record in records:
        article = db.query(GeoArticle).filter(GeoArticle.id == record.article_id).first()
        account = db.query(Account).filter(Account.id == record.account_id).first()
        platform_name = ""
        if account:
            platform_config = PLATFORMS.get(account.platform, {})
            platform_name = platform_config.get("name", account.platform)

        result.append(
            {
                "id": record.id,
                "task_id": record.task_id,
                "article_id": record.article_id,
                "article_title": article.title if article else "",
                "account_id": record.account_id,
                "account_name": account.account_name if account else "",
                "platform": account.platform if account else "",
                "platform_name": platform_name,
                "status": record.status,
                "platform_url": record.platform_url,
                "error_msg": record.error_msg,
                "retry_count": record.retry_count,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "started_at": record.started_at.isoformat() if record.started_at else None,
                "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            }
        )

    return ApiResponse(data={"items": result})


# ==================== 任务执行核心逻辑 ====================


async def execute_auto_publish_task(task_id: int):
    """
    执行自动发布任务（后台异步任务）

    这是核心执行逻辑，负责：
    1. 更新任务状态为 running
    2. 逐个执行子任务（发布文章到账号）
    3. 更新进度和结果
    4. 处理错误和重试

    注意：不再接收 db 参数，函数内部自行管理 Session 生命周期。
    """
    # 获取新的session（避免在异步线程中使用过期的session）
    from backend.database import SessionLocal

    db = SessionLocal()

    try:
        # 1. 获取任务
        task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
        if not task:
            logger.error(f"任务不存在: {task_id}")
            return

        # 2. 更新任务状态
        task.status = "running"
        task.started_at = datetime.now()
        db.commit()

        task_executor.start_task(task_id)

        # 3. 获取子任务记录
        records = (
            db.query(AutoPublishRecord)
            .filter(AutoPublishRecord.task_id == task_id, AutoPublishRecord.status == "pending")
            .all()
        )

        logger.info(f"开始执行自动发布任务: {task_id}, 子任务数: {len(records)}")

        # 4. 获取发布管理器
        publish_mgr = get_playwright_mgr()
        await publish_mgr.start()

        # 5. 逐个执行子任务
        for record in records:
            try:
                # 检查任务是否被取消
                task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
                if task.status == "cancelled":
                    logger.info(f"任务已取消，停止执行: {task_id}")
                    return

                # 更新子任务状态
                record.status = "publishing"
                record.started_at = beijing_now()
                db.commit()

                # 获取文章和账号
                article = db.query(GeoArticle).filter(GeoArticle.id == record.article_id).first()
                account = db.query(Account).filter(Account.id == record.account_id).first()

                if not article or not account:
                    raise Exception("文章或账号不存在")

                # 执行发布 (传递AI声明选项)
                declare_ai = getattr(task, "declare_ai_content", True)

                async def _on_manual_event(event: dict):
                    event_type = event.get("type")
                    current_task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
                    current_record = db.query(AutoPublishRecord).filter(AutoPublishRecord.id == record.id).first()
                    if not current_task or not current_record:
                        return

                    if event_type == "manual_required":
                        message = event.get("message") or event.get("matched_text") or "平台要求人工验证，请在浏览器中完成操作"
                        current_task.manual_required = True
                        current_task.manual_message = message
                        current_task.status = "manual_required"
                        current_record.status = "manual_required"
                        current_record.error_msg = message
                    elif event_type == "manual_resolved":
                        current_task.manual_required = False
                        current_task.manual_message = None
                        current_task.status = "running"
                        current_record.status = "publishing"
                    elif event_type == "manual_timeout":
                        message = "平台要求人工验证，5分钟内未处理完成，本次发布失败，请人工处理后重新发布。"
                        current_task.manual_required = False
                        current_task.manual_message = message
                        current_task.status = "running"
                        current_record.error_msg = message
                    db.commit()

                    ws_mgr = get_ws_manager()
                    if ws_mgr:
                        platform_config = PLATFORMS.get(account.platform, {})
                        await ws_mgr.broadcast(
                            {
                                "type": "auto_publish_manual",
                                "task_id": task_id,
                                "data": {
                                    "record_id": record.id,
                                    "article_id": article.id,
                                    "article_title": article.title,
                                    "account_id": account.id,
                                    "account_name": account.account_name,
                                    "platform": account.platform,
                                    "platform_name": platform_config.get("name", account.platform),
                                    "event": event_type,
                                    "status": current_record.status,
                                    "message": current_record.error_msg or current_task.manual_message,
                                    "timeout_seconds": event.get("timeout_seconds"),
                                    "page_url": event.get("page_url"),
                                    "error_code": event.get("error_code"),
                                },
                            }
                        )

                result = await publish_mgr.execute_publish(
                    article,
                    account,
                    declare_ai_content=declare_ai,
                    manual_event_callback=_on_manual_event,
                )

                if result.get("success"):
                    # 发布成功
                    record.status = "success"
                    record.platform_url = result.get("platform_url")
                    record.completed_at = beijing_now()

                    # 更新任务计数
                    task.completed_count += 1

                    # 同步 GeoArticle 发布状态与发布时间（与 local_client 回传流程 client_publish.py 保持一致）
                    # 否则文章列表页仍停留在旧状态，首页「今日发布」统计也会漏掉服务器侧发布的成功文章
                    article.publish_status = "published"
                    article.publish_time = record.completed_at
                    if result.get("platform_url"):
                        article.platform_url = result.get("platform_url")
                    article.platform = account.platform
                    article.account_id = account.id
                    article.error_msg = None
                else:
                    # 发布失败
                    record.status = "failed"
                    record.error_msg = result.get("error_msg", "未知错误")
                    record.completed_at = beijing_now()
                    record.retry_count += 1

                    # 更新任务计数
                    task.failed_count += 1

                    # 同步文章失败状态，避免文章停留在 publishing 等中间态
                    article.publish_status = "failed"
                    article.error_msg = result.get("error_msg", "未知错误")
                    article.platform = account.platform
                    article.account_id = account.id

                db.commit()

                # WebSocket 推送进度
                ws_mgr = get_ws_manager()
                if ws_mgr:
                    platform_config = PLATFORMS.get(account.platform, {})
                    await ws_mgr.broadcast(
                        {
                            "type": "auto_publish_progress",
                            "task_id": task_id,
                            "data": {
                                "record_id": record.id,
                                "article_id": article.id,
                                "article_title": article.title,
                                "account_id": account.id,
                                "account_name": account.account_name,
                                "platform": account.platform,
                                "platform_name": platform_config.get("name", account.platform),
                                "status": record.status,
                                "platform_url": record.platform_url,
                                "error_msg": record.error_msg,
                                "completed_count": task.completed_count,
                                "failed_count": task.failed_count,
                                "total_count": task.total_count,
                            },
                        }
                    )

            except Exception as e:
                logger.error(f"发布子任务失败: {record.id}, {e}")
                record.status = "failed"
                record.error_msg = str(e)
                record.completed_at = beijing_now()
                record.retry_count += 1
                task.failed_count += 1

                # 同步文章失败状态，避免文章因异常停留在 publishing 等中间态
                failed_article = db.query(GeoArticle).filter(GeoArticle.id == record.article_id).first()
                if failed_article:
                    failed_article.publish_status = "failed"
                    failed_article.error_msg = str(e)
                db.commit()

        # 6. 更新任务完成状态
        task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
        if task:
            if task.exec_type == "interval" and rearm_interval_task(db, task):
                logger.info(f"间隔任务 {task_id} 本轮执行完成，等待下一轮调度")
            else:
                task.status = "completed"
                task.completed_at = datetime.now()

                # 如果有失败的子任务，整体状态设为failed
                if task.failed_count > 0:
                    task.status = "failed"
                    task.error_msg = f"部分发布失败: {task.failed_count}/{task.total_count}"

                db.commit()

        task_executor.complete_task(
            task_id,
            success=(task.status in ("completed", "pending")),
            error_msg=task.error_msg,
        )

        logger.info(f"自动发布任务执行完成: {task_id}, 状态: {task.status}")

    except Exception as e:
        logger.error(f"自动发布任务执行失败: {task_id}, {e}")

        # 更新任务状态为失败
        task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_msg = str(e)
            task.completed_at = datetime.now()
            db.commit()

        task_executor.complete_task(task_id, success=False, error_msg=str(e))

    finally:
        db.close()
