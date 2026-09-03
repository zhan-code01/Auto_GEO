# -*- coding: utf-8 -*-
"""数据报表 API —— 精简版。

仅保留首页 Dashboard 仍在使用的接口：
- GET /api/reports/overview       数据总览
- GET /api/reports/article-stats  GeoArticle 文章统计
- GET /api/reports/stats          数据总览卡片（今日发布等）

已下线的「数据报表」页面独占接口（收录诊断/平台对比/排行榜/手动检测等）
随页面一并移除：其诊断能力已由「收录监控」页的 geo-evaluation 体系取代。
"""
from typing import List, Optional
from datetime import timedelta
from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.database import get_db
from backend.database.models import Project, Keyword, IndexCheckRecord, GeoArticle, User
from backend.api.user import get_current_user_from_token
from backend.middleware.user_isolation import scoped_query
from backend.utils.time_utils import beijing_today_start

router = APIRouter(prefix="/api/reports", tags=["数据报表"])


# ==================== 用户隔离辅助 ====================


def _is_admin(current_user: User) -> bool:
    return getattr(current_user, "role", None) == "admin"


def _user_project_ids(db: Session, current_user: User) -> Optional[List[int]]:
    """
    返回当前用户拥有的项目ID列表；admin 返回 None（表示不限制，可看全部）。
    普通用户若无项目则返回空列表 []。
    """
    if _is_admin(current_user):
        return None
    return [r[0] for r in db.query(Project.id).filter(Project.user_id == current_user.id).all()]


def _scope_keywords(db: Session, current_user: User):
    """返回当前用户可见的 Keyword 查询（通过项目归属隔离）。"""
    query = db.query(Keyword)
    pids = _user_project_ids(db, current_user)
    if pids is None:
        return query
    if not pids:
        return query.filter(Keyword.id == -1)  # 无项目 → 空集
    return query.filter(Keyword.project_id.in_(pids))


def _scope_records(db: Session, current_user: User):
    """返回当前用户可见的 IndexCheckRecord 查询（通过关键词→项目归属隔离）。"""
    query = db.query(IndexCheckRecord)
    pids = _user_project_ids(db, current_user)
    if pids is None:
        return query
    if not pids:
        return query.filter(IndexCheckRecord.id == -1)  # 空集
    return query.join(Keyword).filter(Keyword.project_id.in_(pids))


class SummaryStats(BaseModel):
    total_articles: int
    common_articles: int
    geo_articles: int
    publish_success_rate: float
    publish_success_count: int
    publish_total_count: int
    keyword_hit_rate: float
    keyword_hit_count: int
    keyword_check_count: int
    company_hit_rate: float
    company_hit_count: int
    company_check_count: int


class ArticleStatsResponse(BaseModel):
    """GeoArticle 文章统计响应"""

    total: int
    generating: int
    completed: int
    published: int
    failed: int
    ready_to_publish: int  # 已完成生成或已排期，等待发布的文章数


# ==================== 报表API ====================


@router.get("/article-stats", response_model=ArticleStatsResponse)
async def get_article_stats(
    project_id: Optional[int] = Query(None, description="项目ID筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取 GeoArticle 文章统计信息（按当前用户隔离）
    """
    # 构建基础查询 —— 按用户隔离
    query = scoped_query(db, GeoArticle, current_user)

    # 如果指定了项目，则通过关键词关联筛选
    if project_id:
        query = query.join(Keyword).filter(Keyword.project_id == project_id)

    # 统计各状态数量（同样按用户隔离）
    status_query = scoped_query(db, GeoArticle, current_user)
    if project_id:
        status_query = status_query.join(Keyword).filter(Keyword.project_id == project_id)

    stats = (
        status_query.with_entities(GeoArticle.publish_status, func.count(GeoArticle.id).label("count"))
        .filter(GeoArticle.publish_status.in_(["generating", "completed", "scheduled", "publishing", "published", "failed"]))
        .group_by(GeoArticle.publish_status)
        .all()
    )

    # 将查询结果转换为字典
    stats_dict = {row.publish_status: row.count for row in stats}

    # 统计总数（包含其他状态如 draft）
    total = query.count()

    # 等待发布的文章：已生成、已定时、发布中
    ready_to_publish = (
        stats_dict.get("completed", 0)
        + stats_dict.get("scheduled", 0)
        + stats_dict.get("publishing", 0)
    )

    logger.debug(
        f"[Reports] 文章统计: total={total} published={stats_dict.get('published', 0)} "
        f"failed={stats_dict.get('failed', 0)} ready={ready_to_publish} "
        f"project_id={project_id} user={current_user.username}"
    )

    return ArticleStatsResponse(
        total=total,
        generating=stats_dict.get("generating", 0),
        completed=stats_dict.get("completed", 0),
        published=stats_dict.get("published", 0),
        failed=stats_dict.get("failed", 0),
        ready_to_publish=ready_to_publish,
    )


@router.get("/stats", response_model=SummaryStats)
async def get_summary_stats(
    project_id: Optional[int] = Query(None),
    days: int = Query(7),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取数据总览卡片数据（按当前用户隔离）"""
    # 统计窗口按「自然日」计算（含今天），而非滚动 24h：
    #   days=1 → 今天 00:00 起（对应首页「今日发布」）；
    #   days=7 → 6 天前 00:00 起（近 7 个自然日）。
    # 统一用北京时间（UTC+8）的「今日 00:00」作为基准，避免服务器 TZ 不同导致窗口错位。
    start_date = beijing_today_start() - timedelta(days=days - 1)

    # 1. 文章生成数（仅统计当前用户的 GeoArticle）
    geo_query = scoped_query(db, GeoArticle, current_user).filter(GeoArticle.created_at >= start_date)

    if project_id:
        geo_query = geo_query.join(Keyword).filter(Keyword.project_id == project_id)

    total_articles = geo_query.count()

    # 2. 发布成功率（按实际发布时间 publish_time 统计，而非文章创建时间 created_at）
    pub_query = scoped_query(db, GeoArticle, current_user).filter(GeoArticle.publish_time >= start_date)
    if project_id:
        pub_query = pub_query.join(Keyword).filter(Keyword.project_id == project_id)

    geo_pub_published = pub_query.filter(GeoArticle.publish_status == "published").count()
    geo_pub_total = pub_query.filter(GeoArticle.publish_status.in_(["published", "failed"])).count()
    pub_rate = round((geo_pub_published / geo_pub_total * 100), 2) if geo_pub_total > 0 else 0

    # 3. 关键词/公司名命中率（仅当前用户可见的检测记录）
    # 显式 JOIN Keyword 避免 admin 用户时 _scope_records 未 JOIN 导致的笛卡尔积
    idx_query = (
        db.query(IndexCheckRecord)
        .join(Keyword, IndexCheckRecord.keyword_id == Keyword.id)
        .filter(IndexCheckRecord.check_time >= start_date)
    )
    pids = _user_project_ids(db, current_user)
    if pids is not None and pids:
        idx_query = idx_query.filter(Keyword.project_id.in_(pids))
    if project_id:
        idx_query = idx_query.filter(Keyword.project_id == project_id)

    idx_total = idx_query.count()
    kw_hit_count = idx_query.filter(IndexCheckRecord.keyword_found == True).count()
    co_hit_count = idx_query.filter(IndexCheckRecord.company_found == True).count()

    kw_rate = round((kw_hit_count / idx_total * 100), 2) if idx_total > 0 else 0
    co_rate = round((co_hit_count / idx_total * 100), 2) if idx_total > 0 else 0

    logger.debug(
        f"[Reports] 总览统计: articles={total_articles} pub_rate={pub_rate}% "
        f"kw_hit={kw_hit_count}/{idx_total} co_hit={co_hit_count}/{idx_total} "
        f"days={days} project_id={project_id} user={current_user.username}"
    )

    return SummaryStats(
        total_articles=total_articles,
        common_articles=0,  # 仪表盘只统计GeoArticle
        geo_articles=total_articles,
        publish_success_rate=pub_rate,
        publish_success_count=geo_pub_published,
        publish_total_count=geo_pub_total,
        keyword_hit_rate=kw_rate,
        keyword_hit_count=kw_hit_count,
        keyword_check_count=idx_total,
        company_hit_rate=co_rate,
        company_hit_count=co_hit_count,
        company_check_count=idx_total,
    )


@router.get("/overview")
async def get_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取数据总览（按当前用户隔离）"""
    # 统计当前用户可见的关键词数量
    total_keywords = _scope_keywords(db, current_user).count()

    # 统计当前用户可见的检测记录
    record_query = _scope_records(db, current_user)
    total_records = record_query.count()
    keyword_found = record_query.filter(IndexCheckRecord.keyword_found == True).count()
    company_found = record_query.filter(IndexCheckRecord.company_found == True).count()

    # 计算总体命中率
    overall_hit_rate = 0
    if total_records > 0:
        overall_hit_rate = round(((keyword_found + company_found) / (total_records * 2)) * 100, 2)

    logger.debug(
        f"[Reports] 数据总览: keywords={total_keywords} records={total_records} "
        f"hit_rate={overall_hit_rate}% user={current_user.username}"
    )

    return {
        "total_keywords": total_keywords,
        "keyword_found": keyword_found,
        "company_found": company_found,
        "overall_hit_rate": overall_hit_rate,
    }
