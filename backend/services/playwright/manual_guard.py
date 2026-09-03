# -*- coding: utf-8 -*-
"""Manual handoff helpers for Playwright automation."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from loguru import logger
from playwright.async_api import Page

from backend.services.playwright.risk_detector import RiskDetection, risk_detector


ManualEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


def manual_timeout_seconds(default: Optional[int] = None) -> Optional[int]:
    raw = os.getenv("PLAYWRIGHT_MANUAL_TIMEOUT_SECONDS")
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else None


def manual_poll_interval_seconds(default: float = 10.0) -> float:
    try:
        return float(os.getenv("PLAYWRIGHT_MANUAL_POLL_SECONDS", str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class ManualResolution:
    handled: bool
    timed_out: bool
    detection: RiskDetection
    message: str

    def to_result(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "timed_out": self.timed_out,
            "manual_required": True,
            "manual_timeout": self.timed_out,
            "error_code": self.detection.error_code,
            "risk_type": self.detection.risk_type,
            "message": self.message,
            "page_url": self.detection.page_url,
        }


async def wait_for_manual_resolution(
    page: Page,
    *,
    platform: Optional[str] = None,
    stage: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    poll_interval_seconds: Optional[float] = None,
    on_event: Optional[ManualEventCallback] = None,
) -> ManualResolution:
    """Wait for the user to clear a detected manual challenge.

    The browser must already be headed/visible. This function keeps polling the
    same page and returns handled=True once the detector no longer sees risk.
    """

    timeout_seconds = manual_timeout_seconds() if timeout_seconds is None else timeout_seconds
    if timeout_seconds is not None and timeout_seconds <= 0:
        timeout_seconds = None
    poll_interval_seconds = (
        manual_poll_interval_seconds() if poll_interval_seconds is None else poll_interval_seconds
    )
    first_detection = await risk_detector.detect(page, platform=platform, stage=stage)
    if not first_detection.manual_required:
        return ManualResolution(
            handled=True,
            timed_out=False,
            detection=first_detection,
            message="No manual handling required",
        )

    message = _manual_message(first_detection, timeout_seconds)
    logger.warning(message)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await _emit(
        on_event,
        {
            "type": "manual_required",
            "platform": platform,
            "stage": stage,
            "timeout_seconds": timeout_seconds,
            **first_detection.to_dict(),
        },
    )

    deadline = None
    if timeout_seconds is not None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
    while deadline is None or asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_interval_seconds)
        detection = await risk_detector.detect(page, platform=platform, stage=stage)
        if not detection.manual_required:
            logger.info(f"Manual challenge resolved: platform={platform} stage={stage}")
            await _emit(
                on_event,
                {
                    "type": "manual_resolved",
                    "platform": platform,
                    "stage": stage,
                    "page_url": detection.page_url,
                    "page_title": detection.page_title,
                },
            )
            return ManualResolution(
                handled=True,
                timed_out=False,
                detection=first_detection,
                message="Manual challenge resolved",
            )

    timeout_message = (
        f"{platform or 'platform'} manual handling timed out after {timeout_seconds}s "
        f"at {stage or 'current step'}"
    )
    logger.warning(timeout_message)
    await _emit(
        on_event,
        {
            "type": "manual_timeout",
            "platform": platform,
            "stage": stage,
            "timeout_seconds": timeout_seconds,
            **first_detection.to_dict(),
        },
    )
    return ManualResolution(
        handled=False,
        timed_out=True,
        detection=first_detection,
        message=timeout_message,
    )


async def ensure_no_manual_challenge(
    page: Page,
    *,
    platform: Optional[str] = None,
    stage: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    wait_for_resolution: bool = True,
    on_event: Optional[ManualEventCallback] = None,
) -> Optional[ManualResolution]:
    detection = await risk_detector.detect(page, platform=platform, stage=stage)
    if not detection.manual_required:
        return None
    if not wait_for_resolution:
        await _emit(
            on_event,
            {
                "type": "manual_required",
                "platform": platform,
                "stage": stage,
                "timeout_seconds": timeout_seconds,
                **detection.to_dict(),
            },
        )
        return ManualResolution(
            handled=False,
            timed_out=False,
            detection=detection,
            message="Manual challenge detected",
        )
    return await wait_for_manual_resolution(
        page,
        platform=platform,
        stage=stage,
        timeout_seconds=timeout_seconds,
        on_event=on_event,
    )


def manual_timeout_result(resolution: ManualResolution) -> dict[str, Any]:
    detection = resolution.detection
    return {
        "success": False,
        "manual_required": True,
        "manual_timeout": True,
        "requires_manual_intervention": True,
        "error_code": detection.error_code or "MANUAL_TIMEOUT",
        "risk_type": detection.risk_type,
        "platform_url": detection.page_url,
        "error_msg": (
            "平台要求人工验证，当前任务已暂停，请人工处理后重试。"
        ),
    }


def manual_required_result(resolution: ManualResolution) -> dict[str, Any]:
    detection = resolution.detection
    return {
        "success": False,
        "manual_required": True,
        "manual_timeout": False,
        "requires_manual_intervention": True,
        "error_code": detection.error_code or "MANUAL_REQUIRED",
        "risk_type": detection.risk_type,
        "platform_url": detection.page_url,
        "error_msg": "平台要求人工验证，需要切换到可见浏览器处理。",
    }


def _manual_message(detection: RiskDetection, timeout_seconds: Optional[int]) -> str:
    timeout_text = f"{timeout_seconds}s" if timeout_seconds is not None else "disabled"
    return (
        f"Manual handling required: code={detection.error_code} "
        f"type={detection.risk_type} timeout={timeout_text} url={detection.page_url}"
    )


async def _emit(callback: Optional[ManualEventCallback], payload: dict[str, Any]) -> None:
    if not callback:
        return
    try:
        await callback(payload)
    except Exception as exc:
        logger.warning(f"Manual event callback failed: {exc}")
