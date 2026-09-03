# -*- coding: utf-8 -*-
"""账号统计接口测试：软删除不计数、按用户隔离。"""

import asyncio
from datetime import datetime

from backend.api.account import get_account_stats
from backend.database.models import Account, User


def _make_user(db, username: str) -> User:
    user = User(username=username, email=f"{username}@example.test", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_account(db, user, status=1) -> Account:
    acc = Account(user_id=user.id, platform="zhihu", account_name=f"号{user.id}", status=status)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _cleanup(db):
    db.rollback()
    db.query(Account).delete(synchronize_session=False)
    db.query(User).filter(User.username.like("ut_accstat_%")).delete(synchronize_session=False)
    db.commit()


def test_account_stats_excludes_deleted_and_isolates_by_user(clean_db):
    db = clean_db
    try:
        alice = _make_user(db, "ut_accstat_alice")
        bob = _make_user(db, "ut_accstat_bob")

        # alice：2 个启用 + 1 个停用 + 1 个软删除
        _make_account(db, alice, status=1)
        _make_account(db, alice, status=1)
        _make_account(db, alice, status=0)
        deleted = _make_account(db, alice, status=1)
        deleted.deleted_at = datetime.now()
        deleted.status = 0
        db.commit()

        # bob：1 个启用
        _make_account(db, bob, status=1)

        stats_alice = asyncio.run(get_account_stats(db=db, current_user=alice))["data"]
        assert stats_alice["total"] == 3          # 软删除的不算
        assert stats_alice["authorized"] == 2      # status=1 且未删除
        assert stats_alice["disabled"] == 1

        stats_bob = asyncio.run(get_account_stats(db=db, current_user=bob))["data"]
        assert stats_bob["total"] == 1
        assert stats_bob["authorized"] == 1
    finally:
        _cleanup(db)
