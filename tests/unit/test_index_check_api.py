from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import index_check
from backend.api.user import get_current_user_from_token
from backend.database import Base, get_db
from backend.database.models import IndexCheckRecord, Keyword, Project, User
from backend.services.index_check_service import IndexCheckService


@pytest.fixture
def index_check_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    app = FastAPI()
    app.include_router(index_check.router)
    app.dependency_overrides[get_db] = lambda: db

    user = User(
        username="index_check_user",
        email="index_check_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.flush()
    first_project = Project(user_id=user.id, name="项目一", company_name="公司一", status=1)
    second_project = Project(user_id=user.id, name="项目二", company_name="公司二", status=1)
    db.add_all([first_project, second_project])
    db.commit()
    db.refresh(first_project)
    db.refresh(second_project)

    app.dependency_overrides[get_current_user_from_token] = lambda: user

    try:
        yield TestClient(app), db, user, first_project, second_project
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _platform_result(total, keyword_found, company_found, success_count):
    hit_rate = round((keyword_found + company_found) / (total * 2) * 100, 2)
    keyword_pct = round(keyword_found / total * 100, 2)
    company_pct = round(company_found / total * 100, 2)
    success_rate = round(success_count / total * 100, 2)
    return {
        "platforms": [
            {
                "platform": "doubao",
                "platform_name": "豆包",
                "total_checks": total,
                "hit_rate": hit_rate,
                "keyword_pct": keyword_pct,
                "company_pct": company_pct,
                "success_rate": success_rate,
                "status": "warning" if hit_rate <= 60 else "good",
            }
        ],
        "summary": {
            "total_platforms": 1,
            "total_checks": total,
            "avg_success_rate": success_rate,
        },
    }


def test_platform_performance_merges_same_platform_across_projects(index_check_context, monkeypatch):
    client, _db, _user, first_project, second_project = index_check_context

    first_result = _platform_result(total=2, keyword_found=1, company_found=1, success_count=1)
    second_result = _platform_result(total=3, keyword_found=2, company_found=1, success_count=2)

    def fake_get_platform_performance(self, project_id=None, days=7, project_ids=None):
        if project_ids is not None:
            assert project_ids == [first_project.id, second_project.id]
            return {
                "platforms": [
                    {
                        "platform": "doubao",
                        "platform_name": "豆包",
                        "total_checks": 5,
                        "hit_rate": 50.0,
                        "keyword_pct": 60.0,
                        "company_pct": 40.0,
                        "success_rate": 60.0,
                        "status": "warning",
                    }
                ],
                "summary": {"total_platforms": 1, "total_checks": 5, "avg_success_rate": 60.0},
            }
        if project_id == first_project.id:
            return first_result
        if project_id == second_project.id:
            return second_result
        raise AssertionError(f"unexpected project_id={project_id}")

    monkeypatch.setattr(IndexCheckService, "get_platform_performance", fake_get_platform_performance)

    response = client.get("/api/index-check/platforms/performance")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "platforms": [
            {
                "platform": "doubao",
                "platform_name": "豆包",
                "total_checks": 5,
                "hit_rate": 50.0,
                "keyword_pct": 60.0,
                "company_pct": 40.0,
                "success_rate": 60.0,
                "status": "warning",
            }
        ],
        "summary": {"total_platforms": 1, "total_checks": 5, "avg_success_rate": 60.0},
    }


def test_platform_performance_service_aggregates_project_collection(index_check_context):
    _client, db, _user, first_project, second_project = index_check_context
    first_keyword = Keyword(project_id=first_project.id, keyword="问题一", status="active")
    second_keyword = Keyword(project_id=second_project.id, keyword="问题二", status="active")
    db.add_all([first_keyword, second_keyword])
    db.flush()
    db.add_all(
        [
            IndexCheckRecord(
                keyword_id=first_keyword.id,
                platform="doubao",
                question="问题一",
                answer="回答",
                keyword_found=True,
                company_found=False,
                check_time=datetime.now(),
            ),
            IndexCheckRecord(
                keyword_id=first_keyword.id,
                platform="doubao",
                question="问题一",
                answer=None,
                keyword_found=False,
                company_found=True,
                check_time=datetime.now(),
            ),
            IndexCheckRecord(
                keyword_id=second_keyword.id,
                platform="doubao",
                question="问题二",
                answer="回答",
                keyword_found=True,
                company_found=True,
                check_time=datetime.now(),
            ),
            IndexCheckRecord(
                keyword_id=second_keyword.id,
                platform="doubao",
                question="问题二",
                answer="回答",
                keyword_found=True,
                company_found=False,
                check_time=datetime.now(),
            ),
            IndexCheckRecord(
                keyword_id=second_keyword.id,
                platform="doubao",
                question="问题二",
                answer=None,
                keyword_found=False,
                company_found=False,
                check_time=datetime.now(),
            ),
        ]
    )
    db.commit()

    result = IndexCheckService(db).get_platform_performance(project_ids=[first_project.id, second_project.id])

    assert result == {
        "platforms": [
            {
                "platform": "doubao",
                "platform_name": "豆包",
                "total_checks": 5,
                "hit_rate": 50.0,
                "keyword_pct": 60.0,
                "company_pct": 40.0,
                "success_rate": 60.0,
                "status": "warning",
            }
        ],
        "summary": {"total_platforms": 1, "total_checks": 5, "avg_success_rate": 60.0},
    }


def test_platform_performance_without_projects_keeps_response_shape(index_check_context):
    client, db, _user, _first_project, _second_project = index_check_context
    no_project_user = User(
        username="index_check_empty_user",
        email="index_check_empty_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(no_project_user)
    db.commit()
    client.app.dependency_overrides[get_current_user_from_token] = lambda: no_project_user

    response = client.get("/api/index-check/platforms/performance")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "platforms": [],
        "summary": {"total_platforms": 0, "total_checks": 0, "avg_success_rate": 0},
    }
