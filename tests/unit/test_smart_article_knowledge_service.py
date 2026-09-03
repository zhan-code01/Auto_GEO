import pytest

from backend.services.smart_article.knowledge_service import SmartArticleKnowledgeService
from backend.services.smart_article.schemas import PlannedQuestion, ProjectContext, QuerySpec


class FakeRag:
    def is_configured(self):
        return True


class FakeGeoService:
    def __init__(self):
        self.ragflow = FakeRag()
        self.calls = []

    def resolve_dataset_ids(self, client):
        return ["client-dataset"]

    def retrieve_chunks(self, dataset_ids, queries):
        self.calls.append(queries)
        if len(self.calls) == 1:
            return []
        return [{"id": "chunk-1", "content": "智能客服项目支持常见咨询分流。", "similarity": 0.8}]

    def dedupe_and_rank_chunks(self, chunks):
        return chunks

    def format_rag_context(self, chunks):
        return "客户片段：" + chunks[0]["content"]


class FakeRewriter:
    async def rewrite(self, context, planned, initial):
        return [
            QuerySpec("智能客服 产品能力", "capability_match", "能力"),
            QuerySpec("智能客服 咨询分流", "capability_match", "场景"),
            QuerySpec("智能客服 接入实施", "capability_match", "实施"),
        ]

    def fallback(self, context, planned):
        return []


class SummaryGeoService(FakeGeoService):
    def retrieve_chunks(self, dataset_ids, queries):
        self.calls.append(queries)
        return [{"id": "chunk-1", "content": "智能客服解决高峰咨询排队问题，核心功能是智能分流。", "similarity": 0.9}]


class BrokenGeoService(FakeGeoService):
    def retrieve_chunks(self, dataset_ids, queries):
        raise RuntimeError("RAGFlow连接失败")


def test_product_summary_light_query_returns_text():
    service = SmartArticleKnowledgeService(None, FakeRewriter())
    service.geo_service = SummaryGeoService()
    context = ProjectContext(1, 1, "鲲界科技", "智能客服", "智能客服", client=object())

    summary = service.retrieve_product_summary(context)

    assert "智能分流" in summary
    # 轻量查询覆盖解决问题/核心功能/适用客户/场景四类检索词。
    assert len(service.geo_service.calls) == 1
    assert any("解决什么问题" in query for query in service.geo_service.calls[0])
    assert any("核心功能" in query for query in service.geo_service.calls[0])


def test_product_summary_failure_degrades_to_empty_string():
    service = SmartArticleKnowledgeService(None, FakeRewriter())
    service.geo_service = BrokenGeoService()
    context = ProjectContext(1, 1, "鲲界科技", "智能客服", "智能客服", client=object())

    # RAGFlow异常时返回空字符串，不阻断问题生成。
    assert service.retrieve_product_summary(context) == ""


@pytest.mark.asyncio
async def test_empty_first_round_triggers_only_one_rewrite_round():
    service = SmartArticleKnowledgeService(None, FakeRewriter())
    service.geo_service = FakeGeoService()
    context = ProjectContext(1, 1, "鲲界科技", "智能客服", "智能客服", client=object())
    planned = PlannedQuestion("企业如何选择智能客服？", "selection", "general")

    result = await service.retrieve(context, planned)

    assert result.status == "available"
    assert result.retrieval_rounds == 2
    assert result.query_rewrite_used is True
    assert len(service.geo_service.calls) == 2
    assert result.valid_count == 1
