# -*- coding: utf-8 -*-
"""报表 API 集成测试。

测试使用专用 PostgreSQL 数据库、真实后端进程和 JWT 认证，覆盖当前报表页
仍使用的三个接口：``article-stats``、``stats`` 和 ``overview``。
"""

from __future__ import annotations

from datetime import datetime
import uuid

import pytest
import requests

from backend.api.user import create_access_token
from backend.database.models import GeoArticle, IndexCheckRecord, Keyword, Project, User


BASE_URL = "http://127.0.0.1:8001/api/reports"


@pytest.fixture(scope="module")
def reports_context(backend_server, db):
    """创建本模块专用用户和最小报表数据集。"""
    suffix = uuid.uuid4().hex[:12]
    user = User(
        username=f"reports_{suffix}",
        email=f"reports_{suffix}@example.test",
        password_hash="test-only",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    project = Project(
        user_id=user.id,
        name=f"报表项目_{suffix}",
        company_name="报表测试公司",
        status=1,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    keyword = Keyword(project_id=project.id, keyword="报表测试问题", status="active")
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    article = GeoArticle(
        user_id=user.id,
        project_id=project.id,
        keyword_id=keyword.id,
        title="报表测试文章",
        content="报表测试正文",
        publish_status="published",
        publish_time=datetime.now(),
    )
    record = IndexCheckRecord(
        keyword_id=keyword.id,
        platform="doubao",
        question="报表测试问题",
        answer="报表测试回答",
        keyword_found=True,
        company_found=True,
        check_time=datetime.now(),
    )
    db.add_all([article, record])
    db.commit()

    assert user.id is not None
    assert project.id is not None
    token = create_access_token(user.id, user.username)
    context = {
        "headers": {"Authorization": f"Bearer {token}"},
        "project_id": project.id,
    }

    yield context

    db.rollback()
    db.query(IndexCheckRecord).filter(IndexCheckRecord.keyword_id == keyword.id).delete(
        synchronize_session=False
    )
    db.query(GeoArticle).filter(GeoArticle.keyword_id == keyword.id).delete(synchronize_session=False)
    db.query(Keyword).filter(Keyword.id == keyword.id).delete(synchronize_session=False)
    db.query(Project).filter(Project.id == project.id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db.commit()


def _request(context: dict, method: str, endpoint: str, **kwargs):
    headers = dict(context["headers"])
    headers.update(kwargs.pop("headers", {}))
    return requests.request(
        method,
        f"{BASE_URL}{endpoint}",
        headers=headers,
        timeout=10,
        **kwargs,
    )


def test_article_stats_returns_current_user_data(reports_context):
    response = _request(reports_context, "GET", "/article-stats")

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "generating": 0,
        "completed": 0,
        "published": 1,
        "failed": 0,
        "ready_to_publish": 0,
    }


def test_article_stats_supports_project_filter(reports_context):
    response = _request(
        reports_context,
        "GET",
        "/article-stats",
        params={"project_id": reports_context["project_id"]},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_stats_returns_dashboard_contract(reports_context):
    response = _request(reports_context, "GET", "/stats", params={"days": 7})

    assert response.status_code == 200
    assert response.json() == {
        "total_articles": 1,
        "common_articles": 0,
        "geo_articles": 1,
        "publish_success_rate": 100.0,
        "publish_success_count": 1,
        "publish_total_count": 1,
        "keyword_hit_rate": 100.0,
        "keyword_hit_count": 1,
        "keyword_check_count": 1,
        "company_hit_rate": 100.0,
        "company_hit_count": 1,
        "company_check_count": 1,
    }


def test_stats_supports_project_and_days_filters(reports_context):
    response = _request(
        reports_context,
        "GET",
        "/stats",
        params={"project_id": reports_context["project_id"], "days": 30},
    )

    assert response.status_code == 200
    assert response.json()["total_articles"] == 1


def test_overview_returns_hit_rate_contract(reports_context):
    response = _request(reports_context, "GET", "/overview")

    assert response.status_code == 200
    assert response.json() == {
        "total_keywords": 1,
        "keyword_found": 1,
        "company_found": 1,
        "overall_hit_rate": 100.0,
    }


def test_current_report_endpoint_requires_jwt(backend_server):
    response = requests.get(f"{BASE_URL}/stats", timeout=10)

    assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
