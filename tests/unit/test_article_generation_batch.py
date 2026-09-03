# -*- coding: utf-8 -*-
"""批量文章生成服务单测（方案 §8 / §9.7，阶段7）。

不打 n8n：monkeypatch ``GeoArticleService.generate`` 创建真实 GeoArticle 占位并返回 id，
验证批次创建、job 执行、source/generation_batch_id 回填、使用记录、状态汇总。
"""

import asyncio

import pytest

from backend.services.article_generation_batch_service import (
    ArticleGenerationBatchService,
    _idempotency_key,
)


@pytest.fixture
def gen_user(db):
    from backend.database.models import User

    user = User(username="gen_test_user", email="gen_test@test.local", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    from backend.database.models import (
        AgentExcelImportRow,
        AgentExcelImportBatch,
        KeywordUsageRecord,
        ArticleGenerationJob,
        ArticleGenerationBatch,
        GeoArticle,
        Keyword,
        Project,
        Client,
        User as U,
    )

    db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == user.id).delete(synchronize_session=False)
    db.query(ArticleGenerationJob).delete(synchronize_session=False)
    db.query(ArticleGenerationBatch).filter(ArticleGenerationBatch.user_id == user.id).delete(synchronize_session=False)
    db.query(GeoArticle).filter(GeoArticle.user_id == user.id).delete(synchronize_session=False)
    db.query(AgentExcelImportRow).delete()
    db.query(AgentExcelImportBatch).delete()
    db.query(Keyword).filter(
        Keyword.project_id.in_(db.query(Project.id).filter(Project.user_id == user.id))
    ).delete(synchronize_session=False)
    db.query(Project).filter(Project.user_id == user.id).delete(synchronize_session=False)
    db.query(Client).filter(Client.user_id == user.id).delete(synchronize_session=False)
    db.query(U).filter(U.id == user.id).delete()
    db.commit()


def _seed(db, user, *, n_questions=5, article_count=3):
    """建 client/project + 导入批次(processed 行, project_id 已回填) + N 个未使用问题。"""
    from backend.database.models import (
        AgentExcelImportBatch,
        AgentExcelImportRow,
        Client,
        Keyword,
        Project,
    )

    client = Client(name="生成公司", company_name="生成公司", user_id=user.id, status=1)
    db.add(client); db.commit(); db.refresh(client)
    project = Project(
        user_id=user.id, client_id=client.id, name="生成项目", company_name="生成公司",
        domain_keyword="批量关键词", status=1,
    )
    db.add(project); db.commit(); db.refresh(project)

    batch = AgentExcelImportBatch(user_id=user.id, status="ready", default_article_count=article_count)
    db.add(batch); db.commit(); db.refresh(batch)
    row = AgentExcelImportRow(
        batch_id=batch.id, row_index=2, status="processed",
        normalized_data={"company_name": "生成公司", "project_name": "生成项目", "core_keyword": "批量关键词", "article_count": article_count},
        client_id=client.id, project_id=project.id,
    )
    db.add(row); db.commit(); db.refresh(row)

    for i in range(n_questions):
        db.add(Keyword(project_id=project.id, keyword=f"搜索问题{i}", keyword_type="question", status="active"))
    db.commit()
    return client, project, batch


def _mock_generate(monkeypatch):
    """generate() 创建真实 GeoArticle 占位（completed）并返回 id。"""
    from backend.database.models import GeoArticle
    from backend.services.geo_article_service import GeoArticleService

    async def fake_generate(self, keyword_id, company_name, publish_strategy="draft", user_id=None,
                            source=None, generation_batch_id=None, **kw):
        art = GeoArticle(
            keyword_id=keyword_id, project_id=None, user_id=user_id,
            title=f"文章-{keyword_id}", content="正文", publish_status="completed",
            publish_strategy=publish_strategy, source=source, generation_batch_id=generation_batch_id,
        )
        self.db.add(art); self.db.commit(); self.db.refresh(art)
        return {"success": True, "article_id": art.id}

    monkeypatch.setattr(GeoArticleService, "generate", fake_generate)


def _mock_generate_async(monkeypatch):
    """generate() 创建 generating 占位文章（模拟 n8n 异步：只触发，等回调）。"""
    from backend.database.models import GeoArticle
    from backend.services.geo_article_service import GeoArticleService

    async def fake_generate(self, keyword_id, company_name, publish_strategy="draft", user_id=None,
                            source=None, generation_batch_id=None, **kw):
        art = GeoArticle(
            keyword_id=keyword_id, project_id=None, user_id=user_id,
            title="[AI正在创作中]...", content="", publish_status="generating",
            publish_strategy=publish_strategy, source=source, generation_batch_id=generation_batch_id,
        )
        self.db.add(art); self.db.commit(); self.db.refresh(art)
        return {"success": True, "article_id": art.id}

    monkeypatch.setattr(GeoArticleService, "generate", fake_generate)


def _mock_generate_fail(monkeypatch):
    """generate() 始终返回失败（触发失败）。"""
    from backend.services.geo_article_service import GeoArticleService

    async def fake_generate(self, *a, **kw):
        return {"success": False, "message": "n8n 触发失败"}

    monkeypatch.setattr(GeoArticleService, "generate", fake_generate)


def _no_retry_delay(monkeypatch):
    """把触发重试间隔压成 0，避免测试里真睡。"""
    import backend.services.article_generation_batch_service as m
    monkeypatch.setattr(m, "TRIGGER_RETRY_DELAY", 0.0)


def _kill_bg(monkeypatch):
    """禁止 create_batch 的后台任务，便于单独测 execute_batch。"""
    import backend.services.article_generation_batch_service as m

    async def noop(batch_id, user_id):
        return None

    monkeypatch.setattr(m, "_execute_batch_async", noop)


class TestCreateBatch:
    def test_creates_batch_record(self, db, gen_user, monkeypatch):
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user)
        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=3)
        assert batch.status == "preparing_questions"
        assert batch.source == "agent_excel"
        assert batch.requested_count == 3
        assert batch.import_batch_id == imp.id

    def test_no_projects_raises(self, db, gen_user, monkeypatch):
        _kill_bg(monkeypatch)
        svc = ArticleGenerationBatchService(db)
        with pytest.raises(ValueError):
            svc.create_batch(user=gen_user, article_count=3)


class TestExecuteBatch:
    def test_full_run_success(self, db, gen_user, monkeypatch):
        from backend.database.models import (
            ArticleGenerationJob,
            GeoArticle,
            KeywordUsageRecord,
        )

        _mock_generate(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=5, article_count=3)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=3)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))

        db.refresh(batch)
        assert batch.status == "completed"
        assert batch.success_count == 3
        assert batch.failed_count == 0
        assert batch.queued_count == 3

        jobs = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).all()
        assert len(jobs) == 3
        assert all(j.status == "completed" and j.article_id for j in jobs)

        # 文章带 source/batch_id
        arts = db.query(GeoArticle).filter(GeoArticle.generation_batch_id == batch.id).all()
        assert len(arts) == 3
        assert all(a.source == "agent_excel" for a in arts)

        # 使用记录
        recs = db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == gen_user.id).all()
        assert len(recs) == 3

    def test_idempotency_skips_duplicate_key(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob
        from backend.services.keyword_service import KeywordService

        _mock_generate(monkeypatch)
        _kill_bg(monkeypatch)

        # 第二次执行时问题已用尽，补蒸馏应返回空（不调用真实 n8n）
        async def empty_distill(self, **kwargs):
            return {"status": "success"}

        monkeypatch.setattr(KeywordService, "distill", empty_distill)

        client, project, imp = _seed(db, gen_user, n_questions=3, article_count=3)
        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=3)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))
        n1 = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).count()

        # 再次执行同批次：问题已被使用（有文章），prepare_questions 会补蒸馏(mocked? no)→ 0 新问题 → 0 新 job
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))
        n2 = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).count()
        assert n1 == n2  # 不重复建 job

    def test_status_summary(self, db, gen_user, monkeypatch):
        _mock_generate(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=5, article_count=5)
        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=5)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))
        status = svc.get_status(batch.id, gen_user)
        assert status["status"] == "completed"
        assert status["success_count"] == 5
        assert len(status["jobs"]) == 5
        assert status["jobs"][0]["question"]  # 带搜索问题文本


class TestCallbackSemantics:
    """job 完成语义：等 n8n 回调成功且正文落库才算 completed（文档 §5.1/§6.1）。"""

    def test_async_job_waits_then_callback_completes(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob, GeoArticle, KeywordUsageRecord

        _mock_generate_async(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=2, article_count=2)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=2)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))

        db.refresh(batch)
        # 触发后：job 落 waiting_callback，不计成功，不写使用记录
        assert batch.status == "waiting_callback"
        assert batch.success_count == 0
        jobs = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).all()
        assert len(jobs) == 2
        assert all(j.status == "waiting_callback" for j in jobs)
        assert all(j.article_id for j in jobs)
        assert (
            db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == gen_user.id).count() == 0
        )

        # 模拟 n8n 回调成功：文章置 completed → on_article_callback
        for j in jobs:
            art = db.query(GeoArticle).filter(GeoArticle.id == j.article_id).first()
            art.publish_status = "completed"
            db.commit()
            svc.on_article_callback(art, success=True)

        db.refresh(batch)
        assert batch.status == "completed"
        assert batch.success_count == 2
        for j in jobs:
            db.refresh(j)
        assert all(j.status == "completed" for j in jobs)
        assert (
            db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == gen_user.id).count() == 2
        )

    def test_callback_failure_marks_failed_no_usage(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob, GeoArticle, KeywordUsageRecord

        _mock_generate_async(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=2, article_count=2)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=2)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))

        jobs = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).all()
        # 第 1 个回调成功，第 2 个回调失败
        art0 = db.query(GeoArticle).filter(GeoArticle.id == jobs[0].article_id).first()
        art0.publish_status = "completed"
        db.commit()
        svc.on_article_callback(art0, success=True)

        art1 = db.query(GeoArticle).filter(GeoArticle.id == jobs[1].article_id).first()
        art1.publish_status = "failed"
        art1.error_msg = "生成超时"
        db.commit()
        svc.on_article_callback(art1, success=False, error="生成超时")

        db.refresh(batch)
        assert batch.status == "partial_failed"
        assert batch.success_count == 1
        assert batch.failed_count == 1
        db.refresh(jobs[0]); db.refresh(jobs[1])
        assert jobs[0].status == "completed"
        assert jobs[1].status == "failed"
        assert jobs[1].error_msg == "生成超时"
        # 失败的 job 不写使用记录
        assert (
            db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == gen_user.id).count() == 1
        )

    def test_duplicate_callback_idempotent(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob, GeoArticle, KeywordUsageRecord

        _mock_generate_async(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=1, article_count=1)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=1)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))

        job = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).one()
        art = db.query(GeoArticle).filter(GeoArticle.id == job.article_id).first()
        art.publish_status = "completed"
        db.commit()
        # 模拟 n8n 重复回调两次
        svc.on_article_callback(art, success=True)
        svc.on_article_callback(art, success=True)

        db.refresh(batch)
        assert batch.success_count == 1  # 不翻倍
        assert (
            db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == gen_user.id).count() == 1
        )

    def test_trigger_failure_marks_failed(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob

        _mock_generate_fail(monkeypatch)
        _no_retry_delay(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=2, article_count=2)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=2)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))

        db.refresh(batch)
        assert batch.status == "failed"
        assert batch.failed_count == 2
        jobs = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).all()
        assert all(j.status == "failed" for j in jobs)
        # 触发失败自动重试到 max_attempts
        assert all(j.attempt_count == 2 for j in jobs)


class TestRetry:
    def test_retry_resets_failed_jobs(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob

        _mock_generate_fail(monkeypatch)
        _no_retry_delay(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=1, article_count=1)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=1)
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))

        job = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).one()
        assert job.status == "failed"

        # 手动重试（同步测试无事件循环，不会真派发后台任务，只验重置）
        result = svc.retry_failed_jobs(batch.id, gen_user)
        assert result["reset_count"] == 1

        db.refresh(job); db.refresh(batch)
        assert job.status == "pending"
        assert job.attempt_count == 0
        assert job.error_msg is None
        assert batch.status == "generating"  # 有 pending → generating


class TestRecompute:
    def test_mixed_states_partial_failed(self, db, gen_user):
        from backend.database.models import ArticleGenerationBatch, ArticleGenerationJob

        batch = ArticleGenerationBatch(
            user_id=gen_user.id, source="agent_excel", requested_count=3, queued_count=3,
            status="generating",
        )
        db.add(batch); db.commit(); db.refresh(batch)
        db.add(ArticleGenerationJob(batch_id=batch.id, user_id=gen_user.id, project_id=None, keyword_id=None, status="completed"))
        db.add(ArticleGenerationJob(batch_id=batch.id, user_id=gen_user.id, project_id=None, keyword_id=None, status="completed"))
        db.add(ArticleGenerationJob(batch_id=batch.id, user_id=gen_user.id, project_id=None, keyword_id=None, status="failed"))
        db.commit()

        ArticleGenerationBatchService(db).recompute_batch_status(batch)
        db.refresh(batch)
        assert batch.status == "partial_failed"
        assert batch.success_count == 2
        assert batch.failed_count == 1
        assert batch.completed_at is not None

    def test_has_waiting_callback(self, db, gen_user):
        from backend.database.models import ArticleGenerationBatch, ArticleGenerationJob

        batch = ArticleGenerationBatch(
            user_id=gen_user.id, source="agent_excel", requested_count=2, queued_count=2, status="generating",
        )
        db.add(batch); db.commit(); db.refresh(batch)
        db.add(ArticleGenerationJob(batch_id=batch.id, user_id=gen_user.id, project_id=None, keyword_id=None, status="completed"))
        db.add(ArticleGenerationJob(batch_id=batch.id, user_id=gen_user.id, project_id=None, keyword_id=None, status="waiting_callback"))
        db.commit()

        ArticleGenerationBatchService(db).recompute_batch_status(batch)
        db.refresh(batch)
        assert batch.status == "waiting_callback"
        assert batch.completed_at is None


def test_idempotency_key_stable():
    k1 = _idempotency_key(1, 2, 3)
    k2 = _idempotency_key(1, 2, 3)
    k3 = _idempotency_key(1, 2, 4)
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 64


class TestArticleCountOverride:
    """修复 bug：用户第 4 步设定的「每项目篇数」必须生效，覆盖 Excel 行的默认篇数。

    复现场景：Excel 每行 normalize 后 article_count 默认 5；用户在第 4 步把篇数改成 1，
    原实现里 execute_batch 读 Excel 行的 5（完全无视用户输入），导致设 1 篇仍生成 5 篇。
    """

    def test_user_count_overrides_excel_default(self, db, gen_user, monkeypatch):
        from backend.database.models import ArticleGenerationJob

        _mock_generate(monkeypatch)
        _kill_bg(monkeypatch)
        # Excel 行篇数 = 5（normalize 后总有默认值）；用户第 4 步却设 1
        client, project, imp = _seed(db, gen_user, n_questions=5, article_count=5)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=1)
        # 用户设定被持久化，并据此估算总篇数（1 项目 × 1 篇）
        assert batch.article_count == 1
        assert batch.requested_count == 1

        asyncio.run(svc.execute_batch(batch.id, gen_user.id))
        db.refresh(batch)
        # 实际只生成 1 篇（用户值），而不是 Excel 行的 5 篇
        assert batch.queued_count == 1
        assert batch.success_count == 1
        jobs = db.query(ArticleGenerationJob).filter(ArticleGenerationJob.batch_id == batch.id).all()
        assert len(jobs) == 1

    def test_excel_count_used_when_user_keeps_default(self, db, gen_user, monkeypatch):
        """用户保持默认（=Excel 行值）时正常生成对应篇数，回归保护。"""
        from backend.database.models import ArticleGenerationJob

        _mock_generate(monkeypatch)
        _kill_bg(monkeypatch)
        client, project, imp = _seed(db, gen_user, n_questions=5, article_count=5)

        svc = ArticleGenerationBatchService(db)
        batch = svc.create_batch(user=gen_user, import_batch_id=imp.id, article_count=5)
        assert batch.article_count == 5
        asyncio.run(svc.execute_batch(batch.id, gen_user.id))
        db.refresh(batch)
        assert batch.queued_count == 5
        assert batch.success_count == 5
