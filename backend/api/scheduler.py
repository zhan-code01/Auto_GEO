# -*- coding: utf-8 -*-
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.database.models import ScheduledTask
from backend.services.scheduler_service import get_scheduler_service
from backend.schemas import ApiResponse

router = APIRouter(prefix="/api/scheduler", tags=["定时任务管理"])


# --- Schema ---
class TaskUpdate(BaseModel):
    cron_expression: str
    is_active: bool


class TaskResponse(BaseModel):
    id: int
    name: str
    task_key: str
    cron_expression: str
    is_active: bool
    description: Optional[str] = None

    class Config:
        from_attributes = True


# --- API ---


@router.get("/jobs", response_model=List[TaskResponse])
async def list_jobs(db: Session = Depends(get_db)):
    """获取所有定时任务配置"""
    return db.query(ScheduledTask).all()


@router.post("/start", response_model=ApiResponse)
async def start_scheduler():
    """启动调度器服务。"""
    scheduler = get_scheduler_service()
    was_running = scheduler.is_running()
    scheduler.start()
    logger.info(f"[Scheduler] 收到启动指令（此前运行中={was_running}）")
    return ApiResponse(success=True, message="调度器已启动")


@router.post("/stop", response_model=ApiResponse)
async def stop_scheduler():
    """停止调度器服务。"""
    scheduler = get_scheduler_service()
    scheduler.stop()
    logger.info("[Scheduler] 收到停止指令，调度引擎已停止")
    return ApiResponse(success=True, message="调度器已停止")


@router.put("/jobs/{task_id}", response_model=ApiResponse)
async def update_job(task_id: int, data: TaskUpdate, db: Session = Depends(get_db)):
    """更新任务配置（Cron或开关）"""
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    if not task:
        logger.warning(f"[Scheduler] 更新任务失败：任务不存在 task_id={task_id}")
        return ApiResponse(success=False, message="任务不存在")

    old_cron, old_active = task.cron_expression, task.is_active
    # 更新数据库
    task.cron_expression = data.cron_expression
    task.is_active = data.is_active
    db.commit()

    # 🌟 关键：通知调度器热重载该任务，并如实反馈重载结果
    scheduler = get_scheduler_service()
    if not scheduler.reload_task(task_id):
        db.rollback()
        logger.error(
            f"[Scheduler] 任务配置已保存但热重载失败: task_id={task_id} name={task.name} cron={data.cron_expression}"
        )
        return ApiResponse(success=False, message="任务配置已保存，但调度器热重载失败")

    logger.info(
        f"[Scheduler] 任务配置已更新: task_id={task_id} name={task.name} "
        f"cron={old_cron}->{data.cron_expression} active={old_active}->{data.is_active}"
    )
    return ApiResponse(success=True, message="任务配置已更新并生效")


@router.post("/jobs/{job_id}/run", response_model=ApiResponse)
async def trigger_job(job_id: str):
    """
    立即触发任务执行

    参数:
        job_id: APScheduler 的 Job ID (task_key，如 "publish_task")

    实现:
        使用 job.modify(next_run_time=datetime.now()) 将任务下一次运行时间设置为现在，
        调度器会立即捡起并执行，且不影响原来的周期计划。
    """
    scheduler = get_scheduler_service()
    success = scheduler.trigger_job(job_id)

    if success:
        logger.info(f"[Scheduler] 手动触发任务成功: {job_id}")
        return ApiResponse(success=True, message=f"任务 [{job_id}] 已触发执行")
    else:
        logger.warning(f"[Scheduler] 手动触发任务失败（不存在或未运行）: {job_id}")
        raise HTTPException(status_code=404, detail=f"任务 [{job_id}] 不存在或未运行")
