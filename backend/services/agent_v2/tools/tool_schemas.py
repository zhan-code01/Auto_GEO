# -*- coding: utf-8 -*-
"""工具 Schema 定义 - Pydantic args_schema + docstring。

对应 PRD §8.2。每个工具的 args_schema 作为 Pydantic BaseModel，
LLM 通过 Tool Calling 机制基于 schema 自动生成结构化参数。

工具清单（18 个）：
- 客户管理 3：create_client, list_clients, get_client_detail
- 项目管理 3：create_project, list_projects, get_project_detail
- 智能文章 4：generate_questions, list_questions, generate_articles, list_articles
- 账户绑定 2：bind_platform, list_bindings
- 文章发布 2：publish_article, list_publish_records
- 收录监控 3：create_baseline, run_recheck, get_diagnosis
- 资料管理 1：upload_documents
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.config import AI_PLATFORMS, PLATFORMS


def _platform_options_text() -> str:
    """生成可发布平台的中文名列表（用于 LLM tool schema）。

    只展示中文名（如「抖音」），不展示英文 ID，界面更干净；
    LLM 传中文名时由 resolve_platform 解析回平台 ID。
    排除 AI 鉴权专用平台（doubao/qianwen/deepseek，仅用于 GEO 评测）
    和自定义占位平台。
    """
    excluded = {*AI_PLATFORMS.keys(), "custom"}
    seen: dict[str, None] = {}
    for pid, info in PLATFORMS.items():
        if pid in excluded:
            continue
        name = info.get("name") or pid
        if name not in seen:
            seen[name] = None
    return "、".join(seen.keys())


def _ai_platform_options_text() -> str:
    """生成 AI 监测平台的中文名列表（用于 LLM tool schema）。"""
    return "、".join(info.get("name") or pid for pid, info in AI_PLATFORMS.items())


# ====================================================================
#  客户管理（3 个）
# ====================================================================

class CreateClientInput(BaseModel):
    """创建客户的输入参数。"""

    company_name: str = Field(description="公司名称，必填")
    industry: str = Field(description="所属行业，必填，如：云计算、电商、教育")
    location: str = Field(description="公司所在地，必填，如：杭州、北京")
    website: str = Field(description="公司官网，必填，如：www.aliyun.com")


class ListClientsInput(BaseModel):
    """查询客户列表的输入参数。"""

    keyword: Optional[str] = Field(
        default=None, description="客户名称关键词（可选，用于模糊搜索）"
    )


class GetClientDetailInput(BaseModel):
    """查询客户详情的输入参数。"""

    client_id: int = Field(description="客户ID，必填")


# ====================================================================
#  项目管理（3 个）
# ====================================================================

class CreateProjectInput(BaseModel):
    """创建项目的输入参数。"""

    client_id: int = Field(description="所属客户ID，必填")
    name: str = Field(description="项目名称，必填")
    domain_keyword: str = Field(description="领域关键词，用于AI蒸馏生成用户提问句，必填")
    description: Optional[str] = Field(default=None, description="项目描述（可选）")


class ListProjectsInput(BaseModel):
    """查询项目列表的输入参数。"""

    client_id: Optional[int] = Field(
        default=None, description="按客户ID筛选（可选）"
    )
    keyword: Optional[str] = Field(
        default=None, description="项目名称关键词（可选）"
    )


class GetProjectDetailInput(BaseModel):
    """查询项目详情的输入参数。"""

    project_id: int = Field(description="项目ID，必填")


# ====================================================================
#  智能文章（4 个）
# ====================================================================

class GenerateQuestionsInput(BaseModel):
    """生成用户问题的输入参数。"""

    project_id: int = Field(description="项目ID，必填")
    question_count: int = Field(
        default=5, ge=1, le=30, description="生成问题数量，默认5，单次最多30"
    )


class ListQuestionsInput(BaseModel):
    """查询问题列表的输入参数。"""

    project_id: Optional[int] = Field(
        default=None, description="按项目ID筛选（可选）"
    )


class GenerateArticlesInput(BaseModel):
    """生成文章的输入参数（唯一入口）。

    支持两种模式：
    1. 指定 question_ids：从选定问题生成文章
    2. 指定 project_id + count：全自动规划问题并生成文章
    """

    project_id: int = Field(description="项目ID，必填")
    question_ids: Optional[list[int]] = Field(
        default=None,
        description="指定问题ID列表（可选，若提供则从指定问题生成）",
    )
    count: int = Field(default=5, ge=1, description="生成文章数量，默认5")


class ListArticlesInput(BaseModel):
    """查询文章列表的输入参数。"""

    project_id: Optional[int] = Field(
        default=None, description="按项目ID筛选（可选）"
    )
    keyword: Optional[str] = Field(
        default=None, description="文章标题关键词（可选）"
    )


# ====================================================================
#  账户绑定（2 个）
# ====================================================================

class BindPlatformInput(BaseModel):
    """绑定平台账户的输入参数。"""

    platform: str = Field(
        description=(
            f"平台标识，必填。可选值：{_platform_options_text()}；"
            "也接受中文平台名或常见别名（如「抖音」「B站」「头条号」）"
        )
    )


class ListBindingsInput(BaseModel):
    """查询已绑定账户的输入参数。"""

    platform: Optional[str] = Field(
        default=None, description="按平台筛选（可选）"
    )


# ====================================================================
#  文章发布（2 个）
# ====================================================================

class PublishArticleInput(BaseModel):
    """发布文章的输入参数（单篇单平台）。"""

    article_id: int = Field(description="文章ID，必填")
    account_id: int = Field(description="目标账号ID，必填")


class ListPublishRecordsInput(BaseModel):
    """查询发布记录的输入参数。"""

    article_id: Optional[int] = Field(
        default=None, description="按文章ID筛选（可选）"
    )
    status: Optional[str] = Field(
        default=None, description="按状态筛选（可选）：pending/running/success/failed"
    )


# ====================================================================
#  收录监控（3 个）
# ====================================================================

class CreateBaselineInput(BaseModel):
    """创建基线的输入参数（使用前）。

    注意：底层 GeoEvaluationRunService.create_baseline 强制每次只能选 1 个 AI 平台，
    所以这里用 ai_platform 单值字段，而非 list。
    """

    client_id: int = Field(description="客户ID，必填")
    ai_platform: str = Field(
        description=(
            f"要监测的 AI 平台（单选），必填。可选值：{_ai_platform_options_text()}"
        )
    )
    account_id: Optional[int] = Field(
        default=None,
        description="AI 平台账号ID（可选，未提供时自动从用户绑定的同平台账号中解析）",
    )


class RunRecheckInput(BaseModel):
    """执行复测的输入参数（使用后）。

    注意：底层 GeoEvaluationRunService.create_recheck 强制每次只能选 1 个 AI 平台。
    """

    client_id: int = Field(description="客户ID，必填")
    ai_platform: str = Field(
        description=(
            f"要监测的 AI 平台（单选），必填。可选值：{_ai_platform_options_text()}"
        )
    )
    account_id: Optional[int] = Field(
        default=None,
        description="AI 平台账号ID（可选，未提供时自动从用户绑定的同平台账号中解析）",
    )


class GetDiagnosisInput(BaseModel):
    """获取诊断指标的输入参数。"""

    client_id: int = Field(description="客户ID，必填")


# ====================================================================
#  资料管理（1 个）
# ====================================================================

class UploadDocumentsInput(BaseModel):
    """上传资料的输入参数。"""

    client_id: int = Field(description="客户ID，必填")
    file_names: list[str] = Field(
        description="已上传文件名列表（前端先上传到临时区，这里接收文件名）"
    )


# ====================================================================
#  工具 Schema 注册表（供 LLM Tool Calling 使用）
# ====================================================================

# 工具名 -> (args_schema, docstring)
TOOL_SCHEMAS: dict[str, tuple[type[BaseModel], str]] = {
    # 客户管理
    "create_client": (
        CreateClientInput,
        "创建客户。当用户想新建客户时调用。必填：company_name/industry/location/website。"
        "前置条件：无。若用户信息不全，先追问补全再调用。",
    ),
    "list_clients": (
        ListClientsInput,
        "查询客户列表。当用户想查看客户/我的客户/列出客户时调用。返回分页数据。",
    ),
    "get_client_detail": (
        GetClientDetailInput,
        "查询客户详情。当用户想查看某个客户的具体信息时调用。必填：client_id。",
    ),
    # 项目管理
    "create_project": (
        CreateProjectInput,
        "创建项目。当用户想新建项目时调用。必填：client_id/name/domain_keyword。"
        "前置条件：客户必须已存在。若缺 client_id，先调用 list_clients 查询。"
        "若缺 domain_keyword，向用户询问该项目的领域关键词（用于AI蒸馏生成用户提问句）。",
    ),
    "list_projects": (
        ListProjectsInput,
        "查询项目列表。当用户想查看项目/我的项目时调用。可按 client_id 筛选。",
    ),
    "get_project_detail": (
        GetProjectDetailInput,
        "查询项目详情。当用户想查看某个项目信息时调用。必填：project_id。",
    ),
    # 智能文章
    "generate_questions": (
        GenerateQuestionsInput,
        "生成用户问题。当用户想规划问题/生成问题时调用。必填：project_id。"
        "前置条件：项目必须已存在，且建议先上传客户资料以提升问题质量。",
    ),
    "list_questions": (
        ListQuestionsInput,
        "查询问题列表。当用户想查看问题/生成的问题有哪些时调用。可按 project_id 筛选。",
    ),
    "generate_articles": (
        GenerateArticlesInput,
        "智能文章生成（唯一入口）。当用户想生成文章/写文章时调用。"
        "支持两种模式：1) 指定 question_ids 从选定问题生成；2) 指定 project_id+count 全自动生成。"
        "前置条件：必须先有项目，且项目下有未生成文章的问题。"
        "若问题不足，先调用 generate_questions。",
    ),
    "list_articles": (
        ListArticlesInput,
        "查询文章列表。当用户想查看文章/我的文章时调用。可按 project_id 筛选。",
    ),
    # 账户绑定
    "bind_platform": (
        BindPlatformInput,
        "绑定平台账户/登录平台。当用户想绑定/登录/授权某平台时调用。必填：platform。"
        "调用后会返回 open_browser_auth 动作，由前端打开浏览器登录窗口。",
    ),
    "list_bindings": (
        ListBindingsInput,
        "查询已绑定的平台账户。当用户想看绑了哪些平台/绑定的账号时调用。",
    ),
    # 文章发布
    "publish_article": (
        PublishArticleInput,
        "发布文章到平台（单篇单平台）。当用户想发布文章/把文章发到某平台时调用。"
        "必填：article_id/account_id。"
        "前置条件：文章必须已生成，目标平台必须已绑定。已发布过的文章也可以再次发布。"
        "若缺 article_id 先调用 list_articles；若缺 account_id 先调用 list_bindings。",
    ),
    "list_publish_records": (
        ListPublishRecordsInput,
        "查询发布记录/发布历史。当用户想查看发布情况时调用。",
    ),
    # 收录监控
    "create_baseline": (
        CreateBaselineInput,
        "创建收录基线（使用前）。当用户想监控收录/创建基线/使用前基线时调用。"
        "必填：client_id/ai_platform（单选）。可选：account_id。"
        "核心逻辑：用项目中的用户问题去 AI 平台提问，分析回答，计算 4 个核心指标。"
        "调用后会返回 select_ai_platform 动作让用户选择 AI 平台。",
    ),
    "run_recheck": (
        RunRecheckInput,
        "执行收录复测（使用后）。当用户想复测/重新检测收录时调用。"
        "必填：client_id/ai_platform（单选）。可选：account_id。"
        "前置条件：必须先有基线。",
    ),
    "get_diagnosis": (
        GetDiagnosisInput,
        "获取收录诊断指标。当用户想看诊断/收录数据/指标时调用。"
        "必填：client_id。返回 4 个核心指标：keyword_hit_rate/company_hit_rate/"
        "avg_confidence/platform_count，并对比基线变化。",
    ),
    # 资料管理
    "upload_documents": (
        UploadDocumentsInput,
        "上传客户资料/文档。当用户想上传资料/传文档/上传知识库时调用。"
        "必填：client_id/file_names。调用后会返回 upload_files 动作让前端打开文件选择器。",
    ),
}


def get_tool_schema(tool_name: str) -> tuple[type[BaseModel], str] | None:
    """获取工具的 args_schema 和 docstring。"""
    return TOOL_SCHEMAS.get(tool_name)


def build_tool_definitions() -> list[dict]:
    """构建所有工具的 OpenAI function calling 定义。

    供 LLM 通过 Tool Calling 机制调用。
    """
    import json

    definitions: list[dict] = []
    for name, (schema_cls, doc) in TOOL_SCHEMAS.items():
        # Pydantic v2 的 schema 生成
        schema_dict = schema_cls.model_json_schema()
        definitions.append({
            "name": name,
            "description": doc,
            "parameters": {
                "type": "object",
                "properties": schema_dict.get("properties", {}),
                "required": schema_dict.get("required", []),
            },
        })
    return definitions


def build_langchain_tools() -> list:
    """构建 LangChain StructuredTool 列表，供 `llm.bind_tools(tools)` 使用。

    每个工具用 Pydantic args_schema 描述参数，工具实际执行由 tools_node
    调用 `execute_tool(name, args, user_id)` 完成（不在 LLM 推理时执行）。
    这里返回的 StructuredTool 仅用于让 LLM 看到结构化的 tool schema，
    通过原生 Tool Calling 机制输出 `tool_calls`。

    对应 PRD §4.4 ReAct Agent 节点的 LLM 调用方式。
    """
    from langchain_core.tools import StructuredTool

    def _make_placeholder(tool_name: str):
        """工厂函数，避免闭包变量捕获问题。"""
        async def _placeholder(**kwargs):
            return f"Tool {tool_name} should be executed by tools_node"
        return _placeholder

    tools: list[StructuredTool] = []
    for name, (schema_cls, doc) in TOOL_SCHEMAS.items():
        tool = StructuredTool.from_function(
            coroutine=_make_placeholder(name),
            name=name,
            description=doc,
            args_schema=schema_cls,
        )
        tools.append(tool)
    return tools
