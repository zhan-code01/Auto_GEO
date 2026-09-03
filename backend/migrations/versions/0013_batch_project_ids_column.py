"""Batch project_ids column for cross-project generation.

为 article_generation_batches 增加 ``project_ids``（JSON 数组），用于 Agent「每个项目各生成
N 篇」这种**非 Excel** 的跨项目批量生成：一个批次可覆盖多个 project_id，每项目的 job 仍按
``article_count`` 蒸馏问题。模型本就为「多项目由 job 讗录」设计，本列补齐来源列表，使后台
``execute_batch`` 能重新推导生成计划（与 Excel ``import_batch_id`` 路径并列）。

对已应用 0010~0012 的库由本迁移通过幂等 ``_add_column_if_missing`` 补列；SQLite legacy 由
create_all / fix_database.py 兜底。

Revision ID: 0013_batch_project_ids_column
Revises: 0012_excel_batch_article_count
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0013_batch_project_ids_column"
down_revision = "0012_excel_batch_article_count"
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
        "project_ids",
        sa.Column("project_ids", sa.JSON(), nullable=True),
    )


def downgrade():
    # 谨慎起见不自动 drop 业务列，避免误删数据；如需回滚请手动处理。
    pass
