# -*- coding: utf-8 -*-
"""旧发布 API（/api/publish/*）的用户归属隔离测试（IDOR 防护）。"""

import asyncio

import pytest

from backend.api.publish import (
    BatchPublishRequest,
    SchedulePublishRequest,
    StartPublishRequest,
    batch_publish_geo_articles,
    create_publish_task,
    get_publish_records,
    retry_publish,
    schedule_publish,
    start_publish_immediately,
    trigger_publish_immediately,
)
from backend.database.models import Account, GeoArticle, Keyword, Project, PublishRecord, User
from backend.schemas import PublishTaskCreate


def _make_user(db, username: str) -> User:
    user = User(username=username, email=f"{username}@example.test", password_hash="x", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_chain(db, user):
    project = Project(name="p_" + user.username, user_id=user.id, status=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    keyword = Keyword(project_id=project.id, keyword="kw", status="active")
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    article = GeoArticle(user_id=user.id, keyword_id=keyword.id, title="文章", content="正文")
    db.add(article)
    db.commit()
    db.refresh(article)
    account = Account(user_id=user.id, platform="zhihu", account_name="号", status=1)
    db.add(account)
    db.commit()
    db.refresh(account)
    return {"article": article, "account": account}


def _cleanup(db):
    db.rollback()
    db.query(PublishRecord).delete(synchronize_session=False)
    db.query(GeoArticle).delete(synchronize_session=False)
    db.query(Account).delete(synchronize_session=False)
    db.query(Keyword).delete(synchronize_session=False)
    db.query(Project).delete(synchronize_session=False)
    db.query(User).filter(User.username.like("ut_legacy_%")).delete(synchronize_session=False)
    db.commit()


def test_create_publish_task_other_users_article_rejected(clean_db):
    """用户 B 拿用户 A 的文章/账号创建发布任务 → 403（IDOR 防护）。"""
    db = clean_db
    try:
        alice = _make_user(db, "ut_legacy_alice")
        bob = _make_user(db, "ut_legacy_bob")
        a_chain = _make_chain(db, alice)

        with pytest.raises(Exception) as exc:
            asyncio.run(create_publish_task(
                PublishTaskCreate(article_ids=[a_chain["article"].id], account_ids=[a_chain["account"].id]),
                db=db, current_user=bob))
        assert exc.value.status_code == 403

        # 自己的文章/账号可以正常创建
        b_chain = _make_chain(db, bob)
        resp = asyncio.run(create_publish_task(
            PublishTaskCreate(article_ids=[b_chain["article"].id], account_ids=[b_chain["account"].id]),
            db=db, current_user=bob))
        assert resp.data["task_id"]
    finally:
        _cleanup(db)


def test_legacy_publish_endpoints_isolated_by_user(clean_db):
    """旧发布各端点的归属隔离：B 无法操作 A 的数据。"""
    db = clean_db
    try:
        alice = _make_user(db, "ut_legacy_carol")
        bob = _make_user(db, "ut_legacy_dave")
        a_chain = _make_chain(db, alice)

        # start / batch / schedule：B 用 A 的 id → 403
        for runner, req in [
            (start_publish_immediately, StartPublishRequest(
                article_ids=[a_chain["article"].id], account_ids=[a_chain["account"].id])),
            (batch_publish_geo_articles, BatchPublishRequest(
                article_ids=[a_chain["article"].id], account_ids=[a_chain["account"].id])),
            (schedule_publish, SchedulePublishRequest(
                article_ids=[a_chain["article"].id], account_ids=[a_chain["account"].id],
                scheduled_time="2099-01-01T00:00:00")),
        ]:
            with pytest.raises(Exception) as exc:
                asyncio.run(runner(req, db=db, current_user=bob))
            assert exc.value.status_code == 403

        # trigger：B 触发 A 的文章 → 403
        with pytest.raises(Exception) as exc:
            asyncio.run(trigger_publish_immediately(a_chain["article"].id, db=db, current_user=bob))
        assert exc.value.status_code == 403

        # records：B 看不到 A 的发布记录
        record = PublishRecord(article_id=a_chain["article"].id, account_id=a_chain["account"].id, publish_status=0)
        db.add(record)
        db.commit()
        records = asyncio.run(get_publish_records(db=db, current_user=bob, article_id=None, account_id=None, limit=50))
        assert records == []

        # retry：B 重试 A 的记录 → 403
        with pytest.raises(Exception) as exc:
            asyncio.run(retry_publish(record.id, db=db, current_user=bob))
        assert exc.value.status_code == 403
    finally:
        _cleanup(db)
