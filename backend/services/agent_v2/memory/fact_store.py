# -*- coding: utf-8 -*-
"""用户长期事实存储 - 基于 user_agent_facts 表。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import UserAgentFact


# 默认 facts 结构
DEFAULT_FACTS: dict[str, Any] = {
    "company_name": None,  # 常用公司名
    "industry": None,  # 常用行业
    "common_platforms": [],  # 常选发布平台
    "default_client_id": None,  # 默认客户ID
    "default_project_id": None,  # 默认项目ID
    "website": None,  # 公司官网
    "location": None,  # 所在地
}


class FactStore:
    """用户长期事实存储。一人一条 UserAgentFact 记录。"""

    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, user_id: int) -> UserAgentFact:
        record = self.db.query(UserAgentFact).filter(UserAgentFact.system_user_id == user_id).first()
        if record:
            return record
        record = UserAgentFact(
            system_user_id=user_id,
            facts=dict(DEFAULT_FACTS),
            onboarding_stage=None,
            onboarding_completed=False,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_facts(self, user_id: int) -> dict[str, Any]:
        record = self.get_or_create(user_id)
        facts = record.facts or {}
        # 合并默认值（防止老数据缺字段）
        merged = dict(DEFAULT_FACTS)
        merged.update(facts if isinstance(facts, dict) else {})
        return merged

    def patch_facts(self, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        """增量合并 facts，返回合并后的完整 facts。"""
        record = self.get_or_create(user_id)
        current = record.facts or dict(DEFAULT_FACTS)
        if not isinstance(current, dict):
            current = dict(DEFAULT_FACTS)
        current.update(patch)
        record.facts = current
        self.db.commit()
        self.db.refresh(record)
        return current

    # ------------------------------------------------------------------
    #  引导流程状态
    # ------------------------------------------------------------------
    def get_onboarding_stage(self, user_id: int) -> str | None:
        record = self.get_or_create(user_id)
        return record.onboarding_stage

    def set_onboarding_stage(self, user_id: int, stage: str | None) -> None:
        record = self.get_or_create(user_id)
        record.onboarding_stage = stage
        self.db.commit()

    def is_onboarding_completed(self, user_id: int) -> bool:
        record = self.get_or_create(user_id)
        return bool(record.onboarding_completed)

    def set_onboarding_completed(self, user_id: int, completed: bool = True) -> None:
        record = self.get_or_create(user_id)
        record.onboarding_completed = completed
        if completed:
            record.onboarding_stage = None
        self.db.commit()

    # ------------------------------------------------------------------
    #  槽位失效处理
    # ------------------------------------------------------------------
    def invalidate_facts(self, user_id: int, keys: list[str]) -> None:
        """将指定 facts 字段重置为默认值（用于依赖失效）。"""
        record = self.get_or_create(user_id)
        facts = record.facts or dict(DEFAULT_FACTS)
        for key in keys:
            if key in DEFAULT_FACTS:
                facts[key] = DEFAULT_FACTS[key]
        record.facts = facts
        self.db.commit()
