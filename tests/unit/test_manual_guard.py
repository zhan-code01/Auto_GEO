# -*- coding: utf-8 -*-
"""Tests for Playwright manual handoff waiting."""

import pytest

from backend.services.playwright.manual_guard import (
    ensure_no_manual_challenge,
    manual_timeout_seconds,
    wait_for_manual_resolution,
)
from backend.services.playwright.risk_detector import RiskDetection


class _Page:
    async def bring_to_front(self):
        return None


@pytest.mark.asyncio
async def test_manual_resolution_waits_until_cleared_without_default_timeout(monkeypatch):
    detections = [
        RiskDetection(detected=True, error_code="CAPTCHA_REQUIRED", risk_type="captcha_required"),
        RiskDetection(detected=True, error_code="CAPTCHA_REQUIRED", risk_type="captcha_required"),
        RiskDetection(detected=False, page_url="https://example.test/done", page_title="done"),
    ]
    events = []
    sleeps = []

    async def fake_detect(page, platform=None, stage=None):
        return detections.pop(0)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def on_event(event):
        events.append(event)

    monkeypatch.delenv("PLAYWRIGHT_MANUAL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("backend.services.playwright.manual_guard.risk_detector.detect", fake_detect)
    monkeypatch.setattr("backend.services.playwright.manual_guard.asyncio.sleep", fake_sleep)

    result = await wait_for_manual_resolution(
        _Page(),
        platform="doubao",
        stage="ai_answer",
        poll_interval_seconds=0.1,
        on_event=on_event,
    )

    assert result.handled is True
    assert result.timed_out is False
    assert sleeps == [0.1, 0.1]
    assert [event["type"] for event in events] == ["manual_required", "manual_resolved"]
    assert events[0]["timeout_seconds"] is None


def test_manual_timeout_env_positive_enables_timeout(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MANUAL_TIMEOUT_SECONDS", "300")
    assert manual_timeout_seconds() == 300

    monkeypatch.setenv("PLAYWRIGHT_MANUAL_TIMEOUT_SECONDS", "0")
    assert manual_timeout_seconds() is None


@pytest.mark.asyncio
async def test_manual_detection_can_return_without_waiting(monkeypatch):
    events = []

    async def fake_detect(page, platform=None, stage=None):
        return RiskDetection(detected=True, error_code="LOGIN_REQUIRED", risk_type="login_required")

    async def fake_sleep(seconds):
        raise AssertionError("headless detection should not wait")

    async def on_event(event):
        events.append(event)

    monkeypatch.setattr("backend.services.playwright.manual_guard.risk_detector.detect", fake_detect)
    monkeypatch.setattr("backend.services.playwright.manual_guard.asyncio.sleep", fake_sleep)

    result = await ensure_no_manual_challenge(
        _Page(),
        platform="doubao",
        stage="ai_open",
        wait_for_resolution=False,
        on_event=on_event,
    )

    assert result is not None
    assert result.handled is False
    assert result.timed_out is False
    assert events[0]["type"] == "manual_required"
