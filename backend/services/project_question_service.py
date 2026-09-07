# -*- coding: utf-8 -*-
"""搜索问题（蒸馏/去重/补足/使用记录）服务（方案 §7，阶段6）。

搜索问题 = 用户在 AI 搜索/问答平台可能提的问题，作为"一题一文"的生成单位。
全部复用既有能力，不重写蒸馏逻辑：

    distill_and_persist_questions
      -> KeywordService.distill
      -> 取 conversion_phrases / questions 作为搜索问题
      -> 标准化去重后存 Keyword(keyword_type="question")

关键策略（§7.3 / §7.5 / §9.6）：
- 同项目搜索问题标准化去重（normalize_question：NFKC 全角转半角、小写、合并空格、去末尾问号）；
- 已生成过文章（GeoArticle 非失败）的问题不再使用；
- prepare_questions 在不足时**后台自动补蒸馏**（最多 2 轮，每轮 缺口+3 候选），不弹窗、不打断用户。
"""

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import (
    Client,
    GeoArticle,
    Keyword,
    KeywordUsageRecord,
    Project,
    User,
)
from backend.services.keyword_service import KeywordService


MAX_REFILL_ROUNDS = 2
REFILL_CANDIDATE_PAD = 3  # 每轮补蒸馏 缺口 + 3 个候选
DEFAULT_DISTILL_COUNT = 10
MIN_QUESTIONS_TO_KEEP = 1


# ==================== 纯函数：标准化 ====================


def normalize_question(text: Optional[str]) -> str:
    """搜索问题标准化：NFKC 全角转半角 → 小写 → 合并空格 → 去末尾问号。

    用于 project_id + normalized 维度去重（§7.3）。
    """
    s = unicodedata.normalize("NFKC", str(text or "")).strip()
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    # 去掉末尾中英文问号（"人工客服？" 与 "人工客服" 视作同一）
    s = re.sub(r"[?？]+$", "", s).strip()
    return s


# ==================== 服务类 ====================


class ProjectQuestionService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- 查询：未使用问题 ----------

    def _used_question_ids(self, project_id: int) -> set:
        """已生成过文章（非失败）的问题 keyword_id 集合 —— 这些问题不再使用。"""
        rows = (
            self.db.query(GeoArticle.keyword_id)
            .join(Keyword, GeoArticle.keyword_id == Keyword.id)
            .filter(Keyword.project_id == project_id, GeoArticle.publish_status != "failed")
            .distinct()
        )
        return {r[0] for r in rows.all() if r[0] is not None}

    def get_unused_questions(self, project_id: int, limit: Optional[int] = None) -> List[Keyword]:
        """本项目未生成过文章的搜索问题（按 id 升序，稳定）。"""
        used_ids = self._used_question_ids(project_id)
        q = self.db.query(Keyword).filter(
            Keyword.project_id == project_id,
            Keyword.keyword_type == "question",
            Keyword.status == "active",
        )
        if used_ids:
            q = q.filter(~Keyword.id.in_(used_ids))
        q = q.order_by(Keyword.id.asc())
        if limit:
            q = q.limit(limit)
        return q.all()

    def _existing_question_norms(self, project_id: int) -> set:
        rows = self.db.query(Keyword.keyword).filter(
            Keyword.project_id == project_id, Keyword.keyword_type == "question"
        )
        return {normalize_question(r[0]) for r in rows.all()}

    # ---------- 蒸馏 + 落库 ----------

    def _build_distill_inputs(self, project: Project) -> Tuple[str, str, str, str]:
        """从 project/client/画像构造蒸馏输入 (core_kw, target_info, industry, description)。"""
        client = project.client if project.client_id else None
        core_kw = (project.domain_keyword or "").strip()
        company = (project.company_name or (client.company_name if client else "") or "").strip()
        industry = (project.industry or (client.industry if client else "") or "").strip()
        description = (project.description or "").strip()

        # 画像增强（资料抽取/Excel 的痛点、目标客户、优势等拼进 target_info）
        profile_text = self._profile_summary(project.id)
        target_parts = [p for p in (company, description, profile_text) if p]
        target_info = "；".join(target_parts)[:1000] or project.name
        return core_kw, target_info, industry, description

    def _profile_summary(self, project_id: int) -> str:
        """把生效画像里的关键维度拼成短文本，增强蒸馏 target_info。"""
        try:
            project = self.db.query(Project).filter(Project.id == project_id).first()
            if not project or not project.client_id:
                return ""
            from backend.services.content_profile_extraction_service import ContentProfileExtractionService

            eff = ContentProfileExtractionService(self.db).get_effective_profile(project.client_id, project_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"画像摘要获取失败（忽略）: {exc}")
            return ""

        parts: List[str] = []
        for field in ("target_customer", "pain_points", "selling_points", "product_service"):
            item = eff.get(field)
            if not item:
                continue
            value = item.get("value")
            if isinstance(value, list):
                value = "、".join(str(v) for v in value)
            if value:
                parts.append(f"{field}:{value}")
        return "；".join(parts)

    async def distill_and_persist_questions(
        self, project: Project, count: int = DEFAULT_DISTILL_COUNT
    ) -> List[Keyword]:
        """蒸馏搜索问题并落库（keyword_type=question），返回本次新增/激活的问题列表。

        复用 KeywordService.distill 直连 DeepSeek 蒸馏。失败时返回空（上层据此补蒸馏停止）。
        """
        core_kw, target_info, industry, description = self._build_distill_inputs(project)
        if not core_kw:
            logger.warning(f"[question] 项目 {project.id} 无 domain_keyword，无法蒸馏")
            return []

        try:
            result = await KeywordService(self.db).distill_and_persist(
                project_id=project.id,
                core_kw=core_kw,
                target_info=target_info,
                company_name=project.company_name or "",
                industry=industry,
                description=description,
                count=count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[question] 蒸馏调用异常: {exc}")
            return []
        if not isinstance(result, dict) or result.get("status") == "error":
            return []

        phrase_rows = result.get("saved_phrases") or []
        if not phrase_rows:
            return []

        saved: List[Keyword] = []
        seen_ids = set()
        for row in phrase_rows:
            kw_id = row.get("id") if isinstance(row, dict) else None
            if not kw_id or kw_id in seen_ids:
                continue
            seen_ids.add(kw_id)
            kw = (
                self.db.query(Keyword)
                .filter(
                    Keyword.id == kw_id,
                    Keyword.project_id == project.id,
                    Keyword.keyword_type == "question",
                    Keyword.status == "active",
                )
                .first()
            )
            if kw:
                saved.append(kw)
        logger.info(f"[question] 项目 {project.id} 蒸馏落库 {len(saved)} 个搜索问题")
        return saved

    @staticmethod
    def _flatten_questions(result: Dict, count: int) -> List[str]:
        """优先取 conversion_phrases/questions 作为搜索问题，不足再用其它类别补。"""
        ordered_keys = [
            "conversion_phrases",
            "questions",
            "search_phrases",
            "search_questions",
            "keywords",
            "variants",
            "similar_keywords",
        ]
        out: List[str] = []
        seen = set()
        for key in ordered_keys:
            values = result.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                text = None
                if isinstance(item, str):
                    text = item.strip()
                elif isinstance(item, dict):
                    for k in ("question", "phrase", "keyword", "text", "name"):
                        v = item.get(k)
                        if isinstance(v, str) and v.strip():
                            text = v.strip()
                            break
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
                if len(out) >= count:
                    return out
        return out

    # ---------- 对外：准备指定数量的未使用问题（含自动补蒸馏）----------

    async def prepare_questions(self, project_id: int, needed: int) -> Tuple[List[Keyword], Optional[str]]:
        """为本项目准备 ``needed`` 个未使用搜索问题；不足时后台自动补蒸馏（不打断用户）。

        返回 (questions, note)。note 非空表示未能凑齐，附带原因。
        """
        needed = max(1, int(needed))
        project = self.db.query(Project).filter(Project.id == project_id, Project.status == 1).first()
        if not project:
            return [], "项目不存在或已停用"

        selected: List[Keyword] = []
        seen_norm: set = set()

        def collect() -> None:
            for kw in self.get_unused_questions(project_id):
                if len(selected) >= needed:
                    break
                norm = normalize_question(kw.keyword)
                if not norm or norm in seen_norm:
                    continue
                seen_norm.add(norm)
                selected.append(kw)

        # 第 0 轮：直接取已有未使用问题
        collect()
        logger.info(f"[question] 项目 {project_id} 现有未使用问题 {len(selected)}/{needed}")

        # 补蒸馏
        rounds = 0
        while len(selected) < needed and rounds < MAX_REFILL_ROUNDS:
            rounds += 1
            gap = needed - len(selected)
            request_count = max(DEFAULT_DISTILL_COUNT, gap + REFILL_CANDIDATE_PAD)
            new_qs = await self.distill_and_persist_questions(project, count=request_count)
            if not new_qs:
                break  # 蒸馏失败 → 不再重试
            collect()

        note = None
        if len(selected) < needed:
            note = (
                f"搜索问题不足：需要 {needed} 篇，仅获取到 {len(selected)} 个未使用搜索问题"
                f"（已自动补蒸馏 {rounds} 轮）。将按现有数量生成。"
            )
            logger.warning(f"[question] {note}")
        return selected, note

    # ---------- 使用记录 ----------

    def record_usage(
        self,
        *,
        project_id: int,
        keyword: Keyword,
        article_id: int,
        user_id: Optional[int],
        source: str = "agent_excel",
    ) -> KeywordUsageRecord:
        """文章生成成功后写搜索问题使用记录（§7.4）。"""
        rec = KeywordUsageRecord(
            project_id=project_id,
            keyword_id=keyword.id,
            keyword_text=keyword.keyword,
            article_id=article_id,
            source=source,
            used_by_user_id=user_id,
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec
