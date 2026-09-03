from types import SimpleNamespace

import pytest

from backend.services.smart_article.question_planner import SmartArticleQuestionPlanner
from backend.services.smart_article.question_pool_service import _question_dict


def test_expanded_terms_are_limited_to_allowed_relations_and_deduplicated():
    value = [
        {"term": "智慧客服", "relation": "synonym"},
        {"term": "智慧客服", "relation": "adjacent"},
        {"term": "CRM接入", "relation": "concern"},
        {"term": "无关词", "relation": "random"},
    ]
    result = SmartArticleQuestionPlanner._parse_expanded_terms(value)
    assert result == [
        {"term": "智慧客服", "relation": "synonym"},
        {"term": "CRM接入", "relation": "concern"},
    ]


def test_expanded_terms_require_balanced_sixty_forty_mix():
    balanced = [
        {"term": "智能客服", "relation": "synonym"},
        {"term": "智慧客服", "relation": "synonym"},
        {"term": "客服机器人", "relation": "adjacent"},
        {"term": "工单系统", "relation": "adjacent"},
        {"term": "售前咨询", "relation": "scenario"},
        {"term": "售后服务", "relation": "scenario"},
        {"term": "部署成本", "relation": "concern"},
        {"term": "数据安全", "relation": "concern"},
    ]
    too_many_synonyms = [
        *[{"term": f"同义词{i}", "relation": "synonym"} for i in range(7)],
        {"term": "相关概念", "relation": "adjacent"},
        {"term": "使用场景", "relation": "scenario"},
        {"term": "用户关注", "relation": "concern"},
    ]

    assert SmartArticleQuestionPlanner._expanded_term_mix_is_valid(balanced)
    assert not SmartArticleQuestionPlanner._expanded_term_mix_is_valid(too_many_synonyms)


def test_question_dict_exposes_boolean_article_marker():
    row = SimpleNamespace(
        id=3,
        project_id=8,
        question="广州有哪些智能客服公司？",
        source="ai",
        intent_type="provider",
        context_type="region",
        has_article=False,
        article_id=None,
        article_generation_status="idle",
        created_at=None,
        updated_at=None,
    )
    result = _question_dict(row)
    assert result["has_article"] is False
    assert result["article_generation_status"] == "idle"


@pytest.mark.asyncio
async def test_question_planning_keeps_ai_expanded_terms_without_knowledge_lookup():
    class FakeLLM:
        async def json(self, system_prompt, user_prompt, **kwargs):
            if "expanded_term_rules" in user_prompt:
                return {
                    "expanded_terms": [
                        {"term": "智慧客服", "relation": "synonym"},
                        {"term": "AI客服", "relation": "synonym"},
                        {"term": "客服机器人", "relation": "adjacent"},
                        {"term": "工单系统", "relation": "adjacent"},
                        {"term": "售前咨询", "relation": "scenario"},
                        {"term": "部署成本", "relation": "concern"},
                    ],
                    "questions": [
                        {
                            "question": "广州有哪些智慧客服公司值得了解？",
                            "intent_type": "provider",
                            "context_type": "region",
                            "retrieval_terms": ["智慧客服"],
                            "brand_entry_reason": "可自然介绍项目",
                        }
                    ],
                }
            return {
                "selected_questions": [
                    {
                        "question": "广州有哪些智慧客服公司值得了解？",
                        "intent_type": "provider",
                        "context_type": "region",
                        "retrieval_terms": ["智慧客服"],
                        "brand_entry_reason": "可自然介绍项目",
                    }
                ]
            }

    from backend.services.smart_article.question_planner import SmartArticleQuestionPlanner
    from backend.services.smart_article.region_context import build_region_context
    from backend.services.smart_article.schemas import ProjectContext

    location, allowed, blocked = build_region_context("广州")
    context = ProjectContext(
        project_id=1,
        user_id=1,
        company_name="鲲界科技",
        project_name="智能客服",
        domain_keyword="智能客服",
        location=location,
        allowed_regions=allowed,
        blocked_regions=blocked,
    )
    planner = SmartArticleQuestionPlanner(None, FakeLLM())
    result = await planner.plan(context, 1, [])
    assert result[0].question.startswith("广州有哪些智慧客服")
    assert planner.last_expanded_terms == [
        {"term": "智慧客服", "relation": "synonym"},
        {"term": "AI客服", "relation": "synonym"},
        {"term": "客服机器人", "relation": "adjacent"},
        {"term": "工单系统", "relation": "adjacent"},
        {"term": "售前咨询", "relation": "scenario"},
        {"term": "部署成本", "relation": "concern"},
    ]


@pytest.mark.asyncio
async def test_question_planning_enforces_seventy_five_percent_provider_questions():
    expanded_terms = [
        {"term": "智能客服", "relation": "synonym"},
        {"term": "智慧客服", "relation": "synonym"},
        {"term": "客服机器人", "relation": "adjacent"},
        {"term": "工单系统", "relation": "adjacent"},
        {"term": "售前咨询", "relation": "scenario"},
        {"term": "数据安全", "relation": "concern"},
    ]
    questions = [
        {
            "question": f"广州有哪些智能客服服务商值得推荐{i}？",
            "intent_type": "provider",
            "context_type": "region",
            "brand_entry_reason": "可自然介绍项目",
        }
        for i in range(3)
    ] + [
        {
            "question": "企业部署智能客服时需要注意哪些风险？",
            "intent_type": "risk",
            "context_type": "general",
            "brand_entry_reason": "可自然介绍解决方案",
        }
    ]

    class FakeLLM:
        async def json(self, _system_prompt, user_prompt, **_kwargs):
            if "expanded_term_rules" in user_prompt:
                return {"expanded_terms": expanded_terms, "questions": questions}
            return {"selected_questions": questions, "shortage_count": 0}

    from backend.services.smart_article.region_context import build_region_context
    from backend.services.smart_article.schemas import ProjectContext

    location, allowed, blocked = build_region_context("广州")
    context = ProjectContext(
        project_id=1,
        user_id=1,
        company_name="鲲界科技",
        project_name="智能客服",
        domain_keyword="智能客服",
        location=location,
        allowed_regions=allowed,
        blocked_regions=blocked,
    )
    result = await SmartArticleQuestionPlanner(None, FakeLLM()).plan(context, 4, [])

    assert len(result) == 4
    assert sum(item.intent_type == "provider" for item in result) == 3
