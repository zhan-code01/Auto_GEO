# -*- coding: utf-8 -*-
"""验证 _to_langchain_messages 兼容 BaseMessage 和 dict 两种格式。"""
import sys
sys.path.insert(0, ".")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from backend.services.agent_v2.nodes.agent_node import _to_langchain_messages

print("=== 测试 _to_langchain_messages 兼容性 ===")

# 测试 1: 纯 BaseMessage 列表（add_messages reducer 转换后的实际格式）
print("\n--- 测试 1: 纯 BaseMessage 列表 ---")
base_messages = [
    HumanMessage(content="帮我创建客户", id="msg_1"),
    AIMessage(
        content="请提供信息",
        tool_calls=[{"name": "list_clients", "args": {}, "id": "call_1", "type": "tool_call"}],
        id="msg_2",
    ),
    ToolMessage(content="[]", tool_call_id="call_1", id="msg_3"),
    HumanMessage(content="公司叫阿里云", id="msg_4"),
]
result = _to_langchain_messages(base_messages)
print(f"输入: {len(base_messages)} 条 BaseMessage")
print(f"输出: {len(result)} 条 BaseMessage")
assert len(result) == 4
assert all(isinstance(m, (HumanMessage, AIMessage, ToolMessage, SystemMessage)) for m in result)
print("PASS - BaseMessage 直接使用，无异常")

# 测试 2: 纯 dict 列表（make_initial_state 初始格式）
print("\n--- 测试 2: 纯 dict 列表 ---")
dict_messages = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好，有什么可以帮您？"},
    {"role": "user", "content": "帮我建客户"},
]
result = _to_langchain_messages(dict_messages)
print(f"输入: {len(dict_messages)} 条 dict")
print(f"输出: {len(result)} 条 BaseMessage")
assert len(result) == 3
assert isinstance(result[0], HumanMessage)
assert isinstance(result[1], AIMessage)
assert isinstance(result[2], HumanMessage)
print("PASS - dict 正确转换为 BaseMessage")

# 测试 3: 混合格式（BaseMessage + dict，可能出现在 Checkpoint 恢复场景）
print("\n--- 测试 3: 混合格式 ---")
mixed_messages = [
    HumanMessage(content="历史消息", id="msg_1"),
    {"role": "assistant", "content": "历史回复"},
    AIMessage(content="带工具调用", tool_calls=[{"name": "test", "args": {}, "id": "c1", "type": "tool_call"}]),
    {"role": "tool", "content": "工具结果", "tool_call_id": "c1"},
]
result = _to_langchain_messages(mixed_messages)
print(f"输入: {len(mixed_messages)} 条混合消息")
print(f"输出: {len(result)} 条 BaseMessage")
assert len(result) == 4
print("PASS - 混合格式正确处理")

# 测试 4: AIMessage with tool_calls（BaseMessage 格式）
print("\n--- 测试 4: AIMessage with tool_calls ---")
ai_msg = AIMessage(
    content="",
    tool_calls=[{"name": "create_client", "args": {"company_name": "test"}, "id": "call_1", "type": "tool_call"}],
)
result = _to_langchain_messages([ai_msg])
print(f"输出: {result[0]}")
assert isinstance(result[0], AIMessage)
assert len(result[0].tool_calls) == 1
assert result[0].tool_calls[0]["name"] == "create_client"
print("PASS - AIMessage tool_calls 保留")

# 测试 5: 空列表
print("\n--- 测试 5: 空列表 ---")
result = _to_langchain_messages([])
assert result == []
print("PASS - 空列表正确处理")

# 测试 6: 未知类型跳过
print("\n--- 测试 6: 未知类型跳过 ---")
result = _to_langchain_messages(["invalid_string", 123, None])
assert len(result) == 0
print("PASS - 未知类型正确跳过")

print("\n=== 全部测试通过 ===")
