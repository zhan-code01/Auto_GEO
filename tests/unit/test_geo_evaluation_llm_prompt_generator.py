# -*- coding: utf-8 -*-

from backend.services.geo_evaluation_llm_prompt_generator import GeoEvaluationLLMPromptGenerator


def _candidate(question: str, question_type: str):
    return {
        "question": question,
        "question_type": question_type,
        "related_project_name": None,
        "intent_tags": ["推荐"],
        "competitor_names": [],
    }


def test_llm_prompt_generator_fills_short_llm_result_from_candidates():
    generator = GeoEvaluationLLMPromptGenerator(api_key="key", base_url="http://example.com/v1", model="deepseek-v4-flash")

    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return [
                _candidate("上海有哪些适合中小企业的数字营销服务商？", "recommendation"),
            ]
        return []

    generator._request_questions = fake_request

    prompts = generator.generate(
        company_name="测试科技",
        industry="数字营销",
        distribution={"recommendation": 3},
        competitors=[],
        project_terms=[],
        candidates=[
            _candidate("华东地区数字营销服务商怎么选择？", "recommendation"),
            _candidate("预算有限时有哪些靠谱的数字营销公司？", "recommendation"),
            _candidate("本地数字营销供应商有哪些值得关注？", "recommendation"),
        ],
    )

    assert prompts is not None
    assert len(prompts) == 3
    assert all(item["question_type"] == "recommendation" for item in prompts)
    assert prompts[0]["question"] == "上海有哪些适合中小企业的数字营销服务商？"


def test_llm_prompt_generator_rejects_brand_direct_neutral_questions():
    generator = GeoEvaluationLLMPromptGenerator(api_key="key", base_url="http://example.com/v1", model="deepseek-v4-flash")

    valid = generator._validate_items(
        [
            _candidate("测试科技是不是最好的数字营销服务商？", "recommendation"),
            _candidate("广州有哪些适合门店获客的数字营销服务商？", "recommendation"),
        ],
        question_type="recommendation",
        company_name="测试科技",
        existing=[],
    )

    assert [item["question"] for item in valid] == ["广州有哪些适合门店获客的数字营销服务商？"]


def test_llm_prompt_generator_rejects_off_domain_neutral_questions():
    generator = GeoEvaluationLLMPromptGenerator(api_key="key", base_url="http://example.com/v1", model="deepseek-v4-flash")

    valid = generator._validate_items(
        [
            _candidate("能推荐几家专注于中小企业的云服务商吗？", "recommendation"),
            _candidate("中小企业做数字营销有哪些服务商值得了解？", "recommendation"),
        ],
        question_type="recommendation",
        company_name="测试科技",
        industry="数字营销",
        project_terms=[],
        existing=[],
    )

    assert [item["question"] for item in valid] == ["中小企业做数字营销有哪些服务商值得了解？"]


def test_llm_prompt_generator_rejects_pure_knowledge_neutral_questions():
    generator = GeoEvaluationLLMPromptGenerator(api_key="key", base_url="http://example.com/v1", model="deepseek-v4-flash")

    valid = generator._validate_items(
        [
            _candidate("广东地区餐饮企业使用鹅肝酱作为原料时，如何判断其品质稳定性？", "scenario"),
            _candidate("广东地区采购鹅肝酱原料时，有哪些供应商值得长期合作？", "scenario"),
        ],
        question_type="scenario",
        company_name="广东百盛千鲜食品有限公司",
        industry="食品供应链",
        project_terms=["鹅肝酱", "鹅肝供应商"],
        existing=[],
    )

    assert [item["question"] for item in valid] == ["广东地区采购鹅肝酱原料时，有哪些供应商值得长期合作？"]


def test_llm_prompt_generator_accepts_business_understanding_questions():
    generator = GeoEvaluationLLMPromptGenerator(api_key="key", base_url="http://example.com/v1", model="deepseek-v4-flash")

    valid = generator._validate_items(
        [
            _candidate("鹅肝供应商一般需要具备哪些冷链和品质控制能力？", "business_understanding"),
            _candidate("测试科技的鹅肝供应业务有什么优势？", "business_understanding"),
        ],
        question_type="business_understanding",
        company_name="测试科技",
        industry="食品供应链",
        project_terms=["鹅肝供应商"],
        existing=[],
    )

    assert [item["question"] for item in valid] == ["鹅肝供应商一般需要具备哪些冷链和品质控制能力？"]


def test_llm_prompt_generator_returns_none_when_not_configured():
    generator = GeoEvaluationLLMPromptGenerator(api_key="", base_url="", model="deepseek-v4-flash")
    generator.api_key = ""
    generator.base_url = ""

    assert generator.generate(
        company_name="测试科技",
        industry="数字营销",
        distribution={"recommendation": 1},
        competitors=[],
        project_terms=[],
        candidates=[_candidate("数字营销服务商有哪些？", "recommendation")],
    ) is None
