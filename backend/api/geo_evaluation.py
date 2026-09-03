# -*- coding: utf-8 -*-
"""
GEO 五指标测评 API

改造自有收录监控模块，提供：
- 测评问题集生成/查询
- baseline 建立/补齐
- 使用后复测
- 五指标诊断
- 证据明细查询
"""

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from backend.database import get_db, SessionLocal
from backend.database.models import GeoEvaluationRecord, GeoEvaluationRun, Project, Client, User
from backend.schemas import ApiResponse
from backend.api.user import get_current_user_from_token
from backend.services.geo_evaluation_prompt_service import GeoEvaluationPromptService
from backend.services.geo_evaluation_run_service import CLIENT_EVALUATION_PENDING_MARKER, GeoEvaluationRunService
from backend.services.geo_evaluation_analytics_service import GeoEvaluationAnalyticsService
from loguru import logger

router = APIRouter(prefix="/api/geo-evaluation", tags=["GEO五指标测评"])


def _is_missing_geo_evaluation_table(exc: Exception) -> bool:
    """Return True when the database schema is missing GEO evaluation tables or columns."""
    text = str(exc).lower()
    return (
        "undefinedtable" in text
        or "undefinedcolumn" in text
        or "no such column" in text
        or 'relation "geo_prompt_sets" does not exist' in text
        or 'relation "geo_prompts" does not exist' in text
        or 'relation "geo_evaluation_runs" does not exist' in text
        or 'relation "geo_evaluation_records" does not exist' in text
        or 'column "client_id" does not exist' in text
        or 'column "question_distribution" does not exist' in text
        or 'column "related_project_name" does not exist' in text
    )


def _raise_schema_not_ready() -> None:
    raise HTTPException(
        status_code=503,
        detail=(
            "GEO evaluation database tables are not initialized. "
            "Run `python -m alembic upgrade head` and refresh this page."
        ),
    )


# ==================== 用户隔离辅助 ====================


def _is_admin(current_user: User) -> bool:
    return getattr(current_user, "role", None) == "admin"


def _require_client_owner(db: Session, client_id: int, current_user: User) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="公司不存在")
    if not _is_admin(current_user) and client.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该公司")
    return client


def _require_project_owner(db: Session, project_id: int, current_user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not _is_admin(current_user) and project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return project


def _require_project_client(project: Project) -> int:
    if not project.client_id:
        raise HTTPException(status_code=400, detail="当前项目未关联公司，无法使用公司级GEO测评")
    return project.client_id


# ==================== 请求模型 ====================


class GeneratePromptSetRequest(BaseModel):
    question_count: int = Field(default=100, ge=1, le=200)
    question_type_distribution: Optional[dict] = None
    competitors: Optional[List[str]] = None
    overwrite: bool = False
    project_id: Optional[int] = None


class BaselineRequest(BaseModel):
    platforms: Optional[List[str]] = Field(default=None, min_length=1, max_length=1)
    rounds: int = Field(default=1, ge=1, le=3)
    rebuild: bool = False
    project_id: Optional[int] = None
    risk_acknowledged: bool = False
    account_id: Optional[int] = None


class CompleteBaselineRequest(BaseModel):
    platforms: List[str] = Field(..., min_length=1)
    project_id: Optional[int] = None
    risk_acknowledged: bool = False
    account_id: Optional[int] = None


class RecheckRequest(BaseModel):
    platforms: Optional[List[str]] = Field(default=None, min_length=1, max_length=1)
    rounds: int = Field(default=1, ge=1, le=3)
    project_id: Optional[int] = None
    risk_acknowledged: bool = False
    account_id: Optional[int] = None


class BatchDeleteRecordsRequest(BaseModel):
    record_ids: List[int] = Field(..., min_length=1)


class RetryRecordsRequest(BaseModel):
    record_ids: List[int] = Field(..., min_length=1)
    risk_acknowledged: bool = False


# ==================== 辅助工厂 ====================

def _get_run_service() -> GeoEvaluationRunService:
    """获取 run_service（使用 SessionLocal 工厂，支持后台线程）"""
    return GeoEvaluationRunService(db_factory=SessionLocal)


# ==================== API 路由 ====================


@router.get("/clients/{client_id}/config")
async def get_client_config(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)
    analytics = GeoEvaluationAnalyticsService(db)
    try:
        GeoEvaluationPromptService(db).sync_smart_article_questions(client_id, current_user.id)
        config = analytics.get_client_config(client_id)
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(f"GEO evaluation schema is not ready: {exc}")
        if _is_missing_geo_evaluation_table(exc):
            db.rollback()
            _raise_schema_not_ready()
        raise
    return ApiResponse(success=True, data=config)


@router.post("/clients/{client_id}/prompt-set/generate")
async def generate_client_prompt_set(
    client_id: int,
    request: GeneratePromptSetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    service = GeoEvaluationPromptService(db)
    prompt_set = service.sync_smart_article_questions(client_id, current_user.id)
    if not prompt_set:
        result = {
            "success": False,
            "message": "暂无智能文章问题，请先在智能文章生成模块创建问题",
        }
    else:
        result = {
            "success": True,
            "prompt_set_id": prompt_set.id,
            "prompts_count": prompt_set.question_count,
            "message": f"已同步 {prompt_set.question_count} 个智能文章问题",
        }

    return ApiResponse(success=result["success"], message=result.get("message", ""), data=result)


@router.get("/clients/{client_id}/prompts")
async def get_client_prompts(
    client_id: int,
    prompt_set_id: Optional[int] = Query(None, description="问题集ID"),
    question_type: Optional[str] = Query(None, description="问题类型筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    service = GeoEvaluationPromptService(db)
    if not prompt_set_id:
        ps = service.sync_smart_article_questions(client_id, current_user.id)
        if not ps:
            return ApiResponse(success=True, data={"prompts": [], "total": 0})
        prompt_set_id = ps.id

    prompts = service.get_prompts(prompt_set_id, question_type)
    statuses = service.get_platform_question_statuses(prompt_set_id)
    items = [
        {
            "id": p.id,
            "smart_article_question_id": p.smart_article_question_id,
            "project_id": p.project_id,
            "question": p.question,
            "question_type": p.question_type,
            "intent_tags": p.intent_tags,
            "competitor_names": p.competitor_names,
            "related_project_name": p.related_project_name,
            "sort_order": p.sort_order,
            "platform_statuses": statuses.get(p.id, {}),
        }
        for p in prompts
    ]

    return ApiResponse(success=True, data={"prompts": items, "total": len(items)})


@router.post("/clients/{client_id}/baseline")
async def create_client_baseline(
    client_id: int,
    request: BaselineRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    service = _get_run_service()
    result = service.create_baseline(
        client_id=client_id,
        platforms=request.platforms,
        rounds=request.rounds,
        created_by=current_user.id,
        user_id=current_user.id,
        rebuild=request.rebuild,
        project_id=request.project_id,
        risk_acknowledged=request.risk_acknowledged,
        account_id=request.account_id,
    )

    return ApiResponse(success=result["success"], message=result.get("message", ""), data=result)


@router.post("/clients/{client_id}/baseline/complete")
async def complete_client_baseline(
    client_id: int,
    request: CompleteBaselineRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    service = _get_run_service()
    result = service.complete_baseline(
        client_id=client_id,
        platforms=request.platforms,
        created_by=current_user.id,
        user_id=current_user.id,
        account_id=request.account_id,
        project_id=request.project_id,
        risk_acknowledged=request.risk_acknowledged,
    )

    return ApiResponse(success=result["success"], message=result.get("message", ""), data=result)


@router.post("/clients/{client_id}/recheck")
async def run_client_recheck(
    client_id: int,
    request: RecheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    service = _get_run_service()
    result = service.create_recheck(
        client_id=client_id,
        platforms=request.platforms,
        rounds=request.rounds,
        created_by=current_user.id,
        user_id=current_user.id,
        project_id=request.project_id,
        risk_acknowledged=request.risk_acknowledged,
        account_id=request.account_id,
    )

    return ApiResponse(success=result["success"], message=result.get("message", ""), data=result)


@router.get("/clients/{client_id}/runs/latest")
async def get_client_latest_run(
    client_id: int,
    platform: Optional[str] = Query(None, description="平台：doubao/qianwen/deepseek"),
    prompt_set_id: Optional[int] = Query(None, description="问题集ID"),
    phase: Optional[str] = Query(None, description="阶段：baseline/ongoing"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    service = _get_run_service()
    result = service.get_latest_run_status(
        client_id=client_id,
        platform=platform,
        prompt_set_id=prompt_set_id,
        phase=phase,
    )
    if result and result.get("status") in {"running", "manual_required"}:
        latest_run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == result["id"]).first()
        if latest_run:
            now = datetime.now(latest_run.heartbeat_at.tzinfo) if latest_run.heartbeat_at else datetime.now()
            is_stale = not latest_run.heartbeat_at or (now - latest_run.heartbeat_at).total_seconds() > 120
            if is_stale:
                latest_run.status = "interrupted"
                latest_run.interruption_reason = "client_offline"
                latest_run.error_message = "本地客户端执行已中断，请点击“继续执行”后恢复"
                latest_run.claimed_device_id = None
                db.commit()
                result = service.get_run_status(latest_run.id)
    return ApiResponse(success=True, data=result)


@router.get("/clients/{client_id}/diagnosis")
async def get_client_diagnosis(
    client_id: int,
    days: int = Query(7, ge=1, le=90, description="current 统计窗口天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    analytics = GeoEvaluationAnalyticsService(db)
    try:
        result = analytics.get_client_diagnosis(client_id, days=days)
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(f"GEO evaluation schema is not ready: {exc}")
        if _is_missing_geo_evaluation_table(exc):
            db.rollback()
            _raise_schema_not_ready()
        raise

    return ApiResponse(success=True, data=result)


@router.get("/clients/{client_id}/records")
async def get_client_records(
    client_id: int,
    phase: Optional[str] = Query(None, description="阶段：baseline/ongoing"),
    platform: Optional[str] = Query(None, description="平台：doubao/qianwen/deepseek"),
    question_type: Optional[str] = Query(None, description="问题类型"),
    brand_mentioned: Optional[bool] = Query(None, description="品牌是否被提及"),
    own_source_cited: Optional[bool] = Query(None, description="是否引用我方来源"),
    sentiment: Optional[str] = Query(None, description="情感"),
    success: Optional[bool] = Query(None, description="是否成功"),
    limit: int = Query(20, ge=1, le=500),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)

    analytics = GeoEvaluationAnalyticsService(db)
    try:
        result = analytics.get_client_records(
            client_id=client_id,
            phase=phase,
            platform=platform,
            question_type=question_type,
            brand_mentioned=brand_mentioned,
            own_source_cited=own_source_cited,
            sentiment=sentiment,
            success=success,
            limit=limit,
            skip=skip,
        )
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(f"GEO evaluation schema is not ready: {exc}")
        if _is_missing_geo_evaluation_table(exc):
            db.rollback()
            _raise_schema_not_ready()
        raise

    return ApiResponse(success=True, data=result)


@router.post("/clients/{client_id}/records/batch-delete")
async def batch_delete_client_records(
    client_id: int,
    request: BatchDeleteRecordsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)
    try:
        deleted_count = (
            db.query(GeoEvaluationRecord)
            .filter(GeoEvaluationRecord.client_id == client_id, GeoEvaluationRecord.id.in_(request.record_ids))
            .delete(synchronize_session=False)
        )
        db.commit()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(f"GEO evaluation schema is not ready: {exc}")
        db.rollback()
        if _is_missing_geo_evaluation_table(exc):
            _raise_schema_not_ready()
        raise
    except Exception:
        db.rollback()
        raise

    return ApiResponse(success=True, message=f"已删除 {deleted_count} 条证据明细", data={"deleted_records": deleted_count})


@router.post("/clients/{client_id}/records/retry")
async def retry_client_records(
    client_id: int,
    request: RetryRecordsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)
    service = _get_run_service()
    result = service.retry_failed_records(
        client_id=client_id,
        project_id=None,
        record_ids=request.record_ids,
        created_by=current_user.id,
        user_id=current_user.id,
        risk_acknowledged=request.risk_acknowledged,
    )
    return ApiResponse(success=result["success"], message=result.get("message", ""), data=result)


@router.delete("/clients/{client_id}/records")
async def clear_client_records(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_client_owner(db, client_id, current_user)
    try:
        record_count = (
            db.query(GeoEvaluationRecord)
            .filter(GeoEvaluationRecord.client_id == client_id)
            .delete(synchronize_session=False)
        )
        run_count = (
            db.query(GeoEvaluationRun)
            .filter(GeoEvaluationRun.client_id == client_id)
            .delete(synchronize_session=False)
        )
        db.commit()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(f"GEO evaluation schema is not ready: {exc}")
        db.rollback()
        if _is_missing_geo_evaluation_table(exc):
            _raise_schema_not_ready()
        raise
    except Exception:
        db.rollback()
        raise

    return ApiResponse(
        success=True,
        message=f"已清空 {record_count} 条证据明细和 {run_count} 个测评任务",
        data={"deleted_records": record_count, "deleted_runs": run_count},
    )


@router.get("/projects/{project_id}/config")
async def get_config(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取项目测评配置（问题集状态 + 平台基线覆盖）"""
    project = _require_project_owner(db, project_id, current_user)
    return await get_client_config(_require_project_client(project), db, current_user)


@router.post("/projects/{project_id}/prompt-set/generate")
async def generate_prompt_set(
    project_id: int,
    request: GeneratePromptSetRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """生成测评问题集"""
    project = _require_project_owner(db, project_id, current_user)
    request.project_id = project_id
    return await generate_client_prompt_set(_require_project_client(project), request, db, current_user)


@router.get("/projects/{project_id}/prompts")
async def get_prompts(
    project_id: int,
    prompt_set_id: Optional[int] = Query(None, description="问题集ID"),
    question_type: Optional[str] = Query(None, description="问题类型筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取测评问题列表"""
    project = _require_project_owner(db, project_id, current_user)
    return await get_client_prompts(_require_project_client(project), prompt_set_id, question_type, db, current_user)


@router.post("/projects/{project_id}/baseline")
async def create_baseline(
    project_id: int,
    request: BaselineRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """建立使用前基线（后台执行，立即返回 run_id）"""
    project = _require_project_owner(db, project_id, current_user)
    request.project_id = project_id

    service = _get_run_service()
    result = service.create_baseline(
        client_id=_require_project_client(project),
        project_id=project_id,
        platforms=request.platforms,
        rounds=request.rounds,
        created_by=current_user.id,
        user_id=current_user.id,
        rebuild=request.rebuild,
        account_id=request.account_id,
    )

    return ApiResponse(
        success=result["success"],
        message=result.get("message", ""),
        data=result,
    )


@router.post("/projects/{project_id}/baseline/complete")
async def complete_baseline(
    project_id: int,
    request: CompleteBaselineRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """补齐新平台基线（只检测缺失 baseline 的平台，不删已有）"""
    project = _require_project_owner(db, project_id, current_user)
    request.project_id = project_id

    service = _get_run_service()
    result = service.complete_baseline(
        client_id=_require_project_client(project),
        project_id=project_id,
        platforms=request.platforms,
        created_by=current_user.id,
        user_id=current_user.id,
    )

    return ApiResponse(
        success=result["success"],
        message=result.get("message", ""),
        data=result,
    )


@router.post("/projects/{project_id}/recheck")
async def run_recheck(
    project_id: int,
    request: RecheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """执行使用后复测（后台执行，立即返回 run_id）"""
    project = _require_project_owner(db, project_id, current_user)
    request.project_id = project_id

    service = _get_run_service()
    result = service.create_recheck(
        client_id=_require_project_client(project),
        project_id=project_id,
        platforms=request.platforms,
        rounds=request.rounds,
        created_by=current_user.id,
        user_id=current_user.id,
        account_id=request.account_id,
    )

    return ApiResponse(
        success=result["success"],
        message=result.get("message", ""),
        data=result,
    )


@router.get("/projects/{project_id}/diagnosis")
async def get_diagnosis(
    project_id: int,
    days: int = Query(7, ge=1, le=90, description="current 统计窗口天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取五指标诊断（baseline vs current 对比）"""
    project = _require_project_owner(db, project_id, current_user)
    return await get_client_diagnosis(_require_project_client(project), days, db, current_user)


@router.get("/projects/{project_id}/records")
async def get_records(
    project_id: int,
    phase: Optional[str] = Query(None, description="阶段：baseline/ongoing"),
    platform: Optional[str] = Query(None, description="平台：doubao/qianwen/deepseek"),
    question_type: Optional[str] = Query(None, description="问题类型"),
    brand_mentioned: Optional[bool] = Query(None, description="品牌是否被提及"),
    own_source_cited: Optional[bool] = Query(None, description="是否引用我方来源"),
    sentiment: Optional[str] = Query(None, description="情感"),
    success: Optional[bool] = Query(None, description="是否成功"),
    limit: int = Query(20, ge=1, le=500),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取证据明细（支持多维筛选）"""
    project = _require_project_owner(db, project_id, current_user)
    return await get_client_records(
        _require_project_client(project),
        phase,
        platform,
        question_type,
        brand_mentioned,
        own_source_cited,
        sentiment=sentiment,
        success=success,
        limit=limit,
        skip=skip,
        db=db,
        current_user=current_user,
    )


@router.get("/runs/{run_id}/status")
async def get_run_status(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取任务执行进度"""
    run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")
    if run.client_id:
        _require_client_owner(db, run.client_id, current_user)
    elif run.project_id:
        _require_project_owner(db, run.project_id, current_user)
    else:
        raise HTTPException(status_code=403, detail="任务缺少归属信息")

    if run.status in {"running", "manual_required"}:
        stale_before = datetime.now(run.heartbeat_at.tzinfo) - timedelta(seconds=120) if run.heartbeat_at else None
        if not run.heartbeat_at or run.heartbeat_at < stale_before:
            run.status = "interrupted"
            run.interruption_reason = "client_offline"
            run.error_message = "本地客户端执行已中断，请点击“继续执行”后恢复"
            run.claimed_device_id = None
            db.commit()

    service = _get_run_service()
    result = service.get_run_status(run_id)
    return ApiResponse(success=True, data=result)


@router.post("/runs/{run_id}/resume")
async def resume_interrupted_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Allow the user to resume a run stopped by the consecutive-failure circuit breaker."""
    run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")
    if run.client_id:
        _require_client_owner(db, run.client_id, current_user)
    elif run.project_id:
        _require_project_owner(db, run.project_id, current_user)
    else:
        raise HTTPException(status_code=403, detail="任务缺少归属信息")
    if run.status not in {"interrupted", "running", "manual_required"}:
        raise HTTPException(status_code=409, detail="只有已中断或失去客户端连接的任务可以继续执行")

    target_platforms = set(run.platforms or [])
    active_runs = (
        db.query(GeoEvaluationRun)
        .filter(
            GeoEvaluationRun.id != run.id,
            GeoEvaluationRun.status.in_(["pending", "running", "manual_required"]),
        )
        .all()
    )
    occupied = sorted(
        target_platforms.intersection(
            platform
            for active_run in active_runs
            for platform in (active_run.platforms or [])
        )
    )
    if occupied:
        raise HTTPException(status_code=409, detail=f"{', '.join(occupied)} 平台已有任务执行，请稍后继续")

    run.status = "pending"
    run.error_message = CLIENT_EVALUATION_PENDING_MARKER
    run.interruption_reason = None
    run.claimed_device_id = None
    run.heartbeat_at = None
    run.finished_at = None
    db.commit()
    return ApiResponse(success=True, message="任务已恢复，等待本地客户端继续执行", data={"run_id": run.id})


@router.post("/runs/{run_id}/pause")
async def pause_evaluation_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Pause an active local evaluation while preserving its saved progress."""
    run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")
    if run.client_id:
        _require_client_owner(db, run.client_id, current_user)
    elif run.project_id:
        _require_project_owner(db, run.project_id, current_user)
    else:
        raise HTTPException(status_code=403, detail="任务缺少归属信息")
    if run.status not in {"pending", "running", "manual_required"}:
        raise HTTPException(status_code=409, detail="只有等待中、执行中或人工处理中的任务可以暂停")

    run.status = "interrupted"
    run.error_message = "用户已暂停任务，可从当前进度继续执行"
    run.interruption_reason = "user_paused"
    run.claimed_device_id = None
    run.heartbeat_at = None
    run.finished_at = None
    db.commit()
    return ApiResponse(success=True, message="任务已暂停，进度已保留，平台执行名额已经释放", data={"run_id": run.id})


@router.post("/runs/{run_id}/cancel")
async def cancel_evaluation_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Cancel a pending/running/manual/interrupted evaluation and release its platform slot."""
    run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")
    if run.client_id:
        _require_client_owner(db, run.client_id, current_user)
    elif run.project_id:
        _require_project_owner(db, run.project_id, current_user)
    else:
        raise HTTPException(status_code=403, detail="任务缺少归属信息")
    if run.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="该任务已经结束")

    run.status = "cancelled"
    run.error_message = "用户已取消任务"
    run.interruption_reason = None
    run.claimed_device_id = None
    run.heartbeat_at = None
    run.finished_at = datetime.now()
    db.commit()
    return ApiResponse(success=True, message="任务已取消，平台执行名额已经释放", data={"run_id": run.id})


@router.post("/projects/{project_id}/records/batch-delete")
async def batch_delete_records(
    project_id: int,
    request: BatchDeleteRecordsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete selected GEO evaluation evidence records for the current project."""
    project = _require_project_owner(db, project_id, current_user)
    return await batch_delete_client_records(_require_project_client(project), request, db, current_user)


@router.post("/projects/{project_id}/records/retry")
async def retry_records(
    project_id: int,
    request: RetryRecordsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    project = _require_project_owner(db, project_id, current_user)
    return await retry_client_records(_require_project_client(project), request, db, current_user)


@router.delete("/projects/{project_id}/records")
async def clear_records(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """清空当前项目的 GEO 测评证据明细和任务记录。"""
    project = _require_project_owner(db, project_id, current_user)
    return await clear_client_records(_require_project_client(project), db, current_user)
