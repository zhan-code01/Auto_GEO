"""Excel batch per-project article_count column.

为 article_generation_batches 增加 ``article_count``（每项目生成篇数）。

背景：批量生成第 4 步用户设定的「每项目 N 篇」原未持久化，execute_batch 用
_excel 行的 article_count（默认 5）推导每项目篇数，导致用户设 1 篇仍生成 5 篇。
本列持久化用户设定值，execute_batch 据此为每项目蒸馏问题。

0010 已建表但无此列；对已应用 0010/0011 的库由本迁移通过幂等 _add_column_if_missing
补列。SQLite legacy 由 create_all / fix_database.py 兜底。

Revision ID: 0012_excel_batch_article_count
Revises: 0011_excel_job_retry_columns
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0012_excel_batch_article_count"
down_revision = "0011_excel_job_retry_columns"
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
        "article_generation_batches",
        "article_count",
        sa.Column("article_count", sa.Integer(), server_default="5", nullable=False),
    )


def downgrade():
    # 谨慎起见不自动 drop 业务列，避免误删数据；如需回滚请手动处理。
    pass
