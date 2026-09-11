# -*- coding: utf-8 -*-
"""
文章管理API
写的文章API，简单明了！
"""

from typing import Optional, List
from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import GeoArticle, Keyword, SmartArticleQuestion, User, Project
from backend.schemas import ApiResponse
from backend.api.user import get_current_user_from_token
from backend.middleware.user_isolation import scoped_query, require_owner
from loguru import logger
from pydantic import BaseModel


# 为 GeoArticle 重新定义响应模型
class GeoArticleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    keyword_id: int
    project_id: int | None
    title: str | None
    content: str
    quality_score: int | None
    ai_score: int | None
    readability_score: int | None
    quality_status: str
    platform: str | None
    account_id: int | None
    publish_status: str
    publish_time: str | None
    scheduled_at: str | None
    target_platforms: list | None
    publish_strategy: str
    retry_count: int
    error_msg: str | None
    publish_logs: str | None
    platform_url: str | None
    index_status: str
    last_check_time: str | None
    index_details: str | None
    source: str | None
    generation_batch_id: int | None
    created_at: str
    updated_at: str


# 创建文章请求模型（只包含前端会发送的字段）
class ArticleCreateRequest(BaseModel):
    title: str | None = None
    content: str = ""
    status: int | None = None  # 0=草稿, 1=已发布
    tags: str | None = None
    category: str | None = None
    keyword_id: int | None = None
    project_id: int | None = None


# 更新文章请求模型
class ArticleUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    status: int | None = None
    tags: str | None = None
    category: str | None = None


# 批量删除文章请求模型
class ArticleBatchDeleteRequest(BaseModel):
    article_ids: List[int]


class GeoArticleListResponse(BaseModel):
    total: int
    items: list[GeoArticleResponse]


def _convert_article_to_dict(article: GeoArticle) -> dict:
    """将GeoArticle模型转换为字典，处理datetime和target_platforms类型转换，并处理NULL值"""
    # 处理target_platforms字段
    target_platforms = []
    if article.target_platforms is not None:
        if isinstance(article.target_platforms, str):
            # 如果是字符串，尝试解析为JSON
            try:
                target_platforms = json.loads(article.target_platforms)
            except Exception:
                # 解析失败，检查是否是单个平台名
                target_platforms = [article.target_platforms] if article.target_platforms else []
        elif isinstance(article.target_platforms, list):
            target_platforms = article.target_platforms

    # 处理datetime字段
    def dt_to_str(dt):
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.isoformat()
        return str(dt)

    # 处理可能为NULL的字段，提供默认值
    return {
        "id": article.id,
        "keyword_id": article.keyword_id,
        "project_id": article.project_id,
        "title": article.title or "",
        "content": article.content or "",
        "quality_score": article.quality_score,
        "ai_score": article.ai_score,
        "readability_score": article.readability_score,
        "quality_status": article.quality_status or "pending",
        "platform": article.platform,
        "account_id": article.account_id,
        "publish_status": article.publish_status or "draft",
        "publish_time": dt_to_str(article.publish_time),
        "scheduled_at": dt_to_str(article.scheduled_at),
        "target_platforms": target_platforms,
        "publish_strategy": article.publish_strategy or "draft",
        "retry_count": article.retry_count or 0,
        "error_msg": article.error_msg,
        "publish_logs": article.publish_logs,
        "platform_url": article.platform_url,
        "index_status": article.index_status or "uncheck",
        "last_check_time": dt_to_str(article.last_check_time),
        "index_details": article.index_details,
        "source": getattr(article, "source", None) or "manual",
        "generation_batch_id": getattr(article, "generation_batch_id", None),
        "created_at": dt_to_str(article.created_at) or "",
        "updated_at": dt_to_str(article.updated_at) or "",
    }


router = APIRouter(prefix="/api/articles", tags=["文章管理"])


def _get_owned_article(db: Session, article_id: int, current_user: User) -> GeoArticle:
    """获取文章并校验归属（不存在→404；不属于当前用户→403；admin 放行）。"""
    article = db.query(GeoArticle).filter(GeoArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    require_owner(article, current_user, name="文章")
    return article


def _get_article_keyword(db: Session, request: ArticleCreateRequest, current_user: User) -> Keyword:
    """Resolve a keyword that belongs to one of the current user's projects."""
    owned_keywords = (
        db.query(Keyword).join(Project, Project.id == Keyword.project_id).filter(Project.user_id == current_user.id)
    )

    if request.keyword_id is not None:
        keyword = owned_keywords.filter(Keyword.id == request.keyword_id).first()
        if keyword is None:
            raise HTTPException(status_code=404, detail="关键词不存在或无权访问")
        if request.project_id is not None and keyword.project_id != request.project_id:
            raise HTTPException(status_code=400, detail="关键词与项目不匹配")
        return keyword

    if request.project_id is not None:
        owned_keywords = owned_keywords.filter(Keyword.project_id == request.project_id)

    keyword = (
        owned_keywords.filter(Keyword.status == "active").order_by(Keyword.created_at.desc(), Keyword.id.desc()).first()
    )
    if keyword is None:
        raise HTTPException(status_code=400, detail="请先创建可用关键词，或在请求中传入 keyword_id")
    return keyword


@router.get("", response_model=GeoArticleListResponse)
async def get_articles(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    publish_status: Optional[str] = Query(None, description="发布状态筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    source: Optional[str] = Query(None, description="来源筛选：manual/agent_excel"),
    generation_batch_id: Optional[int] = Query(None, description="生成批次ID筛选"),
    project_id: Optional[int] = Query(None, description="项目ID筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取文章列表（按当前用户隔离：普通用户只看自己的文章，admin 看全部）
    支持按来源/生成批次/项目筛选（Excel 批量生成联动）。
    """
    # 按当前用户隔离：普通用户只匹配 user_id == current_user.id
    query = scoped_query(db, GeoArticle, current_user)

    if publish_status is not None:
        query = query.filter(GeoArticle.publish_status == publish_status)

    if keyword:
        query = query.filter((GeoArticle.title.contains(keyword)) | (GeoArticle.content.contains(keyword)))

    if source:
        query = query.filter(GeoArticle.source == source)

    if generation_batch_id is not None:
        query = query.filter(GeoArticle.generation_batch_id == generation_batch_id)

    if project_id is not None:
        query = query.filter(GeoArticle.project_id == project_id)

    # 统计总数
    total = query.count()

    # 分页查询
    articles = query.order_by(GeoArticle.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    # 批量获取项目名称（避免 N+1 查询）
    project_ids = set(a.project_id for a in articles if a.project_id)
    project_map = {}
    if project_ids:
        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        project_map = {p.id: p.name for p in projects}

    # 手动转换数据类型
    article_dicts = [_convert_article_to_dict(article) for article in articles]

    # 为每篇文章添加前端期望的数字status字段和项目名称
    for article_dict in article_dicts:
        article_dict["status"] = 1 if article_dict.get("publish_status") == "published" else 0
        pid = article_dict.get("project_id")
        article_dict["project_name"] = project_map.get(pid) if pid else None

    return GeoArticleListResponse(total=total, items=article_dicts)


@router.get("/{article_id}", response_model=ApiResponse)
async def get_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取文章详情（校验归属：不属于当前用户→403；admin 放行）"""
    article = _get_owned_article(db, article_id, current_user)

    # 手动转换数据类型，并包装在ApiResponse中
    article_dict = _convert_article_to_dict(article)

    # 添加前端期望的数字status字段
    article_dict["status"] = 1 if article_dict.get("publish_status") == "published" else 0

    return ApiResponse(success=True, message="获取成功", data=article_dict)


@router.post("", response_model=ApiResponse)
async def create_article(
    request: ArticleCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    创建新文章（归属当前用户）
    """
    keyword = _get_article_keyword(db, request, current_user)

    try:
        # 根据status确定publish_status
        publish_status = "draft"
        if request.status == 1:
            publish_status = "published"
        elif request.status == 0:
            publish_status = "draft"

        # 创建新文章（归属当前用户，确保数据隔离）
        new_article = GeoArticle(
            keyword_id=keyword.id,
            project_id=keyword.project_id,
            user_id=current_user.id,  # 数据隔离归属
            title=request.title or "未命名文章",
            content=request.content or "",
            quality_status="pending",
            publish_status=publish_status,
            publish_strategy="draft",
            target_platforms=[],
            retry_count=0,
            index_status="uncheck",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        db.add(new_article)
        db.commit()
        db.refresh(new_article)

        logger.info(f"文章已创建: {new_article.id}, 标题: {new_article.title}, 状态: {publish_status}")

        # 转换数据并添加前端期望的status字段
        article_dict = _convert_article_to_dict(new_article)
        article_dict["status"] = 1 if publish_status == "published" else 0

        return ApiResponse(success=True, message="文章创建成功", data=article_dict)
    except Exception as e:
        db.rollback()
        logger.error(f"创建文章失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{article_id}", response_model=ApiResponse)
async def update_article_api(
    article_id: int,
    request: ArticleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    更新文章（校验归属：不属于当前用户→403；admin 放行）
    """
    article = _get_owned_article(db, article_id, current_user)

    try:
        # 更新字段
        if request.title is not None:
            article.title = request.title
        if request.content is not None:
            article.content = request.content

        # 根据status更新publish_status
        if request.status is not None:
            if request.status == 1:
                article.publish_status = "published"
            elif request.status == 0:
                article.publish_status = "draft"

        article.updated_at = datetime.now()

        db.commit()
        db.refresh(article)

        logger.info(f"文章已更新: {article_id}, 标题: {article.title}")

        # 转换数据并添加前端期望的status字段
        article_dict = _convert_article_to_dict(article)
        article_dict["status"] = 1 if article.publish_status == "published" else 0

        return ApiResponse(success=True, message="文章更新成功", data=article_dict)
    except Exception as e:
        db.rollback()
        logger.error(f"更新文章失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{article_id}", response_model=ApiResponse)
async def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除文章（校验归属：不属于当前用户→403；admin 放行）

    注意：删除会级联删除相关的发布记录！
    """
    article = _get_owned_article(db, article_id, current_user)

    # 删除文章时，同步重置问题池中指向该文章的问题标记。
    # 否则因外键 ON DELETE SET NULL，article_id 会变空，但 has_article 仍为 True，
    # 导致这些问题在界面上继续显示「已生成文章」而实际文章已不存在。
    linked_questions = db.query(SmartArticleQuestion).filter(SmartArticleQuestion.article_id == article_id).all()
    for q in linked_questions:
        q.has_article = False
        q.article_id = None
        q.article_generation_status = "idle"

    db.delete(article)
    db.commit()

    logger.info(f"文章已删除: {article_id}，同步重置 {len(linked_questions)} 条关联问题的标记")
    return ApiResponse(success=True, message="文章已删除")


@router.post("/batch-delete", response_model=ApiResponse)
async def batch_delete_articles(
    request: ArticleBatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    批量删除文章（按当前用户隔离校验归属：不属于当前用户→403；admin 放行）

    注意：删除会级联删除相关的发布记录，并同步重置问题池中的关联标记！
    """
    if not request.article_ids:
        return ApiResponse(success=True, message="没有选择要删除的文章")

    # 查询当前用户有权限删除的文章（自动按 scoped_query 隔离）
    query = scoped_query(db, GeoArticle, current_user).filter(GeoArticle.id.in_(request.article_ids))
    articles = query.all()

    if not articles:
        raise HTTPException(status_code=404, detail="未找到可删除的文章")

    deleted_ids = []
    for article in articles:
        article_id = article.id
        # 删除文章时，同步重置问题池中指向该文章的问题标记
        linked_questions = db.query(SmartArticleQuestion).filter(SmartArticleQuestion.article_id == article_id).all()
        for q in linked_questions:
            q.has_article = False
            q.article_id = None
            q.article_generation_status = "idle"

        db.delete(article)
        deleted_ids.append(article_id)

    db.commit()

    # 提示用户实际删除了多少篇，以及是否有无权限的文章被忽略
    skipped_count = len(request.article_ids) - len(deleted_ids)
    message = f"成功删除 {len(deleted_ids)} 篇文章"
    if skipped_count > 0:
        message += f"，{skipped_count} 篇无权限删除已跳过"

    logger.info(f"批量删除文章: {deleted_ids}，同步重置关联问题标记")
    return ApiResponse(success=True, message=message, data={"deleted_ids": deleted_ids})
