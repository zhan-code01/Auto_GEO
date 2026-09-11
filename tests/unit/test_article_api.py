from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from backend.api import article
from backend.api.user import get_current_user_from_token
from backend.database import Base, get_db
from backend.database.models import Keyword, Project, User


@pytest.fixture
def article_api_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    app = FastAPI()
    app.include_router(article.router)
    app.dependency_overrides[get_db] = lambda: db

    user = User(
        username="article_api_user",
        email="article_api_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(user_id=user.id, name="文章项目", company_name="测试公司", status=1)
    db.add(project)
    db.flush()

    keyword = Keyword(id=30, project_id=project.id, keyword="文章关键词", status="active")
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    app.dependency_overrides[get_current_user_from_token] = lambda: user

    try:
        yield TestClient(app), db, user, project, keyword
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_create_article_uses_requested_keyword_and_project(article_api_context):
    client, db, _user, project, keyword = article_api_context

    response = client.post(
        "/api/articles",
        json={
            "keyword_id": keyword.id,
            "title": "手动文章",
            "content": "文章正文",
            "status": 0,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["keyword_id"] == keyword.id
    assert data["project_id"] == project.id

    created = db.query(article.GeoArticle).filter(article.GeoArticle.id == data["id"]).one()
    assert created.keyword_id == keyword.id
    assert created.project_id == project.id


def test_create_article_rejects_keyword_from_another_users_project(article_api_context):
    client, db, _user, _project, _keyword = article_api_context

    other_user = User(
        username="article_api_other_user",
        email="article_api_other_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(other_user)
    db.flush()
    other_project = Project(user_id=other_user.id, name="其他项目", company_name="其他公司", status=1)
    db.add(other_project)
    db.flush()
    other_keyword = Keyword(project_id=other_project.id, keyword="其他关键词", status="active")
    db.add(other_keyword)
    db.commit()
    db.refresh(other_keyword)

    response = client.post(
        "/api/articles",
        json={"keyword_id": other_keyword.id, "title": "不应创建", "content": "正文"},
    )

    assert response.status_code == 404
    assert "无权访问" in response.json()["detail"]
    assert db.query(article.GeoArticle).filter(article.GeoArticle.title == "不应创建").count() == 0


def test_create_article_without_keyword_uses_current_users_active_keyword(article_api_context):
    client, _db, _user, project, keyword = article_api_context

    response = client.post(
        "/api/articles",
        json={"title": "兼容旧调用", "content": "正文", "status": 0},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["keyword_id"] == keyword.id
    assert data["project_id"] == project.id
