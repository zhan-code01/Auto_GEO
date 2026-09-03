# -*- coding: utf-8 -*-
"""
客户管理API
管理客户信息，一个客户可以有多个项目
按用户隔离：普通用户只能看到自己的客户，管理员可看全部。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from loguru import logger

from backend.database import get_db
from backend.database.models import (
    Client, Project, User,
    Keyword, GeoArticle, QuestionVariant, IndexCheckRecord,
    KeywordUsageRecord,
    KnowledgeCategory, Knowledge,
)
from backend.schemas import ApiResponse
from backend.api.user import get_current_user_from_token
from backend.middleware.user_isolation import scoped_query, require_owner
from backend.services.geo_knowledge_service import CLIENT_UPLOAD_TAG_PREFIX
from backend.services.ragflow_delete_service import RagflowDatasetDeleteError, delete_ragflow_datasets


router = APIRouter(prefix="/api/clients", tags=["客户管理"])


def _canonical_company_name(data: dict) -> str:
    """产品语义上客户名/公司名统一为公司名称；name 仅作为兼容别名。"""
    return (data.get("company_name") or data.get("name") or data.get("client_name") or "").strip()


def _required_text(data: dict, field: str, label: str) -> str:
    value = (data.get(field) or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"缺少必要字段: {label}")
    return value


@router.get("", response_model=dict)
async def get_clients(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    status: Optional[int] = Query(None, description="状态筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    industry: Optional[str] = Query(None, description="行业筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取客户列表（按当前用户隔离）

    支持分页、状态筛选、行业筛选、关键词搜索
    """
    try:
        # 数据隔离：普通用户只看自己的客户；admin 看全部
        query = scoped_query(db, Client, current_user)

        if status is not None:
            query = query.filter(Client.status == status)

        if industry:
            query = query.filter(Client.industry == industry)

        if keyword:
            query = query.filter(or_(
                Client.name.contains(keyword),
                Client.company_name.contains(keyword)
            ))

        # 统计总数
        total = query.count()

        # 分页查询
        clients = query.order_by(Client.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

        # 序列化结果
        items = []
        for c in clients:
            # 统计项目数量（项目同样按用户隔离）
            project_query = scoped_query(db, Project, current_user)
            project_count = project_query.filter(Project.client_id == c.id).count()

            # 安全处理datetime序列化
            def safe_iso(dt):
                if dt is None:
                    return None
                try:
                    return dt.isoformat()
                except AttributeError:
                    return str(dt) if dt else None

            item = {
                "id": c.id,
                "name": c.company_name or c.name,
                "company_name": c.company_name or c.name,
                "contact_person": c.contact_person,
                "phone": c.phone,
                "email": c.email,
                "industry": c.industry,
                "location": c.location,
                "address": c.address,
                "website": c.website,
                "description": c.description,
                "status": c.status,
                "project_count": project_count,
                "created_at": safe_iso(c.created_at),
                "updated_at": safe_iso(c.updated_at),
            }
            items.append(item)

        return {"success": True, "total": total, "items": items, "page": page, "limit": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取客户列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取客户列表失败: {str(e)}")


@router.get("/{client_id}", response_model=dict)
async def get_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取客户详情"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")
    require_owner(client, current_user, name="客户")

    # 获取客户的项目列表（同样按用户隔离）
    projects = scoped_query(db, Project, current_user).filter(Project.client_id == client_id).all()

    return {
        "success": True,
        "data": {
            "id": client.id,
            "name": client.company_name or client.name,
            "company_name": client.company_name or client.name,
            "contact_person": client.contact_person,
            "phone": client.phone,
            "email": client.email,
            "industry": client.industry,
            "location": client.location,
            "address": client.address,
            "website": client.website,
            "description": client.description,
            "status": client.status,
            "created_at": client.created_at.isoformat() if client.created_at else None,
            "updated_at": client.updated_at.isoformat() if client.updated_at else None,
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "domain_keyword": p.domain_keyword,
                    "status": p.status,
                }
                for p in projects
            ],
        },
    }


@router.get("/{client_id}/projects", response_model=dict)
async def get_client_projects(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取客户的项目列表"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")
    require_owner(client, current_user, name="客户")

    projects = scoped_query(db, Project, current_user).filter(Project.client_id == client_id).all()

    return {
        "success": True,
        "data": [
            {
                "id": p.id,
                "name": p.name,
                "company_name": p.company_name,
                "domain_keyword": p.domain_keyword,
                "description": p.description,
                "industry": p.industry,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in projects
        ],
    }


@router.post("", response_model=ApiResponse)
async def create_client(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    创建客户（自动绑定当前用户 user_id）
    """
    company_name = _canonical_company_name(data)
    if not company_name:
        raise HTTPException(status_code=400, detail="缺少必要字段: company_name")
    industry = _required_text(data, "industry", "industry")
    location = _required_text(data, "location", "location")
    website = _required_text(data, "website", "website")

    try:
        client = Client(
            name=company_name,
            company_name=company_name,
            contact_person=data.get("contact_person"),
            phone=data.get("phone"),
            email=data.get("email"),
            industry=industry,
            location=location,
            address=data.get("address"),
            website=website,
            description=data.get("description"),
            status=data.get("status", 1),
            user_id=current_user.id,
        )
        db.add(client)
        db.commit()
        db.refresh(client)

        logger.info(f"新公司已创建: {client.company_name} (user_id={current_user.id})")
        return ApiResponse(success=True, message="创建成功", data={"client_id": client.id})

    except Exception as e:
        db.rollback()
        logger.error(f"创建客户失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{client_id}", response_model=ApiResponse)
async def update_client(
    client_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """更新客户信息"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")
    require_owner(client, current_user, name="客户")

    # 公司名称为唯一主语义；name/client_name 仅作为兼容别名。
    if any(key in data for key in ("company_name", "name", "client_name")):
        company_name = _canonical_company_name(data)
        if not company_name:
            raise HTTPException(status_code=400, detail="公司名称不能为空")
        client.name = company_name
        client.company_name = company_name
    if "contact_person" in data:
        client.contact_person = data["contact_person"]
    if "phone" in data:
        client.phone = data["phone"]
    if "email" in data:
        client.email = data["email"]
    if "industry" in data:
        client.industry = _required_text(data, "industry", "industry")
    if "location" in data:
        location = (data.get("location") or "").strip()
        if not location:
            raise HTTPException(status_code=400, detail="公司所在地不能为空")
        client.location = location
    if "address" in data:
        client.address = data["address"]
    if "website" in data:
        website = (data.get("website") or "").strip()
        if not website:
            raise HTTPException(status_code=400, detail="公司官网不能为空")
        client.website = website
    if "description" in data:
        client.description = data["description"]
    if "status" in data:
        client.status = data["status"]

    db.commit()
    db.refresh(client)

    logger.info(f"客户已更新: {client_id}")
    return ApiResponse(success=True, message="更新成功")


def _cascade_delete_client(client_id: int, user_id: int, db: Session) -> dict:
    """
    执行客户完整级联删除，返回清理统计。

    删除链路（按顺序执行，确保 FK 约束不被阻断）：
      1. 项目下所有关键词的文章（geo_articles）
      2. 项目下所有关键词的问题变体（question_variants）
      3. 项目下所有关键词的收录检测记录（index_check_records）
      4. 项目下所有关键词的使用记录（keyword_usage_records）
      5. 项目下所有关键词（keywords），其 cascade 会清理 question_variants / index_check_records
      6. 项目（projects），其 cascade 会清理 keywords
      7. 知识库分类及其下属知识条目（knowledge_categories → knowledge_items）
         （优先按 client_id 删除；migration 0014 未应用时降级按 user_id 删除）
      8. 最后删除客户本身
    """
    stats = {
        "projects": 0,
        "keywords": 0,
        "articles": 0,
        "question_variants": 0,
        "index_records": 0,
        "keyword_usage_records": 0,
        "knowledge_categories": 0,
        "knowledge_items": 0,
    }

    # 收集所有项目及其关键词 ID（用于清理不依赖 cascade 的表）
    projects = db.query(Project).filter(Project.client_id == client_id).all()
    project_ids = [p.id for p in projects]
    keyword_ids = []

    for project in projects:
        keywords = db.query(Keyword).filter(Keyword.project_id == project.id).all()
        keyword_ids.extend(k.id for k in keywords)

        # 1. 文章（geo_articles.keyword_id 是 NO ACTION，需手动清理）
        if keywords:
            article_count = db.query(GeoArticle).filter(GeoArticle.keyword_id.in_([k.id for k in keywords])).count()
            stats["articles"] += article_count
            db.query(GeoArticle).filter(GeoArticle.keyword_id.in_([k.id for k in keywords])).delete(synchronize_session=False)

        # 2. 问题变体（显式删除，确保跨数据库兼容性）
        if keywords:
            qv_count = db.query(QuestionVariant).filter(QuestionVariant.keyword_id.in_([k.id for k in keywords])).count()
            stats["question_variants"] += qv_count
            db.query(QuestionVariant).filter(QuestionVariant.keyword_id.in_([k.id for k in keywords])).delete(synchronize_session=False)

        # 3. 收录检测记录（显式删除，确保跨数据库兼容性）
        if keywords:
            ic_count = db.query(IndexCheckRecord).filter(IndexCheckRecord.keyword_id.in_([k.id for k in keywords])).count()
            stats["index_records"] += ic_count
            db.query(IndexCheckRecord).filter(IndexCheckRecord.keyword_id.in_([k.id for k in keywords])).delete(synchronize_session=False)

        # 4. 关键词使用记录（FK 是 SET NULL，显式删除防止残留）
        kur_count = db.query(KeywordUsageRecord).filter(KeywordUsageRecord.project_id == project.id).count()
        stats["keyword_usage_records"] += kur_count
        db.query(KeywordUsageRecord).filter(KeywordUsageRecord.project_id == project.id).delete(synchronize_session=False)

    # 5. 删除关键词（cascade 清理 question_variants / index_check_records）
    if keyword_ids:
        kw_count = db.query(Keyword).filter(Keyword.id.in_(keyword_ids)).count()
        stats["keywords"] += kw_count
        db.query(Keyword).filter(Keyword.id.in_(keyword_ids)).delete(synchronize_session=False)

    # 6. 删除项目（cascade 清理 keywords）
    if project_ids:
        proj_count = db.query(Project).filter(Project.id.in_(project_ids)).count()
        stats["projects"] += proj_count
        db.query(Project).filter(Project.id.in_(project_ids)).delete(synchronize_session=False)

    # 7. 知识库分类及其下属知识条目
    #    关键顺序：先找分类ID → 先删知识条目（FK NO ACTION）→ 再删分类
    #    删除策略：按 client_id 或 tags 查找该客户的知识库分类
    try:
        client_tags = f"{CLIENT_UPLOAD_TAG_PREFIX}{client_id}"
        kc_rows = (
            db.query(KnowledgeCategory.id, KnowledgeCategory.ragflow_dataset_id)
            .filter(
                KnowledgeCategory.user_id == user_id,
                or_(KnowledgeCategory.client_id == client_id, KnowledgeCategory.tags == client_tags),
            )
            .all()
        )
        kc_ids = [r[0] for r in kc_rows]
        dataset_ids = [r[1] for r in kc_rows if r[1]]

        kc_count = len(kc_ids)
        stats["knowledge_categories"] = kc_count

        # 先尝试删 RAGFlow 远程数据集（失败不阻断客户删除，只记警告）
        if dataset_ids:
            try:
                delete_ragflow_datasets(dataset_ids)
            except Exception as ragflow_err:
                logger.warning(f"[cascade] RAGFlow 数据集删除失败（不阻断客户删除）: {ragflow_err}")

        # 删知识条目（category_id FK 是 NO ACTION，必须显式删除）
        if kc_ids:
            ki_count = db.query(Knowledge).filter(Knowledge.category_id.in_(kc_ids)).count()
            stats["knowledge_items"] = ki_count
            db.query(Knowledge).filter(Knowledge.category_id.in_(kc_ids)).delete(synchronize_session=False)
            # 再删分类
            db.query(KnowledgeCategory).filter(KnowledgeCategory.id.in_(kc_ids)).delete(synchronize_session=False)
        else:
            stats["knowledge_items"] = 0
    except Exception as e:
        logger.warning(f"[cascade] 知识库分类删除异常: {e}，跳过")
        stats["knowledge_categories"] = stats.get("knowledge_categories", 0)
        stats["knowledge_items"] = stats.get("knowledge_items", 0)

    return stats


@router.delete("/{client_id}", response_model=ApiResponse)
async def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除客户
    级联删除该客户下的所有项目、关键词、文章、知识库等全部关联数据
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")
    require_owner(client, current_user, name="客户")

    # 执行完整级联删除
    stats = _cascade_delete_client(client_id, client.user_id, db)
    total_related = (
        stats["projects"] + stats["keywords"] + stats["articles"]
        + stats["question_variants"] + stats["index_records"]
        + stats["keyword_usage_records"]
        + stats["knowledge_categories"] + stats["knowledge_items"]
    )

    if total_related > 0:
        logger.warning(
            f"删除客户 {client_id}，级联清理：项目{stats['projects']}个/"
            f"关键词{stats['keywords']}条/文章{stats['articles']}篇/"
            f"问题变体{stats['question_variants']}条/收录记录{stats['index_records']}条/"
            f"关键词使用记录{stats['keyword_usage_records']}条/知识库分类{stats['knowledge_categories']}个/"
            f"知识条目{stats['knowledge_items']}条"
        )

    # 8. 最后删除客户本身
    db.delete(client)
    db.commit()

    logger.info(f"客户已删除: {client_id}")
    return ApiResponse(success=True, message="删除成功")


@router.get("/stats/overview", response_model=dict)
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取客户统计信息（按当前用户隔离）"""
    query = scoped_query(db, Client, current_user)
    total = query.count()
    active = query.filter(Client.status == 1).count()

    # 获取行业分布
    industries = query.with_entities(Client.industry).filter(Client.industry.isnot(None)).all()
    industry_dist = {}
    for (ind,) in industries:
        industry_dist[ind] = industry_dist.get(ind, 0) + 1

    return {
        "success": True,
        "data": {"total": total, "active": active, "inactive": total - active, "industry_distribution": industry_dist},
    }


@router.get("/indicators/list", response_model=dict)
async def get_indicators(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取客户行业列表（用于筛选，按当前用户隔离）"""
    rows = (
        scoped_query(db, Client, current_user)
        .with_entities(Client.industry)
        .filter(Client.industry.isnot(None), Client.industry != "")
        .distinct()
        .all()
    )

    return {"success": True, "data": [ind[0] for ind in rows if ind[0]]}
