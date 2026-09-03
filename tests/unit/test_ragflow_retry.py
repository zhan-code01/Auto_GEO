# -*- coding: utf-8 -*-
"""
RAGFlow 客户端瞬态重试配置测试。

RAGFlow 偶发 502/503/504 网关抖动时不应直接失败,而应退避重试。
仅幂等的 GET/PUT/DELETE 重试,POST 不重试以免重复创建/上传。
"""

from urllib3.util.retry import Retry


def _client():
    from backend.services.ragflow_client import RAGFlowClient

    return RAGFlowClient(base_url="http://example.invalid", api_key="k")


def _mounted_retry(client) -> Retry:
    adapter = client.session.get_adapter("http://example.invalid")
    return adapter.max_retries


def test_retry_covers_transient_gateway_errors():
    """502/503/504 必须触发重试。"""
    retry = _mounted_retry(_client())
    assert 502 in retry.status_forcelist
    assert 503 in retry.status_forcelist
    assert 504 in retry.status_forcelist


def test_retry_attempts_and_backoff_configured():
    retry = _mounted_retry(_client())
    assert retry.total == 3
    assert retry.backoff_factor == 0.5


def test_idempotent_methods_are_retried():
    """GET/PUT/DELETE 幂等操作应当被重试。"""
    retry = _mounted_retry(_client())
    allowed = retry.allowed_methods
    for method in ("GET", "HEAD", "PUT", "DELETE"):
        assert method in allowed


def test_post_is_not_retried():
    """POST(创建知识库/上传文档)绝不能重试,否则会重复创建。"""
    retry = _mounted_retry(_client())
    assert "POST" not in retry.allowed_methods
