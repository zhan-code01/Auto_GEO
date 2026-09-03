# -*- coding: utf-8 -*-
"""验证 state.messages 的实际类型，以及 _to_langchain_messages 的处理能力。"""
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# 模拟 add_messages 后 state.messages 中的实际内容
# add_messages 会把 dict 转成 BaseMessage 对象
simulated_state_messages = [
    HumanMessage(content="帮我创建客户", id="msg_1"),
    AIMessage(
        content="请提供公司信息",
        tool_calls=[{"name": "list_clients", "args": {}, "id": "call_1", "type": "tool_call"}],
        id="msg_2",
    ),
    ToolMessage(content="[]", tool_call_id="call_1", id="msg_3"),
    HumanMessage(content="公司叫阿里云", id="msg_4"),
]

print("=== 模拟 state.messages 的实际类型 ===")
for i, msg in enumerate(simulated_state_messages):
    print(f"  [{i}] type={type(msg).__name__} content={msg.content!r}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        print(f"      tool_calls={msg.tool_calls}")

# 测试当前 _to_langchain_messages 的行为
# 它期望 dict，但实际收到 BaseMessage
print()
print("=== 测试 _to_langchain_messages 对 BaseMessage 的处理 ===")

try:
    # 复制 agent_node 中的 _to_langchain_messages 逻辑
    def _to_langchain_messages(messages):
        result = []
        for msg in messages:
            role = msg.get("role", "user")  # BaseMessage 没有 .get() 方法
            content = msg.get("content", "")
            print(f"  msg type={type(msg).__name__}, role={role}, content={content!r}")
        return result

    result = _to_langchain_messages(simulated_state_messages)
    print("SUCCESS")
except AttributeError as e:
    print(f"AttributeError: {e}")
    print(">>> BaseMessage 不支持 dict 风格访问，_to_langchain_messages 会失败！")
except Exception as e:
    print(f"其他错误: {type(e).__name__}: {e}")

# 测试正确的处理方式：检查是 dict 还是 BaseMessage
print()
print("=== 测试兼容 dict 和 BaseMessage 的处理方式 ===")


def _to_langchain_messages_v2(messages):
    """兼容 dict 和 BaseMessage 的消息转换。"""
    result = []
    for msg in messages:
        if isinstance(msg, BaseMessage):
            # 已经是 BaseMessage，直接使用
            result.append(msg)
            print(f"  [BaseMessage] type={type(msg).__name__} 直接使用")
        elif isinstance(msg, dict):
            # dict 格式，需要转换
            role = msg.get("role", "user")
            content = msg.get("content", "")
            print(f"  [dict] role={role} content={content!r} 需要转换")
        else:
            print(f"  [unknown] type={type(msg).__name__} 跳过")
    return result


result = _to_langchain_messages_v2(simulated_state_messages)
print(f"结果: {len(result)} 条消息保持为 BaseMessage")

print()
print("=== 结论 ===")
print("1. add_messages reducer 把 dict 转成 BaseMessage 对象")
print("2. state.messages 中存的是 BaseMessage，不是 dict")
print("3. _to_langchain_messages 需要兼容 BaseMessage（直接使用）和 dict（转换）")
