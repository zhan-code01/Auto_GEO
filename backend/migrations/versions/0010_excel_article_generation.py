"""Excel batch article generation.

新增后台智能体 Excel 批量文章生成所需表与列：
- agent_excel_import_batches / agent_excel_import_rows：Excel 导入批次与行
- article_generation_batches / article_generation_jobs：批量生成批次与任务
- client_content_profiles：从资料抽取的客户内容画像
- geo_articles 增加 source / generation_batch_id（文章管理来源/批次筛选）

SQLite legacy 环境由 create_all 自动建表；PostgreSQL 由本迁移管理。
fix_database.py 同步了 geo_articles 新列（SQLite 缺列兜底）。

Revision ID: 0010_excel_article_generation
Revises: 0009_reconcile_remaining_cols
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0010_excel_article_generation"
down_revision = "0009_reconcile_remaining_cols"
branch_labels = None
depends_on = None


# ==================== 幂等 helper（与 0009 风格一致）====================


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
    # SQLite / 其它：查 sqlite_master
    result = bind.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:name"),
        {"name": index_name},
    )
    return result.fetchone() is not None


def _add_column_if_missing(table_name, column_name, column):
    if _table_exists(table_name) and not _column_exists(table_name, column_name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name, table_name, columns, unique=False):
    if _table_exists(table_name) and not _index_exists(index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


# ==================== upgrade / downgrade ====================


def upgrade():
    # ---- agent_excel_import_batches ----
    if not _table_exists("agent_excel_import_batches"):
        op.create_table(
            "agent_excel_import_batches",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("file_name", sa.String(length=500), nullable=True),
            sa.Column("file_hash", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("total_rows", sa.Integer(), nullable=True),
            sa.Column("valid_rows", sa.Integer(), nullable=True),
            sa.Column("invalid_rows", sa.Integer(), nullable=True),
            sa.Column("default_article_count", sa.Integer(), nullable=True),
            sa.Column("field_mapping", sa.JSON(), nullable=True),
            sa.Column("error_report", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing("ix_agent_excel_import_batches_user_id", "agent_excel_import_batches", ["user_id"])
    _create_index_if_missing("ix_agent_excel_import_batches_file_hash", "agent_excel_import_batches", ["file_hash"])

    # ---- agent_excel_import_rows ----
    if not _table_exists("agent_excel_import_rows"):
        op.create_table(
            "agent_excel_import_rows",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "batch_id",
                sa.Integer(),
                sa.ForeignKey("agent_excel_import_batches.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("row_index", sa.Integer(), nullable=False),
            sa.Column("raw_data", sa.JSON(), nullable=True),
            sa.Column("normalized_data", sa.JSON(), nullable=True),
            sa.Column("client_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("error_msg", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        )
    _create_index_if_missing("ix_agent_excel_import_rows_batch_id", "agent_excel_import_rows", ["batch_id"])
    _create_index_if_missing("ix_agent_excel_import_rows_client_id", "agent_excel_import_rows", ["client_id"])
    _create_index_if_missing("ix_agent_excel_import_rows_project_id", "agent_excel_import_rows", ["project_id"])

    # ---- article_generation_batches ----
    if not _table_exists("article_generation_batches"):
        op.create_table(
            "article_generation_batches",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column(
                "import_batch_id",
                sa.Integer(),
                sa.ForeignKey("agent_excel_import_batches.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String(length=30), nullable=True),
            sa.Column("requested_count", sa.Integer(), nullable=True),
            sa.Column("queued_count", sa.Integer(), nullable=True),
            sa.Column("success_count", sa.Integer(), nullable=True),
            sa.Column("failed_count", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing("ix_article_generation_batches_user_id", "article_generation_batches", ["user_id"])
    _create_index_if_missing(
        "ix_article_generation_batches_import_batch_id", "article_generation_batches", ["import_batch_id"]
    )
    _create_index_if_missing("ix_article_generation_batches_project_id", "article_generation_batches", ["project_id"])

    # ---- article_generation_jobs ----
    if not _table_exists("article_generation_jobs"):
        op.create_table(
            "article_generation_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "batch_id",
                sa.Integer(),
                sa.ForeignKey("article_generation_batches.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("keyword_id", sa.Integer(), sa.ForeignKey("keywords.id", ondelete="SET NULL"), nullable=True),
            sa.Column("article_id", sa.Integer(), nullable=True),
            sa.Column("idempotency_key", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=True),
            sa.Column("max_attempts", sa.Integer(), nullable=True),
            sa.Column("error_msg", sa.Text(), nullable=True),
            sa.Column("last_error_at", sa.DateTime(), nullable=True),
            sa.Column("queued_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing("ix_article_generation_jobs_batch_id", "article_generation_jobs", ["batch_id"])
    _create_index_if_missing("ix_article_generation_jobs_user_id", "article_generation_jobs", ["user_id"])
    _create_index_if_missing("ix_article_generation_jobs_project_id", "article_generation_jobs", ["project_id"])
    _create_index_if_missing("ix_article_generation_jobs_keyword_id", "article_generation_jobs", ["keyword_id"])
    _create_index_if_missing("ix_article_generation_jobs_article_id", "article_generation_jobs", ["article_id"])
    _create_index_if_missing(
        "ix_article_generation_jobs_idempotency_key", "article_generation_jobs", ["idempotency_key"]
    )

    # job 重试字段（max_attempts / last_error_at）—— 兼容已被 create_table 建好的旧库
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

    # ---- client_content_profiles ----
    if not _table_exists("client_content_profiles"):
        op.create_table(
            "client_content_profiles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String(length=30), nullable=True),
            sa.Column("profile_json", sa.JSON(), nullable=True),
            sa.Column("confidence_json", sa.JSON(), nullable=True),
            sa.Column("source_document_ids", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        )
    _create_index_if_missing("ix_client_content_profiles_user_id", "client_content_profiles", ["user_id"])
    _create_index_if_missing("ix_client_content_profiles_client_id", "client_content_profiles", ["client_id"])
    _create_index_if_missing("ix_client_content_profiles_project_id", "client_content_profiles", ["project_id"])

    # ---- geo_articles 新增列（文章管理来源/批次筛选）----
    _add_column_if_missing(
        "geo_articles",
        "source",
        sa.Column("source", sa.String(length=30), server_default="manual", nullable=True),
    )
    _add_column_if_missing(
        "geo_articles",
        "generation_batch_id",
        sa.Column("generation_batch_id", sa.Integer(), nullable=True),
    )
    _create_index_if_missing("ix_geo_articles_generation_batch_id", "geo_articles", ["generation_batch_id"])


def downgrade():
    # 谨慎起见不自动 drop 业务表，避免误删数据；如需回滚请手动处理。
    pass
