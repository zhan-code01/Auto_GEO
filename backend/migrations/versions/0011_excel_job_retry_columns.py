"""Excel batch job retry columns.

为 article_generation_jobs 增加 job 重试字段（文档 §6.3）：
- max_attempts：最大尝试次数（含首次），默认 2
- last_error_at：最后错误时间

0010 已把 attempt_count 加入建表语句，但本期才补这两个列；对已应用 0010 的库
由本迁移通过幂等 _add_column_if_missing 补列。SQLite legacy 由 create_all / fix_database.py 兜底。

Revision ID: 0011_excel_job_retry_columns
Revises: 0010_excel_article_generation
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0011_excel_job_retry_columns"
down_revision = "0010_excel_article_generation"
branch_labels = None
depends_on = None


def _table_exists(table_name):
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name, column_name, column):
    if _table_exists(table_name) and not _column_exists(table_name, column_name):
        op.add_column(table_name, column)


def upgrade():
    _add_column_if_missing(
        "article_generation_jobs",
        "max_attempts",
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=True),
    )
    _add_column_if_missing(
        "article_generation_jobs",
        "last_error_at",
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    # 谨慎起见不自动 drop 业务列，避免误删数据；如需回滚请手动处理。
    pass
