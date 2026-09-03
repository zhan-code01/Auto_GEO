# -*- coding: utf-8 -*-
"""AgentState 定义 - LangGraph 状态对象。

对应 PRD 第五章 State 设计。采用 LangGraph 标准 ReAct 范式：
- messages: 工作记忆（对话历史，由 add_messages 自动累积）
- task_context: 短期记忆（当前任务状态，多轮信息提取用）
- user_facts: 长期记忆（跨会话事实）
- tool_calls / tool_results: ReAct 循环中工具调用与结果

Reducer 规则：
- messages: add_messages（LangGraph 内置，自动累积合并）
- tool_results / actions / async_task_refs / facts_patch: 累积合并（多轮 ReAct 不丢失）
- reply / thinking: last_non_empty（保留最后的非空值，避免被空字符串覆盖）
- tool_calls / status / task_context: 覆盖语义（每轮最新值）
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages


# 执行状态
ExecutionStatus = Literal[
    "completed",          # 本轮执行完成
    "need_clarification",  # 需要用户补充信息
    "running",            # 异步任务运行中
    "failed",             # 执行失败
]

# Action 交互方式
ActionInteraction = Literal["frontend_direct", "via_agent"]


# ================================================================
#  自定义 Reducer
# ================================================================

def add_list(left: list | None, right: list | None) -> list:
    """累积合并 list，None 视为空列表。

    用于 tool_results / actions / async_task_refs / facts_patch 字段，
    确保多轮 ReAct 循环中工具结果不会被后续轮次覆盖。
    """
    return (left or []) + (right or [])


def last_non_empty(left: Any, right: Any) -> Any:
    """保留最后的非空值。

    用于 reply / thinking 字段：
    - agent_node 调用工具时可能返回 reply="" （不应清空 tools_node 已设置的回复）
    - 只有当新值非空时才覆盖
    """
    if right is not None and right != "" and right != []:
        return right
    return left


class Action(TypedDict):
    """Action 按钮。"""

    type: str                       # Action 类型（见 actions.ACTION_TYPES）
    label: str                      # 按钮文案
    payload: dict                   # 按钮数据
    interaction: ActionInteraction  # 交互方式：前端直连 / 走智能体


class TaskContext(TypedDict):
    """短期记忆 - 当前任务上下文。

    用于多轮信息提取，任务完成后整体置 None。
    对应 PRD §7.2.2。
    """

    type: str                       # 任务类型（如 create_client / generate_articles）
    slots: dict[str, Any]           # 已收集的槽位
    missing_slots: list[str]        # 仍缺失的必填槽位
    created_at: str                 # 任务开始时间（ISO 格式）


class AgentState(TypedDict):
    """LangGraph 全局状态对象。

    采用标准 ReAct 范式，messages 由 add_messages 自动累积，
    task_context 由 Agent 节点维护，tool_calls/tool_results 在
    Agent↔Tools 循环中传递。

    Reducer 说明：
    - 累积型（add_list）：tool_results / actions / async_task_refs / facts_patch
      → 多轮 ReAct 循环中所有工具结果都保留，不被后续轮次覆盖
    - 末值型（last_non_empty）：reply / thinking
      → 保留最后的非空值，避免 agent_node 调用工具时 reply="" 清空已有回复
    - 覆盖型（无 reducer）：tool_calls / status / task_context
      → 每轮最新值覆盖旧值
    """

    # ===== 输入 =====
    user_id: int
    session_id: str
    attachments: list[dict]                     # 用户上传的附件

    # ===== 工作记忆（messages，自动累积） =====
    messages: Annotated[list, add_messages]     # 对话历史，LangGraph 自动管理

    # ===== 短期记忆（task_context，任务级语义） =====
    task_context: Optional[TaskContext]         # 当前任务上下文，任务完成置 None

    # ===== 长期记忆（user_facts，跨会话） =====
    user_facts: dict                            # 用户事实（公司/行业/常选平台/默认ID等）
    preferences: dict                           # 用户偏好

    # ===== ReAct 循环（工具调用） =====
    tool_calls: list[dict]                      # Agent 决定调用的工具列表（当前轮，覆盖语义）
    tool_results: Annotated[list[dict], add_list]  # 工具执行结果（累积，多轮不丢失）

    # ===== 异步任务追踪 =====
    async_task_refs: Annotated[list[dict], add_list]  # 本轮触发的异步任务引用（累积）

    # ===== 输出 =====
    reply: Annotated[str, last_non_empty]       # Agent 回复（保留最后非空值）
    actions: Annotated[list[Action], add_list]  # 前端按钮（累积）
    status: ExecutionStatus                     # 执行状态（覆盖语义）
    facts_patch: Annotated[list[dict], add_list]  # 待回写用户事实（累积）
    thinking: Annotated[str, last_non_empty]    # Agent 思考过程（保留最后非空值）


def make_initial_state(
    user_id: int,
    session_id: str,
    message: str,
    attachments: list[dict] | None = None,
) -> AgentState:
    """构造初始 AgentState。

    messages 初始包含用户本轮消息，后续由 LangGraph 通过 add_messages
    reducer 自动累积。历史消息由 load_context（graph 外预处理）从数据库
    加载后注入到 state["messages"]。
    """
    return AgentState(
        user_id=user_id,
        session_id=session_id,
        attachments=attachments or [],
        messages=[{"role": "user", "content": message}],
        task_context=None,
        user_facts={},
        preferences={},
        tool_calls=[],
        tool_results=[],
        async_task_refs=[],
        reply="",
        actions=[],
        status="completed",
        facts_patch=[],
        thinking="",
    )
