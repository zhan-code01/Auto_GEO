# -*- coding: utf-8 -*-
"""异步任务通知 - WebSocket 推送。

对应 PRD 第十章。异步任务（文章生成、发布）完成时通过 ws_manager.notify_user
推送给用户的所有在线会话。仅在线推送，离线不持久化。

事件类型（PRD 10.2 节）：
- question_batch_completed
- article_batch_completed
- article_job_failed
- publish_task_progress
- publish_task_completed
- auth_complete
- knowledge_parse_done
- pending_action_trigger
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.services.websocket_manager import ws_manager


async def notify_user(user_id: int, event_type: str, data: dict) -> bool:
    """推送给用户的所有在线会话。

    Args:
        user_id: 用户 ID
        event_type: 事件类型（见 PRD 10.2 节）
        data: 事件数据

    Returns:
        bool: True 表示至少有一个连接收到；False 表示用户离线
    """
    message = {"type": event_type, "data": data}
    sent = await ws_manager.notify_user(user_id, message)
    if sent:
        logger.info(f"[notify_user] user={user_id} event={event_type} 已推送")
    else:
        logger.info(f"[notify_user] user={user_id} event={event_type} 离线未推送")
    return sent


# ============================================================
#  具体事件通知函数
# ============================================================


async def notify_question_batch_completed(
    user_id: int,
    batch_id: int,
    question_count: int,
    questions: list[dict] | None = None,
) -> bool:
    """问题批次生成完成。"""
    return await notify_user(
        user_id,
        "question_batch_completed",
        {
            "batch_id": batch_id,
            "question_count": question_count,
            "questions": questions or [],
        },
    )


async def notify_article_batch_completed(
    user_id: int,
    batch_id: int,
    success_count: int,
    failed_count: int,
    article_ids: list[int] | None = None,
) -> bool:
    """文章批次生成完成。

    注意：旧版的 pending_actions 自动续跑机制已废弃——ReAct Agent 通过
    LLM 自主决策实现工具链式调用（list_articles → publish_article），
    不再需要 session_slots.pending_actions。
    """
    return await notify_user(
        user_id,
        "article_batch_completed",
        {
            "batch_id": batch_id,
            "success_count": success_count,
            "failed_count": failed_count,
            "article_ids": article_ids or [],
        },
    )


async def notify_article_job_failed(
    user_id: int,
    job_id: int,
    article_id: int,
    error_msg: str,
) -> bool:
    """单篇文章生成失败。"""
    return await notify_user(
        user_id,
        "article_job_failed",
        {
            "job_id": job_id,
            "article_id": article_id,
            "error_msg": error_msg,
        },
    )


async def notify_publish_task_progress(
    user_id: int,
    task_id: int,
    completed: int,
    failed: int,
    total: int,
) -> bool:
    """发布任务进度更新。"""
    return await notify_user(
        user_id,
        "publish_task_progress",
        {
            "task_id": task_id,
            "completed": completed,
            "failed": failed,
            "total": total,
        },
    )


async def notify_publish_task_completed(
    user_id: int,
    task_id: int,
    success_count: int,
    failed_count: int,
) -> bool:
    """发布任务完成。"""
    return await notify_user(
        user_id,
        "publish_task_completed",
        {
            "task_id": task_id,
            "success_count": success_count,
            "failed_count": failed_count,
        },
    )


async def notify_auth_complete(
    user_id: int,
    task_id: int,
    platform: str,
    account_id: int,
    success: bool,
) -> bool:
    """平台登录授权完成。"""
    return await notify_user(
        user_id,
        "auth_complete",
        {
            "task_id": task_id,
            "platform": platform,
            "account_id": account_id,
            "success": success,
        },
    )


async def notify_knowledge_parse_done(
    user_id: int,
    dataset_id: str,
    doc_id: str,
    is_ready: bool,
) -> bool:
    """知识库文档解析完成。"""
    return await notify_user(
        user_id,
        "knowledge_parse_done",
        {
            "dataset_id": dataset_id,
            "doc_id": doc_id,
            "is_ready": is_ready,
        },
    )


# ============================================================
#  pending_actions 触发（已废弃，保留空函数避免外部调用方报错）
# ============================================================


async def trigger_pending_actions(user_id: int, event_type: str, payload: dict) -> None:
    """已废弃：旧版 pending_actions 自动续跑机制。

    ReAct Agent 通过 LLM 自主决策实现工具链式调用，不再需要此机制。
    保留空函数仅为兼容可能存在的外部调用方。
    """
    return None
