# -*- coding: utf-8 -*-
"""P0 修复回归测试（直接验证源码，不复制逻辑）。

覆盖 2026-08-11 修复的四个 P0 问题：
1. P0-1 越权：geo_evaluation_tools 三个工具带 scoped_query 归属校验
2. P0-2 字段对齐：_REQUIRED_SLOTS["create_project"] 与 System Prompt / Schema 一致
   （此前为 project_name/keywords，导致多轮追问死循环）
3. P0-3 直接路由补 persist_mem：按钮操作不再丢失对话历史
4. P0-4 心跳接入：_heartbeat 被 event_stream 合并器消费，长任务 SSE 保活

注意：本测试直接 import 源码模块验证真实行为；
tests/unit/agent_v2/test_task_context_parsing.py 是复制版逻辑，测不到源码修复。
"""
import inspect

import pytest


class TestRequiredSlotsFieldNames:
    """P0-2: create_project 必填槽位字段名对齐。"""

    def test_required_slots_use_name_and_domain_keyword(self):
        from backend.services.agent_v2.nodes.agent_node import _REQUIRED_SLOTS

        assert _REQUIRED_SLOTS["create_project"] == [
            "client_id", "name", "domain_keyword",
        ]

    def test_system_prompt_matches_required_slots(self):
        from backend.services.agent_v2.nodes.agent_node import SYSTEM_PROMPT

        assert "create_project: client_id, name, domain_keyword" in SYSTEM_PROMPT

    def test_missing_slots_empty_when_info_complete(self):
        """LLM 提供全量信息后 missing_slots 必须为空（此前会误判缺失死循环）。"""
        from backend.services.agent_v2.nodes.agent_node import (
            _parse_task_context_from_content,
        )

        tc_json = (
            '{"type": "create_project", "slots": '
            '{"client_id": 1, "name": "GEO优化", "domain_keyword": "AI搜索引擎优化"}}'
        )
        parsed = _parse_task_context_from_content(
            f"<task_context>{tc_json}</task_context>项目已创建"
        )
        assert parsed is not None
        assert parsed["missing_slots"] == []

    def test_missing_slots_listed_when_partial(self):
        from backend.services.agent_v2.nodes.agent_node import (
            _parse_task_context_from_content,
        )

        tc_json = '{"type": "create_project", "slots": {"client_id": 1}}'
        parsed = _parse_task_context_from_content(
            f"<task_context>{tc_json}</task_context>还缺什么"
        )
        assert parsed is not None
        assert set(parsed["missing_slots"]) == {"name", "domain_keyword"}


class TestGeoToolsOwnershipGuard:
    """P0-1: GEO 工具越权防护。"""

    @pytest.mark.parametrize("tool_name", [
        "create_baseline_tool",
        "run_recheck_tool",
        "get_diagnosis_tool",
    ])
    def test_tool_has_scoped_query_guard(self, tool_name):
        from backend.services.agent_v2.tools import geo_evaluation_tools

        src = inspect.getsource(geo_evaluation_tools)
        m = __import__("re").search(
            rf"async def {tool_name}.*?(?=\n@register_tool|\Z)", src, __import__("re").S
        )
        body = m.group(0) if m else ""
        assert "scoped_query" in body, f"{tool_name} 缺少 scoped_query 归属校验"
        assert "owned_client" in body, f"{tool_name} 缺少 owned_client 校验"
        assert "不存在或无权限访问" in body, f"{tool_name} 缺少无权限拦截"


class TestDirectRoutePersist:
    """P0-3/P0-4: agent_v2.py 直接路由持久化 + 心跳合并。"""

    def _api_source(self) -> str:
        from backend.api import agent_v2 as av2_mod

        return inspect.getsource(av2_mod)

    def test_direct_route_calls_persist_mem(self):
        src = self._api_source()
        assert "await persist_mem(persist_state)" in src
        assert "_DIRECT_TOOL_ROUTING" in src

    def test_heartbeat_consumed_by_stream_merger(self):
        src = self._api_source()
        assert "async for hb_event in _heartbeat" in src
        assert "async for sse_event in _main_event_stream" in src
