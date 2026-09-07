# -*- coding: utf-8 -*-
"""记忆合并 + 槽位依赖失效。

对应 PRD 第八章：
- 来源优先级：session_slots > user_facts > preferences
- 依赖失效图：company_name 变 → client_id/project_id 失效；project_id 变 → question_ids/article_ids 失效
"""

from __future__ import annotations

from typing import Any


# 依赖失效图：某个槽位变化时，哪些依赖槽位需要失效
DEPENDENCY_INVALIDATION: dict[str, list[str]] = {
    "company_name": ["client_id", "project_id"],  # 公司名变 → 客户ID、项目ID失效
    "client_id": ["project_id"],  # 客户变 → 项目失效
    "project_id": ["question_ids", "article_ids", "keyword_ids"],  # 项目变 → 问题/文章失效
    "question_ids": ["article_ids"],  # 问题变 → 文章失效
    "platforms": ["account_ids"],  # 平台变 → 账号失效
    "category_id": ["document_ids"],  # 分类变 → 文档失效
}


def merge_slots(
    session_slots: dict[str, Any], user_facts: dict[str, Any], preferences: dict[str, Any]
) -> dict[str, Any]:
    """三层合并：session > facts > preferences。

    返回 effective_slots。None 值不覆盖。
    """
    effective: dict[str, Any] = {}
    # 优先级从低到高
    for source in (preferences, user_facts, session_slots):
        if not source:
            continue
        for key, value in source.items():
            if value is not None:
                effective[key] = value
    return effective


def get_invalidation_chain(changed_key: str) -> list[str]:
    """获取某个槽位变化时需要失效的所有槽位（递归）。"""
    visited: set[str] = set()
    queue: list[str] = [changed_key]
    result: list[str] = []
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        dependents = DEPENDENCY_INVALIDATION.get(current, [])
        for dep in dependents:
            if dep not in visited:
                result.append(dep)
                queue.append(dep)
    return result


def invalidate_slots(slots: dict[str, Any], changed_key: str) -> dict[str, Any]:
    """根据失效图，将依赖槽位置为 None。"""
    chain = get_invalidation_chain(changed_key)
    result = dict(slots)
    for key in chain:
        if key in result:
            result[key] = None
    return result


def detect_changed_keys(old_slots: dict[str, Any], new_slots: dict[str, Any]) -> list[str]:
    """检测哪些槽位的值发生了变化。"""
    changed: list[str] = []
    all_keys = set(old_slots.keys()) | set(new_slots.keys())
    for key in all_keys:
        old_val = old_slots.get(key)
        new_val = new_slots.get(key)
        if old_val != new_val:
            changed.append(key)
    return changed
