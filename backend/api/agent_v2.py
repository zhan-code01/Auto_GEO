# -*- coding: utf-8 -*-
"""Agent V2 API - SSE 流式端点。

对应 PRD 第十三章。提供：
- POST /api/agent-v2/message（SSE 流式）
- GET /api/agent-v2/sessions
- GET /api/agent-v2/sessions/{id}
- DELETE /api/agent-v2/sessions/{id}
- GET /api/agent-v2/sessions/{id}/messages
- GET /api/agent-v2/preferences
- PUT /api/agent-v2/preferences
- GET /api/agent-v2/facts
- POST /api/agent-v2/ws/register（注册 WebSocket user_id 映射）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.user import get_current_active_user, get_current_user_from_token
from backend.database import get_db
from backend.database.models import (
    ConversationMessage,
    ConversationSession,
    User,
    UserAgentFact,
    UserAgentPreference,
)
from backend.schemas import ApiResponse
from backend.services.agent_v2 import events
from backend.services.agent_v2.graph import run_agent_stream
from backend.services.agent_v2.state import make_initial_state
from backend.services.websocket_manager import ws_manager

router = APIRouter(prefix="/api/agent-v2", tags=["智能体V2"])


# ============================================================
#  前端 action -> 工具 直接路由（跳过 LLM 工具选择，速度更快，参数更准）
# ============================================================
# action_type -> (tool_function_name, 需要的 payload 参数默认值/转换)
# 命中的 action.type 会直接调用对应工具，参数用 action.payload，不再经过 graph/agent
_DIRECT_TOOL_ROUTING: dict = {
    # 文章列表弹窗：点击分页、筛选都会发这个
    "list_articles_probe": "list_articles",
    # 打开发布账号选择器时查询可用账号
    "list_bindings_for_publish": "list_bindings",
    # 从弹窗确认发布（批量场景下前端会按每个账号发多次）
    "publish_article": "publish_article",
    # 引导流程按钮：直达工具，跳过 LLM 工具选择（参数来自 onboarding 注入的 payload）
    "generate_questions": "generate_questions",
    "generate_articles": "generate_articles",
}


def _convert_direct_payload(action_type: str, payload: dict, user_id: int) -> dict:
    """把前端 action.payload 转换成工具的 slots 参数（user_id 由调用方单独传入）。"""
    payload = payload or {}
    params = {}
    if action_type == "list_articles_probe":
        params = {
            "project_id": payload.get("project_id"),
            "keyword": payload.get("keyword"),
            "publish_status": payload.get("publish_status"),
            "page": int(payload.get("page") or 1),
            "limit": int(payload.get("limit") or 10),
        }
    elif action_type == "list_bindings_for_publish":
        params = {
            "platform": payload.get("platform"),
            "show_all": False,
        }
    elif action_type == "publish_article":
        params = {
            "article_id": payload.get("article_id"),
            "account_id": payload.get("account_id"),
            # 允许前端指定多个平台名；account_id 优先
            "platforms": payload.get("platforms"),
        }
    elif action_type == "generate_questions":
        params = {
            "project_id": payload.get("project_id"),
            "question_count": int(payload.get("question_count") or payload.get("count") or 5),
        }
    elif action_type == "generate_articles":
        params = {
            "project_id": payload.get("project_id"),
            "count": int(payload.get("count") or 1),
            "question_ids": payload.get("question_ids") or [],
        }
    return params


async def _invoke_tool_directly(tool_name: str, params: dict, user_id: int) -> tuple[str, list[dict], list[dict], dict]:
    """直接调用工具函数（工具签名统一：(slots, user_id)），返回 (reply_text, actions_list, async_task_refs, tool_data)。"""
    # 懒加载，避免循环引用
    from backend.services.agent_v2.tools.article_tools import (
        list_articles_tool,
        generate_articles_tool,
    )
    from backend.services.agent_v2.tools.question_tools import generate_questions_tool
    from backend.services.agent_v2.tools.publish_tools import publish_article_tool
    from backend.services.agent_v2.tools.account_tools import list_bindings_tool

    tool_fn = {
        "list_articles": list_articles_tool,
        "publish_article": publish_article_tool,
        "list_bindings": list_bindings_tool,
        "generate_questions": generate_questions_tool,
        "generate_articles": generate_articles_tool,
    }.get(tool_name)
    if tool_fn is None:
        raise ValueError(f"未知直接路由工具: {tool_name}")
    # 注：V2 工具签名统一为 async fn(slots: dict, user_id: int) -> ToolOutcome
    logger.info(f"[agent_v2/direct] 开始调用工具 {tool_name}, params={params}, user_id={user_id}")
    try:
        result = await tool_fn(params, user_id)
    except Exception as e:
        logger.error(f"[agent_v2/direct] 工具 {tool_name} 调用异常: {e}", exc_info=True)
        raise
    reply = getattr(result, "reply", "") or ""
    actions = getattr(result, "actions", None) or []
    async_task_refs = getattr(result, "async_task_refs", None) or []
    tool_data = getattr(result, "data", None) or {}
    logger.info(
        f"[agent_v2/direct] 工具 {tool_name} 完成, reply_len={len(reply)}, actions={len(actions)}, async_tasks={len(async_task_refs)}"
    )
    return reply, actions, async_task_refs, tool_data


# ============================================================
#  请求 / 响应 Schema
# ============================================================


class AgentMessageRequest(BaseModel):
    """智能体对话请求（响应是 SSE 流）。

    action 字段用于前端 action 回调（如 select_client/show_client_form 后回传用户选择），
    后端把 action payload 注入到消息文本中作为结构化上下文，让 ReAct Agent 能获取
    用户选择的具体实体（如 client_id），避免 payload 丢失。

    silent=true 时，action 正常处理但不创建用户消息气泡（用于弹窗内操作）。
    """

    message: str = Field(default="", max_length=4000)  # 允许空消息（仅 action 回调时）
    session_id: Optional[str] = None
    attachments: list[dict] = Field(default_factory=list)
    action: Optional[dict] = None  # V1 兼容：{type, label, payload}
    silent: bool = Field(default=False)  # 静默模式：不创建用户消息气泡


class PreferenceUpdate(BaseModel):
    """用户偏好更新。"""

    default_project_id: Optional[int] = None
    default_platforms: Optional[list[str]] = None
    default_publish_strategy: Optional[str] = None
    require_confirmation_before_publish: Optional[bool] = None
    tone_preference: Optional[str] = None


class WSRegisterRequest(BaseModel):
    """WebSocket 注册 user_id 映射。"""

    client_id: str
    user_id: int


# ============================================================
#  工具函数
# ============================================================


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_effective_message(message: str, action: Optional[dict]) -> str:
    """把用户消息和 action 回调组合成 LLM 可理解的结构化文本。

    V2 的 ReAct Agent 没有独立的 action 端点，前端 action 回调（如 select_client/
    show_client_form 后用户提交）需要把 payload 注入到消息文本中，让 LLM 能获取
    用户选择的具体实体（如 client_id），避免 payload 丢失。

    策略：
    - 无 action：直接返回 message
    - action + message：拼接 message 和 action 摘要
    - 仅 action（无 message）：用 action.label 或 type 作为消息，附带 payload
    """
    if not action:
        return message

    action_type = action.get("type", "")
    action_label = action.get("label", "")
    payload = action.get("payload") or {}

    # 无 payload 的 action（如 dismiss_onboarding/confirm/cancel）→ 用 label 即可
    if not payload:
        if message:
            return f"{message}（{action_label or action_type}）"
        return action_label or action_type

    # 有 payload 的 action（如 select_client 带 client_id）→ 注入结构化信息
    # 把 payload 的 key-value 拼成可读文本，让 LLM 提取
    payload_parts = [f"{k}={v}" for k, v in payload.items() if v is not None]
    payload_str = "，".join(payload_parts)

    if message:
        return f"{message}（{action_label or action_type}：{payload_str}）"
    return f"{action_label or action_type}：{payload_str}"


def _session_to_dict(session: ConversationSession, include_slots: bool = False) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "source": session.source,
        "created_at": _iso(session.created_at),
        "updated_at": _iso(session.updated_at),
        "slots": session.slots if include_slots else None,
    }


def _message_to_dict(msg: ConversationMessage) -> dict:
    return {
        "id": msg.id,
        "role": msg.role,
        "content": msg.content,
        "metadata": msg.message_metadata or {},
        "created_at": _iso(msg.created_at),
    }


# ============================================================
#  SSE 流式主端点
# ============================================================


@router.post("/message")
async def send_message(
    payload: AgentMessageRequest,
    current_user: User = Depends(get_current_active_user),
):
    """智能体对话主入口，返回 SSE 流。

    响应 Content-Type: text/event-stream，按 PRD 13.3 节推送事件（ReAct 模式）：
    thinking → tool_calls → tool_start → tool_end → actions → text_delta → done

    使用 run_agent_stream 实时推送每个节点的输出，用户能看到 Agent 思考过程
    和工具调用状态（对应 PRD §11.7）。
    """
    user_id = current_user.id
    session_id = payload.session_id or f"v2_{uuid.uuid4().hex[:16]}"

    async def _main_event_stream():
        """主事件流（直接路由 + ReAct Graph 常规通道）。"""
        try:
            # ---------- 快捷通道：前端 action 直接路由工具（跳过 LLM，更准更快）----------
            action = payload.action or {}
            action_type = action.get("type", "")
            if action_type in _DIRECT_TOOL_ROUTING:
                tool_name = _DIRECT_TOOL_ROUTING[action_type]
                direct_params = _convert_direct_payload(action_type, action.get("payload") or {}, user_id)
                logger.info(
                    f"[agent_v2/direct] 命中直接路由 action_type={action_type} -> tool={tool_name} params={direct_params}"
                )
                # 发 tool_start 事件
                yield events.tool_start_event(tool_name, direct_params)
                direct_status = "completed"
                direct_reply = ""
                direct_actions: list[dict] = []
                direct_async_task_refs: list[dict] = []
                direct_tool_data: dict = {}
                try:
                    (
                        direct_reply,
                        direct_actions,
                        direct_async_task_refs,
                        direct_tool_data,
                    ) = await _invoke_tool_directly(tool_name, direct_params, user_id)
                except Exception as t_e:
                    logger.error(f"[agent_v2/direct] 工具 {tool_name} 执行失败: {t_e}", exc_info=True)
                    direct_status = "failed"
                    direct_reply = f"工具执行失败：{t_e}"
                    yield events.tool_end_event(
                        tool_name,
                        {"ok": False, "error": str(t_e)},
                        [],
                    )
                    yield events.error_event("tool_execution_error", str(t_e))
                if direct_status == "completed":
                    # 发 tool_end + actions（如果有）+ text_delta + done
                    yield events.tool_end_event(
                        tool_name, {"ok": True, "reply": direct_reply, "actions": direct_actions}, direct_actions or []
                    )
                    if direct_actions:
                        yield events.actions_event(direct_actions)
                    # 把 reply 作为 text_delta 推给前端（UI 上是助手消息）
                    if direct_reply:
                        yield events.text_delta_event(direct_reply)
                # 直接路由不经过 Graph，这里手动调用 persist_mem 保存对话历史
                # （此前缺失导致按钮操作刷新后历史丢失）
                try:
                    from backend.services.agent_v2.nodes.persist_mem import persist_mem

                    persist_state = {
                        "user_id": user_id,
                        "session_id": session_id,
                        # 供 persist_mem 提取用户消息；silent=true 时跳过用户气泡
                        "messages": [
                            {
                                "role": "user",
                                "content": _build_effective_message(payload.message, payload.action),
                            }
                        ],
                        "reply": direct_reply,
                        "actions": direct_actions,
                        "async_task_refs": direct_async_task_refs,
                        "tool_results": [
                            {
                                "name": tool_name,
                                "result": {"data": direct_tool_data, "status": direct_status},
                            }
                        ],
                        "status": direct_status,
                        "facts_patch": [],
                        "silent": payload.silent,
                    }
                    await persist_mem(persist_state)
                except Exception as persist_e:
                    logger.error(f"[agent_v2/direct] persist_mem 失败（不影响响应）: {persist_e}", exc_info=True)

                # 把工具执行结果回传给前端 done 事件，前端据此推进引导步骤并展示结果（如生成的问题）
                yield events.done_event(
                    status=direct_status,
                    session_id=session_id,
                    actions=direct_actions,
                    async_task_refs=direct_async_task_refs,
                    tool_results=[
                        {
                            "name": tool_name,
                            "result": {"data": direct_tool_data, "status": direct_status},
                        }
                    ],
                )
                return

            # ---------- 常规通道：走 ReAct Graph ----------
            # 把 action 回调转换为结构化消息文本，让 ReAct Agent 能获取 payload
            # 对应 V1 的 action 回调机制：select_client/confirm/show_*_form 等
            effective_message = _build_effective_message(payload.message, payload.action)

            # 构造初始状态
            state = make_initial_state(
                user_id=user_id,
                session_id=session_id,
                message=effective_message,
                attachments=payload.attachments,
            )

            # 流式运行 Agent，run_agent_stream 会实时 yield SSE 事件
            async for sse_event in run_agent_stream(state):
                yield sse_event

        except asyncio.CancelledError:
            logger.info(f"[agent_v2/message] SSE 流被客户端取消 user={user_id}")
            yield events.error_event("cancelled", "客户端取消")
        except Exception as e:
            logger.error("[agent_v2/message] 执行失败: " + str(e), exc_info=True)
            yield events.error_event("internal_error", str(e))
            yield events.done_event(status="failed", session_id=session_id)

    async def event_stream():
        """合并主事件流与后台心跳，防止长任务期间连接超时。

        主事件流（_main_event_stream）与心跳流（_heartbeat，每 5 秒一个
        progress 事件）通过 asyncio.Queue 合并输出：主流程有事件时立即推送，
        阻塞期间由心跳保活，避免 Nginx/网关在长任务（如批量生成文章）时
        因无数据而掐断 SSE 连接。
        """
        queue: "asyncio.Queue" = asyncio.Queue()
        start_time = asyncio.get_event_loop().time()

        async def main_producer():
            try:
                async for sse_event in _main_event_stream():
                    await queue.put(sse_event)
            except asyncio.CancelledError:
                raise
            finally:
                # sentinel：主流程结束，通知消费者停止
                await queue.put(None)

        async def hb_producer():
            try:
                async for hb_event in _heartbeat(start_time):
                    await queue.put(hb_event)
            except asyncio.CancelledError:
                pass

        main_task = asyncio.create_task(main_producer())
        hb_task = asyncio.create_task(hb_producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            hb_task.cancel()
            if not main_task.done():
                main_task.cancel()
            await asyncio.gather(main_task, hb_task, return_exceptions=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 不缓冲
        },
    )


async def _heartbeat(start_time: float):
    """后台心跳任务，防止长任务期间连接超时。

    对应 PRD 13.6 节：generate_articles_batch 阻塞 10-60 秒时，
    每隔 5 秒发一个 progress 心跳事件。
    """
    try:
        while True:
            await asyncio.sleep(5)
            elapsed = asyncio.get_event_loop().time() - start_time
            yield events.progress_event("processing", elapsed)
    except asyncio.CancelledError:
        return


# ============================================================
#  会话管理端点
# ============================================================


@router.get("/sessions")
async def list_sessions(
    status: Optional[str] = Query(None, description="按会话状态过滤"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """列出当前用户的会话（默认排除 archived）。"""
    query = (
        db.query(ConversationSession)
        .filter(ConversationSession.system_user_id == current_user.id)
        .order_by(ConversationSession.updated_at.desc())
    )
    if status:
        query = query.filter(ConversationSession.status == status)
    else:
        query = query.filter(ConversationSession.status.notin_(["archived", "deleted"]))
    total = query.count()
    sessions = query.offset(offset).limit(limit).all()

    items = []
    for s in sessions:
        last_msg = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == s.id)
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .first()
        )
        last_text = None
        if last_msg and last_msg.content:
            _raw = last_msg.content
            last_text = (_raw[:60] + "…") if len(_raw) > 60 else _raw
        items.append(
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "current_intent": s.current_intent,
                "last_message": last_text,
                "last_message_role": last_msg.role if last_msg else None,
                "updated_at": _iso(s.updated_at),
            }
        )
    return {"total": total, "items": items}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    include_slots: bool = Query(False, description="是否返回原始 slots"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取会话详情（含消息历史）。"""
    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.id == session_id,
            ConversationSession.system_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == session_id)
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
        .all()
    )
    return {
        "session": {
            "id": session.id,
            "title": session.title,
            "status": session.status,
            "current_intent": session.current_intent,
            "created_at": _iso(session.created_at),
            "updated_at": _iso(session.updated_at),
            **({"slots": session.slots or {}} if include_slots else {}),
        },
        "messages": [_message_to_dict(m) for m in messages],
    }


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """更新会话（目前仅支持重命名）。"""
    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.id == session_id,
            ConversationSession.system_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    if "title" in body and body["title"]:
        session.title = body["title"]
    db.commit()
    return {"success": True, "id": session_id}


@router.post("/sessions/{session_id}/archive")
async def archive_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """归档会话。"""
    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.id == session_id,
            ConversationSession.system_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    session.status = "archived"
    db.commit()
    return {"success": True, "id": session_id}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """删除会话（软删除）。"""
    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.id == session_id,
            ConversationSession.system_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    session.status = "deleted"
    db.commit()
    return {"success": True, "id": session_id}


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取会话消息历史。"""
    session = (
        db.query(ConversationSession)
        .filter(
            ConversationSession.id == session_id,
            ConversationSession.system_user_id == current_user.id,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    rows = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == session_id,
        )
        .order_by(
            ConversationMessage.created_at.asc(),
            ConversationMessage.id.asc(),
        )
        .limit(limit)
        .all()
    )
    return {
        "total": len(rows),
        "items": [_message_to_dict(r) for r in rows],
    }


# ============================================================
#  偏好与事实端点
# ============================================================


@router.get("/preferences")
async def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取用户偏好。"""
    record = (
        db.query(UserAgentPreference)
        .filter(
            UserAgentPreference.system_user_id == current_user.id,
        )
        .first()
    )
    if not record:
        return {
            "default_project_id": None,
            "default_platforms": [],
            "default_publish_strategy": None,
            "require_confirmation_before_publish": True,
            "tone_preference": None,
        }
    return {
        "default_project_id": record.default_project_id,
        "default_platforms": record.default_platforms or [],
        "default_publish_strategy": record.default_publish_strategy,
        "require_confirmation_before_publish": record.require_confirmation_before_publish,
        "tone_preference": record.tone_preference,
    }


@router.put("/preferences")
async def update_preferences(
    payload: PreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """更新用户偏好。"""
    record = (
        db.query(UserAgentPreference)
        .filter(
            UserAgentPreference.system_user_id == current_user.id,
        )
        .first()
    )
    if not record:
        record = UserAgentPreference(system_user_id=current_user.id)
        db.add(record)

    update_data = payload.dict(exclude_none=True)
    for key, value in update_data.items():
        setattr(record, key, value)

    db.commit()
    db.refresh(record)
    return {"success": True, "preferences": update_data}


@router.get("/facts")
async def get_facts(
    user_id: Optional[int] = Query(None, description="可选，admin 可查任意用户"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取用户事实（admin 可查任意用户）。"""
    target_user_id = user_id if (user_id and current_user.role == "admin") else current_user.id
    record = (
        db.query(UserAgentFact)
        .filter(
            UserAgentFact.system_user_id == target_user_id,
        )
        .first()
    )
    if not record:
        return {
            "user_id": target_user_id,
            "facts": {},
            "onboarding_stage": None,
            "onboarding_completed": False,
        }
    return {
        "user_id": target_user_id,
        "facts": record.facts or {},
        "onboarding_stage": record.onboarding_stage,
        "onboarding_completed": record.onboarding_completed,
    }


@router.get("/onboarding")
async def get_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取新用户引导状态（清单 + 下一步动作）。

    前端在聊天打开时、以及每轮操作（点 action / 收到助手消息）后调用，
    用于渲染顶部常驻进度条与对话内“下一步”卡片。状态完全由 DB 实况算出。
    """
    from backend.services.agent_v2.onboarding import compute_onboarding_state

    return compute_onboarding_state(
        db,
        current_user.id,
        is_admin=(getattr(current_user, "role", None) == "admin"),
    )


@router.post("/onboarding/dismiss")
async def dismiss_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """用户主动跳过引导，持久化 dismissed，之后不再弹（含刷新/重启/新开窗口）。"""
    from backend.services.agent_v2.onboarding import set_onboarding_dismissed

    set_onboarding_dismissed(db, current_user.id, True)
    return {"success": True}


# ============================================================
#  WebSocket user_id 注册端点
# ============================================================


@router.post("/ws/register")
async def register_ws_user(
    payload: WSRegisterRequest,
    current_user: User = Depends(get_current_active_user),
):
    """注册 WebSocket client_id 与 user_id 的映射。

    前端在建立 WebSocket 连接后，调此端点注册映射，
    以便后端异步任务完成时通过 ws_manager.notify_user 推送通知。
    """
    # 校验 client_id 确实在线
    if payload.client_id not in ws_manager.active_connections:
        raise HTTPException(status_code=404, detail="WebSocket client 不在线")

    # 安全校验：user_id 必须是当前登录用户
    if payload.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权注册其他用户的映射")

    # 建立映射
    ws_manager.user_connections.setdefault(payload.user_id, [])
    if payload.client_id not in ws_manager.user_connections[payload.user_id]:
        ws_manager.user_connections[payload.user_id].append(payload.client_id)

    logger.info(f"[agent_v2/ws/register] user={payload.user_id} client={payload.client_id}")
    return {"success": True, "user_id": payload.user_id, "client_id": payload.client_id}
