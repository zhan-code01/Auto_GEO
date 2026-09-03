# -*- coding: utf-8 -*-
"""Agent V2 记忆层单元测试。

覆盖 PRD 第八章：
- merge_slots 三层合并（session > facts > preferences）
- 依赖失效图（company_name 变 → client_id/project_id 失效）
- 检测变化键

注意：这些函数是 V1 遗留的槽位管理逻辑，V2 ReAct 模式下不再使用。
保留测试以确保代码质量，导入路径从 memory.merger 直接导入。
"""
from __future__ import annotations

from backend.services.agent_v2.memory.merger import (
    DEPENDENCY_INVALIDATION,
    detect_changed_keys,
    get_invalidation_chain,
    invalidate_slots,
    merge_slots,
)


# ============================================================
#  merge_slots 测试
# ============================================================

class TestMergeSlots:
    """三层合并测试。"""

    def test_empty_all(self):
        """所有层为空，返回空。"""
        assert merge_slots({}, {}, {}) == {}

    def test_only_preferences(self):
        """只有 preferences。"""
        prefs = {"tone": "professional", "default_project_id": 123}
        assert merge_slots({}, {}, prefs) == prefs

    def test_only_facts(self):
        """只有 user_facts。"""
        facts = {"company_name": "阿里云", "industry": "科技"}
        assert merge_slots({}, facts, {}) == facts

    def test_only_session(self):
        """只有 session_slots。"""
        session = {"project_id": 456, "count": 5}
        assert merge_slots(session, {}, {}) == session

    def test_priority_session_over_facts(self):
        """session 覆盖 facts。"""
        session = {"company_name": "新公司"}
        facts = {"company_name": "老公司", "industry": "食品"}
        result = merge_slots(session, facts, {})
        assert result["company_name"] == "新公司"  # session 覆盖
        assert result["industry"] == "食品"  # facts 保留

    def test_priority_facts_over_preferences(self):
        """facts 覆盖 preferences。"""
        facts = {"default_project_id": 123}
        prefs = {"default_project_id": 999, "tone": "casual"}
        result = merge_slots({}, facts, prefs)
        assert result["default_project_id"] == 123  # facts 覆盖
        assert result["tone"] == "casual"  # prefs 保留

    def test_none_value_not_override(self):
        """None 值不覆盖。"""
        session = {"company_name": None}  # session 显式 None
        facts = {"company_name": "阿里云"}
        result = merge_slots(session, facts, {})
        assert result["company_name"] == "阿里云"  # facts 保留，None 不覆盖

    def test_full_merge(self):
        """完整三层合并。"""
        session = {"project_id": 456, "count": 5}
        facts = {"company_name": "阿里云", "industry": "科技", "default_project_id": 123}
        prefs = {"tone": "professional", "default_project_id": 999}
        result = merge_slots(session, facts, prefs)
        assert result == {
            "project_id": 456,
            "count": 5,
            "company_name": "阿里云",
            "industry": "科技",
            "default_project_id": 123,  # facts 覆盖 prefs
            "tone": "professional",
        }


# ============================================================
#  依赖失效测试
# ============================================================

class TestDependencyInvalidation:
    """依赖失效图测试。"""

    def test_company_name_invalidates_client_and_project(self):
        """公司名变 → client_id、project_id 失效。"""
        chain = get_invalidation_chain("company_name")
        assert "client_id" in chain
        assert "project_id" in chain

    def test_client_id_invalidates_project(self):
        """客户变 → 项目失效。"""
        chain = get_invalidation_chain("client_id")
        assert "project_id" in chain

    def test_project_id_invalidates_questions_and_articles(self):
        """项目变 → 问题、文章失效。"""
        chain = get_invalidation_chain("project_id")
        assert "question_ids" in chain
        assert "article_ids" in chain

    def test_invalidate_slots_sets_none(self):
        """invalidate_slots 把依赖槽位置 None。"""
        slots = {"company_name": "新公司", "client_id": 123, "project_id": 456}
        result = invalidate_slots(slots, "company_name")
        assert result["company_name"] == "新公司"  # 自身保留
        assert result["client_id"] is None  # 失效
        assert result["project_id"] is None  # 失效

    def test_invalidate_slots_preserves_unrelated(self):
        """invalidate_slots 不影响无关槽位。"""
        slots = {"company_name": "新公司", "client_id": 123, "industry": "科技"}
        result = invalidate_slots(slots, "company_name")
        assert result["industry"] == "科技"  # 无关项保留

    def test_cascade_invalidation(self):
        """级联失效：company_name 变 → client_id 失效 → project_id 失效。"""
        chain = get_invalidation_chain("company_name")
        # client_id 依赖 company_name，project_id 依赖 client_id
        assert "client_id" in chain
        assert "project_id" in chain


# ============================================================
#  变化检测测试
# ============================================================

class TestDetectChangedKeys:
    """变化键检测测试。"""

    def test_no_change(self):
        """无变化。"""
        old = {"a": 1, "b": 2}
        new = {"a": 1, "b": 2}
        assert detect_changed_keys(old, new) == []

    def test_value_changed(self):
        """值变化。"""
        old = {"a": 1}
        new = {"a": 2}
        assert "a" in detect_changed_keys(old, new)

    def test_key_added(self):
        """新增键。"""
        old = {"a": 1}
        new = {"a": 1, "b": 2}
        assert "b" in detect_changed_keys(old, new)

    def test_key_removed(self):
        """删除键。"""
        old = {"a": 1, "b": 2}
        new = {"a": 1}
        assert "b" in detect_changed_keys(old, new)
