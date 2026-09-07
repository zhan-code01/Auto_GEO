from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.database.models import (
    GeoArticle,
    Keyword,
    Project,
    SmartArticleBatch,
    SmartArticleJob,
    SmartArticleQuestion,
)
from backend.services.article_image_service import ArticleImageService
from backend.services.article_markdown import markdown_to_html
from backend.middleware.user_isolation import scoped_query
from .article_writer import SmartArticleWriter
from .brief_builder import SmartArticleBriefBuilder
from .context_builder import SmartArticleContextError, build_project_context
from .content_formatter import ensure_company_website_link, remove_duplicate_leading_title
from .knowledge_service import SmartArticleKnowledgeService
from .research import SmartArticleResearchCoordinator
from .prompts import PROMPT_VERSIONS
from .question_planner import QuestionPlanningError, SmartArticleQuestionPlanner, normalize_question
from .schemas import PlannedQuestion


DEFAULT_CONCURRENCY = int(os.getenv("SMART_ARTICLE_CONCURRENCY", "6"))


class SmartArticleService:
    def __init__(self, db: Session):
        self.db = db
        self.images = ArticleImageService()

    def create_batch(
        self, current_user, project_id: int, article_count: int, question: str | None
    ) -> SmartArticleBatch:
        if article_count < 1:
            raise ValueError("文章数量必须大于0")
        normalized_question = str(question or "").strip() or None
        mode = "manual" if normalized_question else "auto"
        if normalized_question:
            article_count = 1
        # Validate project and required fields before creating a batch.
        build_project_context(self.db, project_id, current_user)
        batch = SmartArticleBatch(
            user_id=current_user.id,
            project_id=project_id,
            mode=mode,
            requested_count=article_count,
            input_question=normalized_question,
            status="pending",
            question_prompt_version=None if mode == "manual" else PROMPT_VERSIONS["question"],
            filter_prompt_version=None if mode == "manual" else PROMPT_VERSIONS["filter"],
            query_rewrite_prompt_version=PROMPT_VERSIONS["query_rewrite"],
            article_prompt_version=PROMPT_VERSIONS["article"],
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def create_selection_batch(
        self, current_user, project_id: int, question_ids: list[int]
    ) -> tuple[SmartArticleBatch, list[int]]:
        """Create an article batch from visible, not-yet-generated question rows."""
        if not question_ids:
            raise ValueError("请至少选择一个未生成文章的问题")
        context = build_project_context(self.db, project_id, current_user)
        rows = (
            scoped_query(self.db, SmartArticleQuestion, current_user)
            .filter(
                SmartArticleQuestion.project_id == project_id,
                SmartArticleQuestion.id.in_(question_ids),
                SmartArticleQuestion.is_deleted.is_(False),
            )
            .with_for_update()
            .all()
        )
        by_id = {row.id: row for row in rows}
        accepted: list[SmartArticleQuestion] = []
        skipped: list[int] = []
        for question_id in dict.fromkeys(question_ids):
            row = by_id.get(question_id)
            if not row or row.has_article or row.article_generation_status == "generating":
                skipped.append(question_id)
                continue
            accepted.append(row)
        if not accepted:
            raise ValueError("所选问题均已生成文章或正在生成中")

        batch = SmartArticleBatch(
            user_id=current_user.id,
            project_id=project_id,
            batch_type="article_generation",
            mode="selection",
            requested_count=len(accepted),
            queued_count=len(accepted),
            status="creating_jobs",
            query_rewrite_prompt_version=PROMPT_VERSIONS["query_rewrite"],
            article_prompt_version=PROMPT_VERSIONS["article"],
        )
        self.db.add(batch)
        self.db.flush()
        self._create_jobs_for_questions(batch, accepted, context)
        for row in accepted:
            row.article_generation_status = "generating"
        batch.status = "generating"
        self.db.commit()
        self.db.refresh(batch)
        return batch, skipped

    def _create_jobs_for_questions(
        self, batch: SmartArticleBatch, questions: list[SmartArticleQuestion], context
    ) -> list[int]:
        keyword_by_text = {
            row.keyword: row
            for row in self.db.query(Keyword)
            .filter(Keyword.project_id == context.project_id, Keyword.keyword_type == "smart_question")
            .all()
        }
        job_ids: list[int] = []
        for question_row in questions:
            key = hashlib.sha256(
                f"{batch.user_id}|{batch.project_id}|{batch.id}|question:{question_row.id}|{PROMPT_VERSIONS['article']}".encode(
                    "utf-8"
                )
            ).hexdigest()
            keyword_obj = keyword_by_text.get(question_row.question)
            if keyword_obj is None:
                keyword_obj = Keyword(
                    project_id=context.project_id,
                    keyword=question_row.question,
                    keyword_type="smart_question",
                    status="active",
                )
                self.db.add(keyword_obj)
                self.db.flush()
                keyword_by_text[question_row.question] = keyword_obj
            article = GeoArticle(
                keyword_id=keyword_obj.id,
                project_id=context.project_id,
                user_id=batch.user_id,
                title="[智能文章生成中]...",
                content="正在生成，请稍后刷新...",
                publish_status="generating",
                publish_strategy="draft",
                target_platforms=None,
                platform=None,
                account_id=None,
                source="smart_article",
            )
            self.db.add(article)
            self.db.flush()
            job = SmartArticleJob(
                batch_id=batch.id,
                user_id=batch.user_id,
                project_id=context.project_id,
                question_id=question_row.id,
                question=question_row.question,
                intent_type=question_row.intent_type,
                context_type=question_row.context_type,
                brand_entry_reason=question_row.brand_entry_reason,
                retrieval_terms=question_row.retrieval_terms or [],
                keyword_id=keyword_obj.id,
                article_id=article.id,
                idempotency_key=key,
                status="pending",
            )
            self.db.add(job)
            self.db.flush()
            job_ids.append(job.id)
        return job_ids

    async def run_batch(self, batch_id: int) -> None:
        batch = self.db.query(SmartArticleBatch).filter(SmartArticleBatch.id == batch_id).first()
        if not batch:
            return
        if batch.batch_type == "article_generation" and batch.mode == "selection":
            job_ids = [job.id for job in batch.jobs if job.status in {"pending", "failed"}]
            if not job_ids:
                self._refresh_batch(batch_id)
                return
            batch.status = "generating"
            self.db.commit()
            await self._execute_jobs(job_ids)
            self._refresh_batch(batch_id)
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
            batch.planned_count = len(planned)
            batch.status = "creating_jobs"
            self.db.commit()
            job_ids = self._create_jobs(batch, planned, context)
            if not job_ids:
                raise RuntimeError("没有创建任何文章任务")
            batch.queued_count = len(job_ids)
            batch.status = "generating"
            self.db.commit()
        except (SmartArticleContextError, QuestionPlanningError, ValueError, RuntimeError) as exc:
            batch.status = "failed"
            batch.note = f"阶段=问题规划/任务创建：{exc}"
            batch.completed_at = datetime.now()
            self.db.commit()
            logger.error("智能文章批次 {} 创建失败: {}", batch_id, exc)
            return
        except Exception as exc:  # noqa: BLE001
            batch.status = "failed"
            batch.note = f"阶段=问题规划/任务创建：{exc}"
            batch.completed_at = datetime.now()
            self.db.commit()
            logger.exception("智能文章批次 {} 未知失败", batch_id)
            return

        await self._execute_jobs(job_ids)
        self._refresh_batch(batch_id)

    async def _execute_jobs(self, job_ids: list[int]) -> None:
        semaphore = asyncio.Semaphore(DEFAULT_CONCURRENCY)

        async def run_one(job_id: int) -> None:
            async with semaphore:
                await process_smart_article_job(job_id)

        await asyncio.gather(*(run_one(job_id) for job_id in job_ids))

    def _create_jobs(self, batch: SmartArticleBatch, planned: list[PlannedQuestion], context) -> list[int]:
        existing = {job.idempotency_key for job in batch.jobs}
        keyword_by_normalized = {
            normalize_question(row.keyword): row
            for row in self.db.query(Keyword)
            .filter(Keyword.project_id == context.project_id, Keyword.keyword_type == "smart_question")
            .all()
        }
        job_ids: list[int] = []
        for item in planned:
            key = hashlib.sha256(
                f"{batch.user_id}|{batch.project_id}|{batch.id}|{normalize_question(item.question)}|{PROMPT_VERSIONS['article']}".encode(
                    "utf-8"
                )
            ).hexdigest()
            if key in existing:
                continue
            normalized = normalize_question(item.question)
            keyword_obj = keyword_by_normalized.get(normalized)
            if keyword_obj is None:
                keyword_obj = Keyword(
                    project_id=context.project_id,
                    keyword=item.question,
                    keyword_type="smart_question",
                    status="active",
                )
                self.db.add(keyword_obj)
                self.db.flush()
                keyword_by_normalized[normalized] = keyword_obj

            article = GeoArticle(
                keyword_id=keyword_obj.id,
                project_id=context.project_id,
                user_id=batch.user_id,
                title="[智能文章生成中]...",
                content="正在生成，请稍后刷新...",
                publish_status="generating",
                publish_strategy="draft",
                target_platforms=None,
                platform=None,
                account_id=None,
                source="smart_article",
            )
            self.db.add(article)
            self.db.flush()
            job = SmartArticleJob(
                batch_id=batch.id,
                user_id=batch.user_id,
                project_id=context.project_id,
                question=item.question,
                intent_type=item.intent_type,
                context_type=item.context_type,
                brand_entry_reason=item.brand_entry_reason,
                retrieval_terms=item.retrieval_terms,
                keyword_id=keyword_obj.id,
                article_id=article.id,
                idempotency_key=key,
                status="pending",
            )
            self.db.add(job)
            self.db.flush()
            job_ids.append(job.id)
            existing.add(key)
        self.db.commit()
        return job_ids

    def _refresh_batch(self, batch_id: int) -> None:
        batch = self.db.query(SmartArticleBatch).filter(SmartArticleBatch.id == batch_id).first()
        if not batch:
            return
        jobs = self.db.query(SmartArticleJob).filter(SmartArticleJob.batch_id == batch_id).all()
        batch.success_count = sum(job.status == "completed" for job in jobs)
        batch.failed_count = sum(job.status == "failed" for job in jobs)
        if jobs and all(job.status in {"completed", "failed"} for job in jobs):
            batch.status = (
                "completed" if batch.failed_count == 0 else ("partial_failed" if batch.success_count else "failed")
            )
            batch.completed_at = datetime.now()
        self.db.commit()

    def get_batch(self, batch_id: int, current_user) -> dict[str, Any]:
        batch = scoped_query(self.db, SmartArticleBatch, current_user).filter(SmartArticleBatch.id == batch_id).first()
        if not batch:
            raise LookupError("批次不存在或无权访问")
        jobs = scoped_query(self.db, SmartArticleJob, current_user).filter(SmartArticleJob.batch_id == batch_id).all()
        return {
            "batch_id": batch.id,
            "project_id": batch.project_id,
            "mode": batch.mode,
            "status": batch.status,
            "requested_count": batch.requested_count,
            "planned_count": batch.planned_count,
            "queued_count": batch.queued_count,
            "success_count": batch.success_count,
            "failed_count": batch.failed_count,
            "processing_count": sum(job.status not in {"completed", "failed"} for job in jobs),
            "note": batch.note,
            "jobs": [
                {
                    "id": job.id,
                    "question": job.question,
                    "status": job.status,
                    "article_id": job.article_id,
                    "error_msg": job.error_msg,
                }
                for job in jobs
            ],
        }

    def list_articles(
        self, current_user, project_id: int | None, publish_status: str | None, page: int, limit: int
    ) -> dict[str, Any]:
        query = scoped_query(self.db, GeoArticle, current_user).filter(GeoArticle.source == "smart_article")
        if project_id is not None:
            query = query.filter(GeoArticle.project_id == project_id)
        if publish_status:
            query = query.filter(GeoArticle.publish_status == publish_status)
        total = query.count()
        rows = query.order_by(GeoArticle.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {"total": total, "items": [_article_dict(row) for row in rows]}

    def retry_job(self, job_id: int, current_user) -> int:
        job = scoped_query(self.db, SmartArticleJob, current_user).filter(SmartArticleJob.id == job_id).first()
        if not job:
            raise LookupError("任务不存在或无权访问")
        if job.status != "failed":
            raise ValueError("只有失败任务可以重试")
        job.status = "pending"
        job.error_msg = None
        job.attempt_count = 0
        if job.question_id:
            question = self.db.query(SmartArticleQuestion).filter(SmartArticleQuestion.id == job.question_id).first()
            if question and not question.has_article:
                question.article_generation_status = "generating"
        if job.article_id:
            article = self.db.query(GeoArticle).filter(GeoArticle.id == job.article_id).first()
            if article:
                article.publish_status = "generating"
                article.error_msg = None
        self.db.commit()
        return job.id


async def process_smart_article_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(SmartArticleJob).filter(SmartArticleJob.id == job_id).first()
        if not job:
            return
        service = SmartArticleService(db)
        owner = SimpleNamespace(id=job.user_id, role="user")
        context = build_project_context(db, job.project_id, owner)
        planned = PlannedQuestion(
            question=job.question,
            intent_type=job.intent_type,
            context_type=job.context_type,
            brand_entry_reason=job.brand_entry_reason or "",
            retrieval_terms=job.retrieval_terms or [],
        )
        job.status = "retrieving"
        job.started_at = datetime.now()
        job.attempt_count = (job.attempt_count or 0) + 1
        db.commit()
        knowledge = await SmartArticleKnowledgeService(db).retrieve(context, planned)
        job.initial_queries = [item.as_dict() for item in knowledge.initial_queries]
        job.retrieval_queries = [item.as_dict() for item in knowledge.retrieval_queries]
        job.retrieval_rounds = knowledge.retrieval_rounds
        job.query_rewrite_used = knowledge.query_rewrite_used
        job.query_rewrite_prompt_version = PROMPT_VERSIONS["query_rewrite"] if knowledge.query_rewrite_used else None
        job.retrieval_raw_count = knowledge.raw_count
        job.retrieval_valid_count = knowledge.valid_count
        job.knowledge_enabled = knowledge.status == "available"
        job.knowledge_refs = _chunk_refs(knowledge.chunks)
        db.commit()

        # 多角色资料研究：三个LLM研究角色并行（仅并行网络调用，不共享Session）。
        job.status = "researching"
        db.commit()
        research = await SmartArticleResearchCoordinator().run(context, planned, knowledge)
        for warning in research.warnings:
            logger.warning("智能文章任务 {} 研究降级: {}", job_id, warning)

        # 资料整合：生成文章写作简报（失败时确定性兜底，不阻断）。
        brief = await SmartArticleBriefBuilder().build(context, planned, knowledge, research)

        writer = SmartArticleWriter()
        generated = None
        feedback = ""
        for _attempt in range(3):
            job.status = "generating"
            db.commit()
            try:
                generated = await writer.write(context, planned, knowledge, feedback, brief=brief)
                break
            except Exception as exc:  # noqa: BLE001
                feedback = f"上一次输出未通过校验：{exc}。请重新输出完整JSON并修复格式。"
                if _attempt == 2:
                    raise RuntimeError(f"阶段=格式校验/文章生成：{exc}") from exc
        if generated is None:
            raise RuntimeError("阶段=文章生成：未返回文章")

        article = db.query(GeoArticle).filter(GeoArticle.id == job.article_id).first()
        if not article:
            raise RuntimeError("阶段=保存：文章占位记录不存在")
        job.status = "processing_images"
        db.commit()
        body_without_duplicate_title = remove_duplicate_leading_title(generated.content, generated.title)
        # 官网链接确定性兜底：正文首次出现公司名必须带官网链接；官网为空记录warning不阻断。
        if context.website:
            body_without_duplicate_title, linked = ensure_company_website_link(
                body_without_duplicate_title, context.company_name, context.website
            )
            if not linked:
                logger.warning("智能文章任务 {}：正文未出现公司名，无法插入官网链接", job_id)
        else:
            logger.warning("智能文章任务 {}：客户官网为空，跳过公司名官网链接", job_id)
        processed = await service.images.process_article_images(
            body_without_duplicate_title, article_id=article.id, keyword=job.question, title=generated.title
        )
        article.title = generated.title
        article.content = markdown_to_html(processed)
        article.publish_status = "completed"
        article.publish_strategy = "draft"
        article.source = "smart_article"
        article.error_msg = None
        job.status = "saving"
        db.commit()
        job.status = "completed"
        job.completed_at = datetime.now()
        if job.question_id:
            question_row = db.query(SmartArticleQuestion).filter(SmartArticleQuestion.id == job.question_id).first()
            if question_row:
                question_row.has_article = True
                question_row.article_id = article.id
                question_row.article_generation_status = "generated"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("智能文章任务 {} 失败", job_id)
        _mark_job_failed(db, job_id, str(exc))
    finally:
        db.close()


def _mark_job_failed(db: Session, job_id: int, message: str) -> None:
    job = db.query(SmartArticleJob).filter(SmartArticleJob.id == job_id).first()
    if not job:
        return
    job.status = "failed"
    job.error_msg = message[:2000]
    job.completed_at = datetime.now()
    if job.question_id:
        question_row = db.query(SmartArticleQuestion).filter(SmartArticleQuestion.id == job.question_id).first()
        if question_row and not question_row.has_article:
            question_row.article_generation_status = "failed"
    if job.article_id:
        article = db.query(GeoArticle).filter(GeoArticle.id == job.article_id).first()
        if article:
            article.publish_status = "failed"
            article.error_msg = message[:2000]
    db.commit()
    batch = db.query(SmartArticleBatch).filter(SmartArticleBatch.id == job.batch_id).first()
    if batch:
        jobs = db.query(SmartArticleJob).filter(SmartArticleJob.batch_id == batch.id).all()
        batch.success_count = sum(item.status == "completed" for item in jobs)
        batch.failed_count = sum(item.status == "failed" for item in jobs)
        if jobs and all(item.status in {"completed", "failed"} for item in jobs):
            batch.status = (
                "completed" if batch.failed_count == 0 else ("partial_failed" if batch.success_count else "failed")
            )
            batch.completed_at = datetime.now()
        db.commit()


def _chunk_refs(chunks: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "chunk": index,
            "id": chunk.get("id") or chunk.get("chunk_id"),
            "document_id": chunk.get("document_id") or chunk.get("doc_id"),
            "similarity": chunk.get("similarity", chunk.get("vector_similarity")),
        }
        for index, chunk in enumerate(chunks, start=1)
    ]


def _article_dict(article: GeoArticle) -> dict[str, Any]:
    return {
        "id": article.id,
        "keyword_id": article.keyword_id,
        "project_id": article.project_id,
        "title": article.title,
        "content": article.content,
        "quality_score": article.quality_score,
        "publish_status": article.publish_status,
        "publish_strategy": article.publish_strategy or "draft",
        "source": article.source,
        "error_msg": article.error_msg,
        "created_at": article.created_at.isoformat() if article.created_at else None,
        "updated_at": article.updated_at.isoformat() if article.updated_at else None,
    }


async def run_smart_article_batch(batch_id: int) -> None:
    db = SessionLocal()
    try:
        await SmartArticleService(db).run_batch(batch_id)
    finally:
        db.close()
