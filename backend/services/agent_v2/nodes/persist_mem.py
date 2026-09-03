# -*- coding: utf-8 -*-
"""PERSIST_MEM - graph 外后处理：持久化记忆。

对应 PRD §7.3 记忆流转。在 graph 执行完成后保存：
- 工作记忆：本轮用户消息 + 助手回复 → ConversationMessage 表（供前端展示对话历史）
- 长期记忆：facts_patch → UserAgentFact.facts（跨会话事实）

不保存的部分（由 LangGraph Checkpointer 自动管理）：
- 短期记忆（task_context）：Checkpointer 已持久化到 checkpoint 表
- 工作记忆（messages）：Checkpointer 已持久化到 checkpoint 表

ConversationMessage 表与 checkpoint 表的关系：
- checkpoint 表：LangGraph 内部使用，支持状态恢复和中断恢复
- ConversationMessage 表：前端展示用，提供会话列表和消息历史
- 两者不重复：checkpoint 存完整 State（含 messages/tool_results/actions 等），
  ConversationMessage 只存用户可见的文本对话
"""
from __future__ import annotations

from loguru import logger

from backend.services.agent_v2.state import AgentState


async def persist_mem(state: AgentState) -> None:
    """持久化记忆（graph 外后处理）。

    1. 保存用户消息 + 助手回复到 ConversationMessage（供前端展示）
       - silent=true 时跳过用户消息保存（弹窗内操作不产生对话气泡）
    2. 回写 facts_patch 到 UserAgentFact（长期记忆）
    3. 更新会话状态（供前端会话列表展示）
    4. 清理已废弃的 pending_action 字段（V1 遗留，V2 用 task_context 替代）
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.memory import FactStore, SessionStore

    user_id = state["user_id"]
    session_id = state["session_id"]
    reply = state.get("reply", "") or ""
    facts_patch = state.get("facts_patch", []) or []
    actions = state.get("actions", []) or []
    status = state.get("status", "completed")
    async_task_refs = state.get("async_task_refs", []) or []
    silent = state.get("silent", False)  # 静默模式：不保存用户消息

    # 从 messages 中提取本轮用户消息（最后一条 role=user）
    # messages 可能存 BaseMessage（add_messages reducer 转换后）或 dict
    messages = state.get("messages") or []
    user_message = ""
    for msg in reversed(messages):
        # 兼容 BaseMessage 和 dict 两种格式
        if hasattr(msg, "type"):
            # BaseMessage: type="human" 对应 user
            if msg.type == "human":
                user_message = msg.content or ""
                break
        elif isinstance(msg, dict):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

    db = SessionLocal()
    try:
        session_store = SessionStore(db)
        fact_store = FactStore(db)

        # 1. 保存工作记忆：用户消息 + 助手回复（供前端 ConversationMessage 展示）
        # silent=true 时跳过用户消息保存（弹窗内操作不产生对话气泡）
        if user_message and not silent:
            session_store.add_message(
                session_id, "user", user_message,
                {"async_task_refs": async_task_refs} if async_task_refs else None,
            )
        if reply:
            session_store.add_message(
                session_id, "assistant", reply,
                {"actions": actions, "status": status, "async_task_refs": async_task_refs},
            )

        # 2. 回写长期记忆：facts_patch → UserAgentFact
        patched_count = 0
        for patch in facts_patch:
            if isinstance(patch, dict):
                fact_store.patch_facts(user_id, patch)
                patched_count += 1

        # 3. 清理已废弃的 pending_action 字段（V1 遗留）
        # V2 用 task_context（由 Checkpointer 管理）替代 pending_action
        session_slots = session_store.get_slots(session_id)
        cleaned = False
        for stale_key in ("pending_action", "pending_actions", "task_context"):
            if stale_key in session_slots:
                session_slots.pop(stale_key, None)
                cleaned = True
        if cleaned:
            session_store.set_slots(session_id, session_slots)

        # 4. 更新会话状态（供前端会话列表展示）
        session_store.update_session_status(session_id, status)

        logger.info(
            f"[PERSIST_MEM] session={session_id} status={status} "
            f"facts_patched={patched_count} "
            f"actions={len(actions)} async_tasks={len(async_task_refs)}"
        )
    finally:
        db.close()
