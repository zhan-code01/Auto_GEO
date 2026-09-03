# -*- coding: utf-8 -*-
"""文章发布工具 - 2 个独立工具（对齐 PRD §8.3.5）。

- publish_article: 发布文章（单篇单平台）
- list_publish_records: 查询发布记录

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


# 发布状态映射：文本 <-> publish_status int（0=待发布 1=发布中 2=成功 3=失败）
_PUBLISH_STATUS_MAP: dict[str, int] = {
    "pending": 0,
    "running": 1,
    "success": 2,
    "failed": 3,
}
_PUBLISH_STATUS_LABELS: dict[int, str] = {
    0: "待发布",
    1: "发布中",
    2: "成功",
    3: "失败",
}


@register_tool("publish_article")
async def publish_article_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """发布文章到平台（单篇单平台，对应 PRD §8.3.5）。

    必填槽位：article_id / account_id
    第二层防护：工具执行时校验必填字段，缺失则返回 need_clarification 引导用户补充。
    文章发布在后台异步进行，工具立即返回 running 状态。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import PublishAdapter

    article_id = slots.get("article_id")
    account_id = slots.get("account_id")

    # 第二层防护：必填字段校验
    if not article_id:
        logger.info(f"[publish_article] 缺失 article_id user={user_id}")
        return ToolOutcome.need_clarification(
            reply="请提供要发布的文章",
            suggestion="可以先调用 list_articles 查看文章列表",
        )
    if not account_id:
        logger.info(f"[publish_article] 缺失 account_id user={user_id}")
        return ToolOutcome.need_clarification(
            reply="请提供要发布到的平台账号",
            suggestion="可以先调用 list_bindings 查看已绑定的平台账号",
        )

    # 安全转换为 int
    try:
        article_id_int = int(article_id)
    except (TypeError, ValueError):
        return ToolOutcome.need_clarification(
            reply=f"文章ID格式无效：{article_id}",
            suggestion="请提供数字格式的文章ID",
        )
    try:
        account_id_int = int(account_id)
    except (TypeError, ValueError):
        return ToolOutcome.need_clarification(
            reply=f"账号ID格式无效：{account_id}",
            suggestion="请提供数字格式的账号ID",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        publish_adapter = PublishAdapter(db)
        result = publish_adapter.publish_articles(
            fake_user, [article_id_int], [account_id_int],
        )
        task_id = result.get("task_id")
        logger.info(
            f"[publish_article] task={task_id} article={article_id_int} "
            f"account={account_id_int} user={user_id}"
        )

        return ToolOutcome.running(
            reply=(
                f"已提交发布任务，文章ID: {article_id_int}，账号ID: {account_id_int}。"
                f"完成后会通知您。"
            ),
            data={
                "task_id": task_id,
                "article_id": article_id_int,
                "account_id": account_id_int,
                "total_count": result.get("total_count"),
            },
            async_task_refs=[
                {
                    "task_type": "publish",
                    "task_id": task_id,
                    "query_tool": "list_publish_records",
                }
            ],
        )
    except Exception as e:
        logger.error(f"[publish_article] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="发布文章失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查文章与账号是否正确",
        )
    finally:
        db.close()


@register_tool("list_publish_records")
async def list_publish_records_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询发布记录（对应 PRD §8.3.5）。

    可选槽位：article_id / status（pending/running/success/failed）
    返回分页数据，前端渲染列表弹窗。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import PublishAdapter

    article_id = slots.get("article_id")
    status = slots.get("status")

    # article_id 安全转换
    article_id_int: int | None = None
    if article_id:
        try:
            article_id_int = int(article_id)
        except (TypeError, ValueError):
            return ToolOutcome.need_clarification(
                reply=f"文章ID格式无效：{article_id}",
                suggestion="请提供数字格式的文章ID",
            )

    # status 校验并映射为 publish_status int
    status_int: int | None = None
    if status:
        status_int = _PUBLISH_STATUS_MAP.get(status)
        if status_int is None:
            return ToolOutcome.need_clarification(
                reply=f"发布状态无效：{status}",
                suggestion="请使用 pending/running/success/failed 之一",
            )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = PublishAdapter(db)
        result = adapter.list_publish_records(
            fake_user, article_id=article_id_int,
        )
        items = result.get("items", [])

        # 按状态在内存中过滤（adapter 暂不支持 status 过滤）
        if status_int is not None:
            items = [r for r in items if r.get("publish_status") == status_int]

        if not items:
            return ToolOutcome.success(
                data={"items": [], "total": 0},
                reply="暂无发布记录",
            )

        list_items = [
            {
                "id": r.get("id"),
                "article_id": r.get("article_id"),
                "account_id": r.get("account_id"),
                "status": _PUBLISH_STATUS_LABELS.get(r.get("publish_status"), "未知"),
                "publish_status": r.get("publish_status"),
                "platform_url": r.get("platform_url"),
                "error_msg": r.get("error_msg"),
                "created_at": r.get("created_at"),
                "published_at": r.get("published_at"),
            }
            for r in items[:20]
        ]
        total = len(list_items)

        return ToolOutcome.success(
            data={"items": list_items, "total": total},
            reply=f"共 {total} 条发布记录",
        )
    except Exception as e:
        logger.error(f"[list_publish_records] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询发布记录失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()
