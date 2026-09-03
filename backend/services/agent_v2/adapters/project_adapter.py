# -*- coding: utf-8 -*-
"""ProjectAdapter - 项目管理适配器。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from loguru import logger

from backend.database.models import Project
from backend.middleware.user_isolation import scoped_query


class ProjectAdapter:
    """项目管理适配器。"""

    def __init__(self, db: Session):
        self.db = db

    def list_projects(self, user, client_id: int | None = None, keyword: str | None = None,
                      page: int = 1, limit: int = 20) -> dict[str, Any]:
        query = scoped_query(self.db, Project, user)
        if client_id:
            query = query.filter(Project.client_id == client_id)
        if keyword:
            query = query.filter(Project.name.ilike(f"%{keyword}%"))
        total = query.count()
        rows = query.order_by(Project.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {"total": total, "items": [self._to_dict(r) for r in rows]}

    def get_project(self, user, project_id: int) -> dict[str, Any] | None:
        row = scoped_query(self.db, Project, user).filter(Project.id == project_id).first()
        return self._to_dict(row) if row else None

    def create_project(self, user, data: dict[str, Any]) -> dict[str, Any]:
        # 唯一性查重：同用户、同客户下若已存在同名项目，直接返回已存在项目，
        # 避免 LLM 重试时重复 insert 同名项目。
        name = data.get("name") or "未命名项目"
        client_id = data.get("client_id")
        existing = (
            scoped_query(self.db, Project, user)
            .filter(Project.client_id == client_id)
            .filter(Project.name.ilike(name))
            .first()
        )
        if existing:
            logger.info(f"[create_project] 已存在同名项目，直接返回: id={existing.id} name={existing.name}")
            return self._to_dict(existing)

        project = Project(
            user_id=user.id,
            client_id=client_id,
            name=name,
            company_name=data.get("company_name"),
            domain_keyword=data.get("domain_keyword"),
            description=data.get("description"),
            industry=data.get("industry"),
            status=1,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return self._to_dict(project)

    def update_project(self, user, project_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        project = scoped_query(self.db, Project, user).filter(Project.id == project_id).first()
        if not project:
            return None
        for key in ("name", "company_name", "domain_keyword", "description", "industry", "status", "client_id"):
            if key in data and data[key] is not None:
                setattr(project, key, data[key])
        self.db.commit()
        self.db.refresh(project)
        return self._to_dict(project)

    def delete_project(self, user, project_id: int) -> bool:
        project = scoped_query(self.db, Project, user).filter(Project.id == project_id).first()
        if not project:
            return False
        self.db.delete(project)
        self.db.commit()
        return True

    def find_by_name(self, user, name: str) -> list[dict[str, Any]]:
        """按项目名模糊查找（多候选时用）。"""
        rows = scoped_query(self.db, Project, user).filter(
            Project.name.ilike(f"%{name}%")
        ).limit(10).all()
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(project: Project) -> dict[str, Any]:
        return {
            "id": project.id,
            "client_id": project.client_id,
            "name": project.name,
            "company_name": project.company_name,
            "domain_keyword": project.domain_keyword,
            "description": project.description,
            "industry": project.industry,
            "status": project.status,
            "created_at": project.created_at.isoformat() if project.created_at else None,
        }
