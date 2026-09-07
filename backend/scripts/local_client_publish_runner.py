# -*- coding: utf-8 -*-
"""Run one local-client publish record with the backend Playwright publisher.

This is intentionally thin: Electron owns task polling/reporting, while this
process owns the actual platform automation so the EXE follows the backend
publisher implementations exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loguru import logger
from playwright.async_api import async_playwright

# 日志初始化放在 sys.path 配置完成之后（见下方 setup_worker_logging），
# 因为 backend.log_setup 需要 backend 包可导入。

# PyInstaller 环境下 __file__ 指向临时目录，需要特殊处理
if getattr(sys, "frozen", False):
    # PyInstaller 打包后：exe 在 backend/scripts/dist/ 中
    # 向上三级到 resources/backend/（即 backend 包根目录）
    ROOT = Path(sys.executable).resolve().parent.parent.parent
else:
    # 开发模式：scripts/local_client_publish_runner.py → parents[1] = backend/
    ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ==================== 日志初始化 ====================
# stdout 承载 JSON 结果协议（Electron 读取），绝不能混入日志；
# 日志只写文件（auto_geo_worker_*.log，按日期命名、仅保留最近 3 天），
# 同时可选地把 WARNING+ 级日志打印到 stderr 便于调试。
# setup_worker_logging 会把 stdout/stderr 重配为 UTF-8，保证中文/emoji 输出不乱码。
from backend.log_setup import setup_worker_logging  # noqa: E402

setup_worker_logging()
logger.add(sys.stderr, level=os.environ.get("AUTO_GEO_RUNNER_LOG_LEVEL", "WARNING"))

from backend.config import BROWSER_ARGS, DEFAULT_USER_AGENT, PLATFORMS  # noqa: E402
from backend.services.playwright.publishers import get_publisher, register_publishers  # noqa: E402


def _to_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _to_namespace(val) for key, val in value.items()})
    if isinstance(value, list):
        return [_to_namespace(item) for item in value]
    return value


def _find_chrome() -> str | None:
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), r"Google\Chrome\Application\chrome.exe"
        ),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _normalize_result(result: dict[str, Any], page_url: str | None) -> dict[str, Any]:
    manual_required = bool(
        result.get("manual_required")
        or result.get("requires_manual_intervention")
        or result.get("manual_intervention_required")
    )
    url = result.get("url") or result.get("platform_url") or page_url
    error = result.get("error") or result.get("error_msg") or result.get("message")
    manual_reason = result.get("manual_reason") or result.get("error_msg") or error
    return {
        "success": bool(result.get("success")),
        "url": url,
        "platform_url": url,
        "error": error,
        "error_msg": error,
        "manual_required": manual_required,
        "manual_reason": manual_reason,
        "manual_timeout": bool(result.get("manual_timeout")),
        "error_code": result.get("error_code"),
        "risk_type": result.get("risk_type"),
        "auth_status": result.get("auth_status"),
        "raw": result,
    }


async def _log_manual_event(event: dict[str, Any]) -> None:
    print(f"__AUTO_GEO_EVENT__ {json.dumps(event, ensure_ascii=False)}", file=sys.stderr, flush=True)
    event_type = event.get("type")
    platform = event.get("platform") or "platform"
    stage = event.get("stage") or "current step"
    risk_type = event.get("risk_type") or event.get("error_code") or "manual_required"
    if event_type == "manual_required":
        logger.warning(
            "[{}] 检测到人工验证: stage={} type={} text={}",
            platform,
            stage,
            risk_type,
            event.get("matched_text") or "",
        )
    elif event_type == "manual_resolved":
        logger.info("[{}] 人工验证已解除: stage={}", platform, stage)
    elif event_type == "manual_timeout":
        logger.warning("[{}] 人工验证等待超时: stage={} type={}", platform, stage, risk_type)


async def _run(payload: dict[str, Any]) -> dict[str, Any]:
    platform = payload["platform"]
    article = _to_namespace(payload.get("article") or {})
    account = _to_namespace(payload.get("account") or {})
    storage_state_path = payload.get("storage_state_path")
    headless = bool(payload.get("headless", False))
    attempt_mode = str(payload.get("attempt_mode") or "auto_attempt")

    publisher = None
    try:
        register_publishers(PLATFORMS)
        publisher = get_publisher(platform)
        if hasattr(publisher, "set_attempt_mode"):
            publisher.set_attempt_mode(attempt_mode)
        if hasattr(publisher, "set_manual_event_callback"):
            publisher.set_manual_event_callback(_log_manual_event)
    except Exception as exc:
        logger.exception("注册平台发布器失败")
        return _normalize_result({"success": False, "error_msg": str(exc)}, None)

    if publisher is None:
        return _normalize_result({"success": False, "error_msg": f"未找到平台发布器: {platform}"}, None)

    launch_options: dict[str, Any] = {
        "headless": headless,
        "args": list(BROWSER_ARGS),
        "timeout": 30000,
    }
    chrome = _find_chrome()
    if chrome:
        launch_options["executable_path"] = chrome

    try:
        playwright = await async_playwright().start()
    except Exception as exc:
        logger.exception("启动 playwright 失败")
        return _normalize_result({"success": False, "error_msg": str(exc)}, None)

    browser = None
    context = None
    page = None
    try:
        browser = await playwright.chromium.launch(**launch_options)
        context_options: dict[str, Any] = {
            "user_agent": DEFAULT_USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if storage_state_path and os.path.exists(storage_state_path):
            context_options["storage_state"] = storage_state_path

        context = await browser.new_context(**context_options)
        page = await context.new_page()
        result = await publisher.publish(page, article, account, declare_ai_content=True)

        if storage_state_path:
            await context.storage_state(path=storage_state_path)

        return _normalize_result(result or {}, page.url if page else None)
    except Exception as exc:
        logger.exception("local client backend publish failed")
        return _normalize_result(
            {
                "success": False,
                "error_msg": str(exc),
            },
            page.url if page else None,
        )
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                logger.warning("关闭浏览器上下文失败", exc_info=True)
        if browser:
            try:
                await browser.close()
            except Exception:
                logger.warning("关闭浏览器失败", exc_info=True)
        try:
            await playwright.stop()
        except Exception:
            logger.warning("停止 playwright 失败", exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as file:
        payload = json.load(file)

    result = asyncio.run(_run(payload))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
