from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.database.models import SmartArticleBatch, SmartArticleQuestion
from backend.middleware.user_isolation import scoped_query
from .context_builder import SmartArticleContextError, build_project_context
from .prompts import PROMPT_VERSIONS
from .question_planner import QuestionPlanningError, SmartArticleQuestionPlanner, normalize_question


MAX_QUESTION_COUNT = 30


class SmartArticleQuestionPoolService:
    def __init__(self, db: Session):
        self.db = db

    def create_batch(self, current_user, project_id: int, question_count: int, custom_question: str | None) -> SmartArticleBatch:
        if question_count < 1 or question_count > MAX_QUESTION_COUNT:
            raise ValueError(f"生成问题数量必须在1到{MAX_QUESTION_COUNT}之间")
        value = str(custom_question or "").strip() or None
        if value:
            question_count = 1
        build_project_context(self.db, project_id, current_user)
        batch = SmartArticleBatch(
            user_id=current_user.id,
            project_id=project_id,
            batch_type="question_generation",
            mode="manual" if value else "auto",
            requested_count=question_count,
            input_question=value,
            status="pending",
            question_prompt_version=None if value else PROMPT_VERSIONS["question"],
            filter_prompt_version=None if value else PROMPT_VERSIONS["filter"],
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    async def run_batch(self, batch_id: int) -> None:
        batch = self.db.query(SmartArticleBatch).filter(
            SmartArticleBatch.id == batch_id,
            SmartArticleBatch.batch_type == "question_generation",
        ).first()
        if not batch:
            return
        try:
            batch.status = "planning_questions"
            self.db.commit()
            owner = SimpleNamespace(id=batch.user_id, role="user")
            context = build_project_context(self.db, batch.project_id, owner)
            planner = SmartArticleQuestionPlanner(self.db)
            if batch.mode == "manual":
                planned = [planner.manual(batch.input_question or "", context)]
            else:
                planned = await planner.plan(context, batch.requested_count, planner.history(context))
                batch.expanded_terms = planner.last_expanded_terms
            batch.status = "saving_questions"
            batch.planned_count = len(planned)
            self.db.commit()

            added = 0
            for item in planned:
                normalized = normalize_question(item.question)
                if not normalized:
                    continue
                existing = self.db.query(SmartArticleQuestion).filter(
                    SmartArticleQuestion.project_id == context.project_id,
                    SmartArticleQuestion.normalized_question == normalized,
                ).first()
                if existing:
                    if batch.mode == "manual":
                        raise QuestionPlanningError("该问题已经存在于当前项目的问题历史中")
                    continue
                self.db.add(SmartArticleQuestion(
                    user_id=batch.user_id,
                    project_id=context.project_id,
                    generation_batch_id=batch.id,
                    question=item.question,
                    normalized_question=normalized,
                    source="manual" if batch.mode == "manual" else "ai",
                    intent_type=item.intent_type,
                    context_type=item.context_type,
                    brand_entry_reason=item.brand_entry_reason,
                    retrieval_terms=item.retrieval_terms,
                ))
                added += 1
            batch.queued_count = added
            batch.success_count = added
            batch.status = "completed"
            batch.completed_at = datetime.now()
            batch.note = None if added == len(planned) else f"筛选结果中有 {len(planned) - added} 条已存在，已跳过重复问题"
            self.db.commit()
        except (SmartArticleContextError, QuestionPlanningError, ValueError, RuntimeError) as exc:
            self._fail_batch(batch, f"阶段=问题规划/保存：{exc}")
        except Exception as exc:  # noqa: BLE001
            self._fail_batch(batch, f"阶段=问题规划/保存：{exc}")
            logger.exception("智能问题批次 {} 未知失败", batch_id)

    def list_questions(self, current_user, project_id: int, has_article: bool | None, page: int, limit: int,
                       generation_batch_id: int | None = None) -> dict[str, Any]:
        """列出项目下的问题。支持 has_article / generation_batch_id 过滤。

        Args:
            generation_batch_id: 可选，按问题批次过滤（Agent V2 generate_articles_batch 工具用）
        """
        query = scoped_query(self.db, SmartArticleQuestion, current_user).filter(
            SmartArticleQuestion.project_id == project_id,
            SmartArticleQuestion.is_deleted.is_(False),
        )
        if has_article is not None:
            query = query.filter(SmartArticleQuestion.has_article.is_(has_article))
        if generation_batch_id is not None:
            query = query.filter(SmartArticleQuestion.generation_batch_id == generation_batch_id)
        total = query.count()
        rows = query.order_by(SmartArticleQuestion.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {"total": total, "items": [_question_dict(row) for row in rows]}

    def soft_delete(self, current_user, question_ids: list[int]) -> int:
        if not question_ids:
            return 0
        rows = scoped_query(self.db, SmartArticleQuestion, current_user).filter(
            SmartArticleQuestion.id.in_(question_ids),
            SmartArticleQuestion.is_deleted.is_(False),
        ).all()
        now = datetime.now()
        for row in rows:
            row.is_deleted = True
            row.deleted_at = now
        self.db.commit()
        return len(rows)

    def get_batch(self, batch_id: int, current_user) -> dict[str, Any]:
        batch = scoped_query(self.db, SmartArticleBatch, current_user).filter(
            SmartArticleBatch.id == batch_id,
            SmartArticleBatch.batch_type == "question_generation",
        ).first()
        if not batch:
            raise LookupError("问题生成批次不存在或无权访问")
        return {
            "batch_id": batch.id,
            "batch_type": batch.batch_type,
            "project_id": batch.project_id,
            "status": batch.status,
            "requested_count": batch.requested_count,
            "planned_count": batch.planned_count,
            "queued_count": batch.queued_count,
            "success_count": batch.success_count,
            "failed_count": batch.failed_count,
            "expanded_terms": batch.expanded_terms or [],
            "note": batch.note,
        }

    def _fail_batch(self, batch: SmartArticleBatch, message: str) -> None:
        batch.status = "failed"
        batch.note = message[:2000]
        batch.completed_at = datetime.now()
        self.db.commit()


def _question_dict(row: SmartArticleQuestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "question": row.question,
        "source": row.source,
        "intent_type": row.intent_type,
        "context_type": row.context_type,
        "has_article": bool(row.has_article),
        "article_id": row.article_id,
        "article_generation_status": row.article_generation_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def run_smart_question_batch(batch_id: int) -> None:
    db = SessionLocal()
    try:
        await SmartArticleQuestionPoolService(db).run_batch(batch_id)
    finally:
        db.close()
