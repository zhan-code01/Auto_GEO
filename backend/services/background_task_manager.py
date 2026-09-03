# -*- coding: utf-8 -*-
"""全局后台任务管理器 - 确保后台任务不会被 SSE 流取消。"""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine
from loguru import logger


class BackgroundTaskManager:
    """全局后台任务管理器"""
    
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_counter = 0
    
    def submit(
        self,
        coro: Coroutine[Any, Any, Any],
        task_name: str | None = None,
    ) -> str:
        """提交一个后台任务
        
        Args:
            coro: 要执行的协程
            task_name: 任务名称（可选）
            
        Returns:
            任务 ID
        """
        self._task_counter += 1
        task_id = task_name or f"bg_task_{self._task_counter}"
        
        async def wrapper():
            try:
                logger.info(f"[BackgroundTask] 开始执行: {task_id}")
                await coro
                logger.info(f"[BackgroundTask] 执行完成: {task_id}")
            except asyncio.CancelledError:
                logger.warning(f"[BackgroundTask] 任务被取消: {task_id}")
            except Exception as e:
                logger.error(f"[BackgroundTask] 任务异常: {task_id} - {e}", exc_info=True)
            finally:
                # 任务完成后自动清理
                if task_id in self._tasks:
                    del self._tasks[task_id]
        
        task = asyncio.create_task(wrapper(), name=task_id)
        self._tasks[task_id] = task
        logger.info(f"[BackgroundTask] 任务已提交: {task_id}")
        return task_id
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"[BackgroundTask] 任务已取消: {task_id}")
            return True
        return False
    
    def get_task(self, task_id: str) -> asyncio.Task | None:
        """获取任务"""
        return self._tasks.get(task_id)
    
    def list_tasks(self) -> list[str]:
        """列出所有任务"""
        return list(self._tasks.keys())
    
    def register_task(self, task_id: str, task: asyncio.Task) -> None:
        """注册一个已创建的任务，防止被外部取消

        Args:
            task_id: 任务 ID
            task: 已创建的 asyncio.Task
        """
        # 存储原始 task（而非 shield），因为 asyncio.shield 被 cancel 时
        # 会连带取消内部 task，起不到保护作用。
        # 通过 cancel() 方法拒绝取消来保护任务。
        self._tasks[task_id] = task
        logger.info(f"[BackgroundTask] 任务已注册并保护: {task_id}")

        # 添加回调，任务完成时自动清理
        task.add_done_callback(lambda t: self._on_task_done(task_id, t))
    
    def _on_task_done(self, task_id: str, task: asyncio.Task) -> None:
        """任务完成回调"""
        if task_id in self._tasks:
            del self._tasks[task_id]
        if task.cancelled():
            logger.warning(f"[BackgroundTask] 任务被取消: {task_id}")
        elif task.exception():
            logger.error(f"[BackgroundTask] 任务异常: {task_id} - {task.exception()}")
        else:
            logger.info(f"[BackgroundTask] 任务完成: {task_id}")


# 全局单例
background_task_manager = BackgroundTaskManager()
