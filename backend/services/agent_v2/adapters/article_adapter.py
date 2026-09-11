# -*- coding: utf-8 -*-
"""ArticleAdapter - 文章管理适配器（查询/删除/批次状态）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.models import GeoArticle, SmartArticleBatch
from backend.middleware.user_isolation import scoped_query
from backend.services.smart_article.service import SmartArticleService


class ArticleAdapter:
    """文章管理适配器 - 给 Agent V2 工具层调用。"""

    def __init__(self, db: Session):
        self.db = db

    def list_articles(
        self,
        user,
        project_id: int | None = None,
        keyword: str | None = None,
        publish_status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """列出文章。"""
        query = scoped_query(self.db, GeoArticle, user)
        if project_id:
            query = query.filter(GeoArticle.project_id == project_id)
        if keyword:
            query = query.filter(GeoArticle.title.ilike(f"%{keyword}%"))
        if publish_status is not None:
            if publish_status == "published":
                query = query.filter(GeoArticle.publish_status == "published")
            else:
                query = query.filter(or_(GeoArticle.publish_status != "published", GeoArticle.publish_status.is_(None)))
        total = query.count()
        rows = query.order_by(GeoArticle.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {"total": total, "items": [self._to_dict(r) for r in rows]}

    def get_article(self, user, article_id: int) -> dict[str, Any] | None:
        row = scoped_query(self.db, GeoArticle, user).filter(GeoArticle.id == article_id).first()
        return self._to_dict(row, include_content=True) if row else None

    def delete_article(self, user, article_id: int) -> bool:
        row = scoped_query(self.db, GeoArticle, user).filter(GeoArticle.id == article_id).first()
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def get_article_batch_status(self, user, batch_id: int) -> dict[str, Any]:
        """查询文章批次生成状态。"""
        service = SmartArticleService(self.db)
        return service.get_batch(batch_id, user)

    def retry_article_job(self, user, job_id: int) -> dict[str, Any]:
        """重试单篇文章生成。"""
        service = SmartArticleService(self.db)
        return service.retry_job(job_id, user)

    @staticmethod
    def _to_dict(article: GeoArticle, include_content: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": article.id,
            "title": article.title,
            "project_id": getattr(article, "project_id", None),
            "keyword_id": getattr(article, "keyword_id", None),
            "status": getattr(article, "status", 0),
            "created_at": article.created_at.isoformat() if article.created_at else None,
        }
        if include_content:
            data["content"] = getattr(article, "content", "")
            data["html_content"] = getattr(article, "html_content", "")
        return data
