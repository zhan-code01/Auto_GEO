import asyncio

import pytest
from fastapi import HTTPException

from backend.api import publish


class _Account:
    def __init__(self, platform: str):
        self.platform = platform


def test_publish_platforms_only_returns_registered_publishers(monkeypatch):
    monkeypatch.setattr(publish, "_publishable_platform_ids", lambda: {"zhihu", "jianshu"})

    response = asyncio.run(publish.get_supported_platforms())
    platform_ids = {item["id"] for item in response.data["platforms"]}

    assert platform_ids == {"zhihu", "jianshu"}
    assert "doubao" not in platform_ids
    assert "qianwen" not in platform_ids
    assert "deepseek" not in platform_ids
    assert all(item["publish_supported"] for item in response.data["platforms"])


def test_ai_platform_account_is_rejected_for_publishing(monkeypatch):
    monkeypatch.setattr(publish, "_publishable_platform_ids", lambda: {"zhihu"})

    with pytest.raises(HTTPException) as exc_info:
        publish._validate_publishable_accounts([_Account("qianwen")])

    assert exc_info.value.status_code == 400
    assert "通义千问" in exc_info.value.detail
    assert "不支持文章发布" in exc_info.value.detail
