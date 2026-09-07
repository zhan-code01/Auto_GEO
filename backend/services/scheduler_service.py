# -*- coding: utf-8 -*-
"""
自动化调度服务 - 工业加固版
负责：定时扫描待发布文章、自动触发收录检测、失败重试、动态任务加载
"""

import asyncio
from datetime import timedelta
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# 尝试导入时区，防止环境缺失报错
try:
    from pytz import timezone
except ImportError:
    timezone = None

from backend.database.models import ScheduledTask, GeoArticle, AutoPublishTask
from backend.utils.time_utils import beijing_now
from backend.config import MAX_CONCURRENT_PUBLISH
from backend.log_setup import cleanup_old_log_files

# 🌟 统一日志绑定
log = logger.bind(module="调度中心")

# 调度器使用的时区（与 APScheduler 一致，用于把 naive 北京时间转成 aware 时间触发任务）
_BEIJING_TZ = timezone("Asia/Shanghai") if timezone else None


class SchedulerService:
    def __init__(self):
        # 配置调度器，设置较长的误火容忍时间
        self.scheduler = AsyncIOScheduler(
            timezone=_BEIJING_TZ,
            job_defaults={
                "misfire_grace_time": 60,  # 🌟 允许错过时间后60秒内重试
                "coalesce": True,  # 积压的任务只跑一次
                "max_instances": 1,  # 同一个Job同时只能跑一个实例
            },
        )
        self.db_factory = None

        # 🌟 后台发布任务引用登记：防止任务异常无人消费（Task exception was never retrieved）
        self._bg_tasks: set = set()

        # 🌟 发布/收录检测并发闸门：避免每分钟扫描一次性打爆 Playwright
        self._publish_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PUBLISH)
        self._index_check_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PUBLISH)
        self._auto_publish_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PUBLISH)

        # 🌟 任务映射表
        self.task_registry = {
            "publish_task": self.check_and_publish_scheduled_articles,
            "monitor_task": self.auto_check_indexing_job,
            "ai_index_monitor_task": self.ai_index_monitor_job,
            "auto_publish_scheduler": self.auto_publish_scheduler_job,
        }

    def _spawn_background_task(self, coro):
        """登记并派发后台任务，任务结束后自动从登记表中移除。"""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _spawn_limited(self, semaphore: asyncio.Semaphore, coro):
        """受并发闸门限流地派发一个后台任务；被限流的任务排队等候，永不丢失。

        与裸 create_task 不同，这里先 acquire 信号量再真正执行 coro，从而限制同时
        启动的 Playwright 会话数量。任务对象仍登记进 _bg_tasks 防止异常被 GC 吞掉。
        """

        async def _guarded():
            async with semaphore:
                await coro

        return self._spawn_background_task(_guarded())

    def set_db_factory(self, db_factory):
        self.db_factory = db_factory

    def init_default_tasks(self):
        """初始化默认定时扫描任务（按 task_key 幂等补齐，已存在的自定义配置不被覆盖）"""
        if not self.db_factory:
            return
        db = self.db_factory()
        try:
            defaults = [
                ScheduledTask(
                    name="文章自动发布引擎",
                    task_key="publish_task",
                    cron_expression="*/1 * * * *",  # 每分钟扫描一次
                    description="扫描待发布文章并触发浏览器自动化脚本",
                    is_active=True,
                ),
                ScheduledTask(
                    name="全网收录实时监测",
                    task_key="monitor_task",
                    cron_expression="*/5 * * * *",  # 每5分钟监测一次
                    description="通过AI搜索引擎检查已发布文章的收录状态",
                    is_active=True,
                ),
                ScheduledTask(
                    name="AI收录定期复测",
                    task_key="ai_index_monitor_task",
                    cron_expression="0 3 * * *",  # 每天凌晨3点复测一次（AI收录为天/周级变化）
                    description="对已建立基线的项目，定期复测关键词在豆包/通义/DeepSeek的收录情况，用于前后对比诊断",
                    is_active=True,
                ),
                ScheduledTask(
                    name="自动发布任务调度",
                    task_key="auto_publish_scheduler",
                    cron_expression="*/1 * * * *",  # 每分钟扫描一次（分钟级精度）
                    description="扫描到点的定时/间隔自动发布任务：服务端模式触发执行，本地客户端模式放行领取",
                    is_active=True,
                ),
            ]
            added = 0
            for default in defaults:
                existing = db.query(ScheduledTask).filter(ScheduledTask.task_key == default.task_key).first()
                if existing is None:
                    db.add(default)
                    added += 1
            if added:
                db.commit()
                log.info(f"✅ 默认定时扫描任务补齐完成（新增 {added} 项）")
        except Exception as e:
            log.error(f"初始化任务失败: {e}")
        finally:
            db.close()

    def _schedule_job(self, task: ScheduledTask) -> bool:
        """内部方法：注册/更新单个 Job。返回是否成功装载（含无效 cron / 未知 task_key）。"""
        func = self.task_registry.get(task.task_key)
        if not func:
            log.warning(f"⚠️ 未找到处理函数: {task.task_key}")
            return False

        if self.scheduler.get_job(task.task_key):
            self.scheduler.remove_job(task.task_key)

        if task.is_active:
            try:
                self.scheduler.add_job(
                    func,
                    CronTrigger.from_crontab(task.cron_expression),
                    id=task.task_key,
                    replace_existing=True,
                    misfire_grace_time=60,  # 🌟 加固保护
                )
                log.info(f"📅 任务装载成功: [{task.name}] -> {task.cron_expression}")
            except Exception as e:
                log.error(f"❌ Cron 表达式解析错误 [{task.name}]: {e}")
                return False

        # 未启用：等价于从调度器中移除，视为成功（配置已生效为「暂停」）
        return True

    def load_jobs_from_db(self):
        """从数据库加载并注册所有任务"""
        if not self.db_factory:
            return
        db = self.db_factory()
        try:
            tasks = db.query(ScheduledTask).all()
            for t in tasks:
                self._schedule_job(t)
        finally:
            db.close()

    def is_running(self) -> bool:
        """调度引擎是否正在运行。供健康检查/管理后台准确判断状态。"""
        return bool(self.scheduler.running) if self.scheduler is not None else False

    def start(self):
        """启动调度引擎"""
        if not self.scheduler.running:
            self.init_default_tasks()
            self.load_jobs_from_db()
            # 内置日志清理任务：每天 04:10 清扫超过保留期的日志文件（与 loguru retention 双重保障）
            try:
                self.scheduler.add_job(
                    cleanup_old_log_files,
                    CronTrigger(hour=4, minute=10),
                    id="log_cleanup_task",
                    replace_existing=True,
                    misfire_grace_time=3600,
                )
            except Exception as exc:
                log.warning(f"日志清理任务注册失败: {exc}")
            self.scheduler.start()
            log.success("🚀 [Scheduler] 动态调度引擎已全面启动")

    def stop(self):
        """安全停止"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            log.info("🛑 [Scheduler] 调度引擎已安全关闭")

    def reload_task(self, task_id: int) -> bool:
        """用户修改配置后，手动热更新。返回是否成功装载到调度器。"""
        if not self.db_factory:
            log.warning("⚠️ 调度器 db_factory 未初始化，无法热更新任务")
            return False
        db = self.db_factory()
        try:
            task = db.query(ScheduledTask).get(task_id)
            if task:
                return self._schedule_job(task)
            log.warning(f"⚠️ 热更新失败：任务不存在 id={task_id}")
            return False
        finally:
            db.close()

    def trigger_job(self, job_id: str) -> bool:
        """
        立即触发任务执行

        使用 job.modify(next_run_time=<现在>) 将任务下一次运行时间设置为现在，
        调度器会立即捡起并执行，且不影响原来的周期计划。

        时区处理：next_run_time 必须是调度器时区（Asia/Shanghai）下的 aware datetime，
        否则 APScheduler 会把 naive 时间按错误口径解释，导致「立即执行」落在错误时刻。

        参数:
            job_id: APScheduler 的 Job ID (task_key，如 "publish_task")

        返回:
            bool: 是否触发成功
        """
        job = self.scheduler.get_job(job_id)
        if not job:
            log.warning(f"⚠️ 尝试触发的任务不存在: {job_id}")
            return False

        try:
            # 将下一次运行时间设置为现在（调度器时区 aware），避免 naive/服务器本地时间漂移
            now = beijing_now()
            if _BEIJING_TZ is not None:
                now_aware = _BEIJING_TZ.localize(now)
            else:
                now_aware = now
            job.modify(next_run_time=now_aware)
            log.success(f"🚀 任务已触发执行: [{job_id}]")
            return True
        except Exception as e:
            log.error(f"❌ 触发任务失败 [{job_id}]: {e}")
            return False

    # ================= 🚀 核心业务逻辑 Job =================

    async def check_and_publish_scheduled_articles(self):
        """
        [Job] 自动扫描并发布

        扫描条件：
        1. publish_status = 'scheduled'（已配置定时发布）
        2. platform 不为空（已配置发布平台）
        3. account_id 不为空（已配置发布账号）
        4. scheduled_at 时间已到

        注意：不扫描 completed 状态的文章（等待用户在批量发布页面配置）

        并发模型：扫描阶段用短生命周期的 Session 只读取文章 ID；
        派发阶段每个发布任务通过 run_publish_with_own_session 独立持有 Session，
        杜绝多任务共享连接串台、以及扫描 Session 提前关闭导致任务失效的问题。
        重复发布由 execute_publish 内部的原子状态抢占（scheduled→publishing）兜底。
        """
        if not self.db_factory:
            return
        from sqlalchemy import and_

        db = self.db_factory()
        pending_ids: list[int] = []
        try:
            now = beijing_now()
            rows = (
                db.query(GeoArticle.id)
                .filter(
                    and_(
                        GeoArticle.publish_status == "scheduled",
                        GeoArticle.platform.isnot(None),
                        GeoArticle.account_id.isnot(None),
                        GeoArticle.scheduled_at <= now,
                    )
                )
                .all()
            )
            pending_ids = [row[0] for row in rows]
        except Exception as e:
            log.error(f"发布 Job 运行异常: {e}")
        finally:
            db.close()

        if pending_ids:
            log.info(f"🔍 [发布扫描] 发现 {len(pending_ids)} 篇定时发布文章，准备触发脚本...")
            from backend.services.geo_article_service import run_publish_with_own_session

            for article_id in pending_ids:
                self._spawn_limited(self._publish_semaphore, run_publish_with_own_session(article_id))
        else:
            log.debug("🔍 [发布扫描] 无定时发布文章待处理")

    async def auto_check_indexing_job(self):
        """
        [Job] 自动监测收录

        并发模型同 check_and_publish_scheduled_articles：扫描与任务执行分离，
        每个检测任务独立持有 Session。
        """
        if not self.db_factory:
            return
        db = self.db_factory()
        pending_ids: list[int] = []
        try:
            # 搜索：已发布 但 未被确认收录的文章
            rows = (
                db.query(GeoArticle.id)
                .filter(GeoArticle.publish_status == "published", GeoArticle.index_status != "indexed")
                .all()
            )
            pending_ids = [row[0] for row in rows]
        except Exception as e:
            log.error(f"监测 Job 运行异常: {e}")
        finally:
            db.close()

        if pending_ids:
            log.info(f"📡 [收录扫描] 发现 {len(pending_ids)} 篇已发布文章需要检测效果...")
            from backend.services.geo_article_service import run_index_check_with_own_session

            for article_id in pending_ids:
                self._spawn_limited(self._index_check_semaphore, run_index_check_with_own_session(article_id))

    async def ai_index_monitor_job(self):
        """
        [Job] AI收录定期复测（关键词/公司级，区别于 auto_check_indexing_job 的文章收录检测）

        仅复测 status==1 且 baseline_at 非空的项目（未建基线的项目跳过，避免无意义检测）。
        复测结果标记 check_phase=ongoing，供"使用前后对比"诊断报表使用。

        扫描阶段用短生命周期 Session 只读取项目 ID；执行阶段每个项目独立持有 Session，
        避免 LLM 调用期间 Session 超时失效。
        """
        if not self.db_factory:
            return
        from backend.database.models import Project

        # 扫描阶段：短生命周期 Session，只读项目 ID
        db = self.db_factory()
        project_ids: list[tuple[int, int]] = []  # (project_id, user_id)
        try:
            rows = (
                db.query(Project.id, Project.user_id).filter(Project.status == 1, Project.baseline_at.isnot(None)).all()
            )
            project_ids = [(row[0], row[1]) for row in rows]
        except Exception as e:
            log.error(f"AI收录复测扫描异常: {e}")
        finally:
            db.close()

        if not project_ids:
            log.info("🔍 [AI收录复测] 暂无已建立基线的项目，跳过")
            return

        log.info(f"🔍 [AI收录复测] 开始复测 {len(project_ids)} 个项目...")

        # 执行阶段：每个项目独立 Session，避免 LLM 调用期间连接超时
        for project_id, user_id in project_ids:
            db = self.db_factory()
            try:
                project = db.query(Project).filter(Project.id == project_id).first()
                if not project:
                    log.warning(f"⚠️ [AI收录复测] 项目 id={project_id} 不存在，跳过")
                    continue

                from backend.services.index_check_service import IndexCheckService

                service = IndexCheckService(db)
                results = await service.check_project_keywords(
                    project_id=project_id,
                    user_id=user_id,
                    check_phase="ongoing",
                )
                log.info(f"✅ [AI收录复测] 项目 {project.name}(id={project_id}) 完成，生成 {len(results)} 条记录")
            except Exception as e:
                log.error(f"❌ [AI收录复测] 项目 id={project_id} 复测失败: {e}")
            finally:
                db.close()

            # 反风控：项目之间间隔，避免被平台识别为自动化
            await asyncio.sleep(2)

    async def auto_publish_scheduler_job(self):
        """
        [Job] AutoPublishTask 定时/间隔任务调度扫描（分钟级精度）

        每分钟扫描一次，把到点的 scheduled/interval 自动发布任务放行执行：
        - execution_mode=cloud_browser/api：由服务端 Playwright 执行；
        - execution_mode=local_client：保持 pending，由本地客户端轮询到点领取
          （client_publish.py 的时间闸门），服务端不直接执行，避免与客户端双跑。

        幂等：仅 status=='pending' 的任务会被触发，running 中的任务不会被重复扫描；
        interval 任务每轮完成后由执行方重武装 scheduled_at（见 rearm_interval_task）。
        """
        if not self.db_factory:
            return
        db = self.db_factory()
        try:
            from backend.api.auto_publish import execute_auto_publish_task

            now = beijing_now()
            due = (
                db.query(AutoPublishTask)
                .filter(
                    AutoPublishTask.status == "pending",
                    AutoPublishTask.exec_type.in_(["scheduled", "interval"]),
                    AutoPublishTask.scheduled_at.isnot(None),
                    AutoPublishTask.scheduled_at <= now,
                )
                .all()
            )
            triggered = 0
            for task in due:
                if task.execution_mode not in ("cloud_browser", "api"):
                    log.debug(f"🕐 [任务调度] 任务 {task.id} 已到点，等待本地客户端领取执行")
                    continue
                log.info(f"🕐 [任务调度] 任务 {task.id} 到点，触发服务端自动发布")
                self._spawn_limited(self._auto_publish_semaphore, execute_auto_publish_task(task.id))
                triggered += 1
            if triggered:
                log.info(f"🕐 [任务调度] 本轮触发 {triggered} 个自动发布任务")
        except Exception as e:
            log.error(f"自动发布任务调度 Job 运行异常: {e}")
        finally:
            db.close()


# 单例模式
_instance = SchedulerService()


def get_scheduler_service():
    return _instance
