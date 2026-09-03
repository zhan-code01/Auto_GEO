# -*- coding: utf-8 -*-
"""Agent V2 关键路径集成测试。

测试 graph 层面的状态管理：
1. AgentState reducer 行为（add_messages/add_list/last_non_empty）
2. _should_continue 路由逻辑
3. _check_and_clean_interrupted_state 中断恢复
4. make_initial_state 初始状态构造
"""
import sys
sys.path.insert(0, ".")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.services.agent_v2.state import (
    AgentState,
    add_list,
    last_non_empty,
    make_initial_state,
)


# ============================================================
#  Reducer 测试
# ============================================================

def test_add_list_accumulation():
    """add_list reducer 累积合并 list。"""
    # 空列表合并
    assert add_list(None, None) == []
    assert add_list([], []) == []
    # 累积合并
    assert add_list([1, 2], [3, 4]) == [1, 2, 3, 4]
    # None 视为空列表
    assert add_list(None, [1]) == [1]
    assert add_list([1], None) == [1]
    print("PASS test_add_list_accumulation")


def test_add_list_multiround():
    """add_list 多轮 ReAct 循环中不丢失。"""
    # 模拟多轮工具结果累积
    state_results = []
    state_results = add_list(state_results, [{"tool": "list_clients", "result": {}}])
    state_results = add_list(state_results, [{"tool": "create_client", "result": {}}])
    assert len(state_results) == 2
    print("PASS test_add_list_multiround")


def test_last_non_empty():
    """last_non_empty reducer 保留最后非空值。"""
    # 空值不覆盖
    assert last_non_empty("hello", "") == "hello"
    assert last_non_empty("hello", None) == "hello"
    assert last_non_empty("hello", []) == "hello"
    # 非空值覆盖
    assert last_non_empty("hello", "world") == "world"
    # 初始为空
    assert last_non_empty("", "first") == "first"
    assert last_non_empty(None, "first") == "first"
    print("PASS test_last_non_empty")


def test_last_non_empty_react_scenario():
    """last_non_empty 在 ReAct 场景下的行为。

    agent_node 调用工具时返回 reply=""，不应清空 tools_node 已设置的回复。
    """
    # 第一轮：tools_node 设置 reply
    state_reply = last_non_empty("", "客户创建成功")
    assert state_reply == "客户创建成功"
    # 第二轮：agent_node 调用工具，reply=""
    state_reply = last_non_empty(state_reply, "")
    assert state_reply == "客户创建成功"  # 不被空字符串覆盖
    print("PASS test_last_non_empty_react_scenario")


# ============================================================
#  make_initial_state 测试
# ============================================================

def test_make_initial_state():
    """make_initial_state 构造正确的初始状态。"""
    state = make_initial_state(
        user_id=1,
        session_id="test_session",
        message="帮我建客户",
        attachments=[{"type": "material", "filename": "test.pdf"}],
    )
    assert state["user_id"] == 1
    assert state["session_id"] == "test_session"
    assert state["attachments"] == [{"type": "material", "filename": "test.pdf"}]
    assert state["messages"] == [{"role": "user", "content": "帮我建客户"}]
    assert state["task_context"] is None
    assert state["user_facts"] == {}
    assert state["tool_calls"] == []
    assert state["tool_results"] == []
    assert state["reply"] == ""
    assert state["actions"] == []
    assert state["status"] == "completed"
    print("PASS test_make_initial_state")


def test_make_initial_state_no_attachments():
    """make_initial_state 无附件时 attachments 为空列表。"""
    state = make_initial_state(
        user_id=1,
        session_id="test",
        message="hello",
    )
    assert state["attachments"] == []
    print("PASS test_make_initial_state_no_attachments")


# ============================================================
#  _should_continue 路由测试
# ============================================================

def test_should_continue_with_tool_calls():
    """_should_continue: 有 tool_calls 走 tools。"""
    from backend.services.agent_v2.graph import _should_continue
    state = {"tool_calls": [{"name": "create_client", "args": {}, "id": "1"}]}
    assert _should_continue(state) == "tools"
    print("PASS test_should_continue_with_tool_calls")


def test_should_continue_without_tool_calls():
    """_should_continue: 无 tool_calls 走 END。"""
    from langgraph.graph import END
    from backend.services.agent_v2.graph import _should_continue
    state = {"tool_calls": []}
    assert _should_continue(state) == END
    print("PASS test_should_continue_without_tool_calls")


def test_should_continue_none_tool_calls():
    """_should_continue: tool_calls 为 None 走 END。"""
    from langgraph.graph import END
    from backend.services.agent_v2.graph import _should_continue
    state = {"tool_calls": None}
    assert _should_continue(state) == END
    print("PASS test_should_continue_none_tool_calls")


def test_should_continue_missing_key():
    """_should_continue: 缺少 tool_calls 键走 END。"""
    from langgraph.graph import END
    from backend.services.agent_v2.graph import _should_continue
    state = {}
    assert _should_continue(state) == END
    print("PASS test_should_continue_missing_key")


# ============================================================
#  _normalize_db_url 测试
# ============================================================

def test_normalize_db_url_psycopg2():
    """_normalize_db_url: psycopg2 前缀转换。"""
    from backend.services.agent_v2.graph import _normalize_db_url
    url = "postgresql+psycopg2://user:pwd@localhost:5432/db"
    assert _normalize_db_url(url) == "postgresql://user:pwd@localhost:5432/db"
    print("PASS test_normalize_db_url_psycopg2")


def test_normalize_db_url_psycopg3():
    """_normalize_db_url: psycopg3 前缀转换。"""
    from backend.services.agent_v2.graph import _normalize_db_url
    url = "postgresql+psycopg://user:pwd@localhost:5432/db"
    assert _normalize_db_url(url) == "postgresql://user:pwd@localhost:5432/db"
    print("PASS test_normalize_db_url_psycopg3")


def test_normalize_db_url_already_plain():
    """_normalize_db_url: 已经是 postgresql:// 不变。"""
    from backend.services.agent_v2.graph import _normalize_db_url
    url = "postgresql://user:pwd@localhost:5432/db"
    assert _normalize_db_url(url) == url
    print("PASS test_normalize_db_url_already_plain")


# ============================================================
#  make_action 测试
# ============================================================

def test_make_action_valid():
    """make_action: 构造合法的 Action。"""
    from backend.services.agent_v2.actions import make_action
    action = make_action("show_client_list", "查看客户列表", {"page": 1})
    assert action["type"] == "show_client_list"
    assert action["label"] == "查看客户列表"
    assert action["payload"] == {"page": 1}
    assert action["interaction"] == "frontend_direct"
    print("PASS test_make_action_valid")


def test_make_action_invalid_type():
    """make_action: 非法 type 抛出 ValueError。"""
    from backend.services.agent_v2.actions import make_action
    try:
        make_action("invalid_type", "test")
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "invalid_type" in str(e)
        print("PASS test_make_action_invalid_type")


def test_make_action_override_interaction():
    """make_action: 显式指定 interaction 覆盖默认值。"""
    from backend.services.agent_v2.actions import make_action
    action = make_action("show_client_list", "查看", {}, interaction="via_agent")
    assert action["interaction"] == "via_agent"
    print("PASS test_make_action_override_interaction")


# ============================================================
#  events 测试
# ============================================================

def test_format_sse():
    """format_sse: 正确格式化 SSE 事件。"""
    from backend.services.agent_v2.events import format_sse
    result = format_sse("test", {"key": "value"})
    assert "event: test" in result
    assert "data:" in result
    assert '"key": "value"' in result
    assert result.endswith("\n\n")
    print("PASS test_format_sse")


def test_thinking_event():
    """thinking_event: 构造思考过程事件。"""
    from backend.services.agent_v2.events import thinking_event
    result = thinking_event("正在思考...")
    assert "event: thinking" in result
    assert "正在思考" in result
    print("PASS test_thinking_event")


def test_tool_calls_event():
    """tool_calls_event: 构造工具调用事件。"""
    from backend.services.agent_v2.events import tool_calls_event
    result = tool_calls_event([{"name": "create_client", "args": {"x": 1}}])
    assert "event: tool_calls" in result
    assert "create_client" in result
    print("PASS test_tool_calls_event")


def test_done_event():
    """done_event: 构造完成事件。"""
    from backend.services.agent_v2.events import done_event
    result = done_event(
        status="completed",
        session_id="test_session",
        actions=[],
        async_task_refs=[],
        tool_results=[],
    )
    assert "event: done" in result
    assert "completed" in result
    assert "test_session" in result
    print("PASS test_done_event")


if __name__ == "__main__":
    test_add_list_accumulation()
    test_add_list_multiround()
    test_last_non_empty()
    test_last_non_empty_react_scenario()
    test_make_initial_state()
    test_make_initial_state_no_attachments()
    test_should_continue_with_tool_calls()
    test_should_continue_without_tool_calls()
    test_should_continue_none_tool_calls()
    test_should_continue_missing_key()
    test_normalize_db_url_psycopg2()
    test_normalize_db_url_psycopg3()
    test_normalize_db_url_already_plain()
    test_make_action_valid()
    test_make_action_invalid_type()
    test_make_action_override_interaction()
    test_format_sse()
    test_thinking_event()
    test_tool_calls_event()
    test_done_event()
    print()
    print("=== 全部集成测试通过 ===")
