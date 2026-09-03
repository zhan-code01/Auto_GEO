# -*- coding: utf-8 -*-
"""
贴吧「目标吧」编码单一事实源的单元测试。

覆盖 services/tieba_forum 的编码/解码/合并/规范化契约。这套逻辑被三处依赖
（发布器 tieba.py 读取、client_publish.py payload 解析、account.py 保存接口），
任一处偏离前缀约定都会导致「配置了吧但发布时解析不到」的静默失败，故用 roundtrip
测试锁死契约。纯函数、无服务器/DB 依赖，可直接 `pytest tests/unit/test_tieba_forum.py -v`。
"""

from backend.services.tieba_forum import (
    build_tags_with_forums,
    default_forum_from_tags,
    encode_forum_tag,
    normalize_forum,
    split_forum_tags,
)


class TestNormalizeForum:
    def test_strip_trailing_ba_char(self):
        assert normalize_forum("餐饮创业吧") == "餐饮创业"

    def test_keep_when_only_ba_char(self):
        # 单字"吧"不应被吃掉成空串
        assert normalize_forum("吧") == "吧"

    def test_strip_quotes_and_spaces(self):
        assert normalize_forum('  "餐饮创业"  ') == "餐饮创业"

    def test_empty(self):
        assert normalize_forum("") == ""
        assert normalize_forum("   ") == ""


class TestEncodeDecodeRoundtrip:
    def test_encode_uses_canonical_prefix(self):
        assert encode_forum_tag("餐饮创业") == "吧:餐饮创业"

    def test_encode_normalizes_first(self):
        assert encode_forum_tag("餐饮创业吧") == "吧:餐饮创业"

    def test_default_from_encoded(self):
        assert default_forum_from_tags(["吧:餐饮创业"]) == "餐饮创业"

    def test_roundtrip(self):
        tags = build_tags_with_forums(["餐饮创业", "小吃"], [])
        assert default_forum_from_tags(tags) == "餐饮创业"


class TestSplitForumTags:
    def test_split_preserves_others(self):
        forums, others = split_forum_tags(["吧:餐饮创业", "主账号", "吧:小吃", "高权重"])
        assert forums == ["餐饮创业", "小吃"]
        assert others == ["主账号", "高权重"]

    def test_first_forum_is_default(self):
        forums, _ = split_forum_tags(["吧:小吃", "吧:餐饮创业"])
        assert forums[0] == "小吃"

    def test_recognizes_alt_prefixes(self):
        # 兼容手工录入的其它前缀写法
        forums, _ = split_forum_tags(["目标吧：餐饮创业"])
        assert forums == ["餐饮创业"]

    def test_dedup_forums(self):
        forums, _ = split_forum_tags(["吧:餐饮创业", "吧:餐饮创业"])
        assert forums == ["餐饮创业"]

    def test_none_and_empty(self):
        assert split_forum_tags(None) == ([], [])
        assert split_forum_tags([]) == ([], [])

    def test_no_forum_tags(self):
        forums, others = split_forum_tags(["主账号", "高权重"])
        assert forums == []
        assert others == ["主账号", "高权重"]


class TestBuildTagsWithForums:
    def test_encode_and_prepend_forums(self):
        tags = build_tags_with_forums(["餐饮创业"], ["主账号"])
        assert tags == ["吧:餐饮创业", "主账号"]

    def test_dedup_and_strip_empty(self):
        tags = build_tags_with_forums(["餐饮创业", "餐饮创业", "", "  "], [])
        assert tags == ["吧:餐饮创业"]

    def test_reorder_changes_default(self):
        # 换默认吧 = 调整顺序把目标吧排第一
        _forums, others = split_forum_tags(["吧:小吃", "主账号"])
        tags = build_tags_with_forums(["餐饮创业", "小吃"], others)
        assert default_forum_from_tags(tags) == "餐饮创业"
        assert "主账号" in tags

    def test_empty_forums_keeps_others_only(self):
        tags = build_tags_with_forums([], ["主账号"])
        assert tags == ["主账号"]
        assert default_forum_from_tags(tags) is None


class TestPublisherResolverParity:
    """确保发布器 _resolve_forum 与共享模块解析同一套 tags 得到同一结果。"""

    def test_publisher_matches_shared(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})

        class _Acct:
            tags = ["主账号", "吧:餐饮创业", "吧:小吃"]
            remark = None
            target_forum = None
            forum = None
            forum_name = None

        assert pub._resolve_forum(_Acct()) == default_forum_from_tags(_Acct.tags) == "餐饮创业"

    def test_publisher_prefers_clean_field(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})

        class _Acct:
            target_forum = "小吃"
            tags = ["吧:餐饮创业"]
            remark = None
            forum = None
            forum_name = None

        # 服务端解析好的干净字段优先于 tags
        assert pub._resolve_forum(_Acct()) == "小吃"

    def test_publisher_empty_when_unconfigured(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})

        class _Acct:
            tags = ["主账号"]
            remark = None
            target_forum = None
            forum = None
            forum_name = None

        assert pub._resolve_forum(_Acct()) == ""


class TestTiebaContentLength:
    """锁死贴吧正文长度拦截：硬上限 2000 字，业务上拦截在 1900 字。"""

    def test_max_content_length_is_1900(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})
        assert pub.MAX_CONTENT_LENGTH == 1900
        # 1900 必须严格小于贴吧硬上限 2000，给字数统计口径留余量
        assert pub.MAX_CONTENT_LENGTH < 2000

    def test_short_content_not_truncated(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})
        text = "短" * 100
        assert pub._truncate_content(text, pub.MAX_CONTENT_LENGTH) == text

    def test_long_content_truncated_to_limit(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})
        text = "长" * 3000
        cut = pub._truncate_content(text, pub.MAX_CONTENT_LENGTH)
        assert len(cut) <= pub.MAX_CONTENT_LENGTH
        assert cut.endswith("…")

    def test_truncate_prefers_sentence_boundary(self):
        from backend.services.playwright.publishers.tieba import TiebaPublisher

        pub = TiebaPublisher("tieba", {"id": "tieba", "name": "百度贴吧"})
        text = "第一段话。第二段话。第三段话。" * 300
        cut = pub._truncate_content(text, pub.MAX_CONTENT_LENGTH)
        assert len(cut) <= pub.MAX_CONTENT_LENGTH
        # 在句末标点断开，且以省略号收尾
        assert cut.endswith("…") and "。" in cut[:-1]
