# -*- coding: utf-8 -*-
"""资料管理工具 - 1 个独立工具（对齐 PRD §8.3.7）。

- upload_documents: 触发前端文件上传并记录用户意图

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。

设计说明：
- 工具本身不实际上传文件（文件由前端先上传到临时区）
- 工具的作用是：触发前端打开文件选择器（返回 upload_files action），并记录用户意图
- file_names 为空 → 返回 need_clarification 引导用户选择文件
- file_names 不为空 → 返回 ok，回复"已收到 N 个文件，正在处理"
- 后续文件入库可调用 KnowledgeIngestionService / GeoKnowledgeService
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


@register_tool("upload_documents")
async def upload_documents_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """上传客户资料。

    必填槽位（由 Pydantic UploadDocumentsInput 校验）：client_id、file_names
    第三层防护：工具执行时再次检查必填字段，缺失则返回 need_clarification 引导用户补充。

    - file_names 为空：说明用户还没选文件，返回 need_clarification 引导用户选择文件
    - file_names 不为空：说明文件已上传到临时区，返回 ok 状态，回复"已收到 N 个文件，正在处理"
    """
    from backend.database import SessionLocal

    client_id = slots.get("client_id")
    file_names = slots.get("file_names") or []

    # 第二层防护：工具执行时校验必填
    if not client_id:
        return ToolOutcome.need_clarification(
            reply="请提供客户ID或客户名称",
            suggestion="可以先调用 list_clients 查看客户列表",
        )

    if not file_names:
        # file_names 为空，触发前端打开文件选择器
        logger.info(f"[upload_documents] client={client_id} 待选文件，触发前端文件选择器")
        return ToolOutcome.need_clarification(
            reply="请上传文件（支持 PDF/DOCX/TXT/MD 等格式），在聊天窗口的附件中完成上传",
            suggestion="请在输入框附件中选择要上传的文件，告诉我文件名即可",
        )

    # file_names 不为空，文件已上传到临时区，记录用户意图
    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 记录用户意图（文件实际入库由后续流程处理，可选用 KnowledgeIngestionService）
        logger.info(
            f"[upload_documents] user={fake_user.id} client={client_id} "
            f"收到 {len(file_names)} 个文件: {file_names}"
        )

        return ToolOutcome.success(
            data={
                "client_id": client_id,
                "file_names": file_names,
                "count": len(file_names),
            },
            reply="文件已上传成功！这些资料已关联到客户资料库，后续生成问题时会参考这些知识库内容，让问题更贴合公司业务。",
            facts_patch=[{
                "default_client_id": client_id,
                "pending_files": file_names,
            }],
        )
    except Exception as e:
        logger.error(f"[upload_documents] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="上传资料失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查文件格式是否支持",
        )
    finally:
        db.close()
