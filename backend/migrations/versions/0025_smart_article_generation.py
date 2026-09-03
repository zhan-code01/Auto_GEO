"""Add independent smart article generation batches and jobs.

Revision ID: 0025_smart_article_generation
Revises: 0024_geo_evaluation_account_binding
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_smart_article_generation"
down_revision = "0024_geo_evaluation_account_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smart_article_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="auto"),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("input_question", sa.Text(), nullable=True),
        sa.Column("question_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("filter_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("query_rewrite_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("article_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_smart_article_batches_user_id", "smart_article_batches", ["user_id"])
    op.create_index("ix_smart_article_batches_project_id", "smart_article_batches", ["project_id"])
    op.create_index("ix_smart_article_batches_status", "smart_article_batches", ["status"])

    op.create_table(
        "smart_article_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("intent_type", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("context_type", sa.String(length=20), nullable=False, server_default="general"),
        sa.Column("brand_entry_reason", sa.Text(), nullable=True),
        sa.Column("retrieval_terms", sa.JSON(), nullable=True),
        sa.Column("initial_queries", sa.JSON(), nullable=True),
        sa.Column("retrieval_queries", sa.JSON(), nullable=True),
        sa.Column("retrieval_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("query_rewrite_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("query_rewrite_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("retrieval_raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieval_valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("knowledge_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("knowledge_refs", sa.JSON(), nullable=True),
        sa.Column("keyword_id", sa.Integer(), nullable=True),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["smart_article_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("idempotency_key", name="uq_smart_article_jobs_idempotency_key"),
    )
    op.create_index("ix_smart_article_jobs_batch_id", "smart_article_jobs", ["batch_id"])
    op.create_index("ix_smart_article_jobs_user_id", "smart_article_jobs", ["user_id"])
    op.create_index("ix_smart_article_jobs_project_id", "smart_article_jobs", ["project_id"])
    op.create_index("ix_smart_article_jobs_keyword_id", "smart_article_jobs", ["keyword_id"])
    op.create_index("ix_smart_article_jobs_article_id", "smart_article_jobs", ["article_id"])
    op.create_index("ix_smart_article_jobs_status", "smart_article_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_smart_article_jobs_status", table_name="smart_article_jobs")
    op.drop_index("ix_smart_article_jobs_article_id", table_name="smart_article_jobs")
    op.drop_index("ix_smart_article_jobs_keyword_id", table_name="smart_article_jobs")
    op.drop_index("ix_smart_article_jobs_project_id", table_name="smart_article_jobs")
    op.drop_index("ix_smart_article_jobs_user_id", table_name="smart_article_jobs")
    op.drop_index("ix_smart_article_jobs_batch_id", table_name="smart_article_jobs")
    op.drop_table("smart_article_jobs")
    op.drop_index("ix_smart_article_batches_status", table_name="smart_article_batches")
    op.drop_index("ix_smart_article_batches_project_id", table_name="smart_article_batches")
    op.drop_index("ix_smart_article_batches_user_id", table_name="smart_article_batches")
    op.drop_table("smart_article_batches")
