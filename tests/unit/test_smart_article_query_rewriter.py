import pytest

from backend.services.smart_article.query_rewriter import SmartArticleQueryRewriter
from backend.services.smart_article.schemas import PlannedQuestion, ProjectContext, QuerySpec


class FakeLLM:
    async def json(self, *_args, **_kwargs):
        return {"queries": [
            {"text": "智能客服 产品功能", "purpose": "产品资料"},
            {"text": "智能客服 接入方式", "purpose": "接入资料"},
            {"text": "智能客服 实施流程", "purpose": "交付资料"},
        ]}


@pytest.mark.asyncio
async def test_query_rewriter_only_returns_short_retrieval_queries():
    context = ProjectContext(1, 1, "鲲界科技", "智能客服", "智能客服")
    planned = PlannedQuestion("企业如何选择智能客服？", "selection", "general")
    initial = [QuerySpec("企业如何选择智能客服", "user_need", "用户需求")]

    result = await SmartArticleQueryRewriter(FakeLLM()).rewrite(context, planned, initial)

    assert len(result) == 3
    assert all(item.kind == "capability_match" for item in result)
    assert all("鲲界科技" not in item.text for item in result)
