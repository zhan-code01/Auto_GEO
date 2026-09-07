from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.user import get_current_user_from_token
from backend.database import get_db
from backend.database.models import Project, User
from backend.middleware.user_isolation import scoped_query
from backend.schemas import ApiResponse
from backend.services.smart_article.question_pool_service import (
    SmartArticleQuestionPoolService,
    run_smart_question_batch,
)
from backend.services.smart_article.service import (
    SmartArticleService,
    run_smart_article_batch,
    process_smart_article_job,
)


router = APIRouter(prefix="/api/smart-articles", tags=["智能文章生成"])


class SmartArticleGenerateRequest(BaseModel):
    project_id: int
    article_count: int = Field(1, ge=1)
    question: Optional[str] = None


class SmartArticleQuestionBatchRequest(BaseModel):
    project_id: int
    question_count: int = Field(10, ge=1, le=30)
    custom_question: Optional[str] = None


class SmartArticleQuestionDeleteRequest(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=100)


class SmartArticleSelectionBatchRequest(BaseModel):
    project_id: int
    question_ids: list[int] = Field(min_length=1)


@router.get("/projects")
async def list_projects(
    client_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    query = scoped_query(db, Project, current_user).filter(
        Project.status == 1,
        Project.client_id.is_not(None),
    )
    if client_id is not None:
        query = query.filter(Project.client_id == client_id)
    projects = query.order_by(Project.created_at.desc()).all()
    return [
        {
            "id": project.id,
            "client_id": project.client_id,
            "name": project.name,
            "company_name": (
                project.client.company_name or project.client.name if project.client else project.company_name
            ),
            "domain_keyword": project.domain_keyword,
            "industry": project.industry,
        }
        for project in projects
    ]


def _require_linked_project(db: Session, current_user: User, project_id: int) -> Project:
    project = scoped_query(db, Project, current_user).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    if project.status != 1:
        raise HTTPException(status_code=400, detail="项目已停用，无法生成智能文章")
    if not project.client_id:
        raise HTTPException(status_code=400, detail="项目尚未关联公司，请先在项目管理中关联公司")
    return project


@router.post("/generate", response_model=ApiResponse)
async def generate(
    request: SmartArticleGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        _require_linked_project(db, current_user, request.project_id)
        batch = SmartArticleService(db).create_batch(
            current_user, request.project_id, request.article_count, request.question
        )
        background_tasks.add_task(run_smart_article_batch, batch.id)
        logger.info(
            f"[SmartArticle] 文章生成批次已提交: batch_id={batch.id} project_id={request.project_id} "
            f"count={request.article_count} user={current_user.username}"
        )
        return ApiResponse(
            success=True,
            message="智能文章生成任务已提交",
            data={
                "batch_id": batch.id,
                "status": batch.status,
                "requested_count": batch.requested_count,
            },
        )
    except ValueError as exc:
        logger.warning(f"[SmartArticle] 创建文章批次被拒绝: project_id={request.project_id} error={exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[SmartArticle] 创建智能文章批次失败: project_id={request.project_id} error={exc}")
        raise HTTPException(status_code=500, detail=f"创建智能文章批次失败：{exc}") from exc


@router.post("/question-batches", response_model=ApiResponse)
async def generate_questions(
    request: SmartArticleQuestionBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        _require_linked_project(db, current_user, request.project_id)
        batch = SmartArticleQuestionPoolService(db).create_batch(
            current_user, request.project_id, request.question_count, request.custom_question
        )
        background_tasks.add_task(run_smart_question_batch, batch.id)
        logger.info(
            f"[SmartArticle] 问题生成批次已提交: batch_id={batch.id} project_id={request.project_id} "
            f"count={request.question_count} user={current_user.username}"
        )
        return ApiResponse(
            success=True, message="问题生成任务已提交", data={"batch_id": batch.id, "status": batch.status}
        )
    except ValueError as exc:
        logger.warning(f"[SmartArticle] 创建问题批次被拒绝: project_id={request.project_id} error={exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[SmartArticle] 创建问题生成批次失败: project_id={request.project_id} error={exc}")
        raise HTTPException(status_code=500, detail=f"创建问题生成批次失败：{exc}") from exc


@router.get("/question-batches/{batch_id}", response_model=ApiResponse)
async def get_question_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        data = SmartArticleQuestionPoolService(db).get_batch(batch_id, current_user)
        return ApiResponse(success=True, data=data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/questions", response_model=ApiResponse)
async def list_questions(
    project_id: int = Query(...),
    has_article: Optional[bool] = Query(None),
    generation_batch_id: Optional[int] = Query(None, description="按问题批次过滤（Agent V2 用）"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    _require_linked_project(db, current_user, project_id)
    data = SmartArticleQuestionPoolService(db).list_questions(
        current_user, project_id, has_article, page, limit, generation_batch_id
    )
    return ApiResponse(success=True, data=data)


@router.post("/questions/batch-delete", response_model=ApiResponse)
async def delete_questions(
    request: SmartArticleQuestionDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    count = SmartArticleQuestionPoolService(db).soft_delete(current_user, request.question_ids)
    return ApiResponse(success=True, message=f"已删除{count}个问题", data={"deleted_count": count})


@router.post("/article-batches", response_model=ApiResponse)
async def generate_selected_articles(
    request: SmartArticleSelectionBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        _require_linked_project(db, current_user, request.project_id)
        batch, skipped = SmartArticleService(db).create_selection_batch(
            current_user, request.project_id, request.question_ids
        )
        background_tasks.add_task(run_smart_article_batch, batch.id)
        logger.info(
            f"[SmartArticle] 选题文章批次已提交: batch_id={batch.id} project_id={request.project_id} "
            f"questions={len(request.question_ids)} skipped={len(skipped)} user={current_user.username}"
        )
        return ApiResponse(
            success=True,
            message="文章生成任务已提交",
            data={
                "batch_id": batch.id,
                "accepted_question_ids": [item for item in request.question_ids if item not in skipped],
                "skipped_question_ids": skipped,
            },
        )
    except ValueError as exc:
        logger.warning(f"[SmartArticle] 创建选题批次被拒绝: project_id={request.project_id} error={exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[SmartArticle] 创建文章生成批次失败: project_id={request.project_id} error={exc}")
        raise HTTPException(status_code=500, detail=f"创建文章生成批次失败：{exc}") from exc


@router.get("/batches/{batch_id}", response_model=ApiResponse)
async def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        data = SmartArticleService(db).get_batch(batch_id, current_user)
        return ApiResponse(success=True, data=data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/articles", response_model=ApiResponse)
async def list_articles(
    project_id: Optional[int] = Query(None),
    publish_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    data = SmartArticleService(db).list_articles(current_user, project_id, publish_status, page, limit)
    return ApiResponse(success=True, data=data)


@router.post("/jobs/{job_id}/retry", response_model=ApiResponse)
async def retry_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        job_id = SmartArticleService(db).retry_job(job_id, current_user)
        background_tasks.add_task(process_smart_article_job, job_id)
        return ApiResponse(success=True, message="失败任务已重新提交", data={"job_id": job_id})
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
