# -*- coding: utf-8 -*-
"""
GEO文章管理 API - 工业加固版
处理文章生成、质检、列表、收录检测触发等
"""

import json
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import get_db, SessionLocal
from backend.services.geo_article_service import GeoArticleService
from backend.services.project_question_service import ProjectQuestionService
from backend.database.models import GeoArticle, Project, Keyword, User
from backend.schemas import ApiResponse
from backend.api.user import get_current_user_from_token
from backend.middleware.user_isolation import scoped_query, require_owner
from loguru import logger

router = APIRouter(prefix="/api/geo", tags=["GEO文章"])


# ==================== 辅助函数 ====================


def _convert_article_to_dict(article: GeoArticle) -> dict:
    """
    将GeoArticle模型转换为字典，处理target_platforms和datetime类型转换
    修复Pydantic验证错误：target_platforms字符串需要转换为列表
    """
    # 处理target_platforms字段
    target_platforms = None
    if article.target_platforms is not None:
        if isinstance(article.target_platforms, str):
            try:
                target_platforms = json.loads(article.target_platforms)
            except Exception:
                target_platforms = [article.target_platforms] if article.target_platforms else []
        elif isinstance(article.target_platforms, list):
            target_platforms = article.target_platforms
        else:
            target_platforms = []

    # 处理datetime字段
    def dt_to_str(dt):
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.isoformat()
        return str(dt)

    return {
        "id": article.id,
        "keyword_id": article.keyword_id,
        "project_id": article.project_id,
        "title": article.title,
        "content": article.content,
        "quality_status": article.quality_status,
        "publish_status": article.publish_status,
        "index_status": article.index_status,
        "platform": article.platform,
        "account_id": article.account_id,
        "target_platforms": target_platforms,
        "publish_strategy": article.publish_strategy,
        "quality_score": article.quality_score,
        "ai_score": article.ai_score,
        "readability_score": article.readability_score,
        "retry_count": article.retry_count,
        "error_msg": article.error_msg,
        "publish_logs": article.publish_logs,
        "platform_url": article.platform_url,
        "index_details": article.index_details,
        "publish_time": dt_to_str(article.publish_time),
        "scheduled_at": dt_to_str(article.scheduled_at),
        "last_check_time": dt_to_str(article.last_check_time),
        "created_at": dt_to_str(article.created_at),
        "updated_at": dt_to_str(article.updated_at),
    }


# ==================== 请求/响应模型 ====================


class GenerateArticleRequest(BaseModel):
    """文章生成请求模型"""

    keyword_id: int
    company_name: str
    # 发布策略相关（新增）
    target_platforms: Optional[List[str]] = Field(None, description="预设目标平台列表")
    publish_strategy: Optional[str] = Field(
        "draft", description="发布策略：draft=仅生成草稿 immediate=生成后立即发布 scheduled=定时发布"
    )
    scheduled_at: Optional[str] = Field(None, description="定时发布时间（ISO格式）")


class GenerateProjectArticlesRequest(BaseModel):
    """项目级批量生成请求模型"""

    project_id: int
    target_platforms: Optional[List[str]] = Field(None, description="预设目标平台列表")
    publish_strategy: Optional[str] = Field(
        "draft", description="发布策略：draft=仅生成草稿 immediate=生成后立即发布 scheduled=定时发布"
    )
    scheduled_at: Optional[str] = Field(None, description="定时发布时间（ISO格式）")


class UpdateArticleRequest(BaseModel):
    """手动编辑文章请求模型"""

    title: Optional[str] = Field(None, description="文章标题（为空则不更新标题）")
    content: Optional[str] = Field(None, description="文章正文（为空则不更新正文）")


class ArticleResponse(BaseModel):
    """
    🌟 核心模型：解决前端列表显示的所有字段需求
    """

    id: int
    keyword_id: int
    title: Optional[str] = None
    content: Optional[str] = None

    # 状态字段
    quality_status: Optional[str] = "pending"
    publish_status: Optional[str] = "draft"
    index_status: Optional[str] = "uncheck"
    platform: Optional[str] = None
    account_id: Optional[int] = None

    # 发布策略字段（新增）
    target_platforms: Optional[List[str]] = None
    publish_strategy: Optional[str] = "draft"

    # 评分字段
    quality_score: Optional[int] = None
    ai_score: Optional[int] = None
    readability_score: Optional[int] = None

    # 记录与日志
    retry_count: Optional[int] = 0
    error_msg: Optional[str] = None
    publish_logs: Optional[str] = None
    platform_url: Optional[str] = None  # 🌟 发布成功后的真实链接
    index_details: Optional[str] = None

    # 时间戳
    publish_time: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    last_check_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # 兼容 SQLAlchemy 对象
    model_config = ConfigDict(from_attributes=True)


class ProjectResponse(BaseModel):
    id: int
    name: str
    client_id: Optional[int] = None  # 公司ID，用于 GEO 测评
    company_name: Optional[str] = None  # 数据库允许为NULL
    model_config = ConfigDict(from_attributes=True)


# ==================== 异步辅助逻辑 ====================


async def run_generate_task(
    keyword_id: int,
    company_name: str,
    target_platforms: Optional[List[str]] = None,
    publish_strategy: str = "draft",
    scheduled_at: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """后台执行生成任务的闭包"""
    db = SessionLocal()
    try:
        service = GeoArticleService(db)
        await service.generate(
            keyword_id,
            company_name,
            target_platforms=target_platforms,
            publish_strategy=publish_strategy,
            scheduled_at=scheduled_at,
            user_id=user_id,
        )
    except Exception as e:
        logger.error(f"❌ 后台生成任务失败: {str(e)}")
    finally:
        db.close()


async def run_project_generate_queue(
    project_id: int,
    keyword_ids: List[int],
    company_name: str,
    target_platforms: Optional[List[str]] = None,
    publish_strategy: str = "draft",
    scheduled_at: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """后台串行队列：逐个搜索问题生成文章，避免一次性并发造成卡顿。"""
    db = SessionLocal()
    try:
        service = GeoArticleService(db)
        for keyword_id in keyword_ids:
            try:
                await service.generate(
                    keyword_id,
                    company_name,
                    target_platforms=target_platforms,
                    publish_strategy=publish_strategy,
                    scheduled_at=scheduled_at,
                    user_id=user_id,
                    source="project_bulk",
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"项目批量生成单条失败: project_id={project_id}, keyword_id={keyword_id}, error={e}")
    except Exception as e:
        logger.error(f"项目批量生成队列失败: project_id={project_id}, error={str(e)}")
    finally:
        db.close()


# ==================== 接口实现 ====================


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取所有活跃项目列表（按当前用户隔离）"""
    return scoped_query(db, Project, current_user).filter(Project.status == 1).all()


@router.post("/generate", response_model=ApiResponse)
async def generate_article(
    request: GenerateArticleRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_from_token),
):
    """
    提交文章生成任务
    使用 BackgroundTasks 实现非阻塞响应

    支持发布策略：
    - draft: 仅生成草稿
    - immediate: 生成后立即发布
    - scheduled: 定时发布
    """
    # 在请求线程内捕获当前用户，传入后台任务（BackgroundTask 执行时 contextvar 已失效）
    background_tasks.add_task(
        run_generate_task,
        request.keyword_id,
        request.company_name,
        request.target_platforms,
        request.publish_strategy,
        request.scheduled_at,
        current_user.id,
    )
    return ApiResponse(success=True, message="生成任务已提交，请在列表查看进度")


@router.post("/generate/project", response_model=ApiResponse)
async def generate_project_articles(
    request: GenerateProjectArticlesRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    为指定项目的全部未生成搜索问题创建文章生成队列。

    后台按 keyword_id 顺序逐条执行，降低卡顿与并发压力。
    """
    project = (
        scoped_query(db, Project, current_user).filter(Project.id == request.project_id, Project.status == 1).first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")

    questions = ProjectQuestionService(db).get_unused_questions(project.id)
    keyword_ids = [q.id for q in questions if q.id is not None]
    if not keyword_ids:
        return ApiResponse(
            success=True,
            message="当前项目没有待生成文章的搜索问题",
            data={"queued_count": 0, "project_id": project.id},
        )

    background_tasks.add_task(
        run_project_generate_queue,
        project.id,
        keyword_ids,
        project.company_name or "默认公司",
        request.target_platforms,
        request.publish_strategy or "draft",
        request.scheduled_at,
        current_user.id,
    )
    return ApiResponse(
        success=True,
        message=f"已加入队列，将按顺序生成 {len(keyword_ids)} 篇文章",
        data={"queued_count": len(keyword_ids), "project_id": project.id},
    )


@router.get("/articles")
async def list_articles(
    project_id: Optional[int] = Query(None, description="项目ID筛选"),
    limit: int = Query(100),
    publish_status: Optional[str] = Query(
        None, description="发布状态过滤: generating/completed/scheduled/publishing/published/failed"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取文章列表（按创建时间倒序）

    支持按 publish_status 和 project_id 过滤。

    状态说明：
    - generating: AI 生成中
    - completed: 已生成/待分发（生成完成，等待用户配置发布）
    - scheduled: 已配置定时发布
    - publishing: 发布中
    - published: 已发布
    - failed: 失败

    批量发布页面应使用 publish_status=completed 获取待配置发布的文章。
    """
    query = scoped_query(db, GeoArticle, current_user).order_by(desc(GeoArticle.created_at))

    # 如果指定了项目，进行过滤
    if project_id:
        query = query.join(Keyword, GeoArticle.keyword_id == Keyword.id).filter(
            (GeoArticle.project_id == project_id) | (Keyword.project_id == project_id)
        )

    # 如果指定了状态，进行过滤
    if publish_status:
        # 🌟 支持数组过滤：如果 publish_status 是列表，使用 in_ 方法
        if isinstance(publish_status, list):
            query = query.filter(GeoArticle.publish_status.in_(publish_status))
        else:
            query = query.filter(GeoArticle.publish_status == publish_status)

    # 应用分页限制
    if limit:
        query = query.limit(limit)

    articles = query.all()
    # 手动转换数据类型，修复Pydantic验证错误
    return [_convert_article_to_dict(article) for article in articles]


def _get_owned_article(db: Session, article_id: int, current_user: User) -> GeoArticle:
    """获取文章并校验归属（不存在→404；不属于当前用户→403；admin 放行）。"""
    article = db.query(GeoArticle).filter(GeoArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    require_owner(article, current_user, name="文章")
    return article


@router.get("/articles/{article_id}", response_model=ApiResponse)
async def get_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取单篇 GEO 文章详情。"""
    article = _get_owned_article(db, article_id, current_user)
    return ApiResponse(success=True, message="获取成功", data=_convert_article_to_dict(article))


@router.post("/articles/{article_id}/check-quality", response_model=ApiResponse)
async def check_quality(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    🌟 [修复] 手动触发文章质检评分
    """
    _get_owned_article(db, article_id, current_user)
    service = GeoArticleService(db)
    try:
        result = await service.check_quality(article_id)
        if result.get("success"):
            return ApiResponse(success=True, message="质检完成", data=result)
        return ApiResponse(success=False, message=result.get("message", "质检失败"))
    except Exception as e:
        logger.error(f"质检异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/articles/{article_id}/check-index", response_model=ApiResponse)
async def manual_check_index(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """手动触发单篇文章的收录监测"""
    _get_owned_article(db, article_id, current_user)
    service = GeoArticleService(db)
    try:
        result = await service.check_article_index(article_id)
        if result.get("status") == "error":
            return ApiResponse(success=False, message=result.get("message"))
        return ApiResponse(success=True, message=f"检测完成，当前状态：{result.get('index_status')}")
    except Exception as e:
        logger.error(f"收录检测异常: {str(e)}")
        return ApiResponse(success=False, message="检测服务暂时不可用")


@router.delete("/articles/{article_id}", response_model=ApiResponse)
async def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """删除文章记录"""
    article = _get_owned_article(db, article_id, current_user)

    try:
        db.delete(article)
        db.commit()
        return ApiResponse(success=True, message="文章已成功删除")
    except Exception as e:
        db.rollback()
        return ApiResponse(success=False, message=f"删除失败: {str(e)}")


@router.put("/articles/{article_id}", response_model=ApiResponse)
async def update_article(
    article_id: int,
    payload: UpdateArticleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """手动编辑文章标题/正文"""
    article = _get_owned_article(db, article_id, current_user)

    changed = False
    # 标题：非空时更新
    if payload.title is not None and payload.title.strip():
        article.title = payload.title.strip()
        changed = True
    # 正文：非空时更新，并把过期的质检分清空、状态置为待检
    if payload.content is not None and payload.content.strip():
        article.content = payload.content
        article.quality_score = None
        article.ai_score = None
        article.readability_score = None
        article.quality_status = "pending"
        changed = True

    if not changed:
        return ApiResponse(success=False, message="没有需要更新的内容")

    try:
        db.commit()
        db.refresh(article)
        return ApiResponse(
            success=True,
            message="文章已更新",
            data=_convert_article_to_dict(article),
        )
    except Exception as e:
        db.rollback()
        logger.error(f"更新文章失败: {str(e)}")
        return ApiResponse(success=False, message=f"更新失败: {str(e)}")
