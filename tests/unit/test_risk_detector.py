# -*- coding: utf-8 -*-

import pytest

from backend.services.playwright.risk_detector import RiskDetector


class _Locator:
    def __init__(self, visible=False):
        self._visible = visible

    @property
    def first(self):
        return self

    async def is_visible(self, timeout=0):
        return self._visible


class _CsdnEditorPage:
    url = "https://mp.csdn.net/mp_blog/creation/editor"

    async def title(self):
        return "CSDN editor"

    async def evaluate(self, script, *args):
        if "hasEditorSurface" in script:
            return True
        if "rules" in script:
            return None
        raise AssertionError("unexpected evaluate call")

    def locator(self, selector):
        return _Locator(False)


class _CsdnQrVerifyPage(_CsdnEditorPage):
    async def evaluate(self, script, *args):
        if "rules" in script:
            return {
                "marker": "扫码确认",
                "code": "SECURITY_VERIFY_REQUIRED",
                "riskType": "security_verify_required",
                "text": "为保障您的账号安全，请使用您绑定的微信扫码确认",
            }
        if "hasEditorSurface" in script:
            raise AssertionError("manual verification should be detected before trusted editor bypass")
        raise AssertionError("unexpected evaluate call")


@pytest.mark.asyncio
async def test_csdn_loaded_editor_does_not_require_manual_login():
    result = await RiskDetector().detect(_CsdnEditorPage(), platform="csdn", stage="navigate")

    assert result.detected is False
    assert result.manual_required is False
    assert result.page_url == _CsdnEditorPage.url


@pytest.mark.asyncio
async def test_csdn_qr_verification_on_editor_requires_manual_handling():
    result = await RiskDetector().detect(_CsdnQrVerifyPage(), platform="csdn", stage="wait_result")

    assert result.detected is True
    assert result.manual_required is True
    assert result.error_code == "SECURITY_VERIFY_REQUIRED"
    assert result.risk_type == "security_verify_required"
