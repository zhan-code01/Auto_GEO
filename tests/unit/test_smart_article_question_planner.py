from backend.services.smart_article.question_planner import SmartArticleQuestionPlanner
from backend.services.smart_article.region_context import build_region_context
from backend.services.smart_article.schemas import ProjectContext


def test_manual_question_is_not_rewritten_and_is_one_article():
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
    question = "餐饮门店如何选择智能客服系统？"
    planned = SmartArticleQuestionPlanner(None).manual(question, context)

    assert planned.question == question
    assert planned.intent_type == "manual"
    assert planned.context_type == "general"  # no industry field; scenario remains in the question
