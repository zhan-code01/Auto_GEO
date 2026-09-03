# -*- coding: utf-8 -*-
"""资料结构化画像抽取单测（方案 §6.5，阶段5）。

不打真实 AI / RAGFlow：monkeypatch ``_call_ai`` 与 ``_gather_source_text``，验证
归一化、落库合并、Excel 优先、高置信回填、空资料降级。
"""

import asyncio

import pytest

from backend.services.content_profile_extraction_service import (
    ContentProfileExtractionService,
    _normalize_extracted,
)


# ==================== 归一化纯函数 ====================


class TestNormalize:
    def test_scalar_list_null(self):
        raw = {
            "industry": "AI客服",
            "product_service": ["智能客服机器人", "工单系统"],
            "pain_points": "客服成本高、响应慢",  # 逗号串
            "brand_tone": None,  # 应被过滤
            "project_description": "null",  # 字面 null 应过滤
            "confidence": {"industry": 0.9, "product_service": 0.8, "pain_points": 0.6},
        }
        profile, conf = _normalize_extracted(raw)
        assert profile["industry"] == "AI客服"
        assert profile["product_service"] == ["智能客服机器人", "工单系统"]
        assert profile["pain_points"] == ["客服成本高", "响应慢"]
        assert "brand_tone" not in profile
        assert "project_description" not in profile
        assert conf["industry"] == 0.9
        assert conf["pain_points"] == 0.6

    def test_missing_confidence_defaults(self):
        profile, conf = _normalize_extracted({"industry": "制造"})
        assert conf["industry"] == 0.5  # 无置信度 → 默认 0.5

    def test_confidence_clamped(self):
        profile, conf = _normalize_extracted({"industry": "x", "confidence": {"industry": 5}})
        assert conf["industry"] == 1.0


# ==================== 服务：落库 / 合并 / 回填 ====================


@pytest.fixture
def profile_user(db):
    from backend.database.models import User

    user = User(
        username="profile_test_user",
        email="profile_test@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    from backend.database.models import (
        AgentExcelImportRow,
        AgentExcelImportBatch,
        Keyword,
        Project,
        Client,
        ClientContentProfile,
    )

    db.query(ClientContentProfile).filter(ClientContentProfile.user_id == user.id).delete(synchronize_session=False)
    db.query(AgentExcelImportRow).delete()
    db.query(AgentExcelImportBatch).delete()
    db.query(Keyword).filter(
        Keyword.project_id.in_(db.query(Project.id).filter(Project.user_id == user.id))
    ).delete(synchronize_session=False)
    db.query(Project).filter(Project.user_id == user.id).delete(synchronize_session=False)
    db.query(Client).filter(Client.user_id == user.id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user.id).delete()
    db.commit()


def _seed(db, user, *, company="画像公司", project_name="画像项目", domain="画像关键词", project_industry=None):
    from backend.database.models import Client, Project

    client = Client(name=company, company_name=company, industry=project_industry, user_id=user.id, status=1)
    db.add(client)
    db.commit()
    db.refresh(client)
    project = Project(
        user_id=user.id,
        client_id=client.id,
        name=project_name,
        company_name=company,
        domain_keyword=domain,
        industry=project_industry,
        status=1,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return client, project


def _add_excel_row(db, project_id, normalized):
    from backend.database.models import AgentExcelImportBatch, AgentExcelImportRow

    batch = AgentExcelImportBatch(user_id=None, status="ready")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    row = AgentExcelImportRow(
        batch_id=batch.id, row_index=2, normalized_data=normalized, project_id=project_id, status="processed"
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestPersistAndMerge:
    def test_persist_then_merge(self, db, profile_user):
        client, _ = _seed(db, profile_user)
        svc = ContentProfileExtractionService(db)
        svc.persist_profile(
            user=profile_user, client_id=client.id, project_id=None,
            profile={"industry": "AI"}, confidence={"industry": 0.9}, source_document_ids=["d1"],
        )
        # 二次抽取覆盖同源字段并新增
        svc.persist_profile(
            user=profile_user, client_id=client.id, project_id=None,
            profile={"industry": "AI客服", "product_service": ["机器人"]},
            confidence={"industry": 0.95, "product_service": 0.8}, source_document_ids=["d2"],
        )
        prof = svc.get_profile(client.id)
        assert prof.profile_json["industry"] == "AI客服"  # 覆盖
        assert prof.profile_json["product_service"] == ["机器人"]  # 新增
        assert set(prof.source_document_ids) == {"d1", "d2"}  # 合并去重


class TestEffectiveProfileExcelPriority:
    def test_excel_overrides_extract(self, db, profile_user):
        client, project = _seed(db, profile_user)
        svc = ContentProfileExtractionService(db)
        # 资料抽取：industry 低置信，product_service 高置信
        svc.persist_profile(
            user=profile_user, client_id=client.id, project_id=project.id,
            profile={"industry": "抽取行业", "product_service": ["抽取产品"]},
            confidence={"industry": 0.5, "product_service": 0.9},
            source_document_ids=[],
        )
        # Excel 行：industry 有值（应覆盖抽取）
        _add_excel_row(db, project.id, {"industry": "Excel行业", "company_name": "画像公司", "project_name": "画像项目", "core_keyword": "画像关键词"})

        eff = svc.get_effective_profile(client.id, project.id)
        assert eff["industry"]["source"] == "excel"
        assert eff["industry"]["value"] == "Excel行业"  # Excel 覆盖
        assert eff["product_service"]["source"] == "extract_high"  # Excel 没有该字段 → 用高置信抽取

    def test_no_project_uses_only_extract(self, db, profile_user):
        client, _ = _seed(db, profile_user)
        svc = ContentProfileExtractionService(db)
        svc.persist_profile(
            user=profile_user, client_id=client.id, project_id=None,
            profile={"industry": "x"}, confidence={"industry": 0.9}, source_document_ids=[],
        )
        eff = svc.get_effective_profile(client.id)
        assert eff["industry"]["source"] == "extract_high"


class TestApplyHighConfidence:
    def test_fills_empty_high_conf_only(self, db, profile_user):
        client, project = _seed(db, profile_user, project_industry=None)  # industry 空
        svc = ContentProfileExtractionService(db)
        svc.persist_profile(
            user=profile_user, client_id=client.id, project_id=project.id,
            profile={"industry": "AI客服", "project_description": "面向企业"},
            confidence={"industry": 0.9, "project_description": 0.5},  # desc 低置信
            source_document_ids=[],
        )
        applied = svc.apply_high_confidence_to_project(profile_user, client.id, project.id)
        assert "industry" in applied  # 高置信 → 回填
        assert "project_description" not in applied  # 低置信 → 不回填
        db.refresh(project)
        db.refresh(client)
        assert project.industry == "AI客服"
        assert project.description is None  # 未被低置信回填

    def test_does_not_overwrite_existing(self, db, profile_user):
        client, project = _seed(db, profile_user, project_industry="已有行业")
        svc = ContentProfileExtractionService(db)
        svc.persist_profile(
            user=profile_user, client_id=client.id, project_id=project.id,
            profile={"industry": "AI客服"}, confidence={"industry": 0.95}, source_document_ids=[],
        )
        svc.apply_high_confidence_to_project(profile_user, client.id, project.id)
        db.refresh(project)
        assert project.industry == "已有行业"  # 不覆盖


class TestExtractProfile:
    def test_no_dataset_returns_empty(self, db, profile_user):
        client, _ = _seed(db, profile_user)
        svc = ContentProfileExtractionService(db)
        out = asyncio.get_event_loop().run_until_complete(
            svc.extract_profile(user=profile_user, client_id=client.id)
        )
        # 客户没有 RAGFlow dataset → 无资料文本 → 空画像，不抛异常
        assert out["profile"] == {}
        assert out["persisted"] is False

    def test_full_path_with_mocked_ai(self, db, profile_user, monkeypatch):
        client, project = _seed(db, profile_user)
        svc = ContentProfileExtractionService(db)

        async def fake_call_ai(self_, text):
            return {
                "industry": "AI客服",
                "product_service": ["智能客服"],
                "confidence": {"industry": 0.9, "product_service": 0.85},
            }

        monkeypatch.setattr(ContentProfileExtractionService, "_call_ai", fake_call_ai)
        monkeypatch.setattr(
            ContentProfileExtractionService,
            "_gather_source_text",
            lambda self_, c, doc_ids=None: ("一些资料文本", ["doc1"]),
        )

        out = asyncio.get_event_loop().run_until_complete(
            svc.extract_profile(user=profile_user, client_id=client.id, project_id=project.id)
        )
        assert out["persisted"] is True
        assert out["profile"]["industry"] == "AI客服"
        assert out["source_document_ids"] == ["doc1"]
        prof = svc.get_profile(client.id, project.id)
        assert prof is not None and prof.profile_json["product_service"] == ["智能客服"]

    def test_call_ai_falls_back_to_conversation_llm_config(self, db, monkeypatch):
        import httpx
        import backend.config as config

        monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "")
        monkeypatch.setattr(config, "DEEPSEEK_API_URL", "")
        monkeypatch.setattr(config, "AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
        monkeypatch.setattr(config, "AUTOGEO_CONVERSATION_LLM_BASE_URL", "https://example.test/v1")
        monkeypatch.setattr(config, "AUTOGEO_CONVERSATION_LLM_MODEL", "deepseek-test")

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": '{"industry":"AI客服","confidence":{"industry":0.9}}'}}]}

        class FakeAsyncClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, *, headers, json):
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

        svc = ContentProfileExtractionService(db)
        raw = asyncio.get_event_loop().run_until_complete(svc._call_ai("一些资料文本"))

        assert raw["industry"] == "AI客服"
        assert captured["url"] == "https://example.test/v1/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer conversation-key"
        assert captured["json"]["model"] == "deepseek-test"
