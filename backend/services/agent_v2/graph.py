# -*- coding: utf-8 -*-
"""LangGraph 状态图定义 - Agent V2 主图。

对应 PRD §4.4 / §6 ReAct Agent 循环：

    LOAD_CONTEXT (graph 外预处理)
        ↓
    ┌→ AGENT (LLM 推理 + Tool Calling) ←─┐
    │     ↓                               │
    │  should_continue?                   │
    │     ↓ tool_calls 非空               │
    │  TOOLS (执行工具，回写 ToolMessage) ─┘
    │     ↓ tool_calls 为空
    │  END
    │
    └─→ PERSIST_MEM (graph 外后处理)

LangGraph 通过 PostgresSaver 自动持久化 AGENT↔TOOLS 循环中的 State，
支持中断恢复和跨请求保持上下文（thread_id = session_id）。
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

from loguru import logger

from backend.services.agent_v2 import events
from backend.services.agent_v2.state import AgentState


def _dedup_actions(actions: list[dict]) -> list[dict]:
    """对 actions 列表去重，保留最后一次出现的每个 action。

    add_list reducer 会累积 checkpoint 中的旧值，导致同一 action 在
    多轮对话中重复出现。去重策略：按 (type, label) 作为唯一键，
    保留最后一次出现的版本（payload 取最新的）。
    """
    seen: dict[tuple[str, str], dict] = {}
    for act in actions:
        if not isinstance(act, dict):
            continue
        key = (act.get("type", ""), act.get("label", ""))
        seen[key] = act
    return list(seen.values())


# ------------------------------------------------------------------
#  Checkpointer 初始化（AsyncPostgresSaver，dev 兜底 MemorySaver）
# ------------------------------------------------------------------

_checkpointer: Any = None
_checkpointer_kind: str = ""


def _normalize_db_url(url: str) -> str:
    """把 SQLAlchemy 的 DATABASE_URL 转成 psycopg3 接受的 URL。

    SQLAlchemy: postgresql+psycopg2://user:pwd@host:port/db
    psycopg3:   postgresql://user:pwd@host:port/db  或  postgresql+psycopg://...
    两者都接受 postgresql:// 前缀。
    """
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


async def get_checkpointer() -> Any:
    """获取 AsyncPostgresSaver 实例（懒加载，全局共享）。

    使用异步版本 AsyncPostgresSaver，因为整个 Agent 流程是 async 的：
    - graph.astream / graph.aget_state / graph.aupdate_state 都是 async 方法
    - 同步 PostgresSaver 不实现 async 接口，会抛出 NotImplementedError

    Windows 平台说明：
    - Windows 默认使用 ProactorEventLoop，psycopg async 不兼容（需要 SelectorEventLoop）
    - 全局切换事件循环会破坏 SQLAlchemy 同步代码，因此 Windows 上回退到 MemorySaver
    - 生产环境（Linux）正常使用 AsyncPostgresSaver 持久化

    失败时回退到 MemorySaver（仅开发环境，不持久化）。
    第一次调用会执行 await setup() 创建 checkpoint 表（幂等）。

    使用 AsyncConnectionPool 而非 from_conn_string 上下文管理器：
    - from_conn_string 是 @contextmanager，__enter__ 后必须 __exit__ 才能释放连接
    - AsyncConnectionPool 适合长期持有的服务进程，支持并发访问
    """
    global _checkpointer, _checkpointer_kind
    if _checkpointer is not None:
        return _checkpointer

    import sys

    from backend.config import DATABASE_URL

    db_url = _normalize_db_url(DATABASE_URL)

    # Windows 平台跳过 AsyncPostgresSaver（ProactorEventLoop 不兼容 psycopg async）
    if sys.platform == "win32":
        logger.info(
            "[AgentGraph] Windows 平台检测到，跳过 AsyncPostgresSaver（ProactorEventLoop 不兼容），"
            "使用 MemorySaver（开发环境）。生产环境部署在 Linux 上会自动启用 AsyncPostgresSaver。"
        )
    else:
        # 优先 AsyncPostgresSaver（异步连接池，支持 graph.astream 等异步方法）
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # 连接池参数与 from_conn_string 内部一致：
            # autocommit=True, prepare_threshold=0, row_factory=dict_row
            pool = AsyncConnectionPool(
                conninfo=db_url,
                max_size=10,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                open=True,
            )
            _checkpointer = AsyncPostgresSaver(conn=pool)
            await _checkpointer.setup()  # 幂等创建 checkpoint 表（async）
            _checkpointer_kind = "postgres"
            logger.info("[AgentGraph] Checkpointer=AsyncPostgresSaver (异步生产持久化, 连接池)")
            return _checkpointer
        except Exception as e:
            logger.warning(
                f"[AgentGraph] AsyncPostgresSaver 初始化失败，回退到 MemorySaver: {e}"
            )
            _checkpointer = None

    # 回退 MemorySaver（MemorySaver 同时支持 sync/async 接口）
    try:
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        _checkpointer_kind = "memory"
        logger.warning(
            "[AgentGraph] Checkpointer=MemorySaver（仅开发环境，重启后状态丢失）"
        )
        return _checkpointer
    except Exception as e:
        logger.error(f"[AgentGraph] MemorySaver 也初始化失败: {e}")
        raise


def get_checkpointer_kind() -> str:
    """返回当前 checkpointer 类型（postgres / memory / 空字符串）。"""
    return _checkpointer_kind


# ------------------------------------------------------------------
#  StateGraph 构建
# ------------------------------------------------------------------

_compiled_graph: Any = None


async def build_graph() -> Any:
    """构建并编译 LangGraph StateGraph。

    节点：
    - agent: LLM 推理 + Tool Calling 决策
    - tools: 执行 tool_calls，回写 ToolMessage

    边：
    - START → agent
    - agent → (tool_calls 非空) → tools
    - agent → (tool_calls 为空) → END
    - tools → agent (回环，实现 ReAct 循环)
    """
    from langgraph.graph import END, START, StateGraph

    from backend.services.agent_v2.nodes.agent_node import agent_node
    from backend.services.agent_v2.nodes.tools_node import tools_node

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")  # 工具执行后回到 agent 继续推理

    checkpointer = await get_checkpointer()
    compiled = builder.compile(checkpointer=checkpointer)
    logger.info(
        f"[AgentGraph] StateGraph 编译完成 checkpointer={_checkpointer_kind}"
    )
    return compiled


def _should_continue(state: AgentState) -> str:
    """条件路由：有 tool_calls 走 tools，否则结束。

    LangGraph 在 agent → tools 边上调用此函数。
    返回 langgraph.graph.END 常量（实际值 "__end__"）结束图执行。
    """
    from langgraph.graph import END

    tool_calls = state.get("tool_calls") or []
    if tool_calls:
        return "tools"
    return END


async def get_graph() -> Any:
    """获取全局编译后的 graph 实例（懒加载，async）。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = await build_graph()
    return _compiled_graph


# ------------------------------------------------------------------
#  中断恢复检查
# ------------------------------------------------------------------

async def _check_and_clean_interrupted_state(config: dict) -> None:
    """检查并清理中断恢复场景下的遗留状态。

    场景：进程在 graph.ainvoke 执行期间崩溃，Checkpoint 保存了中间状态
    （比如 agent_node 已输出 tool_calls，但 tools_node 未执行）。下次请求时，
    LangGraph 会尝试从中断处恢复，导致**未经过用户确认就执行遗留的工具调用**。

    解决：检测到 next 非空（有未执行的节点）时，清理 tool_calls 和 status，
    让 graph 从 START 重新开始。

    对应 PRD §6.3 场景2 中断恢复。
    """
    graph = await get_graph()
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.next:
            logger.warning(
                f"[AGENT] 检测到中断恢复，next={snapshot.next}，"
                f"清理遗留 tool_calls 避免误执行"
            )
            await graph.aupdate_state(config, {
                "tool_calls": [],
                "status": "completed",
            })
    except Exception as e:
        # 某些 Checkpointer 可能不支持 aget_state，忽略错误
        logger.warning(f"[AGENT] 检查中断恢复失败（忽略，继续执行）: {e}")


# ------------------------------------------------------------------
#  Graph 入口：run_agent（同步版本）
# ------------------------------------------------------------------

async def run_agent(state: AgentState) -> AgentState:
    """运行 Agent 主流程（同步，整图执行完才返回）。

    SSE 流式场景请用 run_agent_stream。

    流程：
    1. LOAD_CONTEXT（graph 外预处理）：加载 user_facts 和 preferences
    2. 检查中断恢复：清理遗留 tool_calls
    3. graph.ainvoke(...)：执行 ReAct 循环
    4. PERSIST_MEM：写回对话历史与长期记忆
    """
    from backend.services.agent_v2.nodes.load_context import load_context
    from backend.services.agent_v2.nodes.persist_mem import persist_mem

    start_ts = time.perf_counter()
    user_id = state.get("user_id")
    session_id = state.get("session_id")
    message_preview = ""
    messages = state.get("messages") or []
    if messages:
        last_msg = messages[-1]
        # messages 可能存 BaseMessage（add_messages reducer 转换后）或 dict
        if hasattr(last_msg, "content"):
            message_preview = (last_msg.content or "")[:60]
        elif isinstance(last_msg, dict):
            message_preview = (last_msg.get("content") or "")[:60]

    logger.info(
        f"[AGENT_V2_METRIC] start user={user_id} session={session_id} "
        f"msg_preview={message_preview!r}"
    )

    # ===== 1. LOAD_CONTEXT：注入 user_facts 和 preferences =====
    try:
        state = await load_context(state)
    except Exception as e:
        logger.error(f"[LOAD_CONTEXT] 失败，继续以空上下文运行: {e}", exc_info=True)

    # ===== 2. 检查中断恢复 =====
    actual_session_id = state.get("session_id", session_id)
    config = {"configurable": {"thread_id": actual_session_id}}
    await _check_and_clean_interrupted_state(config)

    # ===== 2.5 移除由 Checkpointer 管理的字段，避免覆盖 Checkpoint 中的值 =====
    # task_context 没有 reducer（覆盖语义），make_initial_state 设置的 None 会覆盖
    # Checkpoint 中跨轮累积的 task_context，导致短期记忆丢失。
    # 移除后 LangGraph 会从 Checkpoint 恢复 task_context（对应 PRD §7.2.2 短期记忆）
    state.pop("task_context", None)

    # ===== 2.6 重置每轮输出字段 =====
    # actions / async_task_refs / tool_results / facts_patch 使用 add_list reducer，
    # 会在 Checkpoint 已累积值的基础上追加，导致跨轮累积（按钮重复等）。
    # 这里设置空列表作为初始值，graph 执行完后还需去重（见下方 _dedup_actions）。
    state["actions"] = []
    state["async_task_refs"] = []
    state["tool_results"] = []
    state["facts_patch"] = []

    # ===== 3. 执行 ReAct 循环 =====
    graph = await get_graph()
    try:
        final_state = await graph.ainvoke(state, config=config)
    except Exception as e:
        duration_ms = int((time.perf_counter() - start_ts) * 1000)
        logger.error(
            f"[AGENT_V2_METRIC] failed user={user_id} session={session_id} "
            f"duration={duration_ms}ms error={type(e).__name__}: {e}"
        )
        # 兜底：构造完整 final_state，不依赖 reducer 合并
        # 注意：actions/async_task_refs/facts_patch 用 add_list reducer，
        # 传入空 list 不会清空已累积值，所以这里直接返回空 list 是安全的
        # （因为 graph.ainvoke 失败时 state 未被 graph 内部更新）
        final_state = {
            **state,
            "reply": f"智能体执行失败：{e}",
            "status": "failed",
            "tool_calls": [],
            "actions": [],
            "async_task_refs": [],
            "facts_patch": [],
            "tool_results": [],
            "thinking": f"执行失败: {type(e).__name__}: {e}",
        }

    # ===== 3.5 去重 actions（add_list reducer 会累积 checkpoint 中的旧值） =====
    final_state["actions"] = _dedup_actions(final_state.get("actions", []) or [])

    # ===== 4. PERSIST_MEM：写回对话历史与长期记忆 =====
    try:
        await persist_mem(final_state)
    except Exception as e:
        logger.error(f"[PERSIST_MEM] 失败（不影响主流程）: {e}", exc_info=True)

    # ===== 5. 监控埋点 =====
    duration_ms = int((time.perf_counter() - start_ts) * 1000)
    status = final_state.get("status", "completed")
    reply_len = len(final_state.get("reply") or "")
    async_task_count = len(final_state.get("async_task_refs") or [])
    actions_count = len(final_state.get("actions") or [])
    tool_result_count = len(final_state.get("tool_results") or [])

    logger.info(
        f"[AGENT_V2_METRIC] done user={user_id} session={session_id} "
        f"status={status} duration={duration_ms}ms "
        f"reply_len={reply_len} actions={actions_count} "
        f"tool_results={tool_result_count} async_tasks={async_task_count}"
    )

    return final_state


# ------------------------------------------------------------------
#  Graph 入口：run_agent_stream（流式，供 SSE 端点调用）
# ------------------------------------------------------------------

async def run_agent_stream(state: AgentState) -> AsyncIterator[str]:
    """流式运行 Agent，yield SSE 事件字符串。

    与 run_agent 的区别：用 graph.astream(stream_mode="updates") 实时推送
    每个节点的输出，让用户看到 Agent 思考过程和工具调用状态。

    对应 PRD §11.7 Agent 思考过程展示 + §13.3 SSE 事件类型。

    流程：
    1. LOAD_CONTEXT → 推送 progress 事件
    2. 检查中断恢复
    3. graph.astream(stream_mode="updates") → 实时推送节点输出
       - agent 节点：thinking / tool_calls / reply（直接回复时）
       - tools 节点：tool_start / tool_end / actions / async_task_started
    4. PERSIST_MEM
    5. done 事件

    Yields:
        SSE 事件字符串（event: <type>\\ndata: <json>\\n\\n 格式）
    """
    from backend.services.agent_v2.nodes.load_context import load_context
    from backend.services.agent_v2.nodes.persist_mem import persist_mem

    start_ts = time.perf_counter()
    user_id = state.get("user_id")
    session_id = state.get("session_id")

    logger.info(f"[AGENT_V2_STREAM] start user={user_id} session={session_id}")

    # ===== 1. LOAD_CONTEXT =====
    try:
        state = await load_context(state)
    except Exception as e:
        logger.error(f"[LOAD_CONTEXT] 失败: {e}", exc_info=True)
        yield events.error_event("load_context_failed", str(e))
        yield events.done_event(status="failed", session_id=session_id)
        return

    actual_session_id = state.get("session_id", session_id)
    config = {"configurable": {"thread_id": actual_session_id}}

    # ===== 2. 检查中断恢复 =====
    await _check_and_clean_interrupted_state(config)

    # ===== 2.5 移除由 Checkpointer 管理的字段，避免覆盖 Checkpoint 中的值 =====
    # task_context 没有 reducer（覆盖语义），make_initial_state 设置的 None 会覆盖
    # Checkpoint 中跨轮累积的 task_context，导致短期记忆丢失。
    # 移除后 LangGraph 会从 Checkpoint 恢复 task_context（对应 PRD §7.2.2 短期记忆）
    state.pop("task_context", None)

    # ===== 2.6 重置每轮输出字段 =====
    # actions / async_task_refs / tool_results / facts_patch 使用 add_list reducer，
    # 如果不在每轮开始时重置为空列表，Checkpointer 会恢复上一轮的值，
    # add_list 会在其基础上追加，导致跨轮累积（按钮重复、异步任务重复等）。
    # 重置为空列表后，add_list 会替换 Checkpoint 中的值（空 + 新值 = 新值）。
    state["actions"] = []
    state["async_task_refs"] = []
    state["tool_results"] = []
    state["facts_patch"] = []

    # ===== 3. 流式执行 graph =====
    graph = await get_graph()
    # 先初始化 final_state 为完整默认值，避免后续 KeyError
    final_state: dict = {
        **dict(state),
        "reply": state.get("reply", ""),
        "thinking": state.get("thinking", ""),
        "status": state.get("status", "completed"),
        "tool_calls": state.get("tool_calls", []) or [],
        "tool_results": state.get("tool_results", []) or [],
        "actions": state.get("actions", []) or [],
        "async_task_refs": state.get("async_task_refs", []) or [],
        "facts_patch": state.get("facts_patch", []) or [],
        "task_context": state.get("task_context"),
        "messages": state.get("messages", []) or [],
    }
    exec_exception: Exception | None = None
    try:
        async for chunk in graph.astream(state, config=config, stream_mode="updates"):
            # chunk 是 {node_name: state_update}
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                # 防御性：_emit_node_events 内部错误不影响主流程
                try:
                    async for sse_event in _emit_node_events(node_name, update):
                        yield sse_event
                except Exception as emit_e:
                    logger.warning(f"[AGENT_V2_STREAM] _emit_node_events 失败（忽略）: {emit_e}")

            # 用最后一个 chunk 的 update 更新 final_state
            # 注意：astream 的 updates 模式每个 chunk 是单节点的输出，
            # reducer 已经在 graph 内部应用，这里只是为了拿到最终 state 做 PERSIST_MEM
            if chunk:
                last_update = list(chunk.values())[-1]
                if isinstance(last_update, dict):
                    # 手动合并累积型字段（与 state.py 的 reducer 一致）
                    for key in ("tool_results", "actions", "async_task_refs", "facts_patch"):
                        if key in last_update and last_update[key] is not None:
                            existing = final_state.get(key, []) or []
                            final_state[key] = existing + last_update[key]
                    # 覆盖型字段直接更新（非空才覆盖，避免 last_non_empty reducer 语义被破坏）
                    for key in ("reply", "thinking", "tool_calls", "status", "task_context", "messages"):
                        if key in last_update:
                            val = last_update[key]
                            if key in ("reply", "thinking"):
                                if val:
                                    final_state[key] = val
                            else:
                                final_state[key] = val

    except Exception as e:
        exec_exception = e
        duration_ms = int((time.perf_counter() - start_ts) * 1000)
        logger.error(
            f"[AGENT_V2_STREAM] failed user={user_id} session={session_id} "
            f"duration={duration_ms}ms error={type(e).__name__}: {e}",
            exc_info=True,
        )
        # 把异常信息写进 final_state，让后续 PERSIST_MEM 也能记录
        final_state["status"] = "failed"
        final_state["reply"] = final_state.get("reply") or f"智能体执行失败：{e}"
        final_state["thinking"] = final_state.get("thinking") or f"执行失败: {type(e).__name__}: {e}"
        yield events.error_event("execution_failed", str(e))

    # ===== 4. 用 graph 的最终 state（已应用所有 reducer）=====
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.values:
            # 合并时不覆盖异常路径设置的字段
            merged = {**final_state, **snapshot.values}
            # 保留列表型字段的正确合并（避免 snapshot 的空列表覆盖累积值）
            for key in ("tool_results", "actions", "async_task_refs", "facts_patch"):
                cur = final_state.get(key, []) or []
                snap = snapshot.values.get(key, []) or []
                merged[key] = cur if len(cur) >= len(snap) else snap
            final_state = merged
    except Exception as e:
        logger.warning(f"[AGENT_V2_STREAM] 获取最终 state 失败，用累积的 final_state: {e}")

    # ===== 4.5 去重 actions（add_list reducer 会累积 checkpoint 中的旧值） =====
    try:
        final_state["actions"] = _dedup_actions(final_state.get("actions", []) or [])
    except Exception as e:
        logger.warning(f"[AGENT_V2_STREAM] actions 去重失败（忽略）: {e}")
        final_state["actions"] = final_state.get("actions", []) or []

    # 只保留本轮工具实际产生的 actions，避免历史 actions 被带到当前 assistant 消息。
    # LangGraph 的 add_list reducer 会跨轮次累积 actions，但每条回复只需要本轮工具的建议按钮。
    try:
        current_round_actions: list[dict] = []
        seen_action_types: set[str] = set()
        for tr in reversed(final_state.get("tool_results", []) or []):
            for act in (tr.get("result", {}) or {}).get("actions", []) or []:
                act_type = act.get("type")
                if act_type and act_type not in seen_action_types:
                    seen_action_types.add(act_type)
                    current_round_actions.insert(0, act)
        final_state["actions"] = _dedup_actions(current_round_actions)
    except Exception as e:
        logger.warning(f"[AGENT_V2_STREAM] 提取本轮 actions 失败（忽略）: {e}")

    # ===== 5. PERSIST_MEM =====
    try:
        from backend.services.agent_v2.nodes.persist_mem import persist_mem
        await persist_mem(final_state)
    except Exception as e:
        logger.error(f"[PERSIST_MEM] 失败（不影响主流程）: {e}", exc_info=True)

    # ===== 6. done 事件 =====
    duration_ms = int((time.perf_counter() - start_ts) * 1000)
    status = final_state.get("status", "completed")
    actions = final_state.get("actions", []) or []
    async_task_refs = final_state.get("async_task_refs", []) or []
    tool_results = final_state.get("tool_results", []) or []

    # 如果 graph 执行异常且还没 done，发送 done 事件后返回
    if exec_exception is not None:
        yield events.done_event(
            status="failed",
            session_id=actual_session_id,
            actions=actions,
            async_task_refs=async_task_refs,
            tool_results=tool_results,
        )
        return

    # 异步任务运行中 → status=running
    final_status = "running" if async_task_refs else status

    logger.info(
        f"[AGENT_V2_STREAM] done user={user_id} session={session_id} "
        f"status={final_status} duration={duration_ms}ms "
        f"actions={len(actions)} tool_results={len(tool_results)} "
        f"async_tasks={len(async_task_refs)}"
    )

    yield events.done_event(
        status=final_status,
        session_id=actual_session_id,
        actions=actions,
        async_task_refs=async_task_refs,
        tool_results=tool_results,
    )


async def _emit_node_events(node_name: str, update: dict) -> AsyncIterator[str]:
    """根据节点输出的 state update 推送对应的 SSE 事件。

    节点输出与事件映射：
    - agent 节点：
      * thinking → thinking_event（Agent 思考过程）
      * tool_calls 非空 → tool_calls_event（即将调用工具）
      * tool_calls 为空 → text_delta 流式推送 reply（直接回复用户）
    - tools 节点：
      * tool_results → tool_start + tool_end（每个工具一对）
      * actions → actions_event（前端按钮）
      * async_task_refs → async_task_started_event
      * 不推送 reply（让 agent 下一轮总结后推送）
    """
    if node_name == "agent":
        # thinking 事件
        thinking = update.get("thinking", "")
        if thinking:
            yield events.thinking_event(thinking)

        tool_calls = update.get("tool_calls", []) or []
        if tool_calls:
            # 有工具调用 → 推送 tool_calls 事件，不推送 reply
            yield events.tool_calls_event(tool_calls)
        else:
            # 直接回复 → 流式推送 reply
            reply = update.get("reply", "")
            if reply:
                async for delta_event in events.stream_text_deltas(
                    reply, chunk_size=12, delay_ms=15
                ):
                    yield delta_event

            # 追问场景：agent 不调用工具但更新了 task_context 且仍有 missing_slots
            # 推送 clarification 事件让前端进入"等待用户补充信息"状态
            task_context = update.get("task_context")
            if task_context and task_context.get("missing_slots"):
                logger.info(
                    f"[AGENT_V2_STREAM] 追问用户: type={task_context.get('type')} "
                    f"missing={task_context.get('missing_slots')}"
                )
                yield events.clarification_event(reply, [])

    elif node_name == "tools":
        # tool_start + tool_end 事件
        tool_results = update.get("tool_results", []) or []
        for tr in tool_results:
            tool_name = tr.get("name", "")
            result = tr.get("result", {}) or {}
            tool_actions = result.get("actions", []) or []
            # tool_start 用工具调用参数（如果有）
            yield events.tool_start_event(tool_name, tr.get("args", {}))
            yield events.tool_end_event(tool_name, result, tool_actions)

        # actions 事件（前端按钮：列表弹窗/表单弹窗/选择弹窗等）
        actions = update.get("actions", []) or []
        if actions:
            # 去重后再推送，避免 add_list reducer 累积导致重复
            yield events.actions_event(_dedup_actions(actions))

        # async_task_started 事件
        async_task_refs = update.get("async_task_refs", []) or []
        for ref in async_task_refs:
            yield events.async_task_started_event(
                task_type=ref.get("task_type", ""),
                task_id=ref.get("task_id"),
                query_tool=ref.get("query_tool", ""),
            )

        # need_clarification → clarification 事件
        status = update.get("status", "")
        if status == "need_clarification":
            reply = update.get("reply", "")
            yield events.clarification_event(reply, actions)
