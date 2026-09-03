from backend.services.smart_article.query_builder import build_queries
from backend.services.smart_article.region_context import build_region_context
from backend.services.smart_article.schemas import PlannedQuestion, ProjectContext


def make_context(industry="企业服务"):
    location, allowed, blocked = build_region_context("广州")
    return ProjectContext(
        project_id=1,
        user_id=1,
        company_name="鲲界科技",
        project_name="智能客服",
        domain_keyword="智能客服",
        industry=industry,
        location=location,
        allowed_regions=allowed,
        blocked_regions=blocked,
    )


def test_query_builder_keeps_full_question_and_handles_unstructured_scene():
    context = make_context("")
    planned = PlannedQuestion(
        question="餐饮门店如何选择智能客服系统？",
        intent_type="selection",
        context_type="industry",
        retrieval_terms=["餐饮门店", "咨询分流"],
    )

    queries = build_queries(context, planned)
    texts = [item.text for item in queries]

    assert any(item.kind == "project_identity" for item in queries)
    assert planned.question.rstrip("？?") in texts
    assert any("餐饮门店" in text for text in texts)
    assert len(queries) <= 6


def test_guangzhou_region_query_uses_whitelist_only():
    context = make_context()
    planned = PlannedQuestion(
        question="广州有哪些智能客服公司值得了解？",
        intent_type="provider",
        context_type="region",
    )
    queries = build_queries(context, planned)

    region_queries = [item.text for item in queries if item.kind == "region_verification"]
    assert region_queries
    assert all(any(region in text for region in context.allowed_regions) for text in region_queries)
    assert "北京" not in " ".join(region_queries)
