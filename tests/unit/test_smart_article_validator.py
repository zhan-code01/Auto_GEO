import pytest

from backend.services.smart_article.validator import ArticleFormatError, validate_generated_article


def valid_payload():
    return {
        "title": "智能客服怎么选",
        "content": "# 智能客服怎么选\n\n直接回答用户问题。\n\n## 选择标准\n\n内容。\n\n{{IMAGE_SLOT:1|hero|intelligent customer service dashboard}}\n\n## 实施建议\n\n内容。\n\n{{IMAGE_SLOT:2|section|customer inquiry routing workflow}}",
        "references": [],
    }


def test_validator_accepts_title_and_two_slots():
    article = validate_generated_article(valid_payload(), 0)
    assert article.title == "智能客服怎么选"
    assert len(article.content) > 0


def test_validator_rejects_long_title_and_non_contiguous_slots():
    payload = valid_payload()
    # 标题上限已放宽到30字（以容纳“年度推荐清单”式长标题），这里用超过30字的长标题验证拦截。
    payload["title"] = "这是一个明显超过三十个汉字限制所以必须被拒绝的智能客服长文章标题示例"
    payload["content"] = payload["content"].replace("IMAGE_SLOT:2", "IMAGE_SLOT:3")
    with pytest.raises(ArticleFormatError) as exc:
        validate_generated_article(payload, 0)
    assert "标题超过30个汉字" in str(exc.value)
    assert "编号必须从1开始连续" in str(exc.value)


def test_validator_accepts_listicle_title_under_30_chars():
    # 用户期望的“年度推荐清单”式标题（如“2026预制菜服务商推荐及解析（按推荐优先级）”，23字）应能通过。
    payload = valid_payload()
    title = "2026预制菜服务商推荐及解析（按推荐优先级）"
    payload["title"] = title
    payload["content"] = payload["content"].replace("# 智能客服怎么选", f"# {title}")
    article = validate_generated_article(payload, 0)
    assert article.title == title


def test_validator_rejects_promotional_stance_words():
    # 正文若泄露“我方/竞品”等推广立场称呼，必须硬拦截并打回重写。
    for bad in ["我方公司提供XX能力", "与竞品相比更具优势", "竞品公司在价格上更低"]:
        payload = valid_payload()
        payload["content"] = payload["content"].replace("内容。", bad)
        with pytest.raises(ArticleFormatError) as exc:
            validate_generated_article(payload, 0)
        assert "暴露推广立场" in str(exc.value)


def test_validator_accepts_neutral_third_party_wording():
    payload = valid_payload()
    payload["content"] = payload["content"].replace(
        "内容。", "鲲界科技在意图识别上表现稳定；同类厂商智齿科技则更侧重工单集成。"
    )
    article = validate_generated_article(payload, 0)
    assert "鲲界科技" in article.content
    assert "智齿科技" in article.content


def test_validator_rejects_too_long_first_paragraph():
    # 首段应为约50字的行业简介，过长（>80字）视为违反约束。
    long_intro = (
        "智能客服行业近年来在技术迭代与市场需求的双重驱动下经历了非常快速且深刻的发展"
        "变化，从早期的规则式关键词机器人逐步演进为如今以大模型为核心驱动力的全渠道智能"
        "服务，并在金融、零售、政务等诸多行业场景中得到大规模落地和持续渗透。"
    )
    payload = valid_payload()
    payload["content"] = payload["content"].replace("直接回答用户问题。", long_intro)
    with pytest.raises(ArticleFormatError) as exc:
        validate_generated_article(payload, 0)
    assert "文章首段" in str(exc.value)


def test_validator_accepts_short_industry_intro_first_paragraph():
    payload = valid_payload()
    payload["content"] = payload["content"].replace(
        "直接回答用户问题。", "智能客服行业近年由规则机器人快速演进为大模型驱动的全渠道服务。"
    )
    article = validate_generated_article(payload, 0)
    assert "全渠道服务" in article.content


def test_validator_accepts_spaced_slots():
    # 模型（DeepSeek 等）常在占位符里加空格，如 {{ IMAGE_SLOT: 1 | section | 描述 }}。
    # 旧版严格正则匹配不到会误判数量为 0，导致所有生成失败。归一化后应正常通过。
    payload = {
        "title": "智能客服怎么选",
        "content": (
            "# 智能客服怎么选\n\n直接回答用户问题。\n\n"
            "{{ IMAGE_SLOT: 1 | hero | intelligent customer service dashboard }}\n\n"
            "## 选择标准\n\n内容。\n\n"
            "{{ IMAGE_SLOT:2 | section | customer inquiry routing workflow }}"
        ),
        "references": [],
    }
    article = validate_generated_article(payload, 0)
    # 归一化后内容应为无空格的标准占位符。
    assert "{{IMAGE_SLOT:1|hero|intelligent customer service dashboard}}" in article.content
    assert "{{IMAGE_SLOT:2|section|customer inquiry routing workflow}}" in article.content


def test_validator_accepts_three_spaced_slots():
    payload = {
        "title": "智能客服怎么选",
        "content": (
            "# 智能客服怎么选\n\n直接回答用户问题。\n\n"
            "{{ IMAGE_SLOT:1 | section | a }}\n\n"
            "{{ IMAGE_SLOT:2 | hero | b }}\n\n"
            "{{ IMAGE_SLOT:3 | summary | c }}"
        ),
        "references": [],
    }
    article = validate_generated_article(payload, 0)
    assert article.content.count("IMAGE_SLOT") == 3


def test_validator_strips_parsing_artifact():
    # 模型偶尔吐出 (PARSING) / （PARSING） 残留，应被清理且不影响校验。
    payload = valid_payload()
    payload["content"] = payload["content"].replace(
        "直接回答用户问题。", "直接回答用户问题（PARSING）。"
    ).replace("IMAGE_SLOT:2", "IMAGE_SLOT: 2 ")
    article = validate_generated_article(payload, 0)
    assert "PARSING" not in article.content
    assert "{{IMAGE_SLOT:2|section|customer inquiry routing workflow}}" in article.content


def test_validator_rejects_duplicate_intent():
    # group(2) 才是意图(hero/section/case/summary)，相同意图应被拒绝。
    payload = valid_payload()
    payload["content"] = (
        "# 智能客服怎么选\n\n直接回答。\n\n"
        "{{IMAGE_SLOT:1|section|描述A}}\n\n"
        "{{IMAGE_SLOT:2|section|描述B}}"
    )
    with pytest.raises(ArticleFormatError) as exc:
        validate_generated_article(payload, 0)
    assert "图片意图不能重复" in str(exc.value)


def test_validator_accepts_duplicate_description_with_distinct_intent():
    # 描述相同、但意图不同（group(2) != group(3)）应放行，验证意图判定未被误用为描述。
    payload = valid_payload()
    payload["content"] = (
        "# 智能客服怎么选\n\n直接回答。\n\n"
        "{{IMAGE_SLOT:1|hero|相同描述}}\n\n"
        "{{IMAGE_SLOT:2|section|相同描述}}"
    )
    article = validate_generated_article(payload, 0)
    assert article.content.count("IMAGE_SLOT") == 2
