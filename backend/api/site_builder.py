import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.user import get_current_user_from_token
from backend.database import get_db
from backend.database.models import SiteProject, User
from backend.middleware.user_isolation import require_owner
from backend.services.deploy_service import DeployError, DeployService
from backend.services.site_generator import SiteGeneratorService
from backend.services.webpage_generator import WebPageGeneratorService
from backend.database.models import Client, KnowledgeCategory

router = APIRouter(prefix="/sites", tags=["Site Builder"])
generator = SiteGeneratorService()
deployer = DeployService()
ai_generator = WebPageGeneratorService()


# 1. 构建请求模型
class SiteBuildRequest(BaseModel):
    name: str
    config: dict
    template_id: str = "corporate"


# 2. 部署请求模型
class DeployRequest(BaseModel):
    site_id: str
    project_name: str
    method: str

    sftp_host: Optional[str] = None
    sftp_port: Optional[int] = 22
    sftp_user: Optional[str] = None
    sftp_auth_type: Optional[str] = "password"
    sftp_pass: Optional[str] = None
    sftp_private_key: Optional[str] = None
    sftp_key_passphrase: Optional[str] = None
    sftp_path: Optional[str] = "/var/www/html"

    # 访问域名（新优先字段，custom_domain 保留作向后兼容兜底）
    public_base_url: Optional[str] = None
    custom_domain: Optional[str] = None
    # 可选：自定义发布目录名；留空走自动 项目slug-site_id[:8]
    publish_slug: Optional[str] = None

    s3_endpoint: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None


def _validate_public_base_url(value: Optional[str]) -> None:
    """public_base_url 必须以 http:// 或 https:// 开头。"""
    if value and not value.lower().startswith(("http://", "https://")):
        raise DeployError(
            code="INVALID_PUBLIC_BASE_URL",
            message="访问域名必须以 http:// 或 https:// 开头。",
            suggestion="例如 https://www.example.com",
            status=400,
        )


def _validate_sftp(req: DeployRequest) -> None:
    missing = []
    auth_type = req.sftp_auth_type or ("private_key" if req.sftp_private_key else "password")
    if not req.sftp_host:
        missing.append("主机 IP")
    if not req.sftp_user:
        missing.append("用户名")
    if auth_type == "private_key":
        if not req.sftp_private_key:
            missing.append("PEM 私钥")
    elif auth_type == "password":
        if not req.sftp_pass:
            missing.append("密码")
    else:
        raise DeployError(
            code="INVALID_SFTP_AUTH_TYPE",
            message="SFTP 认证方式无效。",
            suggestion="请选择密码或 PEM 私钥。",
            status=400,
        )
    if not req.sftp_path:
        missing.append("上传路径")
    if missing:
        raise DeployError(
            code="DEPLOY_PARAM_MISSING",
            message="SFTP 发布配置不完整：" + "、".join(missing) + "。",
            suggestion="请补全 SFTP 必填字段。",
            status=400,
        )
    if not req.sftp_path.startswith("/"):
        raise DeployError(
            code="INVALID_SFTP_PATH",
            message="上传路径必须是绝对路径。",
            suggestion="例如 /var/www/html",
            status=400,
        )
    _validate_public_base_url(req.public_base_url)
    _validate_public_base_url(req.custom_domain)


def _validate_s3(req: DeployRequest) -> None:
    missing = []
    if not req.s3_endpoint:
        missing.append("Endpoint")
    if not req.s3_bucket:
        missing.append("Bucket")
    if not req.s3_access_key:
        missing.append("AccessKey")
    if not req.s3_secret_key:
        missing.append("SecretKey")
    if missing:
        raise DeployError(
            code="DEPLOY_PARAM_MISSING",
            message="OSS/S3 发布配置不完整：" + "、".join(missing) + "。",
            suggestion="请补全 OSS/S3 必填字段。",
            status=400,
        )
    _validate_public_base_url(req.public_base_url)


@router.post("/build")
def build_new_site(
    req: SiteBuildRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    # 按 (当前用户, 项目名) 复用 SiteProject：同名复用 site_id（覆盖同一静态目录，
    # 防 debounce 频繁触发导致记录膨胀），异名新建。user_id 由 auto_user_id 事件自动填。
    proj = (
        db.query(SiteProject)
        .filter(
            SiteProject.user_id == current_user.id,
            SiteProject.name == req.name,
        )
        .first()
    )
    is_new = proj is None
    if is_new:
        proj = SiteProject(name=req.name, site_id=uuid.uuid4().hex)
        db.add(proj)

    logger.info(
        f"[SiteBuilder] 构建站点: name={req.name} template={req.template_id} "
        f"site_id={proj.site_id} 新建={is_new} user={current_user.username}"
    )
    try:
        result = generator.generate_site(proj.site_id, req.config, req.template_id)
    except HTTPException:
        logger.error(f"[SiteBuilder] 站点构建失败: name={req.name} site_id={proj.site_id} user={current_user.username}")
        raise
    proj.config_data = req.config
    proj.preview_url = result["preview_url"]
    proj.deploy_path = result["local_path"]
    db.commit()

    result["site_id"] = proj.site_id
    logger.success(
        f"[SiteBuilder] 站点构建成功: name={req.name} site_id={proj.site_id} "
        f"preview={result['preview_url']} user={current_user.username}"
    )
    return {"code": 200, "data": result}


@router.post("/deploy")
def deploy_site(
    req: DeployRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    try:
        # 按 site_id 校验归属：普通用户只能发布自己 build 的站点；admin 放行
        proj = db.query(SiteProject).filter(SiteProject.site_id == req.site_id).first()
        if not proj:
            logger.warning(f"[SiteBuilder] 部署被拒绝：站点不存在 site_id={req.site_id} user={current_user.username}")
            raise DeployError(
                code="SITE_NOT_FOUND",
                message="站点不存在或已失效。",
                suggestion="请重新生成预览后再发布。",
                status=404,
            )
        require_owner(proj, current_user, name="站点")

        # 敏感信息（密码/密钥）绝不写入日志
        logger.info(
            f"[SiteBuilder] 开始部署: site_id={req.site_id} method={req.method} "
            f"project={req.project_name} domain={req.public_base_url or req.custom_domain} "
            f"user={current_user.username}"
        )
        if req.method == "sftp":
            _validate_sftp(req)
            result = deployer.deploy_sftp(
                site_id=req.site_id,
                project_name=req.project_name,
                host=req.sftp_host,
                port=req.sftp_port,
                username=req.sftp_user,
                auth_type=req.sftp_auth_type,
                password=req.sftp_pass,
                private_key=req.sftp_private_key,
                key_passphrase=req.sftp_key_passphrase,
                remote_root=req.sftp_path,
                custom_domain=req.custom_domain,
                public_base_url=req.public_base_url,
                publish_slug=req.publish_slug or "",
            )
        elif req.method == "s3":
            _validate_s3(req)
            result = deployer.deploy_s3(
                site_id=req.site_id,
                endpoint=req.s3_endpoint,
                bucket=req.s3_bucket,
                access_key=req.s3_access_key,
                secret_key=req.s3_secret_key,
                public_base_url=req.public_base_url,
            )
        else:
            logger.warning(f"[SiteBuilder] 部署被拒绝：不支持的发布方式 method={req.method} site_id={req.site_id}")
            raise DeployError(
                code="UNKNOWN_DEPLOY_METHOD",
                message=f"不支持的发布方式：{req.method}",
                suggestion="请选择 sftp 或 s3。",
                status=400,
            )

        logger.success(
            f"[SiteBuilder] 部署成功: site_id={req.site_id} method={req.method} "
            f"url={result.get('public_url') or result.get('url', '')} user={current_user.username}"
        )
        return {"code": 200, "data": result}

    except DeployError as e:
        logger.error(
            f"[SiteBuilder] 部署失败: site_id={req.site_id} method={req.method} "
            f"code={e.code} message={e.message} user={current_user.username}"
        )
        # 结构化错误：detail 是 {code, message, suggestion}，前端按对象解包
        raise HTTPException(
            status_code=e.status,
            detail={
                "code": e.code,
                "message": e.message,
                "suggestion": e.suggestion,
            },
        )


# ==================== AI 网页生成接口 ====================


class AIGenerateRequest(BaseModel):
    """AI 一键生成网页请求。"""

    client_id: int
    template_id: str = "visual"
    extra_instructions: str = ""


class AIRegenerateRequest(BaseModel):
    """用已有结构化数据重新渲染（换模板/微调字段）。不调 AI，纯渲染。"""

    site_id: str
    structured_data: dict
    template_id: str = "visual"


@router.get("/ai-templates")
def list_ai_templates():
    """列出可用的 AI 网页模板。"""
    return {"code": 200, "data": ai_generator.list_templates()}


@router.post("/ai-generate")
async def ai_generate_site(
    req: AIGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """AI 一键生成：从客户知识库检索 → DeepSeek 提取 → 模板渲染。"""
    # 1. 查客户
    client = db.query(Client).filter(Client.id == req.client_id).first()
    if not client:
        logger.warning(f"[SiteBuilder] AI生成被拒绝：客户不存在 client_id={req.client_id} user={current_user.username}")
        raise HTTPException(status_code=404, detail="客户不存在")
    require_owner(client, current_user, name="客户")

    # 2. 找到客户关联的 RAGFlow 知识库
    category = (
        db.query(KnowledgeCategory)
        .filter(KnowledgeCategory.client_id == req.client_id, KnowledgeCategory.status == 1)
        .first()
    )
    if not category or not category.ragflow_dataset_id:
        logger.warning(
            f"[SiteBuilder] AI生成被拒绝：客户未关联知识库 client_id={req.client_id} user={current_user.username}"
        )
        raise HTTPException(
            status_code=400,
            detail="该客户还没有关联知识库，请先上传企业资料后再生成网页",
        )

    company_name = client.company_name or client.name

    logger.info(
        f"[SiteBuilder] AI生成网页开始: client_id={req.client_id} company={company_name} "
        f"template={req.template_id} user={current_user.username}"
    )

    # 3. 生成 site_id（按客户名复用，避免重复记录膨胀）
    existing = (
        db.query(SiteProject)
        .filter(
            SiteProject.user_id == current_user.id,
            SiteProject.client_id == req.client_id,
            SiteProject.source == "ai",
        )
        .first()
    )
    site_id = existing.site_id if existing else uuid.uuid4().hex

    try:
        result = await ai_generator.generate(
            company_name=company_name,
            dataset_id=category.ragflow_dataset_id,
            template_id=req.template_id,
            extra_instructions=req.extra_instructions,
            site_id=site_id,
        )
    except RuntimeError as e:
        logger.error(f"[SiteBuilder] AI生成网页失败: client_id={req.client_id} site_id={site_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

    # 4. 写入/更新 SiteProject 记录
    if existing:
        existing.structured_data = result["structured_data"]
        existing.template_id = req.template_id
        existing.preview_url = result["preview_url"]
        existing.config_data = result["structured_data"]
    else:
        proj = SiteProject(
            name=company_name,
            site_id=site_id,
            user_id=current_user.id,
            client_id=req.client_id,
            source="ai",
            template_id=req.template_id,
            structured_data=result["structured_data"],
            config_data=result["structured_data"],
            preview_url=result["preview_url"],
            deploy_path=f"/static/sites/{site_id}/index.html",
        )
        db.add(proj)

    db.commit()

    logger.success(
        f"[SiteBuilder] AI网页生成成功: client_id={req.client_id} site_id={site_id} "
        f"preview={result['preview_url']} 新建={existing is None} user={current_user.username}"
    )
    return {"code": 200, "data": result}


@router.post("/ai-regenerate")
async def ai_regenerate_site(
    req: AIRegenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """用已有结构化数据重新渲染（换模板/微调字段）。不调 AI。"""
    proj = db.query(SiteProject).filter(SiteProject.site_id == req.site_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="站点不存在")
    require_owner(proj, current_user, name="站点")

    result = await ai_generator.regenerate(
        site_id=req.site_id,
        structured_data=req.structured_data,
        template_id=req.template_id,
    )

    # 更新记录
    proj.structured_data = req.structured_data
    proj.template_id = req.template_id
    proj.preview_url = result["preview_url"]
    proj.config_data = req.structured_data
    db.commit()

    logger.success(
        f"[SiteBuilder] AI网页重新渲染成功: site_id={req.site_id} template={req.template_id} "
        f"preview={result['preview_url']} user={current_user.username}"
    )
    return {"code": 200, "data": result}
