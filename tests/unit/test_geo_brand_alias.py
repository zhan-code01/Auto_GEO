# -*- coding: utf-8 -*-
"""GEO 品牌别名 / 实体归一化纯单测(无 DB)。

对应 AutoGEO优化方案_2026-09 §六 优化项2 份额口径重写的别名归一模块。
覆盖:内置文本归一 / 尾缀剥离、别名表作用域优先级(项目>客户>全局)、miss 回退内置、
is_own/is_competitor 相等语义(含旧子串互含误判反例)、未知品牌自成实体。
"""

from types import SimpleNamespace

import pytest

from backend.services.geo_brand_alias import (
    BrandAliasResolver,
    alnum_norm,
    canonical_key,
    resolve_matched,
    strip_suffix,
)


def _alias(alias, canonical, client_id=None, project_id=None):
    return SimpleNamespace(alias=alias, canonical_name=canonical, client_id=client_id, project_id=project_id)


# ── 内置文本归一 / 尾缀 ──


def test_alnum_norm_lower_and_strip():
    assert alnum_norm("  某某-Brand 科技(集团)  ") == "某某brand科技集团"
    assert alnum_norm("ACME Inc.") == "acmeinc"


def test_strip_suffix_removes_legal_tail():
    assert strip_suffix("某某科技有限公司") == "某某科技"
    assert strip_suffix("某某集团有限公司") == "某某"
    # 拉丁品牌名无中文尾缀,保持全量
    assert strip_suffix("Acme Inc") == "acmeinc"


def test_canonical_key_strips_tail_consistently():
    assert canonical_key("某某有限公司") == canonical_key("某某")
    assert canonical_key("公司A") == canonical_key("公司A")


# ── 表内命中与作用域优先级 ──


def test_alias_table_global_hit():
    resolver = BrandAliasResolver(
        own_label="公司A",
        watch_labels=[],
        alias_rows=[_alias("A企业", "公司A")],
    )
    assert resolver.canonicalize("A企业") == "公司A"


def test_alias_scope_precedence_project_over_client_over_global():
    resolver = BrandAliasResolver(
        own_label="公司A",
        watch_labels=[],
        alias_rows=[
            _alias("A企业", "全局品牌A", client_id=None, project_id=None),
            _alias("A企业", "客户品牌A", client_id=1, project_id=None),
            _alias("A企业", "项目品牌A", client_id=1, project_id=7),
        ],
    )
    assert resolver.canonicalize("A企业") == "项目品牌A"

    # 只有全局+客户两档时,客户优先
    resolver2 = BrandAliasResolver(
        own_label="公司A",
        alias_rows=[
            _alias("A企业", "全局品牌A", client_id=None, project_id=None),
            _alias("A企业", "客户品牌A", client_id=1, project_id=None),
        ],
    )
    assert resolver2.canonicalize("A企业") == "客户品牌A"

    # 只有全局档时,回退全局
    resolver3 = BrandAliasResolver(own_label="公司A", alias_rows=[_alias("A企业", "全局品牌A")])
    assert resolver3.canonicalize("A企业") == "全局品牌A"


def test_alias_miss_falls_back_to_builtin():
    resolver = BrandAliasResolver(own_label="公司A", alias_rows=[_alias("A企业", "公司A")])
    # 表中无此写法,但内置归一命中我方根(含带尾缀写法)
    assert resolver.canonicalize("公司A") == "公司A"
    assert resolver.canonicalize("公司A有限公司") == "公司A"
    # 非我方写法:未在表、也未命中根 → 自成实体
    assert resolver.canonicalize("路人科技") == "路人科技"


def test_empty_alias_rows_no_hit():
    resolver = BrandAliasResolver(own_label="公司A", alias_rows=[])
    assert resolver.canonicalize("随便写") == "随便写"  # 未知自成实体


# ── is_own / is_competitor 相等语义 ──


def test_is_own_by_canonical_equality():
    resolver = BrandAliasResolver(own_label="公司A")
    assert resolver.is_own("公司A") is True
    assert resolver.is_own("公司A有限公司") is True  # 尾缀剥除后相等


def test_no_substring_own_confusion():
    """旧实现用子串互相包含会把 XXA科技有限公司 误判为我方;现按规范键相等应判 False。"""
    resolver = BrandAliasResolver(own_label="A科技")
    other = resolver.canonicalize("XXA科技有限公司")
    assert other is not None
    assert resolver.is_own(other) is False


def test_is_competitor_only_for_watch_root():
    resolver = BrandAliasResolver(own_label="公司A", watch_labels=["公司B", "B公司"])
    assert resolver.is_competitor("公司B") is True
    # B公司 的规范键与 公司B 相同 → 仍判竞品(观察名单归一)
    assert resolver.is_competitor("B公司") is True
    assert resolver.is_competitor("公司A") is False  # 我方不算竞品
    assert resolver.is_competitor("路人甲") is False


def test_alias_can_redirect_to_competitor_root():
    resolver = BrandAliasResolver(
        own_label="公司A",
        watch_labels=["公司B"],
        alias_rows=[_alias("B技术有限公司", "公司B")],
    )
    assert resolver.is_competitor(resolver.canonicalize("B技术有限公司")) is True


def test_alias_redirect_to_own_marked_own():
    resolver = BrandAliasResolver(own_label="公司A", alias_rows=[_alias("A企业", "公司A")])
    assert resolver.is_own(resolver.canonicalize("A企业")) is True


# ── 未知品牌自成实体 ──


def test_unknown_brands_stay_distinct():
    resolver = BrandAliasResolver(own_label="公司A", watch_labels=[])
    a = resolver.canonicalize("路人科技")
    b = resolver.canonicalize("路人智能")
    assert a and b
    assert a != b


def test_resolve_matched_dedups_to_canonical_set():
    resolver = BrandAliasResolver(
        own_label="公司A",
        watch_labels=["公司B"],
        alias_rows=[_alias("A企业", "公司A")],
    )
    names = ["公司A", "A企业", "公司B", "随便写", "", None, "   "]
    result = resolve_matched(names, resolver)
    assert result == {"公司A", "公司B", "随便写"}


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
