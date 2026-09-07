# -*- coding: utf-8 -*-
"""GEO 测评「回答引用证据链」状态契约。

对应 docs/AutoGEO优化方案_2026-09.md 优化项六(引用证据链修复 P0)与
AGENTS.md 数据契约要点(引用三态须在报表区分)。

三态语义(引用证据是否可信、是否真的尝试采集了引用)：

- ``captured``      —— 抓取成功且引用非空(raw_citations 为真实列表)。
- ``empty``         —— 抓取成功但零条引用(raw_citations 为空列表)。
- ``unavailable``   —— 抓取异常(raw_citations 为空,记录标注状态,无法确认零引用)。
- ``not_supported`` —— 平台/通道无引用能力(如 API 通道无 citation 字段),
                      报表层按「null」呈现,不参与引用效果承诺。

报表层展示映射：``not_supported`` → null;``empty`` → [] ;``unavailable`` → unavailable;
``captured`` → 原始引用列表。判卷聚合只对 ``captured`` 计真实引用。
"""

from typing import List, Optional

# 引用状态(存入 geo_evaluation_records.citation_status)
CITATION_STATUS_CAPTURED = "captured"
CITATION_STATUS_EMPTY = "empty"
CITATION_STATUS_UNAVAILABLE = "unavailable"
CITATION_STATUS_NOT_SUPPORTED = "not_supported"

# 合法状态集合(record-result 请求校验用)
VALID_CITATION_STATUSES: frozenset[str] = frozenset(
    {
        CITATION_STATUS_CAPTURED,
        CITATION_STATUS_EMPTY,
        CITATION_STATUS_UNAVAILABLE,
        CITATION_STATUS_NOT_SUPPORTED,
    }
)

# 平台无引用能力的通道标记。当前 3 个浏览器 Web 平台都具备引用展示能力;
# 未来接入 API 通道(DeepSeek API / 文心 API 等无 citation 字段)时在平台注册表标记。
# 该表仅作「通道是否可能产出引用」的快速判定,采集是否真的成功由 worker 上报状态。
CITATION_UNSUPPORTED_PLATFORMS: frozenset[str] = frozenset()


def platform_supports_citations(platform: str) -> bool:
    """该平台是否具备引用采集能力(是否有可抓取的引用字段/展示区)。"""
    return platform not in CITATION_UNSUPPORTED_PLATFORMS


def classify_citation_status(
    capable: bool,
    citations: Optional[List],
    capture_error: bool = False,
) -> str:
    """把一次引用采集的结果归类为三态之一。

    Args:
        capable: 平台/通道是否具备引用能力。
        citations: 采集到的引用原始数据(worker DOM 抽取或 API 返回)。
        capture_error: 采集过程是否抛出异常(与「零条」区分)。
    """
    if not capable:
        return CITATION_STATUS_NOT_SUPPORTED
    if capture_error:
        return CITATION_STATUS_UNAVAILABLE
    return CITATION_STATUS_CAPTURED if citations else CITATION_STATUS_EMPTY
