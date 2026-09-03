# -*- coding: utf-8 -*-
"""GEO evaluation run service tests that avoid real Playwright execution."""

from datetime import datetime, timedelta
import asyncio
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.database.models import GeoEvaluationRecord, GeoEvaluationRun, GeoPrompt, GeoPromptSet, Project, User
from backend.services.geo_evaluation_run_service import (
    _EvaluationRiskGuard,
    GeoEvaluationRunService,
    _execute_run_async_parallel_v2,
    _beijing_now,
    _classify_platform_failure,
    _clear_platform_risk_ack_required,
    _count_existing_attempts,
    _find_existing_success_record,
    _get_platform_cooldown_remaining,
    _get_platform_run_lock,
    _register_active_run,
    _set_platform_risk_ack_required,
    _try_acquire_platform_run_locks,
    _unregister_active_run,
)


@pytest.fixture
def run_db():
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
        yield db, TestingSessionLocal
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _make_project_prompt(db):
    user = User(
        username="geo_run_user",
        email="geo_run_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    project = Project(
        name="GEO Run Project",
        company_name="Test Brand",
        domain_keyword="example.com",
        status=1,
        user_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    prompt_set = GeoPromptSet(
        project_id=project.id,
        name="Run Test Prompt Set",
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
        question="Is Test Brand suitable for GEO?",
        question_type="recommendation",
        sort_order=1,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return user, project, prompt_set, prompt


def test_create_baseline_requires_user_id(run_db):
    db, db_factory = run_db
    _user, project, _prompt_set, _prompt = _make_project_prompt(db)

    result = GeoEvaluationRunService(db_factory).create_baseline(
        project_id=project.id,
        platforms=["doubao"],
        rounds=1,
    )

    assert result["success"] is False
    assert "ID" in result["message"]


def test_create_baseline_skips_platform_with_successful_existing_baseline(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, prompt_set, prompt = _make_project_prompt(db)
    db.add(
        GeoEvaluationRecord(
            run_id=1,
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
        )
    )
    db.commit()

    monkeypatch.setattr("backend.services.geo_evaluation_run_service._start_background_run", lambda **kwargs: None)
    result = GeoEvaluationRunService(db_factory).create_baseline(
        project_id=project.id,
        platforms=["doubao"],
        rounds=1,
        created_by=user.id,
        user_id=user.id,
    )

    assert result["success"] is False
    assert "rebuild=true" in result["message"]


def test_create_baseline_requires_platform_session_before_creating_run(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, _prompt_set, _prompt = _make_project_prompt(db)
    started = []

    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
        lambda **kwargs: {"success": False, "message": "platform session required"},
    )
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._start_background_run",
        lambda **kwargs: started.append(kwargs),
    )

    result = GeoEvaluationRunService(db_factory).create_baseline(
        project_id=project.id,
        platforms=["deepseek"],
        rounds=1,
        created_by=user.id,
        user_id=user.id,
    )

    assert result["success"] is False
    assert "session" in result["message"]
    assert started == []


def test_create_baseline_defaults_to_authorized_platform_subset(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, _prompt_set, _prompt = _make_project_prompt(db)
    started = []

    def fake_resolve(**kwargs):
        assert kwargs["explicit"] is False
        assert kwargs["platforms"] == ["doubao", "qianwen", "deepseek"]
        return {"success": True, "platforms": ["deepseek"], "message_suffix": "; skipped unauthenticated platforms"}

    monkeypatch.setattr("backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions", fake_resolve)
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._start_background_run",
        lambda **kwargs: started.append(kwargs),
    )

    result = GeoEvaluationRunService(db_factory).create_baseline(
        project_id=project.id,
        rounds=1,
        created_by=user.id,
        user_id=user.id,
    )

    assert result["success"] is True
    assert result["total_planned"] == 1
    assert started[0]["platforms"] == ["deepseek"]
    assert "skipped" in result["message"]


def test_create_baseline_requires_risk_ack_and_allows_after_handled(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, _prompt_set, _prompt = _make_project_prompt(db)
    started = []

    _clear_platform_risk_ack_required(user.id, ["doubao"])
    _set_platform_risk_ack_required(
        user.id,
        "doubao",
        category="risk_control",
        reason="doubao risk control",
    )
    try:
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
            lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
        )
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._start_background_run",
            lambda **kwargs: started.append(kwargs),
        )

        blocked = GeoEvaluationRunService(db_factory).create_baseline(
            project_id=project.id,
            platforms=["doubao"],
            rounds=1,
            created_by=user.id,
            user_id=user.id,
        )
        allowed = GeoEvaluationRunService(db_factory).create_baseline(
            project_id=project.id,
            platforms=["doubao"],
            rounds=1,
            created_by=user.id,
            user_id=user.id,
            risk_acknowledged=True,
        )
    finally:
        _clear_platform_risk_ack_required(user.id, ["doubao"])

    assert blocked["success"] is False
    assert blocked["requires_risk_ack"] is True
    assert blocked["blocked_platforms"][0]["platform"] == "doubao"
    assert allowed["success"] is True
    assert started[0]["platforms"] == ["doubao"]


def test_create_baseline_reuses_registered_active_run(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, prompt_set, _prompt = _make_project_prompt(db)
    run = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="running",
        total_planned=1,
        total_completed=0,
        total_failed=0,
        current_progress=0,
        created_by=user.id,
        created_at=_beijing_now() - timedelta(minutes=10),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = []

    _register_active_run(run.id)
    try:
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
            lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
        )
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._start_background_run",
            lambda **kwargs: started.append(kwargs),
        )

        result = GeoEvaluationRunService(db_factory).create_baseline(
            project_id=project.id,
            platforms=["doubao"],
            rounds=1,
            created_by=user.id,
            user_id=user.id,
        )
    finally:
        _unregister_active_run(run.id)

    assert result["success"] is True
    assert result["existing_run"] is True
    assert result["run_id"] == run.id
    assert started == []


def test_create_baseline_marks_stale_active_run_failed_and_creates_new_run(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, prompt_set, _prompt = _make_project_prompt(db)
    stale_run = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="running",
        total_planned=1,
        total_completed=0,
        total_failed=0,
        current_progress=0,
        created_by=user.id,
        created_at=_beijing_now() - timedelta(minutes=10),
    )
    db.add(stale_run)
    db.commit()
    db.refresh(stale_run)
    started = []

    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
        lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
    )
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._start_background_run",
        lambda **kwargs: started.append(kwargs),
    )

    result = GeoEvaluationRunService(db_factory).create_baseline(
        project_id=project.id,
        platforms=["doubao"],
        rounds=1,
        created_by=user.id,
        user_id=user.id,
    )
    db.refresh(stale_run)

    assert result["success"] is True
    assert result["run_id"] != stale_run.id
    assert stale_run.status == "failed"
    assert "自动释放" in stale_run.error_message
    assert started[0]["run_id"] == result["run_id"]


def test_platform_failure_classification_detects_risk_and_rate_limit():
    assert _classify_platform_failure("需要完成验证码安全验证后继续") == "risk_control"
    assert _classify_platform_failure("HTTP 429 too many requests") == "rate_limited"
    assert _classify_platform_failure("DeepSeek 未登录或 session 失效") == "auth"
    assert _classify_platform_failure("未返回有效 AI 回答") == "empty"


def test_risk_guard_stops_after_consecutive_failures():
    _clear_platform_risk_ack_required(7788, ["doubao"])
    guard = _EvaluationRiskGuard(
        user_id=7788,
        min_delay=0,
        max_delay=0,
        min_platform_interval=0,
        failure_limit=2,
        block_cooldown=30,
        stop_on_block=True,
    )

    first = guard.note_failure("doubao", "temporary DOM extraction failed")
    second = guard.note_failure("doubao", "temporary DOM extraction failed again")

    assert first["stop_platform"] is False
    assert second["stop_platform"] is True
    assert second["category"] == "unknown"
    assert _get_platform_cooldown_remaining(7788, "doubao") == 0


@pytest.mark.asyncio
async def test_risk_guard_waits_full_delay_after_previous_completion(monkeypatch):
    sleeps = []
    now = 1000.0

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("backend.services.geo_evaluation_run_service.random.uniform", lambda minimum, maximum: 12.0)
    monkeypatch.setattr("backend.services.geo_evaluation_run_service.time.monotonic", lambda: now)
    monkeypatch.setattr("backend.services.geo_evaluation_run_service.asyncio.sleep", fake_sleep)

    guard = _EvaluationRiskGuard(
        user_id=7789,
        min_delay=10,
        max_delay=15,
        min_platform_interval=10,
        failure_limit=2,
        block_cooldown=30,
        stop_on_block=True,
    )

    await guard.before_request("doubao")
    assert sleeps == []

    await guard.after_request("doubao")
    now += 25
    await guard.before_request("doubao")

    assert sleeps == [12.0]


def test_active_run_only_blocks_overlapping_platforms(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, prompt_set, _prompt = _make_project_prompt(db)
    active = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="running",
        total_planned=1,
        total_completed=0,
        total_failed=0,
        current_progress=0,
        created_by=user.id,
        created_at=_beijing_now(),
    )
    db.add(active)
    db.commit()
    db.refresh(active)
    started = []

    _register_active_run(active.id)
    try:
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
            lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
        )
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._start_background_run",
            lambda **kwargs: started.append(kwargs),
        )
        result = GeoEvaluationRunService(db_factory).create_baseline(
            project_id=project.id,
            platforms=["qianwen"],
            rounds=1,
            created_by=user.id,
            user_id=user.id,
        )
    finally:
        _unregister_active_run(active.id)

    assert result["success"] is True
    assert started[0]["platforms"] == ["qianwen"]


def test_active_run_blocks_same_platform_baseline(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, prompt_set, _prompt = _make_project_prompt(db)
    other_project = Project(
        name="Other GEO Run Project",
        company_name="Other Brand",
        domain_keyword="other.example.com",
        status=1,
        user_id=user.id,
    )
    db.add(other_project)
    db.commit()
    db.refresh(other_project)
    other_prompt_set = GeoPromptSet(
        project_id=other_project.id,
        name="Other Prompt Set",
        question_count=1,
        status="frozen",
        frozen_at=datetime.now(),
        created_by=user.id,
    )
    db.add(other_prompt_set)
    db.commit()
    db.refresh(other_prompt_set)
    db.add(
        GeoPrompt(
            prompt_set_id=other_prompt_set.id,
            project_id=other_project.id,
            question="Is Other Brand suitable for GEO?",
            question_type="recommendation",
            sort_order=1,
        )
    )
    db.commit()

    active = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="running",
        total_planned=1,
        total_completed=0,
        total_failed=0,
        current_progress=0,
        created_by=user.id,
        created_at=_beijing_now(),
    )
    db.add(active)
    db.commit()
    db.refresh(active)

    _register_active_run(active.id)
    try:
        monkeypatch.setattr(
            "backend.services.geo_evaluation_run_service._resolve_platforms_with_sessions",
            lambda **kwargs: {"success": True, "platforms": kwargs["platforms"], "message_suffix": ""},
        )
        result = GeoEvaluationRunService(db_factory).create_baseline(
            project_id=other_project.id,
            platforms=["doubao"],
            rounds=1,
            created_by=user.id,
            user_id=user.id,
        )
    finally:
        _unregister_active_run(active.id)

    assert result["success"] is False
    assert result["active_run_id"] == active.id
    assert result["active_platforms"] == ["doubao"]


def test_platform_run_locks_allow_different_platforms():
    doubao_lock = _get_platform_run_lock("doubao")
    assert doubao_lock.acquire(blocking=False)
    qianwen_locks = []
    try:
        qianwen_locks = _try_acquire_platform_run_locks(["qianwen"])
        doubao_locks = _try_acquire_platform_run_locks(["doubao"])

        assert qianwen_locks
        assert doubao_locks == []
    finally:
        for lock in reversed(qianwen_locks):
            lock.release()
        doubao_lock.release()


def test_existing_success_and_attempt_count_helpers(run_db):
    db, _db_factory = run_db
    _user, project, prompt_set, prompt = _make_project_prompt(db)
    run = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        rounds=1,
        status="running",
        total_planned=1,
        created_at=_beijing_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add(
        GeoEvaluationRecord(
            run_id=run.id,
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
        )
    )
    db.commit()

    existing = _find_existing_success_record(
        db,
        client_id=None,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        prompt_id=prompt.id,
        platform="doubao",
        phase="baseline",
        round_no=1,
    )

    assert existing is not None
    assert _count_existing_attempts(
        db,
        run_id=run.id,
        prompt_id=prompt.id,
        platform="doubao",
        phase="baseline",
        round_no=1,
    ) == 1


@pytest.mark.asyncio
async def test_parallel_run_executes_different_platforms_concurrently(run_db, monkeypatch):
    db, db_factory = run_db
    user, project, prompt_set, prompt = _make_project_prompt(db)
    run = GeoEvaluationRun(
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao", "qianwen"],
        rounds=1,
        status="pending",
        total_planned=2,
        total_completed=0,
        total_failed=0,
        current_progress=0,
        created_by=user.id,
        created_at=_beijing_now(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    platform_started = set()
    both_started = asyncio.Event()

    class FastRiskGuard:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def before_request(self, platform):
            return None

        async def after_request(self, platform):
            return None

        def note_success(self, platform):
            return None

        def note_failure(self, platform, error_message):
            return {
                "category": "unknown",
                "consecutive_failures": 1,
                "stop_platform": False,
                "reason": "",
            }

    async def fake_ask_ai_platform_via_browser(**kwargs):
        platform_started.add(kwargs["platform"])
        if platform_started == {"doubao", "qianwen"}:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return {"success": True, "answer": f"{kwargs['platform']} answer"}

    class FakeJudge:
        async def evaluate(self, **kwargs):
            return {
                "brand_mentioned": True,
                "matched_names": ["Test Brand"],
                "is_recommended": True,
                "recommendation_rank": 1,
                "ranking_score": 100,
                "citation_supported": False,
                "own_source_cited": False,
                "cited_urls": [],
                "cited_domains": [],
                "sentiment": "positive",
                "sentiment_score": 80,
                "visibility_score": 90,
                "evidence": {},
            }

    monkeypatch.setattr("backend.services.geo_evaluation_run_service._get_db_session", db_factory)
    monkeypatch.setattr("backend.services.geo_evaluation_run_service._EvaluationRiskGuard", FastRiskGuard)
    monkeypatch.setattr(
        "backend.services.geo_evaluation_run_service._ask_ai_platform_via_browser",
        fake_ask_ai_platform_via_browser,
    )
    monkeypatch.setattr("backend.services.geo_evaluation_run_service.GeoResponseJudgeService", FakeJudge)

    await _execute_run_async_parallel_v2(
        run_id=run.id,
        client_id=None,
        project_id=project.id,
        company_name="Test Brand",
        official_domains=["example.com"],
        prompt_set_id=prompt_set.id,
        platforms=["doubao", "qianwen"],
        rounds=1,
        user_id=user.id,
    )

    db.expire_all()
    records = db.query(GeoEvaluationRecord).filter(GeoEvaluationRecord.run_id == run.id).all()
    finished_run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run.id).first()

    assert platform_started == {"doubao", "qianwen"}
    assert finished_run.status == "completed"
    assert finished_run.total_completed == 2
    assert {record.platform for record in records} == {"doubao", "qianwen"}
    assert all(record.success for record in records)
