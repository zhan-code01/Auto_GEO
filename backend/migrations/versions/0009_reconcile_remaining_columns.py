"""Reconcile remaining PostgreSQL columns.

Revision ID: 0009_reconcile_remaining_cols
Revises: 0008_reconcile_users_auth
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0009_reconcile_remaining_cols"
down_revision = "0008_reconcile_users_auth"
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


def _index_exists(index_name):
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        result = bind.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
            {"name": index_name},
        )
        return result.fetchone() is not None
    return False


def _add_column_if_missing(table_name, column_name, column):
    if _table_exists(table_name) and not _column_exists(table_name, column_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name, table_name, columns, unique=False):
    if _table_exists(table_name) and not _index_exists(index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    _add_column_if_missing(
        "users",
        "updated_at",
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    _add_column_if_missing(
        "projects",
        "baseline_at",
        sa.Column("baseline_at", sa.DateTime(), nullable=True),
    )
    _create_index_if_missing("ix_projects_baseline_at", "projects", ["baseline_at"])


def downgrade():
    pass
