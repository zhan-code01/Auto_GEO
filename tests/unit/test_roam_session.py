# -*- coding: utf-8 -*-
"""会话漫游接口测试：A 电脑绑定 → 同账号 B 电脑拉取发布（按用户隔离）。"""

import asyncio
import json

import pytest

from backend.api.auth import download_roaming_session, upload_roaming_session
from backend.api.auth import RoamSessionUploadRequest
from backend.database.models import Account, User
from backend.services.session_manager import secure_session_manager


def _body(resp):
    return json.loads(resp.body.decode("utf-8"))


def _make_user(db, username: str) -> User:
    user = User(username=username, email=f"{username}@example.test", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_account(db, user, platform="zhihu", name="知乎号") -> Account:
    account = Account(
        user_id=user.id, platform=platform, account_name=name, status=1,
        auth_mode="local_client", session_location="local_only", device_id="dev_x",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _cleanup(db, account_ids=None):
    db.rollback()
    for aid in account_ids or []:
        try:
            secure_session_manager._get_roaming_session_path(aid).unlink(missing_ok=True)
        except Exception:
            pass
    db.query(Account).delete(synchronize_session=False)
    db.query(User).filter(User.username.like("ut_roam_%")).delete(synchronize_session=False)
    db.commit()


SAMPLE_STATE = {
    "cookies": [
        {"name": "token", "value": "abc", "domain": ".zhihu.com", "path": "/", "expires": 1999999999},
    ],
    "origins": [],
}


def test_upload_and_download_roaming_session(clean_db):
    db = clean_db
    try:
        alice = _make_user(db, "ut_roam_alice")
        acc = _make_account(db, alice)

        resp = asyncio.run(upload_roaming_session(
            RoamSessionUploadRequest(platform="zhihu", account_id=acc.id, storage_state=SAMPLE_STATE),
            db=db, current_user=alice))
        assert _body(resp)["success"] is True

        # 同账号（这里模拟 B 电脑场景，仍是 alice 登录）可下载
        data = _body(asyncio.run(download_roaming_session(acc.id, db=db, current_user=alice)))
        assert data["platform"] == "zhihu"
        assert data["storage_state"]["cookies"][0]["value"] == "abc"
    finally:
        _cleanup(db, [acc.id])


def test_roam_session_isolated_by_user(clean_db):
    db = clean_db
    try:
        alice = _make_user(db, "ut_roam_alice2")
        bob = _make_user(db, "ut_roam_bob2")
        acc = _make_account(db, alice)
        asyncio.run(upload_roaming_session(
            RoamSessionUploadRequest(platform="zhihu", account_id=acc.id, storage_state=SAMPLE_STATE),
            db=db, current_user=alice))

        # bob 不能上传/下载 alice 的账号会话
        with pytest.raises(Exception) as exc:
            asyncio.run(upload_roaming_session(
                RoamSessionUploadRequest(platform="zhihu", account_id=acc.id, storage_state=SAMPLE_STATE),
                db=db, current_user=bob))
        assert exc.value.status_code == 403

        with pytest.raises(Exception) as exc:
            asyncio.run(download_roaming_session(acc.id, db=db, current_user=bob))
        assert exc.value.status_code == 403

        # 未上传过的账号下载 → 404
        acc2 = _make_account(db, alice, name="知乎号2")
        with pytest.raises(Exception) as exc:
            asyncio.run(download_roaming_session(acc2.id, db=db, current_user=alice))
        assert exc.value.status_code == 404
    finally:
        _cleanup(db, [acc.id, acc2.id])


def test_roam_session_upload_platform_mismatch(clean_db):
    db = clean_db
    try:
        alice = _make_user(db, "ut_roam_carol")
        acc = _make_account(db, alice, platform="zhihu")
        with pytest.raises(Exception) as exc:
            asyncio.run(upload_roaming_session(
                RoamSessionUploadRequest(platform="douyin", account_id=acc.id, storage_state=SAMPLE_STATE),
                db=db, current_user=alice))
        assert exc.value.status_code == 400
    finally:
        _cleanup(db, [acc.id])
