# -*- coding: utf-8 -*-
"""
重试策略管理器
管理授权过程中的错误重试逻辑
"""

import asyncio
import random
from typing import Callable, Awaitable, Any, Dict
from loguru import logger

from backend.services.auth_errors import is_retryable_error, AuthError


class RetryStrategy:
    """
    重试策略类
    管理错误重试的逻辑
    """

    def __init__(
        self, max_retries: int = 2, base_delay: float = 2.0, max_delay: float = 10.0, backoff_factor: float = 1.5
    ):
        """
        初始化重试策略

        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒）
            max_delay: 最大延迟（秒）
            backoff_factor: 退避因子
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor

    async def execute_with_retry(
        self, operation: Callable[[], Awaitable[Any]], operation_name: str, **kwargs
    ) -> Dict[str, Any]:
        """
        执行带重试的操作

        Args:
            operation: 要执行的异步操作
            operation_name: 操作名称（用于日志）
            **kwargs: 传递给操作的额外参数

        Returns:
            操作结果
        """
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"执行操作: {operation_name} (尝试 {attempt}/{self.max_retries})")
                result = await operation(**kwargs)

                # 检查结果是否成功
                if isinstance(result, dict) and result.get("success", True):
                    logger.info(f"操作成功: {operation_name}")
                    return result
                elif isinstance(result, dict) and not result.get("success"):
                    # 操作失败，检查错误是否可重试
                    error_code = result.get("error_code")
                    if error_code and is_retryable_error(error_code):
                        logger.warning(f"操作失败，可重试: {result.get('error', '未知错误')}")
                        if attempt < self.max_retries:
                            delay = self._calculate_delay(attempt)
                            logger.info(f"等待 {delay:.2f} 秒后重试")
                            await asyncio.sleep(delay)
                            continue
                    else:
                        logger.error(f"操作失败，不可重试: {result.get('error', '未知错误')}")
                    return result
                else:
                    # 非字典结果，视为成功
                    logger.info(f"操作成功: {operation_name}")
                    return {"success": True, "result": result}

            except AuthError as e:
                # 授权错误
                last_error = e
                error_code = e.error_code

                if is_retryable_error(error_code):
                    logger.warning(f"操作异常，可重试: {str(e)}")
                    if attempt < self.max_retries:
                        delay = self._calculate_delay(attempt)
                        logger.info(f"等待 {delay:.2f} 秒后重试")
                        await asyncio.sleep(delay)
                        continue
                else:
                    logger.error(f"操作异常，不可重试: {str(e)}")
                    return {"success": False, "error": str(e), "error_code": error_code}

            except Exception as e:
                # 其他异常
                last_error = e
                logger.error(f"操作异常: {str(e)}")

                # 网络相关异常视为可重试
                error_str = str(e).lower()
                if any(keyword in error_str for keyword in ["network", "timeout", "connection"]):
                    if attempt < self.max_retries:
                        delay = self._calculate_delay(attempt)
                        logger.info(f"等待 {delay:.2f} 秒后重试")
                        await asyncio.sleep(delay)
                        continue

                return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}

        # 所有重试都失败
        if last_error:
            logger.error(f"操作最终失败: {operation_name}, 错误: {str(last_error)}")
            error_code = getattr(last_error, "error_code", "INTERNAL_ERROR")
            return {"success": False, "error": str(last_error), "error_code": error_code}
        else:
            logger.error(f"操作最终失败: {operation_name}, 未知错误")
            return {"success": False, "error": "未知错误", "error_code": "INTERNAL_ERROR"}

    def _calculate_delay(self, attempt: int) -> float:
        """
        计算重试延迟

        Args:
            attempt: 重试次数

        Returns:
            延迟时间（秒）
        """
        # 指数退避 + 抖动
        delay = min(self.base_delay * (self.backoff_factor ** (attempt - 1)), self.max_delay)
        # 添加 0-1 秒的随机抖动
        jitter = random.uniform(0, 1.0)
        return delay + jitter


# 默认重试策略实例
default_retry_strategy = RetryStrategy()


async def retry_operation(
    operation: Callable[[], Awaitable[Any]], operation_name: str, strategy: RetryStrategy = None, **kwargs
) -> Dict[str, Any]:
    """
    使用重试策略执行操作的便捷函数

    Args:
        operation: 要执行的异步操作
        operation_name: 操作名称
        strategy: 重试策略（可选，默认使用默认策略）
        **kwargs: 传递给操作的额外参数

    Returns:
        操作结果
    """
    if strategy is None:
        strategy = default_retry_strategy

    return await strategy.execute_with_retry(operation=operation, operation_name=operation_name, **kwargs)
