# -*- coding: utf-8 -*-
"""本地客户端发布任务路由测试（文档 §6.1.3 / §6.1.4 / §6.1.5）。

覆盖：
- 创建 local_client 立即任务时不触发服务器执行（保持 pending，等待客户端领取）。
- 客户端协议：poll → claim（含原子锁/续租/过期回收/跨设备 409）→ payload → result（计数与终态）→ manual-required。
- 归属隔离：他人任务不可 claim/payload（403）。

直接调用路由处理器，用真实 DB 行验证持久化、锁与隔离。
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from backend.api.auto_publish import create_auto_publish_task
from backend.api.client_publish import (
    claim_task,
    get_task_payload,
    heartbeat_task,
    mark_manual_required,
    poll_tasks,
    report_result,
    ClaimRequest,
    HeartbeatRequest,
    ManualRequiredRequest,
    TaskResultRequest,
)
from backend.api.client_device import register_device, DeviceRegisterRequest
from backend.database.models import (
    Account,
    AutoPublishRecord,
    AutoPublishTask,
    ClientDevice,
    GeoArticle,
    Keyword,
    Project,
    User,
)
from backend.schemas import AutoPublishTaskCreate


# ==================== 辅助：构建最小数据链 ====================


def _make_user(db, username: str) -> User:
    user = User(username=username, email=f"{username}@example.test", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _build_chain(db, user, *, device_id="dev_main", platform="zhihu"):
    """user → project → keyword → article；+ account + device。返回各对象。"""
    project = Project(name="p_" + device_id, user_id=user.id, status=1)
    db.add(project)
    db.commit()
    db.refresh(project)

    keyword = Keyword(project_id=project.id, keyword="kw", status="active")
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    article = GeoArticle(
        user_id=user.id, keyword_id=keyword.id, title="文章标题", content="正文内容 markdown",
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    account = Account(
        user_id=user.id, platform=platform, account_name=f"{platform}_号", status=1,
        auth_mode="local_client", session_location="local_only",
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    asyncio.run(register_device(
        DeviceRegisterRequest(device_id=device_id, capabilities={"platforms": [platform]}),
        db=db, current_user=user))

    return {"project": project, "keyword": keyword, "article": article, "account": account}


def _make_local_task(db, user, article, account, *, device_id=None, name="t1"):
    """直接建一个 local_client 任务 + 一条子记录。"""
    task = AutoPublishTask(
        name=name, user_id=user.id, article_ids=[article.id], account_ids=[account.id],
        exec_type="immediate", execution_mode="local_client", assigned_device_id=device_id,
        total_count=1, completed_count=0, failed_count=0, status="pending",
        declare_ai_content=True,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    rec = AutoPublishRecord(task_id=task.id, article_id=article.id, account_id=account.id, status="pending")
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return task, rec


def _cleanup(db):
    # 先回滚，清理任何 flush 失败留下的脏会话状态，确保下面的删除能提交
    db.rollback()
    db.query(AutoPublishRecord).delete(synchronize_session=False)
    db.query(AutoPublishTask).delete(synchronize_session=False)
    db.query(ClientDevice).delete(synchronize_session=False)
    db.query(User).filter(User.username.like("ut_pub_%")).delete(synchronize_session=False)
    db.commit()


# ==================== 创建任务的服务端执行门控 ====================


def test_local_client_task_not_executed_on_server(clean_db):
    """local_client 立即任务保持 pending，不触发服务器 Playwright 执行。"""
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_alice")
        chain = _build_chain(db, user)
        req = AutoPublishTaskCreate(
            name="本地发布任务",
            article_ids=[chain["article"].id],
            account_ids=[chain["account"].id],
            exec_type="immediate",
            execution_mode="local_client",
        )
        resp = asyncio.run(create_auto_publish_task(req, db=db, current_user=user))
        task_id = resp.data["task_id"]
        task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task_id).first()
        assert task.execution_mode == "local_client"
        # 关键：未被服务器执行，仍是 pending（而非 running）
        assert task.status == "pending"
        assert task.total_count == 1
    finally:
        _cleanup(db)


# ==================== 客户端协议：poll / claim / payload / result ====================


def test_poll_returns_claimable_local_task(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_bob")
        chain = _build_chain(db, user, device_id="dev_bob")
        task, _ = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_bob")

        resp = asyncio.run(poll_tasks(device_id="dev_bob", platform=None, limit=20, db=db, current_user=user))
        ids = [t["id"] for t in resp.data["items"]]
        assert task.id in ids
    finally:
        _cleanup(db)


def test_claim_locks_task_and_payload_returns_content(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_carol")
        chain = _build_chain(db, user, device_id="dev_carol")
        task, rec = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_carol")

        claim = asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_carol"), db=db, current_user=user))
        assert claim.data["task"]["status"] == "running"
        assert claim.data["task"]["claimed_by_device_id"] == "dev_carol"
        assert rec.id in claim.data["record_ids"]

        payload = asyncio.run(get_task_payload(task.id, device_id="dev_carol", db=db, current_user=user))
        r0 = payload.data["records"][0]
        assert r0["article"]["title"] == "文章标题"
        assert r0["article"]["content"] == "正文内容 markdown"
        assert r0["platform"] == "zhihu"
        assert payload.data["publish_options"]["declare_ai_content"] is True
    finally:
        _cleanup(db)


def test_second_device_claim_rejected(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_dave")
        chain = _build_chain(db, user, device_id="dev_dave")
        # 第二台设备
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_dave2"), db=db, current_user=user))
        task, _ = _make_local_task(db, user, chain["article"], chain["account"])

        asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_dave"), db=db, current_user=user))
        with pytest.raises(Exception) as exc:
            asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_dave2"), db=db, current_user=user))
        assert exc.value.status_code == 409
    finally:
        _cleanup(db)


def test_assigned_task_cannot_be_claimed_by_other_device(clean_db):
    """任务指定给 A 设备（本机创建）后，同账号的 B 设备即使知道 task_id 也领取不了（403）。

    多机同账号场景：一台电脑创建的任务只由该电脑的浏览器执行，其它在线设备不抢。
    """
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_fiona")
        chain = _build_chain(db, user, device_id="dev_fiona")
        # 第二台在线设备（同账号）
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_fiona2"), db=db, current_user=user))
        # 任务由 dev_fiona 创建并指定给本机执行
        task, _ = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_fiona")

        # 指定设备可以正常领取
        ok = asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_fiona"), db=db, current_user=user))
        assert ok.data["task"]["claimed_by_device_id"] == "dev_fiona"

        # 另一台设备领取 → 403（即使领取锁已过期也不允许：任务归属创建它的机器）
        task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task.id).first()
        task.claim_expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(Exception) as exc:
            asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_fiona2"), db=db, current_user=user))
        assert exc.value.status_code == 403
    finally:
        _cleanup(db)


def test_expired_claim_can_be_reclaimed(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_eve")
        chain = _build_chain(db, user, device_id="dev_eve")
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_eve2"), db=db, current_user=user))
        task, _ = _make_local_task(db, user, chain["article"], chain["account"])

        asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_eve"), db=db, current_user=user))
        # 手动把领取锁置为过期，模拟客户端崩溃未续租
        task = db.query(AutoPublishTask).filter(AutoPublishTask.id == task.id).first()
        task.claim_expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()

        # 另一台设备现在可以接管
        claim2 = asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_eve2"), db=db, current_user=user))
        assert claim2.data["task"]["claimed_by_device_id"] == "dev_eve2"
    finally:
        _cleanup(db)


def test_result_success_completes_task(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_frank")
        chain = _build_chain(db, user, device_id="dev_frank")
        task, rec = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_frank")
        asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_frank"), db=db, current_user=user))

        resp = asyncio.run(report_result(
            task.id,
            TaskResultRequest(device_id="dev_frank", record_id=rec.id, status="success",
                              platform_url="https://zhuanlan.zhihu.com/p/xxx"),
            db=db, current_user=user))
        assert resp.data["settled"] is True
        assert resp.data["task"]["status"] == "completed"
        assert resp.data["task"]["completed_count"] == 1

        record = db.query(AutoPublishRecord).filter(AutoPublishRecord.id == rec.id).first()
        assert record.status == "success"
        assert record.platform_url == "https://zhuanlan.zhihu.com/p/xxx"
    finally:
        _cleanup(db)


def test_result_failed_marks_task_failed(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_grace")
        chain = _build_chain(db, user, device_id="dev_grace")
        task, rec = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_grace")
        asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_grace"), db=db, current_user=user))

        resp = asyncio.run(report_result(
            task.id,
            TaskResultRequest(device_id="dev_grace", record_id=rec.id, status="failed",
                              error_code="LOGIN_EXPIRED", error_msg="登录态失效"),
            db=db, current_user=user))
        assert resp.data["task"]["status"] == "failed"
        record = db.query(AutoPublishRecord).filter(AutoPublishRecord.id == rec.id).first()
        assert record.status == "failed"
        assert "LOGIN_EXPIRED" in record.error_msg
    finally:
        _cleanup(db)


def test_manual_required_marks_task_without_failing(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_heidi")
        chain = _build_chain(db, user, device_id="dev_heidi")
        task, _ = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_heidi")
        asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_heidi"), db=db, current_user=user))

        resp = asyncio.run(report_result(
            task.id,
            TaskResultRequest(device_id="dev_heidi", record_id=task.records[0].id, status="manual_required",
                              error_msg="需要扫码验证"),
            db=db, current_user=user))
        assert resp.data["task"]["manual_required"] is True
        assert resp.data["task"]["manual_message"] == "需要扫码验证"
        # 仍未失败
        assert resp.data["task"]["status"] == "running"
        record = db.query(AutoPublishRecord).filter(AutoPublishRecord.id == task.records[0].id).first()
        assert record.status == "manual_required"

        # manual-required 专用接口
        resp2 = asyncio.run(mark_manual_required(
            task.id, ManualRequiredRequest(device_id="dev_heidi", message="滑块验证"),
            db=db, current_user=user))
        assert resp2.data["task"]["manual_message"] == "滑块验证"
    finally:
        _cleanup(db)


def test_other_user_cannot_claim_task(clean_db):
    db = clean_db
    try:
        alice = _make_user(db, "ut_pub_alice2")
        bob = _make_user(db, "ut_pub_bob2")
        chain = _build_chain(db, alice, device_id="dev_alice")
        task, _ = _make_local_task(db, alice, chain["article"], chain["account"], device_id="dev_alice")
        # bob 有自己的设备
        asyncio.run(register_device(
            DeviceRegisterRequest(device_id="dev_bob"), db=db, current_user=bob))

        with pytest.raises(Exception) as exc:
            asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_bob"), db=db, current_user=bob))
        assert exc.value.status_code == 403
    finally:
        _cleanup(db)


def test_heartbeat_extends_claim(clean_db):
    db = clean_db
    try:
        user = _make_user(db, "ut_pub_ivan")
        chain = _build_chain(db, user, device_id="dev_ivan")
        task, _ = _make_local_task(db, user, chain["article"], chain["account"], device_id="dev_ivan")
        asyncio.run(claim_task(task.id, ClaimRequest(device_id="dev_ivan"), db=db, current_user=user))

        before = db.query(AutoPublishTask).filter(AutoPublishTask.id == task.id).first().claim_expires_at
        asyncio.run(asyncio.sleep(0.01))
        asyncio.run(heartbeat_task(task.id, HeartbeatRequest(device_id="dev_ivan"), db=db, current_user=user))
        after = db.query(AutoPublishTask).filter(AutoPublishTask.id == task.id).first().claim_expires_at
        assert after > before
    finally:
        _cleanup(db)
