# -*- coding: utf-8 -*-
"""GEO response judge tests.

不调用真实 DeepSeek；通过 monkeypatch httpx.AsyncClient 验证真实 LLM 路径
的请求契约、输出规范化和失败处理（含降级返回）。
"""

import json

import httpx
import pytest

from backend.services.geo_response_judge_service import (
    GeoResponseJudgeService,
    _extract_json_text,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """可配置响应序列的假 AsyncClient，支持重试场景。"""

    response = None
    responses = None  # 若设置则按顺序返回，用于模拟重试
    _idx = 0
    last_request = None

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last_request = {"url": url, "json": json, "headers": headers}
        if _FakeAsyncClient.responses is not None:
            resp = _FakeAsyncClient.responses[_FakeAsyncClient._idx]
            _FakeAsyncClient._idx += 1
            return resp
        return _FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeAsyncClient.response = None
    _FakeAsyncClient.responses = None
    _FakeAsyncClient._idx = 0
    _FakeAsyncClient.last_request = None
    yield
    _FakeAsyncClient.response = None
    _FakeAsyncClient.responses = None
    _FakeAsyncClient._idx = 0


def _patch_judge(monkeypatch):
    monkeypatch.setattr("backend.services.geo_response_judge_service.AUTOGEO_CONVERSATION_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "backend.services.geo_response_judge_service.AUTOGEO_CONVERSATION_LLM_BASE_URL", "https://api.test/v1"
    )
    # 重试退避设为 0，避免测试中真实等待
    monkeypatch.setattr("backend.services.geo_response_judge_service.JUDGE_RETRY_BACKOFF", 0.0)
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)


# ── JSON 提取工具单测 ──


def test_extract_json_text_plain():
    assert _extract_json_text('{"a": 1}') == '{"a": 1}'


def test_extract_json_text_markdown_fence_json():
    raw = "json" if False else "```json" + chr(10) + '{"a": 1}' + chr(10) + "```"
    assert _extract_json_text(raw) == '{"a": 1}'


def test_extract_json_text_markdown_fence_plain():
    raw = "```" + chr(10) + '{"a": 1}' + chr(10) + "```"
    assert _extract_json_text(raw) == '{"a": 1}'


def test_extract_json_text_empty():
    assert _extract_json_text("") == ""
    assert _extract_json_text("   ") == ""


def test_extract_json_text_with_surrounding_text():
    raw = "评估结果：" + chr(10) + '{"a": 1}' + chr(10) + "以上。"
    assert _extract_json_text(raw) == '{"a": 1}'


# ── 正常评估路径 ──


@pytest.mark.asyncio
async def test_llm_judge_normalizes_scores_and_citation_fields(monkeypatch):
    _patch_judge(monkeypatch)

    llm_output = {
        "brand_mentioned": True,
        "matched_names": ["测试品牌"],
        "is_recommended": True,
        "recommendation_rank": 1,
        "ranking_score": 120,
        "sentiment": "positive",
        "sentiment_score": "80",
        "visibility_score": 101,
        "evidence": {"mention": "提到了测试品牌"},
    }
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": json.dumps(llm_output, ensure_ascii=False)}}]},
    )

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=["测试品牌"],
        official_domains=["example.com"],
        competitors=[],
        question="有哪些服务商推荐？",
        question_type="recommendation",
        answer="测试品牌是首推服务商。",
        citations=[{"url": "https://example.com/case", "domain": "example.com"}],
    )

    assert _FakeAsyncClient.last_request["json"]["model"] == "deepseek-test"
    assert result["ranking_score"] == 100
    assert result["sentiment_score"] == 80
    assert result["visibility_score"] == 100
    assert result["citation_supported"] is True
    assert result["cited_urls"] == ["https://example.com/case"]
    assert result["cited_domains"] == ["example.com"]
    assert "judge_error" not in result


@pytest.mark.asyncio
async def test_llm_judge_accepts_markdown_wrapped_json(monkeypatch):
    """LLM 用 ```json 包裹输出时也应能正确解析。"""
    _patch_judge(monkeypatch)

    llm_output = {"brand_mentioned": True, "ranking_score": 60}
    fenced = "```json" + chr(10) + json.dumps(llm_output, ensure_ascii=False) + chr(10) + "```"
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": fenced}}]},
    )

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌还不错。",
        citations=[],
    )

    assert result["brand_mentioned"] is True
    assert result["ranking_score"] == 60
    assert "judge_error" not in result


@pytest.mark.asyncio
async def test_llm_judge_accepts_reasoning_content(monkeypatch):
    """content 为空但 reasoning_content 有值时也应能解析。"""
    _patch_judge(monkeypatch)

    llm_output = {"brand_mentioned": False, "visibility_score": 0}
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": "", "reasoning_content": json.dumps(llm_output)}}]},
    )

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="其他服务商比较好。",
        citations=[],
    )

    assert result["brand_mentioned"] is False


# ── 失败降级路径 ──


@pytest.mark.asyncio
async def test_llm_judge_fallback_on_api_error(monkeypatch):
    """API 500 不再抛异常，而是返回降级结果。"""
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(status_code=500, text="server error")

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌是不错的选择。",
        citations=[],
    )

    # 降级：基于关键词判断 brand_mentioned
    assert result["brand_mentioned"] is True
    assert result["judge_error"].startswith("LLM judge")
    assert result["confidence"] == 0.1


@pytest.mark.asyncio
async def test_llm_judge_fallback_on_empty_content(monkeypatch):
    """LLM 返回空 content（核心 bug 场景）应返回降级结果而非 raise。"""
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": ""}}]},
    )

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="没有提到任何品牌。",
        citations=[],
    )

    assert result["brand_mentioned"] is False
    assert "judge_error" in result
    assert result["evidence"].get("fallback") is True


@pytest.mark.asyncio
async def test_llm_judge_fallback_on_timeout(monkeypatch):
    """超时（含重试）后返回降级结果。"""
    _patch_judge(monkeypatch)

    call_count = {"n": 0}

    class _TimeoutClient(_FakeAsyncClient):
        async def post(self, url, json=None, headers=None):
            call_count["n"] += 1
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("httpx.AsyncClient", _TimeoutClient)

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌",
        citations=[],
    )

    # 重试 JUDGE_MAX_RETRIES+1 次
    assert call_count["n"] == 3
    assert result["brand_mentioned"] is True
    assert "超时" in result["judge_error"]


@pytest.mark.asyncio
async def test_llm_judge_retry_then_success(monkeypatch):
    """第一次失败、第二次成功时应返回真实结果。"""
    _patch_judge(monkeypatch)

    llm_output = {"brand_mentioned": True, "ranking_score": 80}
    _FakeAsyncClient.responses = [
        _FakeResponse(status_code=500, text="err"),
        _FakeResponse(payload={"choices": [{"message": {"content": json.dumps(llm_output)}}]}),
    ]

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌",
        citations=[],
    )

    assert result["brand_mentioned"] is True
    assert result["ranking_score"] == 80
    assert "judge_error" not in result


@pytest.mark.asyncio
async def test_llm_judge_fallback_on_malformed_json(monkeypatch):
    """JSON 解析失败（char 0 场景）应返回降级结果。"""
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": "这不是JSON"}}]},
    )

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌",
        citations=[],
    )

    assert "judge_error" in result


# ── 引用证据链三态:citation_supported 只由真实采集引用决定 ──

_CITATION_SRC = [
    {"url": "https://example.com/case", "domain": "example.com"},
    {"url": "https://example.org/doc", "domain": "example.org"},
]


def _llm_claim_strong_support():
    """LLM 猜测结果:声称有引用 + 自有来源被引用(无论真实采集是否为零)。"""
    return {
        "brand_mentioned": True,
        "is_recommended": True,
        "recommendation_rank": 1,
        "ranking_score": 100,
        "citation_supported": True,
        "own_source_cited": True,
        "sentiment": "positive",
        "sentiment_score": 80,
        "visibility_score": 90,
    }


async def _evaluate_with_status(monkeypatch, citation_status, citations):
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": json.dumps(_llm_claim_strong_support(), ensure_ascii=False)}}]},
    )
    return await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=["example.com"],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌是首选。",
        citations=citations,
        citation_status=citation_status,
    )


@pytest.mark.asyncio
async def test_judge_citation_supported_true_only_when_captured_with_evidence(monkeypatch):
    """captured + 真实引用 → citation_supported=True,evidence 字段由真实引用回填。

    LLM 声称支持引用的前提必须与真实采集一致;新证据链下以真实采集为准。
    """
    result = await _evaluate_with_status(monkeypatch, "captured", _CITATION_SRC)
    assert result["citation_supported"] is True
    assert result["citation_status"] == "captured"
    assert result["cited_urls"] == ["https://example.com/case", "https://example.org/doc"]
    assert "example.com" in result["cited_domains"]


@pytest.mark.asyncio
async def test_judge_citation_supported_forced_false_on_empty_even_if_llm_claims(monkeypatch):
    """empty(抓取成功但零条)→ citation_supported 恒 False,压制 LLM 猜测。"""
    result = await _evaluate_with_status(monkeypatch, "empty", [])
    assert result["citation_supported"] is False
    assert result["own_source_cited"] is False
    assert result["citation_status"] == "empty"
    assert result["cited_urls"] == []


@pytest.mark.asyncio
async def test_judge_citation_supported_forced_false_on_unavailable(monkeypatch):
    """unavailable(抓取异常)→ citation_supported 恒 False。"""
    result = await _evaluate_with_status(monkeypatch, "unavailable", None)
    assert result["citation_supported"] is False
    assert result["own_source_cited"] is False
    assert result["citation_status"] == "unavailable"


@pytest.mark.asyncio
async def test_judge_citation_supported_forced_false_on_not_supported(monkeypatch):
    """not_supported(平台无引用能力)→ citation_supported 恒 False,报表按 null 呈现。"""
    result = await _evaluate_with_status(monkeypatch, "not_supported", None)
    assert result["citation_supported"] is False
    assert result["own_source_cited"] is False
    assert result["citation_status"] == "not_supported"


@pytest.mark.asyncio
async def test_judge_legacy_without_status_keeps_llm_heuristic(monkeypatch):
    """未上报引用状态(遗留调用方)→ 保留历史语义:LLM 猜测与真实引用取或。"""
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(
        payload={"choices": [{"message": {"content": json.dumps(_llm_claim_strong_support(), ensure_ascii=False)}}]},
    )
    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=["example.com"],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌是首选。",
        citations=[],
    )
    # 无三态上报 + LLM 声称有引用 → 保持 legacy 行为为 True
    assert result["citation_supported"] is True
    assert result["citation_status"] is None


@pytest.mark.asyncio
async def test_judge_fallback_honors_declared_status_on_api_error(monkeypatch):
    """LLM 失败降级路径同样尊重三态:empty 上报时降级结果 citation_supported 为 False。"""
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(status_code=500, text="server error")

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌是不错的选择。",
        citations=[],
        citation_status="empty",
    )
    assert result["judge_error"].startswith("LLM judge")
    assert result["citation_supported"] is False
    assert result["citation_status"] == "empty"


@pytest.mark.asyncio
async def test_judge_fallback_captured_status_keeps_real_citations(monkeypatch):
    """降级路径 + captured 真实引用:即便无 LLM,真实引用证据仍回填 cited_urls。"""
    _patch_judge(monkeypatch)
    _FakeAsyncClient.response = _FakeResponse(status_code=500, text="server error")

    result = await GeoResponseJudgeService(model="deepseek-test").evaluate(
        company_name="测试品牌",
        brand_aliases=[],
        official_domains=[],
        competitors=[],
        question="问题",
        question_type="recommendation",
        answer="测试品牌是不错的选择。",
        citations=_CITATION_SRC,
        citation_status="captured",
    )
    assert result["citation_supported"] is True
    assert result["cited_urls"] == ["https://example.com/case", "https://example.org/doc"]
    assert result["brand_mentioned"] is True  # 关键词降级命中
