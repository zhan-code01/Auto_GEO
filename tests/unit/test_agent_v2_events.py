# -*- coding: utf-8 -*-
"""Agent V2 SSE 事件格式化测试。

覆盖 PRD 第十三章 13.3 节事件类型。
"""
from __future__ import annotations

import json

from backend.services.agent_v2 import events


class TestSSEEventFormat:
    """SSE 事件格式化测试。"""

    def test_format_sse_basic(self):
        """基础 SSE 格式。"""
        result = events.format_sse("test", {"key": "value"})
        assert result.startswith("event: test\n")
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_intent_event(self):
        """intent 事件。"""
        result = events.intent_event("generate_articles", {"project_id": 123}, 0.95)
        assert "event: intent" in result
        data = _extract_data(result)
        assert data["intent"] == "generate_articles"
        assert data["slots"]["project_id"] == 123
        assert data["confidence"] == 0.95

    def test_slot_check_event(self):
        """slot_check 事件。"""
        result = events.slot_check_event(True, {"project_id": 123}, [])
        assert "event: slot_check" in result
        data = _extract_data(result)
        assert data["slots_ok"] is True
        assert data["missing_slots"] == []

    def test_tool_start_event(self):
        """tool_start 事件。"""
        result = events.tool_start_event("generate_articles_batch", {"project_id": 123, "count": 5})
        assert "event: tool_start" in result
        data = _extract_data(result)
        assert data["tool_name"] == "generate_articles_batch"

    def test_tool_end_event(self):
        """tool_end 事件。"""
        actions = [{"type": "view_batch_progress", "label": "查看进度"}]
        result = events.tool_end_event("generate_articles_batch", {"batch_id": 456}, actions)
        assert "event: tool_end" in result
        data = _extract_data(result)
        assert data["result"]["batch_id"] == 456
        assert len(data["actions"]) == 1

    def test_text_delta_event(self):
        """text_delta 事件。"""
        result = events.text_delta_event("你好")
        assert "event: text_delta" in result
        data = _extract_data(result)
        assert data["delta"] == "你好"

    def test_async_task_started_event(self):
        """async_task_started 事件。"""
        result = events.async_task_started_event("article_batch", 456, "get_article_batch_status")
        assert "event: async_task_started" in result
        data = _extract_data(result)
        assert data["task_type"] == "article_batch"
        assert data["task_id"] == 456

    def test_clarification_event(self):
        """clarification 事件。"""
        result = events.clarification_event("请提供项目名称", ["project_id"], [])
        assert "event: clarification" in result
        data = _extract_data(result)
        assert data["reply"] == "请提供项目名称"
        assert data["missing_slots"] == ["project_id"]

    def test_error_event(self):
        """error 事件。"""
        result = events.error_event("internal_error", "执行失败")
        assert "event: error" in result
        data = _extract_data(result)
        assert data["code"] == "internal_error"

    def test_progress_event(self):
        """progress 心跳事件。"""
        result = events.progress_event("processing", 15.5)
        assert "event: progress" in result
        data = _extract_data(result)
        assert data["stage"] == "processing"
        assert data["elapsed_sec"] == 15.5

    def test_done_event(self):
        """done 事件。"""
        result = events.done_event("completed", "sess_123", {"project_id": 123})
        assert "event: done" in result
        data = _extract_data(result)
        assert data["status"] == "completed"
        assert data["session_id"] == "sess_123"
        assert data["slots_patch"]["project_id"] == 123


# ============================================================
#  伪流式分片测试
# ============================================================

class TestStreamTextDeltas:
    """文本分片测试。"""

    def test_empty_text(self):
        """空文本不产生分片。"""
        import asyncio

        async def run():
            chunks = []
            async for chunk in events.stream_text_deltas("", delay_ms=0):
                chunks.append(chunk)
            return chunks

        result = asyncio.run(run())
        assert result == []

    def test_short_text(self):
        """短文本分片。"""
        import asyncio

        async def run():
            chunks = []
            async for chunk in events.stream_text_deltas("你好世界", chunk_size=2, delay_ms=0):
                chunks.append(chunk)
            return chunks

        result = asyncio.run(run())
        assert len(result) == 2  # "你好" + "世界"
        assert "你好" in result[0]
        assert "世界" in result[1]

    def test_long_text(self):
        """长文本分片。"""
        import asyncio

        text = "这是一段较长的文本用于测试分片功能是否正常工作" * 3
        async def run():
            chunks = []
            async for chunk in events.stream_text_deltas(text, chunk_size=10, delay_ms=0):
                chunks.append(chunk)
            return chunks

        result = asyncio.run(run())
        # 拼接后应等于原文
        assert "".join(_extract_delta(c) for c in result) == text

    def test_chunk_size_respected(self):
        """分片大小被尊重。"""
        import asyncio

        async def run():
            chunks = []
            async for chunk in events.stream_text_deltas("abcdefghij", chunk_size=3, delay_ms=0):
                chunks.append(chunk)
            return chunks

        result = asyncio.run(run())
        assert len(result) == 4  # 3+3+3+1


# ============================================================
#  辅助函数
# ============================================================

def _extract_data(sse_str: str) -> dict:
    """从 SSE 字符串中提取 data 字段并解析为 dict。"""
    for line in sse_str.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise ValueError(f"未找到 data 行: {sse_str}")


def _extract_delta(sse_str: str) -> str:
    """从 SSE 字符串中提取 delta。"""
    return _extract_data(sse_str).get("delta", "")
