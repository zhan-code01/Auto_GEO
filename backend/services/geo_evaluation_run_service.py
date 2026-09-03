# -*- coding: utf-8 -*-
"""
GEO 测评任务执行服务

创建 baseline / recheck 任务，调度真实 Playwright 平台提问，并使用真实 LLM judge 评估。
公司级别粒度：client_id 是主键，project_id 用于生成业务维度问题。

所有耗时任务均为 async，API 层通过 BackgroundTasks 调度，避免阻塞 HTTP 响应。
"""

import asyncio
import os
import random
import time
import threading
from types import SimpleNamespace
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from backend.database.models import (
    GeoEvaluationRun, GeoEvaluationRecord,
    Account, GeoPromptSet, GeoPrompt, Project, Client,
)
from backend.services.geo_evaluation_prompt_service import GeoEvaluationPromptService
from backend.services.geo_response_judge_service import GeoResponseJudgeService
from backend.services.crypto import decrypt_storage_state
from backend.utils.asyncio_compat import install_asyncio_exception_filter
from loguru import logger


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


EVALUATION_QUESTION_LIMIT = _env_int("GEO_EVALUATION_QUESTION_LIMIT", 100)
EVALUATION_MAX_ATTEMPTS = _env_int("GEO_EVALUATION_MAX_ATTEMPTS", 3)
EVALUATION_MIN_DELAY_SECONDS = _env_float("GEO_EVALUATION_MIN_DELAY_SECONDS", 10.0)
EVALUATION_MAX_DELAY_SECONDS = _env_float("GEO_EVALUATION_MAX_DELAY_SECONDS", 15.0)
EVALUATION_MIN_PLATFORM_INTERVAL_SECONDS = _env_float("GEO_EVALUATION_MIN_PLATFORM_INTERVAL_SECONDS", 10.0)
EVALUATION_RETRY_MIN_DELAY_SECONDS = _env_float("GEO_EVALUATION_RETRY_MIN_DELAY_SECONDS", 10.0)
EVALUATION_RETRY_MAX_DELAY_SECONDS = _env_float("GEO_EVALUATION_RETRY_MAX_DELAY_SECONDS", 15.0)
QIANWEN_MIN_DELAY_SECONDS = _env_float("GEO_QIANWEN_MIN_DELAY_SECONDS", 10.0)
QIANWEN_MAX_DELAY_SECONDS = _env_float("GEO_QIANWEN_MAX_DELAY_SECONDS", 15.0)
QIANWEN_MIN_PLATFORM_INTERVAL_SECONDS = _env_float("GEO_QIANWEN_MIN_PLATFORM_INTERVAL_SECONDS", 10.0)
QIANWEN_RETRY_MIN_DELAY_SECONDS = _env_float("GEO_QIANWEN_RETRY_MIN_DELAY_SECONDS", 10.0)
QIANWEN_RETRY_MAX_DELAY_SECONDS = _env_float("GEO_QIANWEN_RETRY_MAX_DELAY_SECONDS", 15.0)
EVALUATION_CONSECUTIVE_FAILURE_LIMIT = _env_int("GEO_EVALUATION_CONSECUTIVE_FAILURE_LIMIT", 3)
EVALUATION_RISK_COOLDOWN_SECONDS = _env_float("GEO_EVALUATION_RISK_COOLDOWN_SECONDS", 300.0)
EVALUATION_STOP_ON_RISK_CONTROL = _env_bool("GEO_EVALUATION_STOP_ON_RISK_CONTROL", True)
ACTIVE_RUN_GRACE_SECONDS = 5
CLIENT_EVALUATION_PENDING_MARKER = "local_client_pending"
AI_EVALUATION_PLATFORMS = ["doubao", "qianwen", "deepseek"]
AI_PLATFORM_NAMES = {
    "doubao": "豆包",
    "qianwen": "通义千问",
    "deepseek": "DeepSeek",
}


def _resolve_evaluation_account(
    db: Session,
    *,
    user_id: int,
    platform: str,
    account_id: Optional[int],
) -> tuple[Optional[Account], Optional[str]]:
    def is_browser_verified(account: Account) -> bool:
        if account.platform != "doubao":
            return True
        state = decrypt_storage_state(account.storage_state) if account.storage_state else {}
        marker = state.get("browser_verified_login") if isinstance(state, dict) else {}
        return bool(
            isinstance(marker, dict)
            and marker.get("platform") == "doubao"
            and marker.get("method") in {"api", "dom"}
        )

    query = db.query(Account).filter(
        Account.user_id == user_id,
        Account.platform == platform,
        Account.status == 1,
        Account.deleted_at.is_(None),
        Account.storage_state.isnot(None),
    )
    if account_id:
        account = query.filter(Account.id == account_id).first()
        if not account:
            return None, "选择的授权账户无效或登录状态不可用"
        if not is_browser_verified(account):
            return None, "选择的豆包账户只有Cookie记录，未确认真实登录，请先重新授权"
        return account, None
    accounts = [account for account in query.order_by(Account.id.asc()).all() if is_browser_verified(account)]
    if len(accounts) == 1:
        return accounts[0], None
    if not accounts:
        return None, "当前平台没有有效授权账户，请先完成管理授权"
    return None, "当前平台存在多个有效账户，请先选择本次测评使用的账户"


_ACTIVE_RUN_IDS: set[int] = set()
_ACTIVE_RUN_IDS_LOCK = threading.Lock()
_PLATFORM_RUN_LOCKS: Dict[str, threading.Lock] = {}
_PLATFORM_RUN_LOCKS_GUARD = threading.Lock()
_PLATFORM_COOLDOWN_UNTIL: Dict[str, float] = {}
_PLATFORM_COOLDOWN_LOCK = threading.Lock()
_PLATFORM_RISK_ACK_REQUIRED: Dict[str, Dict[str, Any]] = {}
_PLATFORM_RISK_ACK_LOCK = threading.Lock()


def _queue_client_evaluation_run(run: GeoEvaluationRun) -> None:
    """Mark a GEO evaluation run for Electron/local-client execution."""
    run.status = "pending"
    run.error_message = CLIENT_EVALUATION_PENDING_MARKER


def _platform_risk_key(user_id: Optional[int], platform: str) -> str:
    return f"{user_id or 0}:{platform}"


def _set_platform_cooldown(user_id: Optional[int], platform: str, seconds: float) -> None:
    if seconds <= 0:
        return
    with _PLATFORM_COOLDOWN_LOCK:
        _PLATFORM_COOLDOWN_UNTIL[_platform_risk_key(user_id, platform)] = time.monotonic() + seconds


def _set_platform_risk_ack_required(
    user_id: Optional[int],
    platform: str,
    *,
    category: str,
    reason: str,
) -> None:
    key = _platform_risk_key(user_id, platform)
    with _PLATFORM_RISK_ACK_LOCK:
        _PLATFORM_RISK_ACK_REQUIRED[key] = {
            "platform": platform,
            "category": category,
            "reason": reason,
            "created_at": time.time(),
        }


def _clear_platform_risk_ack_required(user_id: Optional[int], platforms: List[str]) -> None:
    with _PLATFORM_RISK_ACK_LOCK:
        for platform in platforms:
            _PLATFORM_RISK_ACK_REQUIRED.pop(_platform_risk_key(user_id, platform), None)


def _get_platform_risk_ack_required(user_id: Optional[int], platforms: List[str]) -> List[Dict[str, Any]]:
    with _PLATFORM_RISK_ACK_LOCK:
        return [
            dict(_PLATFORM_RISK_ACK_REQUIRED[_platform_risk_key(user_id, platform)])
            for platform in platforms
            if _platform_risk_key(user_id, platform) in _PLATFORM_RISK_ACK_REQUIRED
        ]


def _reject_platforms_requiring_risk_ack(
    user_id: Optional[int],
    platforms: List[str],
    *,
    risk_acknowledged: bool,
) -> Optional[Dict[str, Any]]:
    if risk_acknowledged:
        _clear_platform_risk_ack_required(user_id, platforms)
        return None

    blocked = _get_platform_risk_ack_required(user_id, platforms)
    if not blocked:
        return None

    names = [AI_PLATFORM_NAMES.get(item["platform"], item["platform"]) for item in blocked]
    return {
        "success": False,
        "message": f"{'、'.join(names)} 平台上次检测到异常，请检查平台状态后再继续。",
        "requires_risk_ack": True,
        "blocked_platforms": blocked,
    }


def _get_platform_cooldown_remaining(user_id: Optional[int], platform: str) -> float:
    with _PLATFORM_COOLDOWN_LOCK:
        until = _PLATFORM_COOLDOWN_UNTIL.get(_platform_risk_key(user_id, platform), 0.0)
    return max(0.0, until - time.monotonic())


def _reject_platforms_in_cooldown(user_id: Optional[int], platforms: List[str]) -> Optional[Dict[str, Any]]:
    blocked = [
        (platform, _get_platform_cooldown_remaining(user_id, platform))
        for platform in platforms
    ]
    blocked = [(platform, remaining) for platform, remaining in blocked if remaining > 0]
    if not blocked:
        return None

    message = "；".join(
        f"{AI_PLATFORM_NAMES.get(platform, platform)} 处于风控冷却中，剩余 {remaining:.0f} 秒"
        for platform, remaining in blocked
    )
    return {
        "success": False,
        "message": message,
        "cooldown": True,
        "blocked_platforms": [
            {"platform": platform, "remaining_seconds": int(remaining)}
            for platform, remaining in blocked
        ],
    }


def _platform_delay_settings(platform: str) -> Dict[str, float]:
    if platform == "qianwen":
        return {
            "min_delay": QIANWEN_MIN_DELAY_SECONDS,
            "max_delay": QIANWEN_MAX_DELAY_SECONDS,
            "min_platform_interval": QIANWEN_MIN_PLATFORM_INTERVAL_SECONDS,
            "retry_min_delay": QIANWEN_RETRY_MIN_DELAY_SECONDS,
            "retry_max_delay": QIANWEN_RETRY_MAX_DELAY_SECONDS,
        }
    return {
        "min_delay": EVALUATION_MIN_DELAY_SECONDS,
        "max_delay": EVALUATION_MAX_DELAY_SECONDS,
        "min_platform_interval": EVALUATION_MIN_PLATFORM_INTERVAL_SECONDS,
        "retry_min_delay": EVALUATION_RETRY_MIN_DELAY_SECONDS,
        "retry_max_delay": EVALUATION_RETRY_MAX_DELAY_SECONDS,
    }


def _classify_platform_failure(error_message: str) -> str:
    text = (error_message or "").lower()
    if "manual_timeout" in text or "人工验证" in error_message:
        return "manual_timeout"
    if "cooldown" in text or "冷却" in error_message:
        return "cooldown"
    risk_keywords = [
        "captcha",
        "verify",
        "verification",
        "human",
        "security",
        "risk",
        "abnormal",
        "验证码",
        "人机",
        "安全验证",
        "风控",
        "异常访问",
        "访问异常",
        "账号异常",
        "账号已被禁言",
        "禁言",
        "违反用户使用规范",
        "操作频繁",
        "请求频繁",
        "稍后再试",
        "too many",
        "rate limit",
        "429",
        "403",
        "forbidden",
    ]
    auth_keywords = ["未授权", "未登录", "登录", "login", "sign in", "auth", "授权已失效", "session"]
    empty_keywords = ["未返回", "空回答", "empty", "no answer", "未能获取"]

    if any(keyword in text for keyword in risk_keywords):
        if "429" in text or "rate limit" in text or "too many" in text or "频繁" in text:
            return "rate_limited"
        return "risk_control"
    if any(keyword in text for keyword in auth_keywords):
        return "auth"
    if "回答质量校验失败" in error_message or "quality" in text or "suspicious" in text:
        return "suspicious_content"
    if any(keyword in text for keyword in empty_keywords):
        return "empty"
    return "unknown"


async def _detect_platform_page_block(page, platform: str) -> Optional[str]:
    """Return a clear platform block/risk message from the current page body."""
    texts: List[str] = []
    try:
        texts.append(await page.inner_text("body", timeout=5000))
    except Exception:
        pass
    try:
        dom_text = await page.evaluate(
            """() => {
                const chunks = [];
                const add = (value) => {
                    const text = (value || '').trim();
                    if (text) chunks.push(text);
                };
                add(document.documentElement && document.documentElement.innerText);
                for (const el of document.querySelectorAll('body *')) {
                    add(el.innerText || el.textContent);
                    add(el.getAttribute && el.getAttribute('aria-label'));
                    add(el.getAttribute && el.getAttribute('title'));
                }
                return chunks.join('\\n');
            }"""
        )
        texts.append(dom_text)
    except Exception:
        pass

    compact = " ".join("\n".join(texts).split())
    if not compact:
        return None

    block_markers = [
        "由于违反用户使用规范",
        "账号已被禁言",
        "被禁言至",
        "禁言",
        "安全验证",
        "验证码",
        "人机验证",
        "请选择所有符合",
        "拖拽到下方",
        "拖拽到这里",
        "露营时可以用到的东西",
        "访问异常",
        "账号异常",
        "操作频繁",
        "请求频繁",
    ]
    if any(marker in compact for marker in block_markers):
        return f"{platform} risk_control 页面处于风控/账号限制状态: {compact[:300]}"
    return None


class _EvaluationRiskGuard:
    def __init__(
        self,
        *,
        user_id: Optional[int],
        min_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        min_platform_interval: Optional[float] = None,
        failure_limit: Optional[int] = None,
        block_cooldown: Optional[float] = None,
        stop_on_block: Optional[bool] = None,
    ):
        self.user_id = user_id
        self.min_delay = EVALUATION_MIN_DELAY_SECONDS if min_delay is None else min_delay
        self.max_delay = EVALUATION_MAX_DELAY_SECONDS if max_delay is None else max_delay
        self.min_platform_interval = (
            EVALUATION_MIN_PLATFORM_INTERVAL_SECONDS
            if min_platform_interval is None
            else min_platform_interval
        )
        self.failure_limit = EVALUATION_CONSECUTIVE_FAILURE_LIMIT if failure_limit is None else failure_limit
        self.block_cooldown = EVALUATION_RISK_COOLDOWN_SECONDS if block_cooldown is None else block_cooldown
        self.stop_on_block = EVALUATION_STOP_ON_RISK_CONTROL if stop_on_block is None else stop_on_block
        self.last_request_at: Dict[str, float] = {}
        self.consecutive_failures: Dict[str, int] = {}

    async def before_request(self, platform: str) -> None:
        delay_settings = _platform_delay_settings(platform)
        configured_min_delay = delay_settings["min_delay"] if self.min_delay == EVALUATION_MIN_DELAY_SECONDS else self.min_delay
        configured_max_delay = delay_settings["max_delay"] if self.max_delay == EVALUATION_MAX_DELAY_SECONDS else self.max_delay
        configured_min_interval = (
            delay_settings["min_platform_interval"]
            if self.min_platform_interval == EVALUATION_MIN_PLATFORM_INTERVAL_SECONDS
            else self.min_platform_interval
        )

        max_delay = max(configured_min_delay, configured_max_delay)
        min_delay = min(configured_min_delay, configured_max_delay)
        last_at = self.last_request_at.get(platform)
        if last_at is None:
            return

        delay = random.uniform(max(0.0, min_delay), max_delay) if max_delay > 0 else 0.0
        delay = max(delay, configured_min_interval)
        if delay > 0:
            elapsed = time.monotonic() - last_at
            logger.info(f"[RunService] {platform} 平台距上次完成 {elapsed:.1f}s，本次节流等待 {delay:.1f}s")
            await asyncio.sleep(delay)

    async def after_request(self, platform: str) -> None:
        self.last_request_at[platform] = time.monotonic()

    def note_success(self, platform: str) -> None:
        self.consecutive_failures[platform] = 0

    def note_failure(self, platform: str, error_message: str) -> Dict[str, Any]:
        category = _classify_platform_failure(error_message)
        failures = self.consecutive_failures.get(platform, 0) + 1
        self.consecutive_failures[platform] = failures

        stop_platform = False
        reason = ""
        if category in {"cooldown", "manual_timeout", "risk_control", "rate_limited", "auth"} and self.stop_on_block:
            stop_platform = True
            reason = f"{platform} 触发疑似{category}，暂停该平台后续评估"
        elif self.failure_limit > 0 and failures >= self.failure_limit:
            stop_platform = True
            reason = f"{platform} 连续失败 {failures} 次，暂停该平台后续评估"

        if stop_platform and category != "cooldown":
            _set_platform_risk_ack_required(
                self.user_id,
                platform,
                category=category,
                reason=reason or error_message[:300],
            )

        return {
            "category": category,
            "consecutive_failures": failures,
            "stop_platform": stop_platform,
            "reason": reason,
        }


def _register_active_run(run_id: int) -> None:
    with _ACTIVE_RUN_IDS_LOCK:
        _ACTIVE_RUN_IDS.add(run_id)


def _unregister_active_run(run_id: int) -> None:
    with _ACTIVE_RUN_IDS_LOCK:
        _ACTIVE_RUN_IDS.discard(run_id)


def _is_active_run_registered(run_id: int) -> bool:
    with _ACTIVE_RUN_IDS_LOCK:
        return run_id in _ACTIVE_RUN_IDS


def _get_platform_run_lock(platform: str) -> threading.Lock:
    with _PLATFORM_RUN_LOCKS_GUARD:
        lock = _PLATFORM_RUN_LOCKS.get(platform)
        if lock is None:
            lock = threading.Lock()
            _PLATFORM_RUN_LOCKS[platform] = lock
        return lock


def _try_acquire_platform_run_locks(platforms: List[str]) -> List[threading.Lock]:
    acquired: List[threading.Lock] = []
    for platform in sorted(set(platforms or [])):
        lock = _get_platform_run_lock(platform)
        if not lock.acquire(blocking=False):
            for acquired_lock in reversed(acquired):
                acquired_lock.release()
            return []
        acquired.append(lock)
    return acquired


def _beijing_now() -> datetime:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)


class GeoEvaluationRunService:
    """GEO 测评任务服务（公司级别）"""

    def __init__(self, db_factory: Callable[[], Session]):
        """
        Args:
            db_factory: 返回新 Session 的可调用对象（用于后台线程获取独立 session）
        """
        self.db_factory = db_factory

    def _new_services(self, db: Session):
        """创建独立的 service 实例"""
        return {
            "prompt": GeoEvaluationPromptService(db),
            "judge": GeoResponseJudgeService(),
        }

    # ── 公开方法（同步，立即返回）──

    @staticmethod
    def _run_includes_platform(run: GeoEvaluationRun, platform: Optional[str]) -> bool:
        if not platform:
            return True
        return platform in (run.platforms or [])

    def _find_active_run(
        self,
        db: Session,
        *,
        client_id: Optional[int],
        project_id: Optional[int],
        prompt_set_id: int,
        phase: str,
        platforms: List[str],
    ) -> Optional[GeoEvaluationRun]:
        now = _beijing_now()
        query = db.query(GeoEvaluationRun).filter(
            GeoEvaluationRun.prompt_set_id == prompt_set_id,
            GeoEvaluationRun.phase == phase,
            GeoEvaluationRun.status.in_(["pending", "running", "manual_required", "interrupted"]),
        )
        if client_id:
            query = query.filter(GeoEvaluationRun.client_id == client_id)
        elif project_id:
            query = query.filter(GeoEvaluationRun.project_id == project_id)

        target_platforms = set(platforms or [])
        recent_runs = query.order_by(GeoEvaluationRun.created_at.desc(), GeoEvaluationRun.id.desc()).limit(50).all()
        for run in recent_runs:
            if not target_platforms.intersection(set(run.platforms or [])):
                continue
            if run.status == "pending" and run.error_message == CLIENT_EVALUATION_PENDING_MARKER:
                return run
            if run.status == "interrupted":
                return run
            if run.claimed_device_id:
                if run.heartbeat_at and (now - run.heartbeat_at).total_seconds() <= 120:
                    return run
                run.status = "interrupted"
                run.interruption_reason = "client_offline"
                run.error_message = "本地客户端心跳中断，可在客户端重新上线后自动继续"
                run.claimed_device_id = None
                db.flush()
                return run
            if _is_active_run_registered(run.id):
                return run

            created_at = run.created_at or run.started_at
            age_seconds = (now - created_at).total_seconds() if created_at else ACTIVE_RUN_GRACE_SECONDS + 1
            if age_seconds <= ACTIVE_RUN_GRACE_SECONDS:
                return run

            run.status = "failed"
            run.finished_at = now
            run.error_message = "任务进程已中断，系统已自动释放运行状态，可重新启动基线任务"
            logger.warning(f"[RunService] 标记僵尸任务为 failed: run={run.id} phase={phase}")
            db.flush()
        return None

    def _find_any_active_run(self, db: Session) -> Optional[GeoEvaluationRun]:
        now = _beijing_now()
        recent_runs = (
            db.query(GeoEvaluationRun)
            .filter(GeoEvaluationRun.status.in_(["pending", "running", "manual_required", "interrupted"]))
            .order_by(GeoEvaluationRun.created_at.desc(), GeoEvaluationRun.id.desc())
            .limit(50)
            .all()
        )
        for run in recent_runs:
            if run.status == "pending" and run.error_message == CLIENT_EVALUATION_PENDING_MARKER:
                return run
            if run.status == "interrupted":
                return run
            if run.claimed_device_id:
                if run.heartbeat_at and (now - run.heartbeat_at).total_seconds() <= 120:
                    return run
                run.status = "interrupted"
                run.interruption_reason = "client_offline"
                run.error_message = "本地客户端心跳中断，可在客户端重新上线后自动继续"
                run.claimed_device_id = None
                db.flush()
                return run
            if _is_active_run_registered(run.id):
                return run

            created_at = run.created_at or run.started_at
            age_seconds = (now - created_at).total_seconds() if created_at else ACTIVE_RUN_GRACE_SECONDS + 1
            if age_seconds <= ACTIVE_RUN_GRACE_SECONDS:
                return run

            run.status = "failed"
            run.finished_at = now
            run.error_message = "任务进程已中断，系统已自动释放运行状态，可重新启动评估任务"
            logger.warning(f"[RunService] Mark stale active run failed: run={run.id} phase={run.phase}")
            db.flush()
        return None

    def _reject_if_global_active(self, db: Session) -> Optional[Dict[str, Any]]:
        active_run = self._find_any_active_run(db)
        if not active_run:
            return None
        return {
            "success": False,
            "message": "已有 GEO 评估任务正在执行。为降低平台风控风险，请等待当前任务完成后再启动新的评估。",
            "active_run_id": active_run.id,
            "active_run_status": active_run.status,
        }

    def _reject_if_platform_active(self, db: Session, platforms: List[str]) -> Optional[Dict[str, Any]]:
        target_platforms = set(platforms or [])
        if not target_platforms:
            return None

        now = _beijing_now()
        recent_runs = (
            db.query(GeoEvaluationRun)
            .filter(GeoEvaluationRun.status.in_(["pending", "running", "manual_required", "interrupted"]))
            .order_by(GeoEvaluationRun.created_at.desc(), GeoEvaluationRun.id.desc())
            .limit(50)
            .all()
        )
        for run in recent_runs:
            overlap = target_platforms.intersection(set(run.platforms or []))
            if not overlap:
                continue
            if run.status == "pending" and run.error_message == CLIENT_EVALUATION_PENDING_MARKER:
                active_platforms = sorted(overlap)
                return {
                    "success": False,
                    "message": f"{', '.join(active_platforms)} 平台已有 GEO 测评任务等待本地客户端执行，请等待完成后再启动同平台测评。",
                    "active_run_id": run.id,
                    "active_run_status": run.status,
                    "active_platforms": active_platforms,
                }
            if run.status == "interrupted":
                # 中断任务保留恢复入口，但不占用平台执行名额。
                continue
            if run.claimed_device_id:
                active_platforms = sorted(overlap)
                if not run.heartbeat_at or (now - run.heartbeat_at).total_seconds() > 120:
                    run.status = "interrupted"
                    run.interruption_reason = "client_offline"
                    run.error_message = "本地客户端心跳中断，请点击“继续执行”后恢复"
                    run.claimed_device_id = None
                    db.flush()
                    continue
                return {
                    "success": False,
                    "message": f"{', '.join(active_platforms)} 平台已有可继续的本地客户端测评任务。",
                    "active_run_id": run.id,
                    "active_run_status": run.status,
                    "active_platforms": active_platforms,
                }
            if _is_active_run_registered(run.id):
                active_platforms = sorted(overlap)
                return {
                    "success": False,
                    "message": f"{', '.join(active_platforms)} 平台已有 GEO 测评任务正在执行，请等待这些平台完成后再启动同平台测评。",
                    "active_run_id": run.id,
                    "active_run_status": run.status,
                    "active_platforms": active_platforms,
                }

            created_at = run.created_at or run.started_at
            age_seconds = (now - created_at).total_seconds() if created_at else ACTIVE_RUN_GRACE_SECONDS + 1
            if age_seconds <= ACTIVE_RUN_GRACE_SECONDS:
                active_platforms = sorted(overlap)
                return {
                    "success": False,
                    "message": f"{', '.join(active_platforms)} 平台已有 GEO 测评任务正在启动，请稍后再启动同平台测评。",
                    "active_run_id": run.id,
                    "active_run_status": run.status,
                    "active_platforms": active_platforms,
                }

            run.status = "failed"
            run.finished_at = now
            run.error_message = "任务进程已中断，系统已自动释放运行状态，可重新启动评估任务"
            logger.warning(f"[RunService] Mark stale active run failed: run={run.id} phase={run.phase}")
            db.flush()

        return None

    @staticmethod
    def _active_prompt_ids(db: Session, prompt_set_id: int) -> List[int]:
        return [
            row[0]
            for row in (
                db.query(GeoPrompt.id)
                .filter(GeoPrompt.prompt_set_id == prompt_set_id, GeoPrompt.status == "active")
                .order_by(GeoPrompt.sort_order, GeoPrompt.id)
                .all()
            )
        ]

    def _unmeasured_baseline_prompt_ids(
        self,
        db: Session,
        *,
        prompt_set_id: int,
        platform: str,
        client_id: Optional[int],
        project_id: Optional[int],
        rebuild: bool = False,
    ) -> List[int]:
        """Return questions never attempted on this platform."""
        prompt_ids = self._active_prompt_ids(db, prompt_set_id)
        if rebuild:
            return prompt_ids
        attempted = (
            _scope_records_query(db, client_id=client_id, project_id=project_id)
            .filter(
                GeoEvaluationRecord.prompt_set_id == prompt_set_id,
                GeoEvaluationRecord.phase == "baseline",
                GeoEvaluationRecord.platform == platform,
                GeoEvaluationRecord.schema_version == "1.0.0",
                GeoEvaluationRecord.prompt_id.is_not(None),
            )
            .with_entities(GeoEvaluationRecord.prompt_id)
            .distinct()
            .all()
        )
        attempted_ids = {row[0] for row in attempted}
        return [prompt_id for prompt_id in prompt_ids if prompt_id not in attempted_ids]

    def _successful_baseline_prompt_ids(
        self,
        db: Session,
        *,
        prompt_set_id: int,
        platform: str,
        client_id: Optional[int],
        project_id: Optional[int],
    ) -> List[int]:
        """Return questions with a successful baseline on this platform."""
        successful = (
            _scope_records_query(db, client_id=client_id, project_id=project_id)
            .filter(
                GeoEvaluationRecord.prompt_set_id == prompt_set_id,
                GeoEvaluationRecord.phase == "baseline",
                GeoEvaluationRecord.platform == platform,
                GeoEvaluationRecord.schema_version == "1.0.0",
                GeoEvaluationRecord.success == True,
                GeoEvaluationRecord.answer.is_not(None),
                GeoEvaluationRecord.prompt_id.is_not(None),
            )
            .with_entities(GeoEvaluationRecord.prompt_id)
            .distinct()
            .all()
        )
        successful_ids = {row[0] for row in successful}
        return [
            prompt_id
            for prompt_id in self._active_prompt_ids(db, prompt_set_id)
            if prompt_id in successful_ids
        ]

    def create_baseline(
        self,
        client_id: Optional[int] = None,
        platforms: Optional[List[str]] = None,
        rounds: int = 1,
        created_by: Optional[int] = None,
        user_id: Optional[int] = None,
        rebuild: bool = False,
        project_id: Optional[int] = None,
        risk_acknowledged: bool = False,
        account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建 baseline 任务（立即返回 run_id，后台执行）

        Args:
            client_id: 公司ID（主键）
            platforms: 要检测的 AI 平台列表
            rounds: 测试轮数
            created_by: 创建者用户ID
            user_id: 当前用户ID（用于加载平台会话）
            rebuild: 是否重建基线
            project_id: 可选，关联项目ID（用于生成业务问题）

        Returns:
            {success, run_id, total_planned, message}
        """
        db = self.db_factory()
        try:
            if not (user_id or created_by):
                return {"success": False, "message": "真实检测需要当前用户ID"}

            project = db.query(Project).filter(Project.id == project_id).first() if project_id else None
            if client_id is None and project and project.client_id:
                client_id = project.client_id

            client = db.query(Client).filter(Client.id == client_id).first() if client_id else None
            if client_id and not client:
                return {"success": False, "message": "公司不存在"}
            if not client and not project:
                return {"success": False, "message": "公司或项目不存在"}

            svc = self._new_services(db)
            prompt_service = svc["prompt"]

            # 校验活跃问题集
            if client_id:
                prompt_set = prompt_service.sync_smart_article_questions(client_id, created_by)
            else:
                prompt_set = (
                    db.query(GeoPromptSet)
                    .filter(
                        GeoPromptSet.project_id == project_id,
                        GeoPromptSet.status.in_(["active", "frozen"]),
                    )
                    .order_by(GeoPromptSet.created_at.desc(), GeoPromptSet.id.desc())
                    .first()
                )
            if not prompt_set:
                return {"success": False, "message": "请先生成测评问题集"}

            # 冻结问题集
            if prompt_set.status != "frozen":
                prompt_service.freeze_prompt_set(prompt_set.id)
                db.flush()

            requested_platforms = [p for p in (platforms or []) if p in AI_EVALUATION_PLATFORMS]
            explicit_platforms = bool(requested_platforms)
            target_platforms = requested_platforms or AI_EVALUATION_PLATFORMS
            if not target_platforms:
                target_platforms = AI_EVALUATION_PLATFORMS
            if len(target_platforms) != 1:
                return {"success": False, "message": "每个本地测评任务只能选择一个平台"}
            account, account_error = _resolve_evaluation_account(
                db,
                user_id=user_id or created_by,
                platform=target_platforms[0],
                account_id=account_id,
            )
            if account_error:
                return {"success": False, "message": account_error, "requires_account_selection": True}

            if not self._active_prompt_ids(db, prompt_set.id):
                return {"success": False, "message": "问题集为空"}

            active_run = self._find_active_run(
                db,
                client_id=client_id,
                project_id=project_id,
                prompt_set_id=prompt_set.id,
                phase="baseline",
                platforms=target_platforms,
            )
            if active_run:
                return {
                    "success": True,
                    "run_id": active_run.id,
                    "total_planned": active_run.total_planned,
                    "message": "当前平台的基线任务正在运行，已切换到已有任务进度",
                    "existing_run": True,
                }

            platform_active = self._reject_if_platform_active(db, target_platforms)
            if platform_active:
                return platform_active

            prompt_ids = self._unmeasured_baseline_prompt_ids(
                db,
                prompt_set_id=prompt_set.id,
                platform=target_platforms[0],
                client_id=client_id,
                project_id=project_id,
                rebuild=rebuild,
            )
            if not prompt_ids:
                return {"success": False, "message": "所选平台没有未测评的新问题"}

            # The run is bound to a concrete Account above. Its encrypted
            # storage_state is the execution source of truth; do not reject it
            # because the legacy user-level session file is absent.
            session_check = {"message_suffix": ""}
            risk_ack_block = _reject_platforms_requiring_risk_ack(
                user_id or created_by,
                target_platforms,
                risk_acknowledged=risk_acknowledged,
            )
            if risk_ack_block:
                return risk_ack_block

            # 重建模式：只清除本次目标平台、当前问题集和当前规则版本的旧 baseline。
            if rebuild:
                old_count = (
                    _scope_records_query(db, client_id=client_id, project_id=project_id)
                    .filter(
                        GeoEvaluationRecord.phase == "baseline",
                        GeoEvaluationRecord.prompt_set_id == prompt_set.id,
                        GeoEvaluationRecord.schema_version == "1.0.0",
                        GeoEvaluationRecord.platform.in_(target_platforms),
                    )
                    .delete(synchronize_session=False)
                )
                db.flush()
                logger.info(f"重建基线：已清除公司 {client_id} 的 {old_count} 条旧 baseline 记录")

            total_planned = len(target_platforms) * len(prompt_ids) * rounds

            beijing_now = _beijing_now()

            run = GeoEvaluationRun(
                client_id=client_id,
                project_id=project_id,
                prompt_set_id=prompt_set.id,
                account_id=account.id,
                phase="baseline",
                platforms=target_platforms,
                prompt_ids=prompt_ids,
                rounds=rounds,
                status="pending",
                total_planned=total_planned,
                total_completed=0,
                total_failed=0,
                current_progress=0,
                created_by=created_by,
                evaluation_schema_version="1.0.0",
                created_at=beijing_now,
            )
            _queue_client_evaluation_run(run)
            db.add(run)
            db.commit()
            run_id = run.id

            # 获取公司信息
            company_name = (client.company_name or client.name) if client else (project.company_name or project.name)
            # 获取官网域名
            official_domains = _get_client_domains(db, client_id) if client_id else _get_project_domains(project)

            # 后台线程执行
            _start_background_run(
                run_id=run_id,
                client_id=client_id,
                project_id=project_id,
                company_name=company_name,
                official_domains=official_domains,
                prompt_set_id=prompt_set.id,
                platforms=target_platforms,
                rounds=rounds,
                user_id=user_id or created_by,
                prompt_ids=prompt_ids,
            )

            return {
                "success": True,
                "run_id": run_id,
                "total_planned": total_planned,
                "message": f"基线任务已创建，将测评 {len(prompt_ids)} 个未测评问题，等待本地客户端执行{session_check.get('message_suffix', '')}",
            }
        except Exception as e:
            db.rollback()
            logger.error(f"创建 baseline 失败: {e}")
            return {"success": False, "message": f"创建基线失败: {str(e)}"}
        finally:
            db.close()

    def create_recheck(
        self,
        client_id: int,
        platforms: Optional[List[str]] = None,
        rounds: int = 1,
        created_by: Optional[int] = None,
        user_id: Optional[int] = None,
        project_id: Optional[int] = None,
        risk_acknowledged: bool = False,
        account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建使用后复测任务（公司级别）"""
        db = self.db_factory()
        try:
            if not (user_id or created_by):
                return {"success": False, "message": "真实检测需要当前用户ID"}

            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                return {"success": False, "message": "公司不存在"}

            svc = self._new_services(db)
            prompt_service = svc["prompt"]

            prompt_set = prompt_service.sync_smart_article_questions(client_id, created_by)
            if not prompt_set:
                return {"success": False, "message": "公司没有测评问题集，请先生成"}

            requested_platforms = [p for p in (platforms or []) if p in AI_EVALUATION_PLATFORMS]
            explicit_platforms = bool(requested_platforms)
            target_platforms = requested_platforms or AI_EVALUATION_PLATFORMS
            if not target_platforms:
                target_platforms = AI_EVALUATION_PLATFORMS
            if len(target_platforms) != 1:
                return {"success": False, "message": "每个本地测评任务只能选择一个平台"}
            account, account_error = _resolve_evaluation_account(
                db,
                user_id=user_id or created_by,
                platform=target_platforms[0],
                account_id=account_id,
            )
            if account_error:
                return {"success": False, "message": account_error, "requires_account_selection": True}

            platform_active = self._reject_if_platform_active(db, target_platforms)
            if platform_active:
                return platform_active

            prompt_ids = self._successful_baseline_prompt_ids(
                db,
                prompt_set_id=prompt_set.id,
                platform=target_platforms[0],
                client_id=client_id,
                project_id=project_id,
            )
            if not prompt_ids:
                return {"success": False, "message": "所选平台没有成功建立基线的问题，无法执行使用后测试"}

            session_check = {"message_suffix": ""}
            risk_ack_block = _reject_platforms_requiring_risk_ack(
                user_id or created_by,
                target_platforms,
                risk_acknowledged=risk_acknowledged,
            )
            if risk_ack_block:
                return risk_ack_block

            total_planned = len(target_platforms) * len(prompt_ids) * rounds

            beijing_now = _beijing_now()

            run = GeoEvaluationRun(
                client_id=client_id,
                project_id=project_id,
                prompt_set_id=prompt_set.id,
                account_id=account.id,
                phase="ongoing",
                platforms=target_platforms,
                prompt_ids=prompt_ids,
                rounds=rounds,
                status="pending",
                total_planned=total_planned,
                total_completed=0,
                total_failed=0,
                current_progress=0,
                created_by=created_by,
                evaluation_schema_version="1.0.0",
                created_at=beijing_now,
            )
            _queue_client_evaluation_run(run)
            db.add(run)
            db.commit()
            run_id = run.id

            company_name = client.company_name or client.name
            official_domains = _get_client_domains(db, client_id)

            _start_background_run(
                run_id=run_id,
                client_id=client_id,
                project_id=project_id,
                company_name=company_name,
                official_domains=official_domains,
                prompt_set_id=prompt_set.id,
                platforms=target_platforms,
                rounds=rounds,
                user_id=user_id or created_by,
                prompt_ids=prompt_ids,
            )

            return {
                "success": True,
                "run_id": run_id,
                "total_planned": total_planned,
                "message": f"复测任务已创建（{total_planned} 条待执行），等待本地客户端执行{session_check.get('message_suffix', '')}",
            }
        except Exception as e:
            db.rollback()
            logger.error(f"创建 recheck 失败: {e}")
            return {"success": False, "message": f"创建复测失败: {str(e)}"}
        finally:
            db.close()

    def complete_baseline(
        self,
        client_id: int,
        platforms: Optional[List[str]] = None,
        created_by: Optional[int] = None,
        user_id: Optional[int] = None,
        project_id: Optional[int] = None,
        risk_acknowledged: bool = False,
        account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """补齐新平台 baseline（只检测缺失 baseline 的平台，公司级别）"""
        db = self.db_factory()
        try:
            if not (user_id or created_by):
                return {"success": False, "message": "真实检测需要当前用户ID"}

            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                return {"success": False, "message": "公司不存在"}

            svc = self._new_services(db)
            prompt_service = svc["prompt"]

            prompt_set = prompt_service.sync_smart_article_questions(client_id, created_by)
            if not prompt_set or prompt_set.status != "frozen":
                return {"success": False, "message": "问题集未冻结，无法补齐基线"}

            # 找出缺失 baseline 的平台
            ALL_PLATFORMS = AI_EVALUATION_PLATFORMS
            existing_baseline_platforms = set()
            for pf in ALL_PLATFORMS:
                count = (
                    db.query(GeoEvaluationRecord)
                    .filter(
                        GeoEvaluationRecord.client_id == client_id,
                        GeoEvaluationRecord.platform == pf,
                        GeoEvaluationRecord.phase == "baseline",
                        GeoEvaluationRecord.prompt_set_id == prompt_set.id,
                        GeoEvaluationRecord.schema_version == "1.0.0",
                        GeoEvaluationRecord.success == True,
                    )
                    .count()
                )
                if count > 0:
                    existing_baseline_platforms.add(pf)

            requested_platforms = [p for p in (platforms or []) if p in ALL_PLATFORMS]
            explicit_platforms = bool(requested_platforms)
            candidate_platforms = requested_platforms or ALL_PLATFORMS
            missing = [p for p in candidate_platforms if p not in existing_baseline_platforms]
            if not missing:
                return {"success": True, "message": "所有平台已有基线，无需补齐", "total_completed": 0}
            if len(missing) != 1:
                return {"success": False, "message": "每个本地测评任务只能选择一个平台"}
            account, account_error = _resolve_evaluation_account(
                db,
                user_id=user_id or created_by,
                platform=missing[0],
                account_id=account_id,
            )
            if account_error:
                return {"success": False, "message": account_error, "requires_account_selection": True}

            platform_active = self._reject_if_platform_active(db, missing)
            if platform_active:
                return platform_active

            prompt_ids = self._active_prompt_ids(db, prompt_set.id)
            rounds = 1

            session_check = {"message_suffix": ""}
            risk_ack_block = _reject_platforms_requiring_risk_ack(
                user_id or created_by,
                missing,
                risk_acknowledged=risk_acknowledged,
            )
            if risk_ack_block:
                return risk_ack_block

            total_planned = len(missing) * len(prompt_ids) * rounds

            beijing_now = _beijing_now()

            run = GeoEvaluationRun(
                client_id=client_id,
                project_id=project_id,
                prompt_set_id=prompt_set.id,
                account_id=account.id,
                phase="baseline",
                platforms=missing,
                prompt_ids=prompt_ids,
                rounds=rounds,
                status="pending",
                total_planned=total_planned,
                total_completed=0,
                total_failed=0,
                current_progress=0,
                created_by=created_by,
                evaluation_schema_version="1.0.0",
                created_at=beijing_now,
            )
            _queue_client_evaluation_run(run)
            db.add(run)
            db.commit()
            run_id = run.id

            company_name = client.company_name or client.name
            official_domains = _get_client_domains(db, client_id)

            _start_background_run(
                run_id=run_id,
                client_id=client_id,
                project_id=project_id,
                company_name=company_name,
                official_domains=official_domains,
                prompt_set_id=prompt_set.id,
                platforms=missing,
                rounds=rounds,
                user_id=user_id or created_by,
                prompt_ids=prompt_ids,
            )

            return {
                "success": True,
                "run_id": run_id,
                "total_planned": total_planned,
                "message": f"已为 {', '.join(missing)} 创建补齐基线任务，等待本地客户端执行{session_check.get('message_suffix', '')}",
            }
        except Exception as e:
            db.rollback()
            logger.error(f"创建 complete_baseline 失败: {e}")
            return {"success": False, "message": f"补齐基线失败: {str(e)}"}
        finally:
            db.close()

    def get_run_status(self, run_id: int) -> Dict[str, Any]:
        """获取任务执行状态"""
        db = self.db_factory()
        try:
            run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
            if not run:
                return {"error": "任务不存在"}

            platform_names = {"doubao": "豆包", "qianwen": "通义千问", "deepseek": "DeepSeek"}
            return {
                "id": run.id,
                "client_id": run.client_id,
                "project_id": run.project_id,
                "phase": run.phase,
                "status": run.status,
                "platforms": run.platforms,
                "rounds": run.rounds,
                "total_planned": run.total_planned,
                "total_completed": run.total_completed,
                "total_failed": run.total_failed,
                "current_platform": run.current_platform,
                "current_platform_name": platform_names.get(run.current_platform or "", ""),
                "current_round": run.current_round,
                "current_progress": run.current_progress,
                "claimed_device_id": run.claimed_device_id,
                "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
                "interruption_reason": run.interruption_reason,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "error_message": None if run.error_message == CLIENT_EVALUATION_PENDING_MARKER else run.error_message,
            }
        finally:
            db.close()


# ── 后台执行 ──

    def get_latest_run_status(
        self,
        *,
        client_id: Optional[int] = None,
        project_id: Optional[int] = None,
        platform: Optional[str] = None,
        prompt_set_id: Optional[int] = None,
        phase: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get the latest run for the current scope/platform without crossing platform views."""
        db = self.db_factory()
        try:
            query = db.query(GeoEvaluationRun)
            if client_id:
                query = query.filter(GeoEvaluationRun.client_id == client_id)
            elif project_id:
                query = query.filter(GeoEvaluationRun.project_id == project_id)
            else:
                return None

            if prompt_set_id:
                query = query.filter(GeoEvaluationRun.prompt_set_id == prompt_set_id)
            if phase:
                query = query.filter(GeoEvaluationRun.phase == phase)

            recent_runs = query.order_by(GeoEvaluationRun.created_at.desc(), GeoEvaluationRun.id.desc()).limit(50).all()
            for run in recent_runs:
                if self._run_includes_platform(run, platform):
                    return self.get_run_status(run.id)
            return None
        finally:
            db.close()

    def retry_failed_records(
        self,
        *,
        client_id: Optional[int],
        project_id: Optional[int],
        record_ids: List[int],
        created_by: Optional[int],
        user_id: Optional[int],
        risk_acknowledged: bool = False,
    ) -> Dict[str, Any]:
        db = self.db_factory()
        try:
            if not record_ids:
                return {"success": False, "message": "请选择需要重试的失败记录"}
            if not (user_id or created_by):
                return {"success": False, "message": "真实检测需要当前用户ID"}

            query = db.query(GeoEvaluationRecord).filter(
                GeoEvaluationRecord.id.in_(record_ids),
                GeoEvaluationRecord.success == False,
            )
            if client_id:
                query = query.filter(GeoEvaluationRecord.client_id == client_id)
            if project_id:
                query = query.filter(GeoEvaluationRecord.project_id == project_id)
            if not client_id and not project_id:
                return {"success": False, "message": "缺少公司或项目范围"}

            records = query.all()
            if not records:
                return {"success": False, "message": "没有找到可重试的失败记录"}

            prompt_set_id = records[0].prompt_set_id
            phase = records[0].phase
            rounds = max(record.round_no or 1 for record in records)
            platforms = sorted({record.platform for record in records if record.platform in AI_EVALUATION_PLATFORMS})
            if not prompt_set_id or not platforms:
                return {"success": False, "message": "失败记录缺少问题集或平台信息，无法重试"}
            if len(platforms) != 1:
                return {"success": False, "message": "每次只能重试一个测评平台，请按平台分别选择失败记录"}

            platform_active = self._reject_if_platform_active(db, platforms)
            if platform_active:
                return platform_active

            session_check = _resolve_platforms_with_sessions(
                user_id=user_id or created_by,
                platforms=platforms,
                explicit=True,
            )
            if not session_check["success"]:
                return session_check
            platforms = session_check["platforms"]
            risk_ack_block = _reject_platforms_requiring_risk_ack(
                user_id or created_by,
                platforms,
                risk_acknowledged=risk_acknowledged,
            )
            if risk_ack_block:
                return risk_ack_block

            prompt_ids = {record.prompt_id for record in records if record.prompt_id}
            total_planned = len(platforms) * len(prompt_ids) * rounds
            if total_planned <= 0:
                return {"success": False, "message": "没有可重试的问题"}

            client = db.query(Client).filter(Client.id == client_id).first() if client_id else None
            project = db.query(Project).filter(Project.id == project_id).first() if project_id else None
            if client_id and not client:
                return {"success": False, "message": "公司不存在"}
            if project_id and not project:
                return {"success": False, "message": "项目不存在"}

            run = GeoEvaluationRun(
                client_id=client_id,
                project_id=project_id,
                prompt_set_id=prompt_set_id,
                phase=phase,
                platforms=platforms,
                prompt_ids=sorted(prompt_ids),
                rounds=rounds,
                status="pending",
                total_planned=total_planned,
                total_completed=0,
                total_failed=0,
                current_progress=0,
                created_by=created_by,
                evaluation_schema_version="1.0.0",
                created_at=_beijing_now(),
            )
            _queue_client_evaluation_run(run)
            db.add(run)
            db.commit()
            run_id = run.id

            company_name = ""
            if client:
                company_name = client.company_name or client.name
            elif project:
                company_name = project.company_name or project.name
            official_domains = _get_client_domains(db, client_id) if client_id else _get_project_domains(project)

            _start_background_run(
                run_id=run_id,
                client_id=client_id,
                project_id=project_id,
                company_name=company_name,
                official_domains=official_domains,
                prompt_set_id=prompt_set_id,
                platforms=platforms,
                rounds=rounds,
                user_id=user_id or created_by,
                prompt_ids=sorted(prompt_ids),
            )

            return {
                "success": True,
                "run_id": run_id,
                "total_planned": total_planned,
                "message": f"已创建失败记录重试任务（{total_planned} 条待执行），等待本地客户端执行",
            }
        except Exception as exc:
            db.rollback()
            logger.error(f"Retry failed GEO records failed: {exc}")
            return {"success": False, "message": f"重试失败记录失败: {exc}"}
        finally:
            db.close()


def _start_background_run(
    run_id: int,
    client_id: Optional[int],
    project_id: Optional[int],
    company_name: str,
    official_domains: List[str],
    prompt_set_id: int,
    platforms: List[str],
    rounds: int,
    user_id: Optional[int],
    prompt_ids: Optional[List[int]] = None,
):
    """在独立线程中执行测评任务，避免阻塞 FastAPI 响应"""
    db = _get_db_session()
    try:
        run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
        if run and run.status == "pending" and run.error_message == CLIENT_EVALUATION_PENDING_MARKER:
            logger.info(f"[RunService] GEO run queued for local client execution: run={run_id}")
            return
    finally:
        db.close()

    _register_active_run(run_id)
    thread = threading.Thread(
        target=_execute_run_in_thread,
        args=(run_id, client_id, project_id, company_name, official_domains,
              prompt_set_id, platforms, rounds, user_id, prompt_ids),
        daemon=True,
    )
    thread.start()


def _execute_run_in_thread(
    run_id: int,
    client_id: Optional[int],
    project_id: Optional[int],
    company_name: str,
    official_domains: List[str],
    prompt_set_id: int,
    platforms: List[str],
    rounds: int,
    user_id: Optional[int],
    prompt_ids: Optional[List[int]] = None,
):
    """在线程中运行 async 事件循环"""
    acquired_locks = _try_acquire_platform_run_locks(platforms)
    if not acquired_locks:
        logger.warning(f"[RunService] Platform evaluation worker is busy; run={run_id} platforms={platforms}")
        db = _get_db_session()
        try:
            run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.finished_at = _beijing_now()
                run.error_message = f"{', '.join(platforms)} 平台已有 GEO 测评任务正在执行，本任务已停止以避免同平台并发风控"
                db.commit()
        finally:
            db.close()
        _unregister_active_run(run_id)
        return

    loop = asyncio.new_event_loop()
    install_asyncio_exception_filter(loop)
    try:
        loop.run_until_complete(_execute_run_async(
            run_id, client_id, project_id, company_name, official_domains,
            prompt_set_id, platforms, rounds, user_id, prompt_ids,
        ))
    except Exception as e:
        logger.error(f"[RunService] 后台任务 run={run_id} 异常: {e}")
    finally:
        _unregister_active_run(run_id)
        for lock in reversed(acquired_locks):
            lock.release()
        loop.close()


def _get_db_session():
    from backend.database import SessionLocal
    return SessionLocal()


def _get_client_domains(db: Session, client_id: int) -> List[str]:
    """获取公司关联的官网域名"""
    domains = []
    # 从项目获取域名
    projects = db.query(Project).filter(
        Project.client_id == client_id,
        Project.status == 1,
    ).all()
    for p in projects:
        if p.domain_keyword:
            domains.append(p.domain_keyword)
    # 默认域名
    if not domains:
        domains = ["example.com"]
    return domains


def _get_project_domains(project: Optional[Project]) -> List[str]:
    if project and project.domain_keyword:
        return [project.domain_keyword]
    return ["example.com"]


def _scope_records_query(db: Session, *, client_id: Optional[int], project_id: Optional[int]):
    query = db.query(GeoEvaluationRecord)
    if client_id:
        return query.filter(GeoEvaluationRecord.client_id == client_id)
    return query.filter(GeoEvaluationRecord.project_id == project_id)


def _find_existing_success_record(
    db: Session,
    *,
    client_id: Optional[int],
    project_id: Optional[int],
    prompt_set_id: int,
    prompt_id: int,
    platform: str,
    phase: str,
    round_no: int,
) -> Optional[GeoEvaluationRecord]:
    query = _scope_records_query(db, client_id=client_id, project_id=project_id).filter(
        GeoEvaluationRecord.prompt_set_id == prompt_set_id,
        GeoEvaluationRecord.prompt_id == prompt_id,
        GeoEvaluationRecord.platform == platform,
        GeoEvaluationRecord.phase == phase,
        GeoEvaluationRecord.round_no == round_no,
        GeoEvaluationRecord.schema_version == "1.0.0",
        GeoEvaluationRecord.success == True,
    )
    return query.order_by(GeoEvaluationRecord.created_at.desc(), GeoEvaluationRecord.id.desc()).first()


def _count_existing_attempts(
    db: Session,
    *,
    run_id: int,
    prompt_id: int,
    platform: str,
    phase: str,
    round_no: int,
) -> int:
    return (
        db.query(GeoEvaluationRecord)
        .filter(
            GeoEvaluationRecord.run_id == run_id,
            GeoEvaluationRecord.prompt_id == prompt_id,
            GeoEvaluationRecord.platform == platform,
            GeoEvaluationRecord.phase == phase,
            GeoEvaluationRecord.round_no == round_no,
        )
        .count()
    )


def _is_retryable_failure_category(category: str) -> bool:
    return category in {"empty", "unknown"}


def _run_async_blocking(coro):
    """Run a short async helper from a sync service method."""
    result: Dict[str, Any] = {}

    def runner():
        loop = asyncio.new_event_loop()
        install_asyncio_exception_filter(loop)
        try:
            result["value"] = loop.run_until_complete(coro)
        except Exception as exc:
            result["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _resolve_platforms_with_sessions(
    *,
    user_id: Optional[int],
    platforms: List[str],
    explicit: bool,
) -> Dict[str, Any]:
    """Resolve selected AI platforms to the subset that has usable saved login sessions."""
    if not user_id:
        return {"success": False, "message": "真实检测需要当前用户ID"}
    if not platforms:
        return {"success": False, "message": "请选择要检测的 AI 平台"}

    return _run_async_blocking(
        _resolve_platforms_with_sessions_async(
            user_id=user_id,
            platforms=platforms,
            explicit=explicit,
        )
    )


async def _resolve_platforms_with_sessions_async(
    *,
    user_id: int,
    platforms: List[str],
    explicit: bool,
) -> Dict[str, Any]:
    from backend.services.cookie_validator import cookie_validator
    from backend.services.session_manager import secure_session_manager

    available = []
    missing = []
    invalid = []
    for platform in platforms:
        storage_state = await secure_session_manager.load_session(
            user_id=user_id,
            platform=platform,
            validate=False,
        )
        platform_name = AI_PLATFORM_NAMES.get(platform, platform)
        if not storage_state:
            missing.append(platform_name)
            continue

        is_valid, reason = await cookie_validator.validate_fast(platform=platform, storage_state=storage_state)
        if not is_valid:
            invalid.append(f"{platform_name}({reason})")
            continue

        available.append(platform)

    if explicit and (missing or invalid):
        parts = []
        if missing:
            parts.append(f"未授权或未登录：{', '.join(missing)}")
        if invalid:
            parts.append(f"登录态失效：{', '.join(invalid)}")
        return {
            "success": False,
            "message": "请先完成 AI 平台授权登录后再启动测评；" + "；".join(parts),
            "missing_platforms": missing,
            "invalid_platforms": invalid,
        }

    if not available:
        return {
            "success": False,
            "message": "当前没有可测评的 AI 平台。请先登录至少一个平台；未登录的平台需登录后再测评。",
            "missing_platforms": missing,
            "invalid_platforms": invalid,
            "platforms": [],
        }

    skipped = []
    if missing:
        skipped.append(f"未登录：{', '.join(missing)}")
    if invalid:
        skipped.append(f"登录态失效：{', '.join(invalid)}")
    return {
        "success": True,
        "platforms": available,
        "skipped_platforms": missing + invalid,
        "message_suffix": f"；已跳过 {'；'.join(skipped)}" if skipped else "",
    }


async def _execute_run_async(
    run_id: int,
    client_id: int,
    project_id: Optional[int],
    company_name: str,
    official_domains: List[str],
    prompt_set_id: int,
    platforms: List[str],
    rounds: int,
    user_id: Optional[int],
    prompt_ids: Optional[List[int]] = None,
):
    """异步执行检测任务（公司级别）

    按平台串行、每轮完整遍历问题，轮次之间保持会话隔离。
    通过已登录的 AI 平台网页提问获取回答，再交给现有 LLM judge 计算五指标。
    """
    return await _execute_run_async_parallel(
        run_id=run_id,
        client_id=client_id,
        project_id=project_id,
        company_name=company_name,
        official_domains=official_domains,
        prompt_set_id=prompt_set_id,
        platforms=platforms,
        rounds=rounds,
        user_id=user_id,
        prompt_ids=prompt_ids,
    )


async def _execute_run_async_parallel(
    run_id: int,
    client_id: int,
    project_id: Optional[int],
    company_name: str,
    official_domains: List[str],
    prompt_set_id: int,
    platforms: List[str],
    rounds: int,
    user_id: Optional[int],
    prompt_ids: Optional[List[int]] = None,
):
    """Run one worker per AI platform; each worker keeps platform-local pacing."""
    return await _execute_run_async_parallel_v2(
        run_id=run_id,
        client_id=client_id,
        project_id=project_id,
        company_name=company_name,
        official_domains=official_domains,
        prompt_set_id=prompt_set_id,
        platforms=platforms,
        rounds=rounds,
        user_id=user_id,
        prompt_ids=prompt_ids,
    )

    db = _get_db_session()
    try:
        run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
        if not run:
            logger.error(f"[RunService] run {run_id} 不存在")
            return

        # 获取问题
        prompt_query = db.query(GeoPrompt).filter(
            GeoPrompt.prompt_set_id == prompt_set_id,
            GeoPrompt.status == "active",
        )
        if prompt_ids:
            prompt_query = prompt_query.filter(GeoPrompt.id.in_(prompt_ids))
        prompt_query = prompt_query.order_by(GeoPrompt.question_type, GeoPrompt.sort_order)
        if not prompt_ids:
            prompt_query = prompt_query.limit(EVALUATION_QUESTION_LIMIT)
        prompts = prompt_query.all()
        if not prompts:
            run.status = "failed"
            run.error_message = "问题集为空"
            db.commit()
            return

        # 初始化服务
        judge_service = GeoResponseJudgeService()
        brand_aliases = [company_name]
        competitors: List[str] = []

        beijing_now = _beijing_now()
        run.status = "running"
        run.started_at = beijing_now
        total_completed = 0
        total_failed = 0
        risk_guard = _EvaluationRiskGuard(user_id=user_id)
        stopped_platform_reasons: List[str] = []
        stop_entire_run = False
        progress_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        platform_rounds: Dict[str, int] = {platform: 0 for platform in platforms}
        platform_last_progress: Dict[str, int] = {platform: 0 for platform in platforms}
        db.commit()

        logger.info(f"[RunService] run={run_id} 公司级别，平台={platforms}")

        try:
            # 按平台串行
            for pf in platforms:
                run.current_platform = pf
                run.current_progress = total_completed
                db.commit()

                logger.info(f"[RunService] run={run_id} 检测平台 {pf} 问题数={len(prompts)} 轮次={rounds}")

                for rnd in range(1, rounds + 1):
                    run.current_round = rnd
                    db.commit()

                    for pi, prompt in enumerate(prompts):
                        existing_success = _find_existing_success_record(
                            db,
                            client_id=client_id,
                            project_id=project_id,
                            prompt_set_id=prompt_set_id,
                            prompt_id=prompt.id,
                            platform=pf,
                            phase=run.phase,
                            round_no=rnd,
                        )
                        if existing_success:
                            logger.info(
                                f"[RunService] Skip completed item: run={run_id} pf={pf} "
                                f"rnd={rnd} prompt={prompt.id}"
                            )
                            total_completed += 1
                            run.total_completed = total_completed
                            run.current_progress = total_completed + total_failed
                            db.commit()
                            continue

                        existing_attempts = _count_existing_attempts(
                            db,
                            run_id=run_id,
                            prompt_id=prompt.id,
                            platform=pf,
                            phase=run.phase,
                            round_no=rnd,
                        )
                        if existing_attempts >= max(1, EVALUATION_MAX_ATTEMPTS):
                            logger.info(
                                f"[RunService] Skip exhausted item: run={run_id} pf={pf} "
                                f"rnd={rnd} prompt={prompt.id} attempts={existing_attempts}"
                            )
                            total_failed += 1
                            run.total_failed = total_failed
                            run.current_progress = total_completed + total_failed
                            db.commit()
                            continue

                        request_started = False
                        stop_current_platform = False
                        try:
                            answer = None
                            citations = None

                            await risk_guard.before_request(pf)
                            request_started = True

                            async def _on_ai_manual_event(event: dict):
                                current_run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
                                if not current_run:
                                    return
                                event_type = event.get("type")
                                if event_type == "manual_required":
                                    current_run.status = "manual_required"
                                    current_run.error_message = (
                                        event.get("message")
                                        or event.get("matched_text")
                                        or "AI平台要求人工验证，请在浏览器中完成操作"
                                    )
                                elif event_type == "manual_resolved":
                                    current_run.status = "running"
                                    current_run.error_message = None
                                elif event_type == "manual_timeout":
                                    current_run.status = "running"
                                    current_run.error_message = "AI平台人工验证等待超时，当前问题将记录为失败，可稍后重试"
                                db.commit()

                            # ── 网页登录态提问，拿回 AI 原始回答 ──
                            check_result = await _ask_ai_platform_via_browser(
                                user_id=user_id,
                                question=prompt.question,
                                keyword=company_name,
                                company=company_name,
                                platform=pf,
                                manual_event_callback=_on_ai_manual_event,
                            )

                            if check_result.get("success"):
                                answer = check_result.get("answer", "")
                            else:
                                answer = check_result.get("answer") or ""
                                if check_result.get("manual_timeout") or check_result.get("manual_required"):
                                    raise RuntimeError(
                                        f"[manual_timeout] {check_result.get('error_msg') or 'AI平台人工验证等待超时'}"
                                    )
                                raise RuntimeError(
                                    f"网页提问失败: {check_result.get('error_msg') or '未知错误'}"
                                )

                            # 提取引用来源
                            if check_result.get("citations"):
                                citations = check_result["citations"]

                            if not answer:
                                raise RuntimeError("平台未返回 AI 回答")

                            eval_result = await judge_service.evaluate(
                                company_name=company_name,
                                brand_aliases=brand_aliases,
                                official_domains=official_domains,
                                competitors=competitors,
                                question=prompt.question,
                                question_type=prompt.question_type,
                                answer=answer,
                                citations=citations,
                            )

                            record_time = _beijing_now()
                            risk_guard.note_success(pf)

                            # 写记录（公司级别）
                            record = GeoEvaluationRecord(
                                run_id=run_id,
                                client_id=client_id,
                                project_id=project_id,
                                prompt_set_id=prompt_set_id,
                                prompt_id=prompt.id,
                                related_project_name=prompt.related_project_name,
                                platform=pf,
                                phase=run.phase,
                                round_no=rnd,
                                question=prompt.question,
                                answer=answer,
                                raw_citations=citations,
                                context_cleaned=True,
                                success=bool(answer),
                                brand_mentioned=eval_result["brand_mentioned"],
                                matched_names=eval_result["matched_names"],
                                is_recommended=eval_result["is_recommended"],
                                recommendation_rank=eval_result["recommendation_rank"],
                                ranking_score=eval_result["ranking_score"],
                                citation_supported=eval_result["citation_supported"],
                                own_source_cited=eval_result["own_source_cited"],
                                cited_urls=eval_result["cited_urls"],
                                cited_domains=eval_result["cited_domains"],
                                sentiment=eval_result["sentiment"],
                                sentiment_score=eval_result["sentiment_score"],
                                visibility_score=eval_result["visibility_score"],
                                evidence=eval_result["evidence"],
                                judge_model=_judge_model_label(),
                                judge_raw_output=eval_result,
                                schema_version="1.0.0",
                                asked_at=record_time,
                                evaluated_at=record_time,
                                created_at=record_time,
                            )
                            db.add(record)
                            total_completed += 1

                        except Exception as e:
                            logger.error(
                                f"[RunService] 提问失败: run={run_id} pf={pf} rnd={rnd} "
                                f"q={prompt.id} err={e}"
                            )
                            total_failed += 1
                            record_time = _beijing_now()
                            # 判断失败类型
                            error_str = str(e)[:500]
                            data_quality = "invalid"
                            if "回答质量校验失败" in error_str:
                                data_quality = "suspicious_content"
                            elif "未返回" in error_str or "空回答" in error_str:
                                data_quality = "empty"
                            failure_info = risk_guard.note_failure(pf, error_str)
                            failure_category = failure_info["category"]
                            if failure_category != "unknown":
                                data_quality = failure_category
                            error_str = f"[{data_quality}] {error_str}"[:500]
                            stop_current_platform = bool(failure_info["stop_platform"])
                            if stop_current_platform:
                                stopped_platform_reasons.append(failure_info["reason"])
                                logger.warning(
                                    f"[RunService] 风控保护暂停平台: run={run_id} pf={pf} "
                                    f"category={data_quality} failures={failure_info['consecutive_failures']}"
                                )

                            record = GeoEvaluationRecord(
                                run_id=run_id,
                                client_id=client_id,
                                project_id=project_id,
                                prompt_set_id=prompt_set_id,
                                prompt_id=prompt.id,
                                related_project_name=prompt.related_project_name,
                                platform=pf,
                                phase=run.phase,
                                round_no=rnd,
                                question=prompt.question,
                                answer=answer if "answer" in locals() else None,
                                raw_citations=citations if "citations" in locals() else None,
                                context_cleaned=True,
                                success=False,
                                error_message=error_str,
                                asked_at=record_time,
                                created_at=record_time,
                            )
                            db.add(record)

                        # Commit each answer immediately so the evidence table can show it while the run continues.
                        run.total_completed = total_completed
                        run.total_failed = total_failed
                        run.current_progress = total_completed + total_failed
                        db.commit()
                        if request_started:
                            await risk_guard.after_request(pf)
                        if stop_current_platform:
                            break

                    # 每轮结束提交
                    run.total_completed = total_completed
                    run.total_failed = total_failed
                    run.current_progress = total_completed + total_failed
                    if stop_current_platform:
                        run.error_message = "; ".join(stopped_platform_reasons[-3:])
                    db.commit()
                    if stop_current_platform:
                        logger.info(f"[RunService] run={run_id} pf={pf} round={rnd}/{rounds} stopped by risk guard")
                        break
                    logger.info(f"[RunService] run={run_id} pf={pf} round={rnd}/{rounds} 完成")

        finally:
            pass

        # 全部完成
        beijing_now = _beijing_now()
        run.status = "failed" if total_completed == 0 and total_failed > 0 else "completed"
        run.finished_at = beijing_now
        run.total_completed = total_completed
        run.total_failed = total_failed
        run.current_progress = total_completed + total_failed
        if stopped_platform_reasons:
            run.error_message = "; ".join(stopped_platform_reasons[-3:])
        if run.status == "failed":
            run.error_message = run.error_message or "所有平台网页提问或 LLM 评估均失败，请检查平台授权登录态和 LLM 评估配置"
        db.commit()

        logger.info(
            f"[RunService] run={run_id} 完成: "
            f"client_id={client_id} platforms={platforms} rounds={rounds} "
            f"ok={total_completed} failed={total_failed}"
        )
    except Exception as e:
        logger.error(f"[RunService] 后台执行 run={run_id} 失败: {e}")
        try:
            run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _execute_run_async_parallel_v2(
    run_id: int,
    client_id: int,
    project_id: Optional[int],
    company_name: str,
    official_domains: List[str],
    prompt_set_id: int,
    platforms: List[str],
    rounds: int,
    user_id: Optional[int],
    prompt_ids: Optional[List[int]] = None,
):
    """Run selected AI platforms concurrently, with independent pacing per platform."""
    db = _get_db_session()
    try:
        run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
        if not run:
            logger.error(f"[RunService] run {run_id} not found")
            return

        prompt_query = db.query(GeoPrompt).filter(
            GeoPrompt.prompt_set_id == prompt_set_id,
            GeoPrompt.status == "active",
        )
        if prompt_ids:
            prompt_query = prompt_query.filter(GeoPrompt.id.in_(prompt_ids))
        prompt_query = prompt_query.order_by(GeoPrompt.question_type, GeoPrompt.sort_order)
        if not prompt_ids:
            prompt_query = prompt_query.limit(EVALUATION_QUESTION_LIMIT)
        prompts = prompt_query.all()
        if not prompts:
            run.status = "failed"
            run.error_message = "问题集为空"
            db.commit()
            return
        prompt_items = [
            SimpleNamespace(
                id=prompt.id,
                question=prompt.question,
                question_type=prompt.question_type,
                related_project_name=prompt.related_project_name,
            )
            for prompt in prompts
        ]

        phase = run.phase
        brand_aliases = [company_name]
        competitors: List[str] = []
        total_completed = 0
        total_failed = 0
        stopped_platform_reasons: List[str] = []
        stop_entire_run = False
        progress_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        platform_rounds: Dict[str, int] = {platform: 0 for platform in platforms}
        platform_last_progress: Dict[str, int] = {platform: 0 for platform in platforms}

        run.status = "running"
        run.started_at = _beijing_now()
        run.total_completed = 0
        run.total_failed = 0
        run.current_progress = 0
        db.commit()

        logger.info(
            f"[RunService] run={run_id} parallel evaluation started: "
                f"platforms={platforms} prompts={len(prompt_items)} rounds={rounds}"
        )

        async def _commit_progress(
            *,
            current_platform: Optional[str] = None,
            current_round: Optional[int] = None,
            error_message: Optional[str] = None,
        ) -> None:
            current_run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
            if not current_run:
                return
            current_run.total_completed = total_completed
            current_run.total_failed = total_failed
            current_run.current_progress = total_completed + total_failed
            if current_platform is not None:
                current_run.current_platform = current_platform
            elif platform_last_progress:
                current_run.current_platform = max(platform_last_progress, key=platform_last_progress.get)
            if current_round is not None:
                current_run.current_round = current_round
            elif platform_rounds:
                current_run.current_round = max(platform_rounds.values())
            if error_message is not None:
                current_run.error_message = error_message
            db.commit()

        async def _on_ai_manual_event(event: Dict[str, Any], platform: str, round_no: int) -> None:
            async with progress_lock:
                current_run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
                if not current_run:
                    return
                event_type = event.get("type")
                current_run.current_platform = platform
                current_run.current_round = round_no
                if event_type == "manual_required":
                    current_run.status = "manual_required"
                    current_run.error_message = (
                        event.get("message")
                        or event.get("matched_text")
                        or "AI平台要求人工验证，请在浏览器中完成操作"
                    )
                elif event_type == "manual_resolved":
                    current_run.status = "running"
                    current_run.error_message = None
                elif event_type == "manual_timeout":
                    current_run.status = "running"
                    current_run.error_message = "AI平台人工验证等待超时，当前问题将记录为失败，可稍后重试"
                db.commit()

        async def _process_platform(platform: str) -> None:
            nonlocal total_completed, total_failed, stop_entire_run

            risk_guard = _EvaluationRiskGuard(user_id=user_id)
            judge_service = GeoResponseJudgeService()
            logger.info(
                f"[RunService] run={run_id} platform worker started: "
                f"platform={platform} prompts={len(prompt_items)} rounds={rounds}"
            )

            for round_no in range(1, rounds + 1):
                if stop_event.is_set():
                    break

                platform_rounds[platform] = round_no
                async with progress_lock:
                    await _commit_progress(current_platform=platform, current_round=round_no)

                stop_current_platform = False
                for prompt in prompt_items:
                    if stop_event.is_set():
                        break

                    answer = None
                    citations = None
                    request_started = False
                    skip_item = False

                    async with progress_lock:
                        existing_success = _find_existing_success_record(
                            db,
                            client_id=client_id,
                            project_id=project_id,
                            prompt_set_id=prompt_set_id,
                            prompt_id=prompt.id,
                            platform=platform,
                            phase=phase,
                            round_no=round_no,
                        )
                        if existing_success:
                            logger.info(
                                f"[RunService] skip completed item: run={run_id} platform={platform} "
                                f"round={round_no} prompt={prompt.id}"
                            )
                            total_completed += 1
                            platform_last_progress[platform] = total_completed + total_failed
                            await _commit_progress(current_platform=platform, current_round=round_no)
                            skip_item = True

                        if not skip_item:
                            existing_attempts = _count_existing_attempts(
                                db,
                                run_id=run_id,
                                prompt_id=prompt.id,
                                platform=platform,
                                phase=phase,
                                round_no=round_no,
                            )
                            if existing_attempts >= max(1, EVALUATION_MAX_ATTEMPTS):
                                logger.info(
                                    f"[RunService] skip exhausted item: run={run_id} platform={platform} "
                                    f"round={round_no} prompt={prompt.id} attempts={existing_attempts}"
                                )
                                total_failed += 1
                                platform_last_progress[platform] = total_completed + total_failed
                                await _commit_progress(current_platform=platform, current_round=round_no)
                                skip_item = True

                    if skip_item:
                        continue

                    try:
                        await risk_guard.before_request(platform)
                        request_started = True

                        async def _manual_callback(event: Dict[str, Any]):
                            await _on_ai_manual_event(event, platform, round_no)

                        check_result = await _ask_ai_platform_via_browser(
                            user_id=user_id,
                            question=prompt.question,
                            keyword=company_name,
                            company=company_name,
                            platform=platform,
                            manual_event_callback=_manual_callback,
                        )

                        if check_result.get("success"):
                            answer = check_result.get("answer", "")
                        else:
                            answer = check_result.get("answer") or ""
                            if check_result.get("manual_timeout") or check_result.get("manual_required"):
                                raise RuntimeError(
                                    f"[manual_timeout] {check_result.get('error_msg') or 'AI平台人工验证等待超时'}"
                                )
                            raise RuntimeError(
                                f"网页提问失败: {check_result.get('error_msg') or '未知错误'}"
                            )

                        if check_result.get("citations"):
                            citations = check_result["citations"]

                        if not answer:
                            raise RuntimeError("平台未返回 AI 回答")

                        eval_result = await judge_service.evaluate(
                            company_name=company_name,
                            brand_aliases=brand_aliases,
                            official_domains=official_domains,
                            competitors=competitors,
                            question=prompt.question,
                            question_type=prompt.question_type,
                            answer=answer,
                            citations=citations,
                        )

                        record_time = _beijing_now()
                        risk_guard.note_success(platform)

                        async with progress_lock:
                            record = GeoEvaluationRecord(
                                run_id=run_id,
                                client_id=client_id,
                                project_id=project_id,
                                prompt_set_id=prompt_set_id,
                                prompt_id=prompt.id,
                                related_project_name=prompt.related_project_name,
                                platform=platform,
                                phase=phase,
                                round_no=round_no,
                                question=prompt.question,
                                answer=answer,
                                raw_citations=citations,
                                context_cleaned=True,
                                success=bool(answer),
                                brand_mentioned=eval_result["brand_mentioned"],
                                matched_names=eval_result["matched_names"],
                                is_recommended=eval_result["is_recommended"],
                                recommendation_rank=eval_result["recommendation_rank"],
                                ranking_score=eval_result["ranking_score"],
                                citation_supported=eval_result["citation_supported"],
                                own_source_cited=eval_result["own_source_cited"],
                                cited_urls=eval_result["cited_urls"],
                                cited_domains=eval_result["cited_domains"],
                                sentiment=eval_result["sentiment"],
                                sentiment_score=eval_result["sentiment_score"],
                                visibility_score=eval_result["visibility_score"],
                                evidence=eval_result["evidence"],
                                judge_model=_judge_model_label(),
                                judge_raw_output=eval_result,
                                schema_version="1.0.0",
                                asked_at=record_time,
                                evaluated_at=record_time,
                                created_at=record_time,
                            )
                            db.add(record)
                            total_completed += 1
                            platform_last_progress[platform] = total_completed + total_failed
                            await _commit_progress(current_platform=platform, current_round=round_no)

                    except Exception as exc:
                        logger.error(
                            f"[RunService] platform ask failed: run={run_id} platform={platform} "
                            f"round={round_no} prompt={prompt.id} err={exc}"
                        )
                        record_time = _beijing_now()
                        error_str = str(exc)[:500]
                        data_quality = "invalid"
                        if "回答质量校验失败" in error_str:
                            data_quality = "suspicious_content"
                        elif "未返回" in error_str or "空回答" in error_str:
                            data_quality = "empty"

                        failure_info = risk_guard.note_failure(platform, error_str)
                        failure_category = failure_info["category"]
                        if failure_category != "unknown":
                            data_quality = failure_category
                        error_str = f"[{data_quality}] {error_str}"[:500]
                        stop_current_platform = bool(failure_info["stop_platform"])
                        if stop_current_platform:
                            stopped_platform_reasons.append(failure_info["reason"])
                            logger.warning(
                                f"[RunService] stop platform by risk guard: run={run_id} platform={platform} "
                                f"category={data_quality} failures={failure_info['consecutive_failures']}"
                            )

                        async with progress_lock:
                            record = GeoEvaluationRecord(
                                run_id=run_id,
                                client_id=client_id,
                                project_id=project_id,
                                prompt_set_id=prompt_set_id,
                                prompt_id=prompt.id,
                                related_project_name=prompt.related_project_name,
                                platform=platform,
                                phase=phase,
                                round_no=round_no,
                                question=prompt.question,
                                answer=answer,
                                raw_citations=citations,
                                context_cleaned=True,
                                success=False,
                                error_message=error_str,
                                asked_at=record_time,
                                created_at=record_time,
                            )
                            db.add(record)
                            total_failed += 1
                            platform_last_progress[platform] = total_completed + total_failed
                            await _commit_progress(
                                current_platform=platform,
                                current_round=round_no,
                                error_message=(
                                    "; ".join(stopped_platform_reasons[-3:])
                                    if stop_current_platform
                                    else None
                                ),
                            )

                    finally:
                        if request_started:
                            await risk_guard.after_request(platform)

                    if stop_current_platform:
                        break

                if stop_current_platform:
                    logger.info(f"[RunService] run={run_id} platform={platform} round={round_no}/{rounds} stopped")
                    break
                logger.info(f"[RunService] run={run_id} platform={platform} round={round_no}/{rounds} completed")

            logger.info(f"[RunService] run={run_id} platform worker finished: platform={platform}")

        await asyncio.gather(*[_process_platform(platform) for platform in platforms])

        async with progress_lock:
            run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
            if run:
                run.status = "failed" if total_completed == 0 and total_failed > 0 else "completed"
                run.finished_at = _beijing_now()
                run.total_completed = total_completed
                run.total_failed = total_failed
                run.current_progress = total_completed + total_failed
                if stopped_platform_reasons:
                    run.error_message = "; ".join(stopped_platform_reasons[-3:])
                if run.status == "failed":
                    run.error_message = (
                        run.error_message
                        or "所有平台网页提问或 LLM 评估均失败，请检查平台授权登录状态和 LLM 评估配置"
                    )
                db.commit()

        logger.info(
            f"[RunService] run={run_id} completed: "
            f"client_id={client_id} platforms={platforms} rounds={rounds} "
            f"ok={total_completed} failed={total_failed}"
        )
    except Exception as exc:
        logger.error(f"[RunService] background run={run_id} failed: {exc}")
        try:
            run = db.query(GeoEvaluationRun).filter(GeoEvaluationRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _judge_model_label() -> str:
    """返回当前使用的评估模型标识"""
    from backend.config import AUTOGEO_CONVERSATION_LLM_MODEL
    return AUTOGEO_CONVERSATION_LLM_MODEL or "deepseek-v4-flash"


async def _ask_ai_platform_via_browser(
    *,
    user_id: Optional[int],
    question: str,
    keyword: str,
    company: str,
    platform: str,
    manual_event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Use the saved logged-in browser session to ask one AI platform and return its answer."""
    max_attempts = max(1, EVALUATION_MAX_ATTEMPTS)
    last_result: Dict[str, Any] = {"success": False, "answer": None, "error_msg": "not started"}
    for attempt_no in range(1, max_attempts + 1):
        result = await _ask_ai_platform_via_browser_once(
            user_id=user_id,
            question=question,
            keyword=keyword,
            company=company,
            platform=platform,
            manual_event_callback=manual_event_callback,
        )
        if result.get("success"):
            result["attempt_no"] = attempt_no
            return result
        last_result = result
        if result.get("manual_timeout") or result.get("manual_required"):
            break
        category = _classify_platform_failure(result.get("error_msg") or "")
        if category in {"risk_control", "rate_limited", "auth", "suspicious_content"}:
            break
        if attempt_no < max_attempts:
            delay_settings = _platform_delay_settings(platform)
            retry_min_delay = min(delay_settings["retry_min_delay"], delay_settings["retry_max_delay"])
            retry_max_delay = max(delay_settings["retry_min_delay"], delay_settings["retry_max_delay"])
            delay = random.uniform(max(0.0, retry_min_delay), retry_max_delay)
            logger.info(
                f"[RunService] Retry platform ask: platform={platform} attempt={attempt_no + 1}/{max_attempts} "
                f"delay={delay:.1f}s category={category}"
            )
            await asyncio.sleep(delay)
    last_result["attempt_no"] = max_attempts
    return last_result


async def _ask_ai_platform_via_browser_once(
    *,
    user_id: Optional[int],
    question: str,
    keyword: str,
    company: str,
    platform: str,
    manual_event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Ask one AI platform once using the saved logged-in browser session."""
    if not user_id:
        return {"success": False, "answer": None, "error_msg": "缺少用户ID，无法加载平台授权会话"}

    from playwright.async_api import async_playwright

    from backend.config import AI_PLATFORMS, DEFAULT_USER_AGENT
    from backend.services.cookie_validator import cookie_validator
    from backend.services.playwright.manual_guard import ensure_no_manual_challenge, manual_timeout_result
    from backend.services.playwright.ai_platforms import DoubaoChecker, QianwenChecker, DeepSeekChecker
    from backend.services.session_manager import secure_session_manager

    checker_map = {
        "doubao": DoubaoChecker,
        "qianwen": QianwenChecker,
        "deepseek": DeepSeekChecker,
    }
    checker_cls = checker_map.get(platform)
    platform_config = AI_PLATFORMS.get(platform)
    if not checker_cls or not platform_config:
        return {"success": False, "answer": None, "error_msg": f"不支持的平台: {platform}"}

    checker = checker_cls(platform, platform_config)
    storage_state = await secure_session_manager.load_session(
        user_id=user_id,
        platform=platform,
        validate=False,
    )
    if not storage_state:
        return {"success": False, "answer": None, "error_msg": f"{checker.name} 未授权或登录态不存在"}

    is_valid, reason = await cookie_validator.validate_fast(platform=platform, storage_state=storage_state)
    if not is_valid:
        if platform in {"doubao", "deepseek"} and storage_state.get("cookies"):
            logger.warning(
                f"[RunService] {checker.name} 授权预检失败但存在本机Cookie，继续进入浏览器验证: {reason}"
            )
        else:
            return {"success": False, "answer": None, "error_msg": f"{checker.name} 授权已失效: {reason}"}


    fingerprint = storage_state.get("fingerprint") if storage_state else None
    user_ua = (
        fingerprint.get("user_agent")
        if fingerprint and fingerprint.get("user_agent")
        else DEFAULT_USER_AGENT
    )
    viewport = None
    if fingerprint and fingerprint.get("viewport"):
        vp = fingerprint["viewport"]
        viewport = {"width": int(vp.get("width", 1920)), "height": int(vp.get("height", 1080))}

    async def _run_browser_attempt(*, headless: bool, wait_for_manual: bool) -> Dict[str, Any]:
        browser = await _launch_browser_real(p, headless=headless)
        context = None
        try:
            context_kwargs = {"storage_state": storage_state, "user_agent": user_ua}
            if viewport:
                context_kwargs["viewport"] = viewport
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            manual_resolution = await ensure_no_manual_challenge(
                page,
                platform=platform,
                stage="ai_open",
                wait_for_resolution=wait_for_manual,
                on_event=manual_event_callback,
            )
            if manual_resolution and not manual_resolution.handled:
                result = manual_timeout_result(manual_resolution)
                return {"success": False, "answer": None, "error_msg": result["error_msg"], **result}

            result = await checker.check(
                page=page,
                question=question,
                keyword=keyword,
                company=company,
            )
            manual_resolution = await ensure_no_manual_challenge(
                page,
                platform=platform,
                stage="ai_answer",
                wait_for_resolution=wait_for_manual,
                on_event=manual_event_callback,
            )
            if manual_resolution and not manual_resolution.handled:
                timeout_result = manual_timeout_result(manual_resolution)
                return {"success": False, "answer": None, "error_msg": timeout_result["error_msg"], **timeout_result}
            if not result.get("success"):
                block_message = await _detect_platform_page_block(page, platform)
                if block_message:
                    result["success"] = False
                    result["answer"] = None
                    result["error_msg"] = block_message
                    result["failure_category"] = "risk_control"

            try:
                updated_state = await context.storage_state()
                for key in (
                    "fingerprint",
                    "created_at",
                    "browser_verified_login",
                    "source",
                    "extension_sync_at",
                ):
                    if key in storage_state and key not in updated_state:
                        updated_state[key] = storage_state[key]
                if result.get("success") and result.get("answer"):
                    updated_state["browser_verified_login"] = {
                        "platform": platform,
                        "verified_at": time.time(),
                        "source": "geo_evaluation_browser_headed" if not headless else "geo_evaluation_browser_headless",
                    }
                elif not headless:
                    updated_state["browser_verified_login"] = {
                        "platform": platform,
                        "verified_at": time.time(),
                        "source": "geo_evaluation_manual_headed",
                    }
                await secure_session_manager.save_session(
                    user_id=user_id,
                    platform=platform,
                    storage_state=updated_state,
                    project_id=None,
                )
            except Exception as save_exc:
                logger.warning(f"[RunService] 保存 {checker.name} 更新会话失败: {save_exc}")

            return result
        except Exception as exc:
            return {"success": False, "answer": None, "error_msg": str(exc)}
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            try:
                await browser.close()
            except Exception:
                pass

    async with async_playwright() as p:
        headless_result = await _run_browser_attempt(headless=True, wait_for_manual=False)
        if not headless_result.get("manual_required") and headless_result.get("failure_category") != "risk_control":
            return headless_result

        logger.warning(
            f"[RunService] {checker.name} headless detected manual challenge; "
            "restarting headed browser for user handling"
        )
        headed_result = await _run_browser_attempt(headless=False, wait_for_manual=True)
        if headed_result.get("success"):
            headed_result["manual_recovered"] = True
        return headed_result


async def _launch_browser_real(playwright_ctx, *, headless: bool = True):
    """启动 Playwright 浏览器，复用 index_check_service 的逻辑"""
    import sys
    from backend.config import BROWSER_ARGS

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    if sys.platform == "darwin":
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]

    executable_path = None
    for path in chrome_paths:
        if os.path.exists(path):
            executable_path = path
            logger.info(f"[RunService] 找到 Chrome: {path}")
            break

    launch_options = {"headless": headless, "args": BROWSER_ARGS, "timeout": 30000}
    if executable_path:
        launch_options["executable_path"] = executable_path

    try:
        browser = await playwright_ctx.chromium.launch(**launch_options)
    except Exception as e:
        logger.warning(f"[RunService] Chrome 启动失败: {e}，尝试内置浏览器")
        if executable_path:
            launch_options.pop("executable_path", None)
        browser = await playwright_ctx.chromium.launch(**launch_options)

    logger.info(f"[RunService] 浏览器已启动 headless={launch_options['headless']}")
    return browser
