# -*- coding: utf-8 -*-
"""
用户数据隔离工具
================

提供两层能力：
1. SQLAlchemy before_insert 事件 —— 自动为新记录填充 user_id（无需修改路由代码）
2. 查询过滤辅助函数 —— 路由处理函数可按需调用，实现数据隔离

依赖 auth_middleware 中设置的 contextvars.current_user_id。
"""

from typing import Optional, List, Type
from sqlalchemy import event
from sqlalchemy.orm import Query, Session
from fastapi import HTTPException
from loguru import logger

from backend.middleware.auth_middleware import current_user_id


# ==================== 需要自动填充 user_id 的模型列表 ====================

# 这些模型在 insert 时会自动从上下文获取当前用户 ID 并填充
AUTO_USER_ID_MODELS = set()


def register_model_for_auto_user_id(model_class):
    """
    注册模型以启用自动 user_id 填充。
    仅当模型定义了 user_id 列时才会生效。

    用法（在 main.py 启动时调用）：
        from backend.database.models import GeoArticle
        register_model_for_auto_user_id(GeoArticle)
    """
    if not hasattr(model_class, "user_id"):
        logger.warning(f"[Isolation] 模型 {model_class.__name__} 缺少 user_id 列，跳过注册")
        return

    if model_class in AUTO_USER_ID_MODELS:
        return

    AUTO_USER_ID_MODELS.add(model_class)

    @event.listens_for(model_class, "before_insert", propagate=True)
    def _auto_set_user_id(mapper, connection, target):
        """
        SQLAlchemy before_insert 事件：
        在 INSERT 之前自动填充 user_id（如果尚未设置）。

        优先级：
        1. 如果 target.user_id 已有值 → 保留（允许显式覆盖）
        2. 否则从 contextvars 中取当前请求用户 ID
        3. 如果没有用户上下文（例如后台任务） → 保持 NULL
        """
        if getattr(target, "user_id", None) is not None:
            return  # 已有值，不覆盖

        uid = current_user_id.get()
        if uid is not None:
            setattr(target, "user_id", uid)

    logger.debug(f"[Isolation] 已为 {model_class.__name__} 注册 auto-user_id 事件")


# ==================== 查询过滤辅助函数 ====================


def filter_by_user(
    query: Query,
    model_class,
    user_id: int,
    *,
    is_admin: bool = False,
    allow_null_owner: bool = True,
) -> Query:
    """
    对查询添加用户隔离过滤。

    参数：
        query: SQLAlchemy Query 对象
        model_class: 要过滤的模型类（必须包含 user_id 列）
        user_id: 当前用户的 ID
        is_admin: 是否管理员（管理员跳过过滤，可看全部数据）
        allow_null_owner: 是否允许 user_id=NULL 的行（历史数据迁移前）

    返回：
        过滤后的 Query
    """
    # 管理员可以看全部数据
    if is_admin:
        return query

    if not hasattr(model_class, "user_id"):
        logger.warning(f"[Isolation] 模型 {model_class.__name__} 没有 user_id 列，无法过滤")
        return query

    if allow_null_owner:
        # 允许看自己创建的 + 未归属的历史数据
        return query.filter((model_class.user_id == user_id) | (model_class.user_id.is_(None)))
    else:
        # 严格模式：只看自己的
        return query.filter(model_class.user_id == user_id)


def get_owner_filter(model_class, user_id: int, *, is_admin: bool = False):
    """
    返回 SQLAlchemy 过滤条件（用于构建查询时使用）。

    用法：
        query = db.query(GeoArticle).filter(
            GeoArticle.publish_status == "published",
            *get_owner_filter(GeoArticle, current_user_id)
        )
    """
    if is_admin:
        return []
    if not hasattr(model_class, "user_id"):
        return []
    # 允许 NULL（历史数据）
    from sqlalchemy import or_

    return [
        or_(
            model_class.user_id == user_id,
            model_class.user_id.is_(None),
        )
    ]


# ==================== 路由层快速隔离工具 ====================


def scoped_query(db: Session, model_class, current_user):
    """
    返回按当前用户隔离的查询对象（admin 看全部；普通用户只看自己的）。

    严格模式：普通用户只匹配 user_id == current_user.id（不含 NULL）。
    历史数据已由 fix_database 回填给主管理员(id=1)，故非 admin 不会看到系统历史数据。
    """
    query = db.query(model_class)
    if getattr(current_user, "role", None) == "admin":
        return query
    return query.filter(model_class.user_id == current_user.id)


def require_owner(obj, current_user, *, name: str = "记录"):
    """
    校验单条记录归属，用于 GET/PUT/DELETE 等「按 id 取单条」的接口。
    - admin 放行
    - 普通用户：仅当 obj.user_id == current_user.id 时放行；否则 403
      （user_id 为 NULL 的历史/系统记录，普通用户无权访问）
    """
    if getattr(current_user, "role", None) == "admin":
        return
    if getattr(obj, "user_id", None) != current_user.id:
        raise HTTPException(status_code=403, detail=f"无权访问该{name}")
