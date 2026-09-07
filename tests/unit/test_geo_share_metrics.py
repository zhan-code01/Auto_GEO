# -*- coding: utf-8 -*-
"""GEO 份额口径引擎纯单测(无 DB)。

对应 AutoGEO优化方案_2026-09 §六 优化项2 份额口径重写的引擎模块 geo_share_metrics.py。
覆盖:§3.3 微例、answer_share 总和=100、mention_rate 多品牌同现总和可>100、多轮去重折叠、
run_id 缺失遗留行各自成单元、qualified 过滤(captured+有原始证据 才计)、口径版本常量。
"""

from types import SimpleNamespace

import pytest

from backend.services.geo_brand_alias import BrandAliasResolver

from backend.services.geo_share_metrics import (
    LEGACY_SHARE_METRIC_VERSION,
    QUALIFIED_CITATION_DEF,
    SHARE_METRIC_VERSION,
    SHARE_METRIC_VERSION_LABEL,
    build_units,
    compute_share_report,
)


def _alias(alias, canonical, client_id=None, project_id=None):
    return SimpleNamespace(alias=alias, canonical_name=canonical, client_id=client_id, project_id=project_id)


def _rec(run_id, rid, question, platform, matched_names, *, round_no=1, cited_domains=(), raw_citations=None, citation_status="captured", own_source_cited=False):
    return SimpleNamespace(
        run_id=run_id,
        id=rid,
        question=question,
        platform=platform,
        round_no=round_no,
        matched_names=matched_names,
        cited_domains=list(cited_domains),
        raw_citations=list(raw_citations) if raw_citations else ([] if raw_citations is not None else None),
        citation_status=citation_status,
        own_source_cited=own_source_cited,
    )


def _resolver():
    return BrandAliasResolver(
        own_label="公司A",
        watch_labels=["公司B"],
        alias_rows=[_alias("A企业", "公司A", client_id=1)],
    )


# ── 微例 §3.3 ──


def _micro_records():
    """2 单元 4 行:单元A(run1/Q1/doubao,3 轮),单元B(run2/Q2/qianwen)。"""
    return [
        _rec(1, 1, "Q1", "doubao", ["公司A", "公司B", "A企业"], round_no=1, cited_domains=["a.com", "x.com"], raw_citations=[{"domain": "a.com"}, {"domain": "x.com"}], own_source_cited=False),
        _rec(1, 2, "Q1", "doubao", ["公司A"], round_no=2, cited_domains=["a.com"], raw_citations=[{"domain": "a.com"}], own_source_cited=True),
        _rec(1, 3, "Q1", "doubao", ["公司B", "C公司"], round_no=3, cited_domains=[], raw_citations=[], citation_status="empty", own_source_cited=False),
        _rec(2, 4, "Q2", "qianwen", ["公司A"], round_no=1, cited_domains=["b.com"], raw_citations=[{"domain": "b.com"}], own_source_cited=False),
    ]


def test_micro_example_metrics():
    report = compute_share_report(
        records=_micro_records(),
        resolver=_resolver(),
        own_domain="my.com",
        watch_names=["公司B"],
        platform_names={"doubao": "豆包", "qianwen": "通义千问"},
        client_id=1,
        company_name="公司A",
    )

    assert report["metric_version"] == 2
    assert report["total_units"] == 2
    assert report["total_records"] == 4

    brand = {r["canonical"]: r for r in report["brand_shares"]}
    assert set(brand) == {"公司A", "公司B", "c公司"}
    # 提及单元:公司A=2, 公司B=1, c公司=1;brand_sum=4
    assert brand["公司A"]["mentioned_units"] == 2
    assert brand["公司B"]["mentioned_units"] == 1
    assert brand["c公司"]["mentioned_units"] == 1
    # answer_share 总和=100
    assert round(sum(r["answer_share"] for r in report["brand_shares"]), 1) == 100.0
    assert brand["公司A"]["answer_share"] == 50.0
    # mention_rate 总和>100
    assert sum(r["mention_rate"] for r in report["brand_shares"]) > 100.0
    assert brand["公司A"]["mention_rate"] == 100.0
    assert brand["c公司"]["mention_rate"] == 50.0
    # 是/竞品
    assert brand["公司A"]["is_own"] is True
    assert brand["公司B"]["is_competitor"] is True
    assert brand["c公司"]["is_own"] is False and brand["c公司"]["is_competitor"] is False

    # 域名:v2 domain_sum=3 各 33.3;qualified 同样(empty 轮被排除,无影响)
    dom = {r["domain"]: r for r in report["top_domains"]}
    assert set(dom) == {"a.com", "x.com", "b.com"}
    assert round(sum(r["citation_share"] for r in report["top_domains"]), 1) == pytest.approx(100.0, abs=0.2)
    assert dom["a.com"]["cited_units"] == 1
    assert dom["a.com"]["citation_share"] == pytest.approx(33.3, abs=0.1)
    assert dom["b.com"]["qualified_cited_units"] == 1
    assert dom["a.com"]["qualified_citation_share"] == pytest.approx(33.3, abs=0.1)

    # 自有来源引用率(单元级):unitA own,unitB not => 50%
    assert report["own_source_cited_units"] == 1
    assert report["own_source_unit_rate"] == 50.0
    # 旧口径保留且分母为去重前 R=4:mentions 公司A=4(别名 A企业 归一)、share=100
    assert report["own_source_cited_count"] == 1
    assert brand["公司A"]["mentions"] == 4
    assert brand["公司A"]["share"] == 100.0
    assert brand["c公司"]["mentions"] == 1
    assert brand["c公司"]["share"] == 25.0  # v1 vs v2 差异可见

    # 分平台
    assert {b["platform"] for b in report["by_platform"]} == {"doubao", "qianwen"}
    doubao = next(b for b in report["by_platform"] if b["platform"] == "doubao")
    assert doubao["total"] == 1 and doubao["legacy_total"] == 3
    assert doubao["own_source_cited_units"] == 1


# ── 去重语义 ──


def test_dedup_collapses_rounds_and_retry_rows():
    """同一 (run,question,platform) 的 3 轮 + 1 重复提交 → 折 1 单元。"""
    recs = [
        _rec(9, 1, "Q", "doubao", ["公司A"], round_no=1),
        _rec(9, 2, "Q", "doubao", ["公司A", "公司B"], round_no=2),
        _rec(9, 3, "Q", "doubao", ["公司B"], round_no=3),
        _rec(9, 4, "Q", "doubao", ["公司A"], round_no=1),  # 同键重复(重试残留)
    ]
    report = compute_share_report(records=recs, resolver=_resolver(), company_name="公司A")
    assert report["total_units"] == 1
    assert report["total_records"] == 4  # 旧口径仍按行
    brand = {r["canonical"]: r for r in report["brand_shares"]}
    # 并集语义:公司A 在≥1轮出现 → 该单元计 1 次提及(非 3)
    assert brand["公司A"]["mentioned_units"] == 1
    assert brand["公司B"]["mentioned_units"] == 1
    assert brand["公司A"]["mentions"] == 3  # 旧口径:逐行原始出现 3 次


def test_runless_legacy_rows_do_not_collapse():
    """run_id 缺失的遗留行即便同 问题×平台 也各自成单元,防误并。"""
    recs = [
        _rec(None, 100, "Q", "doubao", ["公司A"]),
        _rec(None, 101, "Q", "doubao", ["公司A"]),
    ]
    report = compute_share_report(records=recs, resolver=_resolver())
    assert report["total_units"] == 2
    assert report["brand_shares"][0]["mentioned_units"] == 2


# ── qualified 过滤 ──


def test_qualified_only_counts_captured_with_raw_evidence():
    """六种状态各 1 行、各引用独立域名:仅 captured+有原始证据计入 qualified 份额。"""
    rows = [
        _rec(run_id=5, rid=1, question="Q_cap", platform="doubao", matched_names=[], round_no=1, cited_domains=["cap.com"], raw_citations=[{"domain": "cap.com"}], citation_status="captured"),
        _rec(run_id=5, rid=2, question="Q_noraw", platform="doubao", matched_names=[], round_no=1, cited_domains=["noraw.com"], raw_citations=[], citation_status="captured"),
        _rec(run_id=5, rid=3, question="Q_empty", platform="doubao", matched_names=[], round_no=1, cited_domains=["empty.com"], raw_citations=[{"domain": "empty.com"}], citation_status="empty"),
        _rec(run_id=5, rid=4, question="Q_unavail", platform="doubao", matched_names=[], round_no=1, cited_domains=["unavail.com"], raw_citations=None, citation_status="unavailable"),
        _rec(run_id=5, rid=5, question="Q_null", platform="doubao", matched_names=[], round_no=1, cited_domains=["null.com"], raw_citations=[{"domain": "null.com"}], citation_status=None),
        _rec(run_id=5, rid=6, question="Q_notsup", platform="doubao", matched_names=[], round_no=1, cited_domains=["notsup.com"], raw_citations=[{"domain": "notsup.com"}], citation_status="not_supported"),
    ]

    report = compute_share_report(records=rows, resolver=_resolver())
    assert report["total_units"] == 6
    dom = {r["domain"]: r for r in report["top_domains"]}
    assert set(dom) == {"cap.com", "noraw.com", "empty.com", "unavail.com", "null.com", "notsup.com"}
    # 6 域名各被 1 单元引用 → citation_share 各 ≈16.7
    for drow in report["top_domains"]:
        assert drow["citation_share"] == pytest.approx(16.7, abs=0.1)
    # 仅 captured 且有原始证据的 1 行计入 qualified;其余全部排除
    assert dom["cap.com"]["qualified_cited_units"] == 1
    assert dom["cap.com"]["qualified_citation_share"] == 100.0
    for other in ("noraw.com", "empty.com", "unavail.com", "null.com", "notsup.com"):
        assert dom[other]["qualified_cited_units"] == 0
        assert dom[other]["qualified_citation_share"] == 0.0


# ── 版本常量 ──


def test_version_constants():
    assert SHARE_METRIC_VERSION == 2
    assert LEGACY_SHARE_METRIC_VERSION == 1
    assert SHARE_METRIC_VERSION_LABEL == "share_v2_four_metrics_dedup"
    assert QUALIFIED_CITATION_DEF == "v1_captured_with_raw"


def test_report_carries_version_labels():
    report = compute_share_report(records=_micro_records(), resolver=_resolver())
    assert report["metric_version"] == SHARE_METRIC_VERSION
    assert report["metric_version_label"] == SHARE_METRIC_VERSION_LABEL
    assert report["legacy_metric_version"] == LEGACY_SHARE_METRIC_VERSION
    assert "口径 v2" in report["metric_version_note"]
    # 旧键与空数据守卫
    assert "total_records" in report and "total_units" in report


def test_empty_records_report():
    report = compute_share_report(records=[], resolver=_resolver())
    assert report["total_records"] == 0
    assert report["total_units"] == 0
    assert report["brand_shares"] == []
    assert report["top_domains"] == []
    assert report["own_source_unit_rate"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
