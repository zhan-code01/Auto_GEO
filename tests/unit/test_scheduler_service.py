# -*- coding: utf-8 -*-
"""调度服务单测：覆盖「不靠谱实现」的关键修复点。

不打真调度器、不连数据库；直接对 SchedulerService 实例做纯逻辑断言：
1. is_running() 真实反映调度器状态（此前 hasattr 兜底恒为 True）。
2. _schedule_job 对非法 cron / 未知 task_key 返回 False（此前静默吞错）。
3. reload_task 在 db_factory 缺失时返回 False（此前返回 None 被当成功）。
4. trigger_job 用调度器时区（Asia/Shanghai）的 aware 时间触发（此前 naive）。
"""

import pytest

from backend.services.scheduler_service import SchedulerService, _BEIJING_TZ
from backend.database.models import ScheduledTask


@pytest.fixture
def svc():
    s = SchedulerService()
    yield s
    # 确保调度器不残留 running 状态（本测试从不 start，但保险起见 shutdown）
    if s.scheduler.running:
        s.scheduler.shutdown(wait=False)


def test_is_running_reflects_real_state(svc):
    # 从未 start，应为 False（此前 hasattr 兜底会恒 True）
    assert svc.is_running() is False
    # start 后应为 True（不加载 DB 任务，仅验证状态翻转）
    svc.start()
    assert svc.is_running() is True
    svc.stop()
    assert svc.is_running() is False


def test_schedule_job_rejects_unknown_task_key(svc):
    task = ScheduledTask(
        id=1,
        name="不存在",
        task_key="no_such_key",
        cron_expression="* * * * *",
        is_active=True,
    )
    assert svc._schedule_job(task) is False
    assert svc.scheduler.get_job("no_such_key") is None


def test_schedule_job_rejects_invalid_cron(svc):
    task = ScheduledTask(
        id=2,
        name="非法Cron",
        task_key="publish_task",
        cron_expression="not a cron",
        is_active=True,
    )
    assert svc._schedule_job(task) is False
    assert svc.scheduler.get_job("publish_task") is None


def test_schedule_job_accepts_valid_cron(svc):
    task = ScheduledTask(
        id=3,
        name="正常任务",
        task_key="publish_task",
        cron_expression="*/1 * * * *",
        is_active=True,
    )
    assert svc._schedule_job(task) is True
    assert svc.scheduler.get_job("publish_task") is not None


def test_schedule_job_inactive_removes_job(svc):
    # 先装载一个活动任务
    active = ScheduledTask(
        id=4, name="活动", task_key="publish_task", cron_expression="*/1 * * * *", is_active=True
    )
    assert svc._schedule_job(active) is True
    assert svc.scheduler.get_job("publish_task") is not None

    # 再置为不活动：应从调度器移除，且视为成功
    inactive = ScheduledTask(
        id=4, name="活动", task_key="publish_task", cron_expression="*/1 * * * *", is_active=False
    )
    assert svc._schedule_job(inactive) is True
    assert svc.scheduler.get_job("publish_task") is None


def test_reload_task_returns_false_without_db_factory(svc):
    svc.db_factory = None
    assert svc.reload_task(1) is False


def test_trigger_job_returns_false_for_missing_job(svc):
    assert svc.trigger_job("no_such_job") is False


def test_trigger_job_uses_aware_beijing_time(svc):
    """trigger_job 走调度器时区 aware 时间路径，且对存在的 job 返回 True。

    AsyncIOScheduler.start() 需要运行中的事件循环，故在 asyncio.run 内执行。
    """
    import asyncio

    task = ScheduledTask(
        id=5, name="任务", task_key="monitor_task", cron_expression="*/5 * * * *", is_active=True
    )
    assert svc._schedule_job(task) is True

    async def _run():
        svc.scheduler.start()
        try:
            assert svc.trigger_job("monitor_task") is True
            job = svc.scheduler.get_job("monitor_task")
            nr = job.next_run_time
            assert nr is not None
            if _BEIJING_TZ is not None:
                assert nr.tzinfo is not None
                assert str(nr.tzinfo) == "Asia/Shanghai"
        finally:
            svc.scheduler.shutdown(wait=False)

    asyncio.run(_run())
