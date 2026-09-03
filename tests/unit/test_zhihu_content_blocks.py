# -*- coding: utf-8 -*-

from backend.services.playwright.publishers.zhihu import ZhihuPublisher


def _publisher() -> ZhihuPublisher:
    return ZhihuPublisher("zhihu", {"name": "知乎", "publish_url": "https://zhuanlan.zhihu.com/write"})


def test_build_content_blocks_keeps_html_image_position():
    publisher = _publisher()
    content = "<p>第一段文字</p><img src='/static/uploads/a.jpg'><p>第二段文字</p>"

    blocks = publisher._build_content_blocks(content, ["C:/tmp/a.jpg"])

    assert blocks == [
        {"type": "text", "content": "第一段文字"},
        {"type": "image", "content": "C:/tmp/a.jpg"},
        {"type": "text", "content": "第二段文字"},
    ]


def test_extract_and_build_content_blocks_follow_mixed_image_order():
    publisher = _publisher()
    content = (
        "开头\n\n"
        "<img alt='首图' src='/static/uploads/first.jpg'>\n\n"
        "中间\n\n"
        "![第二张](/static/uploads/second.jpg)\n\n"
        "结尾"
    )

    assert publisher._extract_image_urls_from_html(content) == [
        "/static/uploads/first.jpg",
        "/static/uploads/second.jpg",
    ]

    blocks = publisher._build_content_blocks(content, ["C:/tmp/first.jpg", "C:/tmp/second.jpg"])

    assert [block["type"] for block in blocks] == ["text", "image", "text", "image", "text"]
    assert blocks[1]["content"] == "C:/tmp/first.jpg"
    assert blocks[3]["content"] == "C:/tmp/second.jpg"
