# -*- coding: utf-8 -*-
"""项目可见性：基于 Project.user_id 的用户隔离（admin 放行）。

替代过去三处各自查空表 ProjectMember 的错误模式（ProjectMember 当前只读、无任何写入，
导致空集合时不加过滤而返回全库）。与 middleware.user_isolation.scoped_query 语义一致：
普通用户只看自己创建的项目，admin 看全部。

未来若要支持团队协作，启用 ProjectMember 写入并在本模块扩展（OR 合并成员项目）即可，
当前严格按创建者归属隔离。
"""

from typing import Set

from sqlalchemy.orm import Session

from backend.database.models import Project


def user_visible_project_ids(db: Session, user_id: int, *, is_admin: bool = False) -> Set[int]:
    """返回用户可见的活跃项目 ID 集合（status==1）。

    - admin：全部活跃项目；
    - 普通用户：仅 Project.user_id == user_id。

    永不返回全库（无"空集 fallback"陷阱）：无可见项目时返回空集合。
    """
    query = db.query(Project.id).filter(Project.status == 1)
    if not is_admin:
        query = query.filter(Project.user_id == user_id)
    return {row[0] for row in query.all()}
