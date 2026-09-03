# -*- coding: utf-8 -*-
"""检查 add_messages reducer 对 dict 格式的处理，验证转换逻辑是否正确。"""
from langgraph.graph.message import add_messages
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

print("=== 测试 add_messages 对 dict 格式的处理 ===")

# 测试 1: 基础 dict（user/assistant）
result = add_messages(
    [{"role": "user", "content": "hello"}],
    [{"role": "assistant", "content": "hi"}],
)
print(f"Test 1 result: {result}")
print(f"Test 1 types: {[type(m).__name__ for m in result]}")
print()

# 测试 2: AIMessage dict 带 tool_calls
result = add_messages(
    [],
    [{"role": "assistant", "content": "", "tool_calls": [{"name": "test", "args": {"x": 1}, "id": "call_1"}]}],
)
print(f"Test 2 result: {result}")
print(f"Test 2 types: {[type(m).__name__ for m in result]}")
if result and hasattr(result[0], "tool_calls"):
    print(f"Test 2 tool_calls: {result[0].tool_calls}")
print()

# 测试 3: ToolMessage dict
result = add_messages(
    [],
    [{"role": "tool", "content": "result", "tool_call_id": "call_1"}],
)
print(f"Test 3 result: {result}")
print(f"Test 3 types: {[type(m).__name__ for m in result]}")
print()

# 测试 4: 已有 BaseMessage + dict 混合
existing = [HumanMessage(content="q1")]
new_msgs = [
    AIMessage(content="a1"),
    {"role": "user", "content": "q2"},
]
result = add_messages(existing, new_msgs)
print(f"Test 4 result: {result}")
print(f"Test 4 types: {[type(m).__name__ for m in result]}")
print()

# 测试 5: 验证 AIMessage.tool_calls 的标准格式
ai_msg = AIMessage(
    content="",
    tool_calls=[{"name": "test", "args": {"x": 1}, "id": "call_1", "type": "tool_call"}],
)
print(f"Test 5 ai_msg.tool_calls: {ai_msg.tool_calls}")
print(f"Test 5 ai_msg.additional_kwargs: {ai_msg.additional_kwargs}")
print()

# 测试 6: add_messages 去重（通过 id）
msg_with_id_1 = HumanMessage(content="hello", id="msg_1")
msg_with_id_2 = HumanMessage(content="hello updated", id="msg_1")
result = add_messages([msg_with_id_1], [msg_with_id_2])
print(f"Test 6 dedup result: {[m.content for m in result]}")
print()

print("=== add_messages 行为验证完成 ===")
