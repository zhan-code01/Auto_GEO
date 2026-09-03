import pytest

from backend.services import ai_generation_service
from backend.services.geo_article_service import GeoArticleService


def test_ai_generation_service_prefers_conversation_url_without_deepseek_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_URL", raising=False)
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(ai_generation_service, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(ai_generation_service, "AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
    monkeypatch.setattr(ai_generation_service, "AUTOGEO_CONVERSATION_LLM_BASE_URL", "http://proxy.test/v1")

    service = ai_generation_service.AIGenerationService()

    assert service.api_key == "conversation-key"
    assert service.api_url == "http://proxy.test/v1"
    assert service.model == "deepseek-v4-flash"


def test_ai_generation_service_uses_deepseek_url_when_deepseek_key_is_set(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_API_URL", "https://deepseek.test/v1")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_BASE_URL", "http://proxy.test/v1")

    service = ai_generation_service.AIGenerationService()

    assert service.api_key == "deepseek-key"
    assert service.api_url == "https://deepseek.test/v1"


@pytest.mark.asyncio
async def test_chat_defaults_to_configured_conversation_model(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(ai_generation_service, "DEEPSEEK_API_KEY", "")

    class FakeResponse:
        status_code = 200
        text = "{}"

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"total_tokens": 1},
            }

    class FakeClient:
        is_closed = False

        def __init__(self):
            self.payload = None

        async def post(self, _url, json):
            self.payload = json
            return FakeResponse()

    service = ai_generation_service.AIGenerationService()
    fake_client = FakeClient()
    service._client = fake_client

    await service._chat(messages=[{"role": "user", "content": "ping"}])

    assert fake_client.payload["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_generate_geo_article_uses_configured_model_for_all_steps(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_API_KEY", "conversation-key")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_BASE_URL", "http://proxy.test/v1")
    monkeypatch.setenv("AUTOGEO_CONVERSATION_LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(ai_generation_service, "DEEPSEEK_API_KEY", "")

    seen_models = []

    async def fake_chat(self, messages, *, model=None, **_kwargs):
        selected_model = model or self.model
        seen_models.append(selected_model)
        if len(seen_models) == 1:
            return {"content": '{"titles": ["智能客服Agent落地指南"]}', "usage": {}, "raw": {}}
        return {
            "content": (
                '{"title": "智能客服Agent落地指南", '
                '"content": "# 智能客服Agent落地指南\\n\\n正文内容", '
                '"references": []}'
            ),
            "usage": {},
            "raw": {},
        }

    monkeypatch.setattr(ai_generation_service.AIGenerationService, "_chat", fake_chat)

    service = ai_generation_service.AIGenerationService()
    result = await service.generate_geo_article(
        keyword="智能客服Agent",
        company_name="测试公司",
        requirements="测试资料",
        word_count=300,
    )

    assert result["status"] == "success"
    assert seen_models == ["deepseek-v4-flash", "deepseek-v4-flash"]


@pytest.mark.asyncio
async def test_quality_ai_uses_shared_ai_generation_service(monkeypatch):
    calls = []

    class FakeAi:
        async def _chat_with_retry(self, **kwargs):
            calls.append(kwargs)
            return {
                "content": (
                    '{"quality_score": 88, "fact_risk_score": 10, '
                    '"platform_risk_score": 12, "duplication_score": 20}'
                )
            }

    monkeypatch.setattr(ai_generation_service, "get_ai_service", lambda: FakeAi())

    result = await GeoArticleService(db=None)._call_quality_ai("评估这篇文章")

    assert result == {
        "quality_score": 88,
        "fact_risk_score": 10,
        "platform_risk_score": 12,
        "duplication_score": 20,
    }
    assert calls[0]["json_mode"] is True
