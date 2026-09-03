# -*- coding: utf-8 -*-
"""GEO 五指标 API 合约测试。

这些测试不启动真实 Playwright，也不调用外部 LLM；只验证路由、权限、
请求校验、run 创建和状态查询契约。真实平台检测由页面触发后在后台执行。
"""

from datetime import datetime
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import geo_evaluation
from backend.api.user import get_current_user_from_token
from backend.database import Base, get_db
from backend.database.models import Client, GeoEvaluationRecord, GeoEvaluationRun, GeoPrompt, GeoPromptSet, Project, User


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(geo_evaluation.router)
    return app


@pytest.fixture
def api_db(monkeypatch, test_app):
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if not test_database_url or not test_database_url.lower().startswith(("postgresql://", "postgresql+")):
        pytest.skip("TEST_DATABASE_URL must point to a PostgreSQL test database")
    if "test" not in test_database_url.lower():
        pytest.skip("Refusing to run destructive schema tests outside a test database")

    engine = create_engine(test_database_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(geo_evaluation, "SessionLocal", TestingSessionLocal)

    try:
        yield db
    finally:
        test_app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api_user(api_db):
    user = User(
        username="geo_api_user",
        email="geo_api_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    api_db.add(user)
    api_db.commit()
    api_db.refresh(user)
    return user


@pytest.fixture
def api_client(test_app, api_user):
    test_app.dependency_overrides[get_current_user_from_token] = lambda: api_user
    return TestClient(test_app)


def _make_project_with_prompt(db, user):
    client = Client(name="GEO API Client", company_name="Test Brand", user_id=user.id)
    db.add(client)
    db.commit()
    db.refresh(client)

    project = Project(
        name="GEO API 项目",
        company_name="测试品牌",
        domain_keyword="example.com",
        status=1,
        user_id=user.id,
        client_id=client.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    prompt_set = GeoPromptSet(
        client_id=client.id,
        project_id=project.id,
        name="API 测试问题集",
        question_count=1,
        status="frozen",
        frozen_at=datetime.now(),
        created_by=user.id,
    )
    db.add(prompt_set)
    db.commit()
    db.refresh(prompt_set)

    prompt = GeoPrompt(
        prompt_set_id=prompt_set.id,
        project_id=project.id,
        question="测试品牌适合做 GEO 吗？",
        question_type="recommendation",
        sort_order=1,
    )
    db.add(prompt)
    db.commit()
    return project


def test_create_baseline_api_creates_run_without_starting_real_playwright(api_db, api_user, api_client, monkeypatch):
    project = _make_project_with_prompt(api_db, api_user)
    started = []

    def fake_start_background_run(**kwargs):
        started.append(kwargs)

    monkeypatch.setattr("backend.services.geo_evaluation_run_service._start_background_run", fake_start_background_run)
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
        lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
    )

    response = api_client.post(
        f"/api/geo-evaluation/projects/{project.id}/baseline",
        json={"platforms": ["doubao"], "rounds": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["run_id"] > 0
    assert body["data"]["total_planned"] == 1
    assert started and started[0]["user_id"] == api_user.id
    assert started[0]["platforms"] == ["doubao"]


def test_geo_api_validates_rounds(api_db, api_user, api_client):
    project = _make_project_with_prompt(api_db, api_user)

    response = api_client.post(
        f"/api/geo-evaluation/projects/{project.id}/recheck",
        json={"platforms": ["doubao"], "rounds": 4},
    )

    assert response.status_code == 422


def test_geo_api_rejects_multiple_platforms_in_one_run(api_db, api_user, api_client):
    project = _make_project_with_prompt(api_db, api_user)

    response = api_client.post(
        f"/api/geo-evaluation/projects/{project.id}/baseline",
        json={"platforms": ["doubao", "qianwen"], "rounds": 1},
    )

    assert response.status_code == 422


def test_run_status_requires_project_owner(api_db, api_user, api_client, monkeypatch):
    project = _make_project_with_prompt(api_db, api_user)
    monkeypatch.setattr("backend.services.geo_evaluation_run_service._start_background_run", lambda **kwargs: None)
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
        lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
    )
    create_response = api_client.post(
        f"/api/geo-evaluation/projects/{project.id}/baseline",
        json={"platforms": ["doubao"], "rounds": 1},
    )
    run_id = create_response.json()["data"]["run_id"]

    other = User(
        username="geo_api_other",
        email="geo_api_other@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    api_db.add(other)
    api_db.commit()
    api_db.refresh(other)
    api_client.app.dependency_overrides[get_current_user_from_token] = lambda: other

    response = api_client.get(f"/api/geo-evaluation/runs/{run_id}/status")

    assert response.status_code == 403


def test_latest_client_run_filters_by_platform(api_db, api_user, api_client):
    client = Client(name="GEO Client", company_name="测试品牌", user_id=api_user.id)
    api_db.add(client)
    api_db.commit()
    api_db.refresh(client)

    prompt_set = GeoPromptSet(
        client_id=client.id,
        name="Client Prompt Set",
        question_count=1,
        status="frozen",
        frozen_at=datetime.now(),
        created_by=api_user.id,
    )
    api_db.add(prompt_set)
    api_db.commit()
    api_db.refresh(prompt_set)

    doubao_run = GeoEvaluationRun(
        client_id=client.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="running",
        total_planned=100,
        total_completed=0,
        total_failed=0,
        current_progress=0,
        created_by=api_user.id,
    )
    qianwen_run = GeoEvaluationRun(
        client_id=client.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["qianwen"],
        rounds=1,
        status="pending",
        total_planned=100,
        total_completed=12,
        total_failed=0,
        current_progress=12,
        created_by=api_user.id,
    )
    api_db.add_all([doubao_run, qianwen_run])
    api_db.commit()

    qianwen_response = api_client.get(
        f"/api/geo-evaluation/clients/{client.id}/runs/latest",
        params={"platform": "qianwen", "prompt_set_id": prompt_set.id},
    )
    doubao_response = api_client.get(
        f"/api/geo-evaluation/clients/{client.id}/runs/latest",
        params={"platform": "doubao", "prompt_set_id": prompt_set.id},
    )

    assert qianwen_response.status_code == 200
    assert qianwen_response.json()["data"]["platforms"] == ["qianwen"]
    assert qianwen_response.json()["data"]["total_completed"] == 12
    assert doubao_response.status_code == 200
    assert doubao_response.json()["data"]["platforms"] == ["doubao"]


def test_clear_geo_evaluation_records_deletes_project_records_and_runs(api_db, api_user, api_client):
    project = _make_project_with_prompt(api_db, api_user)
    run = GeoEvaluationRun(
        client_id=project.client_id,
        project_id=project.id,
        prompt_set_id=project.geo_prompt_sets[0].id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="completed",
        total_planned=1,
        total_completed=1,
        total_failed=0,
        current_progress=1,
        created_by=api_user.id,
    )
    api_db.add(run)
    api_db.commit()
    api_db.refresh(run)
    prompt = project.geo_prompt_sets[0].prompts[0]
    api_db.add(
            GeoEvaluationRecord(
                run_id=run.id,
                client_id=project.client_id,
                project_id=project.id,
            prompt_set_id=project.geo_prompt_sets[0].id,
            prompt_id=prompt.id,
            platform="doubao",
            phase="baseline",
            round_no=1,
            question=prompt.question,
            answer="ok",
            success=True,
            schema_version="1.0.0",
        )
    )
    api_db.commit()

    response = api_client.delete(f"/api/geo-evaluation/projects/{project.id}/records")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["deleted_records"] == 1
    assert body["data"]["deleted_runs"] == 1
    assert api_db.query(GeoEvaluationRecord).count() == 0
    assert api_db.query(GeoEvaluationRun).count() == 0


def test_retry_failed_geo_records_creates_retry_run(api_db, api_user, api_client, monkeypatch):
    project = _make_project_with_prompt(api_db, api_user)
    prompt_set = project.geo_prompt_sets[0]
    prompt = prompt_set.prompts[0]
    run = GeoEvaluationRun(
        client_id=project.client_id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="completed",
        total_planned=1,
        total_completed=0,
        total_failed=1,
        current_progress=1,
        created_by=api_user.id,
    )
    api_db.add(run)
    api_db.commit()
    api_db.refresh(run)
    record = GeoEvaluationRecord(
        run_id=run.id,
        client_id=project.client_id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        prompt_id=prompt.id,
        platform="doubao",
        phase="baseline",
        round_no=1,
        question=prompt.question,
        success=False,
        error_message="[empty] no answer",
        schema_version="1.0.0",
    )
    api_db.add(record)
    api_db.commit()
    api_db.refresh(record)
    started = []

    monkeypatch.setattr("backend.services.geo_evaluation_run_service._start_background_run", lambda **kwargs: started.append(kwargs))
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
        lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
    )

    response = api_client.post(
        f"/api/geo-evaluation/projects/{project.id}/records/retry",
        json={"record_ids": [record.id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["run_id"] > run.id
    assert started and started[0]["platforms"] == ["doubao"]
    assert started[0]["prompt_ids"] == [prompt.id]


def test_client_records_can_filter_failed_only(api_db, api_user, api_client):
    project = _make_project_with_prompt(api_db, api_user)
    prompt_set = project.geo_prompt_sets[0]
    prompt = prompt_set.prompts[0]
    run = GeoEvaluationRun(
        client_id=project.client_id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="completed",
        total_planned=2,
        total_completed=1,
        total_failed=1,
        current_progress=2,
        created_by=api_user.id,
    )
    api_db.add(run)
    api_db.commit()
    api_db.refresh(run)
    api_db.add_all(
        [
            GeoEvaluationRecord(
                run_id=run.id,
                client_id=project.client_id,
                project_id=project.id,
                prompt_set_id=prompt_set.id,
                prompt_id=prompt.id,
                platform="doubao",
                phase="baseline",
                round_no=1,
                question=prompt.question,
                answer="ok",
                success=True,
                schema_version="1.0.0",
            ),
            GeoEvaluationRecord(
                run_id=run.id,
                client_id=project.client_id,
                project_id=project.id,
                prompt_set_id=prompt_set.id,
                prompt_id=prompt.id,
                platform="doubao",
                phase="baseline",
                round_no=1,
                question=prompt.question,
                success=False,
                error_message="[empty] no answer",
                schema_version="1.0.0",
            ),
        ]
    )
    api_db.commit()

    response = api_client.get(
        f"/api/geo-evaluation/clients/{project.client_id}/records",
        params={"success": "false"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["success"] is False
