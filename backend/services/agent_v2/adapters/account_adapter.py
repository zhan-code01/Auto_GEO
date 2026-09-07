# -*- coding: utf-8 -*-
"""AccountAdapter - 平台账号适配器。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import Account
from backend.middleware.user_isolation import scoped_query
from backend.services.agent_v2.platforms import is_ai_platform


class AccountAdapter:
    """平台账号适配器 - 查询绑定/可用平台/发起授权。"""

    def __init__(self, db: Session):
        self.db = db

    def list_user_bindings(self, user) -> list[dict[str, Any]]:
        """查询用户已绑定的平台账号。

        只返回「发布平台」，过滤掉 doubao/qianwen/deepseek 等 AI 鉴权专用账号
        （那些是 GEO 评测采集用的，普通用户不应在「我绑了哪些平台」里看到）。
        """
        rows = (
            scoped_query(self.db, Account, user)
            .filter(Account.deleted_at.is_(None))
            .order_by(Account.created_at.desc())
            .all()
        )
        return [self._to_dict(r) for r in rows if not is_ai_platform(r.platform)]

    def list_available_platforms(self) -> list[dict[str, Any]]:
        """查询系统支持的所有平台。"""
        from backend.config import PLATFORMS

        if not PLATFORMS:
            return []
        return [
            {"platform_id": pid, "platform_name": info.get("name", pid) if isinstance(info, dict) else str(info)}
            for pid, info in PLATFORMS.items()
        ]

    def get_account(self, user, account_id: int) -> dict[str, Any] | None:
        row = scoped_query(self.db, Account, user).filter(Account.id == account_id).first()
        return self._to_dict(row) if row else None

    def find_by_platform(self, user, platform: str) -> list[dict[str, Any]]:
        rows = (
            scoped_query(self.db, Account, user)
            .filter(
                Account.platform == platform,
                Account.deleted_at.is_(None),
            )
            .all()
        )
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(account: Account) -> dict[str, Any]:
        return {
            "id": account.id,
            "platform": account.platform,
            "account_name": account.account_name,
            "username": account.username,
            "status": account.status,
            "last_auth_time": account.last_auth_time.isoformat() if account.last_auth_time else None,
            "is_authorized": account.is_authorized if hasattr(account, "is_authorized") else (account.status == 1),
            "auth_mode": account.auth_mode,
            "device_id": account.device_id,
            "created_at": account.created_at.isoformat() if account.created_at else None,
        }
