import time

import pytest

from backend.services.cookie_validator import CookieValidator


def _deepseek_state():
    return {
        "cookies": [
            {
                "name": "next-auth.csrf-token",
                "value": "not-a-login-session",
                "domain": "chat.deepseek.com",
                "path": "/",
                "expires": time.time() + 3600,
            }
        ],
        "origins": [],
    }


def _doubao_cookie_name_only_state():
    return {
        "cookies": [
            {
                "name": "sessionid",
                "value": "stale-or-homepage-cookie",
                "domain": ".doubao.com",
                "path": "/",
                "expires": time.time() + 3600,
            }
        ],
        "origins": [],
    }


def _doubao_browser_verified_state():
    state = _doubao_cookie_name_only_state()
    state["browser_verified_login"] = {
        "platform": "doubao",
        "verified_at": time.time(),
        "method": "dom",
        "reason": "doubao dom probe confirmed",
    }
    return state


def _deepseek_browser_verified_state():
    state = _deepseek_state()
    state["browser_verified_login"] = {
        "platform": "deepseek",
        "verified_at": time.time(),
        "method": "dom",
        "reason": "deepseek dom probe confirmed",
    }
    return state


@pytest.mark.asyncio
async def test_deepseek_inconclusive_storage_state_is_not_authorized(monkeypatch):
    validator = CookieValidator()

    async def inconclusive_api(*_args, **_kwargs):
        return True, "API无结论", {"conclusive": False}

    async def inconclusive_html(*_args, **_kwargs):
        return True, "HTTP无结论", {"conclusive": False}

    monkeypatch.setattr(validator, "_probe_auth_api", inconclusive_api)
    monkeypatch.setattr(validator, "_check_positive_markers", inconclusive_html)

    is_valid, reason, probe_info = await validator.validate("deepseek", _deepseek_state())

    assert is_valid is False
    assert "DeepSeek" in reason
    assert probe_info["method"] == "fallback"


@pytest.mark.asyncio
async def test_deepseek_fast_validation_uses_strict_validation(monkeypatch):
    validator = CookieValidator()

    async def inconclusive_api(*_args, **_kwargs):
        return True, "API无结论", {"conclusive": False}

    async def inconclusive_html(*_args, **_kwargs):
        return True, "HTTP无结论", {"conclusive": False}

    monkeypatch.setattr(validator, "_probe_auth_api", inconclusive_api)
    monkeypatch.setattr(validator, "_check_positive_markers", inconclusive_html)

    fast_valid, fast_reason = await validator.validate_fast("deepseek", _deepseek_state())

    assert fast_valid is False
    assert "strict layer=5" in fast_reason


@pytest.mark.asyncio
async def test_deepseek_recent_browser_verified_state_is_authorized_when_inconclusive(monkeypatch):
    validator = CookieValidator()

    async def inconclusive_api(*_args, **_kwargs):
        return True, "API无结论", {"conclusive": False}

    async def inconclusive_html(*_args, **_kwargs):
        return True, "HTTP无结论", {"conclusive": False}

    monkeypatch.setattr(validator, "_probe_auth_api", inconclusive_api)
    monkeypatch.setattr(validator, "_check_positive_markers", inconclusive_html)

    is_valid, reason, probe_info = await validator.validate("deepseek", _deepseek_browser_verified_state())
    fast_valid, fast_reason = await validator.validate_fast("deepseek", _deepseek_browser_verified_state())

    assert is_valid is True
    assert "DeepSeek" in reason
    assert probe_info["method"] == "browser_verified_login"
    assert fast_valid is True
    assert "strict layer=2" in fast_reason


@pytest.mark.asyncio
async def test_deepseek_confirmed_api_user_response_is_authorized(monkeypatch):
    validator = CookieValidator()

    async def confirmed_api(*_args, **_kwargs):
        return True, "API返回用户数据", {"conclusive": True, "status": 200}

    monkeypatch.setattr(validator, "_probe_auth_api", confirmed_api)

    is_valid, reason, probe_info = await validator.validate("deepseek", _deepseek_state())

    assert is_valid is True
    assert reason == "API返回用户数据"
    assert probe_info["method"] == "api_probe"


def test_deepseek_user_response_detection_accepts_nested_identity():
    validator = CookieValidator()

    body = '{"code":0,"data":{"biz_data":{"user":{"uid":"u_123","nickname":"tester"}}}}'

    assert validator._is_api_user_response(body) is True


@pytest.mark.asyncio
async def test_doubao_cookie_name_only_is_not_authorized_when_inconclusive(monkeypatch):
    validator = CookieValidator()

    async def inconclusive_api(*_args, **_kwargs):
        return True, "API无结论", {"conclusive": False}

    async def inconclusive_html(*_args, **_kwargs):
        return True, "HTTP无结论", {"conclusive": False}

    monkeypatch.setattr(validator, "_probe_auth_api", inconclusive_api)
    monkeypatch.setattr(validator, "_check_positive_markers", inconclusive_html)

    is_valid, reason, probe_info = await validator.validate("doubao", _doubao_cookie_name_only_state())
    fast_valid, fast_reason = await validator.validate_fast("doubao", _doubao_cookie_name_only_state())

    assert is_valid is False
    assert "豆包" in reason
    assert probe_info["method"] == "fallback"
    assert fast_valid is False
    assert "strict layer=5" in fast_reason


@pytest.mark.asyncio
async def test_doubao_recent_browser_verified_state_is_authorized_when_inconclusive(monkeypatch):
    validator = CookieValidator()

    async def inconclusive_api(*_args, **_kwargs):
        return True, "API无结论", {"conclusive": False}

    async def inconclusive_html(*_args, **_kwargs):
        return True, "HTTP无结论", {"conclusive": False}

    monkeypatch.setattr(validator, "_probe_auth_api", inconclusive_api)
    monkeypatch.setattr(validator, "_check_positive_markers", inconclusive_html)

    is_valid, reason, probe_info = await validator.validate("doubao", _doubao_browser_verified_state())
    fast_valid, fast_reason = await validator.validate_fast("doubao", _doubao_browser_verified_state())

    assert is_valid is True
    assert "浏览器" in reason
    assert probe_info["method"] == "browser_verified_login"
    assert fast_valid is True
    assert "strict layer=2" in fast_reason
