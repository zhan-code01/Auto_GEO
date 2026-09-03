# -*- coding: utf-8 -*-
"""Helpers for preparing Playwright storage_state before automation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


KUAISHOU_SESSION_COOKIE_NAMES = {
    "userid",
    "token",
    "kuaishou.server_st",
    "kuaishou.api_st",
    "kuaishou.web_st",
    "kuaishou.web.cp.api_st",
    "clientid",
}

KUAISHOU_COMPAT_DOMAINS = (".kuaishou.com", "cp.kuaishou.com")


def normalize_platform_storage_state(
    platform: str,
    storage_state: dict[str, Any] | None,
    fallback_cookies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a storage_state adjusted for platform-specific compatibility."""
    if not isinstance(storage_state, dict):
        storage_state = {}
    else:
        storage_state = deepcopy(storage_state)

    if "cookies" not in storage_state and fallback_cookies:
        storage_state["cookies"] = deepcopy(fallback_cookies)

    if platform == "kuaishou":
        _normalize_kuaishou_cookies(storage_state)

    return storage_state


def _normalize_kuaishou_cookies(storage_state: dict[str, Any]) -> None:
    cookies = storage_state.get("cookies")
    if not isinstance(cookies, list):
        storage_state["cookies"] = []
        return

    existing = {
        (
            str(cookie.get("name", "")).lower(),
            str(cookie.get("domain", "")).lower(),
            str(cookie.get("path", "/") or "/"),
        )
        for cookie in cookies
        if isinstance(cookie, dict)
    }

    additions: list[dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue

        name = str(cookie.get("name", ""))
        domain = str(cookie.get("domain", "")).lower()
        path = str(cookie.get("path", "/") or "/")
        if name.lower() not in KUAISHOU_SESSION_COOKIE_NAMES or "kuaishou.com" not in domain:
            continue

        for target_domain in KUAISHOU_COMPAT_DOMAINS:
            key = (name.lower(), target_domain.lower(), path)
            if key in existing:
                continue

            cloned = deepcopy(cookie)
            cloned["domain"] = target_domain
            cloned["path"] = path
            additions.append(cloned)
            existing.add(key)

    if additions:
        cookies.extend(additions)
