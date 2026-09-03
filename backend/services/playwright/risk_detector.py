# -*- coding: utf-8 -*-
"""Shared Playwright risk-control detection.

The detector does not try to bypass a platform challenge. It only answers:
does the current page need a human before automation can continue?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

from loguru import logger
from playwright.async_api import Page


@dataclass
class RiskDetection:
    detected: bool = False
    error_code: Optional[str] = None
    risk_type: Optional[str] = None
    message: Optional[str] = None
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    matched_text: Optional[str] = None

    @property
    def manual_required(self) -> bool:
        return self.detected and self.risk_type not in {"content_rejected", "selector_changed"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "manual_required": self.manual_required,
            "error_code": self.error_code,
            "risk_type": self.risk_type,
            "message": self.message,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "matched_text": self.matched_text,
        }


class RiskDetector:
    """Detect common login, captcha, verification and platform risk pages."""

    URL_RULES: tuple[tuple[str, str, str], ...] = (
        ("login", "LOGIN_REQUIRED", "login_required"),
        ("signin", "LOGIN_REQUIRED", "login_required"),
        ("sign_in", "LOGIN_REQUIRED", "login_required"),
        ("passport", "LOGIN_REQUIRED", "login_required"),
        ("captcha", "CAPTCHA_REQUIRED", "captcha_required"),
        ("verify", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("verification", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("security", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
    )

    TEXT_RULES: tuple[tuple[str, str, str], ...] = (
        ("扫码登录", "QR_LOGIN_REQUIRED", "qr_login_required"),
        ("二维码登录", "QR_LOGIN_REQUIRED", "qr_login_required"),
        ("微信扫码", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("手机扫码", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("扫码确认", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("微信扫码确认", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("扫码认证", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("实名认证", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("请登录", "LOGIN_REQUIRED", "login_required"),
        ("登录后", "LOGIN_REQUIRED", "login_required"),
        ("验证码", "CAPTCHA_REQUIRED", "captcha_required"),
        ("接收短信验证码", "SMS_VERIFY_REQUIRED", "sms_verify_required"),
        ("获取验证码", "SMS_VERIFY_REQUIRED", "sms_verify_required"),
        ("请输入验证码", "SMS_VERIFY_REQUIRED", "sms_verify_required"),
        ("滑块", "CAPTCHA_REQUIRED", "captcha_required"),
        ("拖动滑块", "CAPTCHA_REQUIRED", "captcha_required"),
        ("人机验证", "CAPTCHA_REQUIRED", "captcha_required"),
        ("安全验证", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("身份验证", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("短信验证", "SMS_VERIFY_REQUIRED", "sms_verify_required"),
        ("手机验证", "SMS_VERIFY_REQUIRED", "sms_verify_required"),
        ("为确保是本人操作", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("使用原设备扫码", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("操作频繁", "RATE_LIMITED", "rate_limited"),
        ("请求频繁", "RATE_LIMITED", "rate_limited"),
        ("稍后再试", "RATE_LIMITED", "rate_limited"),
        ("由于违反用户使用规范", "ACCOUNT_RESTRICTED", "account_restricted"),
        ("账号已被禁言", "ACCOUNT_RESTRICTED", "account_restricted"),
        ("被禁言至", "ACCOUNT_RESTRICTED", "account_restricted"),
        ("账号已被封禁", "ACCOUNT_RESTRICTED", "account_restricted"),
        ("账号被封禁", "ACCOUNT_RESTRICTED", "account_restricted"),
        ("账号异常", "ACCOUNT_ABNORMAL", "account_abnormal"),
        ("账号存在风险", "ACCOUNT_ABNORMAL", "account_abnormal"),
        ("账号安全", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("风险提示", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("检测到风险", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("内容存在风险", "CONTENT_REJECTED", "content_rejected"),
        ("内容违规", "CONTENT_REJECTED", "content_rejected"),
        ("发布失败", "CONTENT_REJECTED", "content_rejected"),
        ("too many requests", "RATE_LIMITED", "rate_limited"),
        ("rate limit", "RATE_LIMITED", "rate_limited"),
        ("captcha", "CAPTCHA_REQUIRED", "captcha_required"),
        ("verification", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("security check", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("account abnormal", "ACCOUNT_ABNORMAL", "account_abnormal"),
    )

    SUSPICIOUS_SELECTORS: tuple[tuple[str, str, str], ...] = (
        ("iframe[src*='captcha']", "CAPTCHA_REQUIRED", "captcha_required"),
        ("iframe[src*='verify']", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("[class*='captcha']", "CAPTCHA_REQUIRED", "captcha_required"),
        ("[id*='captcha']", "CAPTCHA_REQUIRED", "captcha_required"),
        ("[class*='verify']", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("[id*='verify']", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("[class*='security']", "SECURITY_VERIFY_REQUIRED", "security_verify_required"),
        ("form[action*='login']", "LOGIN_REQUIRED", "login_required"),
        ("input[type='password']", "LOGIN_REQUIRED", "login_required"),
        ("[role='dialog'] [class*='login']", "LOGIN_REQUIRED", "login_required"),
        ("[role='dialog'] [id*='login']", "LOGIN_REQUIRED", "login_required"),
        ("img[src*='qrcode']", "QR_LOGIN_REQUIRED", "qr_login_required"),
        ("canvas[class*='qrcode']", "QR_LOGIN_REQUIRED", "qr_login_required"),
    )

    async def detect(self, page: Page, *, platform: Optional[str] = None, stage: Optional[str] = None) -> RiskDetection:
        url = page.url or ""
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass

        parsed = urlsplit(url)
        lowered_url = f"{parsed.netloc}{parsed.path}".lower()
        for marker, code, risk_type in self.URL_RULES:
            if marker in lowered_url:
                return self._result(
                    code,
                    risk_type,
                    f"{platform or 'platform'} requires manual verification at {stage or 'current step'}",
                    url,
                    title,
                    marker,
                )

        if (platform or "").lower() in {"doubao", "qianwen", "deepseek"}:
            try:
                visible_login = await page.evaluate(
                    """() => {
                        const visible = el => {
                            if (!el) return false;
                            const rect = el.getBoundingClientRect();
                            const style = getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0
                                && style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && Number(style.opacity || '1') > 0.01;
                        };
                        return Array.from(document.querySelectorAll('button,a'))
                            .some(el => visible(el) && (el.innerText || '').trim() === '登录');
                    }"""
                )
            except Exception:
                visible_login = False
            if visible_login:
                return self._result(
                    "LOGIN_REQUIRED",
                    "login_required",
                    f"{platform} requires login at {stage or 'current step'}",
                    url,
                    title,
                    "visible-login-action",
                )

        selector_result = await self._detect_by_selector(page, url, title, platform, stage)
        if selector_result.detected:
            return selector_result

        modal_text_result = await self._detect_by_text(page, url, title, platform, stage)
        if modal_text_result.detected:
            return modal_text_result

        if await self._is_trusted_editor_page(page, url, platform):
            return RiskDetection(page_url=url, page_title=title)

        return RiskDetection(page_url=url, page_title=title)

    async def _is_trusted_editor_page(self, page: Page, url: str, platform: Optional[str]) -> bool:
        """Return true when a known publish editor is already usable.

        Some platforms keep login-related words or classes in normal editor
        chrome. Positive editor signals prevent those from being treated as a
        manual login challenge after navigation has already succeeded.
        """
        if (platform or "").lower() != "csdn":
            return False
        if "mp.csdn.net/mp_blog/creation/editor" not in url.lower():
            return False

        try:
            return bool(
                await page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0
                                && style.display !== "none"
                                && style.visibility !== "hidden";
                        };
                        const selectors = [
                            "input[placeholder*='文章标题']",
                            "textarea[placeholder*='文章标题']",
                            "[contenteditable='true']",
                            ".ck-editor",
                            ".ck-content",
                            ".editor",
                            ".editor-container",
                            ".CodeMirror",
                            ".cm-editor"
                        ];
                        const hasEditorSurface = selectors.some((selector) =>
                            Array.from(document.querySelectorAll(selector)).some(visible)
                        );
                        const bodyText = (document.body?.innerText || "").replace(/\\s+/g, " ");
                        const hasPublishAction = bodyText.includes("发布博客")
                            || bodyText.includes("发布文章")
                            || bodyText.includes("保存草稿");
                        return hasEditorSurface && hasPublishAction;
                    }"""
                )
            )
        except Exception as exc:
            logger.debug(f"CSDN editor ready detection skipped: {exc}")
            return False

    async def _detect_by_selector(
        self,
        page: Page,
        url: str,
        title: str,
        platform: Optional[str],
        stage: Optional[str],
    ) -> RiskDetection:
        try:
            matched = await page.evaluate(
                """(rules) => {
                    const visible = (el) => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                            && Number(style.opacity || "1") > 0.01;
                    };
                    const challengeText = (el) =>
                        (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
                    const hasChallengeText = (text) =>
                        /验证码|安全验证|身份验证|短信验证|手机验证|人机验证|拖动|滑块|扫码|captcha|verify|verification/i
                            .test(text);
                    const looksLikeChallengeSurface = (el) => {
                        const tag = el.tagName.toLowerCase();
                        if (tag === "body" || tag === "html" || tag === "head") return false;
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        const text = challengeText(el);
                        const isIframeChallenge = tag === "iframe"
                            && /captcha|verify|geetest|risk/i.test(el.getAttribute("src") || "");
                        const hasInput = Boolean(el.querySelector("input, canvas, iframe, [class*='geetest']"));
                        const isOverlay = style.position === "fixed"
                            || Number.parseInt(style.zIndex || "0", 10) >= 1000
                            || Boolean(el.closest("[role='dialog'], [class*='modal'], [class*='mask'], [class*='overlay']"));
                        const coversMostPage = rect.width > window.innerWidth * 0.9
                            && rect.height > window.innerHeight * 0.9;
                        return isIframeChallenge
                            || (isOverlay && (hasChallengeText(text) || hasInput))
                            || (!coversMostPage && hasChallengeText(text) && hasInput);
                    };

                    for (const [selector, code, riskType] of rules) {
                        for (const el of Array.from(document.querySelectorAll(selector))) {
                            if (!visible(el) || !looksLikeChallengeSurface(el)) continue;
                            return {
                                marker: selector,
                                code,
                                riskType,
                                text: challengeText(el).slice(0, 300),
                            };
                        }
                    }
                    return null;
                }""",
                list(self.SUSPICIOUS_SELECTORS),
            )
        except Exception as exc:
            logger.debug(f"Risk selector detection skipped: {exc}")
            matched = None

        if matched:
            return self._result(
                matched["code"],
                matched["riskType"],
                f"{platform or 'platform'} shows a verification element at {stage or 'current step'}",
                url,
                title,
                matched["marker"],
            )
        return RiskDetection(page_url=url, page_title=title)

    async def _detect_by_text(
        self,
        page: Page,
        url: str,
        title: str,
        platform: Optional[str],
        stage: Optional[str],
    ) -> RiskDetection:
        try:
            matched = await page.evaluate(
                """(rules) => {
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden";
                    };
                    const inEditor = (el) => Boolean(el.closest([
                        "[contenteditable='true']",
                        "textarea",
                        "input",
                        ".ProseMirror",
                        "[class*='editor']",
                        "[class*='publish-editor']"
                    ].join(",")));
                    const promptScope = (el) => Boolean(el.closest([
                        "[role='dialog']",
                        "[class*='modal']",
                        "[class*='toast']",
                        "[class*='message']",
                        "[class*='captcha']",
                        "[class*='verify']",
                        "[class*='login']",
                        "[class*='risk']",
                        "[class*='security']"
                    ].join(",")));
                    const looksLikeOverlay = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return style.position === "fixed"
                            || style.position === "sticky"
                            || style.zIndex !== "auto"
                            || (rect.width >= 280
                                && rect.height >= 120
                                && rect.left > 100
                                && rect.top > 40
                                && rect.right < window.innerWidth - 20);
                    };
                    const highConfidenceManualText = (text) => {
                        const sms = text.includes("接收短信验证码")
                            || (text.includes("获取验证码") && text.includes("手机号"))
                            || (text.includes("请输入验证码") && text.includes("验证"));
                        const device = text.includes("使用原设备扫码")
                            || text.includes("为确保是本人操作")
                            || text.includes("微信扫码")
                            || text.includes("手机扫码")
                            || text.includes("扫码认证")
                            || text.includes("实名认证");
                        const accountRestricted = text.includes("由于违反用户使用规范")
                            || text.includes("账号已被禁言")
                            || text.includes("被禁言至")
                            || text.includes("账号已被封禁")
                            || text.includes("账号被封禁");
                        return sms || device || accountRestricted;
                    };

                    for (const el of Array.from(document.querySelectorAll("body *"))) {
                        if (!visible(el) || inEditor(el)) continue;
                        const text = (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
                        if (!text || text.length > 500) continue;
                        const rule = rules.find(([marker]) => text.toLowerCase().includes(marker.toLowerCase()));
                        if (!rule) continue;
                        if (!promptScope(el) && !looksLikeOverlay(el) && !highConfidenceManualText(text)) continue;
                        return { marker: rule[0], code: rule[1], riskType: rule[2], text: text.slice(0, 300) };
                    }
                    return null;
                }""",
                list(self.TEXT_RULES),
            )
        except Exception as exc:
            logger.debug(f"Risk text detection skipped: {exc}")
            matched = None

        if matched:
            return self._result(
                matched["code"],
                matched["riskType"],
                f"{platform or 'platform'} requires manual handling at {stage or 'current step'}",
                url,
                title,
                matched["text"],
            )
        return RiskDetection(page_url=url, page_title=title)

    @staticmethod
    def _result(
        code: str,
        risk_type: str,
        message: str,
        url: str,
        title: str,
        matched_text: str,
    ) -> RiskDetection:
        return RiskDetection(
            detected=True,
            error_code=code,
            risk_type=risk_type,
            message=message,
            page_url=url,
            page_title=title,
            matched_text=matched_text,
        )


risk_detector = RiskDetector()
