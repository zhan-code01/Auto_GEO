# -*- coding: utf-8 -*-
"""Agent V2 工具层。

工具按工具名注册，LLM 通过 LangChain `bind_tools` 机制基于 tool_schemas.py 的
Pydantic schema 自动生成结构化调用。

导入本包即触发所有工具的注册。严格对齐 PRD §8.4 共 18 个工具。
"""

# 导入所有工具模块以触发 @register_tool 装饰器注册
from backend.services.agent_v2.tools import (  # noqa: F401
    account_tools,
    article_tools,
    client_tools,
    geo_evaluation_tools,
    knowledge_tools,
    project_tools,
    publish_tools,
    question_tools,
)
from backend.services.agent_v2.tools.base import (
    ToolOutcome,
    execute_tool,
    get_tool,
    list_tools,
    register_tool,
    VALID_TOOLS,
)
from backend.services.agent_v2.tools.tool_schemas import (
    TOOL_SCHEMAS,
    build_langchain_tools,
    build_tool_definitions,
    get_tool_schema,
)

__all__ = [
    "ToolOutcome",
    "register_tool",
    "get_tool",
    "list_tools",
    "execute_tool",
    "VALID_TOOLS",
    "TOOL_SCHEMAS",
    "build_tool_definitions",
    "build_langchain_tools",
    "get_tool_schema",
]
