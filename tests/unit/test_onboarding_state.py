# -*- coding: utf-8 -*-
"""V2 引导状态机验收测试（对应 docs/ONBOARDING_REDESIGN.md P6 清单）。

运行方式（需 Docker PG `autogeo_local_postgres` 已启动）：
    TEST_DATABASE_URL=postgresql://autogeo:autogeo_dev_password@localhost:5432/autogeo_test \
        python -m pytest tests/unit/test_onboarding_state.py -v

数据库名必须含 "test"（backend/config.py 的 pytest 安全护栏要求），
且不会污染开发库 `autogeo`。每个测试使用独立 user，结束后清理其全部相关数据。

本文件自包含：在 import backend 之前设置 TEST_DATABASE_URL，并在会话级自动执行
`python -m alembic upgrade head` 初始化测试库 schema，不依赖根 conftest 的 db fixture，
以免 Windows 下 `alembic` 可执行文件找不到 `backend` 包的问题。
"""
from __future__ import annotations

import asyncio
import os
import uuid

# —— 必须在 import backend 之前设置，使 backend.config 选中测试库 ——
_TEST_DB = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://autogeo:autogeo_dev_password@localhost:5432/autogeo_test",
)
os.environ["TEST_DATABASE_URL"] = _TEST_DB
os.environ["_"] = "pytest"  # 触发 backend.config 的 pytest 检测

import pytest

from backend.database import SessionLocal
from backend.database.models import (
    Account,
    Client,
    GeoArticle,
    Keyword,
    Project,
    SmartArticleQuestion,
    User,
    UserAgentFact,
    UserAgentPreference,
)
from backend.services.agent_v2.memory import FactStore
from backend.services.agent_v2.onboarding import (
    compute_onboarding_state,
    set_onboarding_dismissed,
)
from backend.services.agent_v2.tools.article_tools import generate_articles_tool


# ---------------------------------------------------------------------------
#  会话级：初始化测试库 schema（仅一次）
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    # 仅当指向测试库（库名含 test）时才建表，避免误伤开发/生产库
    assert "test" in _TEST_DB.lower(), "TEST_DATABASE_URL 必须指向测试库"
    # 用 SQLAlchemy metadata 直接建表（幂等），不依赖 alembic 迁移链的顺序/幂等性，
    # 以免本仓库迁移脚本在该测试库上出现 DuplicateTable 等历史不一致问题。
    from backend.database import Base, engine

    Base.metadata.create_all(bind=engine)
    yield


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    """本文件自用的数据库会话（不走根 conftest 的 db fixture）。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def fresh_user(db):
    """创建一个全新的、与其他测试数据隔离的用户，返回 (db, user_id)。

    结束后清理该 user 在全部相关表中的行，保证用例互不污染。
    """
    uname = f"onb_{uuid.uuid4().hex[:12]}"
    user = User(username=uname, email=f"{uname}@example.com", password_hash="x", role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = user.id
    yield db, uid

    # 逆依赖顺序清理
    db.query(UserAgentFact).filter(UserAgentFact.system_user_id == uid).delete()
    db.query(UserAgentPreference).filter(UserAgentPreference.system_user_id == uid).delete()
    db.query(GeoArticle).filter(GeoArticle.user_id == uid).delete()
    db.query(SmartArticleQuestion).filter(SmartArticleQuestion.user_id == uid).delete()
    db.query(Account).filter(Account.user_id == uid).delete()
    db.query(Keyword).filter(Keyword.project_id.in_(
        db.query(Project.id).filter(Project.user_id == uid)
    )).delete(synchronize_session=False)
    db.query(Project).filter(Project.user_id == uid).delete()
    db.query(Client).filter(Client.user_id == uid).delete()
    db.query(User).filter(User.id == uid).delete()
    db.commit()


# ---------------------------------------------------------------------------
#  数据构造辅助
# ---------------------------------------------------------------------------
def _mk_client(db, uid) -> int:
    c = Client(user_id=uid, name="测试客户")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c.id


def _mk_project(db, uid) -> int:
    p = Project(user_id=uid, name="测试项目", company_name="测试公司", status=1)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.id


def _mk_question(db, uid, pid) -> int:
    q = SmartArticleQuestion(
        user_id=uid,
        project_id=pid,
        question="测试问题",
        normalized_question="测试问题",
        has_article=False,
        article_generation_status="idle",
        is_deleted=False,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q.id


def _mk_article(db, uid, pid, keyword_id, publish_status) -> int:
    a = GeoArticle(
        user_id=uid,
        project_id=pid,
        keyword_id=keyword_id,
        title="测试文章",
        content="x",
        publish_status=publish_status,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a.id


def _mk_account(db, uid) -> int:
    a = Account(user_id=uid, platform="zhihu", account_name="测试账号", username="u", status=1)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a.id


def _mk_keyword(db, pid) -> int:
    k = Keyword(project_id=pid, keyword="测试关键词")
    db.add(k)
    db.commit()
    db.refresh(k)
    return k.id


def _action_types(actions: list[dict]) -> list[str]:
    return [a.get("type") for a in actions]


# ---------------------------------------------------------------------------
#  P6 清单：空用户全流程
# ---------------------------------------------------------------------------
def test_empty_user_shows_first_step_only(fresh_user):
    db, uid = fresh_user
    state = compute_onboarding_state(db, uid)
    assert state["active"] is True
    assert state["completed"] is False
    assert state["dismissed"] is False
    assert state["can_skip"] is True
    # 没有任何数据时，只有第一步「建客户」可推（其前置为空），其余因依赖未满足不出现
    assert _action_types(state["next_actions"]) == ["show_client_form"]
    assert state["optional_actions"] == []
    # 进度条 6 步全部未完成
    assert all(not item["done"] for item in state["checklist"])
    assert len(state["checklist"]) == 6


# ---------------------------------------------------------------------------
#  P6 清单：可选上传可跳过，流程仍能继续
# ---------------------------------------------------------------------------
def test_optional_upload_appears_but_not_required(fresh_user):
    db, uid = fresh_user
    _mk_client(db, uid)  # 仅建客户，不建项目
    state = compute_onboarding_state(db, uid)
    # 客户已建、项目未建 → 提示一次「上传资料(可选)」
    assert "upload_files" in _action_types(state["optional_actions"])
    # 且下一步仍是「新建项目」（上传不是阻塞项）
    assert "show_project_form" in _action_types(state["next_actions"])


def test_skip_upload_still_advances(fresh_user):
    db, uid = fresh_user
    _mk_client(db, uid)
    _mk_project(db, uid)  # 跳过上传，直接建项目
    state = compute_onboarding_state(db, uid)
    # 项目已建后，可选上传不再出现
    assert state["optional_actions"] == []
    # 下一步推进到规划问题（绑定账号需在文章生成后才出现）
    types = _action_types(state["next_actions"])
    assert "generate_questions" in types
    assert "show_add_account" not in types


# ---------------------------------------------------------------------------
#  P6 清单：跳步 / 跑偏健壮性
# ---------------------------------------------------------------------------
def test_off_track_missing_prerequisite_is_recovered(fresh_user):
    """用户跳过「建客户」直接有了项目与问题，状态机仍先推缺失的前置（建客户）。"""
    db, uid = fresh_user
    pid = _mk_project(db, uid)
    _mk_question(db, uid, pid)  # 没有 Client，但有了项目+问题（跑偏）
    state = compute_onboarding_state(db, uid)
    # 仍会要求补齐客户（前置为空、可被推），不会因数据不一致而崩溃
    assert "show_client_form" in _action_types(state["next_actions"])
    # 问题已满足前置 → 下一步推进到生成文章（绑定账号需在文章生成后才出现）
    assert "generate_articles" in _action_types(state["next_actions"])
    assert "show_add_account" not in _action_types(state["next_actions"])


def test_nonlinear_progress_no_crash(fresh_user):
    """数据高度不完整（仅有账号、无客户/项目）→ 不崩、只推可达的第一步。"""
    db, uid = fresh_user
    _mk_account(db, uid)
    state = compute_onboarding_state(db, uid)
    assert state["active"] is True
    assert "show_client_form" in _action_types(state["next_actions"])


# ---------------------------------------------------------------------------
#  P6 清单：跳过持久化
# ---------------------------------------------------------------------------
def test_skip_persists_and_hides_cards(fresh_user):
    db, uid = fresh_user
    _mk_client(db, uid)
    set_onboarding_dismissed(db, uid, True)
    # 重新计算（模拟刷新/重启）应读取持久化的跳过状态
    state = compute_onboarding_state(db, uid)
    assert state["active"] is False
    assert state["dismissed"] is True
    assert state["can_skip"] is False
    assert state["next_actions"] == []
    assert state["optional_actions"] == []


def test_skip_can_be_undone(fresh_user):
    db, uid = fresh_user
    set_onboarding_dismissed(db, uid, True)
    set_onboarding_dismissed(db, uid, False)
    state = compute_onboarding_state(db, uid)
    assert state["dismissed"] is False
    assert state["active"] is True


# ---------------------------------------------------------------------------
#  P6 清单：老用户 / admin 不弹引导
# ---------------------------------------------------------------------------
def test_old_user_with_full_data_no_onboarding(fresh_user):
    db, uid = fresh_user
    cid = _mk_client(db, uid)
    pid = _mk_project(db, uid)
    _mk_question(db, uid, pid)
    kw = _mk_keyword(db, pid)
    _mk_article(db, uid, pid, kw, "completed")   # 文章已生成（非 draft）
    _mk_account(db, uid)
    _mk_article(db, uid, pid, kw, "published")    # 已发布 → 第 6 步完成
    state = compute_onboarding_state(db, uid)
    assert state["completed"] is True
    assert state["active"] is False
    assert state["next_actions"] == []
    # 持久化标记也应被写入
    assert FactStore(db).is_onboarding_completed(uid) is True


def test_admin_never_onboarded(fresh_user):
    db, uid = fresh_user
    _mk_client(db, uid)
    _mk_project(db, uid)
    state = compute_onboarding_state(db, uid, is_admin=True)
    assert state["active"] is False
    assert state["dismissed"] is True
    assert state["completed"] is True
    assert state["next_actions"] == []
    assert state["can_skip"] is False


# ---------------------------------------------------------------------------
#  P6 清单：文章数 > 可用问题数 → 操作不合法
# ---------------------------------------------------------------------------
def test_articles_exceed_questions_illegal(fresh_user, monkeypatch):
    db, uid = fresh_user
    pid = _mk_project(db, uid)
    _mk_question(db, uid, pid)  # 仅 1 个可用问题

    # 拦截真实异步生成，保证用例hermetic；非法分支本就不会走到这里
    from backend.services.agent_v2.adapters import QuestionPoolAdapter

    async def _fake_generate(*args, **kwargs):
        return 999, []

    async def _fake_plan(*args, **kwargs):
        return None, []

    monkeypatch.setattr(QuestionPoolAdapter, "generate_articles_sync", _fake_generate)
    monkeypatch.setattr(QuestionPoolAdapter, "plan_batch_sync", _fake_plan)

    outcome = asyncio.run(generate_articles_tool(slots={"project_id": pid, "count": 5}, user_id=uid))
    assert outcome.status == "failed"
    assert outcome.error_type == "illegal_operation"
    assert "1" in (outcome.reply or "")  # 回含说明“共 1 个问题”
    assert "5" in (outcome.reply or "")  # 回含说明“请求生成 5 篇”
    # 非法分支不应触发真实生成
    # （adapter 被 mock，若触发会返回 999；此处仅校验错误类型）


def test_articles_equal_questions_allowed(fresh_user, monkeypatch):
    db, uid = fresh_user
    pid = _mk_project(db, uid)
    _mk_question(db, uid, pid)  # 1 个可用问题

    from backend.services.agent_v2.adapters import QuestionPoolAdapter

    async def _fake_generate(*args, **kwargs):
        return 999, []

    monkeypatch.setattr(QuestionPoolAdapter, "generate_articles_sync", _fake_generate)

    # count == 可用问题数 → 通过校验、进入生成（被 mock 拦截，不真正生成）
    outcome = asyncio.run(generate_articles_tool(slots={"project_id": pid, "count": 1}, user_id=uid))
    assert outcome.status == "running"
    assert outcome.error_type != "illegal_operation"
    assert outcome.async_task_refs
    assert outcome.async_task_refs[0]["task_type"] == "article_generation"


def test_project_without_questions_auto_plan(fresh_user, monkeypatch):
    """项目暂无问题 → 走自动规划分支（保留原行为）。"""
    db, uid = fresh_user
    pid = _mk_project(db, uid)  # 无问题

    from backend.services.agent_v2.adapters import QuestionPoolAdapter

    async def _fake_generate(*args, **kwargs):
        return 999, []

    async def _fake_plan(*args, **kwargs):
        return None, [10, 11, 12]  # 规划出 3 个问题 id

    monkeypatch.setattr(QuestionPoolAdapter, "generate_articles_sync", _fake_generate)
    monkeypatch.setattr(QuestionPoolAdapter, "plan_batch_sync", _fake_plan)

    outcome = asyncio.run(generate_articles_tool(slots={"project_id": pid, "count": 3}, user_id=uid))
    assert outcome.status == "running"
    assert outcome.error_type != "illegal_operation"
