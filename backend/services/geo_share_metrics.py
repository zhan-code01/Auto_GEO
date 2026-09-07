"""GEO 份额口径引擎(纯逻辑,无 DB) — share 口径重写 §六 优化项2 / P0。

把旧的单值 share(提及次数/回答数,多品牌同现可 >100%,非真正 SOV)重写为四个指标,
计数以"多轮去重后的单元"为准:

  - mention_rate            = 品牌被提及的单元数 / 总有效单元数          (多品牌同现时品牌间总和可 >100%)
  - answer_share            = 品牌提及单元数 / 全品牌提及单元总数        (总和=100%)
  - citation_share          = 域名被引用单元数 / 全域名被引用单元总数    (总和≈100%)
  - qualified_citation_share= 仅计"有原始证据(captured + raw_citations 非空)"的合格引用域名份额

口径版本化:share 从不落库,版本挂在模块常量 + 输出契约(metric_version)。旧 share 字段只读保留、
按 v1 公式以"去重前记录行数 R"作分母计算,仅供存量兼容,不再是权威口径;新指标自 v2 起权威。

多轮去重:计数单元 = (run_id, question, platform);同一 run 内多轮对同一问题×平台重复回答折叠为一个
单元;run_id 缺失的遗留行退化为 (id, question, platform) 各自成单元防误并。跨轮取并集(≥1 轮命中即算)。

qualified 近似(v1):citations 须 citation_status=='captured' 且 raw_citations 非空("有原始证据")。
来源质量分级后置,遗留 citation_status IS NULL 视为不合格——见 QUALIFIED_CITATION_DEF 注释。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from backend.services.geo_brand_alias import BrandAliasResolver, resolve_matched

# 口径版本
SHARE_METRIC_VERSION = 2
LEGACY_SHARE_METRIC_VERSION = 1
SHARE_METRIC_VERSION_LABEL = "share_v2_four_metrics_dedup"
# 合格引用口径近似定义标识;来源质量分级到齐后据此升级(届时 bump 版本号,勿静默改)
QUALIFIED_CITATION_DEF = "v1_captured_with_raw"

# 判卷为判卷本身匹配对象用的自有来源判定在此不适用;下方为引擎内部保留


def _pct(num: int, den: int) -> float:
    """百分比一位小数;den<=0 记 0。"""
    return round(num / den * 100, 1) if den else 0.0


def bare_domain(url) -> Optional[str]:
    """从 url 提取裸域名(与 analytics _extract_domain 语义一致,保持本模块纯/独立)。"""
    if not url or not str(url).strip():
        return None
    text = str(url).strip().lower()
    if text.startswith(("http://", "https://")):
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0].split(":", 1)[0]
    return text or None


def citation_domain(entry) -> Optional[str]:
    """从一条 raw_citations 项提取裸域名。支持 dict(url/domain/href) 或裸字符串。"""
    if isinstance(entry, dict):
        d = entry.get("domain")
        if d:
            return str(d).strip().lower()
        url = entry.get("url") or entry.get("href") or entry.get("src")
        if url:
            return bare_domain(url)
        return None
    if isinstance(entry, str) and entry.strip():
        return bare_domain(entry)
    return None


@dataclass
class RecordUnit:
    """一次(问题×平台)的多轮测量单元。key=(run_or_legacy, question, platform)。"""

    key: tuple
    records: List[Any] = field(default_factory=list)


def build_units(records: Iterable[Any]) -> List[RecordUnit]:
    """把记录按 (run_id, question, platform) 折叠成单元;run_id 缺失的遗留行按行各自成单元。"""
    buckets: Dict[tuple, List[Any]] = {}
    for rec in records:
        run_id = getattr(rec, "run_id", None)
        question = (getattr(rec, "question", None) or "").strip()
        platform = (getattr(rec, "platform", None) or "").strip()
        if run_id is not None:
            key = (run_id, question, platform)
        else:
            key = (f"legacy:{getattr(rec, 'id', None)}", question, platform)
        buckets.setdefault(key, []).append(rec)

    units: List[RecordUnit] = []
    for key, recs in sorted(buckets.items(), key=lambda kv: (kv[0][1], kv[0][2], str(kv[0][0]))):
        recs_sorted = sorted(recs, key=lambda r: ((getattr(r, "round_no", None) or 0), getattr(r, "id", 0) or 0))
        units.append(RecordUnit(key=key, records=recs_sorted))
    return units


def _unit_brands(recs: List[Any], resolver: BrandAliasResolver) -> Set[str]:
    return resolve_matched([n for r in recs for n in (getattr(r, "matched_names", None) or ())], resolver)


def _unit_domains(recs: List[Any]) -> Set[str]:
    out: Set[str] = set()
    for r in recs:
        for d in getattr(r, "cited_domains", None) or ():
            if isinstance(d, str) and d.strip():
                out.add(d.strip().lower())
    return out


def _record_qualified_domains(rec) -> Set[str]:
    """合格引用域名:仅 captured + raw_citations 非空。遗留(NULL)状态一律不合格。"""
    if getattr(rec, "citation_status", None) != "captured":
        return set()
    raw = getattr(rec, "raw_citations", None)
    if not raw:  # None/[] 皆无原始证据
        return set()
    return {d for d in (citation_domain(e) for e in raw) if d}


def _unit_qualified_domains(recs: List[Any]) -> Set[str]:
    out: Set[str] = set()
    for r in recs:
        out |= _record_qualified_domains(r)
    return out


def _unit_own_cited(recs: List[Any]) -> bool:
    return any(bool(getattr(r, "own_source_cited", False)) for r in recs)


@dataclass
class ShareAggregate:
    """v2 单元级聚合计数(全部以单元为分母)。"""

    total_units: int = 0
    brand_units: Counter = field(default_factory=Counter)
    brand_sum: int = 0
    own_units: int = 0
    domain_units: Counter = field(default_factory=Counter)
    domain_sum: int = 0
    qualified_domain_units: Counter = field(default_factory=Counter)
    qualified_sum: int = 0

    @property
    def own_unit_rate(self) -> float:
        return _pct(self.own_units, self.total_units)


def aggregate_share(units: Iterable[RecordUnit], resolver: BrandAliasResolver) -> ShareAggregate:
    agg = ShareAggregate()
    for u in units:
        recs = u.records
        agg.total_units += 1
        brands = _unit_brands(recs, resolver)
        for b in brands:
            agg.brand_units[b] += 1
        agg.brand_sum += len(brands)
        domains = _unit_domains(recs)
        for d in domains:
            agg.domain_units[d] += 1
        agg.domain_sum += len(domains)
        qd = _unit_qualified_domains(recs)
        for d in qd:
            agg.qualified_domain_units[d] += 1
        agg.qualified_sum += len(qd)
        if _unit_own_cited(recs):
            agg.own_units += 1
    return agg


@dataclass
class LegacyRowCounts:
    """v1 旧口径计数(分母 = 去重前记录行数 R;只读保留、停更)。"""

    record_count: int = 0
    brand_counts: Counter = field(default_factory=Counter)
    domain_counts: Counter = field(default_factory=Counter)
    own_cited_rows: int = 0


def legacy_row_counts(records: Iterable[Any], resolver: BrandAliasResolver) -> LegacyRowCounts:
    """旧 v1 公式所需计数:每条记录按原始 matched_names 出现一次计入(不跨轮并集),再归一到规范名。"""
    counts = LegacyRowCounts()
    for rec in records:
        counts.record_count += 1
        for name in getattr(rec, "matched_names", None) or ():
            if not isinstance(name, str) or not name.strip():
                continue
            canonical = resolver.canonicalize(name.strip())
            if canonical:
                counts.brand_counts[canonical] += 1
        for d in getattr(rec, "cited_domains", None) or ():
            if isinstance(d, str) and d.strip():
                counts.domain_counts[d.strip().lower()] += 1
        if bool(getattr(rec, "own_source_cited", False)):
            counts.own_cited_rows += 1
    return counts


def _brand_row(canonical: str, mentioned_units: int, agg: ShareAggregate, legacy: LegacyRowCounts, resolver) -> Dict[str, Any]:
    return {
        "name": canonical,
        "canonical": canonical,
        "is_own": resolver.is_own(canonical),
        "is_competitor": resolver.is_competitor(canonical),
        # —— 以下为 v1 旧口径,只读保留、停更 ——
        "mentions": legacy.brand_counts.get(canonical, 0),
        "share": _pct(legacy.brand_counts.get(canonical, 0), legacy.record_count),
        # —— v2 新口径 ——
        "mentioned_units": mentioned_units,
        "mention_rate": _pct(mentioned_units, agg.total_units),
        "answer_share": _pct(mentioned_units, agg.brand_sum),
    }


def _domain_row(domain: str, cited_units: int, qualified_units: int, agg: ShareAggregate, legacy: LegacyRowCounts, own_domain) -> Dict[str, Any]:
    return {
        "domain": domain,
        "is_own": domain == own_domain,
        # v1 旧口径,只读保留
        "citations": legacy.domain_counts.get(domain, 0),
        "share": _pct(legacy.domain_counts.get(domain, 0), legacy.record_count),
        # v2 新口径
        "cited_units": cited_units,
        "citation_share": _pct(cited_units, agg.domain_sum),
        "qualified_cited_units": qualified_units,
        "qualified_citation_share": _pct(qualified_units, agg.qualified_sum),
    }


def compute_share_report(
    *,
    records: List[Any],
    resolver: BrandAliasResolver,
    own_domain: Optional[str] = None,
    watch_names: Iterable[str] = (),
    platform_names: Optional[Dict[str, str]] = None,
    top_domains: int = 15,
    client_id: Optional[int] = None,
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
    """输出客户级竞品/来源分析契约(含 metric_version 标注),纯函数便于整包测试。

    返回 dict 顶层:旧键 + 新键 metric_version / total_units / own_source_cited_units /
    own_source_unit_rate / legacy_metric_version,以及 v2 规范名粒度的 brand_shares /
    top_domains / by_platform(每行同时带 v1 只读字段与 v2 字段)。
    """
    units = build_units(records)
    agg = aggregate_share(units, resolver)
    legacy = legacy_row_counts(records, resolver)

    watch = sorted({w.strip() for w in watch_names if isinstance(w, str) and w.strip()})

    brand_rows = [
        _brand_row(label, count, agg, legacy, resolver)
        for label, count in agg.brand_units.most_common()
    ]
    brand_rows.sort(key=lambda x: (-x["mentioned_units"], x["name"]))

    # 域名榜取 v2 cited_units 前 top_domains(并集去重后按单元计)
    top_domain_names = [d for d, _ in agg.domain_units.most_common(max(1, top_domains))]
    domain_rows = [_domain_row(d, agg.domain_units[d], agg.qualified_domain_units.get(d, 0), agg, legacy, own_domain) for d in top_domain_names]

    # 分平台:按平台分组记录 → 各自聚合 + 旧计数
    platform_names_map = platform_names or {}
    by_platform: List[Dict[str, Any]] = []
    platform_groups: Dict[str, List[Any]] = {}
    for rec in records:
        p = (getattr(rec, "platform", None) or "").strip()
        if p:
            platform_groups.setdefault(p, []).append(rec)

    for p in sorted(platform_groups, key=lambda k: -len(platform_groups[k])):
        precords = platform_groups[p]
        punits = build_units(precords)
        pagg = aggregate_share(punits, resolver)
        plegacy = legacy_row_counts(precords, resolver)
        pbrand_rows = [_brand_row(label, count, pagg, plegacy, resolver) for label, count in pagg.brand_units.most_common()]
        pbrand_rows.sort(key=lambda x: (-x["mentioned_units"], x["name"]))
        pdomain_rows = [
            _domain_row(d, pagg.domain_units[d], pagg.qualified_domain_units.get(d, 0), pagg, plegacy, own_domain)
            for d in pagg.domain_units.most_common(max(1, top_domains))
        ]
        by_platform.append(
            {
                "platform": p,
                "platform_name": platform_names_map.get(p, p),
                "total": pagg.total_units,
                "own_source_cited": plegacy.own_cited_rows,
                "own_source_rate": _pct(plegacy.own_cited_rows, plegacy.record_count),
                "legacy_total": plegacy.record_count,
                "own_source_cited_units": pagg.own_units,
                "own_source_unit_rate": _pct(pagg.own_units, pagg.total_units),
                "top_names": pbrand_rows[:5],
                "top_domains": pdomain_rows[:8],
            }
        )

    return {
        "client_id": client_id,
        "company_name": company_name or "",
        "own_domain": own_domain,
        "competitor_watchlist": watch,
        # —— v2 版本标注 ——
        "metric_version": SHARE_METRIC_VERSION,
        "metric_version_label": SHARE_METRIC_VERSION_LABEL,
        "metric_version_note": (
            "口径 v2:多轮已按(问题×平台)去重;answer_share 总和≈100%,mention_rate 因多品牌同现总和可>100%;"
            "qualified_citation_share 仅计 captured+有原始证据引用;旧 share 字段只读保留、停更。"
        ),
        "legacy_metric_version": LEGACY_SHARE_METRIC_VERSION,
        # —— 旧口径字段(只读保留) ——
        "total_records": legacy.record_count,
        "own_source_cited_count": legacy.own_cited_rows,
        "own_source_rate": _pct(legacy.own_cited_rows, legacy.record_count),
        # —— v2 权威字段 ——
        "total_units": agg.total_units,
        "own_source_cited_units": agg.own_units,
        "own_source_unit_rate": _pct(agg.own_units, agg.total_units),
        "brand_shares": brand_rows,
        "top_domains": domain_rows,
        "by_platform": by_platform,
    }
