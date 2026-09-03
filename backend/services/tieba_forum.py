# -*- coding: utf-8 -*-
"""
百度贴吧「目标吧」编码 —— 单一事实源。

吧名跟着账号走：绑定贴吧账号时配置一个或多个目标吧，存进 Account.tags（JSON 列表），
以 "吧:" 前缀编码，第一条命中的为默认发布吧。tags 里的非吧标签（如 "主账号"）原样保留。

写入方（api/account.py）与读取方（api/client_publish.py 的 payload 解析、
services/playwright/publishers/tieba.py 发布器）都必须走这里，避免前缀约定各写一套导致
「配置了吧但发布时解析不到」的静默失败。
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

# 目标吧在 tags 里的编码前缀（写入统一用第一个；读取时全部识别以兼容手工录入）
FORUM_TAG_PREFIXES = ("吧:", "吧：", "tieba:", "forum:", "目标吧:", "目标吧：")
_CANONICAL_PREFIX = "吧:"


def normalize_forum(name: str) -> str:
    """规范化吧名：去引号/空白，去掉结尾的"吧"字（选择吧输入通常不带"吧"）。"""
    name = (name or "").strip().strip('"').strip("'").strip()
    if name.endswith("吧") and len(name) > 1:
        name = name[:-1]
    return name.strip()


def encode_forum_tag(name: str) -> str:
    """把干净吧名编码成 tags 里的一条，如 "餐饮创业" → "吧:餐饮创业"。"""
    return f"{_CANONICAL_PREFIX}{normalize_forum(name)}"


def _decode_one(tag: Any) -> Optional[str]:
    """若该 tag 是吧编码，返回规范化吧名；否则 None。"""
    text = str(tag).strip()
    for prefix in FORUM_TAG_PREFIXES:
        if text.startswith(prefix):
            name = normalize_forum(text[len(prefix):])
            return name or None
    return None


def _as_list(tags: Any) -> List[Any]:
    if not tags:
        return []
    if isinstance(tags, (list, tuple)):
        return list(tags)
    return [tags]


def split_forum_tags(tags: Any) -> Tuple[List[str], List[str]]:
    """把 tags 拆成 (吧名列表, 其它标签列表)。吧名保持出现顺序，第一条为默认。"""
    forums: List[str] = []
    others: List[str] = []
    for tag in _as_list(tags):
        name = _decode_one(tag)
        if name is not None:
            if name not in forums:
                forums.append(name)
        else:
            others.append(str(tag))
    return forums, others


def default_forum_from_tags(tags: Any) -> Optional[str]:
    """从 tags 里取默认目标吧（第一条 "吧:" 编码）。无则 None。"""
    forums, _ = split_forum_tags(tags)
    return forums[0] if forums else None


def build_tags_with_forums(forums: List[str], other_tags: List[str]) -> List[str]:
    """把目标吧列表（第一条为默认）编码回 tags，拼在其它标签前面，去重去空。"""
    encoded: List[str] = []
    seen = set()
    for raw in forums or []:
        name = normalize_forum(str(raw))
        if not name or name in seen:
            continue
        seen.add(name)
        encoded.append(encode_forum_tag(name))
    return encoded + list(other_tags or [])
