# -*- coding: utf-8 -*-
"""PublishAdapter - 发布执行适配器。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import Account, GeoArticle, PublishRecord
from backend.middleware.user_isolation import scoped_query


class PublishAdapter:
    """发布执行适配器 - 文章发布到平台。"""

    def __init__(self, db: Session):
        self.db = db

    def publish_articles(
        self,
        user,
        article_ids: list[int],
        account_ids: list[int],
        declare_ai_content: bool = True,
        execution_mode: str = "local_client",
    ) -> dict[str, Any]:
        """发布文章到指定平台账号。

        底层复用 AutoPublishTaskService 创建并发布任务。
        """
        from backend.services.auto_publish_task_service import AutoPublishTaskService

        service = AutoPublishTaskService()
        task = service.create_publish_task(
            db=self.db,
            system_user_id=user.id,
            article_ids=article_ids,
            account_ids=account_ids,
            name=f"智能体发布_{len(article_ids)}篇",
            description="由 Agent V2 触发",
            declare_ai_content=declare_ai_content,
        )
        # 启动发布任务（fire-and-forget）
        service.kickoff(task.id)
        return {
            "task_id": task.id,
            "total_count": task.total_count,
            "article_ids": article_ids,
            "account_ids": account_ids,
        }

    def get_publish_task_status(self, user, task_id: int) -> dict[str, Any]:
        """查询发布任务状态。"""
        from backend.database.models import AutoPublishTask
        from backend.middleware.user_isolation import scoped_query

        query = scoped_query(self.db, AutoPublishTask, user)
        task = query.filter(AutoPublishTask.id == task_id).first()
        if not task:
            return {"error": "任务不存在"}
        return {
            "task_id": task.id,
            "name": task.name,
            "status": task.status,
            "total_count": task.total_count,
            "completed_count": task.completed_count,
            "failed_count": task.failed_count,
        }

    def list_publish_records(
        self, user, article_id: int | None = None, publish_status: int | None = None, page: int = 1, limit: int = 20
    ) -> dict[str, Any]:
        """查询发布记录。

        Args:
            user: 当前用户
            article_id: 按文章ID筛选（可选）
            publish_status: 按发布状态筛选（可选，0=待发布 1=发布中 2=成功 3=失败）
            page: 页码
            limit: 每页条数
        """
        query = scoped_query(self.db, PublishRecord, user)
        if article_id:
            query = query.filter(PublishRecord.article_id == article_id)
        if publish_status is not None:
            query = query.filter(PublishRecord.publish_status == publish_status)
        total = query.count()
        rows = query.order_by(PublishRecord.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return {
            "total": total,
            "items": [
                {
                    "id": r.id,
                    "article_id": r.article_id,
                    "account_id": r.account_id,
                    "publish_status": r.publish_status,
                    "platform_url": r.platform_url,
                    "error_msg": r.error_msg,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                }
                for r in rows
            ],
        }

    async def start_platform_auth(
        self, user, platform: str, account_name: str | None = None, account_id: int | None = None
    ) -> dict[str, Any]:
        """发起平台登录授权（返回 task_id，前端打开浏览器登录窗口）。"""
        from backend.services.playwright_mgr import playwright_mgr

        task = await playwright_mgr.create_auth_task(
            platform=platform,
            account_id=account_id,
            account_name=account_name,
            user_id=user.id,
        )
        return {
            "task_id": task.task_id,
            "platform": platform,
        }
