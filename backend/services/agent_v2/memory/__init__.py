# -*- coding: utf-8 -*-
"""Agent V2 记忆层。

三层记忆（对应 PRD §7）：
- SessionStore：会话短期记忆（ConversationSession + ConversationMessage 表）
  供前端展示对话历史和会话列表。
  注意：messages 和 task_context 的持久化由 LangGraph Checkpointer 管理，
  SessionStore 只负责前端可见的 ConversationMessage 表。
- FactStore：用户长期事实（UserAgentFact 表，跨会话）

merger.py（merge_slots/invalidate_slots 等）是 V1 遗留的槽位管理逻辑，
V2 ReAct 模式下不再使用（LLM 通过 Tool Calling 直接生成工具参数）。
如需使用可直接 from backend.services.agent_v2.memory.merger import ...。
"""

from backend.services.agent_v2.memory.fact_store import DEFAULT_FACTS, FactStore
from backend.services.agent_v2.memory.session_store import SessionStore

__all__ = [
    "SessionStore",
    "FactStore",
    "DEFAULT_FACTS",
]
