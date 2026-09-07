# -*- coding: utf-8 -*-
"""资料结构化画像抽取服务（方案 §6.5，阶段5）。

从用户上传的公司资料里抽取**推荐字段**，补齐 Excel 中缺失的维度，用于后续蒸馏搜索
问题与生成文章。与 RAGFlow 检索分工明确（§6.5）：

- RAGFlow 知识库：文章生成时检索原文片段，提供事实依据；
- 结构化字段抽取：把资料里的行业/产品/痛点/优势/案例等变成系统字段。

抽取来源：客户知识库的 RAGFlow 检索片段（按公司名+维度多 query 取并集）。
存储：``ClientContentProfile``（source=ragflow_extract），记录 profile_json / confidence_json /
source_document_ids。

优先级（``get_effective_profile`` 统一对外，§6.5 回填规则）：
    Excel 已填字段 > 资料抽取高置信度 > 资料抽取低置信度(候选) > 系统默认
即 **Excel 已有字段绝不被资料抽取覆盖**（excel 字段从导入行的 normalized_data 取）。
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import (
    AgentExcelImportRow,
    Client,
    ClientContentProfile,
    KnowledgeCategory,
    Project,
    User,
)
from backend.middleware.user_isolation import require_owner, scoped_query
from backend.services.geo_knowledge_service import CLIENT_UPLOAD_TAG_PREFIX


# 抽取字段：标量 vs 列表
SCALAR_FIELDS = {"industry", "project_description", "brand_tone"}
LIST_FIELDS = {
    "product_service",
    "target_customer",
    "pain_points",
    "selling_points",
    "case_materials",
    "forbidden_words",
}
ALL_PROFILE_FIELDS = SCALAR_FIELDS | LIST_FIELDS

HIGH_CONFIDENCE_THRESHOLD = 0.7
MAX_SOURCE_TEXT_CHARS = 8000  # 喂给 AI 的资料文本上限


def _client_tags(client_id: int) -> str:
    return f"{CLIENT_UPLOAD_TAG_PREFIX}{client_id}"


def _normalize_list(value: Any) -> List[str]:
    """把 AI 返回的列表/逗号串规整成去空字符串列表。"""
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[、,，;；\n]", value)
    elif isinstance(value, list):
        items = value
    else:
        items = [value]
    return [str(it).strip() for it in items if str(it).strip()]


def _normalize_extracted(raw: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, float]]:
    """把 AI 原始返回拆成 (profile, confidence)，按字段类型规整。"""
    profile: Dict[str, Any] = {}
    confidence_raw = raw.get("confidence") if isinstance(raw.get("confidence"), dict) else {}

    for field in ALL_PROFILE_FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if field in LIST_FIELDS:
            items = _normalize_list(value)
            if items:
                profile[field] = items
        else:
            text = str(value).strip() if value is not None else ""
            if text and text.lower() != "null":
                profile[field] = text

    confidence: Dict[str, float] = {}
    for field in profile:
        c = confidence_raw.get(field)
        try:
            confidence[field] = max(0.0, min(1.0, float(c))) if c is not None else 0.5
        except (TypeError, ValueError):
            confidence[field] = 0.5
    return profile, confidence


class ContentProfileExtractionService:
    """从客户资料抽取结构化画像并落库/合并。"""

    def __init__(self, db: Session):
        self.db = db

    # ---------- 客户/项目归属 ----------

    def _get_owned_client(self, user: User, client_id: int) -> Client:
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError("客户不存在")
        require_owner(client, user, name="客户")
        return client

    def _resolve_dataset_id(self, client_id: int) -> Optional[str]:
        tags = _client_tags(client_id)
        cat = (
            self.db.query(KnowledgeCategory)
            .filter(KnowledgeCategory.tags == tags, KnowledgeCategory.status == 1)
            .first()
        )
        return cat.ragflow_dataset_id if (cat and cat.ragflow_dataset_id) else None

    # ---------- 资料 text 收集 ----------

    def _gather_source_text(self, client: Client, document_ids: Optional[List[str]] = None) -> tuple[str, List[str]]:
        """从客户知识库检索片段拼成给 AI 的资料文本；返回 (text, source_doc_ids)。"""
        dataset_id = self._resolve_dataset_id(client.id)
        if not dataset_id:
            return "", []

        from backend.services.ragflow_client import get_ragflow_client

        ragflow = get_ragflow_client()
        if not ragflow.is_configured():
            return "", []

        company = client.company_name or client.name
        queries = [
            f"{company} 公司介绍 所属行业 业务范围",
            f"{company} 产品 服务 解决方案 应用场景",
            f"{company} 目标客户 客户痛点 需求 问题",
            f"{company} 核心优势 卖点 案例 成功案例",
            f"{company} 品牌调性 禁用词 合规",
        ]

        chunks_by_key: Dict[str, str] = {}
        source_doc_ids: List[str] = []
        seen_docs = set()
        total_chars = 0

        for q in queries:
            if total_chars >= MAX_SOURCE_TEXT_CHARS:
                break
            try:
                result = ragflow.retrieve(question=q, dataset_ids=[dataset_id], similarity_threshold=0.2, top_k=5)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"画像抽取检索失败: {exc}")
                continue
            if result.get("code") != 0:
                continue
            data = result.get("data") or {}
            chunks = data.get("chunks") if isinstance(data, dict) else []
            if not isinstance(chunks, list):
                continue
            for ch in chunks:
                if not isinstance(ch, dict):
                    continue
                content = (ch.get("content") or "").strip()
                if not content:
                    continue
                doc_id = ch.get("document_id") or ch.get("doc_id") or ""
                key = (doc_id or "") + "::" + content[:80]
                if key in chunks_by_key:
                    continue
                chunks_by_key[key] = content
                if doc_id and doc_id not in seen_docs:
                    seen_docs.add(doc_id)
                    source_doc_ids.append(doc_id)
                total_chars += len(content)
                if total_chars >= MAX_SOURCE_TEXT_CHARS:
                    break

        text = "\n\n".join(chunks_by_key.values())
        if document_ids:
            # 仅保留指定文档来源
            source_doc_ids = [d for d in source_doc_ids if d in set(document_ids)]
        return text[:MAX_SOURCE_TEXT_CHARS], source_doc_ids

    # ---------- AI 抽取 ----------

    async def _call_ai(self, text: str) -> Dict[str, Any]:
        """调用 DeepSeek 抽取结构化画像，返回原始 dict。"""
        import httpx

        from backend.config import (
            AUTOGEO_CONVERSATION_LLM_API_KEY,
            AUTOGEO_CONVERSATION_LLM_BASE_URL,
            AUTOGEO_CONVERSATION_LLM_MODEL,
            DEEPSEEK_API_KEY,
            DEEPSEEK_API_URL,
        )

        api_key = DEEPSEEK_API_KEY or AUTOGEO_CONVERSATION_LLM_API_KEY
        api_url = DEEPSEEK_API_URL or AUTOGEO_CONVERSATION_LLM_BASE_URL
        model = AUTOGEO_CONVERSATION_LLM_MODEL or "deepseek-v4-flash"
        if not api_key:
            logger.warning("未配置 DeepSeek，跳过资料画像抽取")
            return {}

        base = (api_url or "").rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

        prompt = (
            "你是企业资料分析助手。从下面公司资料中抽取结构化画像，严格只返回 JSON（不要 markdown、不要解释）。\n"
            "字段说明：industry(行业,字符串)、project_description(业务/项目描述,字符串)、"
            "product_service(产品服务,字符串数组)、target_customer(目标客户,字符串数组)、"
            "pain_points(客户痛点,字符串数组)、selling_points(核心优势,字符串数组)、"
            "case_materials(案例素材,字符串数组)、forbidden_words(禁用词,字符串数组)、"
            "brand_tone(品牌语气,字符串)。\n"
            "资料中没有的字段返回 null（数组字段返回空数组 []）。\n"
            '同时在 "confidence" 对象里给每个抽取到的字段一个 0~1 的置信度（资料明确提及高，推断低）。\n'
            "返回示例：\n"
            '{"industry":"AI客服","project_description":"面向企业提供智能客服系统",'
            '"product_service":["智能客服机器人","工单系统"],"target_customer":["电商客服主管"],'
            '"pain_points":["客服成本高","响应慢"],"selling_points":["多渠道接入"],'
            '"case_materials":[],"forbidden_words":["保证"],"brand_tone":"专业",'
            '"confidence":{"industry":0.9,"product_service":0.85}}\n\n'
            f"公司资料：\n{text}"
        )

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 1200,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                content = content.strip()
                # 去掉可能的 markdown 代码块
                if content.startswith("```"):
                    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"资料画像 AI 抽取失败: {exc}")
            return {}

    # ---------- 对外方法 ----------

    async def extract_profile(
        self,
        *,
        user: User,
        client_id: int,
        project_id: Optional[int] = None,
        document_ids: Optional[List[str]] = None,
        source_text: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """抽取客户资料画像。返回 {profile, confidence, source_document_ids, persisted}。

        AI 不可用/无资料时返回空画像（不抛异常，不阻断生成）。
        """
        client = self._get_owned_client(user, client_id)
        if source_text and source_text.strip():
            text = source_text.strip()[:MAX_SOURCE_TEXT_CHARS]
            source_doc_ids = list(dict.fromkeys(document_ids or []))
        else:
            text, source_doc_ids = self._gather_source_text(client, document_ids)
        if not text:
            logger.info(f"[profile] 客户 {client_id} 无可抽取资料文本，跳过")
            return {"profile": {}, "confidence": {}, "source_document_ids": [], "persisted": False}

        raw = await self._call_ai(text)
        profile, confidence = _normalize_extracted(raw)

        result = {
            "profile": profile,
            "confidence": confidence,
            "source_document_ids": source_doc_ids,
            "persisted": False,
        }
        if persist and profile:
            saved = self.persist_profile(
                user=user,
                client_id=client.id,
                project_id=project_id,
                profile=profile,
                confidence=confidence,
                source_document_ids=source_doc_ids,
            )
            result["persisted"] = True
            result["profile_id"] = saved.id
        return result

    def persist_profile(
        self,
        *,
        user: User,
        client_id: int,
        project_id: Optional[int],
        profile: Dict[str, Any],
        confidence: Dict[str, float],
        source_document_ids: List[str],
        source: str = "ragflow_extract",
    ) -> ClientContentProfile:
        """落库画像（按 client_id + project_id + source upsert，新抽取覆盖同源旧值）。"""
        self._get_owned_client(user, client_id)
        existing = (
            self.db.query(ClientContentProfile)
            .filter(
                ClientContentProfile.client_id == client_id,
                ClientContentProfile.project_id == project_id
                if project_id is not None
                else ClientContentProfile.project_id.is_(None),
                ClientContentProfile.source == source,
                ClientContentProfile.status == "active",
            )
            .first()
        )
        if existing:
            merged_profile = dict(existing.profile_json or {})
            merged_profile.update(profile)
            merged_conf = dict(existing.confidence_json or {})
            merged_conf.update(confidence)
            merged_docs = list(dict.fromkeys((existing.source_document_ids or []) + source_document_ids))
            existing.profile_json = merged_profile
            existing.confidence_json = merged_conf
            existing.source_document_ids = merged_docs
            self.db.commit()
            self.db.refresh(existing)
            return existing

        prof = ClientContentProfile(
            user_id=user.id,
            client_id=client_id,
            project_id=project_id,
            source=source,
            profile_json=profile,
            confidence_json=confidence,
            source_document_ids=source_document_ids,
            status="active",
        )
        self.db.add(prof)
        self.db.commit()
        self.db.refresh(prof)
        return prof

    def get_profile(
        self, client_id: int, project_id: Optional[int] = None, source: str = "ragflow_extract"
    ) -> Optional[ClientContentProfile]:
        return (
            self.db.query(ClientContentProfile)
            .filter(
                ClientContentProfile.client_id == client_id,
                ClientContentProfile.project_id == project_id
                if project_id is not None
                else ClientContentProfile.project_id.is_(None),
                ClientContentProfile.source == source,
                ClientContentProfile.status == "active",
            )
            .first()
        )

    def get_excel_fields(self, project_id: int) -> Dict[str, Any]:
        """读取该项目的 Excel 导入行 normalized_data（source=excel，最高优先级）。"""
        row = (
            self.db.query(AgentExcelImportRow)
            .filter(AgentExcelImportRow.project_id == project_id, AgentExcelImportRow.status == "processed")
            .order_by(AgentExcelImportRow.id.desc())
            .first()
        )
        if not row or not row.normalized_data:
            return {}
        nd = row.normalized_data
        fields: Dict[str, Any] = {}
        # 标量
        for f in ("industry", "project_description"):
            v = (nd.get(f) or "").strip()
            if v:
                fields[f] = v
        # 列表（Excel 里是逗号/顿号串）
        for f in (
            "target_customer",
            "pain_points",
            "product_service",
            "selling_points",
            "case_materials",
            "forbidden_words",
        ):
            v = (nd.get(f) or "").strip()
            if v:
                fields[f] = _normalize_list(v)
        return fields

    def get_effective_profile(self, client_id: int, project_id: Optional[int] = None) -> Dict[str, Any]:
        """合并出"生效画像"供蒸馏/生成使用（§6.5 优先级）。

        返回 {field: {"value":..., "source": "excel"|"extract_high"|"extract_low", "confidence": float}}。
        Excel 已填字段绝不被资料抽取覆盖。
        """
        effective: Dict[str, Any] = {}

        # 1. 资料抽取（低置信先入，高置信后入以覆盖）
        prof = self.get_profile(client_id, project_id)
        if prof and prof.profile_json:
            conf = prof.confidence_json or {}
            low_first = sorted(
                prof.profile_json.items(), key=lambda kv: conf.get(kv[0], 0.5) >= HIGH_CONFIDENCE_THRESHOLD
            )
            for field, value in low_first:
                c = conf.get(field, 0.5)
                tier = "extract_high" if c >= HIGH_CONFIDENCE_THRESHOLD else "extract_low"
                effective[field] = {"value": value, "source": tier, "confidence": c}

        # 2. Excel 字段最高优先级（覆盖任何 extract 值）
        if project_id:
            for field, value in self.get_excel_fields(project_id).items():
                effective[field] = {"value": value, "source": "excel", "confidence": 1.0}

        return effective

    def apply_high_confidence_to_project(
        self, user: User, client_id: int, project_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """把高置信度抽取结果回填到客户/项目的**空**字段（不覆盖已填值）。"""
        prof = self.get_profile(client_id, project_id)
        applied: Dict[str, Any] = {}
        if not prof or not prof.profile_json:
            return applied
        conf = prof.confidence_json or {}
        pj = project_id

        client = self._get_owned_client(user, client_id)
        project = self.db.query(Project).filter(Project.id == pj, Project.status == 1).first() if pj else None

        def fill(obj, attr, field):
            if not obj:
                return
            if getattr(obj, attr, None):
                return
            c = conf.get(field, 0)
            value = prof.profile_json.get(field)
            if c >= HIGH_CONFIDENCE_THRESHOLD and value:
                if isinstance(value, list):
                    value = "、".join(str(v) for v in value)
                setattr(obj, attr, str(value)[:500])
                applied[field] = value

        fill(client, "industry", "industry")
        fill(client, "description", "project_description")
        fill(project, "industry", "industry")
        fill(project, "description", "project_description")
        self.db.commit()
        return applied
