# -*- coding: utf-8 -*-
"""工具基类与注册器。

对应 PRD §8 工具系统。采用 LangChain 标准 @tool 装饰器 + Pydantic args_schema，
让 LLM 能基于工具 schema 自动生成结构化调用。

工具清单（18 个，严格对齐 PRD §8.4）：
- 客户管理 3：create_client, list_clients, get_client_detail
- 项目管理 3：create_project, list_projects, get_project_detail
- 智能文章 4：generate_questions, list_questions, generate_articles, list_articles
- 账户绑定 2：bind_platform, list_bindings
- 文章发布 2：publish_article, list_publish_records
- 收录监控 3：create_baseline, run_recheck, get_diagnosis
- 资料管理 1：upload_documents
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from loguru import logger


class ToolOutcome:
    """工具执行结果。

    统一工具返回格式，对应 PRD §8.6：
    - 成功：{data, reply, actions, status="completed"}
    - 失败：{reply, error_type, suggestion, status="failed"}
    - 前置不满足：{reply, suggestion, actions, status="need_clarification"}
    - 异步任务：{reply, async_task_refs, status="running"}
    """

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        reply: str = "",
        actions: list[dict] | None = None,
        status: str = "completed",
        error_type: str | None = None,
        suggestion: str | None = None,
        facts_patch: list[dict] | None = None,
        async_task_refs: list[dict] | None = None,
    ):
        self.data = data or {}
        self.reply = reply
        self.actions = actions or []
        self.status = status
        self.error_type = error_type
        self.suggestion = suggestion
        self.facts_patch = facts_patch or []
        self.async_task_refs = async_task_refs or []

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "data": self.data,
            "reply": self.reply,
            "actions": self.actions,
            "status": self.status,
            "facts_patch": self.facts_patch,
            "async_task_refs": self.async_task_refs,
        }
        if self.error_type:
            result["error_type"] = self.error_type
        if self.suggestion:
            result["suggestion"] = self.suggestion
        return result

    @classmethod
    def success(
        cls,
        data: dict | None = None,
        reply: str = "",
        actions: list | None = None,
        **kwargs,
    ) -> "ToolOutcome":
        return cls(data=data, reply=reply, actions=actions, status="completed", **kwargs)

    @classmethod
    def failure(
        cls,
        reply: str,
        error_type: str = "execution_error",
        suggestion: str | None = None,
        **kwargs,
    ) -> "ToolOutcome":
        return cls(
            reply=reply,
            status="failed",
            error_type=error_type,
            suggestion=suggestion,
            **kwargs,
        )

    @classmethod
    def need_clarification(
        cls,
        reply: str,
        suggestion: str | None = None,
        actions: list | None = None,
        **kwargs,
    ) -> "ToolOutcome":
        return cls(
            reply=reply,
            status="need_clarification",
            suggestion=suggestion,
            actions=actions,
            **kwargs,
        )

    @classmethod
    def running(cls, reply: str = "", **kwargs) -> "ToolOutcome":
        return cls(reply=reply, status="running", **kwargs)


# 工具注册表：tool_name -> handler（handler 接收 slots dict + user_id）
_TOOL_REGISTRY: dict[str, Callable[..., Awaitable[ToolOutcome]]] = {}


def register_tool(name: str):
    """装饰器：按工具名注册 handler。

    handler 签名：async def fn(slots: dict[str, Any], user_id: int) -> ToolOutcome
    """
    def decorator(fn: Callable[..., Awaitable[ToolOutcome]]):
        _TOOL_REGISTRY[name] = fn
        return fn
    return decorator


def get_tool(name: str) -> Callable[..., Awaitable[ToolOutcome]] | None:
    return _TOOL_REGISTRY.get(name)


def list_tools() -> list[str]:
    """列出所有已注册工具名。"""
    return list(_TOOL_REGISTRY.keys())


# 18 个合法工具名清单（严格对齐 PRD §8.4）
VALID_TOOLS: set[str] = {
    # 客户管理
    "create_client", "list_clients", "get_client_detail",
    # 项目管理
    "create_project", "list_projects", "get_project_detail",
    # 智能文章
    "generate_questions", "list_questions", "generate_articles", "list_articles",
    # 账户绑定
    "bind_platform", "list_bindings",
    # 文章发布
    "publish_article", "list_publish_records",
    # 收录监控
    "create_baseline", "run_recheck", "get_diagnosis",
    # 资料管理
    "upload_documents",
}


async def execute_tool(name: str, slots: dict[str, Any], user_id: int) -> dict[str, Any]:
    """按工具名执行工具。

    Args:
        name: 工具名（必须在 VALID_TOOLS 中）
        slots: 工具参数（由 LLM 通过 Tool Calling 生成）
        user_id: 当前用户 ID

    Returns:
        工具执行结果 dict（含 data/reply/actions/status 等字段）
    """
    if name not in VALID_TOOLS:
        logger.warning(f"[execute_tool] 未授权工具：{name}")
        return ToolOutcome.failure(
            reply=f"未授权的工具：{name}",
            error_type="invalid_tool",
            suggestion="请使用合法的 18 个工具之一",
        ).to_dict()

    handler = get_tool(name)
    if not handler:
        return ToolOutcome.failure(
            reply=f"工具 {name} 未实现",
            error_type="tool_not_implemented",
            suggestion=f"请检查工具 {name} 是否已注册",
        ).to_dict()

    try:
        outcome = await handler(slots=slots, user_id=user_id)
        return outcome.to_dict()
    except Exception as e:
        logger.error(f"[execute_tool] 工具 {name} 执行异常: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="工具执行失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查参数是否正确",
        ).to_dict()
