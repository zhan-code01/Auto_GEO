# -*- coding: utf-8 -*-
"""
发布审批服务（Phase 1：服务器审批式发布）

设计思想：把发布流程的关键步骤（开始写入/填充正文/提交发布）当作受控操作，
        每一步客户端都必须先向服务器申请审批。服务器作为唯一决策者，
        即使客户端 exe 被泄露，发布能力仍由我们掌控。

校验链（Chain of Responsibility）：
  ① 基础校验   → 用户 Token、设备在线+归属、任务领取状态、记录有效性
  ② 配额校验   → 用户每日/每月剩余发布次数
  ③ 平台校验   → 平台白名单
  ④ 时间窗口   → 可选：是否在允许发布时间段（默认关闭）
  ⑤ IP 校验    → 可选：IP 是否可信（默认关闭，预留给高安全场景）

每个校验独立开关，便于分阶段上线/灰度。
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import (
    Account,
    AutoPublishRecord,
    AutoPublishTask,
    ClientDevice,
    GeoArticle,
    PublishApprovalLog,
    User,
    UserPublishQuota,
)


# ==================== 数据类 ====================


@dataclass
class ApprovalRequest:
    """审批请求参数"""

    user: User
    task_id: int
    record_id: int
    device_id: str
    checkpoint: str  # "before_write" | "before_fill_body" | "before_submit"
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None


@dataclass
class ApprovalResult:
    """审批结果"""

    approved: bool
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    approval_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "approval_token": self.approval_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "context": self.context,
        }


# ==================== 校验器基类 ====================


class BaseCheck:
    """校验器基类"""

    code: str = "UNKNOWN"
    description: str = "未知校验"

    def verify(self, ctx: "ApprovalContext") -> "CheckResult":
        raise NotImplementedError


@dataclass
class CheckResult:
    """单条校验结果"""

    passed: bool
    code: str = "OK"
    message: str = ""


@dataclass
class ApprovalContext:
    """审批上下文：在多个校验器之间流转"""

    request: ApprovalRequest
    db: Session
    user: User
    task: Optional[AutoPublishTask] = None
    record: Optional[AutoPublishRecord] = None
    account: Optional[Account] = None
    article: Optional[GeoArticle] = None
    device: Optional[ClientDevice] = None
    quota: Optional[UserPublishQuota] = None


# ==================== 校验器实现 ====================


class DeviceActiveCheck(BaseCheck):
    """设备在线 + 归属校验"""

    code = "DEVICE_OFFLINE"
    description = "设备离线或非本用户设备"

    def verify(self, ctx: ApprovalContext) -> CheckResult:
        from backend.api.client_device import is_device_online

        if not ctx.device:
            return CheckResult(False, self.code, "设备不存在")
        if ctx.device.user_id != ctx.user.id:
            return CheckResult(False, self.code, "设备不属于当前用户")
        if not is_device_online(ctx.device):
            return CheckResult(False, self.code, "设备离线，请先心跳上线")
        return CheckResult(True)


class TaskClaimedCheck(BaseCheck):
    """任务领取状态校验"""

    code = "TASK_NOT_CLAIMED"
    description = "任务未被本设备领取或锁已过期"

    def verify(self, ctx: ApprovalContext) -> CheckResult:
        if not ctx.task:
            return CheckResult(False, self.code, "任务不存在")
        if ctx.task.user_id != ctx.user.id:
            return CheckResult(False, self.code, "任务不属于当前用户")
        if ctx.task.claimed_by_device_id != ctx.request.device_id:
            return CheckResult(False, self.code, "任务未被本设备领取")
        if ctx.task.claim_expires_at and ctx.task.claim_expires_at < datetime.now():
            return CheckResult(False, "TASK_CLAIM_EXPIRED", "任务领取锁已过期")
        if ctx.task.status in {"completed", "failed", "cancelled"}:
            return CheckResult(False, "TASK_TERMINAL", f"任务已结束: {ctx.task.status}")
        return CheckResult(True)


class RecordValidCheck(BaseCheck):
    """子记录有效性校验"""

    code = "RECORD_INVALID"
    description = "子记录不存在或已结算"

    def verify(self, ctx: ApprovalContext) -> CheckResult:
        if not ctx.record:
            return CheckResult(False, self.code, "子记录不存在")
        if ctx.record.task_id != ctx.task.id:
            return CheckResult(False, self.code, "子记录与任务不匹配")
        if ctx.record.status in {"success", "failed", "skipped", "manual_required"}:
            return CheckResult(False, "RECORD_TERMINAL", f"子记录已结算: {ctx.record.status}")
        return CheckResult(True)


class QuotaCheck(BaseCheck):
    """配额校验"""

    code = "QUOTA_EXCEEDED"
    description = "今日/本月发布次数已用完"

    def verify(self, ctx: ApprovalContext) -> CheckResult:
        quota = ctx.quota
        if not quota:
            # 无配额记录视为无限制（向后兼容老用户）
            return CheckResult(True)

        now = datetime.now()
        today = now.date()
        first_of_month = today.replace(day=1)

        # 配额自动重置
        if quota.reset_date != today:
            quota.used_today = 0
            quota.reset_date = today
        if quota.month_reset_date != first_of_month:
            quota.used_this_month = 0
            quota.month_reset_date = first_of_month

        # 首次「开始写入」时扣减配额，后续步骤（填充正文/提交）只校验不扣减
        if ctx.request.checkpoint == "before_write":
            if quota.used_today >= quota.daily_limit:
                return CheckResult(False, self.code,
                                   f"今日发布次数已用完 ({quota.used_today}/{quota.daily_limit})")
            if quota.used_this_month >= quota.monthly_limit:
                return CheckResult(False, "MONTHLY_QUOTA_EXCEEDED",
                                   f"本月发布次数已用完 ({quota.used_this_month}/{quota.monthly_limit})")

        return CheckResult(True)


class PlatformWhitelistCheck(BaseCheck):
    """平台白名单校验"""

    code = "PLATFORM_DENIED"
    description = "用户无权发布到此平台"

    def verify(self, ctx: ApprovalContext) -> CheckResult:
        quota = ctx.quota
        if not quota or not quota.platform_whitelist:
            return CheckResult(True)  # 无白名单 = 允许所有平台

        if not ctx.account:
            return CheckResult(True)

        if ctx.account.platform not in quota.platform_whitelist:
            return CheckResult(False, self.code,
                               f"账号平台 {ctx.account.platform} 不在白名单中")
        return CheckResult(True)


class AccountActiveCheck(BaseCheck):
    """账号状态校验"""

    code = "ACCOUNT_INACTIVE"
    description = "账号未授权或已禁用"

    def verify(self, ctx: ApprovalContext) -> CheckResult:
        if not ctx.account:
            return CheckResult(False, self.code, "账号不存在")
        if ctx.account.status != 1:
            return CheckResult(False, self.code,
                               f"账号状态异常: status={ctx.account.status}")
        return CheckResult(True)


# ==================== 校验器注册表 ====================


DEFAULT_CHECK_CHAIN: List[BaseCheck] = [
    DeviceActiveCheck(),
    TaskClaimedCheck(),
    RecordValidCheck(),
    AccountActiveCheck(),
    PlatformWhitelistCheck(),
    QuotaCheck(),
]


# ==================== 主服务 ====================


class PublishApprovalService:
    """发布审批服务 — 主入口"""

    def __init__(self, check_chain: Optional[List[BaseCheck]] = None,
                 token_ttl_seconds: int = 300,
                 config: Optional[Dict[str, Any]] = None):
        """
        Args:
            check_chain: 校验器链，默认使用 DEFAULT_CHECK_CHAIN
            token_ttl_seconds: 令牌有效期(秒)，在 config 未提供时使用
            config: PUBLISH_APPROVAL_CONFIG 字典；不传则从 backend.config 动态读取
        """
        self.check_chain = check_chain or DEFAULT_CHECK_CHAIN
        self._token_ttl_override = token_ttl_seconds
        # 延迟导入避免循环依赖
        try:
            from backend.config import PUBLISH_APPROVAL_CONFIG
            self._config = config if config is not None else PUBLISH_APPROVAL_CONFIG
        except Exception:
            self._config = config or {}

    @property
    def token_ttl_seconds(self) -> int:
        """令牌有效期（优先取 config，其次构造参数，最后默认 300）"""
        if self._config.get("token_ttl_seconds"):
            return int(self._config["token_ttl_seconds"])
        return self._token_ttl_override

    def _is_checkpoint_enabled(self, checkpoint: str) -> bool:
        """该检查点是否启用"""
        if not self._config.get("enabled", True):
            return False  # 总开关关闭 = 检查点全不起作用
        cp_cfg = self._config.get("checkpoints", {})
        if not cp_cfg:
            return True
        return bool(cp_cfg.get(checkpoint, True))

    def _is_bypass_user(self, user_id: int) -> bool:
        """用户是否在调试旁路列表中"""
        bypass = self._config.get("bypass_user_ids", set())
        return user_id in bypass

    def _is_auto_approve_device(self, device_id: str) -> bool:
        """设备是否在自动同意列表中"""
        auto = self._config.get("auto_approve_devices", set())
        return device_id in auto

    def _filter_check_chain(self) -> List[BaseCheck]:
        """根据 permission_checks 配置过滤校验器"""
        perm_cfg = self._config.get("permission_checks", {})
        if not perm_cfg:
            return self.check_chain

        # 校验器类名 → 配置 key 的映射
        # None 表示不可跳过（必须始终运行）
        name_to_key = {
            "DeviceActiveCheck": None,      # 设备检查永远不跳
            "TaskClaimedCheck": None,        # 任务领取检查永远不跳
            "RecordValidCheck": None,        # 子记录检查永远不跳
            "AccountActiveCheck": None,      # 账号检查永远不跳
            "PlatformWhitelistCheck": "platform_whitelist",
            "QuotaCheck": "quota_check",
        }

        filtered = []
        for check in self.check_chain:
            key = name_to_key.get(check.__class__.__name__)
            if key is None:
                filtered.append(check)  # 必要校验
            elif perm_cfg.get(key, True):
                filtered.append(check)
        return filtered

    def _auto_approve(self, request: ApprovalRequest, db: Session,
                      reason: str) -> "ApprovalResult":
        """跳过校验，直接生成令牌并记录日志（用于总开关/旁路/检查点关闭场景）"""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(seconds=self.token_ttl_seconds)
        self._write_log(db, request, approved=True,
                        approval_token=token, expires_at=expires_at)
        logger.info(
            f"[审批] ⚡ 自动同意（{reason}）用户 {request.user.id} "
            f"设备 {request.device_id} 检查点 {request.checkpoint}"
        )
        return ApprovalResult(
            approved=True,
            approval_token=token,
            expires_at=expires_at,
            context={
                "task_id": request.task_id,
                "record_id": request.record_id,
                "checkpoint": request.checkpoint,
                "auto_approved_reason": reason,
            },
        )

    def approve(self, request: ApprovalRequest, db: Session) -> ApprovalResult:
        """
        执行审批流程。

        步骤：
          0. 检查总开关 + 旁路 + 检查点开关（命中任一绕过则直接同意）
          1. 加载上下文（用户、设备、任务、记录、账号、文章、配额）
          2. 依次执行校验链，任一失败即终止
          3. 通过则生成一次性审批令牌
          4. 写审计日志
          5. 返回结果
        """
        # ---- 0. 总开关 + 旁路 + 检查点开关 ----
        if not self._config.get("enabled", True):
            return self._auto_approve(request, db, reason="approval_disabled")

        if self._is_bypass_user(request.user.id):
            return self._auto_approve(request, db, reason="bypass_user")

        if self._is_auto_approve_device(request.device_id):
            return self._auto_approve(request, db, reason="auto_approve_device")

        if not self._is_checkpoint_enabled(request.checkpoint):
            return self._auto_approve(
                request, db, reason=f"checkpoint_disabled:{request.checkpoint}",
            )

        # ---- 1. 加载上下文 ----
        ctx = self._build_context(request, db)

        # ---- 2. 执行校验链（按配置过滤） ----
        active_checks = self._filter_check_chain()
        for check in active_checks:
            try:
                result = check.verify(ctx)
            except Exception as e:
                logger.exception(f"[审批] 校验器 {check.__class__.__name__} 异常: {e}")
                result = CheckResult(False, "INTERNAL_ERROR", f"校验异常: {e}")

            if not result.passed:
                logger.warning(
                    f"[审批] 用户 {request.user.id} 设备 {request.device_id} "
                    f"任务 {request.task_id} 记录 {request.record_id} "
                    f"检查点 {request.checkpoint} → ❌ 拒绝 ({result.code}): {result.message}"
                )
                self._write_log(db, request, approved=False,
                                reason_code=result.code, reason=result.message)
                return ApprovalResult(
                    approved=False,
                    reason_code=result.code,
                    reason=result.message,
                )

        # ---- 2. 通过 → 生成令牌 ----
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(seconds=self.token_ttl_seconds)

        # ---- 3. 扣减配额（仅在 before_write 扣一次）----
        if request.checkpoint == "before_write" and ctx.quota:
            ctx.quota.used_today = (ctx.quota.used_today or 0) + 1
            ctx.quota.used_this_month = (ctx.quota.used_this_month or 0) + 1

        # ---- 4. 写审计日志 ----
        self._write_log(db, request, approved=True,
                        approval_token=token, expires_at=expires_at)

        logger.info(
            f"[审批] ✅ 用户 {request.user.id} 设备 {request.device_id} "
            f"任务 {request.task_id} 记录 {request.record_id} "
            f"检查点 {request.checkpoint} → 通过"
        )

        return ApprovalResult(
            approved=True,
            approval_token=token,
            expires_at=expires_at,
            context={
                "task_id": request.task_id,
                "record_id": request.record_id,
                "checkpoint": request.checkpoint,
                "platform": ctx.account.platform if ctx.account else None,
            },
        )

    # -------- 内部方法 --------

    def _build_context(self, request: ApprovalRequest, db: Session) -> ApprovalContext:
        """加载审批需要的全部关联数据"""
        device = (
            db.query(ClientDevice)
            .filter(
                ClientDevice.device_id == request.device_id,
                ClientDevice.user_id == request.user.id,
            )
            .first()
        )
        task = (
            db.query(AutoPublishTask)
            .filter(AutoPublishTask.id == request.task_id)
            .first()
        )
        record = (
            db.query(AutoPublishRecord)
            .filter(
                AutoPublishRecord.id == request.record_id,
                AutoPublishRecord.task_id == request.task_id,
            )
            .first()
        )
        account = None
        article = None
        if record:
            account = db.query(Account).filter(Account.id == record.account_id).first()
            article = db.query(GeoArticle).filter(GeoArticle.id == record.article_id).first()
        quota = (
            db.query(UserPublishQuota)
            .filter(UserPublishQuota.user_id == request.user.id)
            .first()
        )

        return ApprovalContext(
            request=request,
            db=db,
            user=request.user,
            device=device,
            task=task,
            record=record,
            account=account,
            article=article,
            quota=quota,
        )

    def _write_log(self, db: Session, request: ApprovalRequest, *,
                   approved: bool, reason_code: Optional[str] = None,
                   reason: Optional[str] = None,
                   approval_token: Optional[str] = None,
                   expires_at: Optional[datetime] = None) -> None:
        """写审批日志（异步安全：失败不影响主流程）"""
        try:
            log = PublishApprovalLog(
                user_id=request.user.id,
                task_id=request.task_id,
                record_id=request.record_id,
                device_id=request.device_id,
                checkpoint=request.checkpoint,
                approved=approved,
                reason_code=reason_code,
                reason=reason,
                approval_token=approval_token,
                expires_at=expires_at,
                client_ip=request.client_ip,
                user_agent=request.user_agent,
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.exception(f"[审批] 写日志失败（非阻塞）: {e}")
            try:
                db.rollback()
            except Exception:
                pass


# ==================== 单例 ====================

_approval_service: Optional[PublishApprovalService] = None


def get_approval_service() -> PublishApprovalService:
    """获取审批服务单例"""
    global _approval_service
    if _approval_service is None:
        _approval_service = PublishApprovalService()
    return _approval_service
