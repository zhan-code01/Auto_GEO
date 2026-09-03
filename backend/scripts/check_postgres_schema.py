# -*- coding: utf-8 -*-
"""
PostgreSQL Schema 一致性检查脚本

用途：
  对比 SQLAlchemy ORM 模型 (models.py) 与 PostgreSQL information_schema，
  输出缺失的表和字段。用于部署后验收。

用法：
  # 仅 PostgreSQL 环境有效
  python -m backend.scripts.check_postgres_schema

正常输出示例：
  OK: PostgreSQL schema matches SQLAlchemy models

异常输出示例：
  Missing tables:
    - conversation_sessions

  Missing columns:
    - index_check_records.keyword_count
    - index_check_records.company_count

  EXIT CODE: 1

日志：结果同时写入控制台与 logs/auto_geo_YYYY-MM-DD.log（按日期命名，仅保留 3 天）。
"""

import sys

from loguru import logger


def check_schema():
    """对比 ORM 模型与 PostgreSQL 实际 schema"""
    from backend.config import get_database_type

    db_type = get_database_type()
    if db_type != "postgresql":
        logger.warning(f"SKIP: 当前数据库类型为 {db_type}，此脚本仅用于 PostgreSQL")
        return True

    from sqlalchemy import inspect as sa_inspect, text
    from backend.database import engine, Base

    # 确保所有模型已导入，这样 Base.metadata 才包含全部表
    import backend.database.models  # noqa: F401

    bind = engine
    inspector = sa_inspect(bind)
    logger.info(f"[SchemaCheck] 开始检查: {bind.url}")

    # ========== 1. 获取 ORM 定义的表和列 ==========
    orm_tables = {}
    for table_name, table_obj in Base.metadata.tables.items():
        columns = set()
        for col in table_obj.columns:
            columns.add(col.name)
        orm_tables[table_name] = columns

    # ========== 2. 获取 PostgreSQL 实际的表和列 ==========
    pg_tables = set(inspector.get_table_names())

    pg_columns = {}
    for table_name in pg_tables:
        cols = set()
        for col_info in inspector.get_columns(table_name):
            cols.add(col_info['name'])
        pg_columns[table_name] = cols

    # ========== 3. 对比 ==========
    missing_tables = []
    missing_columns = []

    for table_name, orm_cols in sorted(orm_tables.items()):
        if table_name not in pg_tables:
            missing_tables.append(table_name)
            continue

        actual_cols = pg_columns.get(table_name, set())
        for col_name in sorted(orm_cols):
            if col_name not in actual_cols:
                missing_columns.append(f"{table_name}.{col_name}")

    # ========== 4. 输出结果 ==========
    has_issues = bool(missing_tables or missing_columns)

    if missing_tables:
        logger.error(f"Missing tables ({len(missing_tables)}):")
        for t in missing_tables:
            logger.error(f"  - {t}")

    if missing_columns:
        logger.error(f"Missing columns ({len(missing_columns)}):")
        for c in missing_columns:
            logger.error(f"  - {c}")

    # ========== 5. 汇总统计 ==========
    total_orm_tables = len(orm_tables)
    matched_tables = total_orm_tables - len(missing_tables)
    total_orm_columns = sum(len(cols) for cols in orm_tables.values())
    matched_columns = total_orm_columns - len(missing_columns)

    logger.info(
        f"Summary: {matched_tables}/{total_orm_tables} tables, "
        f"{matched_columns}/{total_orm_columns} columns matched"
    )

    # ========== 6. Alembic 版本检查 ==========
    try:
        with bind.connect() as conn:
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.fetchone()
            if row:
                logger.info(f"Alembic version: {row[0]}")
            else:
                logger.warning("alembic_version table is empty — no migrations have been recorded")
    except Exception as e:
        logger.warning(f"Could not read alembic_version: {e}")

    if not has_issues:
        logger.success("OK: PostgreSQL schema matches SQLAlchemy models")
    else:
        logger.error("Schema 不一致，检查失败")

    return not has_issues


if __name__ == "__main__":
    # 集中式日志初始化：控制台 + 按日期命名的本地日志文件（仅保留最近 3 天）
    from backend.log_setup import setup_logging

    setup_logging()
    try:
        ok = check_schema()
        sys.exit(0 if ok else 1)
    except Exception as e:
        logger.exception(f"Schema 检查异常: {e}")
        sys.exit(2)
