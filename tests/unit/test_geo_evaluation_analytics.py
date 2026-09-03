# -*- coding: utf-8 -*-
"""GEO 五指标聚合分析单元测试。

覆盖 docs/收录监控模块GEO五指标测评实施方案.md 中的核心口径：
- 五指标聚合公式；
- 可见度按出现覆盖率、推荐排名、情感分三项计算；
- sentiment_score 只统计已提及品牌的回答；
- diagnosis verdict；
- 只把 baseline 和 current 均存在的平台列入可比平台。
"""

from datetime import datetime, timedelta
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.database.models import (
    GeoEvaluationRecord,
    GeoEvaluationRun,
    GeoPrompt,
    GeoPromptSet,
    Project,
    User,
)
from backend.services.geo_evaluation_analytics_service import GeoEvaluationAnalyticsService


@pytest.fixture
def local_db():
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if not test_database_url or not test_database_url.lower().startswith(("postgresql://", "postgresql+")):
        pytest.skip("TEST_DATABASE_URL must point to a PostgreSQL test database")
    if "test" not in test_database_url.lower():
        pytest.skip("Refusing to run destructive schema tests outside a test database")

    engine = create_engine(test_database_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _record(
    *,
    success=True,
    answer="answer",
    brand_mentioned=False,
    ranking_score=0,
    citation_supported=False,
    own_source_cited=False,
    sentiment_score=0,
    question="行业里有哪些服务商值得推荐？",
    question_type="recommendation",
):
    return SimpleNamespace(
        success=success,
        answer=answer,
        brand_mentioned=brand_mentioned,
        ranking_score=ranking_score,
        citation_supported=citation_supported,
        own_source_cited=own_source_cited,
        sentiment_score=sentiment_score,
        question=question,
        question_type=question_type,
    )


def test_aggregate_geo_five_metrics():
    analytics = GeoEvaluationAnalyticsService(db=None)

    result = analytics._aggregate(
        [
            _record(
                brand_mentioned=True,
                ranking_score=100,
                citation_supported=True,
                own_source_cited=True,
                sentiment_score=80,
            ),
            _record(
                brand_mentioned=True,
                ranking_score=60,
                citation_supported=True,
                own_source_cited=False,
                sentiment_score=50,
            ),
            _record(
                brand_mentioned=False,
                ranking_score=0,
                citation_supported=False,
                sentiment_score=0,
            ),
            _record(success=True, answer=None, brand_mentioned=True, ranking_score=100, sentiment_score=100),
            _record(success=False, answer="failed", brand_mentioned=True, ranking_score=100, sentiment_score=100),
        ]
    )

    assert result["answer_count"] == 5
    assert result["valid_count"] == 3
    assert result["coverage_rate"] == 66.67
    assert result["ranking_score"] == 53.33
    assert result["sentiment_score"] == 65.0
    assert result["visibility_score"] == 62


def test_aggregate_uses_four_metric_model_and_sentiment_only_counts_mentions():
    analytics = GeoEvaluationAnalyticsService(db=None)

    result = analytics._aggregate(
        [
            _record(
                brand_mentioned=True,
                ranking_score=100,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=80,
            ),
            _record(
                brand_mentioned=False,
                ranking_score=0,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=0,
            ),
        ]
    )

    assert result["coverage_rate"] == 50.0
    assert result["ranking_score"] == 50.0
    assert result["sentiment_score"] == 80.0
    assert result["visibility_score"] == 58


def test_aggregate_excludes_direct_brand_questions_from_main_metrics():
    analytics = GeoEvaluationAnalyticsService(db=None)

    result = analytics._aggregate(
        [
            _record(
                brand_mentioned=True,
                ranking_score=100,
                sentiment_score=80,
                question="测试品牌靠谱吗？",
                question_type="reputation",
            ),
            _record(
                brand_mentioned=True,
                ranking_score=100,
                sentiment_score=80,
                question="测试品牌适合做 GEO 吗？",
                question_type="recommendation",
            ),
            _record(
                brand_mentioned=False,
                ranking_score=0,
                sentiment_score=0,
                question="GEO 服务商有哪些值得推荐？",
                question_type="recommendation",
            ),
        ],
        company_name="测试品牌",
    )

    assert result["answer_count"] == 3
    assert result["valid_count"] == 1
    assert result["sentiment_valid_count"] == 2
    assert result["excluded_direct_count"] == 2
    assert result["coverage_rate"] == 0
    assert result["ranking_score"] == 0
    assert result["sentiment_score"] == 80
    assert result["visibility_score"] == 20


def test_aggregate_can_keep_direct_brand_questions_for_type_breakdown():
    analytics = GeoEvaluationAnalyticsService(db=None)

    result = analytics._aggregate(
        [
            _record(
                brand_mentioned=True,
                ranking_score=100,
                sentiment_score=80,
                question="测试品牌靠谱吗？",
                question_type="reputation",
            )
        ],
        company_name="测试品牌",
        exclude_direct_brand_questions=False,
    )

    assert result["valid_count"] == 1
    assert result["sentiment_valid_count"] == 1
    assert result["excluded_direct_count"] == 0
    assert result["coverage_rate"] == 100
    assert result["ranking_score"] == 100
    assert result["sentiment_score"] == 80


def _make_project_with_prompt(db):
    marker = f"geo_eval_{int(datetime.now().timestamp() * 1000)}"
    user = User(
        username=marker,
        email=f"{marker}@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    project = Project(
        name=f"{marker} 项目",
        company_name="测试品牌",
        domain_keyword="GEO 测评",
        status=1,
        user_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    prompt_set = GeoPromptSet(
        project_id=project.id,
        name="冻结问题集",
        question_count=100,
        status="frozen",
        frozen_at=datetime.now() - timedelta(days=2),
        created_by=user.id,
    )
    db.add(prompt_set)
    db.commit()
    db.refresh(prompt_set)

    prompt = GeoPrompt(
        prompt_set_id=prompt_set.id,
        project_id=project.id,
        question="GEO 服务商有哪些值得推荐？",
        question_type="recommendation",
        sort_order=1,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)

    return user, project, prompt_set, prompt


def _make_run(db, project, prompt_set, *, phase, platforms):
    run = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase=phase,
        platforms=platforms,
        rounds=3,
        status="completed",
        total_planned=30,
        total_completed=30,
        evaluation_schema_version="1.0.0",
        created_at=datetime.now() - timedelta(days=2 if phase == "baseline" else 0),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _add_eval_record(
    db,
    *,
    run,
    project,
    prompt_set,
    prompt,
    phase,
    platform,
    brand_mentioned,
    ranking_score,
    citation_supported,
    own_source_cited,
    sentiment_score,
    created_at,
):
    db.add(
        GeoEvaluationRecord(
            run_id=run.id,
            project_id=project.id,
            prompt_set_id=prompt_set.id,
            prompt_id=prompt.id,
            platform=platform,
            phase=phase,
            round_no=1,
            question=prompt.question,
            answer="测试回答",
            success=True,
            brand_mentioned=brand_mentioned,
            matched_names=["测试品牌"] if brand_mentioned else [],
            is_recommended=brand_mentioned and ranking_score >= 60,
            recommendation_rank=1 if ranking_score == 100 else None,
            ranking_score=ranking_score,
            citation_supported=citation_supported,
            own_source_cited=own_source_cited,
            cited_urls=["https://example.com/case"] if own_source_cited else [],
            cited_domains=["example.com"] if own_source_cited else [],
            sentiment="positive" if brand_mentioned else "not_mentioned",
            sentiment_score=sentiment_score,
            visibility_score=0,
            schema_version="1.0.0",
            asked_at=created_at,
            evaluated_at=created_at,
            created_at=created_at,
        )
    )


def _cleanup_geo_project(db, user_id, project_id):
    db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(GeoEvaluationRun).filter(GeoEvaluationRun.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(GeoPrompt).filter(GeoPrompt.project_id == project_id).delete(synchronize_session=False)
    db.query(GeoPromptSet).filter(GeoPromptSet.project_id == project_id).delete(synchronize_session=False)
    db.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()


def test_diagnosis_verdict_and_partial_baseline_comparable_platforms(local_db):
    db = local_db
    user, project, prompt_set, prompt = _make_project_with_prompt(db)
    try:
        baseline_run = _make_run(db, project, prompt_set, phase="baseline", platforms=["doubao"])
        current_run = _make_run(db, project, prompt_set, phase="ongoing", platforms=["doubao", "qianwen"])
        now = datetime.now()

        for _ in range(30):
            _add_eval_record(
                db,
                run=baseline_run,
                project=project,
                prompt_set=prompt_set,
                prompt=prompt,
                phase="baseline",
                platform="doubao",
                brand_mentioned=False,
                ranking_score=0,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=0,
                created_at=now - timedelta(days=2),
            )

        for _ in range(30):
            _add_eval_record(
                db,
                run=current_run,
                project=project,
                prompt_set=prompt_set,
                prompt=prompt,
                phase="ongoing",
                platform="doubao",
                brand_mentioned=True,
                ranking_score=100,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=80,
                created_at=now,
            )

        # 新授权平台已有 current，但尚未补 baseline，不能直接参与可比平台。
        for _ in range(30):
            _add_eval_record(
                db,
                run=current_run,
                project=project,
                prompt_set=prompt_set,
                prompt=prompt,
                phase="ongoing",
                platform="qianwen",
                brand_mentioned=True,
                ranking_score=100,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=80,
                created_at=now,
            )

        db.commit()

        result = GeoEvaluationAnalyticsService(db).get_diagnosis(project.id, days=7)

        assert result["comparable_platforms"] == ["doubao"]
        assert "qianwen" in result["missing_baseline_platforms"]
        assert "deepseek" in result["missing_baseline_platforms"]
        assert result["delta"]["verdict"] == "显著提升"
        assert result["delta"]["visibility_score_delta"] >= 10
        assert result["by_platform"][1]["platform"] == "qianwen"
        assert result["by_platform"][1]["baseline"]["valid_count"] == 0
        assert result["by_platform"][1]["current"]["valid_count"] == 30
    finally:
        _cleanup_geo_project(db, user.id, project.id)


def test_diagnosis_uses_active_prompt_set_and_schema_version_only(local_db):
    db = local_db
    user, project, prompt_set, prompt = _make_project_with_prompt(db)
    try:
        old_prompt_set = GeoPromptSet(
            project_id=project.id,
            name="旧问题集",
            question_count=100,
            status="archived",
            frozen_at=datetime.now() - timedelta(days=10),
            created_by=user.id,
        )
        db.add(old_prompt_set)
        db.commit()
        db.refresh(old_prompt_set)

        old_prompt = GeoPrompt(
            prompt_set_id=old_prompt_set.id,
            project_id=project.id,
            question="旧问题集问题",
            question_type="recommendation",
            sort_order=1,
        )
        db.add(old_prompt)
        db.commit()
        db.refresh(old_prompt)

        baseline_run = _make_run(db, project, prompt_set, phase="baseline", platforms=["doubao"])
        current_run = _make_run(db, project, prompt_set, phase="ongoing", platforms=["doubao"])
        old_run = _make_run(db, project, old_prompt_set, phase="ongoing", platforms=["qianwen"])
        now = datetime.now()

        for _ in range(30):
            _add_eval_record(
                db,
                run=baseline_run,
                project=project,
                prompt_set=prompt_set,
                prompt=prompt,
                phase="baseline",
                platform="doubao",
                brand_mentioned=False,
                ranking_score=0,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=0,
                created_at=now - timedelta(days=2),
            )
            _add_eval_record(
                db,
                run=current_run,
                project=project,
                prompt_set=prompt_set,
                prompt=prompt,
                phase="ongoing",
                platform="doubao",
                brand_mentioned=True,
                ranking_score=100,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=80,
                created_at=now,
            )
            _add_eval_record(
                db,
                run=old_run,
                project=project,
                prompt_set=old_prompt_set,
                prompt=old_prompt,
                phase="ongoing",
                platform="qianwen",
                brand_mentioned=True,
                ranking_score=100,
                citation_supported=False,
                own_source_cited=False,
                sentiment_score=80,
                created_at=now,
            )

        db.commit()

        result = GeoEvaluationAnalyticsService(db).get_diagnosis(project.id, days=7)

        assert result["comparable_platforms"] == ["doubao"]
        assert result["current"]["valid_count"] == 30
        qianwen = next(item for item in result["by_platform"] if item["platform"] == "qianwen")
        assert qianwen["current"]["valid_count"] == 0
    finally:
        _cleanup_geo_project(db, user.id, project.id)
