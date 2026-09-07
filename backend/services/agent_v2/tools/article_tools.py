# -*- coding: utf-8 -*-
"""智能文章工具 - 2 个独立工具（对齐 PRD §8.3.3）。

- list_articles: 查询文章列表
- generate_articles: 生成文章（唯一入口，支持两种模式）

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。

注：原 article_tools 中的 get_article / delete_article / get_article_batch_status /
retry_article_job 不在 PRD §8.4 的 18 工具清单内，已移除。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.actions import make_action
from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


# 文章发布状态中文标签（与 GeoArticle.publish_status 枚举对应）
_STATUS_LABELS = {
    "draft": "草稿",
    "generating": "生成中",
    "completed": "未发布",
    "scheduled": "已排期",
    "publishing": "发布中",
    "published": "发布成功",
    "failed": "发布失败",
}


def _build_grouped_article_reply(
    items: list[dict],
    project_map: dict[int, str],
    max_per_project: int = 2,
) -> str:
    """按项目分组格式化文章列表，用于发布选择场景。

    格式示例：
        项目A：1、《文章标题1》（待发布） 2、《文章标题2》（已发布）
        项目B：1、《文章标题3》（发布失败）
        项目C：无
    """
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        pid = item.get("project_id")
        pname = item.get("project_name") or project_map.get(pid) or "未分类项目"
        groups[pname].append(item)

    lines: list[str] = []
    for pname in sorted(groups.keys()):
        articles = groups[pname]
        displayed = articles[:max_per_project]
        if not displayed:
            lines.append(f"{pname}：无")
            continue

        parts = [f"{pname}："]
        for idx, article in enumerate(displayed, 1):
            title = article.get("title") or "（无标题）"
            status = article.get("publish_status_label") or "待发布"
            parts.append(f"{idx}、{title}（{status}）")

        if len(articles) > max_per_project:
            parts.append(f"...还有 {len(articles) - max_per_project} 篇")

        lines.append(" ".join(parts))

    return "\n".join(lines) if lines else "暂无可选文章。"


@register_tool("list_articles")
async def list_articles_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询文章列表。返回分页数据，前端渲染列表弹窗（支持分页/项目筛选/去发布按钮）。

    可选槽位：project_id / keyword / publish_status / page / limit
    """
    from backend.database import SessionLocal
    from backend.database.models import GeoArticle, Project
    from backend.middleware.user_isolation import scoped_query
    from backend.services.agent_v2.adapters import ArticleAdapter, ProjectAdapter

    project_id = slots.get("project_id")
    keyword = slots.get("keyword") or slots.get("article_hint")
    publish_status = slots.get("publish_status")
    page = int(slots.get("page") or 1)
    limit = int(slots.get("limit") or 10)

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 1. 查询用户下所有项目（用于弹窗左侧筛选下拉框）
        project_adapter = ProjectAdapter(db)
        project_list_raw = project_adapter.list_projects(fake_user)
        # 注意：list_projects 返回的是 {"total": ..., "items": [...]}
        project_items = project_list_raw.get("items", []) if isinstance(project_list_raw, dict) else []
        project_options = [{"id": p["id"], "name": p.get("name") or f"项目{p['id']}"} for p in project_items]
        project_map = {p["id"]: p.get("name") or f"项目{p['id']}" for p in project_items}

        # 2. 查询文章
        adapter = ArticleAdapter(db)
        result = adapter.list_articles(
            fake_user,
            project_id=project_id,
            keyword=keyword,
            publish_status=publish_status,
            page=page,
            limit=limit,
        )

        if not result["items"]:
            return ToolOutcome.success(
                data=result,
                reply="暂无文章。需要的话可以让我先生成问题，再生成文章。",
            )

        # 3. 组装更丰富的返回字段（含项目名、状态中文名、publish_status）
        def _enrich(a: dict) -> dict:
            raw_publish_status = None
            # 从 DB 再查一次 publish_status（article_adapter 只返回 status，不够用）
            row = db.query(GeoArticle).filter(GeoArticle.id == a["id"]).first()
            if row:
                raw_publish_status = row.publish_status or "completed"
            status_label = _STATUS_LABELS.get(raw_publish_status or "completed", "待发布")
            return {
                "id": a["id"],
                "title": a.get("title", "") or "（无标题）",
                "project_id": a.get("project_id"),
                "project_name": project_map.get(a.get("project_id"), "-") if a.get("project_id") else "-",
                "keyword_id": a.get("keyword_id"),
                "status": a.get("status", 0),
                "publish_status": raw_publish_status or "completed",
                "publish_status_label": status_label,
                "created_at": a.get("created_at"),
            }

        items = [_enrich(a) for a in result["items"]]
        total = result["total"]

        payload = {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "project_id": project_id,
            "project_options": project_options,
        }

        # 按项目分组格式化展示，便于 Agent 直接呈现给用户选择
        grouped_reply = _build_grouped_article_reply(items, project_map, max_per_project=2)
        reply = f"共 {total} 篇文章。按项目展示如下（每个项目最多 2 篇，已发布/失败的也可再次发布）：\n{grouped_reply}"

        return ToolOutcome.success(
            data={"items": items, "total": total, "page": page, "limit": limit, "project_options": project_options},
            reply=reply,
            actions=[
                make_action(
                    "show_article_list",
                    "查看文章列表",
                    payload,
                )
            ],
        )
    except Exception as e:
        logger.error(f"[list_articles] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询文章列表失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()


@register_tool("generate_articles")
async def generate_articles_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """智能文章生成（文章生成唯一入口）。

    根据参数自动判断生成模式：
    - 提供了 question_ids → 从指定问题生成（GATE 强校验：所有问题必须未生成文章且非生成中）
    - 仅提供 project_id + count → 全自动规划问题并生成

    第二层防护：工具执行时校验必填 project_id，缺失则返回 need_clarification。
    文章实际生成在后台异步进行，工具立即返回 running 状态。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import QuestionPoolAdapter

    project_id = slots.get("project_id")
    question_ids = slots.get("question_ids") or []
    count = slots.get("count", 5)

    # 第二层防护：必填字段校验
    if not project_id:
        return ToolOutcome.need_clarification(
            reply="请提供项目ID，才能生成文章",
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
        raw_count = int(count)
    except (TypeError, ValueError):
        raw_count = 5
    count_int = raw_count
    limit_note = ""

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        adapter = QuestionPoolAdapter(db)

        # ---------- P2：文章数 ≤ 问题数 硬校验依据（查项目实况）----------
        from backend.database.models import SmartArticleQuestion

        existing_questions = (
            db.query(SmartArticleQuestion)
            .filter(
                SmartArticleQuestion.project_id == project_id_int,
                SmartArticleQuestion.user_id == user_id,
                SmartArticleQuestion.is_deleted.is_(False),
            )
            .all()
        )
        existing_count = len(existing_questions)

        # 模式1：从指定问题生成（GATE 强校验）
        if question_ids:
            try:
                question_id_list = [int(q) for q in question_ids]
            except (TypeError, ValueError):
                return ToolOutcome.need_clarification(
                    reply="问题ID列表格式无效",
                    suggestion="请提供数字数组格式的问题ID",
                )

            questions = adapter.get_many_questions(fake_user, question_id_list)
            if not questions:
                return ToolOutcome.failure(
                    reply="所选问题不存在或无权限访问",
                    error_type="not_found",
                    suggestion="请检查问题ID，或调用 list_questions 查看问题列表",
                )

            invalid_ids = [
                q["id"] for q in questions if q.get("has_article") or q.get("article_generation_status") == "generating"
            ]
            if invalid_ids:
                return ToolOutcome.need_clarification(
                    reply=f"以下问题已生成过文章或正在生成中：{invalid_ids}，请重新选择",
                    suggestion="请选择未生成文章的问题",
                )

            valid_ids = [q["id"] for q in questions]
            batch_id, skipped = await adapter.generate_articles_sync(
                user=fake_user,
                project_id=project_id_int,
                question_ids=valid_ids,
            )
            logger.info(
                f"[generate_articles] from_questions batch={batch_id} "
                f"accepted={len(valid_ids) - len(skipped)} skipped={len(skipped)}"
            )

            return ToolOutcome.running(
                reply=(f"已提交 {len(valid_ids) - len(skipped)} 篇文章生成任务，预计需要几分钟。完成时会通知您。"),
                data={
                    "article_batch_id": batch_id,
                    "accepted_question_ids": valid_ids,
                    "skipped_question_ids": skipped,
                },
                async_task_refs=[
                    {
                        "task_type": "article_generation",
                        "task_id": batch_id,
                        "query_tool": "list_articles",
                    }
                ],
            )

        # 模式2：全自动 / 基于已有问题生成
        logger.info(
            f"[generate_articles] auto mode project={project_id_int} count={count_int} "
            f"existing_questions={existing_count}"
        )

        if existing_count > 0:
            # 项目已有问题：直接基于“尚未生成文章”的问题生成，严格遵守 文章数 ≤ 问题数。
            available_ids = sorted(
                q.id for q in existing_questions if not q.has_article and q.article_generation_status != "generating"
            )
            if count_int > len(available_ids):
                return ToolOutcome.failure(
                    reply=(
                        f"{limit_note}"
                        f"操作不合法：当前项目共有 {existing_count} 个问题，"
                        f"其中 {len(available_ids)} 个可用于生成文章，"
                        f"但本次请求生成 {count_int} 篇。文章数不能超过可用问题数。"
                    ),
                    error_type="illegal_operation",
                    suggestion="请先生成更多问题（generate_questions），或降低本次生成数量",
                )
            target_ids = available_ids[:count_int]
            article_batch_id, skipped = await adapter.generate_articles_sync(
                user=fake_user,
                project_id=project_id_int,
                question_ids=target_ids,
            )
            logger.info(
                f"[generate_articles] from_existing: article_batch={article_batch_id} "
                f"questions={len(target_ids)} skipped={len(skipped)}"
            )
            return ToolOutcome.running(
                reply=(
                    f"{limit_note}已基于 {len(target_ids)} 个已有问题开始生成文章，预计需要几分钟，可随时查询进度。"
                ),
                data={
                    "article_batch_id": article_batch_id,
                    "question_ids": target_ids,
                    "skipped_question_ids": skipped,
                },
                async_task_refs=[
                    {
                        "task_type": "article_generation",
                        "task_id": article_batch_id,
                        "query_tool": "list_articles",
                    }
                ],
            )

        # 项目暂无问题：从零规划（保留原自动规划行为）
        _, planned_question_ids = await adapter.plan_batch_sync(
            user=fake_user,
            project_id=project_id_int,
            count=count_int,
        )

        if not planned_question_ids:
            return ToolOutcome.failure(
                reply="问题规划未生成有效问题",
                error_type="execution_error",
                suggestion="请稍后重试，或检查项目配置与资料是否充足",
            )

        article_batch_id, skipped = await adapter.generate_articles_sync(
            user=fake_user,
            project_id=project_id_int,
            question_ids=planned_question_ids,
        )
        logger.info(
            f"[generate_articles] auto mode done: article_batch={article_batch_id} "
            f"questions={len(planned_question_ids)} skipped={len(skipped)}"
        )

        return ToolOutcome.running(
            reply=(
                f"{limit_note}"
                f"已自动规划 {len(planned_question_ids)} 个用户问题并开始生成文章，"
                f"预计需要几分钟，可随时查询进度。"
            ),
            data={
                "article_batch_id": article_batch_id,
                "planned_count": count_int,
                "question_ids": planned_question_ids,
                "skipped_question_ids": skipped,
            },
            async_task_refs=[
                {
                    "task_type": "article_generation",
                    "task_id": article_batch_id,
                    "query_tool": "list_articles",
                }
            ],
        )
    except Exception as e:
        logger.error(f"[generate_articles] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="生成文章失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查项目与问题参数是否正确",
        )
    finally:
        db.close()
