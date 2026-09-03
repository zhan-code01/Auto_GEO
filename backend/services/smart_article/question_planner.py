from __future__ import annotations

import re

from sqlalchemy.orm import Session

from loguru import logger

from backend.database.models import Keyword, SmartArticleJob, SmartArticleQuestion
from backend.middleware.user_isolation import scoped_query
from .llm_adapter import SmartArticleLLMAdapter
from .prompts import (
    FILTER_SYSTEM,
    PROMPT_VERSIONS,
    QUESTION_SYSTEM,
    build_filter_prompt,
    build_question_prompt,
    recommendation_target,
)
from .region_context import detect_region
from .schemas import CONTEXT_TYPES, INTENT_TYPES, PlannedQuestion, ProjectContext


class QuestionPlanningError(RuntimeError):
    pass


def normalize_question(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "")).lower()


class SmartArticleQuestionPlanner:
    def __init__(self, db: Session, llm: SmartArticleLLMAdapter | None = None):
        self.db = db
        self.llm = llm or SmartArticleLLMAdapter()
        self.last_expanded_terms: list[dict[str, str]] = []

    def history(self, context: ProjectContext) -> list[str]:
        pool_rows = (
            self.db.query(SmartArticleQuestion.question)
            .filter(SmartArticleQuestion.project_id == context.project_id)
            .all()
            if self.db is not None
            else []
        )
        rows = (
            self.db.query(SmartArticleJob.question)
            .filter(SmartArticleJob.project_id == context.project_id, SmartArticleJob.status == "completed")
            .all()
        ) if self.db is not None else []
        keyword_rows = (
            self.db.query(Keyword.keyword)
            .filter(Keyword.project_id == context.project_id, Keyword.keyword_type == "smart_question")
            .all()
        ) if self.db is not None else []
        return list(dict.fromkeys([row[0] for row in pool_rows + rows + keyword_rows if row[0]]))

    def manual(self, question: str, context: ProjectContext) -> PlannedQuestion:
        value = str(question or "").strip()
        if not value:
            raise QuestionPlanningError("指定问题不能为空")
        context_type = "region" if detect_region(value, context.allowed_regions) else ("industry" if context.industry else "general")
        return PlannedQuestion(
            question=value,
            intent_type="manual",
            context_type=context_type,
            brand_entry_reason="根据用户指定问题自然介绍目标项目，供用户进一步咨询或评估",
            retrieval_terms=[],
        )

    async def plan(self, context: ProjectContext, target_count: int, excluded: list[str]) -> list[PlannedQuestion]:
        if target_count < 1:
            raise QuestionPlanningError("文章数量必须至少为1")
        candidate_count = min(120, target_count + 5)
        provider_target = recommendation_target(target_count)
        selected: list[PlannedQuestion] = []
        excluded_norm = {normalize_question(item) for item in excluded}
        self.last_expanded_terms = []
        product_summary = self._load_product_summary(context)
        logger.info(
            f"[QuestionPlanner] 开始规划问题: project_id={context.project_id} "
            f"target={target_count} provider_target={provider_target} excluded={len(excluded)} "
            f"product_summary={'有' if product_summary else '无'}"
        )

        for _round in range(3):
            prompt1 = await self.llm.json(
                QUESTION_SYSTEM,
                build_question_prompt(context, target_count, candidate_count, excluded, product_summary),
                temperature=0.8,
                # 推理模型 reasoning_tokens 占比高，输出配额调大，给实际 JSON 内容留出空间
                max_tokens=16000,
                stage="Prompt 1：关键词扩展与候选问题生成",
                prompt_version=PROMPT_VERSIONS["question"],
            )
            candidates = prompt1.get("questions")
            if not isinstance(candidates, list):
                raise QuestionPlanningError("Prompt 1返回缺少questions数组")
            candidates = [item for item in candidates if isinstance(item, dict)]
            if not self.last_expanded_terms:
                expanded_terms = self._parse_expanded_terms(prompt1.get("expanded_terms"))
                if not self._expanded_term_mix_is_valid(expanded_terms):
                    if _round < 2:
                        continue
                    raise QuestionPlanningError("Prompt 1关键词扩展数量或类别比例不合格")
                self.last_expanded_terms = expanded_terms
            current_provider_count = sum(item.intent_type == "provider" for item in selected)
            remaining_provider_count = max(0, provider_target - current_provider_count)
            prompt2 = await self.llm.json(
                FILTER_SYSTEM,
                build_filter_prompt(
                    context,
                    target_count - len(selected),
                    candidates,
                    excluded,
                    self.last_expanded_terms,
                    required_provider_count=remaining_provider_count,
                    product_summary=product_summary,
                ),
                temperature=0.3,
                max_tokens=16000,
                stage="Prompt 2：推荐机会问题筛选",
                prompt_version=PROMPT_VERSIONS["filter"],
            )
            selected_raw = prompt2.get("selected_questions")
            if not isinstance(selected_raw, list):
                raise QuestionPlanningError("Prompt 2返回缺少selected_questions数组")
            for item in selected_raw:
                planned = self._parse(item, context)
                if not planned:
                    continue
                non_provider_count = sum(question.intent_type != "provider" for question in selected)
                if planned.intent_type != "provider" and non_provider_count >= target_count - provider_target:
                    continue
                norm = normalize_question(planned.question)
                if not norm or norm in excluded_norm or any(normalize_question(x.question) == norm for x in selected):
                    continue
                selected.append(planned)
                excluded_norm.add(norm)
                if len(selected) >= target_count and sum(item.intent_type == "provider" for item in selected) >= provider_target:
                    logger.success(
                        f"[QuestionPlanner] 问题规划完成: project_id={context.project_id} "
                        f"selected={len(selected)} rounds={_round + 1}"
                    )
                    return selected[:target_count]
            excluded = excluded + [item.question for item in selected]
            candidate_count = min(120, target_count - len(selected) + 5)

        if len(selected) < target_count or sum(item.intent_type == "provider" for item in selected) < provider_target:
            logger.error(
                f"[QuestionPlanner] 问题规划不足: project_id={context.project_id} "
                f"selected={len(selected)}/{target_count} provider_need={provider_target}"
            )
            raise QuestionPlanningError(f"没有筛选出足量问题，且推荐型问题需至少{provider_target}个")
        logger.success(
            f"[QuestionPlanner] 问题规划完成: project_id={context.project_id} selected={len(selected)}"
        )
        return selected[:target_count]

    def _load_product_summary(self, context: ProjectContext) -> str:
        """问题生成前对批次做一次RAGFlow轻量查询；失败或无资料时返回空字符串，不阻断。"""
        if self.db is None:
            return ""
        try:
            from .knowledge_service import SmartArticleKnowledgeService

            return SmartArticleKnowledgeService(self.db).retrieve_product_summary(context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("智能文章问题批次产品摘要查询失败，继续用基础资料生成: {}", exc)
            return ""

    @staticmethod
    def _parse_expanded_terms(value: object) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        allowed = {"synonym", "adjacent", "scenario", "concern"}
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term") or "").strip()
            relation = str(item.get("relation") or "").strip().lower()
            key = normalize_question(term)
            if not term or not key or relation not in allowed or key in seen:
                continue
            result.append({"term": term[:50], "relation": relation})
            seen.add(key)
            if len(result) >= 15:
                break
        return result

    @staticmethod
    def _expanded_term_mix_is_valid(terms: list[dict[str, str]]) -> bool:
        """Require all four relations and keep synonym+adjacent near the agreed 60%."""
        if not 6 <= len(terms) <= 15:
            return False
        counts = {relation: 0 for relation in ("synonym", "adjacent", "scenario", "concern")}
        for item in terms:
            relation = item.get("relation")
            if relation in counts:
                counts[relation] += 1
        if any(count == 0 for count in counts.values()):
            return False
        core_ratio = (counts["synonym"] + counts["adjacent"]) / len(terms)
        return 0.5 <= core_ratio <= 0.7

    def _parse(self, item: dict, context: ProjectContext) -> PlannedQuestion | None:
        question = str(item.get("question") or "").strip()
        intent = str(item.get("intent_type") or "").strip()
        context_type = str(item.get("context_type") or "general").strip()
        if not question or len(question) < 8 or len(question) > 60:
            return None
        if intent not in INTENT_TYPES - {"manual"} or context_type not in CONTEXT_TYPES:
            return None
        if context.company_name and context.company_name in question:
            return None
        if any(region in question for region in context.blocked_regions):
            return None
        if context_type == "region" and not detect_region(question, context.allowed_regions):
            return None
        terms = item.get("retrieval_terms") or item.get("related_terms") or []
        if not isinstance(terms, list):
            terms = []
        terms = [str(term).strip() for term in terms[:5] if str(term).strip()]
        return PlannedQuestion(
            question=question,
            intent_type=intent,
            context_type=context_type,
            brand_entry_reason=str(item.get("brand_entry_reason") or "").strip(),
            retrieval_terms=terms,
        )

    @property
    def question_prompt_version(self) -> str:
        return PROMPT_VERSIONS["question"]

    @property
    def filter_prompt_version(self) -> str:
        return PROMPT_VERSIONS["filter"]
