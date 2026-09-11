from datetime import datetime

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.database.models import GeoArticle, Keyword, Project, User
from backend.services.agent_v2.adapters.article_adapter import ArticleAdapter


@pytest.fixture
def article_adapter_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    user = User(
        username="article_adapter_user",
        email="article_adapter_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.flush()
    project = Project(user_id=user.id, name="文章项目", company_name="文章公司", status=1)
    db.add(project)
    db.flush()
    keyword = Keyword(project_id=project.id, keyword="文章问题", status="active")
    db.add(keyword)
    db.flush()
    articles = [
        GeoArticle(
            user_id=user.id,
            project_id=project.id,
            keyword_id=keyword.id,
            title="已发布",
            content="正文",
            publish_status="published",
            created_at=datetime.now(),
        ),
        GeoArticle(
            user_id=user.id,
            project_id=project.id,
            keyword_id=keyword.id,
            title="已生成",
            content="正文",
            publish_status="completed",
            created_at=datetime.now(),
        ),
        GeoArticle(
            user_id=user.id,
            project_id=project.id,
            keyword_id=keyword.id,
            title="草稿",
            content="正文",
            publish_status="draft",
            created_at=datetime.now(),
        ),
        GeoArticle(
            user_id=user.id,
            project_id=project.id,
            keyword_id=keyword.id,
            title="空状态",
            content="正文",
            publish_status="draft",
            created_at=datetime.now(),
        ),
    ]
    db.add_all(articles)
    db.commit()
    db.execute(update(GeoArticle).where(GeoArticle.title == "空状态").values(publish_status=None))
    db.commit()

    try:
        yield db, user
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_article_adapter_accepts_string_published_status(article_adapter_context):
    db, user = article_adapter_context

    result = ArticleAdapter(db).list_articles(user, publish_status="published")

    assert result["total"] == 1
    assert [item["title"] for item in result["items"]] == ["已发布"]


def test_article_adapter_non_published_status_includes_null_status(article_adapter_context):
    db, user = article_adapter_context

    result = ArticleAdapter(db).list_articles(user, publish_status="draft")

    assert result["total"] == 3
    assert {item["title"] for item in result["items"]} == {"已生成", "草稿", "空状态"}
