# -*- coding: utf-8 -*-
"""TOOLS 节点 - 工具执行节点。

对应 PRD §4.4 ReAct 循环的 Tools 部分。
执行 agent_node 决策的 tool_calls，把结果作为 ToolMessage 回写 messages，
LangGraph 通过 add_edge("tools", "agent") 自动路由回 agent 节点继续推理，
实现 Agent↔Tools 循环。

关键设计：
- ToolMessage 携带 `tool_call_id`，与上一轮 AIMessage.tool_calls 中的 id 对应
- 让 LLM 在下一轮推理时能正确关联工具调用与结果（OpenAI 协议要求）
- 工具结果同时回写到 tool_results / actions / async_task_refs / facts_patch
"""
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from backend.services.agent_v2.state import AgentState


# 任务型工具集合：执行这些工具意味着开始/结束一个任务
# 与 agent_node._TASK_TYPE_TOOLS 保持一致
# 查询型工具（list_*/get_*）不改变 task_context
_TASK_TYPE_TOOLS: set[str] = {
    "create_client", "create_project",
    "generate_questions", "generate_articles",
    "publish_article", "bind_platform",
    "create_baseline", "run_recheck",
    "upload_documents",
}


async def tools_node(state: AgentState) -> dict:
    """工具执行节点。

    执行 state["tool_calls"] 中的所有工具调用，把结果回写：
    - tool_results: 工具执行结果列表（累积到 state）
    - messages: 追加 ToolMessage（role=tool + tool_call_id），让 LLM 在下一轮推理时能看到
    - reply/actions/async_task_refs: 从工具结果提取，供最终输出
    - facts_patch: 从工具结果提取，待 persist_mem 回写长期记忆
    - task_context: 任务型工具完成时清空（completed/failed），需要补充信息时保留

    执行完后 LangGraph 自动路由回 agent 节点（由 add_edge("tools", "agent") 定义），
    Agent 看到 ToolMessage 后决定继续调用工具还是输出最终 reply。
    """
    from backend.services.agent_v2.tools import execute_tool

    tool_calls = state.get("tool_calls", []) or []
    user_id = state["user_id"]
    current_tc = state.get("task_context")

    if not tool_calls:
        logger.warning("[TOOLS] 无 tool_calls，跳过")
        return {"tool_calls": []}

    all_results: list[dict[str, Any]] = []
    all_reply_parts: list[str] = []
    all_actions: list[dict] = []
    all_async_task_refs: list[dict] = []
    all_facts_patch: list[dict] = []
    tool_messages: list[dict] = []
    final_status = "completed"
    # 跟踪是否有任务型工具执行（用于决定是否清空 task_context）
    has_task_tool = False

    for call in tool_calls:
        tool_name = call.get("name", "")
        tool_args = call.get("args", {}) or {}
        tool_call_id = call.get("id", "")

        # 检查是否为任务型工具
        if tool_name in _TASK_TYPE_TOOLS:
            has_task_tool = True

        logger.info(f"[TOOLS] 执行工具: {tool_name} args={tool_args} call_id={tool_call_id}")

        try:
            result = await execute_tool(tool_name, tool_args, user_id)
        except Exception as e:
            logger.error(f"[TOOLS] 工具 {tool_name} 执行异常: {e}", exc_info=True)
            result = {
                "reply": f"工具 {tool_name} 执行失败",
                "status": "failed",
                "error_type": "execution_error",
                "suggestion": "请稍后重试",
                "data": {},
                "actions": [],
                "facts_patch": [],
                "async_task_refs": [],
            }

        all_results.append({"name": tool_name, "result": result, "id": tool_call_id})

        # 收集工具返回的 reply
        reply = result.get("reply", "")
        if reply:
            all_reply_parts.append(reply)

        # 收集 actions
        actions = result.get("actions", []) or []
        all_actions.extend(actions)

        # 收集 async_task_refs
        async_refs = result.get("async_task_refs", []) or []
        all_async_task_refs.extend(async_refs)

        # 收集 facts_patch
        facts_patch = result.get("facts_patch", []) or []
        all_facts_patch.extend(facts_patch)

        # 状态聚合：任一工具 need_clarification/running/failed 则整体状态为该状态
        status = result.get("status", "completed")
        if status == "need_clarification":
            final_status = "need_clarification"
        elif status == "running" and final_status != "need_clarification":
            final_status = "running"
        elif status == "failed" and final_status == "completed":
            final_status = "failed"

        # 把工具结果作为 ToolMessage 回写 messages
        # 让 LLM 在下一轮推理时能看到工具执行结果（ReAct 模式核心）
        # 关键：tool_call_id 必须与上一轮 AIMessage.tool_calls 中的 id 对应
        tool_msg_content = json.dumps({
            "tool": tool_name,
            "status": status,
            "data": result.get("data", {}),
            "reply": reply,
            "error_type": result.get("error_type"),
            "suggestion": result.get("suggestion"),
        }, ensure_ascii=False)
        tool_messages.append({
            "role": "tool",
            "content": tool_msg_content,
            "tool_call_id": tool_call_id,
        })

    logger.info(
        f"[TOOLS] 完成 {len(tool_calls)} 个工具调用, status={final_status}, "
        f"actions={len(all_actions)}, async_tasks={len(all_async_task_refs)}"
    )

    # task_context 清空策略：
    # - 任务型工具执行且状态为 completed/failed → 清空（任务已结束，无论成功失败）
    # - 状态为 need_clarification → 保留（用户需要补充信息，任务进行中）
    # - 状态为 running → 保留（异步任务运行中）
    # - 查询型工具（list_*/get_*）→ 不影响 task_context（不在 _TASK_TYPE_TOOLS 中）
    result_dict: dict[str, Any] = {
        # 清空 tool_calls，让 _should_continue 路由到 END（除非 Agent 再次决策调用工具）
        "tool_calls": [],
        # 累积 tool_results（add_list reducer 会自动合并）
        "tool_results": all_results,
        # 追加 ToolMessage 到 messages（add_messages reducer 会自动合并）
        "messages": tool_messages,
        "reply": "\n".join(all_reply_parts) if all_reply_parts else "",
        "actions": all_actions,
        "async_task_refs": all_async_task_refs,
        "facts_patch": all_facts_patch,
        "status": final_status,
    }

    if has_task_tool and final_status in ("completed", "failed"):
        result_dict["task_context"] = None
        logger.info(f"[TOOLS] 任务型工具 {final_status}，清空 task_context")

    return result_dict
