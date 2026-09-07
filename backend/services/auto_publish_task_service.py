# -*- coding: utf-8 -*-
"""
自动发布任务服务层

统一封装 "创建发布任务 + 启动执行" 的逻辑，供 API（backend.api.auto_publish）
和后台 Agent（backend.services.agent.task_executor）共同调用。

设计目的：
1. 消除 Agent 执行器对 backend.api.auto_publish 的反向依赖（service -> api 分层错误）。
2. 统一任务创建逻辑：文章归属校验、账号归属校验、子任务记录创建，避免在
   API 和 Agent 两处各写一份而出现权限不一致。
3. 所有关键 ID（project_id / account_id / article_id）均以 system_user_id 为准
   重新过滤，绝不信任外部传入的归属关系。
"""

import asyncio
from datetime import datetime
from typing import List, Optional, Set

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import (
    Account,
    AutoPublishRecord,
    AutoPublishTask,
    GeoArticle,
)
from backend.services.project_access import user_visible_project_ids


class AutoPublishTaskService:
    """创建、校验、启动自动发布任务的统一入口。"""

    def list_user_project_ids(self, db: Session, system_user_id: int, *, is_admin: bool = False) -> Set[int]:
        """返回当前用户可见的项目 ID 集合（基于 Project.user_id，admin 放行）。

        不再依赖只读空表 ProjectMember（否则成员记录为空时返回空集，使下游文章归属
        校验失效）。
        """
        return user_visible_project_ids(db, system_user_id, is_admin=is_admin)

    def create_publish_task(
        self,
        db: Session,
        system_user_id: int,
        article_ids: List[int],
        account_ids: List[int],
        name: str = "",
        description: str = "",
        status: str = "pending",
        declare_ai_content: Optional[bool] = None,
        triggered_by: str = "agent",
    ) -> AutoPublishTask:
        """
        创建自动发布任务并写入子任务记录。

        权限校验（不可绕过）：
        - 文章必须存在；
        - 文章所属项目必须在当前用户可见项目集合内；
        - 发布账号必须存在、已启用且属于当前用户（deleted_at 为空）。

        任意一项不满足都抛出 ValueError，调用方负责转成可读错误。
        """
        if not article_ids or not account_ids:
            raise ValueError("文章和发布账号均不能为空")

        article_ids = [int(aid) for aid in article_ids]
        account_ids = [int(aid) for aid in account_ids]
        logger.info(
            f"[AutoPublish] 创建任务开始: user_id={system_user_id} "
            f"articles={len(article_ids)} accounts={len(account_ids)} triggered_by={triggered_by}"
        )

        # 1. 文章存在性
        articles = db.query(GeoArticle).filter(GeoArticle.id.in_(article_ids)).all()
        if len(articles) != len(article_ids):
            missing = sorted(set(article_ids) - {a.id for a in articles})
            logger.warning(f"[AutoPublish] 创建任务被拒绝：部分文章不存在 missing={missing} user_id={system_user_id}")
            raise ValueError("部分文章不存在")

        # 2. 文章归属：文章所在项目必须在用户可见项目内
        allowed_project_ids = self.list_user_project_ids(db, system_user_id)
        for article in articles:
            if article.project_id and article.project_id not in allowed_project_ids:
                logger.warning(
                    f"[AutoPublish] 创建任务被拒绝：文章越权 article_id={article.id} "
                    f"project_id={article.project_id} user_id={system_user_id}"
                )
                raise ValueError("部分文章不属于当前用户可访问项目")

        # 3. 账号归属：必须存在、启用且属于当前用户
        accounts = (
            db.query(Account)
            .filter(
                Account.id.in_(account_ids),
                Account.user_id == system_user_id,
                Account.status == 1,
                Account.deleted_at.is_(None),
            )
            .all()
        )
        if len(accounts) != len(account_ids):
            missing = sorted(set(account_ids) - {a.id for a in accounts})
            logger.warning(f"[AutoPublish] 创建任务被拒绝：账号不可用 missing={missing} user_id={system_user_id}")
            raise ValueError("部分发布账号不存在、未启用或不属于当前用户")

        # 4. 创建任务主记录
        total_count = len(article_ids) * len(account_ids)
        task_fields = dict(
            name=name or f"Agent发布任务-{datetime.now().strftime('%m%d%H%M')}",
            description=description or "由后台 Agent 创建",
            article_ids=article_ids,
            account_ids=account_ids,
            exec_type="immediate",
            total_count=total_count,
            completed_count=0,
            failed_count=0,
            status=status,
            # 后台 Agent 无 HTTP 上下文，写入时自动填充不会生效，
            # 必须显式写入归属，否则任务对该用户不可见（仅 admin 可见）。
            user_id=system_user_id,
            triggered_by_user_id=system_user_id,
        )
        if declare_ai_content is not None:
            task_fields["declare_ai_content"] = declare_ai_content
        task = AutoPublishTask(**task_fields)
        db.add(task)
        db.commit()
        db.refresh(task)

        # 5. 创建子任务记录（article × account 笛卡尔积）
        for article_id in article_ids:
            for account_id in account_ids:
                db.add(
                    AutoPublishRecord(
                        task_id=task.id,
                        article_id=article_id,
                        account_id=account_id,
                        status="pending",
                    )
                )
        db.commit()
        logger.info(
            f"[AutoPublish] 任务创建成功: task_id={task.id} name={task.name} "
            f"total={total_count} articles={article_ids} accounts={account_ids} "
            f"user_id={system_user_id}"
        )
        return task

    def kickoff(self, task_id: int) -> None:
        """
        启动一个已创建的发布任务（fire-and-forget）。

        实际的发布编排（Playwright 发布、WebSocket 进度推送、重试）实现于
        backend.api.auto_publish.execute_auto_publish_task，这里只做转发，
        避免在 service 层重复维护一套发布流水线。task_id 必须是已属于调用方
        的任务（调用方在调用前应自行校验归属）。

        使用 BackgroundTaskManager 提交，防止被 SSE 流取消。
        """
        from backend.api.auto_publish import execute_auto_publish_task
        from backend.services.background_task_manager import background_task_manager

        logger.info(f"[AutoPublish] 任务启动（fire-and-forget）: task_id={task_id}")
        background_task_manager.submit(
            execute_auto_publish_task(task_id),
            task_name=f"auto_publish_{task_id}",
        )


_instance: Optional[AutoPublishTaskService] = None


def get_auto_publish_task_service() -> AutoPublishTaskService:
    global _instance
    if _instance is None:
        _instance = AutoPublishTaskService()
    return _instance
