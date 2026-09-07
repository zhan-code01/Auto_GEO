"""GEO 品牌别名 / 实体归一化(份额口径用,纯逻辑,不依赖 DB)。

对应 AutoGEO优化方案_2026-09 §六 优化项2(P0 份额口径重写)的"补品牌别名表 +
系统性实体归一化"。判卷落库的 matched_names 是 LLM 自由文本,同一品牌常有多种写法;
聚合读时用本模块把写法归一到规范名,替代旧 geo_evaluation_analytics_service 里的
子串互含判断(_normalize_brand_text 仅做"去非字母数字+小写")。

设计:
- 别名表(geo_brand_aliases)作用域:项目级 > 客户级 > 全局;先精确查表,命中即归一到 canonical_name。
- 未命中表时回退内置规则:与自身/竞品观察名单做"规范键相等"(剥离常见公司尾缀后相等),仍不中就
  未知品牌自成实体(用全量 alnum 归一文本,不剥尾缀,防过度合并)。
- is_own/is_competitor 一律以规范键相等判断,取代旧的子串互相包含(会误判如 `A科技` 与 `XXA科技有限公司`)。
- 本模块不 import 任何 DB/模型,保持纯函数;DB 行由调用方传入(真实 ORM 行或测试 SimpleNamespace)。
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Set

# 常见公司名称尾缀,长→短,命中一次移除一个后重扫(用于两两相等比较,两侧同规则故确定)。
# 刻意保持最小:完整别名治理归 geo_brand_aliases 表,不做字符串启发式大表。
SUFFIXES: tuple = (
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "股份有限公司分公司",
    "有限公司",
    "责任公司",
    "股份公司",
    "集团公司",
    "控股",
    "集团",
    "股份",
    "公司",
)


def alnum_norm(text: str) -> str:
    """去非字母数字 + 小写(与旧 _normalize_brand_text 语义一致)。"""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def strip_suffix(text: str) -> str:
    """alnum_norm 后反复移除单个公司尾缀(剥离前保证不剥空)。"""
    norm = alnum_norm(text)
    changed = True
    while changed:
        changed = False
        for suffix in SUFFIXES:
            if len(norm) > len(suffix) and norm.endswith(suffix):
                norm = norm[: -len(suffix)]
                changed = True
                break
    return norm


def canonical_key(label: str) -> str:
    """实体比较键:剥尾缀(用于根/自身/观察名单的相等比较)。"""
    return strip_suffix(label)


def alias_lookup_key(raw: str) -> str:
    """表内精确命中键:只做 alnum_norm,不剥尾缀(alias 按原始拼写归一后精确比对)。"""
    return alnum_norm(raw)


class BrandAliasResolver:
    """一次聚合会话的品牌解析器。

    参数:
        own_label:      我方规范名(client.company_name or client.name)。
        watch_labels:   竞品观察名单原始写法(项目 prompt.competitor_names 并集)。
        alias_rows:     geo_brand_aliases 行(已按 client/project 过滤),可为 None/空。
                        row 需有 .alias/.canonical_name/.client_id/.project_id。
    """

    def __init__(
        self,
        *,
        own_label: Optional[str] = None,
        watch_labels: Iterable[str] = (),
        alias_rows: Optional[Sequence[object]] = None,
    ) -> None:
        own_label = (own_label or "").strip()
        self.own_label: Optional[str] = own_label or None
        self.own_key: str = canonical_key(own_label) if own_label else ""

        # 观察名单:规范键 -> 展示名(首个命中保留)
        self._watch: Dict[str, str] = {}
        for w in watch_labels:
            if not w or not isinstance(w, str):
                continue
            key = canonical_key(w.strip())
            if key:
                self._watch.setdefault(key, w.strip())

        # 别名桶:作用域 -> {alias 键 -> canonical_name}
        self._table: Dict[str, Dict[str, str]] = {"project": {}, "client": {}, "global": {}}
        for row in alias_rows or ():
            scope = self._row_scope(row)
            if scope is None:
                continue
            lookup = alias_lookup_key(getattr(row, "alias", "") or "")
            if lookup:
                self._table[scope].setdefault(lookup, (getattr(row, "canonical_name", "") or "").strip())

    @staticmethod
    def _row_scope(row: object) -> Optional[str]:
        client_id = getattr(row, "client_id", None)
        project_id = getattr(row, "project_id", None)
        if client_id is None and project_id is None:
            return "global"
        if client_id is not None and project_id is None:
            return "client"
        # client_id 有值 + project_id 有值 => project 级;不支持 client NULL + project 有值
        return "project"

    @property
    def watch_keys(self) -> Set[str]:
        return set(self._watch)

    def canonicalize(self, raw: str) -> Optional[str]:
        """把一种原始写法归一到规范品牌名;无法归一时返回 None。

        顺序:表内(项目>客户>全局)→ 我方根相等 → 观察名单相等 → 未知品牌自成实体(alnum_norm)。
        """
        text = (raw or "").strip()
        if not text:
            return None

        lookup = alias_lookup_key(text)
        for scope in ("project", "client", "global"):
            canonical = self._table[scope].get(lookup)
            if canonical:
                return canonical

        key = canonical_key(text)
        if self.own_key and key == self.own_key:
            return self.own_label
        if key in self._watch:
            return self._watch[key]

        # 未知:自成实体,保留全量 alnum 文本(不去尾缀,防两个不同品牌被并成一个)
        self_key = alnum_norm(text)
        return self_key or None

    def is_own(self, canonical_label: str) -> bool:
        if not self.own_key or not canonical_label:
            return False
        return canonical_key(canonical_label) == self.own_key

    def is_competitor(self, canonical_label: str) -> bool:
        if not canonical_label or self.is_own(canonical_label):
            return False
        return canonical_key(canonical_label) in self._watch


def resolve_matched(names, resolver: BrandAliasResolver) -> Set[str]:
    """把一条回答的 matched_names 原始写法集,归一为规范品牌名集合(空/无效项剔除)。"""
    out: Set[str] = set()
    for n in names or ():
        if not isinstance(n, str) or not n.strip():
            continue
        canonical = resolver.canonicalize(n.strip())
        if canonical:
            out.add(canonical)
    return out
