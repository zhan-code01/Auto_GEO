# -*- coding: utf-8 -*-
"""智能文章工具 - 2 个工具（对齐 PRD §8.3.3）。

- generate_questions: 生成用户问题（异步任务，等待 LLM 规划完成）
- list_questions: 查询问题列表

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.actions import make_action
from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


@register_tool("generate_questions")
async def generate_questions_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """生成用户问题。

    必填槽位：project_id
    可选槽位：question_count（默认 5）
    第三层防护：工具执行时再次检查必填字段，缺失则返回 need_clarification 引导用户补充。

    底层调 QuestionPoolAdapter.plan_batch_sync 异步等待 LLM 规划完成，
    返回 ToolOutcome.running 并附带 async_task_refs，前端可凭 query_tool 轮询结果。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import QuestionPoolAdapter

    project_id = slots.get("project_id")
    question_count = slots.get("question_count", 5)

    # 第二层防护：工具执行时校验必填
    if not project_id:
        return ToolOutcome.need_clarification(
            reply="请提供项目ID，以便为该项目生成问题",
            suggestion="可以先调用 list_projects 查看项目列表",
        )

    try:
        project_id_int = int(project_id)
    except (TypeError, ValueError):
        return ToolOutcome.need_clarification(
            reply=f"项目ID格式无效：{project_id}",
            suggestion="请提供数字格式的项目ID",
        )

    try:
        raw_count = int(question_count)
        if raw_count <= 0:
            raw_count = 5
    except (TypeError, ValueError):
        raw_count = 5
    from backend.services.smart_article.question_pool_service import MAX_QUESTION_COUNT

    count_clamped = raw_count > MAX_QUESTION_COUNT
    count_int = min(raw_count, MAX_QUESTION_COUNT)
    limit_note = (
        f"您请求生成 {raw_count} 个问题，超过单次上限 {MAX_QUESTION_COUNT} 个，"
        f"已按 {MAX_QUESTION_COUNT} 个生成。\n"
    ) if count_clamped else ""

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = QuestionPoolAdapter(db)
        batch_id, question_ids = await adapter.plan_batch_sync(
            user=fake_user,
            project_id=project_id_int,
            count=count_int,
        )
        logger.info(
            f"[generate_questions] project={project_id_int} "
            f"batch={batch_id} planned={len(question_ids)}"
        )

        # plan_batch_sync 内部已 await 完成 LLM 规划，问题已入库。
        # 直接取出问题详情，写入返回结果，让前端能看到真实生成的问题（而非占位语）。
        try:
            questions_raw = adapter.get_many_questions(fake_user, question_ids)
        except Exception as e:
            logger.warning(f"[generate_questions] 读取问题详情失败: {e}")
            questions_raw = []
        questions = [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "intent_type": q.get("intent_type"),
                "context_type": q.get("context_type"),
                "has_article": bool(q.get("has_article")),
            }
            for q in questions_raw
        ]

        # 直接把生成的问题展示给用户，而不是"正在规划中"的占位文案
        if questions:
            lines = [f"已为您生成 {len(questions)} 个问题："]
            for idx, q in enumerate(questions, 1):
                lines.append(f"{idx}. {q.get('question', '')}")
            reply_text = limit_note + "\n".join(lines)
        else:
            reply_text = f"{limit_note}已提交 {count_int} 个问题的生成任务，正在规划中……"

        return ToolOutcome.running(
            reply=reply_text,
            data={
                "project_id": project_id_int,
                "question_batch_id": batch_id,
                "question_ids": question_ids,
                "planned_count": len(question_ids),
                "questions": questions,
            },
            async_task_refs=[{
                "task_type": "question_generation",
                "task_id": batch_id,
                "query_tool": "list_questions",
            }],
            facts_patch=[{"default_project_id": project_id_int}],
        )
    except Exception as e:
        logger.error(f"[generate_questions] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="生成问题失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查项目ID是否正确",
        )
    finally:
        db.close()


@register_tool("list_questions")
async def list_questions_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询问题列表。

    可选槽位：project_id（缺失时查询所有项目的问题）
    可选槽位：has_article、generation_batch_id、page、limit
    空列表时返回 need_clarification，引导用户先创建项目或生成问题。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import QuestionPoolAdapter

    project_id = slots.get("project_id")
    has_article = slots.get("has_article")
    generation_batch_id = slots.get("generation_batch_id") or slots.get("question_batch_id")
    page = slots.get("page", 1)
    limit = slots.get("limit", 50)

    try:
        project_id_int = int(project_id) if project_id else None
    except (TypeError, ValueError):
        return ToolOutcome.need_clarification(
            reply=f"项目ID格式无效：{project_id}",
            suggestion="请提供数字格式的项目ID",
        )

    try:
        page_int = int(page)
        limit_int = int(limit)
    except (TypeError, ValueError):
        page_int, limit_int = 1, 50

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = QuestionPoolAdapter(db)
        result = adapter.list_questions(
            user=fake_user,
            project_id=project_id_int,
            has_article=has_article,
            generation_batch_id=generation_batch_id,
            page=page_int,
            limit=limit_int,
        )

        items = result.get("items", [])
        total = result.get("total", len(items))

        if not items:
            return ToolOutcome.need_clarification(
                reply="暂无问题记录，请先创建项目或生成问题",
                suggestion="可以调用 generate_questions 为项目生成问题",
            )

        # 补充项目名/客户名，便于前端按项目、按客户分组展示
        from backend.database.models import Client, Project

        project_ids = {q.get("project_id") for q in items if q.get("project_id")}
        project_map: dict[int, dict] = {}
        if project_ids:
            proj_rows = db.query(Project.id, Project.name, Project.client_id).filter(
                Project.id.in_(project_ids)
            ).all()
            client_ids = {p.client_id for p in proj_rows if p.client_id}
            client_map: dict[int, str] = {}
            if client_ids:
                client_rows = db.query(Client.id, Client.company_name).filter(
                    Client.id.in_(client_ids)
                ).all()
                client_map = {c.id: c.company_name for c in client_rows}
            project_map = {
                p.id: {"name": p.name, "client_name": client_map.get(p.client_id, "")}
                for p in proj_rows
            }

        items_simple = [
            {
                "id": q.get("id"),
                "project_id": q.get("project_id"),
                "question": q.get("question", ""),
                "project_name": project_map.get(q.get("project_id"), {}).get("name", ""),
                "client_name": project_map.get(q.get("project_id"), {}).get("client_name", ""),
                "has_article": bool(q.get("has_article")),
                "article_generation_status": q.get("article_generation_status"),
                "created_at": q.get("created_at"),
            }
            for q in items
        ]

        return ToolOutcome.success(
            data={"items": items_simple, "total": total},
            reply=f"共 {total} 个问题",
            actions=[make_action(
                "show_question_list",
                "查看问题列表",
                {
                    "project_id": project_id_int,
                    "items": items_simple,
                    "total": total,
                },
            )],
        )
    except Exception as e:
        logger.error(f"[list_questions] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询问题列表失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()
