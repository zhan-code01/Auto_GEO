# -*- coding: utf-8 -*-
"""
知识库管理API
管理企业知识库分类和知识条目
"""

import os
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Path
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import KnowledgeCategory, Knowledge, Client, User
from backend.schemas import ApiResponse, PaginatedResponse
from backend.api.user import get_current_user_from_token, require_admin
from backend.middleware.user_isolation import scoped_query, require_owner
from backend.services.geo_knowledge_service import CLIENT_UPLOAD_TAG_PREFIX
from backend.services.ragflow_delete_service import RagflowDatasetDeleteError, delete_ragflow_datasets
from loguru import logger


router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])


def _get_owned_category(db: Session, category_id: int, current_user: User) -> KnowledgeCategory:
    """获取知识库分类并校验归属（不存在→404；不属于当前用户→403；admin 放行）。"""
    category = db.query(KnowledgeCategory).filter(KnowledgeCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="知识库分类不存在")
    require_owner(category, current_user, name="知识库分类")
    return category


def _get_owned_knowledge(db: Session, knowledge_id: int, current_user: User) -> Knowledge:
    """获取知识条目并校验其所属分类的归属。"""
    knowledge = db.query(Knowledge).filter(Knowledge.id == knowledge_id).first()
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识不存在")
    # 通过 ragflow_dataset_id 关联到分类，校验分类归属
    if knowledge.ragflow_dataset_id:
        cat = (
            db.query(KnowledgeCategory)
            .filter(KnowledgeCategory.ragflow_dataset_id == knowledge.ragflow_dataset_id)
            .first()
        )
        if cat:
            require_owner(cat, current_user, name="知识库分类")
    return knowledge


def _require_dataset_owner(db: Session, dataset_id: str, current_user: User):
    """
    校验 RAGFlow 知识库（dataset）归属：
    - admin 放行
    - 普通用户：仅当该 dataset_id 属于其名下分类（ragflow_dataset_id 匹配）时放行，否则 403
    这样一个用户只能查看/管理自己创建的知识库的数据。
    """
    if getattr(current_user, "role", None) == "admin":
        return
    owned = (
        db.query(KnowledgeCategory.id)
        .filter(
            KnowledgeCategory.ragflow_dataset_id == str(dataset_id),
            KnowledgeCategory.user_id == current_user.id,
        )
        .first()
    )
    if not owned:
        raise HTTPException(status_code=403, detail="无权访问该知识库")


CLIENT_UPLOAD_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
CLIENT_UPLOAD_MAX_FILES = 5
CLIENT_UPLOAD_MAX_FILE_SIZE = 10 * 1024 * 1024
CLIENT_UPLOAD_CATEGORY_LABELS = {
    "company": "公司资料",
    "product": "产品文档",
    "industry": "行业报告",
    "technical": "技术文档",
    "other": "其他",
}


def _extract_ragflow_id(result: dict) -> Optional[str]:
    """兼容 RAGFlow 不同版本的 id 返回格式。"""
    data = result.get("data")
    if isinstance(data, dict):
        dataset_id = data.get("id")
        if dataset_id:
            return str(dataset_id)
    if isinstance(data, list) and data:
        dataset_id = data[0].get("id")
        if dataset_id:
            return str(dataset_id)
    dataset_id = result.get("id")
    return str(dataset_id) if dataset_id else None


def _extract_ragflow_documents(result: dict) -> List[dict]:
    """Normalize RAGFlow upload responses across versions."""
    data = result.get("data")
    if isinstance(data, list):
        return [doc for doc in data if isinstance(doc, dict)]
    if isinstance(data, dict):
        for key in ("docs", "documents", "items", "list"):
            docs = data.get(key)
            if isinstance(docs, list):
                return [doc for doc in docs if isinstance(doc, dict)]
        if data.get("id"):
            return [data]
    if result.get("id"):
        return [result]
    return []


def _build_client_upload_tags(client_id: int) -> str:
    return f"source=client_upload,client_id={client_id}"


def _safe_upload_filename(file_name: Optional[str]) -> str:
    base_name = os.path.basename(file_name or "unknown")
    return base_name or "unknown"


# ==================== 请求/响应模型 ====================


class KnowledgeCategoryCreate(BaseModel):
    """创建知识库分类请求"""

    name: str
    industry: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    color: str = "#6366f1"
    client_id: Optional[int] = None  # 关联的客户ID（可选，便于级联删除）


class KnowledgeCategoryUpdate(BaseModel):
    """更新知识库分类请求"""

    name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    color: Optional[str] = None


class KnowledgeCategoryResponse(BaseModel):
    """知识库分类响应"""

    id: int
    name: str
    industry: Optional[str]
    description: Optional[str]
    tags: Optional[str]
    color: str
    knowledge_count: int
    project_count: int
    created_at: str
    updated_at: str


class KnowledgeCreate(BaseModel):
    """创建知识条目请求"""

    category_id: int
    title: str
    content: str
    type: str = "other"


class KnowledgeUpdate(BaseModel):
    """更新知识条目请求"""

    title: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None


class KnowledgeResponse(BaseModel):
    """知识条目响应"""

    id: int
    category_id: int
    title: str
    content: str
    type: str
    created_at: str
    updated_at: str


# ==================== 知识库分类API ====================


@router.get("/categories", response_model=PaginatedResponse[KnowledgeCategoryResponse])
async def get_categories(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取知识库分类列表（支持分页）
    """
    # ... 同步RAGFlow的代码保持不变 ...
    from backend.services.ragflow_client import get_ragflow_client
    from starlette.concurrency import run_in_threadpool

    try:
        ragflow_client = get_ragflow_client()
        ragflow_result = await run_in_threadpool(ragflow_client.list_datasets)

        if ragflow_result.get("code") == 0:
            ragflow_datasets = ragflow_result.get("data", [])

            for dataset in ragflow_datasets:
                ragflow_dataset_id = dataset.get("id")
                if getattr(current_user, "role", None) != "admin":
                    continue
                category = (
                    db.query(KnowledgeCategory)
                    .filter(KnowledgeCategory.ragflow_dataset_id == ragflow_dataset_id)
                    .first()
                )

                if category:
                    category.name = dataset.get("name")
                    category.description = dataset.get("description", "")
                    category.sync_status = "synced"
                    category.last_sync_at = datetime.now()
                else:
                    category = KnowledgeCategory(
                        ragflow_dataset_id=ragflow_dataset_id,
                        name=dataset.get("name"),
                        description=dataset.get("description", ""),
                        sync_status="synced",
                        last_sync_at=datetime.now(),
                    )
                    db.add(category)

            db.commit()
    except Exception as e:
        logger.warning(f"从RAGFlow同步分类失败，使用SQLite缓存: {e}")

    # 同步 RAGFlow 分类（仅同步当前用户可见的，避免越权）
    # 策略：只同步当前用户本地已存在的 ragflow_dataset_id；对于 RAGFlow 上有但本地没有的，不主动创建（防止跨用户数据泄露）
    try:
        ragflow_client = get_ragflow_client()
        ragflow_result = await run_in_threadpool(ragflow_client.list_datasets)

        if ragflow_result.get("code") == 0:
            ragflow_datasets = ragflow_result.get("data", [])

            for dataset in ragflow_datasets:
                ragflow_dataset_id = dataset.get("id")
                if not ragflow_dataset_id:
                    continue

                # 查找本地是否已有该 ragflow_dataset_id 的记录（按 user_id 隔离）
                # admin 可以看所有，普通用户只看自己的
                existing_query = db.query(KnowledgeCategory).filter(
                    KnowledgeCategory.ragflow_dataset_id == ragflow_dataset_id
                )
                if getattr(current_user, "role", None) != "admin":
                    existing_query = existing_query.filter(KnowledgeCategory.user_id == current_user.id)
                existing_cat = existing_query.first()

                if existing_cat:
                    # 更新已有记录
                    existing_cat.name = dataset.get("name")
                    existing_cat.description = dataset.get("description", "")
                    existing_cat.sync_status = "synced"
                    existing_cat.last_sync_at = datetime.now()
                # else: RAGFlow 上有这个 dataset，但本地没有归属当前用户的记录 → 跳过，不创建
                # 这样防止普通用户通过同步看到其他用户创建的 RAGFlow 知识库

            db.commit()
    except Exception as e:
        logger.warning(f"从RAGFlow同步分类失败，使用SQLite缓存: {e}")

    # 查询（带搜索）—— 按当前用户隔离：普通用户只看自己的分类，admin 看全部
    query = scoped_query(db, KnowledgeCategory, current_user).filter(KnowledgeCategory.status == 1)

    if search:
        query = query.filter(
            (KnowledgeCategory.name.like(f"%{search}%"))
            | (KnowledgeCategory.industry.like(f"%{search}%"))
            | (KnowledgeCategory.tags.like(f"%{search}%"))
        )

    # 统计总数
    total = query.count()

    # 分页查询
    categories = query.order_by(KnowledgeCategory.updated_at.desc()).offset((page - 1) * limit).limit(limit).all()

    # 构建响应
    result = []
    for cat in categories:
        knowledge_count = (
            db.query(Knowledge)
            .filter(Knowledge.ragflow_dataset_id == cat.ragflow_dataset_id, Knowledge.status == 1)
            .count()
        )

        from backend.database.models import Project
        project_count = (
            db.query(Project).filter(Project.industry == cat.industry, Project.status == 1).count()
            if cat.industry
            else 0
        )

        result.append(
            KnowledgeCategoryResponse(
                id=cat.id,
                name=cat.name,
                industry=cat.industry,
                description=cat.description,
                tags=cat.tags,
                color=cat.color,
                knowledge_count=knowledge_count,
                project_count=project_count,
                created_at=cat.created_at.isoformat() if cat.created_at else "",
                updated_at=cat.updated_at.isoformat() if cat.updated_at else "",
            )
        )

    # 计算分页信息
    pages = (total + limit - 1) // limit if total > 0 else 1

    return PaginatedResponse(
        total=total,
        items=result,
        page=page,
        limit=limit,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1
    )


@router.post("/categories", response_model=ApiResponse)
async def create_category(
    data: KnowledgeCategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    创建知识库分类
    先在RAGFlow创建知识库，再更新SQLite缓存

    Args:
        data: 分类数据
        db: 数据库会话

    Returns:
        创建结果
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        # 1. 在RAGFlow创建知识库
        ragflow_client = get_ragflow_client()
        ragflow_result = ragflow_client.create_dataset(
            name=data.name, description=data.description or f"{data.name} - AutoGeo知识库"
        )

        logger.info(f"RAGFlow返回结果: {ragflow_result}")

        if ragflow_result.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"RAGFlow创建失败: {ragflow_result.get('message')}")

        # 尝试多种方式获取 dataset_id
        dataset_id = None

        # 方式1: data.id (标准格式)
        if not dataset_id and ragflow_result.get("data"):
            dataset_id = ragflow_result.get("data", {}).get("id")

        # 方式2: 直接在 result 中 (某些 API 格式)
        if not dataset_id:
            dataset_id = ragflow_result.get("id")

        # 方式3: data 是数组，取第一个
        if not dataset_id and isinstance(ragflow_result.get("data"), list):
            data_list = ragflow_result.get("data", [])
            if data_list:
                dataset_id = data_list[0].get("id")

        logger.info(f"解析到的 dataset_id: {dataset_id}")

        if not dataset_id:
            raise HTTPException(status_code=500, detail=f"RAGFlow返回的dataset_id为空，返回数据: {ragflow_result}")

        # 2. 在SQLite创建缓存记录
        logger.info(f"准备创建数据库记录，dataset_id类型: {type(dataset_id)}, 值: {dataset_id}")
        # 如果关联了客户但缺少标准 tags，自动补齐，保证 has_client_documents 等查询能命中
        effective_tags = data.tags
        if data.client_id and not data.tags:
            effective_tags = _build_client_upload_tags(data.client_id)
        elif data.client_id and data.tags and CLIENT_UPLOAD_TAG_PREFIX not in data.tags:
            effective_tags = data.tags + "," + _build_client_upload_tags(data.client_id)
        category = KnowledgeCategory(
            ragflow_dataset_id=str(dataset_id),  # 确保转换为字符串
            name=data.name,
            industry=data.industry,
            description=data.description,
            tags=effective_tags,
            color=data.color,
            sync_status="synced",
            last_sync_at=datetime.now(),
            user_id=current_user.id,  # 数据隔离归属
            client_id=data.client_id,  # 关联客户（便于级联删除）
        )
        db.add(category)
        db.commit()
        db.refresh(category)
        logger.info(f"数据库记录创建成功，category.id: {category.id}")

        logger.info(f"分类创建成功（RAGFlow ID: {dataset_id}）: {category.name}")

        return ApiResponse(
            success=True, data={"id": category.id, "ragflow_dataset_id": dataset_id}, message="分类创建成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/categories/{category_id}", response_model=ApiResponse)
async def update_category(
    category_id: int,
    data: KnowledgeCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    更新知识库分类

    Args:
        category_id: 分类ID
        data: 更新数据
        db: 数据库会话

    Returns:
        更新结果
    """
    try:
        category = _get_owned_category(db, category_id, current_user)
        if data.name is not None:
            category.name = data.name
        if data.industry is not None:
            category.industry = data.industry
        if data.description is not None:
            category.description = data.description
        if data.tags is not None:
            category.tags = data.tags
        if data.color is not None:
            category.color = data.color

        # 如果关联了客户但缺少标准 tags，自动补齐
        if category.client_id and (not category.tags or CLIENT_UPLOAD_TAG_PREFIX not in (category.tags or "")):
            std_tags = _build_client_upload_tags(category.client_id)
            if category.tags:
                category.tags = category.tags + "," + std_tags
            else:
                category.tags = std_tags

        db.commit()
        return ApiResponse(success=True, message="分类更新成功")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/categories/{category_id}", response_model=ApiResponse)
async def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除知识库分类

    Args:
        category_id: 分类ID
        db: 数据库会话

    Returns:
        删除结果
    """
    try:
        category = _get_owned_category(db, category_id, current_user)

        # 删除分类（会级联删除关联的知识）
        dataset_id = category.ragflow_dataset_id
        if dataset_id:
            try:
                delete_ragflow_datasets([dataset_id])
            except RagflowDatasetDeleteError as exc:
                logger.error(f"删除 RAGFlow 知识库失败，已保留本地分类: category_id={category_id}, error={exc}")
                raise HTTPException(status_code=502, detail=f"RAGFlow 知识库删除失败: {exc}") from exc

        db.delete(category)
        db.commit()

        return ApiResponse(success=True, message="分类删除成功")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 知识条目API ====================


@router.get("/categories/{category_id}/knowledge", response_model=List[KnowledgeResponse])
async def get_knowledge_list(
    category_id: int,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取指定分类的知识列表
    从RAGFlow获取文档并更新SQLite缓存

    Args:
        category_id: 分类ID
        search: 搜索关键词（可选）
        db: 数据库会话

    Returns:
        知识条目列表
    """
    category = _get_owned_category(db, category_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    # 1. 获取分类的RAGFlow知识库ID（已在校验函数中确认归属）
    if not category.ragflow_dataset_id:
        raise HTTPException(status_code=400, detail="分类未关联RAGFlow知识库")

    try:
        # 2. 从RAGFlow获取文档列表
        ragflow_client = get_ragflow_client()
        ragflow_result = ragflow_client.list_documents(category.ragflow_dataset_id)

        if ragflow_result.get("code") == 0:
            ragflow_docs = ragflow_result.get("data", [])

            # 3. 同步到SQLite缓存
            for doc in ragflow_docs:
                ragflow_doc_id = doc.get("id")

                # 检查是否存在
                knowledge = db.query(Knowledge).filter(Knowledge.ragflow_document_id == ragflow_doc_id).first()

                if not knowledge:
                    # 创建缓存
                    knowledge = Knowledge(
                        ragflow_document_id=ragflow_doc_id,
                        ragflow_dataset_id=category.ragflow_dataset_id,
                        title=doc.get("name", ""),
                        type="other",
                        sync_status="synced",
                        last_sync_at=datetime.now(),
                    )
                    db.add(knowledge)

            db.commit()
    except Exception as e:
        logger.warning(f"从RAGFlow同步知识失败，使用SQLite缓存: {e}")

    # 4. 从SQLite返回（带搜索）
    query = db.query(Knowledge).filter(
        Knowledge.ragflow_dataset_id == category.ragflow_dataset_id, Knowledge.status == 1
    )

    if search:
        # 从RAGFlow搜索
        try:
            ragflow_client = get_ragflow_client()
            search_result = ragflow_client.retrieve(
                question=search, dataset_ids=[category.ragflow_dataset_id], top_k=100, similarity_threshold=0.0
            )

            if search_result.get("code") == 0:
                chunks = search_result.get("data", {}).get("chunks", [])
                doc_ids = set(chunk.get("document_id") for chunk in chunks)

                # 过滤出搜索到的文档
                if doc_ids:
                    query = query.filter(Knowledge.ragflow_document_id.in_(doc_ids))
        except Exception as e:
            logger.warning(f"RAGFlow搜索失败，使用本地搜索: {e}")
            # 降级到本地标题搜索
            query = query.filter(Knowledge.title.like(f"%{search}%"))

    items = query.order_by(Knowledge.updated_at.desc()).all()

    # 5. 获取文档内容（从RAGFlow）
    result = []
    for item in items:
        content = item.title  # 默认使用标题

        try:
            # 从RAGFlow获取完整内容
            content_result = ragflow_client.get_document_content(category.ragflow_dataset_id, item.ragflow_document_id)
            if content_result.get("code") == 0:
                content = content_result.get("data", {}).get("content", item.title)
        except Exception as e:
            logger.warning(f"获取文档内容失败: {e}")

        result.append(
            KnowledgeResponse(
                id=item.id,
                category_id=category_id,
                title=item.title,
                content=content,
                type=item.type,
                created_at=item.created_at.isoformat() if item.created_at else "",
                updated_at=item.updated_at.isoformat() if item.updated_at else "",
            )
        )

    return result


@router.post("/knowledge", response_model=ApiResponse)
async def create_knowledge(
    data: KnowledgeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    创建知识条目
    先在RAGFlow上传文档，再更新SQLite缓存

    Args:
        data: 知识数据
        db: 数据库会话

    Returns:
        创建结果
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        # 1. 获取分类的RAGFlow知识库ID（校验归属）
        category = _get_owned_category(db, data.category_id, current_user)

        if not category.ragflow_dataset_id:
            raise HTTPException(status_code=400, detail="分类未关联RAGFlow知识库")

        # 2. 在RAGFlow上传文档
        ragflow_client = get_ragflow_client()
        ragflow_result = ragflow_client.upload_document_content(
            dataset_id=category.ragflow_dataset_id, title=data.title, content=data.content
        )

        if ragflow_result.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"RAGFlow上传失败: {ragflow_result.get('message')}")

        docs = ragflow_result.get("data", [])
        if not docs:
            raise HTTPException(status_code=500, detail="RAGFlow返回的文档列表为空")

        doc_id = docs[0].get("id")
        if not doc_id:
            raise HTTPException(status_code=500, detail="RAGFlow返回的文档ID为空")

        # 3. 在SQLite创建缓存记录
        knowledge = Knowledge(
            ragflow_document_id=doc_id,
            ragflow_dataset_id=category.ragflow_dataset_id,
            category_id=data.category_id,  # 添加 category_id
            title=data.title,
            content=data.content[:500] if data.content else data.title,  # 保存内容摘要到数据库
            type=data.type,
            sync_status="synced",
            last_sync_at=datetime.now(),
        )
        db.add(knowledge)
        db.commit()
        db.refresh(knowledge)

        logger.info(f"知识创建成功（RAGFlow ID: {doc_id}）: {knowledge.title}")

        return ApiResponse(
            success=True, data={"id": knowledge.id, "ragflow_document_id": doc_id}, message="知识添加成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge/upload", response_model=ApiResponse)
async def upload_knowledge_file(
    category_id: int = Form(...),
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    type: Optional[str] = Form("other"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    上传文件到知识库（支持PDF、Word、Excel等格式）

    Args:
        category_id: 分类ID
        file: 上传的文件
        title: 自定义标题（可选，默认使用文件名）
        type: 知识类型
        db: 数据库会话

    Returns:
        创建结果
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        # 1. 获取分类的RAGFlow知识库ID（校验归属）
        category = _get_owned_category(db, category_id, current_user)

        if not category.ragflow_dataset_id:
            raise HTTPException(status_code=400, detail="分类未关联RAGFlow知识库")

        # 2. 读取上传的文件内容
        file_content = await file.read()
        file_name = title or file.filename

        # 3. 在RAGFlow上传文件
        ragflow_client = get_ragflow_client()
        ragflow_result = ragflow_client.upload_document_bytes(
            dataset_id=category.ragflow_dataset_id,
            file_content=file_content,
            file_name=file_name,
        )

        if ragflow_result.get("code") != 0:
            raise HTTPException(status_code=500, detail=f"RAGFlow上传失败: {ragflow_result.get('message')}")

        docs = ragflow_result.get("data", [])
        if not docs:
            raise HTTPException(status_code=500, detail="RAGFlow返回的文档列表为空")

        doc_id = docs[0].get("id")
        if not doc_id:
            raise HTTPException(status_code=500, detail="RAGFlow返回的文档ID为空")

        # 4. 在SQLite创建缓存记录
        knowledge = Knowledge(
            ragflow_document_id=doc_id,
            ragflow_dataset_id=category.ragflow_dataset_id,
            category_id=category_id,
            title=file_name,
            content=f"文件: {file_name}",  # 保存文件名作为摘要
            type=type,
            sync_status="synced",
            last_sync_at=datetime.now(),
        )
        db.add(knowledge)
        db.commit()
        db.refresh(knowledge)

        logger.info(f"文件上传成功（RAGFlow ID: {doc_id}）: {file_name}")

        return ApiResponse(
            success=True,
            data={"id": knowledge.id, "ragflow_document_id": doc_id, "file_name": file_name},
            message="文件上传成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload", response_model=ApiResponse)
async def upload_client_files(
    client_id: str = Form(...),
    category: str = Form(...),
    description: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    客户管理 - 上传资料文件到知识库

    与前端 ClientPage.vue 对齐：
    - client_id: 客户ID
    - category: 分类名称
    - description: 描述
    - files: 多个文件

    实际入库逻辑统一委托给 ``KnowledgeIngestionService.upload_files``，
    与后台智能体 Agent 工具共用同一套闭环（方案 §6.7）。
    """
    from backend.services.knowledge_ingestion_service import KnowledgeIngestionService

    try:
        try:
            client_id_int = int(client_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="客户ID格式不正确")

        # 把 UploadFile 转成 service 需要的 {filename, content, content_type}
        file_payloads = []
        for f in files:
            content = await f.read()
            file_payloads.append(
                {
                    "filename": _safe_upload_filename(f.filename),
                    "content": content,
                    "content_type": f.content_type,
                }
            )

        service = KnowledgeIngestionService(db)
        result = await service.upload_files(
            user=current_user,
            client_id=client_id_int,
            files=file_payloads,
            category=category,
            description=description,
        )

        # RAGFlow 未配置：不阻断调用方（与 service 设计一致，文档 P0-3）。
        # service 已返回 ragflow_configured:false 的完整 result，这里以 success=False 透出，
        # 让前端提示「资料暂未入库，可继续生成」，而不是抛 500 报「上传失败」。
        if not result.get("ragflow_configured"):
            return ApiResponse(
                success=False,
                data=result,
                message="RAGFlow 未配置，资料暂未入库，可继续生成文章",
            )

        return ApiResponse(
            success=True,
            data=result,
            message=f"上传完成: 成功 {result['success_count']} 个, 失败 {result['failed_count']} 个",
        )

    except HTTPException:
        raise
    except ValueError as e:
        # service 层的参数/归属校验
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"客户资料上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/knowledge/{knowledge_id}", response_model=ApiResponse)
async def update_knowledge(
    knowledge_id: int,
    data: KnowledgeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    更新知识条目

    Args:
        knowledge_id: 知识ID
        data: 更新数据
        db: 数据库会话

    Returns:
        更新结果
    """
    try:
        knowledge = _get_owned_knowledge(db, knowledge_id, current_user)

        if data.title is not None:
            knowledge.title = data.title
        if data.content is not None:
            knowledge.content = data.content
        if data.type is not None:
            knowledge.type = data.type

        db.commit()
        return ApiResponse(success=True, message="知识更新成功")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge/{knowledge_id}", response_model=ApiResponse)
async def delete_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除知识条目

    Args:
        knowledge_id: 知识ID
        db: 数据库会话

    Returns:
        删除结果
    """
    try:
        knowledge = _get_owned_knowledge(db, knowledge_id, current_user)

        db.delete(knowledge)
        db.commit()

        return ApiResponse(success=True, message="知识删除成功")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge/search", response_model=List[KnowledgeResponse])
async def search_knowledge(
    keyword: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    全局搜索知识（仅在当前用户可见的知识库分类中搜索）

    Args:
        keyword: 搜索关键词
        db: 数据库会话

    Returns:
        知识条目列表
    """
    # 数据隔离：只搜索当前用户名下分类里的知识条目
    user_dataset_ids = [
        r[0]
        for r in scoped_query(db, KnowledgeCategory, current_user)
        .with_entities(KnowledgeCategory.ragflow_dataset_id)
        .filter(KnowledgeCategory.ragflow_dataset_id.isnot(None))
        .all()
    ]

    base_query = db.query(Knowledge).filter(Knowledge.status == 1)
    if user_dataset_ids:
        base_query = base_query.filter(Knowledge.ragflow_dataset_id.in_(user_dataset_ids))
    else:
        # 当前用户没有任何分类，直接返回空（避免搜到他人数据）
        return []

    items = (
        base_query.filter(
            (Knowledge.title.like(f"%{keyword}%")) | (Knowledge.content.like(f"%{keyword}%"))
        )
        .order_by(Knowledge.updated_at.desc())
        .limit(50)
        .all()
    )

    return [
        KnowledgeResponse(
            id=item.id,
            category_id=item.category_id,
            title=item.title,
            content=item.content,
            type=item.type,
            created_at=item.created_at.isoformat() if item.created_at else "",
            updated_at=item.updated_at.isoformat() if item.updated_at else "",
        )
        for item in items
    ]


# ==================== RAGFlow同步API ====================


@router.post("/sync/categories/{category_id}", response_model=ApiResponse)
async def sync_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    同步指定分类到RAGFlow

    Args:
        category_id: 分类ID
        db: 数据库会话

    Returns:
        同步结果
    """
    try:
        category = _get_owned_category(db, category_id, current_user)

        from backend.services.knowledge_sync_service import get_sync_service

        sync_service = get_sync_service(db)

        success = sync_service.sync_category_to_ragflow(category)
        if success:
            return ApiResponse(success=True, message="分类同步成功")
        else:
            return ApiResponse(success=False, message="分类同步失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步分类失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/knowledge/{knowledge_id}", response_model=ApiResponse)
async def sync_knowledge(
    knowledge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    同步指定知识条目到RAGFlow

    Args:
        knowledge_id: 知识ID
        db: 数据库会话

    Returns:
        同步结果
    """
    try:
        knowledge = _get_owned_knowledge(db, knowledge_id, current_user)

        from backend.services.knowledge_sync_service import get_sync_service

        sync_service = get_sync_service(db)

        success = sync_service.sync_knowledge_to_ragflow(knowledge)
        if success:
            return ApiResponse(success=True, message="知识同步成功")
        else:
            return ApiResponse(success=False, message="知识同步失败")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/all", response_model=ApiResponse)
async def sync_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    同步所有分类和知识到RAGFlow

    Args:
        db: 数据库会话

    Returns:
        同步结果
    """
    try:
        from backend.services.knowledge_sync_service import get_sync_service

        sync_service = get_sync_service(db)

        # 同步分类
        cat_success, cat_fail = sync_service.sync_all_categories()

        # 同步知识
        know_success, know_fail = sync_service.sync_all_knowledge()

        return ApiResponse(
            success=True,
            data={
                "categories": {"success": cat_success, "failed": cat_fail},
                "knowledge": {"success": know_success, "failed": know_fail},
            },
            message=f"同步完成: 分类成功{cat_success}失败{cat_fail}, 知识成功{know_success}失败{know_fail}",
        )

    except Exception as e:
        logger.error(f"全量同步失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/status/{category_id}", response_model=ApiResponse)
async def get_sync_status(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取分类的同步状态

    Args:
        category_id: 分类ID
        db: 数据库会话

    Returns:
        同步状态信息
    """
    try:
        _get_owned_category(db, category_id, current_user)
        from backend.services.knowledge_sync_service import get_sync_service

        sync_service = get_sync_service(db)

        status = sync_service.get_sync_status(category_id)
        return ApiResponse(success=True, data=status)

    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/semantic", response_model=ApiResponse)
async def semantic_search(
    query: str = Query(..., min_length=1),
    category_id: Optional[int] = None,
    top_k: int = Query(50, ge=1, le=100),
    similarity_threshold: float = Query(0.7, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    使用RAGFlow进行语义搜索

    Args:
        query: 搜索查询
        category_id: 限定分类ID（可选）
        top_k: 返回结果数量
        similarity_threshold: 相似度阈值
        db: 数据库会话

    Returns:
        搜索结果
    """
    try:
        from backend.services.knowledge_sync_service import get_sync_service
        from backend.config import RAGFLOW_DATASET_ID

        sync_service = get_sync_service(db)

        # 确定要搜索的知识库ID列表（仅限当前用户可见的分类）
        dataset_ids = []

        if category_id:
            # 搜索指定分类（校验归属）
            category = _get_owned_category(db, category_id, current_user)
            if category.ragflow_dataset_id:
                dataset_ids.append(category.ragflow_dataset_id)
        else:
            # 搜索当前用户名下已同步的分类
            categories = (
                scoped_query(db, KnowledgeCategory, current_user)
                .filter(KnowledgeCategory.ragflow_dataset_id.isnot(None), KnowledgeCategory.status == 1)
                .all()
            )
            dataset_ids = [cat.ragflow_dataset_id for cat in categories]

        # 如果没有知识库，使用默认知识库
        if not dataset_ids and RAGFLOW_DATASET_ID:
            dataset_ids.append(RAGFLOW_DATASET_ID)

        if not dataset_ids:
            return ApiResponse(success=True, data=[], message="没有可搜索的知识库")

        # 执行搜索
        results = sync_service.search_in_ragflow(
            query=query, dataset_ids=dataset_ids, top_k=top_k, similarity_threshold=similarity_threshold
        )

        return ApiResponse(success=True, data=results, message=f"找到 {len(results)} 个相关结果")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"语义搜索失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-info", response_model=ApiResponse)
async def extract_document_info(
    knowledge_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    从知识库文档中提取客户信息

    使用AI从上传的文档中自动提取客户信息：
    - 公司名称
    - 联系人
    - 电话
    - 邮箱
    - 行业
    - 地址
    - 业务描述

    Args:
        knowledge_id: 知识ID
        db: 数据库会话

    Returns:
        提取的客户信息
    """
    try:
        from backend.services.document_extractor import get_document_extractor
        from backend.services.ragflow_client import get_ragflow_client

        # 1. 获取知识记录（校验归属）
        knowledge = _get_owned_knowledge(db, knowledge_id, current_user)

        # 2. 从RAGFlow提取文档信息
        ragflow_client = get_ragflow_client()
        extractor = get_document_extractor()

        extracted_info = extractor.extract_from_ragflow_document(
            dataset_id=knowledge.ragflow_dataset_id,
            document_id=knowledge.ragflow_document_id,
            ragflow_client=ragflow_client,
        )

        if not extracted_info:
            return ApiResponse(
                success=False,
                data={},
                message="未能从文档中提取到客户信息，请确认文档内容包含相关信息",
            )

        # 3. 尝试自动创建或更新客户记录
        client_data = {}
        if extracted_info.get("company_name"):
            # 查找是否已存在该公司
            from backend.database.models import Client

            existing_client = (
                db.query(Client)
                .filter(
                    (Client.company_name == extracted_info["company_name"])
                    | (Client.name == extracted_info["company_name"])
                )
                .first()
            )

            if existing_client:
                # 更新现有客户信息
                if extracted_info.get("contact_person"):
                    existing_client.contact_person = extracted_info["contact_person"]
                if extracted_info.get("phone"):
                    existing_client.phone = extracted_info["phone"]
                if extracted_info.get("email"):
                    existing_client.email = extracted_info["email"]
                if extracted_info.get("industry"):
                    existing_client.industry = extracted_info["industry"]
                if extracted_info.get("address"):
                    existing_client.address = extracted_info["address"]
                if extracted_info.get("description"):
                    existing_client.description = extracted_info["description"]

                db.commit()
                client_data = {
                    "client_id": existing_client.id,
                    "name": existing_client.name,
                    "company_name": existing_client.company_name,
                }
                logger.info(f"已更新客户信息: {existing_client.name}")
            else:
                # 创建新客户
                new_client = Client(
                    name=extracted_info.get("company_name", "未知客户")[:200],
                    company_name=extracted_info.get("company_name"),
                    contact_person=extracted_info.get("contact_person"),
                    phone=extracted_info.get("phone"),
                    email=extracted_info.get("email"),
                    industry=extracted_info.get("industry"),
                    address=extracted_info.get("address"),
                    description=extracted_info.get("description"),
                    status=1,
                )
                db.add(new_client)
                db.commit()
                db.refresh(new_client)

                client_data = {
                    "client_id": new_client.id,
                    "name": new_client.name,
                    "company_name": new_client.company_name,
                }
                logger.info(f"已创建新客户: {new_client.name}")

        return ApiResponse(
            success=True,
            data={
                "extracted_info": extracted_info,
                "client": client_data if client_data else None,
            },
            message="信息提取成功"
            + (
                f"，已{'更新' if client_data.get('client_id') and existing_client else '创建'}客户记录"
                if client_data
                else ""
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"提取文档信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-info-from-text", response_model=ApiResponse)
async def extract_info_from_text(
    text: str,
    db: Session = Depends(get_db),
):
    """
    从文本中提取客户信息（直接文本输入）

    用于用户直接粘贴文本内容进行信息提取

    Args:
        text: 文本内容
        db: 数据库会话

    Returns:
        提取的客户信息
    """
    try:
        from backend.services.document_extractor import get_document_extractor

        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="文本内容不能为空")

        # 使用AI提取客户信息
        extractor = get_document_extractor()
        extracted_info = extractor.extract_from_text(text)

        if not extracted_info:
            return ApiResponse(
                success=False,
                data={},
                message="未能从文本中提取到客户信息",
            )

        return ApiResponse(
            success=True,
            data={"extracted_info": extracted_info},
            message="信息提取成功",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"从文本提取信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== RAGFlow 直接管理 API ====================


class RAGFlowDatasetCreate(BaseModel):
    """创建 RAGFlow 知识库请求"""
    name: str
    description: Optional[str] = None


class RAGFlowDatasetUpdate(BaseModel):
    """更新 RAGFlow 知识库请求"""
    name: Optional[str] = None
    description: Optional[str] = None


@router.get("/ragflow/status", response_model=ApiResponse)
async def get_ragflow_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取 RAGFlow 服务状态

    Returns:
        RAGFlow 连接状态和配置信息
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            return ApiResponse(
                success=False,
                data={
                    "connected": False,
                    "configured": False,
                    "message": "RAGFlow 未配置，请设置 RAGFLOW_API_KEY 和 RAGFLOW_BASE_URL"
                },
                message="RAGFlow 未配置"
            )

        # 测试连接
        result = ragflow_client.list_datasets()

        if result.get("code") == 0:
            datasets = result.get("data", [])
            if getattr(current_user, "role", None) != "admin":
                owned_ids = {
                    r[0]
                    for r in scoped_query(db, KnowledgeCategory, current_user)
                    .with_entities(KnowledgeCategory.ragflow_dataset_id)
                    .filter(KnowledgeCategory.ragflow_dataset_id.isnot(None))
                    .all()
                }
                datasets = [d for d in datasets if d.get("id") in owned_ids]
            return ApiResponse(
                success=True,
                data={
                    "connected": True,
                    "configured": True,
                    "base_url": ragflow_client.base_url,
                    "dataset_count": len(datasets),
                    # 不返回完整 datasets 列表，避免向普通用户泄露他人知识库信息
                },
                message=f"已连接到 RAGFlow，当前有 {len(datasets)} 个知识库"
            )
        else:
            return ApiResponse(
                success=False,
                data={
                    "connected": False,
                    "configured": True,
                    "message": result.get("message", "连接失败")
                },
                message="RAGFlow 连接失败"
            )

    except Exception as e:
        logger.error(f"检查 RAGFlow 状态失败: {e}")
        return ApiResponse(
            success=False,
            data={
                "connected": False,
                "error": str(e)
            },
            message=f"检查状态失败: {str(e)}"
        )


@router.get("/ragflow/datasets", response_model=ApiResponse)
async def list_ragflow_datasets(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    列出 RAGFlow 知识库（按当前用户隔离：普通用户只能看到自己名下分类对应的知识库；admin 看全部）

    Args:
        page: 页码
        limit: 每页数量
        search: 搜索名称

    Returns:
        知识库列表
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        # 调用 RAGFlow API
        result = ragflow_client.list_datasets(name=search)

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "获取知识库列表失败"))

        all_datasets = result.get("data", [])

        # 数据隔离：普通用户只能看到自己名下分类对应的知识库；admin 看全部
        if getattr(current_user, "role", None) != "admin":
            # 防御性检查：确保 current_user.id 有效
            if not getattr(current_user, "id", None):
                logger.warning(f"[知识库权限] user_id 无效，无法返回知识库列表: user={getattr(current_user, 'username', '?')}")
                all_datasets = []
            else:
                owned_ids = {
                    r[0]
                    for r in scoped_query(db, KnowledgeCategory, current_user)
                    .with_entities(KnowledgeCategory.ragflow_dataset_id)
                    .filter(KnowledgeCategory.ragflow_dataset_id.isnot(None))
                    .all()
                }
                logger.debug(f"[知识库权限] user={current_user.username}(id={current_user.id}) 可见的知识库IDs: {owned_ids}")
                all_datasets = [d for d in all_datasets if d.get("id") in owned_ids]

        # 分页
        total = len(all_datasets)
        start = (page - 1) * limit
        end = start + limit
        datasets = all_datasets[start:end]

        # 格式化输出 — 字段名对齐前端 RAGFlowDataset 接口
        formatted_datasets = []
        for ds in datasets:
            formatted_datasets.append({
                "id": ds.get("id"),
                "name": ds.get("name"),
                "description": ds.get("description", ""),
                "embedding_model": ds.get("embedding_model", ""),
                "chunk_count": ds.get("chunk_count", ds.get("chunk_num", 0)),
                "document_count": ds.get("document_count", ds.get("document_num", 0)),
                "created_at": ds.get("create_time", ds.get("create_date", "")),
                "updated_at": ds.get("update_time", ds.get("update_date", "")),
            })

        pages = (total + limit - 1) // limit if total > 0 else 1

        return ApiResponse(
            success=True,
            data={
                "items": formatted_datasets,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": pages,
                "has_next": page < pages,
                "has_prev": page > 1
            },
            message=f"获取到 {total} 个知识库"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出 RAGFlow 知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ragflow/datasets", response_model=ApiResponse)
async def create_ragflow_dataset(
    data: RAGFlowDatasetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    创建 RAGFlow 知识库（直接管理）

    同时在本地创建一条归属当前用户的 KnowledgeCategory 缓存记录，
    这样创建者才能在自己的知识库列表中看到并管理它（数据隔离）。

    Args:
        data: 知识库创建数据

    Returns:
        创建结果
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        # 创建知识库
        result = ragflow_client.create_dataset(name=data.name, description=data.description)

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "创建知识库失败"))

        dataset_info = result.get("data", {})
        dataset_id = dataset_info.get("id")

        # 同步建立归属当前用户的本地分类缓存，确保创建者可见且隔离
        if dataset_id:
            existing = (
                db.query(KnowledgeCategory)
                .filter(KnowledgeCategory.ragflow_dataset_id == str(dataset_id))
                .first()
            )
            if not existing:
                category = KnowledgeCategory(
                    ragflow_dataset_id=str(dataset_id),
                    name=data.name,
                    description=data.description,
                    sync_status="synced",
                    last_sync_at=datetime.now(),
                    user_id=current_user.id,
                )
                db.add(category)
                db.commit()

        return ApiResponse(
            success=True,
            data={
                "id": dataset_id,
                "name": data.name,
                "description": data.description,
                "embedding_model": dataset_info.get("embedding_model", "")
            },
            message=f"知识库 '{data.name}' 创建成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建 RAGFlow 知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ragflow/datasets/{dataset_id}", response_model=ApiResponse)
async def get_ragflow_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取 RAGFlow 知识库详情

    Args:
        dataset_id: 知识库 ID

    Returns:
        知识库详情
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        result = ragflow_client.get_dataset(dataset_id)

        if result.get("code") != 0:
            raise HTTPException(status_code=404, detail=result.get("message", "知识库不存在"))

        dataset = result.get("data", {})

        return ApiResponse(
            success=True,
            data={
                "id": dataset.get("id"),
                "name": dataset.get("name"),
                "description": dataset.get("description", ""),
                "embedding_model": dataset.get("embedding_model", ""),
                "chunk_count": dataset.get("chunk_count", dataset.get("chunk_num", 0)),
                "document_count": dataset.get("document_count", dataset.get("document_num", 0)),
                "created_at": dataset.get("create_time", dataset.get("create_date", "")),
                "updated_at": dataset.get("update_time", dataset.get("update_date", "")),
            },
            message="获取知识库详情成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 RAGFlow 知识库详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/ragflow/datasets/{dataset_id}", response_model=ApiResponse)
async def update_ragflow_dataset(
    dataset_id: str,
    data: RAGFlowDatasetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    更新 RAGFlow 知识库

    Args:
        dataset_id: 知识库 ID
        data: 更新数据

    Returns:
        更新结果
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        result = ragflow_client.update_dataset(dataset_id, name=data.name, description=data.description)

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "更新知识库失败"))

        return ApiResponse(
            success=True,
            data={"id": dataset_id, "name": data.name, "description": data.description},
            message="知识库更新成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新 RAGFlow 知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/ragflow/datasets/{dataset_id}", response_model=ApiResponse)
async def delete_ragflow_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除 RAGFlow 知识库

    Args:
        dataset_id: 知识库 ID

    Returns:
        删除结果
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        result = ragflow_client.delete_dataset(dataset_id)

        # RAGFlow 删除成功时可能返回空响应或无 code 字段
        if result.get("code") is not None and result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "删除知识库失败"))

        # 同步清理本地分类缓存（含其下知识条目），避免残留指向已删除知识库的记录
        cat = (
            db.query(KnowledgeCategory)
            .filter(KnowledgeCategory.ragflow_dataset_id == str(dataset_id))
            .first()
        )
        if cat:
            db.delete(cat)
            db.commit()

        return ApiResponse(
            success=True,
            data={"id": dataset_id},
            message="知识库删除成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除 RAGFlow 知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== RAGFlow 文档管理 API ====================


@router.get("/ragflow/datasets/{dataset_id}/documents", response_model=ApiResponse)
async def list_ragflow_documents(
    dataset_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    keywords: Optional[str] = None,
    run_status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    列出知识库中的文档

    Args:
        dataset_id: 知识库 ID
        page: 页码
        limit: 每页数量
        keywords: 搜索关键词
        run_status: 状态筛选 (DONE, RUNNING, FAIL, UNSTART)

    Returns:
        文档列表
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        # 构建查询参数
        params = {
            "page": page,
            "page_size": limit
        }
        if keywords:
            params["keywords"] = keywords
        if run_status:
            params["run"] = run_status

        result = ragflow_client.list_documents(dataset_id, **params)

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "获取文档列表失败"))

        # RAGFlow 返回格式: {code: 0, data: {docs: [], total: n}}
        # 兼容多种可能的字段名: docs / list / data
        data = result.get("data", {})
        all_docs = data.get("docs", data.get("list", data.get("data", []))) or []
        total = data.get("total", data.get("total_datasets", len(all_docs)))

        # 格式化输出 — 字段名对齐前端 RAGFlowDocument 接口
        formatted_docs = []
        for doc in all_docs:
            formatted_docs.append({
                "id": doc.get("id"),
                "name": doc.get("name"),
                "size": doc.get("size", 0),
                "type": doc.get("type", "unknown"),
                "run_status": doc.get("run", doc.get("status", "0")),
                "chunk_count": doc.get("chunk_count", 0),
                "chunk_method": doc.get("chunk_method", doc.get("parser_id", "naive")),
                "progress": doc.get("progress", 0),
                "progress_msg": doc.get("progress_msg", doc.get("message", "")),
                "created_at": doc.get("create_time", doc.get("create_date", "")),
                "updated_at": doc.get("update_time", doc.get("update_date", "")),
            })

        pages = (total + limit - 1) // limit if total > 0 else 1

        return ApiResponse(
            success=True,
            data={
                "items": formatted_docs,
                "total": total,
                "page": page,
                "limit": limit,
                "pages": pages,
                "has_next": page < pages,
                "has_prev": page > 1
            },
            message=f"获取到 {total} 个文档"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出 RAGFlow 文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ragflow/datasets/{dataset_id}/documents/{document_id}", response_model=ApiResponse)
async def get_ragflow_document(
    dataset_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取文档详情（包括预览信息）

    Args:
        dataset_id: 知识库 ID
        document_id: 文档 ID

    Returns:
        文档详情和预览 URL
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        result = ragflow_client.get_document(dataset_id, document_id)

        if result.get("code") != 0:
            raise HTTPException(status_code=404, detail=result.get("message", "文档不存在"))

        doc = result.get("data", {})

        return ApiResponse(
            success=True,
            data={
                "id": doc.get("id"),
                "name": doc.get("name"),
                "size": doc.get("size", 0),
                "type": doc.get("type", "unknown"),
                "run_status": doc.get("run", doc.get("status", "0")),
                "chunk_count": doc.get("chunk_count", 0),
                "chunk_method": doc.get("chunk_method", doc.get("parser_id", "naive")),
                "progress": doc.get("progress", 0),
                "progress_msg": doc.get("progress_msg", doc.get("message", "")),
                "created_at": doc.get("create_time", doc.get("create_date", "")),
                "updated_at": doc.get("update_time", doc.get("update_date", "")),
            },
            message="获取文档详情成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 RAGFlow 文档详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ragflow/datasets/{dataset_id}/documents/{document_id}/download", response_model=ApiResponse)
async def get_ragflow_document_download_url(
    dataset_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取文档下载 URL

    Args:
        dataset_id: 知识库 ID
        document_id: 文档 ID

    Returns:
        下载 URL
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        # 构建下载 URL
        base_url = ragflow_client.base_url
        download_url = f"{base_url}/api/v1/datasets/{dataset_id}/documents/{document_id}/download"

        return ApiResponse(
            success=True,
            data={
                "document_id": document_id,
                "download_url": download_url,
                "expires_in": 3600  # URL 有效期 1 小时
            },
            message="获取下载链接成功"
        )

    except Exception as e:
        logger.error(f"获取文档下载链接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/ragflow/datasets/{dataset_id}/documents/{document_id}", response_model=ApiResponse)
async def delete_ragflow_document(
    dataset_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    删除文档

    Args:
        dataset_id: 知识库 ID
        document_id: 文档 ID

    Returns:
        删除结果
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        result = ragflow_client.delete_document(dataset_id, document_id)

        # RAGFlow 删除成功时可能返回 code=0 或空响应，只要没有抛出异常就算成功
        if result.get("code") is not None and result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "删除文档失败"))

        return ApiResponse(
            success=True,
            data={"id": document_id},
            message="文档删除成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除 RAGFlow 文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ragflow/datasets/{dataset_id}/documents/{document_id}/parse", response_model=ApiResponse)
async def parse_ragflow_document(
    dataset_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    触发文档解析（重新分块）

    Args:
        dataset_id: 知识库 ID
        document_id: 文档 ID

    Returns:
        解析结果
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        result = ragflow_client.parse_documents(dataset_id, [document_id])

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "解析文档失败"))

        return ApiResponse(
            success=True,
            data={"document_id": document_id, "status": "parsing"},
            message="文档解析已触发"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解析 RAGFlow 文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ragflow/datasets/{dataset_id}/documents", response_model=ApiResponse)
async def upload_ragflow_document(
    dataset_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    auto_parse: Optional[str] = Form("true"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    上传文件到知识库

    Args:
        dataset_id: 知识库 ID
        file: 上传的文件
        title: 自定义标题（可选）
        auto_parse: 是否自动触发解析 (true/false, 默认true)
        db: 数据库会话

    Returns:
        上传结果
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        # 读取文件内容 (限制50MB防止内存溢出)
        file_content = await file.read()
        if len(file_content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件大小超过50MB限制")

        file_name = title or file.filename

        # 上传到 RAGFlow
        do_parse = auto_parse.lower() != "false"
        result = ragflow_client.upload_document_bytes(
            dataset_id=dataset_id,
            file_content=file_content,
            file_name=file_name,
            do_parse=do_parse
        )

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "上传文件失败"))

        docs = result.get("data", [])
        if not docs:
            raise HTTPException(status_code=500, detail="上传成功但未返回文档信息")

        doc_info = docs[0]

        return ApiResponse(
            success=True,
            data={
                "id": doc_info.get("id"),
                "name": doc_info.get("name"),
                "status": doc_info.get("run", "UNSTART")
            },
            message=f"文件 '{file_name}' 上传成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"上传 RAGFlow 文档失败: {error_msg}")
        # 区分不同类型的错误
        if "Connection" in error_msg or "connect" in error_msg.lower():
            raise HTTPException(status_code=503, detail=f"RAGFlow 服务不可达: {error_msg}")
        elif "timeout" in error_msg.lower():
            raise HTTPException(status_code=504, detail=f"RAGFlow 响应超时: {error_msg}")
        else:
            raise HTTPException(status_code=500, detail=error_msg)


@router.get("/ragflow/datasets/{dataset_id}/chunks", response_model=ApiResponse)
async def get_ragflow_chunks(
    dataset_id: str,
    document_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取知识库的文档块

    Args:
        dataset_id: 知识库 ID
        document_id: 可选，筛选特定文档
        page: 页码
        limit: 每页数量

    Returns:
        文档块列表
    """
    _require_dataset_owner(db, dataset_id, current_user)
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        # RAGFlow chunks API 端点
        url = f"{ragflow_client.base_url}/api/v1/datasets/{dataset_id}/chunks"
        params = {"page": page, "page_size": limit}
        if document_id:
            params["document_id"] = document_id

        resp = ragflow_client.session.get(url, params=params, timeout=ragflow_client.timeout)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise HTTPException(status_code=500, detail=result.get("message", "获取文档块失败"))

        data = result.get("data", {})
        chunks = data.get("chunks", []) or data.get("list", [])
        total = data.get("total", len(chunks))

        # 格式化
        formatted_chunks = []
        for chunk in chunks:
            formatted_chunks.append({
                "id": chunk.get("id"),
                "content": chunk.get("content", ""),
                "document_id": chunk.get("document_id"),
                "document_name": chunk.get("document_name", ""),
                "similarity": chunk.get("similarity"),
                "vector_similarity": chunk.get("vector_similarity"),
                "term_similarity": chunk.get("term_similarity")
            })

        return ApiResponse(
            success=True,
            data={
                "items": formatted_chunks,
                "total": total,
                "page": page,
                "limit": limit
            },
            message=f"获取到 {total} 个文档块"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 RAGFlow 文档块失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ragflow/documents/{document_id}/status", response_model=ApiResponse)
async def get_document_parsing_status(
    dataset_id: str = Query(..., description="知识库ID"),
    document_id: str = Path(..., description="文档ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    获取文档解析状态

    支持轮询查询文档是否解析完成。可用于上传后检查 PDF 等文件的解析进度。

    返回状态:
    - unstart: 未开始
    - running: 解析中
    - done: 解析完成（可用于检索）
    - fail: 解析失败
    - unknown: 未知
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        status = ragflow_client.get_document_parsing_status(dataset_id, document_id)

        return ApiResponse(
            success=True,
            data=status,
            message=status.get("message", f"文档状态: {status.get('status')}")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档解析状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ragflow/datasets/{dataset_id}/documents/status", response_model=ApiResponse)
async def get_documents_parsing_status(
    dataset_id: str,
    document_ids: str = Query(..., description="文档ID列表，逗号分隔"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    批量获取文档解析状态

    Args:
        dataset_id: 知识库ID
        document_ids: 文档ID列表，逗号分隔

    Returns:
        {
            "total": 总数,
            "done": 已完成,
            "running": 解析中,
            "failed": 失败,
            "unstart": 未开始,
            "is_ready": 全部就绪,
            "documents": [...]  # 每个文档详情
        }
    """
    from backend.services.ragflow_client import get_ragflow_client

    try:
        ragflow_client = get_ragflow_client()

        if not ragflow_client.is_configured():
            raise HTTPException(status_code=400, detail="RAGFlow 未配置")

        doc_ids = [d.strip() for d in document_ids.split(",") if d.strip()]
        if not doc_ids:
            raise HTTPException(status_code=400, detail="请提供有效的文档ID")

        status = ragflow_client.get_documents_parsing_status(dataset_id, doc_ids)

        return ApiResponse(
            success=True,
            data=status,
            message=f"共 {status['total']} 个文档，{status['done']} 个已完成，{status['failed']} 个失败"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量获取文档解析状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
