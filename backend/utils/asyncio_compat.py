# -*- coding: utf-8 -*-
"""Windows asyncio compatibility helpers.

Playwright needs subprocess support on Windows, so AutoGeo should keep the
Proactor loop policy. Python 3.13 can still emit a noisy internal assertion
from Proactor pipe writes when subprocess pipes are closing; the exception
filter below suppresses only that known benign callback failure.
"""

from __future__ import annotations

import asyncio
import sys
import warnings
from typing import Any, Callable

from loguru import logger


_POLICY_CONFIGURED = False


def configure_windows_asyncio_policy() -> None:
    """Configure Windows asyncio policy once, before Playwright is imported."""
    global _POLICY_CONFIGURED

    if sys.platform != "win32" or _POLICY_CONFIGURED:
        return

    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        _POLICY_CONFIGURED = True
    except AttributeError:
        warnings.warn(
            "WindowsProactorEventLoopPolicy is not available; Playwright subprocess support may fail.",
            RuntimeWarning,
            stacklevel=2,
        )


def install_asyncio_exception_filter(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Suppress the known Python 3.13 Proactor pipe-write assertion noise."""
    if sys.platform != "win32":
        return

    target_loop = loop or asyncio.get_event_loop()
    previous_handler: Callable[[asyncio.AbstractEventLoop, dict[str, Any]], None] | None = (
        target_loop.get_exception_handler()
    )

    def _handler(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        handle_text = str(context.get("handle", ""))

        if isinstance(exc, AssertionError) and "_ProactorBaseWritePipeTransport._loop_writing" in handle_text:
            logger.debug("Suppressed benign Windows Proactor pipe-write assertion.")
            return

        if previous_handler is not None:
            previous_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    target_loop.set_exception_handler(_handler)
