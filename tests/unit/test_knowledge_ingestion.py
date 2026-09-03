# -*- coding: utf-8 -*-
"""KnowledgeIngestionService 单测（方案 §6.7，阶段4）。

不打真实 RAGFlow 网络：用 monkeypatch 注入 FakeRagflowClient，验证入库闭环逻辑、
归属校验、参数校验与降级行为。extractor 也替换为假实现，避免 AI 调用。
"""

import pytest

from backend.services.knowledge_ingestion_service import KnowledgeIngestionService


class _FakeRagflowClient:
    """模拟 RAGFlow：create_dataset/upload/parse 全部成功；get_dataset 视为不存在以触发创建。"""

    def __init__(self):
        self.is_configured_value = True
        self.created_datasets = []
        self.uploaded = []
        self.parsed = []
        self._ds_counter = 0
        self._doc_counter = 0

    def is_configured(self):
        return self.is_configured_value

    def get_dataset(self, dataset_id):
        return {"code": -1, "message": "not found"}

    def create_dataset(self, name, description=None):
        self._ds_counter += 1
        ds_id = f"ds_fake_{self._ds_counter}"
        self.created_datasets.append((ds_id, name))
        return {"code": 0, "data": {"id": ds_id, "name": name}}

    def upload_document_bytes(self, dataset_id, file_content, file_name, content_type=None, do_parse=True):
        self._doc_counter += 1
        doc_id = f"doc_fake_{self._doc_counter}"
        self.uploaded.append((dataset_id, file_name, doc_id))
        return {"code": 0, "data": [{"id": doc_id, "name": file_name}]}

    def parse_documents(self, dataset_id, document_ids):
        self.parsed.append((dataset_id, list(document_ids)))
        return {"code": 0}


class _FakeExtractor:
    def extract_text_from_file_bytes(self, content, name):
        return ""

    def extract_from_text(self, text):
        return {}

    def extract_from_ragflow_document(self, dataset_id, document_id, ragflow_client):
        return {}


@pytest.fixture
def ingest_user(db):
    from backend.database.models import User

    user = User(
        username="ingest_test_user",
        email="ingest_test@test.local",
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
        Knowledge,
        KnowledgeCategory,
    )

    db.query(Knowledge).filter(Knowledge.title.like("test_%")).delete(synchronize_session=False)
    db.query(KnowledgeCategory).filter(KnowledgeCategory.user_id == user.id).delete(synchronize_session=False)
    db.query(Keyword).filter(
        Keyword.project_id.in_(db.query(Project.id).filter(Project.user_id == user.id))
    ).delete(synchronize_session=False)
    db.query(AgentExcelImportRow).delete()
    db.query(AgentExcelImportBatch).delete()
    db.query(Project).filter(Project.user_id == user.id).delete(synchronize_session=False)
    db.query(Client).filter(Client.user_id == user.id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user.id).delete()
    db.commit()


@pytest.fixture
def patched_ragflow(monkeypatch):
    fake = _FakeRagflowClient()
    import backend.services.ragflow_client as rfc
    import backend.services.document_extractor as de

    monkeypatch.setattr(rfc, "get_ragflow_client", lambda: fake)
    monkeypatch.setattr(de, "get_document_extractor", lambda: _FakeExtractor())
    return fake


def _make_client(db, user, name="测试公司", company_name=None):
    from backend.database.models import Client

    client = Client(
        name=name,
        company_name=company_name or name,
        industry="测试行业",
        user_id=user.id,
        status=1,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


class TestUploadFiles:
    def test_upload_success(self, db, ingest_user, patched_ragflow):
        import asyncio

        from backend.database.models import Knowledge, KnowledgeCategory

        client = _make_client(db, ingest_user, company_name="成功公司")
        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_intro.txt", "content": b"hello world"}],
                category="company",
            )
        )

        assert out["ragflow_configured"] is True
        assert out["success_count"] == 1
        assert out["failed_count"] == 0
        assert out["ragflow_dataset_id"].startswith("ds_fake_")
        assert patched_ragflow.uploaded and patched_ragflow.parsed

        # 本地 Knowledge 记录已写
        kat = (
            db.query(KnowledgeCategory)
            .filter(KnowledgeCategory.user_id == ingest_user.id)
            .first()
        )
        assert kat is not None and kat.ragflow_dataset_id == out["ragflow_dataset_id"]
        kw = db.query(Knowledge).filter(Knowledge.ragflow_dataset_id == kat.ragflow_dataset_id).first()
        assert kw is not None and kw.title == "test_intro.txt"

    def test_upload_caches_extracted_text_in_knowledge_content(self, db, ingest_user, patched_ragflow, monkeypatch):
        import asyncio

        import backend.services.document_extractor as de
        from backend.database.models import Knowledge

        class PdfExtractor(_FakeExtractor):
            def extract_text_from_file_bytes(self, content, name):
                return "PDF产品介绍\n核心功能：智能客服、知识库问答"

        monkeypatch.setattr(de, "get_document_extractor", lambda: PdfExtractor())

        client = _make_client(db, ingest_user, company_name="PDF入库公司")
        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_intro.pdf", "content": b"%PDF fake", "content_type": "application/pdf"}],
                category="product",
                extract_profile=False,
                apply_profile=False,
            )
        )

        assert out["success_count"] == 1
        kw = db.query(Knowledge).filter(Knowledge.title == "test_intro.pdf").first()
        assert kw is not None
        assert "parsed_text" in kw.content
        assert "PDF产品介绍" in kw.content
        assert "智能客服" in kw.content

    def test_upload_applies_extracted_client_info(self, db, ingest_user, patched_ragflow, monkeypatch):
        import asyncio

        import backend.services.document_extractor as de
        from backend.services.content_profile_extraction_service import ContentProfileExtractionService

        class InfoExtractor(_FakeExtractor):
            def extract_text_from_file_bytes(self, content, name):
                return "公司名称：自动回填公司\n联系人：李四\n电话：13800138000\n行业：人工智能"

            def extract_from_text(self, text):
                return {
                    "company_name": "自动回填公司",
                    "contact_person": "李四",
                    "phone": "13800138000",
                    "industry": "人工智能",
                }

        async def fake_call_ai(self, text):
            return {}

        monkeypatch.setattr(de, "get_document_extractor", lambda: InfoExtractor())
        monkeypatch.setattr(ContentProfileExtractionService, "_call_ai", fake_call_ai)

        client = _make_client(db, ingest_user, name="未知客户", company_name=None)
        client.company_name = None
        client.contact_person = None
        client.phone = None
        client.industry = None
        db.commit()
        db.refresh(client)
        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_profile.txt", "content": b"profile"}],
                category="company",
            )
        )

        db.refresh(client)
        assert out["success_count"] == 1
        assert out["applied_client_fields"]["company_name"] == "自动回填公司"
        assert out["applied_client_fields"]["contact_person"] == "李四"
        assert client.name == "自动回填公司"
        assert client.phone == "13800138000"
        assert client.industry == "人工智能"

    def test_upload_all_flags_off_does_not_extract(self, db, ingest_user, patched_ragflow, monkeypatch):
        """三参全 False（仅入知识库）：不抽取、不回填，但仍上传 + 解析。"""
        import asyncio

        import backend.services.document_extractor as de
        from backend.services.content_profile_extraction_service import ContentProfileExtractionService

        class InfoExtractor(_FakeExtractor):
            def extract_text_from_file_bytes(self, content, name):
                return "公司名称：不该回填公司\n行业：不该回填行业"

            def extract_from_text(self, text):
                return {"company_name": "不该回填公司", "industry": "不该回填行业"}

        async def fake_call_ai(self, text):
            return {"industry": "不该回填行业"}

        monkeypatch.setattr(de, "get_document_extractor", lambda: InfoExtractor())
        monkeypatch.setattr(ContentProfileExtractionService, "_call_ai", fake_call_ai)

        client = _make_client(db, ingest_user, name="关闭抽取客户", company_name=None)
        client.company_name = None
        client.industry = None
        db.commit()
        db.refresh(client)

        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_konly.txt", "content": b"profile"}],
                category="company",
                extract_basic_info=False,
                extract_profile=False,
                apply_profile=False,
            )
        )
        db.refresh(client)
        assert out["success_count"] == 1
        assert out["extracted_info"] == {}
        assert out["applied_client_fields"] == {}
        # 文档仍正常上传并触发解析
        assert patched_ragflow.uploaded and patched_ragflow.parsed
        # 客户字段未被改动
        assert client.company_name is None
        assert client.industry is None

    def test_upload_invalid_phone_email_are_skipped(self, db, ingest_user, patched_ragflow, monkeypatch):
        """非法电话/邮箱计入 skipped_client_fields，不写回客户。"""
        import asyncio

        import backend.services.document_extractor as de
        from backend.services.content_profile_extraction_service import ContentProfileExtractionService

        class InfoExtractor(_FakeExtractor):
            def extract_text_from_file_bytes(self, content, name):
                return "公司名称：合规公司\n电话：not-a-phone\n邮箱：bad-email"

            def extract_from_text(self, text):
                return {"company_name": "合规公司", "phone": "not-a-phone", "email": "bad-email", "industry": "AI"}

        async def fake_call_ai(self, text):
            return {}

        monkeypatch.setattr(de, "get_document_extractor", lambda: InfoExtractor())
        monkeypatch.setattr(ContentProfileExtractionService, "_call_ai", fake_call_ai)

        client = _make_client(db, ingest_user, name="格式校验客户", company_name=None)
        client.company_name = None
        client.phone = None
        client.email = None
        client.industry = None
        db.commit()
        db.refresh(client)

        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_fmt.txt", "content": b"profile"}],
                category="company",
                extract_profile=False,
                apply_profile=False,
            )
        )
        db.refresh(client)
        assert out["applied_client_fields"]["company_name"] == "合规公司"
        assert out["applied_client_fields"]["industry"] == "AI"
        assert "phone" in out["skipped_client_fields"]
        assert "email" in out["skipped_client_fields"]
        # 非法值未写回
        assert client.phone is None
        assert client.email is None
        assert client.company_name == "合规公司"

    def test_upload_placeholder_contact_is_filtered(self, db, ingest_user, patched_ragflow, monkeypatch):
        """联系人=电话 这类字段标签误抽不能回显或回填。"""
        import asyncio

        import backend.services.document_extractor as de

        class InfoExtractor(_FakeExtractor):
            def extract_text_from_file_bytes(self, content, name):
                return "公司名称：占位过滤公司\n联系人：电话\n邮箱：邮箱地址\n行业：互联网"

            def extract_from_text(self, text):
                return {
                    "company_name": "占位过滤公司",
                    "contact_person": "电话",
                    "email": "邮箱地址",
                    "industry": "互联网",
                }

        monkeypatch.setattr(de, "get_document_extractor", lambda: InfoExtractor())

        client = _make_client(db, ingest_user, name="占位客户", company_name=None)
        client.company_name = None
        client.contact_person = None
        client.email = None
        client.industry = None
        db.commit()
        db.refresh(client)

        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_placeholder.txt", "content": b"profile"}],
                category="company",
                extract_profile=False,
                apply_profile=False,
            )
        )
        db.refresh(client)

        assert out["success_count"] == 1
        assert out["extracted_info"] == {"company_name": "占位过滤公司", "industry": "互联网"}
        assert client.contact_person is None
        assert client.email is None
        assert client.company_name == "占位过滤公司"

    def test_unsupported_extension_failed(self, db, ingest_user, patched_ragflow):
        import asyncio

        client = _make_client(db, ingest_user, company_name="扩展公司")
        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_bad.exe", "content": b"xx"}],
                category="company",
            )
        )
        assert out["success_count"] == 0
        assert out["failed_count"] == 1
        assert "格式" in out["failed"][0]["error"]

    def test_not_configured_returns_all_failed(self, db, ingest_user, patched_ragflow):
        import asyncio

        patched_ragflow.is_configured_value = False
        client = _make_client(db, ingest_user, company_name="未配置公司")
        svc = KnowledgeIngestionService(db)
        out = asyncio.run(
            svc.upload_files(
                user=ingest_user,
                client_id=client.id,
                files=[{"filename": "test_a.txt", "content": b"a"}],
                category="company",
            )
        )
        assert out["ragflow_configured"] is False
        assert out["success_count"] == 0
        assert out["failed_count"] == 1

    def test_validation_errors(self, db, ingest_user, patched_ragflow):
        import asyncio

        client = _make_client(db, ingest_user, company_name="校验公司")
        svc = KnowledgeIngestionService(db)

        # 客户不存在
        with pytest.raises(ValueError):
            asyncio.run(
                svc.upload_files(
                    user=ingest_user, client_id=999999, files=[{"filename": "x.txt", "content": b"x"}]
                )
            )
        # 非法分类
        with pytest.raises(ValueError):
            asyncio.run(
                svc.upload_files(
                    user=ingest_user,
                    client_id=client.id,
                    files=[{"filename": "x.txt", "content": b"x"}],
                    category="not_a_category",
                )
            )
        # 文件过多
        with pytest.raises(ValueError):
            asyncio.run(
                svc.upload_files(
                    user=ingest_user,
                    client_id=client.id,
                    files=[{"filename": f"test_{i}.txt", "content": b"x"} for i in range(20)],
                )
            )

    def test_other_user_client_forbidden(self, db, ingest_user, patched_ragflow):
        """不能向他人客户上传资料（require_owner）。"""
        import asyncio

        from backend.database.models import Client, User

        other = User(username="ingest_other", email="ingest_other@test.local", password_hash="x", role="user", is_active=True)
        db.add(other)
        db.commit()
        db.refresh(other)
        other_client = Client(name="他人公司", company_name="他人公司", user_id=other.id, status=1)
        db.add(other_client)
        db.commit()
        db.refresh(other_client)

        svc = KnowledgeIngestionService(db)
        try:
            # require_owner 抛 HTTPException(403)
            with pytest.raises(Exception):
                asyncio.run(
                    svc.upload_files(
                        user=ingest_user,
                        client_id=other_client.id,
                        files=[{"filename": "x.txt", "content": b"x"}],
                    )
                )
        finally:
            db.query(Client).filter(Client.id == other_client.id).delete()
            db.query(User).filter(User.id == other.id).delete()
            db.commit()
