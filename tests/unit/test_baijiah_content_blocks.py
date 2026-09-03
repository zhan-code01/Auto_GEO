# -*- coding: utf-8 -*-
"""百家号正文图文分块逻辑测试（纯函数，不依赖浏览器/网络）。

验证 `_build_content_blocks` 能把 content 按图片标记位置切成正确的
text/image 交替块，并保持图文相对顺序，多余图片追加到末尾。
"""

from backend.services.playwright.publishers.baijiahao import BaijiahaoPublisher


def _make_publisher() -> BaijiahaoPublisher:
    return BaijiahaoPublisher("baijiahao", {"name": "百家号"})


def test_no_images_in_content_appends_all_images_at_end():
    pub = _make_publisher()
    content = "这是开头的一段文字。\n\n这是第二段文字。"
    blocks = pub._build_content_blocks(content, ["/tmp/a.jpg", "/tmp/b.jpg"])

    # 一个文字块（含两段） + 两张图追加到末尾
    assert [b["type"] for b in blocks] == ["text", "image", "image"]
    assert "这是开头的一段文字" in blocks[0]["content"]
    assert "这是第二段文字" in blocks[0]["content"]
    assert blocks[1]["content"] == "/tmp/a.jpg"
    assert blocks[2]["content"] == "/tmp/b.jpg"


def test_markdown_images_interleave_with_text():
    pub = _make_publisher()
    content = "第一段。\n\n![](http://x/1.jpg)\n\n第二段。"
    blocks = pub._build_content_blocks(content, ["/tmp/1.jpg"])

    assert [b["type"] for b in blocks] == ["text", "image", "text"]
    assert "第一段" in blocks[0]["content"]
    assert blocks[1]["content"] == "/tmp/1.jpg"
    assert "第二段" in blocks[2]["content"]


def test_html_images_interleave_with_text():
    pub = _make_publisher()
    content = '前文。<img src="http://x/2.jpg" alt="图"> 后文。'
    blocks = pub._build_content_blocks(content, ["/tmp/2.jpg"])

    assert blocks[0]["type"] == "text"
    assert "前文" in blocks[0]["content"]
    assert any(b["type"] == "image" and b["content"] == "/tmp/2.jpg" for b in blocks)
    assert blocks[-1]["type"] == "text"
    assert "后文" in blocks[-1]["content"]


def test_more_marks_than_paths_only_inserts_available_images():
    pub = _make_publisher()
    content = "a\n\n![](http://x/1.jpg)\n\n![](http://x/2.jpg)\n\nb"
    # 只有 1 张图，但 content 有 2 个图片标记
    blocks = pub._build_content_blocks(content, ["/tmp/only.jpg"])

    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["content"] == "/tmp/only.jpg"
    text_blocks = [b["content"] for b in blocks if b["type"] == "text"]
    assert any("a" in t for t in text_blocks)
    assert any("b" in t for t in text_blocks)


def test_empty_content_with_images_yields_only_image_blocks():
    pub = _make_publisher()
    blocks = pub._build_content_blocks("", ["/tmp/x.jpg"])
    assert [b["type"] for b in blocks] == ["image"]
    assert blocks[0]["content"] == "/tmp/x.jpg"


def test_empty_content_and_no_images_yields_no_blocks():
    pub = _make_publisher()
    assert pub._build_content_blocks("", []) == []
