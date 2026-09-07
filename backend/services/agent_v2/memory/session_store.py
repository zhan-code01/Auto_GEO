# -*- coding: utf-8 -*-
"""会话短期记忆存储 - 基于 ConversationSession / ConversationMessage 表。"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import ConversationMessage, ConversationSession


class SessionStore:
    """会话短期记忆存储。

    管理 ConversationSession 和 ConversationMessage 表：
    - 会话 CRUD（供前端会话列表展示）
    - 消息历史（供前端对话历史展示）
    - slots（存储会话级元数据，V2 中主要用于清理 V1 遗留字段）

    注意：messages 和 task_context 的持久化由 LangGraph Checkpointer 管理，
    本类只负责前端可见的 ConversationMessage 表。
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    #  会话管理
    # ------------------------------------------------------------------
    def get_or_create_session(
        self, user_id: int, session_id: str | None, title: str | None = None
    ) -> ConversationSession:
        """获取或创建会话。session_id 为 None 时新建。"""
        if session_id:
            session = (
                self.db.query(ConversationSession)
                .filter(
                    ConversationSession.id == session_id,
                    ConversationSession.system_user_id == user_id,
                )
                .first()
            )
            if session:
                logger.debug(f"[SessionStore] 复用会话: session_id={session_id} user_id={user_id}")
                return session
        # 新建
        import uuid

        new_id = session_id or f"v2_{uuid.uuid4().hex[:16]}"
        session = ConversationSession(
            id=new_id,
            source="web",
            channel="web",
            system_user_id=user_id,
            status="active",
            slots={},
            title=title or "智能体对话",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        logger.debug(f"[SessionStore] 新建会话: session_id={new_id} user_id={user_id}")
        return session

    def update_session_status(self, session_id: str, status: str) -> None:
        self.db.query(ConversationSession).filter(ConversationSession.id == session_id).update({"status": status})
        self.db.commit()
        logger.debug(f"[SessionStore] 会话状态更新: session_id={session_id} status={status}")

    # ------------------------------------------------------------------
    #  槽位（slots）
    # ------------------------------------------------------------------
    def get_slots(self, session_id: str) -> dict[str, Any]:
        session = self.db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if not session or not session.slots:
            return {}
        return session.slots if isinstance(session.slots, dict) else {}

    def set_slots(self, session_id: str, slots: dict[str, Any]) -> None:
        """整体覆盖 slots。"""
        self.db.query(ConversationSession).filter(ConversationSession.id == session_id).update({"slots": slots})
        self.db.commit()

    def patch_slots(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """增量合并 slots，返回合并后的完整 slots。"""
        current = self.get_slots(session_id)
        current.update(patch)
        self.set_slots(session_id, current)
        return current

    # ------------------------------------------------------------------
    #  消息历史
    # ------------------------------------------------------------------
    def get_history(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取最近 N 条消息（按时间正序）。"""
        rows = (
            self.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == session_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [
            {
                "role": row.role,
                "content": row.content,
                "metadata": row.message_metadata or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def add_message(
        self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> ConversationMessage:
        """追加一条消息。"""
        msg = ConversationMessage(
            conversation_id=session_id,
            role=role,
            content=content,
            message_metadata=metadata or {},
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        logger.debug(f"[SessionStore] 追加消息: session_id={session_id} role={role} content_len={len(content or '')}")
        return msg
