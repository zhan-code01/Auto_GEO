from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.database.models import (
    Client,
    GeoEvaluationRecord,
    GeoEvaluationRun,
    GeoPrompt,
    Project,
    SmartArticleQuestion,
    User,
)
from backend.services.geo_evaluation_prompt_service import GeoEvaluationPromptService
from backend.services.geo_evaluation_analytics_service import GeoEvaluationAnalyticsService
from backend.services.geo_evaluation_run_service import GeoEvaluationRunService


@pytest.fixture
def local_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _seed_questions(db):
    user = User(
        username="smart_geo_user",
        email="smart_geo_user@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.flush()
    client = Client(name="测试公司", company_name="测试公司", user_id=user.id)
    db.add(client)
    db.flush()
    projects = [
        Project(name="项目甲", status=1, user_id=user.id, client_id=client.id),
        Project(name="项目乙", status=1, user_id=user.id, client_id=client.id),
    ]
    db.add_all(projects)
    db.flush()
    questions = [
        SmartArticleQuestion(
            user_id=user.id,
            project_id=projects[0].id,
            question="广州有哪些智能客服服务商值得推荐？",
            normalized_question="广州有哪些智能客服服务商值得推荐",
            intent_type="provider",
        ),
        SmartArticleQuestion(
            user_id=user.id,
            project_id=projects[0].id,
            question="智能客服产品应该如何选型？",
            normalized_question="智能客服产品应该如何选型",
            intent_type="selection",
        ),
        SmartArticleQuestion(
            user_id=user.id,
            project_id=projects[1].id,
            question="连锁门店部署智能客服有哪些场景？",
            normalized_question="连锁门店部署智能客服有哪些场景",
            intent_type="scenario",
        ),
    ]
    db.add_all(questions)
    db.commit()
    return user, client, projects, questions


def test_sync_exposes_smart_questions_without_starting_evaluation(local_db):
    db = local_db
    user, client, _projects, questions = _seed_questions(db)

    service = GeoEvaluationPromptService(db)
    prompt_set = service.sync_smart_article_questions(client.id, user.id)
    second_sync = service.sync_smart_article_questions(client.id, user.id)

    prompts = db.query(GeoPrompt).filter(GeoPrompt.prompt_set_id == prompt_set.id).all()
    assert second_sync.id == prompt_set.id
    assert prompt_set.question_count == 3
    assert {prompt.smart_article_question_id for prompt in prompts} == {q.id for q in questions}
    assert {prompt.question_type for prompt in prompts} == {"recommendation", "comparison", "scenario"}
    assert db.query(GeoEvaluationRun).count() == 0
    assert db.query(GeoEvaluationRecord).count() == 0

    prompt_set.status = "frozen"
    extra = SmartArticleQuestion(
        user_id=user.id,
        project_id=questions[0].project_id,
        question="智能客服系统实施时有哪些风险？",
        normalized_question="智能客服系统实施时有哪些风险",
        intent_type="risk",
    )
    db.add(extra)
    db.commit()

    incremental_sync = service.sync_smart_article_questions(client.id, user.id)
    assert incremental_sync.id == prompt_set.id
    assert incremental_sync.status == "frozen"
    assert incremental_sync.question_count == 4
    assert db.query(GeoEvaluationRun).count() == 0


def test_platform_baseline_selection_is_incremental_and_success_gated(local_db):
    db = local_db
    user, client, _projects, _questions = _seed_questions(db)
    prompt_set = GeoEvaluationPromptService(db).sync_smart_article_questions(client.id, user.id)
    prompts = db.query(GeoPrompt).filter(GeoPrompt.prompt_set_id == prompt_set.id).order_by(GeoPrompt.id).all()

    run = GeoEvaluationRun(
        client_id=client.id,
        prompt_set_id=prompt_set.id,
        phase="baseline",
        platforms=["doubao"],
        prompt_ids=[prompts[0].id, prompts[1].id],
        rounds=1,
        status="completed",
        total_planned=2,
        total_completed=2,
        created_by=user.id,
        created_at=datetime.now(),
    )
    db.add(run)
    db.flush()
    db.add_all(
        [
            GeoEvaluationRecord(
                run_id=run.id,
                client_id=client.id,
                prompt_set_id=prompt_set.id,
                prompt_id=prompts[0].id,
                platform="doubao",
                phase="baseline",
                round_no=1,
                question=prompts[0].question,
                answer="有效回答",
                success=True,
                schema_version="1.0.0",
            ),
            GeoEvaluationRecord(
                run_id=run.id,
                client_id=client.id,
                prompt_set_id=prompt_set.id,
                prompt_id=prompts[1].id,
                platform="doubao",
                phase="baseline",
                round_no=1,
                question=prompts[1].question,
                success=False,
                error_message="平台失败",
                schema_version="1.0.0",
            ),
        ]
    )
    db.commit()

    service = GeoEvaluationRunService(lambda: db)
    doubao_new = service._unmeasured_baseline_prompt_ids(
        db,
        prompt_set_id=prompt_set.id,
        platform="doubao",
        client_id=client.id,
        project_id=None,
    )
    qianwen_new = service._unmeasured_baseline_prompt_ids(
        db,
        prompt_set_id=prompt_set.id,
        platform="qianwen",
        client_id=client.id,
        project_id=None,
    )
    recheck_ids = service._successful_baseline_prompt_ids(
        db,
        prompt_set_id=prompt_set.id,
        platform="doubao",
        client_id=client.id,
        project_id=None,
    )

    assert doubao_new == [prompts[2].id]
    assert qianwen_new == [prompt.id for prompt in prompts]
    assert recheck_ids == [prompts[0].id]

    config = GeoEvaluationAnalyticsService(db).get_client_config(client.id)
    statuses = {item["platform"]: item for item in config["baseline_status"]["platforms"]}
    assert statuses["doubao"]["attempted_count"] == 2
    assert statuses["doubao"]["baseline_count"] == 1
    assert statuses["doubao"]["failed_count"] == 1
    assert statuses["doubao"]["unmeasured_count"] == 1
    assert statuses["qianwen"]["unmeasured_count"] == 3

    ongoing_run = GeoEvaluationRun(
        client_id=client.id,
        prompt_set_id=prompt_set.id,
        phase="ongoing",
        platforms=["doubao"],
        prompt_ids=[prompts[0].id],
        rounds=1,
        status="completed",
        total_planned=1,
        total_completed=1,
        created_by=user.id,
        created_at=datetime.now(),
    )
    db.add(ongoing_run)
    db.flush()
    db.add(
        GeoEvaluationRecord(
            run_id=ongoing_run.id,
            client_id=client.id,
            prompt_set_id=prompt_set.id,
            prompt_id=prompts[0].id,
            platform="doubao",
            phase="ongoing",
            round_no=1,
            question=prompts[0].question,
            answer="使用后回答",
            success=True,
            schema_version="1.0.0",
            created_at=datetime.now(),
        )
    )
    db.commit()

    diagnosis = GeoEvaluationAnalyticsService(db).get_client_diagnosis(client.id, days=7)
    assert diagnosis["comparable_platforms"] == ["doubao"]
    assert diagnosis["baseline"]["answer_count"] == 1
    assert diagnosis["current"]["answer_count"] == 1
