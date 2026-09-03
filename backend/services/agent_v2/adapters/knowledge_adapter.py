# -*- coding: utf-8 -*-
"""KnowledgeAdapter - 知识库适配器。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import KnowledgeCategory


class KnowledgeAdapter:
    """知识库适配器 - 文件上传/分类/就绪检查。"""

    def __init__(self, db: Session):
        self.db = db

    def list_categories(self, user, client_id: int | None = None) -> list[dict[str, Any]]:
        """列出知识库分类。"""
        from backend.middleware.user_isolation import scoped_query
        query = scoped_query(self.db, KnowledgeCategory, user)
        if client_id:
            query = query.filter(KnowledgeCategory.client_id == client_id)
        rows = query.order_by(KnowledgeCategory.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "client_id": r.client_id,
                "document_count": getattr(r, "document_count", 0),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def create_category(self, user, name: str, client_id: int | None = None) -> dict[str, Any]:
        """创建知识库分类。"""
        category = KnowledgeCategory(
            user_id=user.id,
            name=name,
            client_id=client_id,
        )
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return {
            "id": category.id,
            "name": category.name,
            "client_id": category.client_id,
        }

    def check_knowledge_ready(self, user, project_id: int) -> dict[str, Any]:
        """检查项目是否有可用的知识库资料。"""
        from backend.database.models import Project
        from backend.middleware.user_isolation import scoped_query
        project = scoped_query(self.db, Project, user).filter(Project.id == project_id).first()
        if not project:
            return {"ready": False, "reason": "项目不存在"}
        # 检查项目关联的客户是否有知识库分类
        if not project.client_id:
            return {"ready": False, "reason": "项目未关联客户"}
        categories = self.db.query(KnowledgeCategory).filter(
            KnowledgeCategory.client_id == project.client_id
        ).count()
        if categories == 0:
            return {"ready": False, "reason": "客户尚未上传知识库资料"}
        return {"ready": True, "reason": "知识库就绪"}
