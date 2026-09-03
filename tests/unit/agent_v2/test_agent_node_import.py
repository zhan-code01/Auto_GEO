# -*- coding: utf-8 -*-
"""验证 agent_node 实际模块导入和函数工作。"""
from backend.services.agent_v2.nodes.agent_node import (
    _parse_task_context_from_content,
    _strip_task_context_tag,
    _infer_task_context,
    _REQUIRED_SLOTS,
    _TASK_TYPE_TOOLS,
)

print("import OK")
print(f"_REQUIRED_SLOTS keys: {list(_REQUIRED_SLOTS.keys())}")
print(f"_TASK_TYPE_TOOLS: {_TASK_TYPE_TOOLS}")

# 测试 1: 解析 task_context 标签
content1 = '<task_context>{"type": "create_client", "slots": {"company_name": "test"}}</task_context>reply'
tc1 = _parse_task_context_from_content(content1)
print(f"\nTest 1 - parse result: {tc1}")
assert tc1 is not None
assert tc1["type"] == "create_client"
assert tc1["slots"]["company_name"] == "test"
assert "industry" in tc1["missing_slots"]
assert "location" in tc1["missing_slots"]
assert "website" in tc1["missing_slots"]
print("Test 1 PASS")

# 测试 2: strip 标签
clean = _strip_task_context_tag('<task_context>{"type": "create_client", "slots": {}}</task_context>hello')
print(f"\nTest 2 - clean: {clean!r}")
assert clean == "hello"
print("Test 2 PASS")

# 测试 3: _infer_task_context 优先使用 parsed_tc
parsed_tc = {"type": "create_client", "slots": {"company_name": "from_tag"}, "missing_slots": [], "created_at": "2026-01-01T00:00:00Z"}
result = _infer_task_context([], None, parsed_tc)
print(f"\nTest 3 - infer with parsed_tc: {result}")
assert result == parsed_tc
print("Test 3 PASS")

# 测试 4: _infer_task_context 从工具调用推断（含 slots 合并）
current_tc = {"type": "create_client", "slots": {"company_name": "existing", "industry": "AI"}, "missing_slots": ["location", "website"], "created_at": "2026-01-01T00:00:00Z"}
tool_calls = [{"name": "create_client", "args": {"company_name": "new", "industry": "AI", "location": "BJ", "website": "www.test.com"}, "id": "1"}]
result = _infer_task_context(tool_calls, current_tc, None)
print(f"\nTest 4 - infer from tool call (merged): {result}")
assert result["slots"]["company_name"] == "new"  # 工具参数优先
assert result["slots"]["industry"] == "AI"
assert result["slots"]["location"] == "BJ"
assert result["slots"]["website"] == "www.test.com"
assert result["missing_slots"] == []  # 所有必填都已
print("Test 4 PASS")

# 测试 5: 查询型工具不改变 task_context
current_tc = {"type": "create_client", "slots": {"company_name": "x"}, "missing_slots": ["industry"], "created_at": "2026-01-01"}
tool_calls = [{"name": "list_clients", "args": {}, "id": "1"}]
result = _infer_task_context(tool_calls, current_tc, None)
print(f"\nTest 5 - query tool keeps tc: {result}")
assert result == current_tc
print("Test 5 PASS")

print("\n=== agent_node 模块验证全部通过 ===")
