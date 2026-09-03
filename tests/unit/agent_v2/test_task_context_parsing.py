# -*- coding: utf-8 -*-
"""验证 agent_node 中 task_context 标签解析逻辑。

快速验证多轮信息提取的核心功能：
- _parse_task_context_from_content: 从 LLM 回复中解析 <task_context> 标签
- _strip_task_context_tag: 从回复中移除标签，得到给用户看的纯净文本
"""
import json
import re
from datetime import datetime, timezone

# 复制 agent_node.py 中的核心逻辑进行独立验证
_TASK_CONTEXT_PATTERN = re.compile(
    r"<task_context>\s*(\{.*?\})\s*</task_context>",
    re.DOTALL,
)
_REQUIRED_SLOTS = {
    "create_client": ["company_name", "industry", "location", "website"],
    "create_project": ["client_id", "project_name", "keywords"],
    "generate_questions": ["project_id"],
    "generate_articles": ["project_id"],
    "publish_article": ["article_id", "platform"],
    "bind_platform": ["platform"],
    "create_baseline": ["client_id", "ai_platforms"],
    "run_recheck": ["client_id", "ai_platforms"],
    "upload_documents": ["client_id"],
}


def _parse_task_context_from_content(content):
    match = _TASK_CONTEXT_PATTERN.search(content or "")
    if not match:
        return None
    try:
        tc = json.loads(match.group(1).strip())
        if not isinstance(tc, dict):
            return None
        tc_type = tc.get("type")
        if not tc_type or tc_type not in _REQUIRED_SLOTS:
            return None
        tc.setdefault("slots", {})
        tc.setdefault("missing_slots", [])
        required = _REQUIRED_SLOTS[tc_type]
        slots = tc.get("slots", {}) or {}
        tc["missing_slots"] = [
            k for k in required if k not in slots or slots[k] in (None, "")
        ]
        if not tc.get("created_at"):
            tc["created_at"] = "2026-08-06T00:00:00Z"
        return tc
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None


def _strip_task_context_tag(content):
    return _TASK_CONTEXT_PATTERN.sub("", content or "").strip()


def test_full_task_context_tag():
    """测试 1: 完整 task_context 标签"""
    content = (
        '<task_context>{"type": "create_client", "slots": {"company_name": "阿里云"}, '
        '"missing_slots": ["industry", "location", "website"]}</task_context>'
        "请提供行业、地点和网站。"
    )
    tc = _parse_task_context_from_content(content)
    clean = _strip_task_context_tag(content)
    assert tc is not None
    assert tc["type"] == "create_client"
    assert tc["slots"]["company_name"] == "阿里云"
    assert "industry" in tc["missing_slots"]
    assert "请提供行业、地点和网站。" in clean
    assert "<task_context>" not in clean
    print("PASS test_full_task_context_tag")


def test_no_tag_chitchat():
    """测试 2: 无标签（闲聊场景）"""
    content = "你好，有什么可以帮您的吗？"
    tc = _parse_task_context_from_content(content)
    clean = _strip_task_context_tag(content)
    assert tc is None
    assert clean == "你好，有什么可以帮您的吗？"
    print("PASS test_no_tag_chitchat")


def test_auto_compute_missing_slots():
    """测试 3: 自动计算 missing_slots（即使 LLM 没提供）"""
    content = (
        '<task_context>{"type": "create_client", '
        '"slots": {"company_name": "阿里云", "industry": "云计算"}}</task_context>'
        "还需要地点和网站"
    )
    tc = _parse_task_context_from_content(content)
    assert tc["slots"]["company_name"] == "阿里云"
    assert tc["slots"]["industry"] == "云计算"
    assert tc["missing_slots"] == ["location", "website"]
    print("PASS test_auto_compute_missing_slots")


def test_invalid_type():
    """测试 4: 非法 type 返回 None"""
    content = '<task_context>{"type": "invalid_type", "slots": {}}</task_context>test'
    tc = _parse_task_context_from_content(content)
    assert tc is None
    print("PASS test_invalid_type")


def test_multiline_tag():
    """测试 5: 标签跨行"""
    content = (
        '<task_context>\n'
        '{"type": "create_client", "slots": {"company_name": "测试公司"}}\n'
        '</task_context>\n'
        "请提供其他信息"
    )
    tc = _parse_task_context_from_content(content)
    clean = _strip_task_context_tag(content)
    assert tc["slots"]["company_name"] == "测试公司"
    assert tc["missing_slots"] == ["industry", "location", "website"]
    assert "请提供其他信息" in clean
    print("PASS test_multiline_tag")


def test_all_slots_filled():
    """测试 6: 所有槽位已填（missing_slots 应为空）"""
    content = (
        '<task_context>{"type": "create_client", "slots": '
        '{"company_name": "A", "industry": "B", "location": "C", "website": "D"}}'
        '</task_context>正在创建...'
    )
    tc = _parse_task_context_from_content(content)
    assert tc["missing_slots"] == []
    print("PASS test_all_slots_filled")


def test_malformed_json():
    """测试 7: JSON 格式错误"""
    content = '<task_context>{not valid json}</task_context>回复'
    tc = _parse_task_context_from_content(content)
    assert tc is None
    clean = _strip_task_context_tag(content)
    # 即使解析失败，strip 仍然会移除标签
    assert "<task_context>" not in clean
    assert clean == "回复"
    print("PASS test_malformed_json")


def test_empty_content():
    """测试 8: 空内容"""
    tc = _parse_task_context_from_content("")
    assert tc is None
    clean = _strip_task_context_tag("")
    assert clean == ""
    print("PASS test_empty_content")


def test_slots_with_empty_values():
    """测试 9: slots 中有空值应视为缺失"""
    content = (
        '<task_context>{"type": "create_client", '
        '"slots": {"company_name": "阿里云", "industry": "", "location": null}}'
        '</task_context>请补充信息'
    )
    tc = _parse_task_context_from_content(content)
    # industry="" 和 location=None 都应视为缺失
    assert "industry" in tc["missing_slots"]
    assert "location" in tc["missing_slots"]
    assert "website" in tc["missing_slots"]
    print("PASS test_slots_with_empty_values")


if __name__ == "__main__":
    test_full_task_context_tag()
    test_no_tag_chitchat()
    test_auto_compute_missing_slots()
    test_invalid_type()
    test_multiline_tag()
    test_all_slots_filled()
    test_malformed_json()
    test_empty_content()
    test_slots_with_empty_values()
    print()
    print("=== 全部测试通过 ===")
