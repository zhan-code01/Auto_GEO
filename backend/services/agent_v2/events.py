# -*- coding: utf-8 -*-
"""SSE 事件工具。

对应 PRD 第十三章 13.3 节 SSE 事件类型（ReAct 模式版本）。

事件类型：
- thinking: Agent 思考过程（展示给用户）
- tool_calls: Agent 决策调用的工具列表
- tool_start: 工具开始执行
- tool_end: 工具执行完成
- actions: 前端按钮（列表弹窗/表单弹窗/选择弹窗等）
- text_delta: LLM 回复生成中（流式分片）
- async_task_started: 异步任务已启动
- clarification: 需要用户补充信息
- error: 执行异常
- progress: 心跳/阶段进度
- done: 本轮响应结束
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator


# SSE 事件类型
EVENT_THINKING = "thinking"
EVENT_TOOL_CALLS = "tool_calls"
EVENT_TOOL_START = "tool_start"
EVENT_TOOL_END = "tool_end"
EVENT_ACTIONS = "actions"
EVENT_TEXT_DELTA = "text_delta"
EVENT_ASYNC_TASK_STARTED = "async_task_started"
EVENT_CLARIFICATION = "clarification"
EVENT_ERROR = "error"
EVENT_PROGRESS = "progress"  # 心跳/阶段进度
EVENT_DONE = "done"


def format_sse(event_type: str, data: Any) -> str:
    """格式化 SSE 事件。

    格式：event: <type>\ndata: <json>\n\n
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def thinking_event(thinking: str) -> str:
    """Agent 思考过程事件（展示给用户，类似 ChatGPT 的 thinking 状态）。

    对应 PRD §11.7。
    """
    return format_sse(EVENT_THINKING, {"thinking": thinking or ""})


def tool_calls_event(tool_calls: list[dict]) -> str:
    """Agent 决策调用的工具列表事件。

    在 Agent 决策调用工具但还未执行时发送，让前端展示"正在调用 list_clients..."等状态。
    """
    return format_sse(EVENT_TOOL_CALLS, {
        "tool_calls": [
            {"name": tc.get("name", ""), "args": tc.get("args", {}) or {}}
            for tc in tool_calls
        ],
    })


def tool_start_event(tool_name: str, params: dict) -> str:
    """工具开始执行事件。"""
    return format_sse(EVENT_TOOL_START, {"tool_name": tool_name, "params": params})


def tool_end_event(tool_name: str, result: dict, actions: list | None = None) -> str:
    """工具执行完成事件。"""
    return format_sse(EVENT_TOOL_END, {
        "tool_name": tool_name,
        "result": result,
        "actions": actions or [],
    })


def actions_event(actions: list[dict]) -> str:
    """前端按钮事件（列表弹窗/表单弹窗/选择弹窗/指标卡片等）。

    对应 PRD §11。前端根据 actions 中的 type 渲染对应组件。
    """
    return format_sse(EVENT_ACTIONS, {"actions": actions or []})


def text_delta_event(delta: str) -> str:
    """LLM 回复文本增量事件（流式分片，打字机效果）。"""
    return format_sse(EVENT_TEXT_DELTA, {"delta": delta})


def async_task_started_event(task_type: str, task_id: Any, query_tool: str) -> str:
    """异步任务已启动事件。

    前端收到后可用 query_tool 轮询结果。
    """
    return format_sse(EVENT_ASYNC_TASK_STARTED, {
        "task_type": task_type,
        "task_id": task_id,
        "query_tool": query_tool,
    })


def clarification_event(reply: str, actions: list | None = None) -> str:
    """需要用户补充信息事件。

    ReAct 模式下：当工具返回 need_clarification 或 Agent 追问用户时发送。
    """
    return format_sse(EVENT_CLARIFICATION, {
        "reply": reply,
        "actions": actions or [],
    })


def error_event(code: str, message: str) -> str:
    """错误事件。"""
    return format_sse(EVENT_ERROR, {"code": code, "message": message})


def progress_event(stage: str, elapsed_sec: float, **extra) -> str:
    """心跳/阶段进度事件（防止长任务期间连接超时）。"""
    payload = {"stage": stage, "elapsed_sec": round(elapsed_sec, 1)}
    payload.update(extra)
    return format_sse(EVENT_PROGRESS, payload)


def done_event(
    status: str,
    session_id: str,
    *,
    actions: list | None = None,
    async_task_refs: list | None = None,
    tool_results: list | None = None,
) -> str:
    """本轮响应结束事件。

    Args:
        status: completed / need_clarification / running / failed
        session_id: 会话 ID
        actions: 前端按钮列表
        async_task_refs: 异步任务引用（前端可轮询）
        tool_results: 工具执行结果列表
    """
    return format_sse(EVENT_DONE, {
        "status": status,
        "session_id": session_id,
        "actions": actions or [],
        "async_task_refs": async_task_refs or [],
        "tool_results": tool_results or [],
    })


async def stream_text_deltas(text: str, chunk_size: int = 8,
                             delay_ms: int = 20) -> AsyncIterator[str]:
    """把完整文本按字分片，模拟打字机流式输出。

    对于不支持原生流式的 LLM 调用，用此函数把 reply 切片发送 text_delta 事件。
    使用 asyncio.sleep 避免阻塞事件循环（time.sleep 会阻塞整个 loop）。
    """
    if not text:
        return
    i = 0
    while i < len(text):
        chunk = text[i:i + chunk_size]
        yield text_delta_event(chunk)
        i += chunk_size
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
