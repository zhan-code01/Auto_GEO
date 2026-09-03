# -*- coding: utf-8 -*-
"""
发布原子抢占回归测试。

背景：调度器每分钟扫描 scheduled 文章并派发后台发布任务；任务内部原先把状态
scheduled→publishing 延迟了 5-10 秒才写入，扫描窗口内同一篇文章会被重复派发，
导致并发重复发布。修复后由 claim_scheduled_for_publish 用单条原子 UPDATE 抢占，
抢不到的任务必须跳过。
"""

from backend.database import SessionLocal
from backend.database.models import GeoArticle, Keyword, Project
from backend.services.geo_article_service import GeoArticleService


def _make_scheduled_article(db, project):
    keyword = Keyword(
        project_id=project.id,
        keyword="并发抢占测试关键词",
        difficulty_score=50,
        status="active",
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    article = GeoArticle(
        keyword_id=keyword.id,
        project_id=project.id,
        title="并发抢占测试文章",
        content="正文",
        publish_status="scheduled",
        platform="zhihu",
        account_id=None,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def _make_project(db, suffix=""):
    project = Project(name=f"抢占测试项目{suffix}", company_name="测试公司", status=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_claim_marks_article_publishing(clean_db):
    """第一次抢占成功：状态从 scheduled 变为 publishing。"""
    project = _make_project(clean_db, "A")
    article = _make_scheduled_article(clean_db, project)

    service = GeoArticleService(clean_db)
    assert service.claim_scheduled_for_publish(article.id) is True

    clean_db.refresh(article)
    assert article.publish_status == "publishing"
    assert article.error_msg is None


def test_second_claim_returns_false(clean_db):
    """模拟并发场景：第二个任务抢占已被占的文章必须失败。"""
    project = _make_project(clean_db, "B")
    article = _make_scheduled_article(clean_db, project)

    first = GeoArticleService(clean_db)
    assert first.claim_scheduled_for_publish(article.id) is True

    # 第二个任务使用独立 Session（与后台任务各持独立连接的模型一致）
    second = GeoArticleService(SessionLocal())
    try:
        assert second.claim_scheduled_for_publish(article.id) is False
    finally:
        second.db.close()

    clean_db.refresh(article)
    assert article.publish_status == "publishing"


def test_claim_on_non_scheduled_returns_false(clean_db):
    """已发布/草稿状态的文章不可被抢占（不破坏既有状态机）。"""
    project = _make_project(clean_db, "C")
    article = _make_scheduled_article(clean_db, project)
    article.publish_status = "published"
    clean_db.commit()

    service = GeoArticleService(clean_db)
    assert service.claim_scheduled_for_publish(article.id) is False

    clean_db.refresh(article)
    assert article.publish_status == "published"
