# -*- coding: utf-8 -*-
"""项目管理工具 - 3 个独立工具（对齐 PRD §8.3.2）。

- create_project: 创建项目
- list_projects: 查询项目列表
- get_project_detail: 查询项目详情

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.actions import make_action
from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


@register_tool("create_project")
async def create_project_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """创建项目。

    必填槽位（由 Pydantic CreateProjectInput 校验）：name（项目名称）、client_id（关联客户）、domain_keyword（领域关键词）
    第二层防护：工具执行时再次检查必填字段，缺失则返回 need_clarification 引导用户补充。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import ProjectAdapter

    name = slots.get("name") or slots.get("project_name")
    client_id = slots.get("client_id")
    domain_keyword = slots.get("domain_keyword")

    # 第二层防护：工具执行时校验必填
    missing = []
    if not name:
        missing.append("项目名称")
    if not client_id:
        missing.append("关联客户")
    if not domain_keyword:
        missing.append("领域关键词")

    if missing:
        return ToolOutcome.need_clarification(
            reply=f"创建项目还需要以下信息：{', '.join(missing)}",
            suggestion="请补充缺失的信息，我会为您创建项目",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = ProjectAdapter(db)
        data = {
            "name": name,
            "client_id": client_id,
            "company_name": slots.get("company_name"),
            "domain_keyword": slots.get("domain_keyword"),
            "description": slots.get("description"),
            "industry": slots.get("industry"),
        }
        project = adapter.create_project(fake_user, data)
        project_id = project["id"]
        project_name = project["name"]
        logger.info(f"[create_project] 创建项目: id={project_id} name={project_name}")

        return ToolOutcome.success(
            data={"project_id": project_id, "project_name": project_name},
            reply=(
                f"项目【{project_name}】创建成功！"
                f"接下来您可以上传客户资料（提升问题生成质量），或直接生成用户问题（默认生成 1 个）。"
            ),
            facts_patch=[{
                "project_name": project_name,
                "default_project_id": project_id,
                "default_client_id": client_id,
            }],
        )
    except Exception as e:
        logger.error(f"[create_project] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="创建项目失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查关联客户是否存在",
        )
    finally:
        db.close()


@register_tool("list_projects")
async def list_projects_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询项目列表。返回分页数据，前端渲染列表弹窗。"""
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import ProjectAdapter

    client_id = slots.get("client_id")
    keyword = slots.get("keyword") or slots.get("project_hint") or slots.get("name")
    fake_user = SimpleNamespace(id=user_id, role="user")

    db = SessionLocal()
    try:
        adapter = ProjectAdapter(db)
        result = adapter.list_projects(fake_user, client_id=client_id, keyword=keyword)

        if not result["items"]:
            return ToolOutcome.success(
                data=result,
                reply="您还没有项目。可以让我为您新建项目。",
            )

        items = [
            {
                "id": p["id"],
                "name": p["name"],
                "client_id": p.get("client_id"),
                "company_name": p.get("company_name", ""),
                "industry": p.get("industry", ""),
            }
            for p in result["items"][:20]
        ]

        return ToolOutcome.success(
            data={"items": items, "total": result["total"]},
            reply=f"共 {result['total']} 个项目",
            actions=[make_action(
                "show_project_list",
                "查看项目列表",
                {"items": items, "total": result["total"]},
            )],
        )
    except Exception as e:
        logger.error(f"[list_projects] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询项目列表失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()


@register_tool("get_project_detail")
async def get_project_detail_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询项目详情。必填：project_id。"""
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import ProjectAdapter

    project_id = slots.get("project_id")
    if not project_id:
        return ToolOutcome.need_clarification(
            reply="请提供项目ID或项目名称",
            suggestion="可以先调用 list_projects 查看项目列表",
        )

    try:
        project_id_int = int(project_id)
    except (TypeError, ValueError):
        return ToolOutcome.need_clarification(
            reply=f"项目ID格式无效：{project_id}",
            suggestion="请提供数字格式的项目ID",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = ProjectAdapter(db)
        project = adapter.get_project(fake_user, project_id_int)

        if not project:
            return ToolOutcome.failure(
                reply=f"项目 {project_id} 不存在",
                error_type="not_found",
                suggestion="请检查项目ID，或调用 list_projects 查看项目列表",
            )

        return ToolOutcome.success(
            data=project,
            reply=(
                f"项目详情：{project['name']}，"
                f"行业：{project.get('industry', '')}，"
                f"公司：{project.get('company_name') or ''}"
            ),
        )
    except Exception as e:
        logger.error(f"[get_project_detail] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询项目详情失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()
