# -*- coding: utf-8 -*-
"""验证 _build_effective_message 的 action payload 注入逻辑。"""
import sys
sys.path.insert(0, ".")

from backend.api.agent_v2 import _build_effective_message

print("=== 测试 _build_effective_message ===")

# 测试 1: 无 action，直接返回 message
result = _build_effective_message("帮我建客户", None)
print(f"Test 1: {result!r}")
assert result == "帮我建客户"
print("PASS")

# 测试 2: action + message（如 select_client 后带文本）
result = _build_effective_message(
    "继续创建项目",
    {"type": "select_client", "label": "阿里云", "payload": {"client_id": 123}},
)
print(f"Test 2: {result!r}")
assert "继续创建项目" in result
assert "阿里云" in result
assert "client_id=123" in result
print("PASS")

# 测试 3: 仅 action 无 message（如 dismiss_onboarding）
result = _build_effective_message(
    "",
    {"type": "dismiss_onboarding", "label": "跳过引导", "payload": {}},
)
print(f"Test 3: {result!r}")
assert result == "跳过引导"
print("PASS")

# 测试 4: action 带 payload 无 message（如 select_client 后无文本）
result = _build_effective_message(
    "",
    {"type": "select_client", "label": "阿里云", "payload": {"client_id": 123, "company_name": "阿里云"}},
)
print(f"Test 4: {result!r}")
assert "阿里云" in result
assert "client_id=123" in result
assert "company_name=阿里云" in result
print("PASS")

# 测试 5: confirm action
result = _build_effective_message(
    "",
    {"type": "confirm", "label": "确认发布", "payload": {}},
)
print(f"Test 5: {result!r}")
assert result == "确认发布"
print("PASS")

# 测试 6: action 带 None payload 值被过滤
result = _build_effective_message(
    "",
    {"type": "select_platform", "label": "知乎", "payload": {"platform": "zhihu", "account_id": None}},
)
print(f"Test 6: {result!r}")
assert "platform=zhihu" in result
assert "account_id" not in result  # None 值被过滤
print("PASS")

# 测试 7: 空 action dict
result = _build_effective_message("你好", {})
print(f"Test 7: {result!r}")
assert result == "你好"
print("PASS")

print("\n=== 全部测试通过 ===")
