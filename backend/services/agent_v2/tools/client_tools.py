# -*- coding: utf-8 -*-
"""客户管理工具 - 3 个独立工具（对齐 PRD §8.3.1）。

- create_client: 创建客户
- list_clients: 查询客户列表
- get_client_detail: 查询客户详情

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.actions import make_action
from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


@register_tool("create_client")
async def create_client_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """创建客户。

    必填槽位（由 Pydantic CreateClientInput 校验）：company_name/industry/location/website
    第三层防护：工具执行时再次检查必填字段，缺失则返回 need_clarification 引导用户补充。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import ClientAdapter

    company_name = slots.get("company_name")
    industry = slots.get("industry")
    location = slots.get("location")
    website = slots.get("website")

    # 第二层防护：工具执行时校验必填
    missing = []
    if not company_name:
        missing.append("公司名称")
    if not industry:
        missing.append("所属行业")
    if not location:
        missing.append("所在地")
    if not website:
        missing.append("公司官网")

    if missing:
        return ToolOutcome.need_clarification(
            reply=f"创建客户还需要以下信息：{', '.join(missing)}",
            suggestion="请补充缺失的信息，我会为您创建客户",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = ClientAdapter(db)
        data = {
            "name": company_name,
            "company_name": company_name,
            "industry": industry,
            "location": location,
            "website": website,
        }
        client = adapter.create_client(fake_user, data)
        logger.info(f"[create_client] 创建客户: id={client['id']} company={company_name}")

        return ToolOutcome.success(
            data={"client_id": client["id"], "company_name": client["company_name"]},
            reply=f"客户【{client['company_name']}】创建成功！",
            facts_patch=[
                {
                    "company_name": client["company_name"],
                    "industry": industry,
                    "default_client_id": client["id"],
                }
            ],
        )
    except Exception as e:
        logger.error(f"[create_client] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="创建客户失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查公司名称是否重复",
        )
    finally:
        db.close()


@register_tool("list_clients")
async def list_clients_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询客户列表。返回分页数据，前端渲染列表弹窗。"""
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import ClientAdapter

    keyword = slots.get("keyword")
    fake_user = SimpleNamespace(id=user_id, role="user")

    db = SessionLocal()
    try:
        adapter = ClientAdapter(db)
        result = adapter.list_clients(fake_user, keyword=keyword)

        if not result["items"]:
            return ToolOutcome.success(
                data=result,
                reply="您还没有客户。可以让我为您新建客户。",
            )

        items = [
            {
                "id": c["id"],
                "company_name": c["company_name"],
                "industry": c.get("industry", ""),
                "location": c.get("location", ""),
            }
            for c in result["items"][:20]
        ]

        return ToolOutcome.success(
            data={"items": items, "total": result["total"]},
            reply=f"共 {result['total']} 个客户",
            actions=[
                make_action(
                    "show_client_list",
                    "查看客户列表",
                    {"items": items, "total": result["total"]},
                )
            ],
        )
    except Exception as e:
        logger.error(f"[list_clients] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询客户列表失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()


@register_tool("get_client_detail")
async def get_client_detail_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询客户详情。必填：client_id。"""
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import ClientAdapter

    client_id = slots.get("client_id")
    if not client_id:
        return ToolOutcome.need_clarification(
            reply="请提供客户ID或客户名称",
            suggestion="可以先调用 list_clients 查看客户列表",
        )

    try:
        client_id_int = int(client_id)
    except (TypeError, ValueError):
        return ToolOutcome.need_clarification(
            reply=f"客户ID格式无效：{client_id}",
            suggestion="请提供数字格式的客户ID",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = ClientAdapter(db)
        client = adapter.get_client(fake_user, client_id_int)

        if not client:
            return ToolOutcome.failure(
                reply=f"客户 {client_id} 不存在",
                error_type="not_found",
                suggestion="请检查客户ID，或调用 list_clients 查看客户列表",
            )

        return ToolOutcome.success(
            data=client,
            reply=(
                f"客户详情：{client['company_name']}，"
                f"行业：{client.get('industry', '')}，"
                f"所在地：{client.get('location', '')}"
            ),
        )
    except Exception as e:
        logger.error(f"[get_client_detail] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询客户详情失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()
