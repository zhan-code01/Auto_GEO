# -*- coding: utf-8 -*-
"""本地客户端 record-result 证据链集成测试(PG 门控)。

覆盖 docs/AutoGEO优化方案_2026-09.md 优化项六(引用证据链修复 P0):
- 三态 / capture_method 随 record-result 落库;
- 非法引用状态 400 拦截;
- 幂等命中时回填引用证据(旧记录无 raw_citations 而本次补传真实引用);
- _evaluate_record 把 citation_status 透传给判卷服务,引用字段不被 bool() 抹平。

这些测试不启动真实 Playwright、不调用外部 LLM(强制判卷走降级路径);
仅在 TEST_DATABASE_URL 指向 PostgreSQL 测试库时运行(否则跳过)。
"""

from datetime import datetime
import asyncio
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import client_geo_evaluation
from backend.api.user import get_current_user_from_token
from backend.database import Base, get_db
from backend.database.models import (
    Client,
    ClientDevice,
    GeoEvaluationRecord,
    GeoEvaluationRun,
    GeoPrompt,
    GeoPromptSet,
    Project,
    User,
)
from backend.services.geo_evaluation_analytics_service import GeoEvaluationAnalyticsService


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(client_geo_evaluation.router)
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
    # 背景判卷任务用自己的 SessionLocal 打开新会话
    monkeypatch.setattr(client_geo_evaluation, "SessionLocal", TestingSessionLocal)
    # 强制判卷走降级路径(无 API key 时 _llm_evaluate 立即抛错),避免测试期间真实外呼 LLM
    monkeypatch.setattr(
        "backend.services.geo_response_judge_service.AUTOGEO_CONVERSATION_LLM_API_KEY",
        "",
    )

    try:
        yield db
    finally:
        test_app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api_user(api_db):
    user = User(
        username="geo_client_user",
        email="geo_client_user@test.local",
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


def _build_graph(db, user):
    """Client → Project → PromptSet → Prompt → Device → Run(running,已 claim)。"""
    client = Client(name="证据链客户端", company_name="测试品牌", user_id=user.id)
    db.add(client)
    db.commit()
    db.refresh(client)

    project = Project(
        name="证据链项目",
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
        name="证据链问题集",
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
        client_id=client.id,
        question="测试品牌适合做 GEO 吗？",
        question_type="recommendation",
        sort_order=1,
        status="active",
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)

    device = ClientDevice(
        user_id=user.id,
        device_id="evidence_chain_device_1",
        device_name="测试机",
        status="online",
        last_seen_at=datetime.now(),
    )
    db.add(device)

    run = GeoEvaluationRun(
        client_id=client.id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        prompt_ids=[prompt.id],
        rounds=1,
        status="running",
        total_planned=1,
        created_by=user.id,
        claimed_device_id=device.device_id,
        heartbeat_at=datetime.now(),
        started_at=datetime.now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {
        "client": client,
        "project": project,
        "prompt_set": prompt_set,
        "prompt": prompt,
        "device": device,
        "run": run,
    }


def _record_body(graph, **overrides):
    base = {
        "device_id": graph["device"].device_id,
        "prompt_id": graph["prompt"].id,
        "platform": "doubao",
        "round_no": 1,
        "question": graph["prompt"].question,
        "success": True,
        "answer": "测试品牌是国内领先的 GEO 服务商。",
        "context_cleaned": True,
        "attempt_count": 1,
    }
    base.update(overrides)
    return base


def _load_record(db, graph):
    return db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.run_id == graph["run"].id).first()


def _run_background_eval(record_id: int) -> None:
    """显式驱动路由的 _evaluate_record 判卷,保证结果确定可断言。

    不依赖 TestClient 是否同步执行 background tasks;判卷在无 LLM key 时
    走降级路径(零外呼),是确定性的。
    """
    asyncio.run(client_geo_evaluation._evaluate_record(record_id))


def test_record_result_persists_tri_state_and_capture_method(api_db, api_user, api_client):
    graph = _build_graph(api_db, api_user)

    resp = api_client.post(
        f"/api/client/geo-evaluation/runs/{graph['run'].id}/record-result",
        json=_record_body(
            graph,
            citations=[],
            citation_status="empty",
            capture_method="dom",
        ),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["idempotent"] is False

    api_db.expire_all()
    record = _load_record(api_db, graph)
    assert record is not None
    assert record.citation_status == "empty"
    assert record.capture_method == "dom"
    assert record.success is True

    # 判卷(显式驱动)且引用三态不再被 bool() 抹平:empty → citation_supported False
    _run_background_eval(record.id)
    api_db.expire_all()
    record = _load_record(api_db, graph)
    assert record.evaluated_at is not None
    assert record.citation_supported is False
    assert record.own_source_cited is False


def test_record_result_persists_captured_real_citations(api_db, api_user, api_client):
    graph = _build_graph(api_db, api_user)
    citations = [{"url": "https://example.com/case", "domain": "example.com"}]

    resp = api_client.post(
        f"/api/client/geo-evaluation/runs/{graph['run'].id}/record-result",
        json=_record_body(
            graph,
            citations=citations,
            citation_status="captured",
            capture_method="dom",
        ),
    )
    assert resp.status_code == 200

    api_db.expire_all()
    record = _load_record(api_db, graph)
    assert record.citation_status == "captured"
    assert record.raw_citations == citations

    # 降级判卷同样尊重真实引用证据
    _run_background_eval(record.id)
    api_db.expire_all()
    record = _load_record(api_db, graph)
    assert record.citation_supported is True
    assert record.cited_urls == ["https://example.com/case"]


def test_record_result_rejects_invalid_citation_status(api_db, api_user, api_client):
    graph = _build_graph(api_db, api_user)

    resp = api_client.post(
        f"/api/client/geo-evaluation/runs/{graph['run'].id}/record-result",
        json=_record_body(graph, citation_status="made_up", capture_method="dom"),
    )
    assert resp.status_code == 400
    assert "非法引用状态" in resp.json()["detail"]


def test_record_result_idempotent_hit_backfills_citation_evidence(api_db, api_user, api_client):
    """旧记录无引用证据、本次补传真实引用 → 幂等命中回填 raw_citations/状态。"""
    graph = _build_graph(api_db, api_user)
    url = f"/api/client/geo-evaluation/runs/{graph['run'].id}/record-result"

    # 第一次:抓取成功但零条引用,不带 capture_method
    first = api_client.post(url, json=_record_body(graph, citations=[], citation_status="empty"))
    assert first.status_code == 200
    assert first.json()["data"]["idempotent"] is False

    # 第二次:同一 run/platform/round/prompt 补传真实引用(幂等命中)
    citations = [{"url": "https://example.com/doc", "domain": "example.com"}]
    second = api_client.post(
        url,
        json=_record_body(graph, citations=citations, citation_status="captured", capture_method="network"),
    )
    assert second.status_code == 200
    assert second.json()["data"]["idempotent"] is True

    api_db.expire_all()
    record = _load_record(api_db, graph)
    # 只有一条记录(幂等),且引用证据被回填
    assert api_db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.run_id == graph["run"].id).count() == 1
    assert record.raw_citations == citations
    assert record.citation_status == "captured"
    assert record.capture_method == "network"


def test_analytics_record_item_exposes_tri_state_fields(api_db, api_user, api_client):
    """报表侧记录项序列化需带 citation_status/capture_method,供前端区分三态。"""
    graph = _build_graph(api_db, api_user)
    api_client.post(
        f"/api/client/geo-evaluation/runs/{graph['run'].id}/record-result",
        json=_record_body(graph, citations=[], citation_status="empty", capture_method="dom"),
    )
    api_db.expire_all()

    analytics = GeoEvaluationAnalyticsService(db=api_db)
    result = analytics.get_records(project_id=graph["project"].id)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["citation_status"] == "empty"
    assert item["capture_method"] == "dom"
