# -*- coding: utf-8 -*-
"""收录监控工具 - 3 个独立工具（对齐 PRD §8.3.6）。

- create_baseline: 创建基线（使用前）
- run_recheck: 执行复测（使用后）
- get_diagnosis: 获取诊断指标

收录监控核心逻辑（PRD §8.3.6）：
- 用**用户问题**去 AI 平台提问（不是监测特定文章），分析 AI 回答中的收录情况。
- 计算 4 个核心指标：
  1. 关键词命中率 (keyword_hit_rate)
  2. 公司名提及率 (company_hit_rate)
  3. 平均置信度 (avg_confidence)
  4. 覆盖平台 (platform_count)

工具签名统一：async def fn(slots: dict, user_id: int) -> ToolOutcome
参数由 LLM 通过 Tool Calling 机制基于 tool_schemas.py 的 Pydantic schema 生成。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from backend.services.agent_v2.platforms import resolve_platform
from backend.services.agent_v2.tools.base import ToolOutcome, register_tool


# AI 平台中文名映射（对齐 PRD §8.3.6）
_PLATFORM_NAMES: dict[str, str] = {
    "doubao": "豆包",
    "qianwen": "通义千问",
    "deepseek": "DeepSeek",
}


def _platform_text(platforms: list[str]) -> str:
    """把平台英文 key 列表转成中文名顿号串。"""
    return "、".join(_PLATFORM_NAMES.get(p, p) for p in platforms)


def _extract_metrics(block: dict[str, Any] | None) -> dict[str, Any]:
    """从诊断数据块中提取 4 个核心指标。

    对齐 GeoEvaluationAnalyticsService._aggregate 实际返回字段：
    - coverage_rate   → 关键词/品牌命中率（PRD §8.3.6 keyword_hit_rate 对应）
    - ranking_score   → 推荐排名得分（PRD §8.3.6 avg_confidence 对应）
    - sentiment_score → 情感得分
    - visibility_score → AI 可见度总分（PRD §8.3.6 company_hit_rate 综合维度对应）
    - valid_count     → 有效样本数
    缺失或为空时回落为 0。
    """
    block = block or {}
    return {
        # PRD §8.3.6 四指标对齐实际服务返回字段
        "keyword_hit_rate": block.get("coverage_rate") or 0,  # 覆盖率 = 关键词命中率
        "company_hit_rate": block.get("visibility_score") or 0,  # 可见度总分 = 公司综合提及率
        "avg_confidence": block.get("ranking_score") or 0,  # 排名得分 = 平均置信度
        "platform_count": block.get("valid_count") or 0,  # 有效样本数 = 覆盖平台数
        # 同时保留原字段供前端展示对比
        "coverage_rate": block.get("coverage_rate") or 0,
        "ranking_score": block.get("ranking_score") or 0,
        "sentiment_score": block.get("sentiment_score") or 0,
        "visibility_score": block.get("visibility_score") or 0,
        "valid_count": block.get("valid_count") or 0,
    }


@register_tool("create_baseline")
async def create_baseline_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """创建基线（使用前）。

    必填槽位（由 Pydantic CreateBaselineInput 校验）：client_id/ai_platform（单选）
    可选槽位：account_id（未提供时由服务自动从用户绑定的同平台账号解析）
    第二层防护：工具执行时再次检查必填字段，缺失则返回 need_clarification 引导用户补充。

    底层 GeoEvaluationRunService.create_baseline 强制每次只能选 1 个 AI 平台，
    所以本工具只接受 ai_platform 单值，不接收 list。
    """
    from backend.database import SessionLocal
    from backend.services.geo_evaluation_run_service import GeoEvaluationRunService

    client_id = slots.get("client_id")
    ai_platform = resolve_platform(slots.get("ai_platform"))
    account_id = slots.get("account_id")

    # 第二层防护：工具执行时校验必填
    if not client_id:
        return ToolOutcome.need_clarification(
            reply="请提供客户ID",
            suggestion="可以先调用 list_clients 查看客户列表",
        )

    if not ai_platform:
        return ToolOutcome.need_clarification(
            reply="请选择要监测的 AI 平台（豆包/通义千问/DeepSeek，单选）",
            suggestion="请告诉我使用哪个 AI 平台进行监测",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 越权防护：校验 client 归属（与 list_clients 等工具一致，scoped_query 按 user 隔离）
        from backend.database.models import Client
        from backend.middleware.user_isolation import scoped_query

        owned_client = scoped_query(db, Client, fake_user).filter(Client.id == int(client_id)).first()
        if not owned_client:
            return ToolOutcome.failure(
                reply=f"客户 {client_id} 不存在或无权限访问",
                error_type="not_found",
                suggestion="请检查客户ID，或调用 list_clients 查看客户列表",
            )

        # RunService 需要可返回新 Session 的工厂（供后台线程使用）
        service = GeoEvaluationRunService(db_factory=SessionLocal)
        result = service.create_baseline(
            client_id=int(client_id),
            platforms=[ai_platform],  # 服务内部强制单选
            created_by=fake_user.id,
            user_id=fake_user.id,
            account_id=int(account_id) if account_id else None,
        )

        if not result.get("success"):
            logger.warning(
                f"[create_baseline] 创建失败: client={client_id} platform={ai_platform} msg={result.get('message')}"
            )
            # 账号选择缺失 → 引导用户选择账号
            if result.get("requires_account_selection"):
                return ToolOutcome.need_clarification(
                    reply=result.get("message", "请选择 AI 平台账号"),
                    suggestion="请先绑定并选择该平台的账号",
                )
            return ToolOutcome.failure(
                reply=result.get("message", "创建基线失败"),
                error_type="execution_error",
                suggestion="请稍后重试，或检查客户ID是否正确",
            )

        run_id = result.get("run_id")
        logger.info(f"[create_baseline] client={client_id} platform={ai_platform} run_id={run_id}")

        return ToolOutcome.running(
            data={
                "run_id": run_id,
                "client_id": int(client_id),
                "platform": ai_platform,
            },
            reply=(
                f"正在创建基线，监测平台：{_platform_text([ai_platform])}。\n"
                f"系统将使用项目中的用户问题去该平台提问，分析 AI 回答中的收录情况。\n"
                f"任务已提交（任务ID: {run_id}），完成后可通过 get_diagnosis 查看 4 个核心指标。"
            ),
            async_task_refs=[
                {
                    "task_type": "baseline_run",
                    "task_id": run_id,
                    "query_tool": "get_diagnosis",
                }
            ],
        )
    except Exception as e:
        logger.error(f"[create_baseline] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="创建基线失败",
            error_type="execution_error",
            suggestion="请稍后重试，或检查客户ID与平台参数是否正确",
        )
    finally:
        db.close()


@register_tool("run_recheck")
async def run_recheck_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """执行复测（使用后）。

    必填槽位（由 Pydantic RunRecheckInput 校验）：client_id/ai_platform（单选）
    可选槽位：account_id
    第二层防护：工具执行时再次检查必填字段，缺失则返回 need_clarification 引导用户补充。
    """
    from backend.database import SessionLocal
    from backend.services.geo_evaluation_run_service import GeoEvaluationRunService

    client_id = slots.get("client_id")
    ai_platform = resolve_platform(slots.get("ai_platform"))
    account_id = slots.get("account_id")

    # 第二层防护：工具执行时校验必填
    if not client_id:
        return ToolOutcome.need_clarification(
            reply="请提供客户ID",
            suggestion="可以先调用 list_clients 查看客户列表",
        )

    if not ai_platform:
        return ToolOutcome.need_clarification(
            reply="请选择要监测的 AI 平台（豆包/通义千问/DeepSeek，单选）",
            suggestion="请告诉我使用哪个 AI 平台进行复测",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 越权防护：校验 client 归属（与 list_clients 等工具一致，scoped_query 按 user 隔离）
        from backend.database.models import Client
        from backend.middleware.user_isolation import scoped_query

        owned_client = scoped_query(db, Client, fake_user).filter(Client.id == int(client_id)).first()
        if not owned_client:
            return ToolOutcome.failure(
                reply=f"客户 {client_id} 不存在或无权限访问",
                error_type="not_found",
                suggestion="请检查客户ID，或调用 list_clients 查看客户列表",
            )

        # RunService 需要可返回新 Session 的工厂（供后台线程使用）
        service = GeoEvaluationRunService(db_factory=SessionLocal)
        result = service.create_recheck(
            client_id=int(client_id),
            platforms=[ai_platform],  # 服务内部强制单选
            created_by=fake_user.id,
            user_id=fake_user.id,
            account_id=int(account_id) if account_id else None,
        )

        if not result.get("success"):
            logger.warning(
                f"[run_recheck] 复测失败: client={client_id} platform={ai_platform} msg={result.get('message')}"
            )
            if result.get("requires_account_selection"):
                return ToolOutcome.need_clarification(
                    reply=result.get("message", "请选择 AI 平台账号"),
                    suggestion="请先绑定并选择该平台的账号",
                )
            return ToolOutcome.failure(
                reply=result.get("message", "执行复测失败"),
                error_type="execution_error",
                suggestion="请先确认已创建基线，或稍后重试",
            )

        run_id = result.get("run_id")
        logger.info(f"[run_recheck] client={client_id} platform={ai_platform} run_id={run_id}")

        return ToolOutcome.running(
            data={
                "run_id": run_id,
                "client_id": int(client_id),
                "platform": ai_platform,
            },
            reply=(
                f"正在执行复测，监测平台：{_platform_text([ai_platform])}。\n"
                f"系统将使用项目中的用户问题去该平台提问，与基线对比，评估 GEO 优化效果。\n"
                f"任务已提交（任务ID: {run_id}），完成后可通过 get_diagnosis 查看 4 个核心指标的变化。"
            ),
            async_task_refs=[
                {
                    "task_type": "recheck_run",
                    "task_id": run_id,
                    "query_tool": "get_diagnosis",
                }
            ],
        )
    except Exception as e:
        logger.error(f"[run_recheck] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="执行复测失败",
            error_type="execution_error",
            suggestion="请稍后重试，或确认已先创建基线",
        )
    finally:
        db.close()


@register_tool("get_diagnosis")
async def get_diagnosis_tool(slots: dict[str, Any], user_id: int) -> ToolOutcome:
    """获取诊断指标。

    必填槽位（由 Pydantic GetDiagnosisInput 校验）：client_id
    返回 4 个核心指标：keyword_hit_rate/company_hit_rate/avg_confidence/platform_count，
    并与基线对比。无数据时引导用户先创建基线。
    """
    from backend.database import SessionLocal
    from backend.services.geo_evaluation_analytics_service import GeoEvaluationAnalyticsService

    client_id = slots.get("client_id")

    # 第二层防护：工具执行时校验必填
    if not client_id:
        return ToolOutcome.need_clarification(
            reply="请提供客户ID",
            suggestion="可以先调用 list_clients 查看客户列表",
        )

    fake_user = SimpleNamespace(id=user_id, role="user")
    db = SessionLocal()
    try:
        # 越权防护：校验 client 归属（与 list_clients 等工具一致，scoped_query 按 user 隔离）
        from backend.database.models import Client
        from backend.middleware.user_isolation import scoped_query

        owned_client = scoped_query(db, Client, fake_user).filter(Client.id == int(client_id)).first()
        if not owned_client:
            return ToolOutcome.failure(
                reply=f"客户 {client_id} 不存在或无权限访问",
                error_type="not_found",
                suggestion="请检查客户ID，或调用 list_clients 查看客户列表",
            )

        analytics = GeoEvaluationAnalyticsService(db)
        diagnosis = analytics.get_client_diagnosis(
            client_id=int(client_id),
            days=7,
        )

        # 服务返回错误（如公司不存在）
        if not diagnosis or diagnosis.get("error"):
            logger.warning(
                f"[get_diagnosis] 查询异常: client={client_id} err={diagnosis.get('error') if diagnosis else 'empty'}"
            )
            return ToolOutcome.failure(
                reply=f"客户 {client_id} 不存在或查询失败",
                error_type="not_found",
                suggestion="请检查客户ID，或调用 list_clients 查看客户列表",
            )

        baseline_block = diagnosis.get("baseline") or {}
        current_block = diagnosis.get("current") or {}

        # 无基线数据：引导用户先创建基线（选择 AI 平台）
        if baseline_block.get("valid_count", 0) == 0:
            logger.info(f"[get_diagnosis] 暂无基线数据: client={client_id}")
            return ToolOutcome.need_clarification(
                reply="该客户暂无收录诊断数据。请先创建基线，选择要监测的 AI 平台。",
                suggestion="请告诉我监测哪个 AI 平台（豆包/通义千问/DeepSeek），我再为您创建基线",
            )

        metrics = _extract_metrics(current_block)
        baseline_metrics = _extract_metrics(baseline_block)

        logger.info(f"[get_diagnosis] client={client_id} metrics={metrics}")

        return ToolOutcome.success(
            data={
                "client_id": int(client_id),
                "metrics": metrics,
                "baseline": baseline_metrics,
            },
            reply=(
                f"收录诊断结果：\n"
                f"- 关键词命中率：{float(metrics['keyword_hit_rate']):.1f}%\n"
                f"- 公司名提及率：{float(metrics['company_hit_rate']):.1f}%\n"
                f"- 平均置信度：{float(metrics['avg_confidence']):.2f}\n"
                f"- 覆盖平台：{metrics['platform_count']} 个"
            ),
        )
    except Exception as e:
        logger.error(f"[get_diagnosis] 失败: {e}", exc_info=True)
        return ToolOutcome.failure(
            reply="获取诊断数据失败",
            error_type="execution_error",
            suggestion="请稍后重试，或确认已创建基线",
        )
    finally:
        db.close()
