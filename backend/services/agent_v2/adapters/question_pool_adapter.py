# -*- coding: utf-8 -*-
"""QuestionPoolAdapter - 智能文章问题池适配器。

关键方法：
- plan_batch_sync: 同步封装，绕过 FastAPI BackgroundTasks，await run_smart_question_batch
- generate_articles_sync: 创建文章生成任务，异步在后台跑
- list_questions: 列出问题（支持 generation_batch_id 过滤）

对应 PRD 第七章 7.5 节 adapter 同步封装方案。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.database.models import SmartArticleBatch, SmartArticleQuestion
from backend.middleware.user_isolation import scoped_query
from backend.services.smart_article.question_pool_service import (
    SmartArticleQuestionPoolService,
    run_smart_question_batch,
)
from backend.services.smart_article.service import SmartArticleService, run_smart_article_batch


class QuestionPoolAdapter:
    """问题池适配器 - 给 Agent V2 工具层调用。"""

    def __init__(self, db: Session | None = None):
        self._db = db

    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def close(self) -> None:
        """如果 adapter 自己创建了 db session，则关闭。"""
        if self._db is not None:
            self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    #  问题规划（同步封装）
    # ------------------------------------------------------------------
    async def plan_batch_sync(
        self,
        user,
        project_id: int,
        count: int,
        mode: str = "auto",
        custom_question: str | None = None,
    ) -> tuple[int, list[int]]:
        """同步规划问题批次，等待 LLM 规划完成，返回 (batch_id, question_ids)。

        绕过 FastAPI BackgroundTasks，直接 await run_smart_question_batch。
        用 ORM 查询 generation_batch_id 精确拿本批次问题，避免混入历史问题。

        Args:
            user: 当前用户对象（含 id 属性）
            project_id: 项目ID
            count: 问题数量
            mode: "auto" 自动生成 / "manual" 手动输入
            custom_question: manual 模式时的问题文本

        Returns:
            (batch_id, question_ids)
        """
        db = self.db
        try:
            service = SmartArticleQuestionPoolService(db)
            # 1. 创建批次记录（同步，status=pending）
            batch = service.create_batch(
                current_user=user,
                project_id=project_id,
                question_count=count,
                custom_question=custom_question,
            )
            batch_id = batch.id
            logger.info(f"[QuestionPoolAdapter] plan_batch_sync 开始，batch_id={batch_id}")

            # 2. 同步等待 LLM 规划完成（阻塞当前协程，不阻塞事件循环）
            await run_smart_question_batch(batch_id)

            # 3. 重新查询批次状态
            db.expire_all()
            batch = db.query(SmartArticleBatch).filter(SmartArticleBatch.id == batch_id).first()
            if not batch:
                raise RuntimeError(f"批次 {batch_id} 不存在")
            if batch.status == "failed":
                raise RuntimeError(f"问题规划失败：{batch.note or '未知原因'}")

            # 4. 直接查 ORM 拿本批次的问题（避免 list_questions 混入历史问题）
            questions = (
                db.query(SmartArticleQuestion)
                .filter(
                    SmartArticleQuestion.generation_batch_id == batch_id,
                    SmartArticleQuestion.is_deleted.is_(False),
                )
                .order_by(SmartArticleQuestion.id.asc())
                .all()
            )
            question_ids = [q.id for q in questions]
            logger.info(
                f"[QuestionPoolAdapter] plan_batch_sync 完成，batch_id={batch_id}, "
                f"planned={batch.planned_count}, queued={batch.queued_count}, "
                f"question_ids={len(question_ids)}"
            )
            return batch_id, question_ids
        finally:
            # 不关闭 db，由调用方管理（如果是 adapter 自己创建的，则由 close() 关闭）
            pass

    # ------------------------------------------------------------------
    #  文章生成（异步在后台跑）
    # ------------------------------------------------------------------
    async def generate_articles_sync(
        self,
        user,
        project_id: int,
        question_ids: list[int],
    ) -> tuple[int, list[int]]:
        """创建文章生成批次，立即返回 (batch_id, skipped_question_ids)。

        文章实际生成用 asyncio.create_task 在后台跑，不阻塞当前协程。

        Args:
            user: 当前用户对象
            project_id: 项目ID
            question_ids: 要生成文章的问题ID列表

        Returns:
            (article_batch_id, skipped_question_ids)
        """
        db = self.db
        try:
            service = SmartArticleService(db)
            batch, skipped = service.create_selection_batch(
                current_user=user,
                project_id=project_id,
                question_ids=question_ids,
            )
            batch_id = batch.id
            logger.info(
                f"[QuestionPoolAdapter] generate_articles_sync 批次已创建，"
                f"batch_id={batch_id}, accepted={len(question_ids) - len(skipped)}, "
                f"skipped={len(skipped)}"
            )
            # 后台跑文章生成任务（不等完成）
            asyncio.create_task(run_smart_article_batch(batch_id))
            return batch_id, skipped
        except Exception as e:
            logger.error(f"[QuestionPoolAdapter] generate_articles_sync 失败: {e}")
            raise

    # ------------------------------------------------------------------
    #  问题查询
    # ------------------------------------------------------------------
    def list_questions(
        self,
        user,
        project_id: int,
        has_article: bool | None = None,
        generation_batch_id: int | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """列出项目下的问题。"""
        service = SmartArticleQuestionPoolService(self.db)
        return service.list_questions(
            current_user=user,
            project_id=project_id,
            has_article=has_article,
            page=page,
            limit=limit,
            generation_batch_id=generation_batch_id,
        )

    def get_question_batch_status(self, user, batch_id: int) -> dict[str, Any]:
        """查询问题批次状态。"""
        service = SmartArticleQuestionPoolService(self.db)
        return service.get_batch(batch_id, user)

    def soft_delete_questions(self, user, question_ids: list[int]) -> int:
        """软删除问题。"""
        service = SmartArticleQuestionPoolService(self.db)
        return service.soft_delete(user, question_ids)

    def get_many_questions(self, user, question_ids: list[int]) -> list[dict[str, Any]]:
        """批量查询问题详情。"""
        rows = (
            scoped_query(self.db, SmartArticleQuestion, user)
            .filter(
                SmartArticleQuestion.id.in_(question_ids),
                SmartArticleQuestion.is_deleted.is_(False),
            )
            .all()
        )
        return [
            {
                "id": row.id,
                "project_id": row.project_id,
                "question": row.question,
                "intent_type": row.intent_type,
                "has_article": row.has_article,
                "article_id": row.article_id,
                "article_generation_status": row.article_generation_status,
                "generation_batch_id": row.generation_batch_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
