# -*- coding: utf-8 -*-
"""竞品与来源分析端点(份额口径 v2)集成测试(PG 门控)。

覆盖 docs/AutoGEO优化方案_2026-09.md §六 优化项2(P0 份额口径重写)的客户级端点
GET /api/geo-evaluation/clients/{id}/competitor-analysis 契约:
- metric_version==2 / legacy_metric_version==1 / 版本标注文案;
- 跨轮按 (run_id, question, platform) 去重 → total_units < total_records;
- answer_share 总和≈100、mention_rate 因多品牌同现总和可>100;
- 别名行把写法归一到规范名并命中我方/竞品根(is_own/is_competitor);
- empty/无原始证据行不进 qualified_citation_share,但计入普通 citation_share 域名;
- 旧 share 键(total_records/own_source_cited_count/own_source_rate)只读保留。

纯读端点、不启动判卷/外呼;仅在 TEST_DATABASE_URL 指向 PostgreSQL 测试库时运行(否则跳过)。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import geo_evaluation
from backend.api.user import get_current_user_from_token
from backend.database import Base, get_db
from backend.database.models import (
    Client,
    GeoBrandAlias,
    GeoEvaluationRecord,
    GeoEvaluationRun,
    GeoPrompt,
    GeoPromptSet,
    User,
)


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

    try:
        yield db
    finally:
        test_app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def api_user(api_db):
    user = User(
        username="geo_competitor_user",
        email="geo_competitor_user@test.local",
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
    """Client → PromptSet → Prompt(含竞品名单);两支 run(豆包/通义) + 客户级别名行。"""
    client = Client(name="竞品分析客户端", company_name="公司A", user_id=user.id)
    db.add(client)
    db.commit()
    db.refresh(client)

    prompt_set = GeoPromptSet(
        client_id=client.id,
        name="竞品分析问题集",
        question_count=1,
        status="frozen",
        created_by=user.id,
    )
    db.add(prompt_set)
    db.commit()
    db.refresh(prompt_set)

    prompt = GeoPrompt(
        prompt_set_id=prompt_set.id,
        client_id=client.id,
        question="公司A值得推荐吗？",
        question_type="recommendation",
        competitor_names=["公司B"],
        status="active",
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)

    run_doubao = GeoEvaluationRun(
        client_id=client.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=3,
        status="completed",
        created_by=user.id,
    )
    db.add(run_doubao)
    db.commit()
    db.refresh(run_doubao)

    run_qianwen = GeoEvaluationRun(
        client_id=client.id,
        phase="baseline",
        platforms=["qianwen"],
        rounds=1,
        status="completed",
        created_by=user.id,
    )
    db.add(run_qianwen)
    db.commit()
    db.refresh(run_qianwen)

    # 别名表(客户级):把自由写法归一到我方 / 竞品根
    db.add_all(
        [
            GeoBrandAlias(alias="A企业", canonical_name="公司A", client_id=client.id, project_id=None),
            GeoBrandAlias(alias="B品牌", canonical_name="公司B", client_id=client.id, project_id=None),
        ]
    )
    db.commit()

    return {"client": client, "prompt": prompt, "run_doubao": run_doubao, "run_qianwen": run_qianwen}


def _record(run, client, prompt, *, round_no, question, platform, matched_names, cited_domains=(), raw_citations=None, citation_status="captured", own_source_cited=False):
    return GeoEvaluationRecord(
        run_id=run.id,
        client_id=client.id,
        prompt_id=prompt.id,
        platform=platform,
        phase="baseline",
        round_no=round_no,
        question=question,
        answer=f"回答：{question}",
        success=True,
        matched_names=list(matched_names),
        cited_domains=list(cited_domains),
        raw_citations=list(raw_citations) if raw_citations else None,
        citation_status=citation_status,
        own_source_cited=own_source_cited,
    )


def _seed_records(db, graph):
    """豆包 run:同 Q1 三轮(去重折 1 单元);通义 run:Q2 单行(1 单元)。共 4 行 / 2 单元。"""
    rows = [
        # 单元A(doubao/Q1,3 轮):r1 双品牌+别名写法;r2 仅我方+自有引用;r3 竞品+未知+空引用
        _record(
            graph["run_doubao"], graph["client"], graph["prompt"],
            round_no=1, question="Q1", platform="doubao",
            matched_names=["公司A", "公司B", "A企业", "B品牌"],
            cited_domains=["a.com"],
            raw_citations=[{"url": "https://a.com/x", "domain": "a.com"}],
            citation_status="captured",
        ),
        _record(
            graph["run_doubao"], graph["client"], graph["prompt"],
            round_no=2, question="Q1", platform="doubao",
            matched_names=["公司A"],
            cited_domains=["a.com"],
            raw_citations=[{"domain": "a.com"}],
            citation_status="captured",
            own_source_cited=True,
        ),
        _record(
            graph["run_doubao"], graph["client"], graph["prompt"],
            round_no=3, question="Q1", platform="doubao",
            matched_names=["公司B", "c公司"],
            cited_domains=["x.com"],
            raw_citations=None,
            citation_status="empty",
        ),
        # 单元B(qianwen/Q2)
        _record(
            graph["run_qianwen"], graph["client"], graph["prompt"],
            round_no=1, question="Q2", platform="qianwen",
            matched_names=["公司A"],
            cited_domains=["b.com"],
            raw_citations=[{"domain": "b.com"}],
            citation_status="captured",
        ),
    ]
    db.add_all(rows)
    db.commit()


def _get_report(api_client, graph):
    resp = api_client.get(
        f"/api/geo-evaluation/clients/{graph['client'].id}/competitor-analysis",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    return body["data"]


def test_competitor_analysis_v2_contract(api_db, api_user, api_client):
    graph = _build_graph(api_db, api_user)
    _seed_records(api_db, graph)
    report = _get_report(api_client, graph)

    # 版本标注 + 计数:4 行 → 2 单元
    assert report["metric_version"] == 2
    assert report["legacy_metric_version"] == 1
    assert report["metric_version_label"] == "share_v2_four_metrics_dedup"
    assert "口径 v2" in report["metric_version_note"]
    assert report["total_records"] == 4
    assert report["total_units"] == 2
    assert report["company_name"] == "公司A"

    # 品牌:别名归一到规范名;answer_share 和≈100;mention_rate 和>100
    brand = {r["canonical"]: r for r in report["brand_shares"]}
    assert set(brand) == {"公司A", "公司B", "c公司"}
    assert brand["公司A"]["mentioned_units"] == 2
    assert round(sum(r["answer_share"] for r in report["brand_shares"]), 1) == 100.0
    assert sum(r["mention_rate"] for r in report["brand_shares"]) > 100.0
    assert brand["公司A"]["is_own"] is True and brand["公司A"]["is_competitor"] is False
    assert brand["公司B"]["is_competitor"] is True
    assert brand["c公司"]["is_own"] is False and brand["c公司"]["is_competitor"] is False

    # 别名有效性:品牌通过别名行计入(legacy mentions 含 A企业/B品牌 归一)
    assert brand["公司A"]["mentions"] == 4
    assert brand["公司B"]["mentions"] == 3

    # 自有来源引用率:单元级 50%(仅豆包单元);旧行级 25%(4 行中 1 行)
    assert report["own_source_cited_units"] == 1
    assert report["own_source_unit_rate"] == 50.0
    assert report["own_source_cited_count"] == 1
    assert report["own_source_rate"] == 25.0

    # 域名:普通份额计 a/x/b 三域名各≈33.3;qualified 仅 captured+有原始证据的 a.com/b.com
    dom = {r["domain"]: r for r in report["top_domains"]}
    assert set(dom) == {"a.com", "x.com", "b.com"}
    for drow in report["top_domains"]:
        assert drow["citation_share"] == pytest.approx(33.3, abs=0.1)
    assert dom["a.com"]["qualified_cited_units"] == 1
    assert dom["a.com"]["qualified_citation_share"] == 50.0
    assert dom["b.com"]["qualified_citation_share"] == 50.0
    assert dom["x.com"]["qualified_cited_units"] == 0
    assert dom["x.com"]["qualified_citation_share"] == 0.0

    # 分平台:豆包块 3 行折 1 单元并带 legacy_total 防静默重定义
    by = {b["platform"]: b for b in report["by_platform"]}
    assert set(by) == {"doubao", "qianwen"}
    assert by["doubao"]["total"] == 1 and by["doubao"]["legacy_total"] == 3
    assert by["qianwen"]["total"] == 1 and by["qianwen"]["legacy_total"] == 1
    assert by["doubao"]["own_source_cited_units"] == 1
    assert by["doubao"]["own_source_unit_rate"] == 100.0
    assert by["qianwen"]["own_source_cited_units"] == 0


def test_competitor_analysis_missing_client_guard(api_db, api_user, api_client):
    resp = api_client.get("/api/geo-evaluation/clients/999999/competitor-analysis")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "公司不存在"


def test_competitor_analysis_empty_records_empty_report(api_db, api_user, api_client):
    graph = _build_graph(api_db, api_user)
    report = _get_report(api_client, graph)
    assert report["total_records"] == 0
    assert report["total_units"] == 0
    assert report["brand_shares"] == []
    assert report["top_domains"] == []
    assert report["own_source_unit_rate"] == 0.0
