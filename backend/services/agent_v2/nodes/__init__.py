# -*- coding: utf-8 -*-
"""Agent V2 节点 - ReAct Agent 架构。

对应 PRD §4.4 ReAct 循环：
- agent_node: LLM 推理 + Tool Calling 决策
- tools_node: 执行 tool_calls，回写 ToolMessage

graph 外辅助函数（在 graph.ainvoke 前后调用）：
- load_context: 加载历史消息 + user_facts + task_context
- persist_mem: 保存对话历史 + facts_patch + task_context
"""

from backend.services.agent_v2.nodes.agent_node import agent_node
from backend.services.agent_v2.nodes.load_context import load_context
from backend.services.agent_v2.nodes.persist_mem import persist_mem
from backend.services.agent_v2.nodes.tools_node import tools_node

__all__ = [
    "agent_node",
    "tools_node",
    "load_context",
    "persist_mem",
]
