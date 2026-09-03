# -*- coding: utf-8 -*-
"""本地客户端设备管理测试（文档 §6.1.1 / §6.2.2）。

- 纯单测：is_device_online / serialize_device 的判活与序列化逻辑。
- DB 集成测：注册（新建/幂等刷新）、心跳、列表按用户隔离、禁用、归属 403。
DB 集成测直接调用路由处理器（绕过 FastAPI 依赖注入），用真实 DB 行验证持久化与隔离。
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.api.client_device import (
    HEARTBEAT_ONLINE_SECONDS,
    disable_device,
    heartbeat_device,
    is_device_online,
    list_devices,
    register_device,
    serialize_device,
    DeviceHeartbeatRequest,
    DeviceRegisterRequest,
    DeviceUpdateRequest,
    update_device,
)
from backend.database.models import ClientDevice, User


# ==================== 纯单测：判活逻辑 ====================


def _dev(**kw):
    base = dict(status="online", last_seen_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_is_device_online_fresh_heartbeat():
    now = datetime(2026, 6, 22, 12, 0, 0)
    assert is_device_online(_dev(last_seen_at=now), now=now) is True


def test_is_device_online_within_window_boundary():
    now = datetime(2026, 6, 22, 12, 0, 0)
    # 恰好等于判活窗口边界（含）→ 仍在线
    assert is_device_online(_dev(last_seen_at=now - timedelta(seconds=HEARTBEAT_ONLINE_SECONDS)), now=now) is True


def test_is_device_online_stale():
    now = datetime(2026, 6, 22, 12, 0, 0)
    assert is_device_online(_dev(last_seen_at=now - timedelta(seconds=HEARTBEAT_ONLINE_SECONDS + 1)), now=now) is False


def test_is_device_online_disabled_never_online():
    now = datetime(2026, 6, 22, 12, 0, 0)
    assert is_device_online(_dev(status="disabled", last_seen_at=now), now=now) is False


def test_is_device_online_no_heartbeat():
    assert is_device_online(_dev(last_seen_at=None), now=datetime.now()) is False


def test_serialize_device_shape_and_online_flag():
    now = datetime(2026, 6, 22, 12, 0, 0)
    dev = SimpleNamespace(
        id=1, user_id=7, device_id="dev_1", device_name="我的电脑", os="windows",
        app_version="1.0.0", capabilities={"local_publish": True}, status="online",
        last_seen_at=now, created_at=now, updated_at=now,
    )
    out = serialize_device(dev, now=now)
    assert out["device_id"] == "dev_1"
    assert out["online"] is True
    assert out["capabilities"] == {"local_publish": True}
    assert out["last_seen_at"] == now.isoformat()


# ==================== DB 集成测 ====================


def _make_user(db, username: str, role: str = "user") -> User:
    user = User(username=username, email=f"{username}@example.test", password_hash="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _cleanup_devices(db):
    db.rollback()  # 清理脏会话状态，确保删除能提交
    db.query(ClientDevice).delete(synchronize_session=False)
    db.query(User).filter(User.username.like("ut_dev_%")).delete(synchronize_session=False)
    db.commit()


def test_register_creates_device_and_marks_online(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_dev_alice")
        req = DeviceRegisterRequest(
            device_id="dev_alice_1", device_name="Alice-PC", os="windows",
            app_version="1.0.0", capabilities={"platforms": ["zhihu"]},
        )
        resp = asyncio.run(register_device(req, db=db, current_user=user))
        device = resp.data["device"]
        assert device["device_id"] == "dev_alice_1"
        assert device["online"] is True
        assert device["status"] == "online"
        assert device["capabilities"]["platforms"] == ["zhihu"]

        # 幂等：再次注册视为刷新，不新建
        resp2 = asyncio.run(register_device(req, db=db, current_user=user))
        assert resp2.data["device"]["id"] == device["id"]
        count = db.query(ClientDevice).filter(ClientDevice.device_id == "dev_alice_1").count()
        assert count == 1
    finally:
        _cleanup_devices(db)


def test_heartbeat_refreshes_last_seen(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_dev_bob")
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_bob_1"), db=db, current_user=user))
        before = db.query(ClientDevice).filter(ClientDevice.device_id == "dev_bob_1").first()
        old_seen = before.last_seen_at

        # 等待时钟推进后心跳
        asyncio.run(asyncio.sleep(0.01))
        asyncio.run(heartbeat_device(
            DeviceHeartbeatRequest(device_id="dev_bob_1"), db=db, current_user=user))
        after = db.query(ClientDevice).filter(ClientDevice.device_id == "dev_bob_1").first()
        assert after.last_seen_at > old_seen
        assert after.status == "online"
    finally:
        _cleanup_devices(db)


def test_list_devices_isolated_by_user(clean_db):
    db = clean_db
    try:
        alice = _make_user(db, "ut_dev_alice2")
        bob = _make_user(db, "ut_dev_bob2")
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_a"), db=db, current_user=alice))
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_b"), db=db, current_user=bob))

        alice_list = asyncio.run(list_devices(db=db, current_user=alice)).data["items"]
        bob_list = asyncio.run(list_devices(db=db, current_user=bob)).data["items"]
        assert {d["device_id"] for d in alice_list} == {"dev_a"}
        assert {d["device_id"] for d in bob_list} == {"dev_b"}
    finally:
        _cleanup_devices(db)


def test_heartbeat_other_users_device_not_registered(clean_db):
    """Bob 未登记过的设备（属于 Alice）→ 404；Bob 用自己的账号登记同一台设备后可正常心跳。"""
    db = clean_db
    try:
        alice = _make_user(db, "ut_dev_alice3")
        bob = _make_user(db, "ut_dev_bob3")
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_alice_only"), db=db, current_user=alice))

        with pytest.raises(Exception) as exc:
            asyncio.run(heartbeat_device(
                DeviceHeartbeatRequest(device_id="dev_alice_only"), db=db, current_user=bob))
        # Bob 没有该设备记录 → 404 引导先注册
        assert exc.value.status_code == 404

        # Bob 登记同一台设备后，心跳自己那条记录成功（多账号共用一台机器）
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_alice_only"), db=db, current_user=bob))
        resp = asyncio.run(heartbeat_device(
            DeviceHeartbeatRequest(device_id="dev_alice_only"), db=db, current_user=bob))
        assert resp.data["device"]["user_id"] == bob.id
        assert resp.data["device"]["online"] is True
    finally:
        _cleanup_devices(db)


def test_same_device_registered_by_multiple_users(clean_db):
    """同一台电脑（同一 device_id）可被多个账号分别登记，互不冲突。"""
    db = clean_db
    try:
        alice = _make_user(db, "ut_dev_alice4")
        bob = _make_user(db, "ut_dev_bob4")
        resp_a = asyncio.run(register_device(
            DeviceRegisterRequest(device_id="shared_id", device_name="Alice-PC"),
            db=db, current_user=alice))
        resp_b = asyncio.run(register_device(
            DeviceRegisterRequest(device_id="shared_id", device_name="Bob-PC"),
            db=db, current_user=bob))
        assert resp_a.data["device"]["id"] != resp_b.data["device"]["id"]
        assert resp_a.data["device"]["user_id"] == alice.id
        assert resp_b.data["device"]["user_id"] == bob.id

        count = db.query(ClientDevice).filter(ClientDevice.device_id == "shared_id").count()
        assert count == 2

        # 各自列表只看到自己的记录
        alice_list = asyncio.run(list_devices(db=db, current_user=alice)).data["items"]
        bob_list = asyncio.run(list_devices(db=db, current_user=bob)).data["items"]
        assert {d["device_id"] for d in alice_list} == {"shared_id"}
        assert {d["device_id"] for d in bob_list} == {"shared_id"}
        assert {d["user_id"] for d in alice_list} == {alice.id}
        assert {d["user_id"] for d in bob_list} == {bob.id}
    finally:
        _cleanup_devices(db)


def test_disable_device_makes_offline(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_dev_carol")
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_carol"), db=db, current_user=user))
        resp = asyncio.run(disable_device("dev_carol", db=db, current_user=user))
        assert resp.data["device"]["status"] == "disabled"
        assert resp.data["device"]["online"] is False
    finally:
        _cleanup_devices(db)


def test_update_device_name(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_dev_dave")
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_dave"), db=db, current_user=user))
        resp = asyncio.run(update_device(
            "dev_dave", DeviceUpdateRequest(device_name="Dave-Mac"), db=db, current_user=user))
        assert resp.data["device"]["device_name"] == "Dave-Mac"
    finally:
        _cleanup_devices(db)
