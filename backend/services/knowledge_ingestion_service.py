# -*- coding: utf-8 -*-
"""知识入库服务（方案 §6.7 / §9.3，阶段4）。

把 ``POST /api/knowledge/upload`` 里原本内联的 RAGFlow 入库逻辑抽成 service，供
**API 与 Agent Tool 共用**，避免各写一套。文档 §6.7 明确要求：

    /api/knowledge/upload  -> KnowledgeIngestionService.upload_files
    Agent Tool upload_files_to_knowledge_base -> KnowledgeIngestionService.upload_files

入库闭环：校验客户归属 → 找/建客户级 KnowledgeCategory(dataset) → 上传文件到
RAGFlow → 触发解析 → 写本地 Knowledge 记录 →（可选）抽取基础客户信息。

设计约定：
- 资料库按 **公司/客户** 维度建立（一个公司一个 dataset），tag 固定为
  ``source=client_upload,client_id={id}``，与 ``GeoKnowledgeService.resolve_dataset_ids``
  的检索路径严格对齐 —— 这样文章生成时能自动检索到本批资料。
- ``project_id / scope_type`` 当前记录到 Knowledge 内容里用于追溯；V1 不为项目维度
  另建 dataset（避免破坏既有检索）。多公司时由调用方（API/Agent/前端）强制选择 client_id。
- RAGFlow 未配置或上传失败：该文件计入 failed，但**不抛异常、不阻断**后续/文章生成。
"""

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.models import Client, Knowledge, KnowledgeCategory, User
from backend.middleware.user_isolation import require_owner, scoped_query
from backend.services.geo_knowledge_service import CLIENT_UPLOAD_TAG_PREFIX


# ==================== 常量 ====================

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
MAX_FILES = 5
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
LOCAL_TEXT_CACHE_CHARS = 12000
CATEGORY_LABELS = {
    "company": "公司资料",
    "product": "产品文档",
    "industry": "行业报告",
    "technical": "技术文档",
    "other": "其他",
}


def _extract_ragflow_id(result: dict) -> Optional[str]:
    """兼容 RAGFlow 不同版本的 dataset id 返回格式。"""
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


def _client_tags(client_id: int) -> str:
    return f"{CLIENT_UPLOAD_TAG_PREFIX}{client_id}"


def _safe_filename(name: Optional[str]) -> str:
    return os.path.basename(name or "unknown") or "unknown"


def _build_knowledge_content(
    *,
    client_id: int,
    category: str,
    category_label: str,
    scope_type: str,
    project_id: Optional[int],
    description: Optional[str],
    file_name: str,
    extracted_text: str,
) -> str:
    meta = (
        f"client_id={client_id}; category={category}; "
        f"category_label={category_label}; scope={scope_type}; "
        f"project_id={project_id or ''}; description={description or ''}; file={file_name}"
    )
    text = (extracted_text or "").strip()
    if not text:
        return meta
    if len(text) > LOCAL_TEXT_CACHE_CHARS:
        text = f"{text[:LOCAL_TEXT_CACHE_CHARS]}\n\n[本地解析文本已截断，完整原文见 RAGFlow 文档]"
    return f"{meta}\n\n--- parsed_text ---\n{text}"


# 电话：手机号或带区号/分机的座机（允许 +、空格、连字符、括号），去掉分隔符后需为 7~15 位数字。
_PHONE_STRIP = re.compile(r"[\s\-()+]")
_PHONE_RE = re.compile(r"^\d{7,15}$")
# 邮箱：宽松校验（含 @ 且本地域非空），避免误杀合法地址；严格格式以业务正则为准。
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PLACEHOLDER_VALUES = {
    "公司",
    "公司名称",
    "企业名称",
    "客户名称",
    "联系人",
    "联系人姓名",
    "联系电话",
    "电话",
    "手机号",
    "手机",
    "邮箱",
    "邮箱地址",
    "行业",
    "所属行业",
    "地址",
    "公司地址",
    "描述",
    "公司简介",
    "无",
    "暂无",
    "未填写",
    "未提供",
    "不详",
    "未知",
    "null",
    "none",
}


def _is_valid_phone(value: str) -> bool:
    digits = _PHONE_STRIP.sub("", value or "")
    return bool(_PHONE_RE.match(digits))


def _is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


def _is_placeholder_value(value: str) -> bool:
    text = str(value or "").strip(" \t\r\n：:，,；;")
    if not text:
        return True
    compact = re.sub(r"\s+", "", text).lower()
    return compact in {item.lower() for item in _PLACEHOLDER_VALUES}


def _is_valid_basic_info_value(field: str, value: str) -> bool:
    if _is_placeholder_value(value):
        return False
    if field == "contact_person":
        if any(label in value for label in ("电话", "邮箱", "地址", "行业", "公司", "联系人")):
            return False
        if re.search(r"\d|@|www\.|https?://", value, re.IGNORECASE):
            return False
    return True


def _sanitize_basic_info(info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(info, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for field, raw in info.items():
        if raw is None:
            continue
        value = "、".join(str(item).strip() for item in raw if str(item).strip()) if isinstance(raw, list) else str(raw).strip()
        if not value or not _is_valid_basic_info_value(field, value):
            continue
        cleaned[field] = value
    return cleaned


# ==================== 服务类 ====================


class KnowledgeIngestionService:
    """统一的客户资料 → RAGFlow 入库服务。"""

    def __init__(self, db: Session):
        self.db = db

    # ---------- 客户归属 ----------

    def _get_owned_client(self, user: User, client_id: int) -> Client:
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError("客户不存在")
        require_owner(client, user, name="客户")
        return client

    # ---------- dataset 准备 ----------

    def ensure_client_dataset(self, user: User, client_id: int) -> KnowledgeCategory:
        """为客户确保一个 KnowledgeCategory + RAGFlow dataset（与既有检索路径对齐）。

        RAGFlow 未配置或创建失败时：仍返回本地 category，但 ``ragflow_dataset_id`` 可能为
        None，调用方据此判断是否可上传。
        """
        from backend.services.ragflow_client import get_ragflow_client

        client = self._get_owned_client(user, client_id)
        tags = _client_tags(client.id)
        display_name = client.company_name or client.name
        dataset_name = f"{display_name}-客户知识库"[:200]

        cat = (
            scoped_query(self.db, KnowledgeCategory, user)
            .filter(
                KnowledgeCategory.status == 1,
                or_(
                    KnowledgeCategory.client_id == client.id,
                    KnowledgeCategory.tags == tags,
                    KnowledgeCategory.tags.contains(tags),
                ),
            )
            .first()
        )

        ragflow_client = get_ragflow_client()
        ragflow_ok = ragflow_client.is_configured()

        if cat is None:
            cat = KnowledgeCategory(
                name=dataset_name,
                industry=client.industry,
                description=f"{display_name} 客户资料知识库",
                tags=tags,
                status=1,
                user_id=user.id,
                client_id=client.id,
            )
            self.db.add(cat)
            self.db.commit()
            self.db.refresh(cat)

        # RAGFlow 端知识库若被删除则重建
        if ragflow_ok and cat.ragflow_dataset_id:
            check = ragflow_client.get_dataset(cat.ragflow_dataset_id)
            if check.get("code") != 0:
                logger.warning(
                    f"客户知识库在 RAGFlow 中不存在，将重建: client={client.id}, "
                    f"dataset_id={cat.ragflow_dataset_id}"
                )
                cat.ragflow_dataset_id = None
                cat.sync_status = "missing"
                cat.last_sync_at = datetime.now()
                self.db.commit()

        if ragflow_ok and not cat.ragflow_dataset_id:
            result = ragflow_client.create_dataset(
                name=dataset_name, description=cat.description or f"{display_name} 客户资料知识库"
            )
            if result.get("code") == 0:
                dataset_id = _extract_ragflow_id(result)
                if dataset_id:
                    cat.ragflow_dataset_id = str(dataset_id)
                    cat.sync_status = "synced"
                    cat.last_sync_at = datetime.now()
                    self.db.commit()
                    self.db.refresh(cat)

        return cat

    # ---------- 上传 ----------

    async def upload_files(
        self,
        *,
        user: User,
        client_id: int,
        files: Sequence[Mapping[str, Any]],
        category: str = "company",
        project_id: Optional[int] = None,
        scope_type: str = "client",
        description: Optional[str] = None,
        extract_basic_info: bool = True,
        extract_profile: bool = True,
        apply_profile: bool = True,
    ) -> Dict[str, Any]:
        """把一组文件入库到客户知识库。

        ``files``: 每项是 Mapping，至少含 ``filename`` 与 ``content``(bytes)，可选 ``content_type``。
        这样 API（UploadFile）和 Agent（已读字节）都能转成同一结构共用本方法。

        抽取/回填开关（方案 §8）：
        - ``extract_basic_info``：是否抽取基础客户信息（company_name/contact/phone/...）并回填空字段。
        - ``extract_profile``：是否抽取结构化画像（产品/痛点/...）落 ``ClientContentProfile``。
        - ``apply_profile``：是否把高置信画像回填到客户/项目空字段（依赖 ``extract_profile``）。
        用户只说「加到知识库」时三参全 False，仅做上传 + RAGFlow parse，不做任何回填。

        返回 ``{uploaded, failed, category_id, ragflow_dataset_id, extracted_info, ...}``。
        RAGFlow 未配置 → 所有文件计入 failed，但不抛异常（不阻断生成）。
        """
        from backend.services.ragflow_client import get_ragflow_client

        client = self._get_owned_client(user, client_id)

        if not files:
            raise ValueError("请至少上传一个文件")
        if len(files) > MAX_FILES:
            raise ValueError(f"文件数量超过上限 {MAX_FILES}")
        if category not in CATEGORY_LABELS:
            raise ValueError(f"资料分类不正确，可选：{', '.join(CATEGORY_LABELS.keys())}")

        ragflow_client = get_ragflow_client()
        category_label = CATEGORY_LABELS[category]

        # RAGFlow 未配置：不阻断调用方，返回全部失败
        if not ragflow_client.is_configured():
            return {
                "uploaded": [],
                "failed": [{"name": _safe_filename(f.get("filename")), "error": "RAGFlow未配置"} for f in files],
                "total": len(files),
                "success_count": 0,
                "failed_count": len(files),
                "category_id": None,
                "ragflow_dataset_id": None,
                "ragflow_configured": False,
                "extracted_info": None,
            }

        cat = self.ensure_client_dataset(user, client.id)
        if not cat.ragflow_dataset_id:
            return {
                "uploaded": [],
                "failed": [
                    {"name": _safe_filename(f.get("filename")), "error": "RAGFlow知识库创建失败"} for f in files
                ],
                "total": len(files),
                "success_count": 0,
                "failed_count": len(files),
                "category_id": cat.id,
                "ragflow_dataset_id": None,
                "ragflow_configured": True,
                "extracted_info": None,
            }

        uploaded: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        text_contents: List[str] = []
        uploaded_doc_ids: List[str] = []

        for f in files:
            file_name = _safe_filename(f.get("filename"))
            content = f.get("content")
            if not isinstance(content, (bytes, bytearray)):
                failed.append({"name": file_name, "error": "文件内容缺失"})
                continue
            content = bytes(content)

            ext = os.path.splitext(file_name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                failed.append({"name": file_name, "error": "不支持的文件格式"})
                continue
            if not content:
                failed.append({"name": file_name, "error": "文件内容为空"})
                continue
            if len(content) > MAX_FILE_SIZE:
                failed.append({"name": file_name, "error": f"文件大小超过 {MAX_FILE_SIZE // 1024 // 1024}MB"})
                continue

            # 本地抽文本用于字段提取；RAGFlow 仍保存完整原文件
            extracted_text = ""
            try:
                from backend.services.document_extractor import get_document_extractor

                extracted_text = get_document_extractor().extract_text_from_file_bytes(content, file_name)
                if extracted_text:
                    text_contents.append(extracted_text)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"本地读取上传文件文本失败（不影响入库）: {file_name}, {exc}")

            try:
                result = ragflow_client.upload_document_bytes(
                    dataset_id=cat.ragflow_dataset_id,
                    file_content=content,
                    file_name=file_name,
                    content_type=f.get("content_type"),
                    do_parse=False,
                )
            except Exception as exc:  # noqa: BLE001
                failed.append({"name": file_name, "error": str(exc)})
                logger.error(f"上传到 RAGFlow 失败: {file_name}, {exc}")
                continue

            if result.get("code") != 0:
                failed.append({"name": file_name, "error": result.get("message", "上传失败")})
                continue

            docs = _extract_ragflow_documents(result)
            if not docs:
                failed.append({"name": file_name, "error": "RAGFlow未返回文档信息"})
                continue
            doc_id = str(docs[0].get("id") or "")
            if not doc_id:
                failed.append({"name": file_name, "error": "RAGFlow返回的文档ID为空"})
                continue

            uploaded_doc_ids.append(doc_id)

            knowledge = Knowledge(
                ragflow_document_id=doc_id,
                ragflow_dataset_id=cat.ragflow_dataset_id,
                category_id=cat.id,
                title=file_name,
                content=_build_knowledge_content(
                    client_id=client.id,
                    category=category,
                    category_label=category_label,
                    scope_type=scope_type,
                    project_id=project_id,
                    description=description,
                    file_name=file_name,
                    extracted_text=extracted_text,
                ),
                type=category,
                sync_status="synced",
                last_sync_at=datetime.now(),
            )
            self.db.add(knowledge)
            self.db.commit()
            self.db.refresh(knowledge)

            uploaded.append(
                {
                    "id": knowledge.id,
                    "name": file_name,
                    "category": category,
                    "ragflow_document_id": doc_id,
                    "ragflow_dataset_id": cat.ragflow_dataset_id,
                }
            )
            logger.info(f"客户资料上传成功: client={client.name}, file={file_name}, doc_id={doc_id}")

        # 触发解析（upload_document_bytes 默认已解析，这里对批量兜底再触发一次，失败不影响结果）
        parse_result: Dict[str, Any] = {}
        if uploaded_doc_ids:
            try:
                parse_result = ragflow_client.parse_documents(cat.ragflow_dataset_id, uploaded_doc_ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"触发 RAGFlow 解析失败（不影响上传结果）: {exc}")
                parse_result = {"code": -1, "message": str(exc)}

        # 基础客户信息提取（保持与原 /upload 行为一致；阶段5 在此之上做结构化画像）
        extracted_info: Dict[str, Any] = {}
        applied_client_fields: Dict[str, Any] = {}
        skipped_client_fields: Dict[str, Any] = {}
        if extract_basic_info:
            extracted_info = _sanitize_basic_info(
                self._extract_basic_info(ragflow_client, cat, text_contents, uploaded_doc_ids)
            )
            applied_client_fields, skipped_client_fields = self._apply_basic_info_to_client(client, extracted_info)

        profile_out: Dict[str, Any] = {"profile": {}, "confidence": {}, "source_document_ids": [], "persisted": False}
        applied_profile_fields: Dict[str, Any] = {}
        if extract_profile and uploaded_doc_ids:
            try:
                from backend.services.content_profile_extraction_service import ContentProfileExtractionService

                profile_service = ContentProfileExtractionService(self.db)
                profile_out = await profile_service.extract_profile(
                    user=user,
                    client_id=client.id,
                    project_id=project_id,
                    document_ids=uploaded_doc_ids,
                    source_text="\n\n---\n\n".join(text_contents) if text_contents else None,
                )
                if apply_profile and profile_out.get("profile"):
                    applied_profile_fields = profile_service.apply_high_confidence_to_project(
                        user, client.id, project_id
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"客户资料画像抽取失败（不影响上传结果）: {exc}")
                profile_out = {
                    "profile": {},
                    "confidence": {},
                    "source_document_ids": uploaded_doc_ids,
                    "persisted": False,
                    "error": str(exc),
                }

        return {
            "uploaded": uploaded,
            "failed": failed,
            "total": len(files),
            "success_count": len(uploaded),
            "failed_count": len(failed),
            "category_id": cat.id,
            "category_name": cat.name,
            "category_label": category_label,
            "ragflow_dataset_id": cat.ragflow_dataset_id,
            "ragflow_configured": True,
            "extracted_info": extracted_info,
            "applied_client_fields": applied_client_fields,
            "skipped_client_fields": skipped_client_fields,
            "profile": profile_out,
            "applied_profile_fields": applied_profile_fields,
            "parse": {
                "triggered": bool(uploaded_doc_ids),
                "document_ids": uploaded_doc_ids,
                "code": parse_result.get("code") if parse_result else None,
                "message": parse_result.get("message") if parse_result else "",
            },
        }

    def _extract_basic_info(
        self,
        ragflow_client,
        cat: KnowledgeCategory,
        text_contents: List[str],
        uploaded_doc_ids: List[str],
    ) -> Dict[str, Any]:
        if not text_contents and not uploaded_doc_ids:
            return {}
        try:
            from backend.services.document_extractor import get_document_extractor

            extractor = get_document_extractor()
            if text_contents:
                combined = "\n\n---\n\n".join(text_contents)
                info = extractor.extract_from_text(combined)
                if info:
                    return info
            if uploaded_doc_ids and cat.ragflow_dataset_id:
                for doc_id in uploaded_doc_ids:
                    info = extractor.extract_from_ragflow_document(cat.ragflow_dataset_id, doc_id, ragflow_client)
                    if info:
                        return info
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"客户信息提取失败（不影响上传结果）: {exc}")
        return {}

    def _apply_basic_info_to_client(
        self, client: Client, extracted_info: Optional[Dict[str, Any]]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Fill empty client fields from document extraction without overwriting user-maintained data.

        返回 ``(applied, skipped)``：
        - ``applied``：``{field: new_value}``，保持字符串值（前端表单把它当字段 spread，契约不可变）。
        - ``skipped``：``{field: reason}``，记录「已有值不覆盖」「格式不合法」等跳过原因。
        """
        if not extracted_info:
            return {}, {}

        applied: Dict[str, Any] = {}
        skipped: Dict[str, Any] = {}
        field_limits = {
            "company_name": 200,
            "contact_person": 100,
            "phone": 50,
            "email": 200,
            "industry": 100,
            "location": 100,
            "address": 500,
            "description": 2000,
        }

        for field, limit in field_limits.items():
            value = extracted_info.get(field)
            # 字段已有值：绝不覆盖
            if getattr(client, field, None):
                if value not in (None, "", []):
                    skipped[field] = "已有值，不覆盖"
                continue
            if value is None:
                continue
            if isinstance(value, list):
                value = "、".join(str(item).strip() for item in value if str(item).strip())
            value = str(value).strip()
            if not value:
                continue
            if not _is_valid_basic_info_value(field, value):
                skipped[field] = "疑似字段标签或占位符"
                continue
            # 格式校验：电话/邮箱不合法则跳过，避免脏数据回填
            if field == "phone" and not _is_valid_phone(value):
                skipped[field] = "电话格式不合法"
                continue
            if field == "email" and not _is_valid_email(value):
                skipped[field] = "邮箱格式不合法"
                continue
            setattr(client, field, value[:limit])
            applied[field] = getattr(client, field)

        placeholder_names = {"未知客户", "未命名客户", "新客户", "客户"}
        company_name = applied.get("company_name") or extracted_info.get("company_name")
        if company_name:
            company_name = str(company_name).strip()
        if company_name and (not client.name or client.name.strip() in placeholder_names):
            client.name = company_name[:200]
            applied["name"] = client.name

        if applied:
            self.db.commit()
            self.db.refresh(client)
        return applied, skipped

    # ---------- 资料存在性（只读，用于生成前置闸门）----------

    def has_client_documents(self, user: User, client_id: int) -> bool:
        """该客户的知识库里是否已有**实际文档**（只读）。

        生成文章前置闸门用：查找属于该客户的 KnowledgeCategory(status=1)，
        再 count 其下 Knowledge(status=1)。
        查找方式：优先用 client_id 字段（可靠），回退用 tags 匹配（兼容历史数据）。
        """
        cid = int(client_id)
        tags = _client_tags(cid)
        # 两条路径 OR 查询：client_id 字段 或 标准 tags
        from sqlalchemy import or_
        cats = (
            scoped_query(self.db, KnowledgeCategory, user)
            .filter(
                KnowledgeCategory.status == 1,
                or_(
                    KnowledgeCategory.client_id == cid,
                    KnowledgeCategory.tags == tags,
                    KnowledgeCategory.tags.contains(tags),
                ),
            )
            .all()
        )
        if not cats:
            return False
        cat_ids = [c.id for c in cats]
        count = (
            self.db.query(Knowledge)
            .filter(Knowledge.category_id.in_(cat_ids), Knowledge.status == 1)
            .count()
        )
        return count > 0

    # ---------- 状态查询 ----------

    def get_ingestion_status(
        self, *, user: User, category_id: int, document_ids: Optional[Sequence[str]] = None
    ) -> Dict[str, Any]:
        """查询某分类下资料（可选限定文档ID）的本地入库状态。"""
        cat = (
            scoped_query(self.db, KnowledgeCategory, user)
            .filter(KnowledgeCategory.id == category_id, KnowledgeCategory.status == 1)
            .first()
        )
        if not cat:
            raise ValueError("知识库分类不存在")

        query = self.db.query(Knowledge).filter(
            Knowledge.ragflow_dataset_id == cat.ragflow_dataset_id, Knowledge.status == 1
        )
        if document_ids:
            query = query.filter(Knowledge.ragflow_document_id.in_(list(document_ids)))
        items = query.order_by(Knowledge.created_at.desc()).all()

        return {
            "category_id": cat.id,
            "ragflow_dataset_id": cat.ragflow_dataset_id,
            "ready": bool(cat.ragflow_dataset_id),
            "sync_status": cat.sync_status,
            "documents": [
                {
                    "id": it.id,
                    "title": it.title,
                    "ragflow_document_id": it.ragflow_document_id,
                    "sync_status": it.sync_status,
                    "type": it.type,
                }
                for it in items
            ],
            "document_count": len(items),
        }
