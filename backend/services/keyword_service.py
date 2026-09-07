# -*- coding: utf-8 -*-
"""
关键词服务 - 工业加固版
负责：关键词的增删改查、直连 DeepSeek 的蒸馏逻辑、变体生成
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from loguru import logger

from backend.database.models import Keyword, Project, QuestionVariant


class KeywordService:
    def __init__(self, db: Session):
        self.db = db

    def add_keyword(
        self, project_id: int, keyword: str, difficulty_score: Optional[int] = None, keyword_type: str = "keyword"
    ) -> Keyword:
        """
        添加单个关键词 (带查重逻辑)
        """
        # 1. 检查是否存在
        exists = self.db.query(Keyword).filter(Keyword.project_id == project_id, Keyword.keyword == keyword).first()

        if exists:
            # 如果已存在但状态不是 active，则激活它
            if exists.status != "active":
                exists.status = "active"
                exists.difficulty_score = difficulty_score or exists.difficulty_score
                exists.keyword_type = keyword_type
                self.db.commit()
                logger.info(f"激活已有关键词: {keyword}")
            return exists

        # 2. 创建新词
        new_kw = Keyword(
            project_id=project_id,
            keyword=keyword,
            difficulty_score=difficulty_score,
            keyword_type=keyword_type,
            status="active",
        )
        self.db.add(new_kw)
        self.db.commit()
        self.db.refresh(new_kw)
        logger.info(f"新增关键词: {keyword} (type={keyword_type})")
        return new_kw

    def add_question_variant(self, keyword_id: int, question: str) -> QuestionVariant:
        """添加问题变体"""
        # 简单查重
        exists = (
            self.db.query(QuestionVariant)
            .filter(QuestionVariant.keyword_id == keyword_id, QuestionVariant.question == question)
            .first()
        )

        if exists:
            return exists

        new_qv = QuestionVariant(keyword_id=keyword_id, question=question)
        self.db.add(new_qv)
        self.db.commit()
        self.db.refresh(new_qv)
        return new_qv

    @staticmethod
    def _item_text(item: Any, keys: Optional[List[str]] = None) -> str:
        """Extract display text from list items."""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in keys or ["keyword", "question", "phrase", "text", "name"]:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _dedupe_texts(items: List[Any], keys: Optional[List[str]] = None) -> List[Any]:
        """Dedupe items by extracted text while keeping original item shape."""
        seen = set()
        output = []
        for item in items or []:
            text = KeywordService._item_text(item, keys)
            norm = " ".join(text.split()).lower().rstrip("?？").strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            output.append(item)
        return output

    def parse_distill_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize KeywordService.distill output for all callers.

        This is the shared parser used by both `/api/keywords/distill` and the
        Excel automation flow. It only normalizes the response shapes we already
        support.
        """
        raw_response = result.get("raw_response")
        similar_keywords = result.get("similar_keywords", []) or []
        keywords_data = result.get("keywords", []) or []
        variants_data = result.get("variants", []) or []
        conversion_phrases = (
            result.get("conversion_phrases") or result.get("questions") or result.get("high_conversion_phrases") or []
        )

        # Some upstream responses return `{code, data: [...]}`. KeywordService.distill
        # normally auto-detects that into conversion_phrases, but keep this here
        # so every caller gets the same fallback.
        if not conversion_phrases and isinstance(raw_response, dict):
            data_items = raw_response.get("data")
            if isinstance(data_items, list):
                conversion_phrases = data_items
            for key in ("questions", "conversion_phrases", "search_phrases", "search_questions"):
                value = raw_response.get(key)
                if isinstance(value, list) and value:
                    conversion_phrases = value
                    break
            if not keywords_data:
                value = raw_response.get("keywords")
                if isinstance(value, list):
                    keywords_data = value
            if not variants_data:
                value = raw_response.get("variants") or raw_response.get("keyword_variants")
                if isinstance(value, list):
                    variants_data = value
            if not similar_keywords:
                value = raw_response.get("similar_keywords") or raw_response.get("related_keywords")
                if isinstance(value, list):
                    similar_keywords = value

        # Core keywords include both `keywords` and `variants`; the API comment
        # already said so, but the old endpoint only persisted `keywords`.
        core_items = []
        core_items.extend(keywords_data if isinstance(keywords_data, list) else [])
        core_items.extend(variants_data if isinstance(variants_data, list) else [])

        return {
            "keywords": self._dedupe_texts(core_items, ["keyword", "text", "phrase", "name"]),
            "similar_keywords": self._dedupe_texts(similar_keywords),
            "variants": self._dedupe_texts(variants_data, ["keyword", "text", "phrase", "name"]),
            "conversion_phrases": self._dedupe_texts(
                conversion_phrases,
                ["question", "phrase", "keyword", "text", "name"],
            ),
            "raw_response": raw_response,
        }

    async def distill_and_persist(
        self,
        *,
        project_id: int,
        core_kw: str,
        target_info: str,
        prefixes: str = "",
        suffixes: str = "",
        company_name: str = "",
        industry: str = "",
        description: str = "",
        count: int = 10,
    ) -> Dict[str, Any]:
        """Call the distill API and persist both core keywords and questions."""
        result = await self.distill(
            core_kw=core_kw,
            target_info=target_info,
            prefixes=prefixes,
            suffixes=suffixes,
            company_name=company_name,
            industry=industry,
            description=description,
            count=count,
        )
        if result.get("status") == "error":
            return {
                "status": "error",
                "message": result.get("message", "蒸馏失败"),
                "keywords": [],
                "similar_keywords": [],
                "variants": [],
                "conversion_phrases": [],
                "saved_keywords": [],
                "saved_phrases": [],
                "raw_response": result.get("raw_response"),
            }

        parsed = self.parse_distill_result(result)
        saved_keywords = []
        saved_phrases = []

        for item in parsed["keywords"]:
            kw_text = self._item_text(item, ["keyword", "text", "phrase", "name"])
            if not kw_text:
                continue
            difficulty = item.get("difficulty_score") if isinstance(item, dict) else None
            keyword = self.add_keyword(
                project_id=project_id,
                keyword=kw_text[:200],
                difficulty_score=difficulty,
                keyword_type="keyword",
            )
            saved_keywords.append({"id": keyword.id, "keyword": keyword.keyword, "keyword_type": "keyword"})

        # If distillation returns only high-conversion phrases, keep the
        # provided seed core keyword visible in the "核心关键词" column instead
        # of showing 0. It only persists the user/project seed as the baseline
        # core keyword.
        if not saved_keywords and core_kw:
            keyword = self.add_keyword(
                project_id=project_id,
                keyword=core_kw[:200],
                difficulty_score=None,
                keyword_type="keyword",
            )
            saved_keywords.append({"id": keyword.id, "keyword": keyword.keyword, "keyword_type": "keyword"})

        for item in parsed["conversion_phrases"]:
            phrase_text = self._item_text(item, ["question", "phrase", "keyword", "text", "name"])
            if not phrase_text:
                continue
            keyword = self.add_keyword(
                project_id=project_id,
                keyword=phrase_text[:200],
                difficulty_score=None,
                keyword_type="question",
            )
            saved_phrases.append({"id": keyword.id, "keyword": keyword.keyword, "keyword_type": "question"})

        return {
            "status": "success",
            "keywords": saved_keywords,
            "similar_keywords": parsed["similar_keywords"],
            "variants": parsed["variants"],
            "conversion_phrases": parsed["conversion_phrases"],
            "saved_phrases": saved_phrases,
            "raw_response": parsed.get("raw_response"),
        }

    async def distill(
        self,
        *,
        core_kw: str,
        target_info: str,
        prefixes: str = "",
        suffixes: str = "",
        company_name: str = "",
        industry: str = "",
        description: str = "",
        count: int = 10,
    ) -> Dict[str, Any]:
        """
        🔥 核心方法：两步蒸馏 (直连 DeepSeek)
        Step 1: distill_keywords → 15 个关键词
        Step 2: generate_search_questions → 20+ 个搜索问题
        """
        logger.info(f"🧪 开始关键词蒸馏: {core_kw} - {target_info}")

        try:
            from backend.services.ai_generation_service import get_ai_service

            ai = get_ai_service()

            # Step 1: 蒸馏关键词
            kw_result = await ai.distill_keywords(
                core_kw=core_kw,
                target_info=target_info,
                prefixes=prefixes,
                suffixes=suffixes,
            )

            if kw_result.get("status") != "success":
                logger.error(f"❌ AI 蒸馏失败: {kw_result}")
                return {"status": "error", "message": str(kw_result)}

            keywords_list = kw_result.get("keywords", [])
            formatted_keywords = [
                {"keyword": kw, "difficulty_score": 50} for kw in keywords_list if kw and isinstance(kw, str)
            ]
            logger.success(f"✅ Step1 蒸馏完成: {len(formatted_keywords)} 个关键词")

            # Step 2: 用关键词生成搜索问题
            question_result = await ai.generate_search_questions(
                keyword_family=keywords_list,
                company_name=company_name,
                industry=industry,
                description=description,
                count=25,
            )

            questions = question_result.get("questions", []) if question_result.get("status") == "success" else []
            logger.success(f"✅ Step2 搜索问题: {len(questions)} 个")

            response_data = {
                "status": "success",
                "keywords": formatted_keywords,
                "similar_keywords": [],
                "variants": [],
                "conversion_phrases": questions,
                "raw_keywords": keywords_list,
            }

            logger.success(f"✅ 蒸馏完成: {len(formatted_keywords)} 关键词 + {len(questions)} 搜索问题")
            return response_data

        except Exception as e:
            logger.exception(f"🚨 蒸馏服务异常: {e}")
            return {"status": "error", "message": str(e)}

    async def generate_questions(self, keyword: str, count: int = 5) -> List[str]:
        """
        生成问题变体 (直连 DeepSeek)
        """
        logger.info(f"❓ 正在为 [{keyword}] 生成长尾问题...")
        try:
            from backend.services.ai_generation_service import get_ai_service

            ai = get_ai_service()
            result = await ai.generate_search_questions(
                keyword_family=[keyword],
                count=count,
            )

            if result.get("status") == "success":
                questions = result.get("questions", [])
                final_questions = [str(q) for q in questions if q]
                logger.success(f"✅ 生成了 {len(final_questions)} 个问题")
                return final_questions
            else:
                logger.error(f"❌ 变体生成失败: {result.get('message', '')}")
                return []
        except Exception as e:
            logger.error(f"🚨 变体服务异常: {e}")
            return []

    # ==================== 基础 CRUD 方法 ====================

    def create_project(
        self, name: str, company_name: str, description: Optional[str] = None, industry: Optional[str] = None
    ) -> Project:
        project = Project(name=name, company_name=company_name, description=description, industry=industry, status=1)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get_project_keywords(self, project_id: int) -> List[Keyword]:
        """获取项目关键词 (包含软删除的，以便查看历史)"""
        return self.db.query(Keyword).filter(Keyword.project_id == project_id).all()

    def get_keyword_questions(self, keyword_id: int) -> List[QuestionVariant]:
        return self.db.query(QuestionVariant).filter(QuestionVariant.keyword_id == keyword_id).all()

    def list_projects(self) -> List[Project]:
        return self.db.query(Project).filter(Project.status == 1).all()
