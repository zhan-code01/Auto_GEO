# -*- coding: utf-8 -*-
"""
关键词管理API - 兼容性增强版
解决了收录监控页关键词不显示的问题
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import Project, Keyword, QuestionVariant, User
from backend.services.keyword_service import KeywordService
from backend.schemas import ApiResponse
from backend.api.user import get_current_user_from_token
from backend.middleware.user_isolation import scoped_query, require_owner
from loguru import logger

router = APIRouter(prefix="/api/keywords", tags=["关键词管理"])


def _get_owned_project(db: Session, project_id: int, current_user: User) -> Project:
    """获取项目并校验归属（不存在→404；不属于当前用户→403；admin 放行）。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_owner(project, current_user, name="项目")
    return project


def _get_owned_keyword(db: Session, keyword_id: int, current_user: User) -> Keyword:
    """获取关键词并校验其所属项目的归属。"""
    kw = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="关键词不存在")
    if kw.project_id:
        project = db.query(Project).filter(Project.id == kw.project_id).first()
        if project:
            require_owner(project, current_user, name="关键词所属项目")
    return kw


# ==================== 请求/响应模型 ====================


class ProjectCreate(BaseModel):
    """创建项目请求"""

    client_id: Optional[int] = None
    name: str
    company_name: str
    domain_keyword: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None


def _required_project_text(value: Optional[str], label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"缺少必要字段: {label}")
    return text


class ProjectResponse(BaseModel):
    """项目响应"""

    id: int
    client_id: Optional[int] = None
    name: str
    company_name: Optional[str] = None  # 数据库允许为NULL
    domain_keyword: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    status: int = 1
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KeywordCreate(BaseModel):
    """创建关键词请求"""

    project_id: int
    keyword: str
    difficulty_score: Optional[int] = None


class KeywordResponse(BaseModel):
    """关键词响应"""

    id: int
    project_id: int
    keyword: str
    difficulty_score: Optional[int] = None
    status: Optional[str] = None  # 🌟 允许为 None
    keyword_type: Optional[str] = None  # keyword / question

    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QuestionVariantResponse(BaseModel):
    """问题变体响应"""

    id: int
    keyword_id: int
    question: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DistillRequest(BaseModel):
    """关键词蒸馏请求"""

    project_id: int
    # 通用版入参（对齐关键词蒸馏通用版）
    core_kw: Optional[str] = None
    target_info: Optional[str] = None
    prefixes: Optional[str] = None
    suffixes: Optional[str] = None

    # 旧版兼容字段（前端历史版本仍可能发送）
    company_name: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    count: int = 10

    # 直接传入关键词列表（跳过生成步骤，仅做分类评分）
    # 对齐旧版 KeywordDistillRequest.keywords
    keywords: Optional[List[str]] = None


class GenerateQuestionsRequest(BaseModel):
    """生成问题变体请求"""

    keyword_id: int
    count: int = 3


# ==================== 项目API ====================


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取活跃项目列表（按当前用户隔离）"""
    projects = (
        scoped_query(db, Project, current_user)
        .filter(Project.status != 0)
        .order_by(Project.created_at.desc())
        .all()
    )
    return projects


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Get one project owned by the current user."""
    return _get_owned_project(db, project_id, current_user)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """创建项目（自动绑定当前用户 user_id）"""
    name = _required_project_text(project_data.name, "name")
    company_name = _required_project_text(project_data.company_name, "company_name")
    domain_keyword = _required_project_text(project_data.domain_keyword, "domain_keyword")
    project = Project(
        client_id=project_data.client_id,
        name=name,
        company_name=company_name,
        domain_keyword=domain_keyword,
        description=project_data.description,
        industry=(project_data.industry or "").strip() or None,
        status=1,
        user_id=current_user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info(f"项目已创建: {project.name} (user_id={current_user.id})")
    return project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """更新项目"""
    project = _get_owned_project(db, project_id, current_user)
    name = _required_project_text(project_data.name, "name")
    company_name = _required_project_text(project_data.company_name, "company_name")
    domain_keyword = _required_project_text(project_data.domain_keyword, "domain_keyword")

    project.client_id = project_data.client_id
    project.name = name
    project.company_name = company_name
    project.domain_keyword = domain_keyword
    project.description = project_data.description
    project.industry = (project_data.industry or "").strip() or None

    db.commit()
    db.refresh(project)
    logger.info(f"项目已更新: {project.name}")
    return project


@router.delete("/projects/{project_id}", response_model=ApiResponse)
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """删除项目（物理删除，级联删除关联关键词）"""
    project = _get_owned_project(db, project_id, current_user)

    db.delete(project)  # 物理删除，关联的关键词会自动级联删除
    db.commit()
    logger.info(f"项目已物理删除: {project.name}")
    return ApiResponse(success=True, message="项目已删除")


@router.get("/projects/{project_id}/keywords", response_model=List[KeywordResponse])
async def get_project_keywords(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    🌟 [修复核心] 获取项目的所有关键词
    移除了严格的 status == "active" 过滤，确保所有导入的词都能显示
    """
    _get_owned_project(db, project_id, current_user)  # 校验项目归属

    keywords = db.query(Keyword).filter(Keyword.project_id == project_id).order_by(Keyword.created_at.desc()).all()

    logger.info(f"查询项目 {project_id} 的关键词，找到 {len(keywords)} 个结果")
    return keywords


# ==================== 关键词业务API ====================


@router.post("/distill", response_model=ApiResponse)
async def distill_keywords(
    request: DistillRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """蒸馏关键词 - 支持新版数据结构（相近关键词、核心变体、高转化短语）"""
    project = _get_owned_project(db, request.project_id, current_user)

    service = KeywordService(db)

    # 参数映射：优先使用通用版字段；否则从项目/旧字段推导
    core_kw = (request.core_kw or "").strip() or (project.domain_keyword or "").strip()
    target_info = (
        (request.target_info or "").strip()
        or (request.company_name or "").strip()
        or (project.company_name or "").strip()
    )

    logger.info(f"蒸馏请求: core_kw={core_kw}, target_info={target_info}, project={project.name}")

    result = await service.distill_and_persist(
        project_id=request.project_id,
        core_kw=core_kw,
        target_info=target_info,
        prefixes=(request.prefixes or "").strip(),
        suffixes=(request.suffixes or "").strip(),
        company_name=(request.company_name or "").strip(),
        industry=(request.industry or "").strip(),
        description=(request.description or "").strip(),
        count=request.count,
    )

    if result.get("status") == "error":
        logger.error(f"蒸馏失败: {result.get('message')}")
        return ApiResponse(success=False, message=result.get("message", "蒸馏失败"))

    # 构建响应数据 - 支持新旧两种格式
    # keywords 保持只含核心关键词，conversion_phrases 单独渲染；
    # questions 已通过 saved_phrases 入库，右侧面板 refresh 后可看到
    response_data = {
        "keywords": result.get("keywords", []),
        "similar_keywords": result.get("similar_keywords", []),
        "variants": result.get("variants", []),
        "conversion_phrases": result.get("conversion_phrases", []),
    }

    # 透传搜索问题生成错误，方便前端展示
    question_error = result.get("question_error")
    if question_error:
        response_data["question_error"] = question_error

    # 透传原始响应用于前端调试兜底
    if result.get("raw_response"):
        response_data["raw_response"] = result.get("raw_response")

    saved_keywords = result.get("keywords", [])
    similar_keywords = result.get("similar_keywords", [])
    conversion_phrases = result.get("conversion_phrases", [])
    saved_phrases = result.get("saved_phrases", [])
    total_count = len(saved_keywords) + len(similar_keywords) + len(conversion_phrases)
    logger.info(
        f"蒸馏完成: {len(saved_keywords)} 核心词, {len(similar_keywords)} 相近词, "
        f"{len(conversion_phrases)} 转化短语(已入库{len(saved_phrases)}条)"
    )

    msg = f"蒸馏完成！生成 {len(saved_keywords)} 个核心词、{len(conversion_phrases)} 个搜索问题"
    if question_error:
        msg += f"\n（搜索问题生成失败: {question_error}）"

    return ApiResponse(
        success=True,
        message=msg,
        data=response_data
    )


@router.post("/generate-questions", response_model=ApiResponse)
async def generate_questions(
    request: GenerateQuestionsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """生成问题变体"""
    keyword = _get_owned_keyword(db, request.keyword_id, current_user)

    service = KeywordService(db)
    questions = await service.generate_questions(keyword=keyword.keyword, count=request.count)

    saved_questions = []
    for question in questions:
        qv = service.add_question_variant(keyword_id=request.keyword_id, question=question)
        saved_questions.append({"id": qv.id, "question": qv.question})

    return ApiResponse(success=True, message="生成完成", data={"questions": saved_questions})


@router.get("/keywords/{keyword_id}/questions")
async def get_keyword_questions(
    keyword_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """获取关键词的问题变体列表"""
    _get_owned_keyword(db, keyword_id, current_user)

    questions = db.query(QuestionVariant).filter(QuestionVariant.keyword_id == keyword_id).order_by(QuestionVariant.id).all()
    return [
        {"id": q.id, "keyword_id": q.keyword_id, "question": q.question, "created_at": q.created_at.isoformat() if q.created_at else None}
        for q in questions
    ]


@router.get("/{keyword_id}/questions")
async def get_keyword_questions_compat(
    keyword_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """Compatibility alias for older frontend calls."""
    return await get_keyword_questions(keyword_id, db, current_user)


@router.post("/projects/{project_id}/keywords", response_model=KeywordResponse, status_code=201)
async def create_keyword(
    project_id: int,
    keyword_data: KeywordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """手动创建关键词"""
    _get_owned_project(db, project_id, current_user)
    keyword = Keyword(
        project_id=project_id,
        keyword=keyword_data.keyword,
        difficulty_score=keyword_data.difficulty_score,
        status="active",
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return keyword


@router.delete("/{keyword_id}", response_model=ApiResponse)
async def delete_keyword(
    keyword_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """删除单个关键词"""

    # 🌟 路由说明: router prefix 已含 /api/keywords，此处仅需 /{keyword_id}
    # 完整路径: DELETE /api/keywords/{keyword_id}
    keyword = _get_owned_keyword(db, keyword_id, current_user)
    db.delete(keyword)
    db.commit()
    return ApiResponse(success=True, message="关键词已物理删除")


@router.delete("/projects/{project_id}/keywords", response_model=ApiResponse)
async def delete_all_keywords(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """一键删除项目下的所有关键词（物理删除）"""
    _get_owned_project(db, project_id, current_user)

    deleted_count = db.query(Keyword).filter(Keyword.project_id == project_id).delete()
    db.commit()
    logger.info(f"项目 {project_id} 下已删除 {deleted_count} 个关键词")
    return ApiResponse(success=True, message=f"已删除 {deleted_count} 个关键词")
