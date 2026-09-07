# -*- coding: utf-8 -*-
"""LOAD_CONTEXT - graph 外预处理：加载会话上下文。

对应 PRD §7 记忆系统。只加载 Checkpointer 不负责的部分：
- 长期记忆：从 UserAgentFact 加载 user_facts（跨会话事实）
- 用户偏好：从 UserAgentPreference 加载 preferences
- 确保会话行存在（供前端会话列表展示）

不加载的部分（由 LangGraph Checkpointer 自动管理）：
- 工作记忆（messages）：Checkpointer 按 thread_id 自动加载历史消息
- 短期记忆（task_context）：Checkpointer 自动持久化和恢复

之前的问题：load_context 从 ConversationMessage 表加载历史消息注入 messages，
但 Checkpointer 也会自动加载 messages → 历史消息被重复加载。
修复后：messages 完全由 Checkpointer 管理，load_context 不再干预。
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.services.agent_v2.state import AgentState


async def load_context(state: AgentState) -> AgentState:
    """加载会话上下文：user_facts + preferences + 确保会话行存在。

    返回新的 state dict（注入 user_facts 和 preferences）。
    不加载历史消息和 task_context（由 Checkpointer 自动管理）。
    """
    user_id = state["user_id"]
    session_id = state["session_id"]
    db: Session = SessionLocal()
    try:
        from backend.services.agent_v2.memory import FactStore, SessionStore

        session_store = SessionStore(db)
        fact_store = FactStore(db)

        # 确保会话行存在（供前端会话列表展示）
        session = session_store.get_or_create_session(user_id, session_id)

        # 加载长期记忆：user_facts（跨会话事实，每次从数据库加载最新值）
        user_facts = fact_store.get_facts(user_id)

        # 加载用户偏好
        preferences = _load_preferences(db, user_id)

        logger.info(
            f"[LOAD_CONTEXT] user={user_id} session={session.id} "
            f"facts={len(user_facts)} preferences={len(preferences)} "
            f"(messages/task_context 由 Checkpointer 管理)"
        )

        return {
            **state,
            "session_id": session.id,
            "user_facts": user_facts,
            "preferences": preferences,
        }
    finally:
        db.close()


def _load_preferences(db: Session, user_id: int) -> dict[str, Any]:
    """加载用户偏好（从 UserAgentPreference 表）。"""
    from backend.database.models import UserAgentPreference

    record = db.query(UserAgentPreference).filter(UserAgentPreference.system_user_id == user_id).first()
    if not record:
        return {}
    return {
        "default_project_id": record.default_project_id,
        "default_platforms": record.default_platforms or [],
        "default_publish_strategy": record.default_publish_strategy,
        "require_confirmation_before_publish": record.require_confirmation_before_publish,
        "tone_preference": record.tone_preference,
    }
