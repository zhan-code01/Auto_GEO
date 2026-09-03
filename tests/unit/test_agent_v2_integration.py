# -*- coding: utf-8 -*-
"""Agent V2 端到端集成测试。

覆盖 PRD 第六章起整图流程：
- 完整端到端流程（chat / plan_questions / generate_articles 双路径 / publish）
- 引导流程触发与跨会话恢复
- 组合意图检测（pending_intents）
- 异步任务通知（async_task_refs）
- 持久化路径（persist_mem 双场景：reply 已填充 vs respond 生成 reply）

不依赖真实数据库和 LLM —— 所有外部调用被 mock。
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.agent_v2.graph import build_graph, run_agent
from backend.services.agent_v2.state import AgentState, make_initial_state


# ============================================================
#  通用 Mock 工厂
# ============================================================

def _make_db_mock() -> MagicMock:
    """构造一个不与真实数据库交互的 SessionLocal 替身。"""
    db = MagicMock()
    db.close = MagicMock()
    db.expire_all = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.add = MagicMock()
    db.query = MagicMock(return_value=MagicMock())
    return db


def _make_session_store_mock(
    *,
    slots: dict | None = None,
    history: list | None = None,
    session_id: str = "v2_test_session",
) -> MagicMock:
    """构造 SessionStore 替身。"""
    store = MagicMock()
    fake_session = MagicMock()
    fake_session.id = session_id
    store.get_or_create_session.return_value = fake_session
    store.get_slots.return_value = slots or {}
    store.get_history.return_value = history or []
    store.patch_slots = MagicMock(return_value=slots or {})
    store.add_message = MagicMock()
    store.update_session_status = MagicMock()
    return store


def _make_fact_store_mock(
    *,
    facts: dict | None = None,
    onboarding_stage: str | None = None,
    onboarding_completed: bool = True,
) -> MagicMock:
    """构造 FactStore 替身。"""
    store = MagicMock()
    store.get_facts.return_value = facts or {}
    store.get_onboarding_stage.return_value = onboarding_stage
    store.is_onboarding_completed.return_value = onboarding_completed
    store.patch_facts = MagicMock()
    store.set_onboarding_completed = MagicMock()
    store.set_onboarding_stage = MagicMock()
    return store


@pytest.fixture
def patch_session_and_fact_stores():
    """统一的 SessionStore/FactStore mock 装配器。

    用法：
        with patch_session_and_fact_stores(slots={...}, facts={...}) as ctx:
            await run_agent(state)
    """
    @contextmanager
    def _factory(
        *,
        slots: dict | None = None,
        history: list | None = None,
        facts: dict | None = None,
        onboarding_stage: str | None = None,
        onboarding_completed: bool = True,
        session_id: str = "v2_test_session",
    ):
        session_store = _make_session_store_mock(
            slots=slots, history=history, session_id=session_id,
        )
        fact_store = _make_fact_store_mock(
            facts=facts,
            onboarding_stage=onboarding_stage,
            onboarding_completed=onboarding_completed,
        )
        db = _make_db_mock()

        def session_local_factory():
            return db

        ctx = {
            "session_store": session_store,
            "fact_store": fact_store,
            "db": db,
        }

        patches = [
            patch("backend.database.SessionLocal", side_effect=session_local_factory),
            # load_context / check_onboarding 顶层导入 SessionLocal，
            # 模块加载时已绑定引用，必须额外 patch 模块属性才能覆盖
            patch(
                "backend.services.agent_v2.nodes.load_context.SessionLocal",
                side_effect=session_local_factory,
            ),
            patch(
                "backend.services.agent_v2.nodes.check_onboarding.SessionLocal",
                side_effect=session_local_factory,
            ),
            patch(
                "backend.services.agent_v2.memory.SessionStore",
                return_value=session_store,
            ),
            patch(
                "backend.services.agent_v2.memory.FactStore",
                return_value=fact_store,
            ),
            # load_context 顶层导入 SessionStore/FactStore，需额外 patch 模块属性
            patch(
                "backend.services.agent_v2.nodes.load_context.SessionStore",
                return_value=session_store,
            ),
            patch(
                "backend.services.agent_v2.nodes.load_context.FactStore",
                return_value=fact_store,
            ),
            # persist_mem / check_onboarding / question_gate 是函数内延迟导入，
            # patch 源模块 memory.SessionStore/FactStore 与 backend.database.SessionLocal 即可生效
        ]
        for p in patches:
            p.start()
        try:
            yield ctx
        finally:
            for p in patches:
                p.stop()

    return _factory


# ============================================================
#  完整端到端流程测试
# ============================================================

class TestEndToEndChatFlow:
    """chat 意图完整流程。"""

    @pytest.mark.asyncio
    async def test_chat_flow_with_rule_shortcut(
        self, patch_session_and_fact_stores,
    ):
        """闲聊消息（命中规则短路）→ load_context → check_onboarding → intent_router → slot_check → respond → persist_mem。

        路径：respond 节点 reply 已被 LLM 生成（_reply_finalized=True）→ persist_mem → 结束。
        """
        state = make_initial_state(
            user_id=1, session_id="v2_chat_1", message="你好",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True, facts={"company_name": "测试公司"},
        ), patch(
            "backend.services.agent_v2.nodes.respond._generate_chat_reply",
            new_callable=AsyncMock,
            return_value="您好！有什么可以帮您的？",
        ):
            final_state = await run_agent(state)

        assert final_state["intent"] == "chat"
        assert final_state["reply"] == "您好！有什么可以帮您的？"
        assert final_state.get("_reply_finalized") is True
        assert final_state.get("_persisted") is True


class TestEndToEndPlanQuestionsFlow:
    """plan_questions 完整流程。"""

    @pytest.mark.asyncio
    async def test_plan_questions_flow(
        self, patch_session_and_fact_stores,
    ):
        """plan_questions：槽位齐全 → execute_tool → persist_mem → respond。

        工具被 mock 返回成功 reply，应走 persist_mem → respond（reply 已存在则终止）。
        """
        state = make_initial_state(
            user_id=1, session_id="v2_pq_1", message="给项目123生成5个问题",
        )
        # 模拟 intent_router 已识别意图与槽位（绕过 LLM）
        # 通过 mock rule_shortcut 强制返回 plan_questions
        with patch_session_and_fact_stores(
            onboarding_completed=True,
            slots={"project_id": 123},
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("plan_questions", {"project_id": 123, "count": 5}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "已生成 5 个问题",
                "actions": [],
                "status": "completed",
                "slots_patch": {"question_ids": [1, 2, 3, 4, 5]},
                "facts_patch": [],
                "async_task_refs": [],
            },
        ):
            final_state = await run_agent(state)

        assert final_state["intent"] == "plan_questions"
        assert final_state["reply"] == "已生成 5 个问题"
        assert final_state["status"] == "completed"
        # slots_patch 应传递到 persist_mem 写入
        assert final_state["slots_patch"].get("question_ids") == [1, 2, 3, 4, 5]


class TestEndToEndGenerateArticlesBatchFlow:
    """generate_articles batch 路径完整流程。"""

    @pytest.mark.asyncio
    async def test_batch_path_full_flow(
        self, patch_session_and_fact_stores,
    ):
        """batch 路径：count + project_id → 绕过 GATE → execute_tool → persist_mem → respond。"""
        state = make_initial_state(
            user_id=1, session_id="v2_ga_batch_1",
            message="给项目123生成5篇文章",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("generate_articles", {"project_id": 123, "count": 5}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "已开始生成 5 篇文章",
                "actions": [{
                    "type": "view_batch_progress",
                    "label": "查看进度",
                    "payload": {"batch_id": 999},
                    "interaction": "frontend_direct",
                }],
                "status": "completed",
                "slots_patch": {
                    "question_batch_id": 888,
                    "article_batch_id": 999,
                    "question_ids": [1, 2, 3, 4, 5],
                    "project_id": 123,
                },
                "facts_patch": [],
                "async_task_refs": [{
                    "task_type": "article_batch",
                    "task_id": 999,
                    "query_tool": "get_article_batch_status",
                }],
            },
        ):
            final_state = await run_agent(state)

        assert final_state["intent"] == "generate_articles"
        assert final_state["reply"] == "已开始生成 5 篇文章"
        assert final_state["slots_patch"].get("article_batch_id") == 999
        assert len(final_state["async_task_refs"]) == 1
        assert final_state["async_task_refs"][0]["task_type"] == "article_batch"


class TestEndToEndGenerateArticlesFromQuestionsFlow:
    """generate_articles from_questions 路径完整流程。"""

    @pytest.mark.asyncio
    async def test_from_questions_path_passes_gate(
        self, patch_session_and_fact_stores,
    ):
        """from_questions 路径：question_ids → GATE 放行 → execute_tool → persist_mem → respond。"""
        state = make_initial_state(
            user_id=1, session_id="v2_ga_q_1",
            message="把这5个问题生成文章",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
            slots={"project_id": 123},
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("generate_articles", {"question_ids": [1, 2, 3, 4, 5]}),
        ), patch(
            "backend.services.agent_v2.adapters.QuestionPoolAdapter.list_questions",
            return_value={"items": [{"id": i} for i in range(1, 6)]},
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "已提交 5 篇文章生成任务",
                "actions": [],
                "status": "completed",
                "slots_patch": {"article_batch_id": 999},
                "facts_patch": [],
                "async_task_refs": [{
                    "task_type": "article_batch",
                    "task_id": 999,
                    "query_tool": "get_article_batch_status",
                }],
            },
        ):
            final_state = await run_agent(state)

        assert final_state["intent"] == "generate_articles"
        assert final_state["questions_ready"] is True
        assert final_state["article_mode"] == "from_questions"
        assert final_state["reply"] == "已提交 5 篇文章生成任务"


class TestEndToEndPublishFlow:
    """publish 完整流程。"""

    @pytest.mark.asyncio
    async def test_publish_flow(
        self, patch_session_and_fact_stores,
    ):
        """publish：槽位齐全 → execute_tool → 异步任务引用。"""
        state = make_initial_state(
            user_id=1, session_id="v2_pub_1",
            message="把文章123发布到账号456",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("publish", {"article_ids": [123], "account_ids": [456]}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "已提交发布任务",
                "actions": [{
                    "type": "view_batch_progress",
                    "label": "查看发布进度",
                    "payload": {"task_id": 777},
                    "interaction": "frontend_direct",
                }],
                "status": "completed",
                "slots_patch": {
                    "publish_task_id": 777,
                    "article_ids": [123],
                    "account_ids": [456],
                },
                "facts_patch": [],
                "async_task_refs": [{
                    "task_type": "publish_task",
                    "task_id": 777,
                    "query_tool": "get_publish_task_status",
                }],
            },
        ):
            final_state = await run_agent(state)

        assert final_state["intent"] == "publish"
        assert final_state["reply"] == "已提交发布任务"
        assert final_state["slots_patch"].get("publish_task_id") == 777
        assert final_state["async_task_refs"][0]["task_type"] == "publish_task"


# ============================================================
#  引导流程测试
# ============================================================

class TestOnboardingFlow:
    """引导流程触发与跨会话恢复。

    对应 PRD 第六章。
    """

    @pytest.mark.asyncio
    async def test_trigger_onboarding_for_zero_client_user(
        self, patch_session_and_fact_stores,
    ):
        """零客户 + 未完成引导 → 触发引导，reply 包含引导提示。"""
        state = make_initial_state(
            user_id=99, session_id="v2_onboard_1", message="你好",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=False,
            onboarding_stage=None,
            facts={},
        ), patch(
            "backend.middleware.user_isolation.scoped_query",
            return_value=MagicMock(count=MagicMock(return_value=0)),
        ):
            final_state = await run_agent(state)

        assert final_state["intent"] == "manage_client"
        assert final_state["status"] == "need_clarification"
        assert "创建客户" in final_state["reply"]
        assert any(a["type"] == "navigate_to_client" for a in final_state["actions"])

    @pytest.mark.asyncio
    async def test_skip_onboarding_when_completed(
        self, patch_session_and_fact_stores,
    ):
        """已完成引导 → 跳过引导，进入 intent_router。"""
        state = make_initial_state(
            user_id=1, session_id="v2_onboard_done", message="你好",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
        ), patch(
            "backend.services.agent_v2.nodes.respond._generate_chat_reply",
            new_callable=AsyncMock,
            return_value="您好！",
        ):
            final_state = await run_agent(state)

        # 不应该走 manage_client 引导分支
        assert final_state["intent"] != "manage_client"

    @pytest.mark.asyncio
    async def test_resume_onboarding_when_paused(
        self, patch_session_and_fact_stores,
    ):
        """有客户但引导未完成 → 继续引导（从暂停处）。"""
        state = make_initial_state(
            user_id=1, session_id="v2_onboard_resume", message="继续",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=False,
            onboarding_stage="upload_knowledge",
            facts={"default_client_id": 123},
        ), patch(
            "backend.middleware.user_isolation.scoped_query",
            return_value=MagicMock(count=MagicMock(return_value=1)),
        ):
            final_state = await run_agent(state)

        assert final_state["status"] == "need_clarification"
        assert "upload_knowledge" in final_state["reply"]

    @pytest.mark.asyncio
    async def test_complete_onboarding_when_has_client_but_unmarked(
        self, patch_session_and_fact_stores,
    ):
        """有客户 + 未标记完成 + 无 stage → 标记完成，进入 intent_router。"""
        state = make_initial_state(
            user_id=1, session_id="v2_onboard_auto", message="你好",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=False,
            onboarding_stage=None,
            facts={"default_client_id": 123},
        ), patch(
            "backend.middleware.user_isolation.scoped_query",
            return_value=MagicMock(count=MagicMock(return_value=1)),
        ), patch(
            "backend.services.agent_v2.nodes.respond._generate_chat_reply",
            new_callable=AsyncMock,
            return_value="您好！",
        ):
            final_state = await run_agent(state)

        # 应该标记完成，进入 intent_router
        assert final_state["onboarding_completed"] is True
        assert final_state["intent"] != "manage_client"


# ============================================================
#  组合意图处理测试
# ============================================================

class TestCompoundIntent:
    """组合意图检测。

    对应 PRD 第九章 9.5 节组合意图依赖。
    """

    def test_detect_publish_after_articles(self):
        """消息含'并发布' → pending_intents 包含 publish。"""
        from backend.services.agent_v2.nodes.intent_router import _detect_pending_intents

        pending = _detect_pending_intents("生成5篇文章并发布", "generate_articles")
        assert "publish" in pending

    def test_detect_generate_after_plan_questions(self):
        """消息含'并生成文章' → pending_intents 包含 generate_articles。"""
        from backend.services.agent_v2.nodes.intent_router import _detect_pending_intents

        pending = _detect_pending_intents("生成问题并生成文章", "plan_questions")
        assert "generate_articles" in pending

    def test_no_pending_for_single_intent(self):
        """单意图消息 → pending_intents 为空。"""
        from backend.services.agent_v2.nodes.intent_router import _detect_pending_intents

        pending = _detect_pending_intents("生成5篇文章", "generate_articles")
        assert pending == []

    def test_pending_intents_not_added_for_wrong_primary(self):
        """主意图不匹配时不追加 pending。"""
        from backend.services.agent_v2.nodes.intent_router import _detect_pending_intents

        # 主意图是 chat，不应该追加 publish
        pending = _detect_pending_intents("生成5篇文章并发布", "chat")
        assert pending == []


# ============================================================
#  防跳步端到端测试
# ============================================================

class TestAntiSkipEndToEnd:
    """防跳步端到端验证。"""

    @pytest.mark.asyncio
    async def test_from_questions_blocked_by_gate_when_no_valid_questions(
        self, patch_session_and_fact_stores,
    ):
        """from_questions 路径 + 池中无有效问题 → GATE 拦截，返回 need_clarification。"""
        state = make_initial_state(
            user_id=1, session_id="v2_skip_1",
            message="生成文章",
        )
        state["session_slots"] = {"project_id": 123}

        with patch_session_and_fact_stores(
            onboarding_completed=True,
            slots={"project_id": 123},
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("generate_articles", {"question_ids": [999]}),  # 不存在的问题
        ), patch(
            "backend.services.agent_v2.adapters.QuestionPoolAdapter.list_questions",
            return_value={"items": []},  # 池里没东西
        ):
            final_state = await run_agent(state)

        assert final_state["questions_ready"] is False
        assert final_state["status"] == "need_clarification"
        # 应有 plan_questions Action
        action_types = [a["type"] for a in final_state["actions"]]
        assert "plan_questions" in action_types

    @pytest.mark.asyncio
    async def test_batch_path_bypasses_gate_completely(
        self, patch_session_and_fact_stores,
    ):
        """batch 路径完全不经过 GATE，即使池里没问题也能执行。"""
        state = make_initial_state(
            user_id=1, session_id="v2_skip_2",
            message="给项目123生成5篇文章",
        )

        gate_called = {"value": False}
        original_list_questions = None

        async def _mock_execute_intent(intent, slots, user_id):
            # 检查执行是否到达工具层（即绕过了 GATE）
            return {
                "reply": "已开始生成",
                "actions": [],
                "status": "completed",
                "slots_patch": {"article_batch_id": 1},
                "facts_patch": [],
                "async_task_refs": [],
            }

        def _gate_spy(*args, **kwargs):
            gate_called["value"] = True
            return {"items": []}

        with patch_session_and_fact_stores(
            onboarding_completed=True,
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("generate_articles", {"project_id": 123, "count": 5}),
        ), patch(
            "backend.services.agent_v2.adapters.QuestionPoolAdapter.list_questions",
            side_effect=_gate_spy,
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            side_effect=_mock_execute_intent,
        ):
            final_state = await run_agent(state)

        # GATE 没被调用（batch 路径绕过）
        assert gate_called["value"] is False
        assert final_state["reply"] == "已开始生成"


# ============================================================
#  持久化路径测试
# ============================================================

class TestPersistMemPaths:
    """persist_mem 双场景测试。

    场景 1：工具执行后 reply 已填充 → persist_mem → respond（终止）
    场景 2：respond 生成 reply → persist_mem（_reply_finalized=True）→ 终止
    """

    @pytest.mark.asyncio
    async def test_persist_after_tool_execution(
        self, patch_session_and_fact_stores,
    ):
        """场景 1：工具执行后 reply 已填充 → persist_mem → respond 终止。"""
        state = make_initial_state(
            user_id=1, session_id="v2_persist_1",
            message="生成问题",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
            slots={"project_id": 123},
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("plan_questions", {"project_id": 123, "count": 5}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "已生成问题",
                "actions": [],
                "status": "completed",
                "slots_patch": {"question_ids": [1, 2]},
                "facts_patch": [],
                "async_task_refs": [],
            },
        ) as exec_mock:
            final_state = await run_agent(state)

        # 工具被调用
        exec_mock.assert_awaited_once()
        # 持久化被标记
        assert final_state.get("_persisted") is True
        # 回复被保留
        assert final_state["reply"] == "已生成问题"

    @pytest.mark.asyncio
    async def test_persist_after_respond_generated_reply(
        self, patch_session_and_fact_stores,
    ):
        """场景 2：respond 生成 reply → persist_mem（_reply_finalized=True）→ 终止。"""
        state = make_initial_state(
            user_id=1, session_id="v2_persist_2", message="你好",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
        ), patch(
            "backend.services.agent_v2.nodes.respond._generate_chat_reply",
            new_callable=AsyncMock,
            return_value="您好！",
        ):
            final_state = await run_agent(state)

        assert final_state.get("_reply_finalized") is True
        assert final_state.get("_persisted") is True
        assert final_state["reply"] == "您好！"


# ============================================================
#  错误处理测试
# ============================================================

class TestErrorHandling:
    """错误处理与降级。"""

    @pytest.mark.asyncio
    async def test_tool_exception_falls_back_to_error_reply(
        self, patch_session_and_fact_stores,
    ):
        """工具执行抛异常 → execute_tool 节点捕获，返回失败 reply。"""
        state = make_initial_state(
            user_id=1, session_id="v2_err_1",
            message="生成问题",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
            slots={"project_id": 123},
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("plan_questions", {"project_id": 123, "count": 5}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("适配器爆炸"),
        ):
            final_state = await run_agent(state)

        assert "执行失败" in final_state["reply"]
        assert final_state["status"] == "failed"

    @pytest.mark.asyncio
    async def test_llm_intent_fallback_on_exception(
        self, patch_session_and_fact_stores,
    ):
        """LLM 分类失败 → fallback 到 unknown 意图，不阻塞流程。

        llm_classify 内部 try/except 已捕获 LLM 异常并返回 unknown，
        因此本测试 mock 的是底层 service.chat_json 抛错，
        验证 llm_classify 的 fallback 逻辑生效、整图不崩溃。
        """
        state = make_initial_state(
            user_id=1, session_id="v2_err_2",
            message="一条无法被规则匹配的消息",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=None,  # 规则不命中，走 LLM
        ), patch(
            "backend.services.ai_generation_service.get_ai_service",
            return_value=MagicMock(
                chat_json=AsyncMock(side_effect=RuntimeError("LLM 挂了")),
            ),
        ), patch(
            "backend.services.agent_v2.nodes.respond._generate_chat_reply",
            new_callable=AsyncMock,
            return_value="您好！",
        ):
            final_state = await run_agent(state)

        # llm_classify 应捕获异常并返回 unknown，流程继续到 respond
        assert final_state["intent"] == "unknown"
        assert "reply" in final_state


# ============================================================
#  跨轮槽位累积测试
# ============================================================

class TestCrossTurnSlotAccumulation:
    """跨轮槽位累积场景。

    对应 PRD 第八章 merge_slots。
    """

    @pytest.mark.asyncio
    async def test_session_slots_used_when_intent_slots_missing(
        self, patch_session_and_fact_stores,
    ):
        """session_slots 中已有 project_id，本轮消息只补充 count → 槽位齐全。"""
        state = make_initial_state(
            user_id=1, session_id="v2_accum_1",
            message="生成5篇",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
            slots={"project_id": 123},  # 上一轮已存
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("generate_articles", {"count": 5}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "已开始生成",
                "actions": [],
                "status": "completed",
                "slots_patch": {"article_batch_id": 1},
                "facts_patch": [],
                "async_task_refs": [],
            },
        ) as exec_mock:
            final_state = await run_agent(state)

        # 工具应被调用，且收到的 slots 应包含合并后的 project_id
        exec_mock.assert_awaited_once()
        called_slots = exec_mock.call_args.args[1] if exec_mock.call_args.args else exec_mock.call_args.kwargs.get("slots")
        assert called_slots.get("project_id") == 123
        assert called_slots.get("count") == 5

    @pytest.mark.asyncio
    async def test_user_facts_provide_default_client_id(
        self, patch_session_and_fact_stores,
    ):
        """user_facts 提供默认 client_id，无需用户本轮再次提供。"""
        state = make_initial_state(
            user_id=1, session_id="v2_accum_2",
            message="建项目",
        )

        with patch_session_and_fact_stores(
            onboarding_completed=True,
            facts={"default_client_id": 999, "company_name": "测试公司"},
        ), patch(
            "backend.services.agent_v2.nodes.intent_router.rule_shortcut",
            return_value=("manage_project", {"project_name": "新项目"}),
        ), patch(
            "backend.services.agent_v2.tools.execute_intent",
            new_callable=AsyncMock,
            return_value={
                "reply": "项目已创建",
                "actions": [],
                "status": "completed",
                "slots_patch": {},
                "facts_patch": [],
                "async_task_refs": [],
            },
        ) as exec_mock:
            final_state = await run_agent(state)

        exec_mock.assert_awaited_once()
        called_slots = exec_mock.call_args.args[1] if exec_mock.call_args.args else exec_mock.call_args.kwargs.get("slots")
        # user_facts 中的 default_client_id 应被合并到 resolved_slots
        assert called_slots.get("default_client_id") == 999
