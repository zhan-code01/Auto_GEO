# -*- coding: utf-8 -*-
"""Electron/local-client GEO evaluation task protocol."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.api.client_device import get_owned_device, is_device_online
from backend.api.user import get_current_user_from_token
from backend.database import SessionLocal, get_db
from backend.database.models import Account, Client, GeoEvaluationRecord, GeoEvaluationRun, GeoPrompt, Project, User
from backend.services.crypto import decrypt_storage_state, encrypt_cookies, encrypt_storage_state
from backend.services.geo_citation import VALID_CITATION_STATUSES
from backend.schemas import ApiResponse
from backend.services.geo_evaluation_run_service import (
    EVALUATION_QUESTION_LIMIT,
    GeoResponseJudgeService,
    _get_client_domains,
    _get_project_domains,
    _judge_model_label,
)
from backend.services.session_manager import secure_session_manager


router = APIRouter(prefix="/api/client/geo-evaluation/runs", tags=["本地客户端GEO测评"])

CLAIM_TTL_MINUTES = 30
HEARTBEAT_STALE_SECONDS = 120
CLIENT_PENDING_MARKER = "local_client_pending"


class ClaimRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


class HeartbeatRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


class RecordResultRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    prompt_id: int
    platform: str
    round_no: int = Field(1, ge=1)
    question: str
    success: bool
    answer: Optional[str] = None
    citations: Optional[List[Any]] = None
    citation_status: Optional[str] = None
    error_msg: Optional[str] = None
    context_cleaned: bool = True
    capture_method: Optional[str] = None
    attempt_count: int = Field(1, ge=1, le=20)


class FinishRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    status: str = "completed"
    error_msg: Optional[str] = None


class ManualRequiredRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    platform: str
    message: str
    error_code: Optional[str] = None
    risk_type: Optional[str] = None


class ManualResolvedRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    platform: str


class InterruptRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    message: str
    reason: str = "client_error"


class ResumeRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)


class SessionStateRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    platform: str
    storage_state: Dict[str, Any]


def _now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def _serialize_run(run: GeoEvaluationRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "client_id": run.client_id,
        "project_id": run.project_id,
        "prompt_set_id": run.prompt_set_id,
        "phase": run.phase,
        "platforms": run.platforms or [],
        "rounds": run.rounds or 1,
        "status": run.status,
        "total_planned": run.total_planned,
        "total_completed": run.total_completed,
        "total_failed": run.total_failed,
        "current_platform": run.current_platform,
        "current_round": run.current_round,
        "current_progress": run.current_progress,
        "claimed_device_id": run.claimed_device_id,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "interruption_reason": run.interruption_reason,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error_message": None if run.error_message == CLIENT_PENDING_MARKER else run.error_message,
    }


def _owned_run(db: Session, run_id: int, current_user: User) -> GeoEvaluationRun:
    run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="GEO测评任务不存在")
    if run.created_by != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问该GEO测评任务")
    return run


def _ensure_device(db: Session, device_id: str, current_user: User):
    device = get_owned_device(db, device_id, current_user)
    if not is_device_online(device):
        raise HTTPException(status_code=400, detail="本地客户端设备不在线")
    return device


def _ensure_claim(run: GeoEvaluationRun, device_id: str) -> None:
    if run.claimed_device_id and run.claimed_device_id != device_id:
        raise HTTPException(status_code=409, detail="任务已由其他本地客户端领取")


def _company_payload(db: Session, run: GeoEvaluationRun) -> Dict[str, Any]:
    client = db.query(Client).filter(Client.id == run.client_id).first() if run.client_id else None
    project = db.query(Project).filter(Project.id == run.project_id).first() if run.project_id else None
    company_name = ""
    official_domains: List[str] = []
    if client:
        company_name = client.company_name or client.name or ""
        official_domains = _get_client_domains(db, client.id)
    elif project:
        company_name = project.company_name or project.name or ""
        official_domains = _get_project_domains(project)
    return {"company_name": company_name, "official_domains": official_domains}


def _reclaim_stale_runs(db: Session, current_user: User) -> None:
    stale_before = _now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    stale_runs = (
        db.query(GeoEvaluationRun)
        .filter(
            GeoEvaluationRun.created_by == current_user.id,
            GeoEvaluationRun.status.in_(["running", "manual_required"]),
            or_(GeoEvaluationRun.heartbeat_at.is_(None), GeoEvaluationRun.heartbeat_at < stale_before),
        )
        .all()
    )
    for run in stale_runs:
        run.status = "interrupted"
        run.interruption_reason = "client_offline"
        run.error_message = "本地客户端心跳中断，请点击“继续执行”后恢复"
        run.claimed_device_id = None
    if stale_runs:
        db.commit()
        for run in stale_runs:
            logger.warning(
                f"[GeoEval] 心跳超时回收任务: run_id={run.id} "
                f"last_heartbeat={run.heartbeat_at} user_id={current_user.id}"
            )


@router.get("/poll", response_model=ApiResponse)
async def poll_runs(
    device_id: str = Query(..., min_length=1, max_length=64),
    platform: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, device_id, current_user)
    _reclaim_stale_runs(db, current_user)

    # 同时返回 pending 和当前设备已 claim 的 running run，
    # 让客户端有机会重启崩溃的 worker
    query = db.query(GeoEvaluationRun).filter(
        GeoEvaluationRun.created_by == current_user.id,
        GeoEvaluationRun.status.in_(["pending", "running"]),
        or_(
            and_(
                GeoEvaluationRun.status == "pending",
                GeoEvaluationRun.error_message == CLIENT_PENDING_MARKER,
            ),
            GeoEvaluationRun.claimed_device_id == device_id,
        ),
    )
    runs = query.order_by(GeoEvaluationRun.created_at.asc(), GeoEvaluationRun.id.asc()).limit(limit * 3).all()
    items = []
    for run in runs:
        if platform and platform not in (run.platforms or []):
            continue
        items.append(_serialize_run(run))
        if len(items) >= limit:
            break
    return ApiResponse(data={"items": items})


@router.post("/{run_id}/claim", response_model=ApiResponse)
async def claim_run(
    run_id: int,
    request: ClaimRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    is_pending = run.status == "pending" and run.error_message == CLIENT_PENDING_MARKER
    if not is_pending:
        raise HTTPException(status_code=409, detail="该GEO测评任务当前不可领取")
    run.status = "running"
    run.started_at = run.started_at or _now()
    run.error_message = None
    run.interruption_reason = None
    run.claimed_device_id = request.device_id
    run.heartbeat_at = _now()
    run.current_progress = run.current_progress or 0
    db.commit()
    logger.info(
        f"[GeoEval] 任务领取: run_id={run.id} device={request.device_id} "
        f"platforms={run.platforms} user_id={current_user.id}"
    )
    return ApiResponse(
        data={
            "run": _serialize_run(run),
            "claim_expires_at": (_now() + timedelta(minutes=CLAIM_TTL_MINUTES)).isoformat(),
        }
    )


@router.get("/{run_id}/payload", response_model=ApiResponse)
async def get_payload(
    run_id: int,
    device_id: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, device_id)
    if run.status not in {"running", "manual_required"}:
        raise HTTPException(status_code=400, detail="GEO测评任务尚未领取或已经结束")
    prompt_query = db.query(GeoPrompt).filter(
        GeoPrompt.prompt_set_id == run.prompt_set_id,
        GeoPrompt.status == "active",
    )
    if run.prompt_ids:
        prompt_query = prompt_query.filter(GeoPrompt.id.in_(run.prompt_ids))
    prompt_query = prompt_query.order_by(GeoPrompt.question_type, GeoPrompt.sort_order)
    if not run.prompt_ids:
        prompt_query = prompt_query.limit(EVALUATION_QUESTION_LIMIT)
    prompts = prompt_query.all()
    prompt_items = [
        {
            "id": prompt.id,
            "question": prompt.question,
            "question_type": prompt.question_type,
            "related_project_name": prompt.related_project_name,
        }
        for prompt in prompts
    ]
    completed = (
        db.query(
            GeoEvaluationRecord.platform,
            GeoEvaluationRecord.round_no,
            GeoEvaluationRecord.prompt_id,
        )
        .filter(GeoEvaluationRecord.run_id == run.id)
        .all()
    )
    completed_keys = [
        f"{run.id}:{platform_name}:{round_no}:{prompt_id}"
        for platform_name, round_no, prompt_id in completed
        if prompt_id is not None
    ]
    platform_sessions: Dict[str, Any] = {}
    if run.account_id:
        account = (
            db.query(Account)
            .filter(
                Account.id == run.account_id,
                Account.user_id == current_user.id,
                Account.deleted_at.is_(None),
            )
            .first()
        )
        if not account or not account.storage_state:
            raise HTTPException(status_code=409, detail="任务绑定的授权账户不存在或登录状态不可用")
        state = decrypt_storage_state(account.storage_state)
        if state:
            platform_sessions[account.platform] = state
    if not platform_sessions:
        for platform_name in run.platforms or []:
            state = await secure_session_manager.load_session(
                user_id=current_user.id,
                project_id=None,
                platform=platform_name,
                validate=False,
            )
            if state:
                platform_sessions[platform_name] = state

    logger.info(
        f"[GeoEval] 下发任务负载: run_id={run.id} device={device_id} "
        f"prompts={len(prompt_items)} platforms={run.platforms} "
        f"sessions={list(platform_sessions.keys())} completed_keys={len(completed_keys)}"
    )
    return ApiResponse(
        data={
            "run": _serialize_run(run),
            "prompts": prompt_items,
            "completed_keys": completed_keys,
            "platform_sessions": platform_sessions,
            "account_id": run.account_id,
            "timing": {
                "questionDelayMinMs": 10000,
                "questionDelayMaxMs": 15000,
                "retryDelayMinMs": 10000,
                "retryDelayMaxMs": 15000,
                "maxAttempts": 3,
            },
            **_company_payload(db, run),
        }
    )


@router.post("/{run_id}/heartbeat", response_model=ApiResponse)
async def heartbeat_run(
    run_id: int,
    request: HeartbeatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    if run.status == "cancelled":
        return ApiResponse(data={"run": _serialize_run(run)})
    _ensure_claim(run, request.device_id)
    if run.status in {"running", "manual_required"}:
        run.heartbeat_at = _now()
        db.commit()
    return ApiResponse(data={"run": _serialize_run(run)})


@router.post("/{run_id}/session-state", response_model=ApiResponse)
async def save_platform_session_state(
    run_id: int,
    request: SessionStateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, request.device_id)
    if request.platform not in (run.platforms or []):
        raise HTTPException(status_code=400, detail="会话平台不属于当前任务")
    saved = await secure_session_manager.save_session(
        user_id=current_user.id,
        project_id=None,
        platform=request.platform,
        storage_state=request.storage_state,
        is_new_login=True,
    )
    if not saved:
        raise HTTPException(status_code=500, detail="保存平台登录会话失败")
    if run.account_id:
        account = (
            db.query(Account)
            .filter(
                Account.id == run.account_id,
                Account.user_id == current_user.id,
                Account.platform == request.platform,
                Account.deleted_at.is_(None),
            )
            .first()
        )
        if not account:
            raise HTTPException(status_code=404, detail="任务绑定账户不存在")
        account.storage_state = encrypt_storage_state(request.storage_state)
        account.cookies = encrypt_cookies(request.storage_state.get("cookies", []))
        account.status = 1
        account.last_auth_time = _now()
        db.commit()
    return ApiResponse(message="登录会话已更新")


@router.post("/{run_id}/record-result", response_model=ApiResponse)
async def record_result(
    run_id: int,
    request: RecordResultRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, request.device_id)
    if run.status not in {"running", "manual_required"}:
        raise HTTPException(status_code=400, detail="GEO测评任务不在执行中")
    if request.platform not in (run.platforms or []):
        raise HTTPException(status_code=400, detail="提交平台不属于当前测评任务")
    if run.prompt_ids and request.prompt_id not in run.prompt_ids:
        raise HTTPException(status_code=400, detail="提交问题不属于当前测评任务")
    if request.citation_status is not None and request.citation_status not in VALID_CITATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"非法引用状态: {request.citation_status}")

    existing = (
        db.query(GeoEvaluationRecord)
        .filter(
            GeoEvaluationRecord.run_id == run.id,
            GeoEvaluationRecord.platform == request.platform,
            GeoEvaluationRecord.round_no == request.round_no,
            GeoEvaluationRecord.prompt_id == request.prompt_id,
        )
        .first()
    )
    if existing:
        # 幂等命中。若本次补传了真实引用而旧记录未带引用证据，则回填引用字段，
        # 避免重试/补传时引用证据被幂等去重丢弃；未判卷的记录重新触发判卷。
        needs_backfill = bool(request.citations) and not existing.raw_citations
        if needs_backfill:
            existing.raw_citations = request.citations
            if request.citation_status is not None:
                existing.citation_status = request.citation_status
            if request.capture_method is not None:
                existing.capture_method = request.capture_method
            db.commit()
            logger.info(
                f"[GeoEval] 幂等命中回填引用证据: run_id={run.id} record_id={existing.id} "
                f"citations={len(request.citations)} status={existing.citation_status}"
            )
        if existing.success and existing.answer and existing.evaluated_at is None:
            background_tasks.add_task(_evaluate_record, existing.id)
        return ApiResponse(data={"run": _serialize_run(run), "record_id": existing.id, "idempotent": True})

    prompt = (
        db.query(GeoPrompt)
        .filter(
            GeoPrompt.id == request.prompt_id,
            GeoPrompt.prompt_set_id == run.prompt_set_id,
        )
        .first()
    )
    if not prompt:
        raise HTTPException(status_code=400, detail="测评问题不存在或不属于当前问题集")
    record_time = _now()
    answer = request.answer or ""
    record = GeoEvaluationRecord(
        run_id=run.id,
        client_id=run.client_id,
        project_id=run.project_id,
        prompt_set_id=run.prompt_set_id,
        prompt_id=request.prompt_id,
        related_project_name=prompt.related_project_name,
        platform=request.platform,
        phase=run.phase,
        round_no=request.round_no,
        question=request.question,
        answer=answer,
        raw_citations=request.citations,
        citation_status=request.citation_status,
        capture_method=request.capture_method,
        context_cleaned=request.context_cleaned,
        success=bool(request.success and answer),
        error_message=None if request.success else request.error_msg,
        schema_version="1.0.0",
        asked_at=record_time,
        created_at=record_time,
    )
    db.add(record)
    if record.success:
        run.total_completed = (run.total_completed or 0) + 1
    else:
        run.total_failed = (run.total_failed or 0) + 1
    run.current_platform = request.platform
    run.current_round = request.round_no
    run.current_progress = (run.total_completed or 0) + (run.total_failed or 0)
    run.error_message = request.error_msg if not record.success else None
    run.heartbeat_at = _now()
    db.commit()
    if record.success:
        background_tasks.add_task(_evaluate_record, record.id)
    logger.info(
        f"[GeoEval] 记录答题结果: run_id={run.id} record_id={record.id} "
        f"platform={request.platform} round={request.round_no} prompt_id={request.prompt_id} "
        f"success={record.success} answer_len={len(answer)} attempts={request.attempt_count}"
    )
    return ApiResponse(data={"run": _serialize_run(run), "record_id": record.id, "idempotent": False})


async def _evaluate_record(record_id: int) -> None:
    """Evaluate one saved answer without holding a DB connection during the LLM request.

    The judge request may take tens of seconds.  Keeping the SQLAlchemy session
    checked out across that await can exhaust the pool when several answers are
    evaluated concurrently, which in turn prevents local workers from fetching
    their task payloads.
    """
    read_db = SessionLocal()
    try:
        record = read_db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.id == record_id).first()
        if not record or not record.success or not record.answer or record.evaluated_at:
            return
        run = read_db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == record.run_id).first()
        if not run:
            return
        company = _company_payload(read_db, run)
        prompt = read_db.query(GeoPrompt).filter(GeoPrompt.id == record.prompt_id).first()
        evaluation_input = {
            "company_name": company["company_name"],
            "brand_aliases": [company["company_name"]],
            "official_domains": list(company["official_domains"]),
            "competitors": [],
            "question": record.question,
            "question_type": prompt.question_type if prompt else None,
            "answer": record.answer,
            "citations": record.raw_citations,
            "citation_status": record.citation_status,
        }
    finally:
        # Release the connection before waiting for the external judge API.
        read_db.close()

    result = await GeoResponseJudgeService().evaluate(**evaluation_input)
    logger.info(
        f"[GeoEval] 判定完成: record_id={record_id} "
        f"brand_mentioned={result.get('brand_mentioned')} "
        f"is_recommended={result.get('is_recommended')} visibility={result.get('visibility_score')}"
    )

    write_db = SessionLocal()
    try:
        record = write_db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.id == record_id).first()
        if not record or record.evaluated_at:
            return
        record.brand_mentioned = result["brand_mentioned"]
        record.matched_names = result["matched_names"]
        record.is_recommended = result["is_recommended"]
        record.recommendation_rank = result["recommendation_rank"]
        record.ranking_score = result["ranking_score"]
        record.citation_supported = result["citation_supported"]
        record.own_source_cited = result["own_source_cited"]
        record.cited_urls = result["cited_urls"]
        record.cited_domains = result["cited_domains"]
        record.sentiment = result["sentiment"]
        record.sentiment_score = result["sentiment_score"]
        record.visibility_score = result["visibility_score"]
        record.evidence = result["evidence"]
        record.judge_model = _judge_model_label()
        record.judge_raw_output = result
        record.evaluated_at = _now()
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        write_db.close()


@router.post("/{run_id}/manual-required", response_model=ApiResponse)
async def mark_manual_required(
    run_id: int,
    request: ManualRequiredRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, request.device_id)
    run.status = "manual_required"
    run.current_platform = request.platform
    run.heartbeat_at = _now()
    details = request.message
    if request.error_code or request.risk_type:
        details = f"[{request.error_code or request.risk_type}] {details}"
    run.error_message = details[:500]
    if request.error_code in {"LOGIN_REQUIRED", "AUTH_REQUIRED"} and run.account_id:
        account = (
            db.query(Account)
            .filter(
                Account.id == run.account_id,
                Account.user_id == current_user.id,
            )
            .first()
        )
        if account:
            account.status = 0
            account.health_score = 0
    db.commit()
    logger.warning(
        f"[GeoEval] 需要人工介入: run_id={run.id} platform={request.platform} "
        f"code={request.error_code} risk={request.risk_type} message={request.message[:200]}"
    )
    return ApiResponse(data={"run": _serialize_run(run)})


@router.post("/{run_id}/manual-resolved", response_model=ApiResponse)
async def mark_manual_resolved(
    run_id: int,
    request: ManualResolvedRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, request.device_id)
    if run.status != "manual_required":
        raise HTTPException(status_code=409, detail="任务当前不在人工处理状态")
    run.status = "running"
    run.current_platform = request.platform
    run.error_message = None
    run.heartbeat_at = _now()
    db.commit()
    logger.info(f"[GeoEval] 人工处理完成，任务继续: run_id={run.id} platform={request.platform}")
    return ApiResponse(data={"run": _serialize_run(run)})


@router.post("/{run_id}/interrupt", response_model=ApiResponse)
async def interrupt_run(
    run_id: int,
    request: InterruptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, request.device_id)
    run.status = "interrupted"
    run.interruption_reason = request.reason
    run.error_message = request.message[:500]
    run.claimed_device_id = None
    run.heartbeat_at = _now()
    db.commit()
    logger.warning(
        f"[GeoEval] 任务中断: run_id={run.id} reason={request.reason} "
        f"message={request.message[:200]} device={request.device_id}"
    )
    return ApiResponse(data={"run": _serialize_run(run)})


@router.post("/{run_id}/resume", response_model=ApiResponse)
async def resume_run(
    run_id: int,
    request: ResumeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    if run.status != "interrupted":
        raise HTTPException(status_code=409, detail="只有中断任务可以继续")
    run.status = "pending"
    run.error_message = CLIENT_PENDING_MARKER
    run.interruption_reason = None
    run.claimed_device_id = None
    run.heartbeat_at = None
    run.finished_at = None
    db.commit()
    logger.info(f"[GeoEval] 任务恢复排队: run_id={run.id} device={request.device_id}")
    return ApiResponse(data={"run": _serialize_run(run)})


@router.post("/{run_id}/finish", response_model=ApiResponse)
async def finish_run(
    run_id: int,
    request: FinishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _ensure_device(db, request.device_id, current_user)
    run = _owned_run(db, run_id, current_user)
    _ensure_claim(run, request.device_id)
    if request.status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="不支持的结束状态")
    run.status = request.status
    run.finished_at = _now()
    run.claimed_device_id = None
    run.heartbeat_at = _now()
    if request.error_msg:
        run.error_message = request.error_msg[:500]
    if request.status == "completed" and (run.total_completed or 0) == 0 and (run.total_failed or 0) > 0:
        run.status = "failed"
        run.error_message = run.error_message or "所有AI平台测评均失败"
    db.commit()
    duration_s = ""
    if run.started_at and run.finished_at:
        duration_s = f" duration={(run.finished_at - run.started_at).total_seconds():.0f}s"
    logger.info(
        f"[GeoEval] 任务结束: run_id={run.id} status={run.status} "
        f"completed={run.total_completed} failed={run.total_failed}{duration_s}"
    )
    return ApiResponse(data={"run": _serialize_run(run)})
