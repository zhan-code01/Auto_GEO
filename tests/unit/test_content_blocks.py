# -*- coding: utf-8 -*-

from backend.services.playwright.publishers.base import BasePublisher


class _DummyPublisher(BasePublisher):
    """最小可实例化子类，只用于测试基类的按原文位置切块逻辑。"""

    async def publish(self, page, article, account, declare_ai_content=True):
        return {"success": False, "platform_url": "", "error_msg": "not implemented"}


def _publisher() -> _DummyPublisher:
    return _DummyPublisher("test", {"name": "测试", "publish_url": "https://example.com"})


def test_blocks_none_without_images():
    publisher = _publisher()
    content = "<p>第一段</p><img src='/static/uploads/a.jpg'><p>第二段</p>"

    assert publisher.build_content_blocks_by_markers(content, []) is None


def test_blocks_none_without_markers():
    publisher = _publisher()
    content = "<p>只有文字，没有任何图片标记</p>"

    assert publisher.build_content_blocks_by_markers(content, ["C:/tmp/a.jpg"]) is None


def test_blocks_html_img_follows_original_position():
    publisher = _publisher()
    content = "<p>第一段文字</p><img src='/static/uploads/a.jpg'><p>第二段文字</p>"

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/tmp/a.jpg"])

    assert blocks == [
        {"type": "text", "content": "第一段文字"},
        {"type": "image", "content": "C:/tmp/a.jpg"},
        {"type": "text", "content": "第二段文字"},
    ]


def test_blocks_markdown_and_html_mixed_order():
    publisher = _publisher()
    content = (
        "开头\n\n"
        "<img alt='首图' src='/static/uploads/first.jpg'>\n\n"
        "中间\n\n"
        "![第二张](/static/uploads/second.jpg)\n\n"
        "结尾"
    )

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/tmp/first.jpg", "C:/tmp/second.jpg"])

    assert [block["type"] for block in blocks] == ["text", "image", "text", "image", "text"]
    assert blocks[1]["content"] == "C:/tmp/first.jpg"
    assert blocks[3]["content"] == "C:/tmp/second.jpg"


def test_blocks_leading_and_trailing_images():
    publisher = _publisher()
    content = "<img src='/a.jpg'>中间文字<img src='/b.jpg'>"

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/a.jpg", "C:/b.jpg"])

    assert [block["type"] for block in blocks] == ["image", "text", "image"]
    assert blocks[0]["content"] == "C:/a.jpg"
    assert blocks[2]["content"] == "C:/b.jpg"


def test_blocks_extra_images_appended_at_end():
    publisher = _publisher()
    content = "<p>只有一张图的标记</p><img src='/a.jpg'>"

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/a.jpg", "C:/extra.jpg"])

    assert [block["type"] for block in blocks] == ["text", "image", "image"]
    assert blocks[2]["content"] == "C:/extra.jpg"


def test_blocks_duplicate_url_only_consumes_one_image():
    publisher = _publisher()
    content = "开头<img src='/a.jpg'>中间<img src='/a.jpg'>结尾"

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/a.jpg"])

    assert [block["type"] for block in blocks] == ["text", "image", "text", "text"]


def test_blocks_max_chars_truncates_last_text_block():
    publisher = _publisher()
    content = "<p>一</p><img src='/a.jpg'><p>二</p><p>三</p>"

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/a.jpg"], max_chars=2)

    assert [block["type"] for block in blocks] == ["text", "image", "text"]
    assert blocks[2]["content"].startswith("二")


def test_blocks_clean_text_keeps_paragraphs_separated():
    publisher = _publisher()
    content = "第一段\n\n**加粗第二段**\n\n![图](/static/uploads/a.jpg)\n\n第三段"

    blocks = publisher.build_content_blocks_by_markers(content, ["C:/tmp/a.jpg"])

    assert blocks[0]["type"] == "text"
    assert "第一段" in blocks[0]["content"]
    assert "第二段" in blocks[0]["content"]
    assert blocks[1]["content"] == "C:/tmp/a.jpg"
    assert blocks[2]["type"] == "text"
    assert "第三段" in blocks[2]["content"]
