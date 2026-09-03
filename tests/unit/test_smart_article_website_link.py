from backend.services.smart_article.content_formatter import (
    ensure_company_website_link,
    normalize_website_url,
)
from backend.services.smart_article.schemas import ProjectContext


def test_normalize_website_url():
    assert normalize_website_url("kunjie.example.com") == "https://kunjie.example.com"
    assert normalize_website_url("http://kunjie.example.com") == "http://kunjie.example.com"
    assert normalize_website_url("  ") == ""


def test_first_company_mention_gets_linked_once():
    content = "## 我方公司项目介绍\n\n鲲界科技的智能客服支持全渠道接入。\n\n选择鲲界科技可以降低成本。"
    linked, ok = ensure_company_website_link(content, "鲲界科技", "https://kunjie.example.com")

    assert ok is True
    assert linked.count("[鲲界科技](https://kunjie.example.com)") == 1
    # 首次出现处加链接，后续出现保持纯文本。
    assert linked.index("[鲲界科技]") < linked.index("选择鲲界科技")


def test_existing_link_is_not_duplicated_and_headings_are_skipped():
    content = "## 鲲界科技介绍\n\n[鲲界科技](https://kunjie.example.com)是一家AI公司。"
    linked, ok = ensure_company_website_link(content, "鲲界科技", "https://kunjie.example.com")
    assert ok is True
    assert linked == content

    heading_only = "## 鲲界科技介绍\n\n{{IMAGE_SLOT:1|hero|ai customer service}}"
    unchanged, ok2 = ensure_company_website_link(heading_only, "鲲界科技", "https://kunjie.example.com")
    # 标题行与图片占位符行不插入链接。
    assert ok2 is False
    assert unchanged == heading_only


def test_empty_website_returns_content_unchanged():
    content = "鲲界科技的智能客服。"
    linked, ok = ensure_company_website_link(content, "鲲界科技", "")
    assert ok is False
    assert linked == content


def test_project_context_website_defaults_empty():
    context = ProjectContext(project_id=1, user_id=1, company_name="鲲界科技", project_name="智能客服", domain_keyword="AI客服")
    assert context.website == ""


def test_first_natural_short_name_gets_linked_when_full_name_has_suffix():
    # 系统登记的公司名带后缀/地域，文章自然写成简称，首次出现仍需挂链接。
    content = "## 法式鹅肝供应商推荐：品质与稳定性解析\n\n直接回答\n\n高端酒店采购法式鹅肝，品质与供货稳定性是两大核心诉求。综合行业经验、品控体系、产品线和客户口碑，百盛千鲜是值得优先考虑的供应商之一。"
    linked, ok = ensure_company_website_link(content, "百盛千鲜食品有限公司", "https://baisheng.example.com")

    assert ok is True
    assert linked.count("[百盛千鲜](https://baisheng.example.com)") == 1
    # 跳过标题，链接落在正文首次出现处。
    assert linked.index("[百盛千鲜]") > linked.index("直接回答")


def test_first_natural_short_name_gets_linked_with_location_prefix():
    content = "## 高端预制菜供应商推荐\n\n百盛千鲜专注于鹅肝行业16年，建立了STAR品质标准。"
    linked, ok = ensure_company_website_link(content, "广州百盛千鲜食品有限公司", "https://baisheng.example.com")

    assert ok is True
    assert "[百盛千鲜](https://baisheng.example.com)" in linked
    assert "[广州百盛千鲜](https://baisheng.example.com)" not in linked


def test_longest_variant_match_wins_at_first_position():
    # 同一行同时可能出现长变体和短变体，应优先链接最长、最早出现的那个。
    content = "百盛千鲜食品有限公司专注鹅肝；百盛千鲜也提供礼盒。"
    linked, ok = ensure_company_website_link(content, "百盛千鲜食品有限公司", "https://baisheng.example.com")

    assert ok is True
    # 首次出现的长名称应被链接，而不是先截到短名称。
    assert "[百盛千鲜食品有限公司](https://baisheng.example.com)" in linked
    assert linked.index("[百盛千鲜食品有限公司]") < linked.index("百盛千鲜也提供")
