# -*- coding: utf-8 -*-
"""验证 AsyncPostgresSaver 的导入和基本 API。"""
import asyncio

async def main():
    # 测试导入
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        print("OK: AsyncPostgresSaver 导入成功")
    except ImportError as e:
        print(f"FAIL: AsyncPostgresSaver 导入失败: {e}")
        # 尝试其他路径
        try:
            from langgraph.checkpoint.postgres import AsyncPostgresSaver
            print("OK: AsyncPostgresSaver 从 postgres 模块导入成功")
        except ImportError as e2:
            print(f"FAIL: 备选路径也失败: {e2}")
            return

    # 测试 AsyncConnectionPool 导入
    try:
        from psycopg_pool import AsyncConnectionPool
        print("OK: AsyncConnectionPool 导入成功")
    except ImportError as e:
        print(f"FAIL: AsyncConnectionPool 导入失败: {e}")
        return

    # 检查 AsyncPostgresSaver 的方法
    print("\nAsyncPostgresSaver 方法:")
    for method in ["setup", "aget_state", "aput", "aget_tuple"]:
        has_method = hasattr(AsyncPostgresSaver, method)
        is_async = asyncio.iscoroutinefunction(getattr(AsyncPostgresSaver, method, None))
        print(f"  {method}: exists={has_method}, async={is_async}")

asyncio.run(main())
