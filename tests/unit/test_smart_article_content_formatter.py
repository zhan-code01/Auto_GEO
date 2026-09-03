from backend.services.smart_article.content_formatter import remove_duplicate_leading_title


def test_removes_matching_markdown_h1_only() -> None:
    content = "# 广州AI数字员工供应商推荐\n\n正文内容"
    assert remove_duplicate_leading_title(content, "广州AI数字员工供应商推荐") == "正文内容"


def test_keeps_different_markdown_h1() -> None:
    content = "# 如何选择数字员工\n\n正文内容"
    assert remove_duplicate_leading_title(content, "广州AI数字员工供应商推荐") == content


def test_removes_matching_html_h1_for_compatibility() -> None:
    content = '<h1 id="title">广州AI数字员工供应商推荐</h1>\n<p>正文内容</p>'
    assert remove_duplicate_leading_title(content, "广州AI数字员工供应商推荐") == "<p>正文内容</p>"
