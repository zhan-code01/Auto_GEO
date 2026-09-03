# -*- coding: utf-8 -*-
"""账户绑定工具 - 2 个独立工具（对齐 PRD §8.3.4）。

- bind_platform: 绑定发布平台账号（发起浏览器登录授权）
- list_bindings: 查询当前用户已绑定的平台账号

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.actions import make_action
from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


@register_tool("bind_platform")
async def bind_platform_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """绑定发布平台账号。

    必填槽位：platform（中文名或 platform_id 均可，如「抖音」/「douyin」）
    可选槽位：account_name / account_id（重新授权已有账号时使用）

    第二层防护：工具执行时校验 platform，缺失或无法识别则返回 need_clarification。
    """
    from backend.database import SessionLocal
    from backend.services.agent_v2.adapters import PublishAdapter
    from backend.services.agent_v2.platforms import resolve_platform

    raw_platform = slots.get("platform")
    account_name = slots.get("account_name")
    account_id_raw = slots.get("account_id")

    # 中文名/别名 -> platform_id（platform_id 自身也会命中映射）
    platform = resolve_platform(raw_platform) if raw_platform else None

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 第二层防护：必填校验
        if not platform:
            logger.warning(f"[bind_platform] 缺失或无法识别 platform: raw={raw_platform!r} user={user_id}")
            return ToolOutcome.need_clarification(
                reply="请选择要绑定的发布平台",
                suggestion="支持知乎、百家号、抖音等平台，请告诉我您想绑定哪个",
            )

        # account_id 安全转换为 int（非法值忽略并告警，不阻断流程）
        try:
            account_id = int(account_id_raw) if account_id_raw else None
        except (TypeError, ValueError):
            logger.warning(f"[bind_platform] 无效 account_id={account_id_raw!r}，已忽略")
            account_id = None

        adapter = PublishAdapter(db)
        result = await adapter.start_platform_auth(
            user=fake_user,
            platform=platform,
            account_name=account_name,
            account_id=account_id,
        )
        task_id = result.get("task_id")
        logger.info(f"[bind_platform] 发起授权 platform={platform} task_id={task_id} user={user_id}")
        
        # 轮询逻辑已在 playwright_mgr.create_auth_task 中启动（_poll_login_status）
        # 这里只需要返回任务信息给前端

        return ToolOutcome.running(
            reply=f"正在为【{platform}】发起登录授权，请在弹出的浏览器窗口中完成登录。登录成功后浏览器会自动关闭。",
            data={"task_id": task_id, "platform": platform},
            facts_patch=[{"common_platforms": [platform]}],
            async_task_refs=[{
                "task_type": "auth",
                "task_id": task_id,
                "platform": platform,
            }],
        )
    except Exception as e:
        logger.error(f"[bind_platform] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="发起平台授权失败",
            error_type="execution_error",
            suggestion="请稍后重试，或确认平台名称是否正确",
        )
    finally:
        db.close()


@register_tool("list_bindings")
async def list_bindings_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """查询当前用户已绑定的平台账号（含登录态有效性检测）。

    可选槽位：platform（按平台筛选，中文名或 platform_id 均可）
    有绑定记录时返回 show_binding_list action 供前端展示列表。

    登录态有效性判定规则（重要：只依据数据库 status 与凭证存在性，绝不按"授权天数"瞎猜）：
    - status == -1 → 数据库标记授权过期（确定失效）
    - 凭证（cookies / storage_state / 本地会话）缺失 → 未授权
    - 有凭证且未被标记过期 → 视为有效（但仅代表"最近未被判定失效"，不代表此刻一定登录着）
    - 真正的登录态只有"用会话在浏览器里实际访问一次"才能确认；last_check_time 记录最近一次真实验证时间
    - 若 last_check_time 缺失或较久（>30 天），在回复中提示用户"建议点一键检测"，
      但不得自行断言"已过期"或"登录超期"
    - 返回 session_valid 字段供前端展示"需要重新授权"提示
    """
    from datetime import datetime, timedelta, timezone
    from backend.database import SessionLocal
    from backend.database.models import Account
    from backend.middleware.user_isolation import scoped_query
    from backend.services.agent_v2.adapters import AccountAdapter
    from backend.services.agent_v2.platforms import resolve_platform, get_platform_name

    raw_platform = slots.get("platform")
    platform = resolve_platform(raw_platform) if raw_platform else None
    # 认为登录态可能失效的授权时间窗口（14 天）
    _SESSION_EXPIRE_DAYS = 14

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 直接用 ORM 查询 Account 原行，保证拿到完整的 cookies/storage_state/status
        rows = (
            scoped_query(db, Account, fake_user)
            .filter(Account.deleted_at.is_(None))
            .order_by(Account.created_at.desc())
            .all()
        )
        # 过滤掉 AI 平台账号（仅展示发布平台）
        from backend.services.agent_v2.platforms import is_ai_platform
        rows = [r for r in rows if not is_ai_platform(r.platform)]
        # 按平台筛选
        if platform:
            rows = [r for r in rows if r.platform == platform]

        if not rows:
            adapter = AccountAdapter(db)
            available = adapter.list_available_platforms()
            if platform:
                reply = f"您还没有绑定【{platform}】平台账号"
            else:
                reply = "您还没有绑定任何发布平台账号"
            logger.info(f"[list_bindings] 用户 {user_id} 无绑定记录 platform={platform}")
            return ToolOutcome(
                reply=reply,
                suggestion="请在弹窗中选择平台并完成登录授权",
            )

        # 现在逐项检测登录态
        items: list[dict] = []
        lines: list[str] = []
        for r in rows[:30]:
            # 基础授权判断（复用 Account.is_authorized 属性，已区分 local_only / server）
            try:
                base_auth = r.is_authorized
            except Exception:
                base_auth = bool(r.cookies and r.storage_state)

            session_location = r.session_location or "server"

            # 登录态有效性判断
            session_valid = base_auth
            invalid_reason: str | None = None
            needs_reauth = False

            # 1) 数据库明确标记过期 → 肯定失效
            if r.status == -1:
                session_valid = False
                needs_reauth = True
                invalid_reason = "授权已过期"
            # 2) 凭证缺失 → 未授权
            elif not base_auth:
                session_valid = False
                needs_reauth = True
                if session_location == "local_only":
                    invalid_reason = "未绑定设备"
                else:
                    invalid_reason = "登录凭证缺失"
            # 3) 有凭证且未被标记过期 → 视为有效
            # （不应用固定天数过期规则，因为各平台 cookie 有效期差异很大）

            platform_name = get_platform_name(r.platform) or r.platform
            account_name = r.account_name or r.username or "未命名"

            items.append({
                "id": r.id,
                "platform": r.platform,
                "platform_name": platform_name,
                "account_name": account_name,
                "is_authorized": base_auth,
                "session_valid": session_valid,
                "needs_reauth": needs_reauth,
                "invalid_reason": invalid_reason,
                "status": r.status,
                "session_location": session_location,
                # 注意：不再把 last_auth_time（授权时间）放进给 LLM 的数据，
                # 避免模型自行按"距今天数"推断过期。改用 last_check_time（最近真实验证时间）。
                "last_check_time": r.last_check_time.isoformat() if r.last_check_time else None,
            })

            # 给用户看的总结文本（避免出现 id 等内部字段）
            status_icon = "✅" if session_valid else "⚠️"
            if session_valid:
                if r.last_check_time:
                    age_days = (datetime.now() - r.last_check_time).days
                    status_text = "正常" if age_days <= 30 else "正常（状态较久未验证，建议点一键检测）"
                else:
                    status_text = "正常（尚未验证，建议点一键检测确认）"
            else:
                status_text = invalid_reason or "需要重新授权"
            lines.append(f"- {status_icon} {platform_name} / {account_name}（{status_text}）")

        total = len(items)
        valid_count = sum(1 for it in items if it["session_valid"])
        invalid_count = total - valid_count

        header = f"您已绑定 {total} 个平台账号（有效 {valid_count} / 需重新授权 {invalid_count}）"
        reply_text = header + "\n" + "\n".join(lines)
        logger.info(
            f"[list_bindings] 用户 {user_id} 已绑定 {total} 个平台 "
            f"(valid={valid_count} invalid={invalid_count}) platform={platform}"
        )

        return ToolOutcome.success(
            data={"items": items, "total": total, "valid_count": valid_count, "invalid_count": invalid_count},
            reply=reply_text,
            actions=[make_action(
                "show_binding_list",
                "查看绑定列表",
                {
                    "items": items,
                    "total": total,
                    "valid_count": valid_count,
                    "invalid_count": invalid_count,
                },
            )],
        )
    except Exception as e:
        logger.error(f"[list_bindings] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="查询已绑定平台账号失败",
            error_type="execution_error",
            suggestion="请稍后重试",
        )
    finally:
        db.close()
