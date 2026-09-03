from __future__ import annotations

from sqlalchemy.orm import Session

from backend.database.models import Client, Project
from backend.middleware.user_isolation import scoped_query
from .region_context import build_region_context
from .schemas import ProjectContext


class SmartArticleContextError(ValueError):
    pass


def build_project_context(db: Session, project_id: int, current_user) -> ProjectContext:
    project = scoped_query(db, Project, current_user).filter(Project.id == project_id, Project.status == 1).first()
    if not project:
        raise SmartArticleContextError("项目不存在或无权访问")

    client = db.query(Client).filter(Client.id == project.client_id).first() if project.client_id else None
    company_name = (project.company_name or (client.company_name if client else None) or (client.name if client else None) or "").strip()
    project_name = (project.name or "").strip()
    domain_keyword = (project.domain_keyword or "").strip()
    if not project_name:
        raise SmartArticleContextError("项目名称不能为空")
    if not company_name:
        raise SmartArticleContextError("公司名称不能为空，请先完善项目或客户资料")
    if not domain_keyword:
        raise SmartArticleContextError("领域关键词不能为空，请先完善项目资料")

    industry = (project.industry or (client.industry if client else None) or "").strip()
    location = (client.location if client else "") or ""
    location, allowed_regions, blocked_regions = build_region_context(location)
    return ProjectContext(
        project_id=project.id,
        user_id=project.user_id or getattr(current_user, "id", 0),
        company_name=company_name,
        project_name=project_name,
        domain_keyword=domain_keyword,
        industry=industry,
        location=location,
        project_description=(project.description or "").strip(),
        client_description=(client.description if client else "") or "",
        website=((getattr(client, "website", "") if client else "") or "").strip(),
        allowed_regions=allowed_regions,
        blocked_regions=blocked_regions,
        client=client,
        project=project,
    )
