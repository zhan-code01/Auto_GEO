# -*- coding: utf-8 -*-
"""搜索问题蒸馏/去重/补足单测（方案 §7，阶段6）。

不打 n8n：monkeypatch ``KeywordService.distill`` 返回固定结果，验证落库、去重、
未使用筛选、prepare 自动补蒸馏与不足降级。
"""

import asyncio

import pytest

from backend.services.project_question_service import (
    ProjectQuestionService,
    normalize_question,
)


# ==================== 标准化 ====================


class TestNormalize:
    def test_fullwidth_and_lowercase_and_spaces(self):
        assert normalize_question("　人工　客服？") == "人工 客服"
        assert normalize_question("ABC？") == "abc"
        assert normalize_question("  多   余 空格 ??") == "多 余 空格"

    def test_dedup_equivalence(self):
        assert normalize_question("人工客服？") == normalize_question("人工客服")
        assert normalize_question("ＡＩ客服") == normalize_question("ai客服")


# ==================== 服务 ====================


@pytest.fixture
def q_user(db):
    from backend.database.models import User

    user = User(username="q_test_user", email="q_test@test.local", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    from backend.database.models import (
        AgentExcelImportRow,
        AgentExcelImportBatch,
        KeywordUsageRecord,
        GeoArticle,
        Keyword,
        Project,
        Client,
        User as U,
    )

    db.query(KeywordUsageRecord).filter(KeywordUsageRecord.used_by_user_id == user.id).delete(synchronize_session=False)
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


def _seed_project(db, user, *, domain="人工客服"):
    from backend.database.models import Client, Project

    client = Client(name="问题公司", company_name="问题公司", user_id=user.id, status=1)
    db.add(client)
    db.commit()
    db.refresh(client)
    project = Project(
        user_id=user.id, client_id=client.id, name="问题项目", company_name="问题公司",
        domain_keyword=domain, status=1,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return client, project


def _add_question(db, project, text):
    from backend.database.models import Keyword

    kw = Keyword(project_id=project.id, keyword=text, keyword_type="question", status="active")
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return kw


def _add_article(db, project, keyword, user, status="completed"):
    from backend.database.models import GeoArticle

    a = GeoArticle(
        keyword_id=keyword.id, project_id=project.id, user_id=user.id,
        title="t", content="c", publish_status=status,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


class TestUnusedQuestions:
    def test_excludes_used_keeps_failed_and_unused(self, db, q_user):
        client, project = _seed_project(db, q_user)
        q_used = _add_question(db, project, "已用问题")
        q_failed = _add_question(db, project, "失败文章问题")
        q_free = _add_question(db, project, "未用问题")
        _add_article(db, project, q_used, q_user, status="completed")  # 已生成 → 排除
        _add_article(db, project, q_failed, q_user, status="failed")  # 失败 → 不算用

        svc = ProjectQuestionService(db)
        unused = svc.get_unused_questions(project.id)
        texts = [k.keyword for k in unused]
        assert "未用问题" in texts
        assert "失败文章问题" in texts
        assert "已用问题" not in texts


class TestDistillPersist:
    def test_persists_as_question_with_dedup(self, db, q_user, monkeypatch):
        from backend.services.keyword_service import KeywordService
        from backend.database.models import Keyword

        client, project = _seed_project(db, q_user)

        async def fake_distill(self, **kwargs):
            return {
                "status": "success",
                # 第3个去掉问号后与第1个标准化等价（去末尾问号）
                "conversion_phrases": ["人工客服怎么选？", "智能客服贵吗", "人工客服怎么选"],
            }

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        svc = ProjectQuestionService(db)
        saved = asyncio.get_event_loop().run_until_complete(svc.distill_and_persist_questions(project, count=10))

        texts = [k.keyword for k in saved]
        assert len(saved) == 2  # 第3个标准化去重
        assert all(k.keyword_type == "question" for k in saved)
        # 落库可查
        qs = db.query(Keyword).filter(Keyword.project_id == project.id, Keyword.keyword_type == "question").all()
        assert len(qs) == 2

    def test_no_domain_keyword_returns_empty(self, db, q_user):
        from backend.database.models import Client, Project

        client = Client(name="无词公司", company_name="无词公司", user_id=q_user.id, status=1)
        db.add(client); db.commit(); db.refresh(client)
        project = Project(user_id=q_user.id, client_id=client.id, name="无词项目", company_name="无词公司", status=1)
        db.add(project); db.commit(); db.refresh(project)

        svc = ProjectQuestionService(db)
        out = asyncio.get_event_loop().run_until_complete(svc.distill_and_persist_questions(project, count=5))
        assert out == []

    def test_keyword_service_persists_core_fallback_and_code_data_phrases(self, db, q_user, monkeypatch):
        from backend.database.models import Keyword
        from backend.services.keyword_service import KeywordService

        client, project = _seed_project(db, q_user, domain="智能工单")

        async def fake_distill(self, **kwargs):
            return {
                "status": "success",
                "raw_response": {"code": 200, "data": ["智能工单哪家好", "智能工单服务商推荐"]},
                "conversion_phrases": ["智能工单哪家好", "智能工单服务商推荐"],
            }

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        out = asyncio.get_event_loop().run_until_complete(
            KeywordService(db).distill_and_persist(
                project_id=project.id,
                core_kw="智能工单",
                target_info="问题公司",
                count=10,
            )
        )

        assert out["status"] == "success"
        assert [k["keyword"] for k in out["keywords"]] == ["智能工单"]
        assert len(out["saved_phrases"]) == 2
        assert db.query(Keyword).filter(Keyword.project_id == project.id, Keyword.keyword_type == "keyword").count() == 1
        assert db.query(Keyword).filter(Keyword.project_id == project.id, Keyword.keyword_type == "question").count() == 2

    def test_keyword_service_persists_variants_as_core_keywords(self, db, q_user, monkeypatch):
        from backend.database.models import Keyword
        from backend.services.keyword_service import KeywordService

        client, project = _seed_project(db, q_user, domain="智能工单")

        async def fake_distill(self, **kwargs):
            return {
                "status": "success",
                "variants": ["智能工单平台", "智能工单软件"],
                "conversion_phrases": ["智能工单平台哪家好"],
            }

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        out = asyncio.get_event_loop().run_until_complete(
            KeywordService(db).distill_and_persist(
                project_id=project.id,
                core_kw="智能工单",
                target_info="问题公司",
                count=10,
            )
        )

        assert [k["keyword"] for k in out["keywords"]] == ["智能工单平台", "智能工单软件"]
        assert len(out["saved_phrases"]) == 1
        core = db.query(Keyword).filter(Keyword.project_id == project.id, Keyword.keyword_type == "keyword").all()
        assert [k.keyword for k in core] == ["智能工单平台", "智能工单软件"]


class TestPrepareQuestions:
    def test_refill_meets_need(self, db, q_user, monkeypatch):
        from backend.services.keyword_service import KeywordService

        client, project = _seed_project(db, q_user)

        async def fake_distill(self, **kwargs):
            return {"status": "success", "conversion_phrases": [f"问题{i}怎么样" for i in range(6)]}

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        svc = ProjectQuestionService(db)
        qs, note = asyncio.get_event_loop().run_until_complete(svc.prepare_questions(project.id, 5))
        assert len(qs) == 5
        assert note is None

    def test_insufficient_returns_note(self, db, q_user, monkeypatch):
        from backend.services.keyword_service import KeywordService

        client, project = _seed_project(db, q_user)

        async def fake_distill(self, **kwargs):
            # 始终只返回 2 个 → 第二轮去重后 0 新增 → 停止
            return {"status": "success", "conversion_phrases": ["仅问题A", "仅问题B"]}

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        svc = ProjectQuestionService(db)
        qs, note = asyncio.get_event_loop().run_until_complete(svc.prepare_questions(project.id, 5))
        assert len(qs) == 2
        assert note is not None
        assert "不足" in note

    def test_uses_existing_unused_first(self, db, q_user, monkeypatch):
        from backend.services.keyword_service import KeywordService

        client, project = _seed_project(db, q_user)
        _add_question(db, project, "已有未用1")
        _add_question(db, project, "已有未用2")

        distill_called = {"n": 0}

        async def fake_distill(self, **kwargs):
            distill_called["n"] += 1
            return {"status": "success", "conversion_phrases": ["蒸馏问题1", "蒸馏问题2", "蒸馏问题3"]}

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        svc = ProjectQuestionService(db)
        qs, note = asyncio.get_event_loop().run_until_complete(svc.prepare_questions(project.id, 4))
        assert len(qs) == 4
        assert note is None
        assert distill_called["n"] == 1  # 现有 2 个 → 缺 2 → 蒸馏 1 轮够用

    def test_refill_requests_at_least_default_distill_count(self, db, q_user, monkeypatch):
        from backend.services.keyword_service import KeywordService

        client, project = _seed_project(db, q_user)
        seen_counts = []

        async def fake_distill(self, **kwargs):
            seen_counts.append(kwargs.get("count"))
            return {"status": "success", "conversion_phrases": [f"候选问题{i}" for i in range(10)]}

        monkeypatch.setattr(KeywordService, "distill", fake_distill)
        svc = ProjectQuestionService(db)
        qs, note = asyncio.get_event_loop().run_until_complete(svc.prepare_questions(project.id, 5))
        assert len(qs) == 5
        assert note is None
        assert seen_counts == [10]


class TestRecordUsage:
    def test_writes_record(self, db, q_user):
        client, project = _seed_project(db, q_user)
        kw = _add_question(db, project, "记录问题")
        article = _add_article(db, project, kw, q_user, status="completed")

        svc = ProjectQuestionService(db)
        rec = svc.record_usage(project_id=project.id, keyword=kw, article_id=article.id, user_id=q_user.id)
        assert rec.keyword_text == "记录问题"
        assert rec.article_id == article.id
        assert rec.source == "agent_excel"
        assert rec.used_by_user_id == q_user.id
