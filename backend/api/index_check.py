# -*- coding: utf-8 -*-
"""
收录检测API
写的收录检测API，简单明了！
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, field_serializer
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.index_check_service import IndexCheckService
from backend.database.models import IndexCheckRecord, Keyword, Project, User
from backend.schemas import ApiResponse
from backend.api.user import get_current_user_from_token
from loguru import logger


router = APIRouter(prefix="/api/index-check", tags=["收录检测"])


# ==================== 用户隔离辅助 ====================


def _is_admin(current_user: User) -> bool:
    return getattr(current_user, "role", None) == "admin"


def _user_project_ids(db: Session, current_user: User):
    """admin → None（不限制）；普通用户 → 其项目ID列表（可能为空）。"""
    if _is_admin(current_user):
        return None
    return [r[0] for r in db.query(Project.id).filter(Project.user_id == current_user.id).all()]


def _user_keyword_ids(db: Session, current_user: User):
    """admin → None；普通用户 → 其关键词ID列表（可能为空）。"""
    pids = _user_project_ids(db, current_user)
    if pids is None:
        return None
    if not pids:
        return []
    return [r[0] for r in db.query(Keyword.id).filter(Keyword.project_id.in_(pids)).all()]


def _require_keyword_owner(db: Session, keyword_id: int, current_user: User):
    """校验关键词所属项目的归属（admin 放行）。"""
    if _is_admin(current_user):
        return
    kw = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="关键词不存在")
    if kw.project_id:
        project = db.query(Project).filter(Project.id == kw.project_id).first()
        if project and project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="无权访问该关键词")


def _require_project_owner(db: Session, project_id: int, current_user: User) -> Project:
    """校验项目归属并返回项目（admin 放行）。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not _is_admin(current_user) and project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return project


# ==================== 请求/响应模型 ====================


class CheckRequest(BaseModel):
    """收录检测请求"""

    keyword_id: int
    company_name: str
    platforms: Optional[List[str]] = None


class BatchCheckRequest(BaseModel):
    """批量收录检测请求"""

    project_id: int
    platforms: Optional[List[str]] = None


class CheckResultResponse(BaseModel):
    """检测结果响应"""

    platform: str
    question: str
    keyword_found: bool
    company_found: bool
    success: bool


class RecordResponse(BaseModel):
    """检测记录响应"""

    id: int
    keyword_id: int
    platform: str
    question: str
    answer: Optional[str]
    keyword_found: Optional[bool]
    company_found: Optional[bool]
    check_time: str

    @field_serializer("check_time")
    def serialize_check_time(self, dt: datetime) -> str:
        return dt.isoformat() if dt else ""

    class Config:
        from_attributes = True


class HitRateResponse(BaseModel):
    """命中率响应"""

    hit_rate: float
    total: int
    keyword_found: int
    company_found: int


# ==================== 收录监控平台选择 API ====================


class PlatformSelectionRequest(BaseModel):
    """收录监控平台选择请求"""

    platforms: Optional[List[str]] = None  # null 表示默认全部已授权平台


@router.get("/projects/{project_id}/platforms")
async def get_project_platforms(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取项目收录监控平台选择

    返回 selected_platforms（null 表示默认全部已授权平台）和 baseline_platforms（基线建立时实际使用的平台）。
    """
    project = _require_project_owner(db, project_id, current_user)
    return ApiResponse(
        success=True,
        message="获取平台选择成功",
        data={
            "selected_platforms": project.selected_platforms,  # null = 默认全部
            "baseline_platforms": project.baseline_platforms,
            "has_baseline": project.baseline_at is not None,
        },
    )


@router.put("/projects/{project_id}/platforms")
async def update_project_platforms(
    project_id: int,
    request: PlatformSelectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    保存项目收录监控平台选择

    platforms = null（或不传）→ 重置为默认行为（每次检测时使用全部已授权平台）。
    platforms = ["doubao", "qianwen"] → 仅检测指定平台。
    """
    project = _require_project_owner(db, project_id, current_user)

    # 校验传入的平台 ID 是否合法
    valid_platforms = {"doubao", "qianwen", "deepseek"}
    if request.platforms is not None:
        invalid = [p for p in request.platforms if p not in valid_platforms]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的平台: {invalid}，支持的平台: {sorted(valid_platforms)}",
            )

    project.selected_platforms = request.platforms
    db.commit()

    return ApiResponse(
        success=True,
        message="平台选择已保存",
        data={"selected_platforms": project.selected_platforms},
    )


# ==================== 收录检测 API ====================


@router.post("/check", response_model=ApiResponse)
async def check_index(
    request: CheckRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    执行收录检测

    调用Playwright自动化检测AI平台收录情况。
    注意：这是一个耗时操作，建议异步执行！
    """
    # 验证关键词存在且属于当前用户
    keyword = db.query(Keyword).filter(Keyword.id == request.keyword_id).first()
    if not keyword:
        raise HTTPException(status_code=404, detail="关键词不存在")
    _require_keyword_owner(db, request.keyword_id, current_user)

    service = IndexCheckService(db)

    # 执行检测
    try:
        skipped: List[dict] = []
        results = await service.check_keyword(
            keyword_id=request.keyword_id,
            company_name=request.company_name,
            platforms=request.platforms,
            user_id=current_user.id,
            project_id=keyword.project_id,
            skipped_collector=skipped,
        )

        # 若有平台因未授权/失效被跳过，明确告知用户去绑定
        if skipped:
            names = "、".join(str(s.get("name") or s.get("platform")) for s in skipped)
            msg = f"检测完成，共{len(results)}条记录；{names} 未授权/失效，已跳过（请先在上方“AI平台授权状态”绑定）"
        else:
            msg = f"检测完成，共{len(results)}条记录"

        return ApiResponse(success=True, message=msg, data={"results": results, "skipped": skipped})
    except Exception as e:
        logger.error(f"收录检测失败: {e}")
        return ApiResponse(success=False, message=f"检测失败: {str(e)}")


@router.post("/batch/check", response_model=ApiResponse)
async def batch_check_index(
    request: BatchCheckRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    批量执行收录检测

    调用Playwright自动化检测项目下所有关键词在AI平台的收录情况。
    注意：这是一个耗时操作，建议异步执行！
    """
    # 验证项目存在且属于当前用户
    _require_project_owner(db, request.project_id, current_user)

    service = IndexCheckService(db)

    # 执行批量检测
    try:
        skipped: List[dict] = []
        results = await service.check_project_keywords(
            project_id=request.project_id,
            platforms=request.platforms,
            user_id=current_user.id,
            skipped_collector=skipped,
        )

        if skipped:
            names = "、".join(str(s.get("name") or s.get("platform")) for s in skipped)
            msg = f"批量检测完成，共{len(results)}条记录；{names} 未授权/失效，已跳过"
        else:
            msg = f"批量检测完成，共{len(results)}条记录"

        return ApiResponse(success=True, message=msg, data={"results": results, "skipped": skipped})
    except Exception as e:
        logger.error(f"批量收录检测失败: {e}")
        return ApiResponse(success=False, message=f"批量检测失败: {str(e)}")


@router.post("/projects/{project_id}/baseline", response_model=ApiResponse)
async def create_baseline(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    生成项目基线快照（接入时跑一次；重复调用=重建，会先清除旧 baseline 记录）

    对项目下所有关键词在所有已授权 AI 平台执行一次收录检测，结果标记为 check_phase=baseline，
    并写入 project.baseline_at 作为"使用前/使用后"的分界点。此后手动/定时检测均归为 ongoing，
    对比报表据此计算前后差异。前置条件：项目已有蒸馏关键词、平台已授权。
    """
    project = _require_project_owner(db, project_id, current_user)

    service = IndexCheckService(db)
    try:
        skipped: List[dict] = []

        # 基线去重：重建基线前先清除该项目旧的 baseline 记录，避免新旧快照在诊断里被混算。
        # ongoing（日常复测）历史保留不动。
        try:
            old_ids = [
                r[0]
                for r in db.query(IndexCheckRecord.id)
                .join(Keyword)
                .filter(
                    Keyword.project_id == project_id,
                    IndexCheckRecord.check_phase == "baseline",
                )
                .all()
            ]
            if old_ids:
                db.query(IndexCheckRecord).filter(IndexCheckRecord.id.in_(old_ids)).delete(synchronize_session=False)
                db.commit()
                logger.info(f"基线重建：已清除项目 {project_id} 的 {len(old_ids)} 条旧 baseline 记录")
        except Exception as clean_err:
            db.rollback()
            logger.warning(f"清除旧 baseline 记录失败（继续建立新基线）: {clean_err}")

        # 使用用户选择的平台（null → service 内部会取全部已授权平台）
        # 先记录本次实际参与检测的平台列表，存到 baseline_platforms
        platforms_to_check = project.selected_platforms

        results = await service.check_project_keywords(
            project_id=project_id,
            platforms=platforms_to_check,
            user_id=current_user.id,
            skipped_collector=skipped,
            check_phase="baseline",
        )

        # 标记基线建立时间（北京时间无时区，与 check_time 同基准，便于对比查询）
        from datetime import timezone, timedelta

        beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
        project.baseline_at = beijing_now.replace(tzinfo=None)

        # 记录本次基线实际使用了哪些平台（从 skipped 排除后的剩余平台 = 实际执行检测的平台）
        actual_platforms = [s["platform"] for s in skipped]  # skipped 的反面就是实际测了的，但更准确的方式是：
        # 从 results 中提取实际测了哪些平台（results 中有 platform 字段）
        actual_baseline_platforms = sorted(set(r.get("platform") for r in results if r.get("platform")))
        project.baseline_platforms = actual_baseline_platforms

        db.commit()

        total = len(results)
        kw_hits = sum(1 for r in results if r.get("keyword_found"))
        co_hits = sum(1 for r in results if r.get("company_found"))

        if skipped:
            names = "、".join(str(s.get("name") or s.get("platform")) for s in skipped)
            msg = f"基线快照已建立，共{total}条记录；{names} 未授权/失效，已跳过"
        else:
            msg = f"基线快照已建立，共{total}条记录"

        return ApiResponse(
            success=True,
            message=msg,
            data={
                "baseline_at": project.baseline_at.isoformat() if project.baseline_at else None,
                "baseline_platforms": project.baseline_platforms,
                "total": total,
                "keyword_found": kw_hits,
                "company_found": co_hits,
                "keyword_hit_rate": round(kw_hits / total * 100, 2) if total else 0,
                "company_hit_rate": round(co_hits / total * 100, 2) if total else 0,
                "skipped": skipped,
            },
        )
    except Exception as e:
        logger.error(f"基线快照建立失败: {e}")
        return ApiResponse(success=False, message=f"基线建立失败: {str(e)}")


@router.get("/records")
async def get_records(
    keyword_id: Optional[int] = Query(None, description="关键词ID筛选"),
    platform: Optional[str] = Query(None, description="平台筛选"),
    limit: int = Query(15, ge=1, le=500),
    skip: int = Query(0, ge=0),
    keyword_found: Optional[bool] = Query(None, description="关键词命中筛选"),
    company_found: Optional[bool] = Query(None, description="公司名命中筛选"),
    start_date: Optional[str] = Query(None, description="开始时间 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束时间 YYYY-MM-DD"),
    question: Optional[str] = Query(None, description="问题搜索"),
    project_id: Optional[int] = Query(None, description="项目ID筛选"),
    check_phase: Optional[str] = Query(None, description="检测阶段筛选：baseline/ongoing"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取检测记录（支持分页和筛选，按当前用户隔离）
    """
    try:
        # 处理日期
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        # 用户隔离：普通用户只能看到自己关键词的检测记录
        user_kw_ids = _user_keyword_ids(db, current_user)
        if user_kw_ids == []:
            # 普通用户无关键词 → 空集
            return {"total": 0, "items": [], "limit": limit, "skip": skip}
        if user_kw_ids is None:
            # admin：不限制（但若指定了 keyword_id 仍按其过滤）
            pass

        # 指定了 keyword_id 时，校验是否在用户可见范围内
        if keyword_id is not None and user_kw_ids is not None and keyword_id not in user_kw_ids:
            return {"total": 0, "items": [], "limit": limit, "skip": skip}

        query = db.query(IndexCheckRecord)
        if user_kw_ids is not None:
            query = query.filter(IndexCheckRecord.keyword_id.in_(user_kw_ids))
        if keyword_id is not None:
            query = query.filter(IndexCheckRecord.keyword_id == keyword_id)
        if platform:
            query = query.filter(IndexCheckRecord.platform == platform)
        if keyword_found is not None:
            query = query.filter(IndexCheckRecord.keyword_found == keyword_found)
        if company_found is not None:
            query = query.filter(IndexCheckRecord.company_found == company_found)
        if start_dt:
            query = query.filter(IndexCheckRecord.check_time >= start_dt)
        if end_dt:
            query = query.filter(IndexCheckRecord.check_time <= end_dt)
        if question:
            query = query.filter(IndexCheckRecord.question.contains(question))
        if project_id is not None:
            query = query.join(Keyword).filter(Keyword.project_id == project_id)
        if check_phase:
            query = query.filter(IndexCheckRecord.check_phase == check_phase)

        total = query.count()
        records = query.order_by(IndexCheckRecord.check_time.desc()).offset(skip).limit(limit).all()

        result = []
        for record in records:
            record_dict = {
                "id": record.id,
                "keyword_id": record.keyword_id,
                "platform": record.platform,
                "question": record.question,
                "answer": record.answer,
                "keyword_found": record.keyword_found,
                "company_found": record.company_found,
                "check_phase": record.check_phase or "ongoing",
                "keyword_count": record.keyword_count,
                "company_count": record.company_count,
                "company_matched": record.company_matched,
                "confidence": record.confidence,
                "check_time": record.check_time.isoformat() if record.check_time else "",
            }
            result.append(record_dict)

        return {"total": total, "items": result, "limit": limit, "skip": skip}
    except Exception as e:
        logger.error(f"获取检测记录失败: {e}")
        return {"total": 0, "items": []}


class BatchDeleteRequest(BaseModel):
    record_ids: List[int]


@router.post("/records/batch-delete", response_model=ApiResponse)
async def batch_delete_records(
    request: BatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """批量删除记录（仅删除当前用户可见的记录）"""
    user_kw_ids = _user_keyword_ids(db, current_user)
    # 仅删除属于当前用户关键词的记录；admin 不限制
    q = db.query(IndexCheckRecord).filter(IndexCheckRecord.id.in_(request.record_ids))
    if user_kw_ids is not None:
        if not user_kw_ids:
            count = 0
            return ApiResponse(success=True, message="已删除 0 条记录")
        q = q.filter(IndexCheckRecord.keyword_id.in_(user_kw_ids))
    count = q.delete(synchronize_session=False)
    db.commit()
    return ApiResponse(success=True, message=f"已删除 {count} 条记录")


@router.get("/keywords/{keyword_id}/hit-rate", response_model=HitRateResponse)
async def get_hit_rate(
    keyword_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取关键词命中率

    注意：命中率越高，SEO效果越好！
    """
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(status_code=404, detail="关键词不存在")
    _require_keyword_owner(db, keyword_id, current_user)

    service = IndexCheckService(db)
    return service.get_hit_rate(keyword_id)


@router.get("/keywords/{keyword_id}/trend")
async def get_keyword_trend(
    keyword_id: int,
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取关键词收录趋势

    返回指定天数内的关键词收录趋势数据，包括每日命中率、关键词出现率和公司出现率。
    """
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(status_code=404, detail="关键词不存在")
    _require_keyword_owner(db, keyword_id, current_user)

    service = IndexCheckService(db)
    trend_data = service.get_keyword_trend(keyword_id, days)

    return ApiResponse(success=True, message=f"获取{days}天趋势数据成功", data=trend_data)


@router.get("/trend/{keyword_id}")
async def get_keyword_trend_compat(
    keyword_id: int,
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Compatibility alias for older frontend calls."""
    return await get_keyword_trend(keyword_id, days, db, current_user)


@router.get("/projects/{project_id}/analytics")
async def get_project_analytics(
    project_id: int,
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取项目综合分析

    返回项目下所有关键词的收录分析数据，包括命中率、关键词出现率和公司出现率。
    """
    _require_project_owner(db, project_id, current_user)

    service = IndexCheckService(db)
    analytics = service.get_project_analytics(project_id, days)

    return ApiResponse(success=True, message="获取项目分析数据成功", data=analytics)


@router.get("/platforms/performance")
async def get_platform_performance(
    project_id: Optional[int] = Query(None, description="项目ID，可选"),
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取平台表现分析

    返回各AI平台的收录表现数据，包括命中率、成功率等指标。
    """
    # 数据隔离：若指定项目，校验归属；普通用户未指定项目时仅统计自己的项目数据
    if project_id is not None:
        _require_project_owner(db, project_id, current_user)
        service = IndexCheckService(db)
        performance = service.get_platform_performance(project_id, days)
        return ApiResponse(success=True, message="获取平台表现数据成功", data=performance)

    # 未指定项目：admin 看全部；普通用户只能看自己的项目（聚合）
    if _is_admin(current_user):
        service = IndexCheckService(db)
        performance = service.get_platform_performance(None, days)
        return ApiResponse(success=True, message="获取平台表现数据成功", data=performance)

    # 普通用户：聚合其名下所有项目的平台表现
    pids = _user_project_ids(db, current_user)
    if not pids:
        return ApiResponse(success=True, message="暂无平台表现数据", data=[])
    service = IndexCheckService(db)
    performance = []
    for pid in pids:
        performance.extend(service.get_platform_performance(pid, days) or [])
    return ApiResponse(success=True, message="获取平台表现数据成功", data=performance)


@router.get("/projects/{project_id}/summary")
async def get_project_summary(
    project_id: int,
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取项目收录摘要

    返回项目的收录情况摘要，包括总检测数、平均命中率等核心指标。
    """
    _require_project_owner(db, project_id, current_user)

    service = IndexCheckService(db)
    analytics = service.get_project_analytics(project_id, days)

    # 只返回摘要信息
    return ApiResponse(
        success=True,
        message="获取项目摘要数据成功",
        data={
            "project_name": analytics["project_name"],
            "company_name": analytics["company_name"],
            "summary": analytics["summary"],
            "active_keywords": analytics["active_keywords"],
            "total_keywords": analytics["total_keywords"],
        },
    )


@router.get("/records/{record_id}", response_model=RecordResponse)
async def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取检测记录详情"""
    record = db.query(IndexCheckRecord).filter(IndexCheckRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    _require_keyword_owner(db, record.keyword_id, current_user)
    return record


@router.delete("/records/{record_id}", response_model=ApiResponse)
async def delete_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除检测记录

    注意：删除操作不可恢复！
    """
    record = db.query(IndexCheckRecord).filter(IndexCheckRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    _require_keyword_owner(db, record.keyword_id, current_user)

    db.delete(record)
    db.commit()

    logger.info(f"检测记录已删除: {record_id}")
    return ApiResponse(success=True, message="记录已删除")
