# -*- coding: utf-8 -*-
"""
GEO文章业务服务 - 工业加固修复版 (v2.7)
修复：
1. 解决 AI 还没生成完就触发发布的竞态问题
2. 强化发布前的状态校验
3. 优化日志输出，适配前端实时监控
4. 修复 project_id 关联问题
5. 修复变量名混用导致的 NameError
"""

import asyncio
import os
import random
import json
import re
import sys
import zlib
from typing import Any, Dict, Optional, List
from datetime import datetime
from loguru import logger
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.database.models import (
    GeoArticle,
    Keyword,
    Account,
    PublishRecord,
    Project,
    AutoPublishTask,
    AutoPublishRecord,
)
from backend.services.article_markdown import markdown_to_html
from backend.services.article_image_service import ArticleImageService
from backend.services.geo_knowledge_service import GeoKnowledgeService
from backend.services.playwright.publishers.base import get_publisher
from backend.services.crypto import decrypt_cookies, decrypt_storage_state
from backend.services.playwright.session_state import normalize_platform_storage_state
from backend.services.websocket_manager import ws_manager
from backend.utils.time_utils import beijing_now
from playwright.async_api import async_playwright

# 模块化日志绑定
gen_log = logger.bind(module="生成器")
pub_log = logger.bind(module="发布器")
chk_log = logger.bind(module="监测站")


class GeoArticleService:
    def __init__(self, db: Session):
        self.db = db
        self.article_image_service = ArticleImageService()

    def _stabilize_image_urls(self, content: str, article_id: int) -> str:
        """
        给动态图源补稳定 lock，避免预览和发布两次请求拿到不同图片。
        只处理 loremflickr，保留其它图片源原样。
        """
        if not content:
            return content

        counter = 0

        def replace_url(match):
            nonlocal counter
            url = match.group(1)
            if "loremflickr.com" not in url or "lock=" in url:
                return match.group(0)

            counter += 1
            seed_text = f"{article_id}:{counter}:{url}"
            lock = zlib.crc32(seed_text.encode("utf-8")) % 9999 + 1
            separator = "&" if "?" in url else "?"
            stable_url = f"{url}{separator}lock={lock}"
            return match.group(0).replace(url, stable_url)

        return re.sub(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", replace_url, content)

    async def _prepare_article_content(self, content: str, *, article_id: int, keyword: str, title: str) -> str:
        """Convert generated image slots to stable remote loremflickr URLs."""
        return await self.article_image_service.process_article_images(
            content,
            article_id=article_id,
            keyword=keyword,
            title=title,
        )

    async def generate(
        self,
        keyword_id: int,
        company_name: str,
        target_platforms: Optional[List[str]] = None,
        publish_strategy: str = "draft",
        scheduled_at: Optional[str] = None,
        user_id: Optional[int] = None,
        source: Optional[str] = None,
        generation_batch_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        异步生成文章逻辑（异步回调模式）

        user_id: 显式指定文章归属用户。若未传，则从关键词所属项目的属主推导，
        保证后台链路（飞书/Agent）生成的文章也正确归属。
        """
        # 1. 先获取关键词对象，获取 project_id
        kw_obj = self.db.query(Keyword).filter(Keyword.id == keyword_id).first()
        if not kw_obj:
            return {"success": False, "message": "关键词不存在"}
        kw_text = kw_obj.keyword if kw_obj else "未知关键词"
        project_id = kw_obj.project_id if kw_obj else None

        # 1.1 解析文章归属用户：优先显式传入，否则取项目属主
        owner_id = user_id
        if owner_id is None and project_id:
            project = self.db.query(Project).filter(Project.id == project_id).first()
            if project:
                owner_id = project.user_id

        # 归属兜底：仍无法解析时记录告警，避免静默产生 user_id=None 的孤儿文章
        # （孤儿文章在按 user_id 隔离的文章管理列表中对普通用户不可见）
        if owner_id is None:
            gen_log.warning(
                f"⚠️ 无法解析文章归属用户 (keyword_id={keyword_id}, project_id={project_id})，"
                "将生成孤儿文章（普通用户不可见）。请确认调用入口已传入 user_id 或关键词绑定了有效项目。"
            )

        # 2. 创建占位记录，初始状态为 generating
        article = GeoArticle(
            keyword_id=keyword_id,
            project_id=project_id,  # 设置项目ID
            user_id=owner_id,  # 数据隔离归属
            title="[AI正在创作中]...",
            content="正在努力写作，请稍后刷新列表...",
            publish_status="generating",
            # 存储发布策略
            target_platforms=target_platforms,
            publish_strategy=publish_strategy,
            # 来源与批次（批量生成时由调用方传入；默认 None → 模型默认 'manual'）
            source=source,
            generation_batch_id=generation_batch_id,
        )

        # 如果是定时发布，解析并设置定时时间
        if publish_strategy == "scheduled" and scheduled_at:
            from datetime import datetime

            try:
                article.scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except Exception as e:
                gen_log.warning(f"解析定时时间失败: {e}")

        self.db.add(article)
        self.db.commit()
        self.db.refresh(article)

        gen_log.info(
            f"🆕 任务启动：为关键词 ID {keyword_id} (项目ID: {project_id}) 生成文章 (article_id: {article.id})"
        )
        gen_log.info(f"📋 发布策略: {publish_strategy}, 目标平台: {target_platforms}")

        try:
            # 3. 调用 DeepSeek 直连生成（同步返回）
            gen_log.info(f"🛰️ 正在生成 AI 文章 (关键词: {kw_text})，DeepSeek 直连同步模式...")
            knowledge_service = GeoKnowledgeService(self.db)
            base_requirements = (
                f"围绕【{company_name}】编写，风格专业商务，适合 B2B 企业发布。"
                "文章应自然覆盖用户搜索意图、行业痛点、解决方案和企业优势。"
            )
            rag_context = knowledge_service.build_context_for_keyword(
                keyword_id=keyword_id,
                company_name=company_name,
            )
            requirements = knowledge_service.build_requirements(
                base_requirements=base_requirements,
                rag_context=rag_context,
            )
            gen_log.info(
                "GEO RAG context: article_id={}, enabled={}, datasets={}, chunks={}, warnings={}",
                article.id,
                rag_context.get("enabled"),
                len(rag_context.get("dataset_ids", [])),
                len(rag_context.get("chunks", [])),
                rag_context.get("warnings", []),
            )
            # 使用 DeepSeek AI 直连
            from backend.services.ai_generation_service import get_ai_service
            ai = get_ai_service()
            gen_log.info(f"🤖 开始 AI 生成文章 (article_id: {article.id})")
            ai_res = await ai.generate_geo_article(
                keyword=kw_text,
                company_name=company_name,
                requirements=requirements,
                word_count=1200,
                article_id=article.id,
            )

            if ai_res.get("status") == "success":
                ai_data = ai_res.get("data", {})
                if ai_data.get("title") and ai_data.get("content"):
                    gen_log.info(f"✅ AI 同步返回文章 (article_id: {article.id})")
                    article.title = ai_data["title"]
                    stabilized = await self._prepare_article_content(
                        ai_data["content"],
                        article_id=article.id,
                        keyword=kw_text,
                        title=ai_data["title"],
                    )
                    article.content = markdown_to_html(stabilized)

                    # 提取 SEO 评分
                    seo = ai_res.get("seo", {})
                    if isinstance(seo, dict) and seo.get("score"):
                        article.ai_score = int(seo["score"])

                    # 根据发布策略更新状态
                    strategy = article.publish_strategy or "draft"
                    if strategy == "immediate":
                        article.publish_status = "publishing"
                    elif strategy == "scheduled":
                        scheduled_ok = self._create_scheduled_publish_task(article, owner_id)
                        article.publish_status = "scheduled" if scheduled_ok else "failed"
                    else:
                        article.publish_status = "completed"
                        article.error_msg = None

                    self.db.commit()
                    gen_log.success(f"✅ 文章 {article.id} 同步生成完成，策略: {strategy}")

                    # 如果是立即发布，触发发布逻辑。
                    # 每个发布任务独立持有数据库会话（见 run_publish_with_own_session），
                    # 避免调用方（请求/调度）Session 关闭后任务失效。
                    if strategy == "immediate":
                        asyncio.create_task(run_publish_with_own_session(article.id))
                else:
                    gen_log.warning(f"⚠️ AI 返回数据缺少 title/content (article_id: {article.id})")
                    article.publish_status = "failed"
                    article.error_msg = "AI 返回数据不完整"
                    self.db.commit()
            else:
                article.publish_status = "failed"
                article.error_msg = ai_res.get("message") or "AI 生成失败"
                self.db.commit()
                gen_log.error(f"❌ AI 生成失败：{ai_res.get('message', '')}")

            return {"success": True, "article_id": article.id}

        except Exception as e:
            gen_log.exception(f"🚨 后端生成异常：{str(e)}")
            article.publish_status = "failed"
            article.error_msg = str(e)
            self.db.commit()
            return {"success": False, "message": str(e)}

    def _resolve_platform_accounts(self, platforms: Optional[List[str]], owner_id: Optional[int]) -> List[Account]:
        """为每个目标平台解析一个可用授权账号（取该平台首个已授权账号）。

        账号必须属于文章归属用户且 status==1，并按 Account.is_authorized 校验，
        避免把「已启用但未登录/未绑定设备」的账号写进本地客户端任务。
        """
        if not platforms or owner_id is None:
            return []
        resolved: List[Account] = []
        seen_ids: set = set()
        for platform in platforms:
            if not platform:
                continue
            query = self.db.query(Account).filter(
                Account.platform == platform,
                Account.status == 1,
                Account.user_id == owner_id,
            )
            account = query.order_by(Account.id).first()
            if account and account.is_authorized and account.id not in seen_ids:
                resolved.append(account)
                seen_ids.add(account.id)
        return resolved

    def _create_scheduled_publish_task(self, article: GeoArticle, owner_id: Optional[int]) -> bool:
        """生成完成后落地定时发布任务（本地客户端执行链）。

        迁移背景：生成时选择「定时发布」此前只把 GeoArticle.publish_status 置为
        scheduled，却不设置 platform/account_id；旧的服务端扫描器（要求两者均非空）
        永远不会捡起这类文章，导致其停留在 scheduled 状态而永不发布。

        现改为直接创建 execution_mode=local_client、exec_type=scheduled 的
        AutoPublishTask，由本地客户端到点轮询领取执行（见 client_publish.py 的时间闸门）。
        账号解析规则：每个目标平台取该归属用户下首个已授权账号。
        """
        if not article.scheduled_at:
            article.error_msg = "定时发布未配置：缺少发布时间"
            return False

        platforms = article.target_platforms
        if isinstance(platforms, str):
            try:
                platforms = json.loads(platforms)
            except Exception:
                platforms = [platforms] if platforms else []
        accounts = self._resolve_platform_accounts(platforms, owner_id)
        if not accounts:
            article.error_msg = "定时发布未配置：目标平台没有可用的已授权账号"
            return False

        task = AutoPublishTask(
            name=f"定时发布-{article.title or article.id}",
            description="生成时选择的定时发布策略",
            article_ids=[article.id],
            account_ids=[a.id for a in accounts],
            platforms=sorted({a.platform for a in accounts}),
            declare_ai_content=True,
            user_id=owner_id,
            triggered_by_user_id=owner_id,
            status="pending",
            exec_type="scheduled",
            execution_mode="local_client",
            scheduled_at=article.scheduled_at,
            total_count=len(accounts),
            completed_count=0,
            failed_count=0,
        )
        self.db.add(task)
        self.db.flush()
        for account in accounts:
            self.db.add(
                AutoPublishRecord(
                    task_id=task.id,
                    article_id=article.id,
                    account_id=account.id,
                    status="pending",
                )
            )
        gen_log.info(
            f"📅 定时发布任务已创建: article_id={article.id}, task_id={task.id}, "
            f"accounts={[a.id for a in accounts]}, scheduled_at={article.scheduled_at}"
        )
        return True

    def claim_scheduled_for_publish(self, article_id: int) -> bool:
        """
        原子抢占发布权：仅当文章当前状态为 scheduled 时，将其置为 publishing。

        单条 UPDATE ... WHERE publish_status='scheduled' 依赖数据库条件匹配，
        并发场景下只有第一个执行成功的任务拿到 rowcount==1，其余任务拿到 0 并应跳过。
        这保证同一篇文章绝不会被并发重复发布。
        """
        claimed = self.db.execute(
            update(GeoArticle)
            .where(
                GeoArticle.id == article_id,
                GeoArticle.publish_status == "scheduled",
            )
            .values(publish_status="publishing", error_msg=None)
        )
        self.db.commit()
        return claimed.rowcount == 1

    async def execute_publish(self, article_id: int) -> bool:
        """
        执行真实发布动作 (修复 Session 丢失问题版)
        """
        # 重新从数据库获取最新状态
        db_article = self.db.query(GeoArticle).filter(GeoArticle.id == article_id).first()

        if not db_article:
            pub_log.error(f"❌ 文章不存在: {article_id}")
            return False

        # 支持 scheduled、publishing、failed 和 completed 状态（允许重试失败任务）
        if db_article.publish_status not in ["scheduled", "publishing", "failed", "completed"]:
            pub_log.info(f"⏭️ 跳过文章 {article_id}：当前状态为 {db_article.publish_status}")
            return False

        # 🌟 原子抢占：scheduled → publishing。
        # 调度器每分钟扫描与手动触发可能并发命中同一篇文章；只有抢到状态变更的
        # 任务才真正执行发布，杜绝同一篇文章被重复发布。
        if db_article.publish_status == "scheduled":
            if not self.claim_scheduled_for_publish(article_id):
                pub_log.info(f"⏭️ 跳过文章 {article_id}：已被其他发布任务抢占")
                return False
            self.db.refresh(db_article)

        # 🌟 状态流转优化：如果是 failed 或 completed，先重置为 publishing
        if db_article.publish_status in ["failed", "completed"]:
            _prev_status = db_article.publish_status
            db_article.publish_status = "publishing"
            db_article.error_msg = None  # 清除之前的错误信息
            self.db.commit()
            pub_log.info(f"🔄 重置文章 {article_id} 状态为 publishing（原状态: {_prev_status}）")

        if "创作中" in (db_article.title or ""):
            pub_log.warning(f"⚠️ 文章 {article_id} 内容仍为占位符")
            return False

        # 自动填充平台
        if not db_article.platform and db_article.target_platforms:
            try:
                if isinstance(db_article.target_platforms, list):
                    target = db_article.target_platforms[0]
                else:
                    targets = json.loads(str(db_article.target_platforms))
                    target = targets[0] if targets else None

                if target:
                    db_article.platform = target
                    self.db.commit()
                    self.db.refresh(db_article)
            except Exception as e:
                pub_log.warning(f"⚠️ 自动填充平台失败: {e}")

        if not db_article.platform:
            db_article.publish_status = "failed"
            db_article.error_msg = "未指定发布平台"
            self.db.commit()
            return False

        # 查找账号：优先使用前端/任务已绑定的 account_id，避免发布到同平台的错误账号
        account = None
        if db_article.account_id:
            account = (
                self.db.query(Account)
                .filter(Account.id == db_article.account_id, Account.status == 1)
                .first()
            )
            if not account:
                db_article.publish_status = "failed"
                db_article.error_msg = "指定发布账号不可用或未授权"
                self.db.commit()
                return False

            if account.platform != db_article.platform:
                pub_log.warning(
                    f"⚠️ 文章 {article_id} 平台与账号平台不一致，已使用账号平台: "
                    f"{db_article.platform} -> {account.platform}"
                )
                db_article.platform = account.platform
                self.db.commit()
                self.db.refresh(db_article)
        else:
            account = self.db.query(Account).filter(Account.platform == db_article.platform, Account.status == 1).first()

        if not account or not account.storage_state:
            db_article.publish_status = "failed"
            db_article.error_msg = "缺少授权数据"
            self.db.commit()
            return False

        # 锁定账号ID
        db_article.account_id = account.id
        self.db.commit()

        publisher = get_publisher(db_article.platform)
        if not publisher:
            db_article.publish_status = "failed"
            db_article.error_msg = f"暂不支持发布平台: {db_article.platform}"
            self.db.commit()
            return False

        # 解析 Session
        try:
            state_data = decrypt_storage_state(account.storage_state)
            if not state_data:
                state_data = json.loads(account.storage_state)
            fallback_cookies = decrypt_cookies(account.cookies) if account.cookies else None
            state_data = normalize_platform_storage_state(account.platform, state_data, fallback_cookies)
        except Exception:
            db_article.publish_status = "failed"
            db_article.error_msg = "Session解析失败"
            self.db.commit()
            return False

        # 提取关键变量（防止 commit 后对象失效）
        # 🌟 关键：提前把 ID、平台等信息存到局部变量
        target_article_id = db_article.id
        target_account_id = account.id
        target_platform = db_article.platform

        wait_time = random.randint(5, 10)
        pub_log.info(f"⏳ 模拟人工：将在 {wait_time}s 后启动浏览器")
        await asyncio.sleep(wait_time)

        # 🌟 关键修复：和 PlaywrightManager 保持一致的浏览器配置
        # 否则微信等平台会因浏览器指纹不一致而拒绝 session（page_timeout）
        from backend.config import BROWSER_ARGS as _browser_args, DEFAULT_USER_AGENT as _default_ua

        _executable_path = None
        for _p in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]:
            if os.path.exists(_p):
                _executable_path = _p
                break
        if sys.platform == "darwin":
            for _p in [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]:
                if os.path.exists(_p):
                    _executable_path = _p
                    break

        _launch_opts = {"headless": False, "args": list(_browser_args)}
        if _executable_path:
            _launch_opts["executable_path"] = _executable_path

        async with async_playwright() as p:
            browser = await p.chromium.launch(**_launch_opts)
            try:
                context = await browser.new_context(
                    storage_state=state_data,
                    viewport={"width": 1280, "height": 800},
                    user_agent=_default_ua,
                )
                page = await context.new_page()

                # 更新为发布中
                # 注意：这里需要重新查询一次，确保 Session 活跃
                current_article = self.db.query(GeoArticle).get(target_article_id)
                if current_article:
                    current_article.publish_status = "publishing"
                    self.db.commit()

                # 执行发布
                pub_log.info(f"🚀 开始执行发布脚本: {target_platform}")
                # 注意：publisher 内部不应再操作 db 对象，只读取属性
                result = await publisher.publish(page, current_article, account)

                # 重新查询以进行最终状态更新
                # 🌟 再次获取全新对象，避免 Playwright 操作期间 Session 过期
                final_article = self.db.query(GeoArticle).get(target_article_id)
                if not final_article:
                    raise Exception("文章在发布过程中被删除")

                # 准备数据
                now_time = beijing_now()
                is_success = result.get("success")
                final_url = result.get("platform_url")
                error_msg = result.get("error_msg")

                # 更新数据库对象
                if is_success:
                    final_article.publish_status = "published"
                    final_article.publish_time = now_time
                    final_article.platform_url = final_url
                    final_article.publish_logs = f"[{now_time}] ✅ 发布成功"
                    pub_log.success(f"🎊 发布完成：{final_url}")
                else:
                    final_article.publish_status = "failed"
                    final_article.error_msg = error_msg
                    final_article.retry_count += 1
                    pub_log.error(f"❌ 发布失败：{error_msg}")

                # 🌟 核心修改：提交事务
                self.db.commit()
                # 提交后，final_article 对象即视为过期，不再访问它

                # 🌟 核心修改：使用局部变量广播 WebSocket
                # 不再使用 db_article 或 final_article 的属性
                ws_data = {
                    "type": "publish_progress",
                    "article_id": target_article_id,
                    "account_id": target_account_id,
                    "status": 2 if is_success else 3,
                    "publish_status": "published" if is_success else "failed",
                    "platform_url": final_url,
                    "error_msg": error_msg,
                }
                await ws_manager.broadcast(ws_data)

                # 🌟 核心修改：使用局部变量写入发布记录
                # 完全解耦，不再依赖之前的 Session
                # 注意：PublishRecord 通过 account_id 关联 Account，平台信息可从 Account 获取，不需要直接存储 platform 字段
                try:
                    record = (
                        self.db.query(PublishRecord)
                        .filter(
                            PublishRecord.article_id == target_article_id,
                            PublishRecord.account_id == target_account_id,
                        )
                        .order_by(PublishRecord.created_at.desc())
                        .first()
                    )
                    if not record:
                        record = PublishRecord(
                            article_id=target_article_id,
                            account_id=target_account_id,
                        )
                        self.db.add(record)

                    record.publish_status = 2 if is_success else 3
                    record.platform_url = final_url
                    record.error_msg = error_msg
                    record.published_at = now_time if is_success else None
                    self.db.commit()
                    pub_log.info("📝 发布记录已保存")
                except Exception as rec_e:
                    pub_log.error(f"⚠️ 记录写入失败 (不影响状态): {rec_e}")
                    self.db.rollback()

                return is_success

            except Exception as e:
                self.db.rollback()
                pub_log.error(f"🚨 发布异常中断: {e}")

                # 异常情况下的状态回滚
                try:
                    fail_article = self.db.query(GeoArticle).get(target_article_id)
                    if fail_article:
                        fail_article.publish_status = "failed"
                        fail_article.error_msg = f"异常: {str(e)}"
                        self.db.commit()

                        # 广播失败
                        await ws_manager.broadcast(
                            {
                                "type": "publish_progress",
                                "article_id": target_article_id,
                                "status": 3,
                                "publish_status": "failed",
                                "error_msg": str(e),
                            }
                        )
                except:
                    pass
                return False
            finally:
                await browser.close()

    async def check_quality(self, article_id: int) -> Dict[str, Any]:
        """
        文章质量检查（AI 评估）

        评估维度：
        - quality_score: 内容完整性、结构、可读性 (0-100)
        - fact_risk_score: 事实风险和幻觉风险 (0-100，越低越安全)
        - platform_risk_score: 平台合规风险 (0-100，越低越安全)
        - duplication_score: 与历史文章重复度 (0-100，越低越原创)

        自动发布阈值：
        - quality_score >= 75
        - fact_risk_score <= 30
        - platform_risk_score <= 30
        - duplication_score <= 70
        """
        article = self.get_article(article_id)
        if not article:
            return {"success": False, "message": "文章不存在"}

        gen_log.info(f"📊 正在对文章 {article_id} 进行 AI 质量评估...")

        try:
            # 构建质量检查 Prompt
            prompt = self._build_quality_check_prompt(article)

            # 尝试调用 AI 获取质量评分
            result = await self._call_quality_ai(prompt)

            if result:
                article.quality_score = result.get("quality_score", 70)
                article.fact_risk_score = result.get("fact_risk_score", 30)
                article.platform_risk_score = result.get("platform_risk_score", 30)
                article.duplication_score = result.get("duplication_score", 50)

                # 检查自动发布阈值
                if (
                    article.quality_score >= 75
                    and article.fact_risk_score <= 30
                    and article.platform_risk_score <= 30
                    and article.duplication_score <= 70
                ):
                    article.quality_status = "passed"
                else:
                    article.quality_status = "review_required"

                self.db.commit()

                gen_log.info(
                    f"✅ 质量检查完成: article_id={article_id}, "
                    f"quality={article.quality_score}, fact_risk={article.fact_risk_score}, "
                    f"platform_risk={article.platform_risk_score}, dup={article.duplication_score}, "
                    f"status={article.quality_status}"
                )

                return {
                    "success": True,
                    "quality_score": article.quality_score,
                    "fact_risk_score": article.fact_risk_score,
                    "platform_risk_score": article.platform_risk_score,
                    "duplication_score": article.duplication_score,
                    "quality_status": article.quality_status,
                }

        except Exception as e:
            gen_log.warning(f"AI 质量检查调用失败，使用保守评分: {e}")

        # AI 不可用时使用保守评分，进入人工审核，避免无质检能力时自动发布。
        article.quality_score = 70
        article.fact_risk_score = 25
        article.platform_risk_score = 25
        article.duplication_score = 50
        article.quality_status = "review_required"
        self.db.commit()

        return {
            "success": True,
            "quality_score": article.quality_score,
            "fact_risk_score": article.fact_risk_score,
            "platform_risk_score": article.platform_risk_score,
            "duplication_score": article.duplication_score,
            "quality_status": article.quality_status,
            "note": "fallback_score (AI unavailable)",
        }

    def _build_quality_check_prompt(self, article) -> str:
        """构建质量检查 Prompt"""
        title = article.title or ""
        content = article.content or ""
        # 截取前 2000 字符用于评分
        content_preview = content[:2000] if content else ""

        return f"""请对以下文章进行质量评估，返回 JSON 格式的评分结果。

评估标准：
1. quality_score (0-100): 内容完整性、结构逻辑、可读性、专业性
2. fact_risk_score (0-100): 是否存在编造的资质、案例、价格、客户名称等幻觉风险（分数越低越安全）
3. platform_risk_score (0-100): 是否可能违反内容平台规则，如过度营销、虚假宣传（分数越低越安全）
4. duplication_score (0-100): 是否为通用模板化内容，缺乏独特观点（分数越低越原创）

文章标题：{title}

文章内容：
{content_preview}

请只返回 JSON：{{"quality_score": 数字, "fact_risk_score": 数字, "platform_risk_score": 数字, "duplication_score": 数字}}"""

    async def _call_quality_ai(self, prompt: str) -> Optional[Dict[str, int]]:
        """调用 AI 进行质量检查"""
        import json as json_module

        try:
            from backend.services.ai_generation_service import get_ai_service

            ai = get_ai_service()
            result = await ai._chat_with_retry(
                messages=[
                    {"role": "system", "content": "你是一个专业的内容质量审核员。只返回 JSON，不返回其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
                json_mode=True,
            )
            content = result.get("content", "")

            # 提取 JSON
            json_match = json_module.loads(content.strip())
            if isinstance(json_match, dict) and "quality_score" in json_match:
                return {
                    "quality_score": int(json_match.get("quality_score", 70)),
                    "fact_risk_score": int(json_match.get("fact_risk_score", 30)),
                    "platform_risk_score": int(json_match.get("platform_risk_score", 30)),
                    "duplication_score": int(json_match.get("duplication_score", 50)),
                }
        except Exception as e:
            gen_log.warning(f"质量检查 AI 调用异常: {e}")

        return None

    async def check_article_index(self, article_id: int) -> Dict[str, Any]:
        """收录监测逻辑"""
        article = self.get_article(article_id)
        if not article or article.publish_status != "published":
            return {"status": "error", "message": "文章未发布"}

        chk_log.info(f"🔍 [监测] 正在检索文章《{article.title[:10]}...》的收录情况")
        await asyncio.sleep(2)
        is_indexed = random.random() > 0.5
        article.index_status = "indexed" if is_indexed else "not_indexed"
        article.last_check_time = datetime.now()
        self.db.commit()
        return {"status": "success", "index_status": article.index_status}

    def get_article(self, article_id: int) -> Optional[GeoArticle]:
        return self.db.query(GeoArticle).get(article_id)

    def get_articles(self) -> List[GeoArticle]:
        # ⚠️ 注意：此方法返回全部文章，不做用户隔离。
        # 当前无 API 端点调用它；如需在路由层使用，必须先按 user_id 过滤
        # （参见 backend.middleware.user_isolation.scoped_query），否则会越权泄露。
        return self.db.query(GeoArticle).order_by(GeoArticle.created_at.desc()).all()

    def delete_article(self, article_id: int) -> bool:
        article = self.get_article(article_id)
        if article:
            self.db.delete(article)
            self.db.commit()
            return True
        return False


# ==================== 后台任务安全入口 ====================
# 背景任务（asyncio.create_task 派发）绝不能复用调用方的 Session：
# 调用方（HTTP 请求 / 调度器扫描）返回后其 Session 即被关闭，
# 且多个并发任务共享同一 Session 会互相串台。
# 因此统一在这里为每个后台任务创建独立的数据库会话，用完即关。


async def run_publish_with_own_session(article_id: int) -> bool:
    """在独立 Session 上执行发布，供后台任务安全调用（不共享调用方 Session）。"""
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        return await GeoArticleService(db).execute_publish(article_id)
    except Exception:
        pub_log.exception(f"❌ 后台发布任务异常 (article_id={article_id})")
        return False
    finally:
        db.close()


async def run_index_check_with_own_session(article_id: int) -> Dict[str, Any]:
    """在独立 Session 上执行收录检测，供后台任务安全调用（不共享调用方 Session）。"""
    from backend.database import SessionLocal

    db = SessionLocal()
    try:
        return await GeoArticleService(db).check_article_index(article_id)
    except Exception:
        chk_log.exception(f"❌ 后台收录检测任务异常 (article_id={article_id})")
        return {"status": "error", "message": "后台检测任务异常"}
    finally:
        db.close()
