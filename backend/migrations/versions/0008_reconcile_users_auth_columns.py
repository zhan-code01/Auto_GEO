"""Reconcile users auth columns for PostgreSQL.

Revision ID: 0008_reconcile_users_auth
Revises: 0007_reconcile_postgresql_schema
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0008_reconcile_users_auth"
down_revision = "0007_reconcile_postgresql_schema"
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

    inspector = sa_inspect(bind)
    for table_name in inspector.get_table_names():
        if index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}:
            return True
    return False


def _add_column_if_missing(table_name, column_name, column):
    if not _column_exists(table_name, column_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name, table_name, columns, unique=False):
    if not _index_exists(index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    if not _table_exists("users"):
        return

    _add_column_if_missing(
        "users",
        "role",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )
    _add_column_if_missing(
        "users",
        "is_active",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add_column_if_missing(
        "users",
        "status",
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column_if_missing(
        "users",
        "last_login",
        sa.Column("last_login", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "users",
        "login_count",
        sa.Column("login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "users",
        "failed_login_attempts",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "users",
        "locked_until",
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )

    _create_index_if_missing("ix_users_role", "users", ["role"])
    _create_index_if_missing("ix_users_is_active", "users", ["is_active"])
    _create_index_if_missing("ix_users_status", "users", ["status"])
    _create_index_if_missing("ix_users_last_login", "users", ["last_login"])


def downgrade():
    # This reconciliation migration is intentionally conservative. Do not drop
    # auth columns automatically because existing code may depend on them.
    pass
