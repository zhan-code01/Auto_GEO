# -*- coding: utf-8 -*-
"""批量文章生成服务（方案 §8 / §9.7 / §9.8，阶段7）。

把"一批搜索问题 → 一批文章"做成可控的批次/任务：

    create_batch(...)            # 建 ArticleGenerationBatch，立即返回 batch_id
      -> (后台) execute_batch    # 准备问题 -> 建 job -> 每个 job 调
         GeoArticleService.generate(publish_strategy="draft", source="agent_excel",
                                    generation_batch_id=batch.id)
      -> generate 直连 DeepSeek 同步返回正文，job 直接进入 completed

关键状态语义（文档 §5.1/§6.1）：**job 的"完成"= 正文已落库**。因此：
  - _run_job 触发成功且文章已落库即置 completed 并写 KeywordUsageRecord；
  - success_count / failed_count / batch.status 一律由 recompute_batch_status 从 job 真实状态汇总。

本期只生成、不发布（§2.2）。
"""

import asyncio
import hashlib
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.database.models import (
    AgentExcelImportRow,
    ArticleGenerationBatch,
    ArticleGenerationJob,
    GeoArticle,
    Keyword,
    KeywordUsageRecord,
    Project,
    User,
)
from backend.middleware.user_isolation import require_owner, scoped_query
from backend.services.geo_article_service import GeoArticleService
from backend.services.project_question_service import ProjectQuestionService


GENERATION_PROFILE = "excel_draft_v1"  # 幂等键的 profile 段

# 触发失败的内联自动重试间隔（秒）；文档 §6.3「触发失败可自动重试 1-2 次」
TRIGGER_RETRY_DELAY = 2.0

# job 状态：终态集合（不再变动，幂等守卫）
JOB_TERMINAL_STATES = {"completed", "failed", "skipped"}
# job 状态：仍在进行中（决定批次是否已结束）
JOB_ACTIVE_STATES = {"pending", "triggering", "running", "waiting_callback"}


def _idempotency_key(user_id: Optional[int], project_id: Optional[int], keyword_id: Optional[int]) -> str:
    raw = f"{user_id}:{project_id}:{keyword_id}:{GENERATION_PROFILE}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ArticleGenerationBatchService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- 归属 ----------

    def get_owned_batch(self, batch_id: int, user: User) -> ArticleGenerationBatch:
        batch = (
            self.db.query(ArticleGenerationBatch).filter(ArticleGenerationBatch.id == batch_id).first()
        )
        if not batch:
            raise ValueError("生成批次不存在")
        require_owner(batch, user, name="文章生成批次")
        return batch

    # ---------- 解析每个项目的生成计划 ----------

    def _plan_projects(
        self,
        *,
        user: User,
        import_batch_id: Optional[int],
        project_id: Optional[int],
        article_count: int,
        project_ids: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """返回 [{project_id, article_count}]。

        三种来源（优先级 project_id > project_ids > import_batch_id）：
        - project_id：单项目；
        - project_ids：非 Excel 跨项目批量（如「每个项目各生成 N 篇」），逐个校验归属；
        - import_batch_id：Excel 导入批次内全部 processed 行的项目。
        """
        if project_id:
            project = (
                scoped_query(self.db, Project, user)
                .filter(Project.id == project_id, Project.status == 1)
                .first()
            )
            if not project:
                raise ValueError("项目不存在或无权访问")
            return [{"project_id": project.id, "article_count": article_count}]

        if project_ids:
            cnt = max(1, min(10, int(article_count)))
            rows = (
                scoped_query(self.db, Project, user)
                .filter(Project.id.in_(list(project_ids)), Project.status == 1)
                .order_by(Project.id.asc())
                .all()
            )
            if not rows:
                raise ValueError("没有可生成的项目（项目不存在、已停用或无权访问）")
            return [{"project_id": p.id, "article_count": cnt} for p in rows]

        if not import_batch_id:
            raise ValueError("需要指定 project_id、project_ids 或 import_batch_id")

        rows = (
            self.db.query(AgentExcelImportRow)
            .filter(
                AgentExcelImportRow.batch_id == import_batch_id,
                AgentExcelImportRow.status == "processed",
                AgentExcelImportRow.project_id.isnot(None),
            )
            .order_by(AgentExcelImportRow.row_index.asc())
            .all()
        )
        plan: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            pid = row.project_id
            if pid in seen:
                continue
            seen.add(pid)
            # 用户在生成时设定的「每项目篇数」统一覆盖 Excel 列默认值。
            # （Excel 行的 article_count 在 normalize 后总有默认值，无法区分是否显式填写，
            # 故以生成时刻的用户输入为准，语义最可预测。）
            plan.append({"project_id": pid, "article_count": max(1, min(20, article_count))})
        return plan

    # ---------- 创建批次（立即返回，后台执行）----------

    def create_batch(
        self,
        *,
        user: User,
        import_batch_id: Optional[int] = None,
        project_id: Optional[int] = None,
        project_ids: Optional[List[int]] = None,
        article_count: int = 5,
    ) -> ArticleGenerationBatch:
        """创建生成批次并**立即返回**；实际生成在后台 execute_batch 中异步进行。

        ``project_ids``：非 Excel 的跨项目批量入口（如 Agent「每个项目各生成 N 篇」）。
        与 ``import_batch_id`` / ``project_id`` 三选一，优先级 project_id > project_ids > import_batch_id。
        """
        article_count = max(1, min(10, int(article_count)))
        plan = self._plan_projects(
            user=user,
            import_batch_id=import_batch_id,
            project_id=project_id,
            project_ids=project_ids,
            article_count=article_count,
        )
        if not plan:
            raise ValueError("没有可生成的项目（请先确认导入并创建客户/项目）")

        requested = sum(p["article_count"] for p in plan)
        # 多项目（非 Excel）时持久化 project_ids，供后台 execute_batch 重新推导计划
        multi_project_ids: Optional[List[int]] = None
        if project_ids and not project_id:
            multi_project_ids = [item["project_id"] for item in plan]
        source = "agent_batch" if multi_project_ids else "agent_excel"
        batch = ArticleGenerationBatch(
            user_id=user.id,
            import_batch_id=import_batch_id,
            project_id=plan[0]["project_id"] if len(plan) == 1 else None,
            project_ids=multi_project_ids,
            source=source,
            requested_count=requested,
            article_count=article_count,
            queued_count=0,
            success_count=0,
            failed_count=0,
            status="preparing_questions",
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)

        # 后台执行（独立 session，避免请求会话生命周期问题）。
        # 仅在有运行中的事件循环时（如 FastAPI 异步端点）派发；同步上下文（测试/脚本）下跳过，
        # 由调用方自行调用 execute_batch。
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_execute_batch_async(batch.id, user.id))
            logger.info(f"[gen_batch] 批次 {batch.id} 已创建（项目数 {len(plan)}，期望 {requested} 篇），后台执行中")
        except RuntimeError:
            logger.info(f"[gen_batch] 批次 {batch.id} 已创建（无事件循环，未自动派发后台执行）")
        return batch

    # ---------- 后台执行（用独立 session）----------

    async def execute_batch(self, batch_id: int, user_id: int) -> None:
        """准备问题 -> 建 job -> 逐个调 generate -> 写使用记录 -> 汇总状态。"""
        batch = self.db.query(ArticleGenerationBatch).filter(ArticleGenerationBatch.id == batch_id).first()
        if not batch:
            logger.error(f"[gen_batch] 批次 {batch_id} 不存在")
            return
        user = self.db.query(User).filter(User.id == user_id).first()

        try:
            # 推导生成计划：用批次持久化的「每项目篇数」（用户生成时设定，覆盖 Excel 列）。
            # 旧批次（升级前 article_count 为 NULL/0）回退 requested_count 兜底，保持兼容。
            per_project = max(1, min(10, int(batch.article_count or batch.requested_count or 5)))
            if batch.import_batch_id:
                plan = self._plan_from_import(batch.import_batch_id, per_project)
            elif batch.project_id:
                plan = [{"project_id": batch.project_id, "article_count": per_project}]
            elif batch.project_ids:
                plan = [
                    {"project_id": int(pid), "article_count": per_project} for pid in batch.project_ids
                ]
            else:
                plan = []

            # 1. 准备问题 + 建 job
            qsvc = ProjectQuestionService(self.db)
            jobs: List[ArticleGenerationJob] = []
            notes: List[str] = []
            for item in plan:
                pid = item["project_id"]
                cnt = item["article_count"]
                questions, note = await qsvc.prepare_questions(pid, cnt)
                if note:
                    notes.append(f"项目{pid}: {note}")
                for kw in questions:
                    key = _idempotency_key(user_id, pid, kw.id)
                    # 幂等：同 key 已存在任意 job 即跳过创建（含 failed/pending 重置态），
                    # 避免重跑或 retry 时为同一搜索问题造重复 job。
                    existing = (
                        self.db.query(ArticleGenerationJob)
                        .filter(ArticleGenerationJob.idempotency_key == key)
                        .first()
                    )
                    if existing:
                        continue
                    jobs.append(
                        ArticleGenerationJob(
                            batch_id=batch.id,
                            user_id=user_id,
                            project_id=pid,
                            keyword_id=kw.id,
                            idempotency_key=key,
                            status="pending",
                        )
                    )
            if jobs:
                self.db.bulk_save_objects(jobs)
            self.db.commit()

            # queued_count 累计（防重跑清零）；note 记补蒸馏不足原因
            batch.queued_count = (batch.queued_count or 0) + len(jobs)
            batch.status = "generating" if jobs else "completed"
            if notes:
                batch.note = "; ".join(notes)
            self.db.commit()

            # 2. 逐个执行 job（只跑 pending；retry/恢复重入时已 reset 的也会被捡起）
            gsvc = GeoArticleService(self.db)
            for job in (
                self.db.query(ArticleGenerationJob)
                .filter(ArticleGenerationJob.batch_id == batch.id, ArticleGenerationJob.status == "pending")
                .order_by(ArticleGenerationJob.id.asc())
                .all()
            ):
                await self._run_job(gsvc, batch, job, user_id)

            # 3. 汇总（job 状态 → batch 状态 + 计数）
            self.recompute_batch_status(batch)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"[gen_batch] 批次 {batch_id} 执行异常: {exc}")
            batch.status = "failed"
            batch.note = (batch.note or "") + f"；批次执行异常：{exc}"
            self.db.commit()

    def _plan_from_import(
        self, import_batch_id: Optional[int], article_count: int = 5
    ) -> List[Dict[str, Any]]:
        """导入批次的项目列表 + 每项目篇数。

        每项目篇数统一取 ``article_count``（生成时设定，覆盖 Excel 列默认值），
        与 ``_plan_projects`` 保持同一语义 —— Excel「生成篇数」列在批量生成入口
        不再单独生效，以生成时刻的用户输入为准。
        """
        if not import_batch_id:
            return []
        rows = (
            self.db.query(AgentExcelImportRow)
            .filter(
                AgentExcelImportRow.batch_id == import_batch_id,
                AgentExcelImportRow.status == "processed",
                AgentExcelImportRow.project_id.isnot(None),
            )
            .order_by(AgentExcelImportRow.row_index.asc())
            .all()
        )
        cnt = max(1, min(10, int(article_count)))
        plan: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            pid = row.project_id
            if pid in seen:
                continue
            seen.add(pid)
            plan.append({"project_id": pid, "article_count": cnt})
        return plan

    async def _run_job(
        self,
        gsvc: GeoArticleService,
        batch: ArticleGenerationBatch,
        job: ArticleGenerationJob,
        user_id: int,
    ) -> None:
        """触发单个 job 的文章生成。

        语义（文档 §6.1）：触发成功 → waiting_callback（等回调）；同步返回正文 → 直接 completed。
        触发失败 → 内联自动重试到 max_attempts，仍失败才 failed。
        success_count / failed_count 不在此自增，统一由 recompute_batch_status 汇总。
        """
        # 重入守卫：恢复扫描/重试可能与循环并发，只处理未开始的 job
        self.db.refresh(job)
        if job.status not in ("pending", "triggering"):
            return

        job.status = "triggering"
        job.started_at = datetime.now()
        self.db.commit()

        project = self.db.query(Project).filter(Project.id == job.project_id).first()
        keyword = self.db.query(Keyword).filter(Keyword.id == job.keyword_id).first()
        if not project or not keyword:
            self._mark_failed(job, batch, "项目或搜索问题不存在")
            self.recompute_batch_status(batch)
            return

        max_attempts = max(1, int(job.max_attempts or 2))
        result: Optional[Dict[str, Any]] = None
        last_err = "生成失败"

        while True:
            job.attempt_count = (job.attempt_count or 0) + 1
            self.db.commit()
            try:
                result = await gsvc.generate(
                    keyword_id=keyword.id,
                    company_name=project.company_name or "",
                    publish_strategy="draft",
                    user_id=user_id,
                    source="agent_excel",
                    generation_batch_id=batch.id,
                )
                if result.get("success") and result.get("article_id"):
                    break  # 触发成功
                last_err = (result.get("message") or "生成失败")[:500]
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[gen_batch] job {job.id} 第 {job.attempt_count} 次触发异常: {exc}")
                last_err = str(exc)[:500]

            # 触发失败：未达上限则退避后重试，否则判失败
            if job.attempt_count >= max_attempts:
                self._mark_failed(job, batch, last_err)
                self.recompute_batch_status(batch)
                return
            await asyncio.sleep(TRIGGER_RETRY_DELAY)

        # 触发成功：文章由 DeepSeek 同步生成，正文已落库 → 直接完成。
        article_id = result["article_id"]
        job.article_id = article_id
        article = self.db.get(GeoArticle, article_id)
        if article and article.publish_status in ("completed", "published"):
            self._mark_completed(job, batch, project=project, keyword=keyword, user_id=user_id)
        else:
            # 同步生成理应已落库；未完成则视为失败，避免 job 永久卡住。
            self._mark_failed(job, batch, "文章生成未完成")
        self.recompute_batch_status(batch)

    # ---------- job 状态流转（幂等）----------

    def _mark_completed(
        self,
        job: ArticleGenerationJob,
        batch: ArticleGenerationBatch,
        *,
        project: Optional[Project] = None,
        keyword: Optional[Keyword] = None,
        user_id: Optional[int] = None,
        source: str = "agent_excel",
    ) -> None:
        """把 job 置 completed，并幂等写 KeywordUsageRecord（文档 §7.3/§7.4）。

        幂等：job 已终态则不动；使用记录按 (article_id, keyword_id) 去重，避免重复回调写多条。
        不在此自增 success_count —— 交给 recompute_batch_status 汇总。
        """
        if job.status in JOB_TERMINAL_STATES:
            return
        if keyword is None:
            keyword = self.db.query(Keyword).filter(Keyword.id == job.keyword_id).first()
        if project is None:
            project = self.db.query(Project).filter(Project.id == job.project_id).first()

        # 幂等写使用记录
        if job.article_id and keyword:
            exists = (
                self.db.query(KeywordUsageRecord)
                .filter(
                    KeywordUsageRecord.article_id == job.article_id,
                    KeywordUsageRecord.keyword_id == keyword.id,
                )
                .first()
            )
            if not exists:
                try:
                    ProjectQuestionService(self.db).record_usage(
                        project_id=(project.id if project else job.project_id),
                        keyword=keyword,
                        article_id=job.article_id,
                        user_id=user_id if user_id is not None else job.user_id,
                        source=source,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[gen_batch] job {job.id} 写使用记录失败（忽略）: {exc}")

        job.status = "completed"
        job.completed_at = datetime.now()
        self.db.commit()

    def _mark_failed(
        self, job: ArticleGenerationJob, batch: ArticleGenerationBatch, error_msg: Optional[str]
    ) -> None:
        """把 job 置 failed（幂等：已终态则不动）。计数交给 recompute_batch_status。"""
        if job.status in JOB_TERMINAL_STATES:
            return
        job.status = "failed"
        job.error_msg = (error_msg or "未知错误")[:500]
        job.last_error_at = datetime.now()
        job.completed_at = datetime.now()
        self.db.commit()

    def recompute_batch_status(self, batch: ArticleGenerationBatch) -> None:
        """由本批 job 的真实状态汇总 batch.status + success/failed_count（文档 §7.4）。

        - 有 active job（pending/triggering/running/waiting_callback）：有 waiting_callback
          则 waiting_callback，否则 generating，并清 completed_at；
        - 否则全 completed→completed、全 failed→failed、混合→partial_failed，置 completed_at。
        success_count / failed_count 始终从 job 真实状态重算（自愈、防漂移）。
        """
        jobs = (
            self.db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).all()
        )
        if not jobs:
            batch.status = "failed"
            batch.success_count = 0
            batch.failed_count = 0
            self.db.commit()
            return

        counts = Counter(j.status for j in jobs)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        waiting = counts.get("waiting_callback", 0)
        active = sum(counts.get(s, 0) for s in JOB_ACTIVE_STATES)

        batch.success_count = completed
        batch.failed_count = failed

        if active > 0:
            batch.status = "waiting_callback" if waiting > 0 else "generating"
            batch.completed_at = None
        elif failed == 0:
            batch.status = "completed"
            batch.completed_at = datetime.now()
        elif completed == 0:
            batch.status = "failed"
            batch.completed_at = datetime.now()
        else:
            batch.status = "partial_failed"
            batch.completed_at = datetime.now()
        self.db.commit()
        logger.info(
            f"[gen_batch] 批次 {batch.id} 状态汇总：{batch.status}，"
            f"完成 {completed}，失败 {failed}，待回调 {waiting}"
        )

    # ---------- 失败重试 ----------

    def retry_failed_jobs(self, batch_id: int, user: User) -> Dict[str, Any]:
        """重置本批 failed job 为 pending 并重新派发（文档 §6.3 手动重试）。

        回调失败的 job 不自动重试，由用户在此触发：清空 attempt_count / error / 时间，
        job 回 pending，recompute 后后台重新 execute_batch（只跑 pending）。
        """
        batch = self.get_owned_batch(batch_id, user)
        failed_jobs = (
            self.db.query(ArticleGenerationJob)
            .filter(ArticleGenerationJob.batch_id == batch.id, ArticleGenerationJob.status == "failed")
            .all()
        )
        reset = 0
        for j in failed_jobs:
            j.status = "pending"
            j.attempt_count = 0
            j.error_msg = None
            j.last_error_at = None
            j.started_at = None
            j.completed_at = None
            reset += 1
        self.db.commit()
        self.recompute_batch_status(batch)

        if reset:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_execute_batch_async(batch.id, batch.user_id))
                logger.info(f"[gen_batch] 批次 {batch.id} 重试 {reset} 个失败 job")
            except RuntimeError:
                logger.warning(f"[gen_batch] 批次 {batch.id} 重试：无事件循环，未自动派发")
        return {"reset_count": reset, "batch_id": batch.id, "status": batch.status}


    # ---------- 状态查询 ----------

    def get_status(self, batch_id: int, user: User) -> Dict[str, Any]:
        batch = self.get_owned_batch(batch_id, user)
        jobs = (
            self.db.query(ArticleGenerationJob)
            .filter(ArticleGenerationJob.batch_id == batch.id)
            .order_by(ArticleGenerationJob.id.asc())
            .all()
        )
        from backend.database.models import Keyword

        job_list = []
        for j in jobs:
            kw = self.db.query(Keyword).filter(Keyword.id == j.keyword_id).first()
            job_list.append(
                {
                    "job_id": j.id,
                    "project_id": j.project_id,
                    "keyword_id": j.keyword_id,
                    "question": kw.keyword if kw else None,
                    "status": j.status,
                    "article_id": j.article_id,
                    "error_msg": j.error_msg,
                    "attempt_count": j.attempt_count,
                    "max_attempts": j.max_attempts,
                }
            )
        return {
            "batch_id": batch.id,
            "status": batch.status,
            "source": batch.source,
            "requested_count": batch.requested_count,
            "queued_count": batch.queued_count,
            "success_count": batch.success_count,
            "failed_count": batch.failed_count,
            "note": batch.note,
            "import_batch_id": batch.import_batch_id,
            "project_id": batch.project_id,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "jobs": job_list,
        }

    def list_user_batches(self, user: User, limit: int = 20) -> List[ArticleGenerationBatch]:
        return (
            scoped_query(self.db, ArticleGenerationBatch, user)
            .order_by(ArticleGenerationBatch.created_at.desc())
            .limit(limit)
            .all()
        )


async def _execute_batch_async(batch_id: int, user_id: int) -> None:
    """后台执行入口：用独立 DB session 跑 execute_batch。"""
    db = SessionLocal()
    try:
        await ArticleGenerationBatchService(db).execute_batch(batch_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[gen_batch] 后台执行失败 batch={batch_id}: {exc}")
    finally:
        db.close()
