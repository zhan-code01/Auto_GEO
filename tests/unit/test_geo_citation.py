# -*- coding: utf-8 -*-
"""GEO 引用证据链状态契约单测(纯函数,无 DB)。

覆盖 backend/services/geo_citation.py 的三态归类与平台能力判定。
对应 docs/AutoGEO优化方案_2026-09.md 优化项六(引用证据链修复 P0)。
"""

import pytest

from backend.services.geo_citation import (
    CITATION_STATUS_CAPTURED,
    CITATION_STATUS_EMPTY,
    CITATION_STATUS_NOT_SUPPORTED,
    CITATION_STATUS_UNAVAILABLE,
    VALID_CITATION_STATUSES,
    CITATION_UNSUPPORTED_PLATFORMS,
    classify_citation_status,
    platform_supports_citations,
)


# ── classify_citation_status 三态归类 ──


def test_classify_captured_when_real_citations_present():
    """抓取成功且有真实引用 → captured。"""
    status = classify_citation_status(
        True,
        [{"url": "https://example.com/a", "domain": "example.com"}],
    )
    assert status == CITATION_STATUS_CAPTURED


def test_classify_empty_when_capture_succeeds_but_zero():
    """抓取成功但零条 → empty(与 unavailable 区分)。"""
    status = classify_citation_status(True, [])
    assert status == CITATION_STATUS_EMPTY


def test_classify_unavailable_when_capture_raises():
    """采集抛异常 → unavailable(即使部分引用已就位也以不可信处理)。"""
    status = classify_citation_status(True, [], capture_error=True)
    assert status == CITATION_STATUS_UNAVAILABLE


def test_classify_not_supported_when_platform_incapable():
    """平台/通道无引用能力 → not_supported,忽略其余入参。"""
    status = classify_citation_status(False, [{"url": "x"}], capture_error=False)
    assert status == CITATION_STATUS_NOT_SUPPORTED


def test_classify_not_supported_overrides_capture_error():
    """无引用能力的平台即使采集报错也归 not_supported,而不是 unavailable。"""
    status = classify_citation_status(False, [], capture_error=True)
    assert status == CITATION_STATUS_NOT_SUPPORTED


# ── 平台能力判定 ──


def test_platform_supports_by_default():
    """当前 Web 平台均具备引用采集能力。"""
    for platform in ("kimi", "doubao", "deepseek", "qianwen", "qwen"):
        assert platform_supports_citations(platform) is True


def test_platform_unsupported_list_is_empty_registry_placeholder():
    """无能力平台注册表当前为空;清空即全部平台按支持处理。"""
    assert isinstance(CITATION_UNSUPPORTED_PLATFORMS, frozenset)
    assert CITATION_UNSUPPORTED_PLATFORMS == frozenset()


def test_valid_statuses_cover_all_constants():
    """合法状态集合与四个常量一一对应,无拼写漂移。"""
    assert VALID_CITATION_STATUSES == frozenset(
        {
            CITATION_STATUS_CAPTURED,
            CITATION_STATUS_EMPTY,
            CITATION_STATUS_UNAVAILABLE,
            CITATION_STATUS_NOT_SUPPORTED,
        }
    )
