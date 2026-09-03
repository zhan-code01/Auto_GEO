"""GEO five-metric evaluation tables.

Revision ID: 0018_geo_evaluation_tables
Revises: 0017_publish_approval_and_quota
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_geo_evaluation_tables"
down_revision = "0017_publish_approval_and_quota"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "geo_prompt_sets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("question_count", sa.Integer(), server_default="10", nullable=True),
        sa.Column("generation_model", sa.String(length=100), nullable=True),
        sa.Column("generation_prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("frozen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_geo_prompt_sets_project_id", "geo_prompt_sets", ["project_id"], if_not_exists=True)

    op.create_table(
        "geo_prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prompt_set_id", sa.Integer(), sa.ForeignKey("geo_prompt_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(length=30), server_default="recommendation", nullable=False),
        sa.Column("intent_tags", sa.JSON(), nullable=True),
        sa.Column("competitor_names", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_geo_prompts_prompt_set_id", "geo_prompts", ["prompt_set_id"], if_not_exists=True)
    op.create_index("ix_geo_prompts_project_id", "geo_prompts", ["project_id"], if_not_exists=True)

    op.create_table(
        "geo_evaluation_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_set_id", sa.Integer(), sa.ForeignKey("geo_prompt_sets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("platforms", sa.JSON(), nullable=True),
        sa.Column("rounds", sa.Integer(), server_default="1", nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=True),
        sa.Column("total_planned", sa.Integer(), server_default="0", nullable=True),
        sa.Column("total_completed", sa.Integer(), server_default="0", nullable=True),
        sa.Column("total_failed", sa.Integer(), server_default="0", nullable=True),
        sa.Column("current_platform", sa.String(length=50), nullable=True),
        sa.Column("current_round", sa.Integer(), nullable=True),
        sa.Column("current_progress", sa.Integer(), server_default="0", nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("evaluation_schema_version", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_geo_evaluation_runs_project_id", "geo_evaluation_runs", ["project_id"], if_not_exists=True)
    op.create_index("ix_geo_evaluation_runs_prompt_set_id", "geo_evaluation_runs", ["prompt_set_id"], if_not_exists=True)

    op.create_table(
        "geo_evaluation_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("geo_evaluation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_set_id", sa.Integer(), sa.ForeignKey("geo_prompt_sets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("geo_prompts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("round_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("raw_citations", sa.JSON(), nullable=True),
        sa.Column("context_cleaned", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("success", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("brand_mentioned", sa.Boolean(), nullable=True),
        sa.Column("matched_names", sa.JSON(), nullable=True),
        sa.Column("is_recommended", sa.Boolean(), nullable=True),
        sa.Column("recommendation_rank", sa.Integer(), nullable=True),
        sa.Column("ranking_score", sa.Float(), nullable=True),
        sa.Column("citation_supported", sa.Boolean(), nullable=True),
        sa.Column("own_source_cited", sa.Boolean(), nullable=True),
        sa.Column("cited_urls", sa.JSON(), nullable=True),
        sa.Column("cited_domains", sa.JSON(), nullable=True),
        sa.Column("sentiment", sa.String(length=30), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("visibility_score", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("judge_model", sa.String(length=100), nullable=True),
        sa.Column("judge_raw_output", sa.JSON(), nullable=True),
        sa.Column("schema_version", sa.String(length=20), nullable=True),
        sa.Column("asked_at", sa.DateTime(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_geo_evaluation_records_run_id", "geo_evaluation_records", ["run_id"], if_not_exists=True)
    op.create_index("ix_geo_evaluation_records_project_id", "geo_evaluation_records", ["project_id"], if_not_exists=True)
    op.create_index("ix_geo_evaluation_records_prompt_set_id", "geo_evaluation_records", ["prompt_set_id"], if_not_exists=True)
    op.create_index("ix_geo_evaluation_records_prompt_id", "geo_evaluation_records", ["prompt_id"], if_not_exists=True)
    op.create_index("ix_geo_evaluation_records_platform", "geo_evaluation_records", ["platform"], if_not_exists=True)


def downgrade():
    op.drop_index("ix_geo_evaluation_records_platform", table_name="geo_evaluation_records", if_exists=True)
    op.drop_index("ix_geo_evaluation_records_prompt_id", table_name="geo_evaluation_records", if_exists=True)
    op.drop_index("ix_geo_evaluation_records_prompt_set_id", table_name="geo_evaluation_records", if_exists=True)
    op.drop_index("ix_geo_evaluation_records_project_id", table_name="geo_evaluation_records", if_exists=True)
    op.drop_index("ix_geo_evaluation_records_run_id", table_name="geo_evaluation_records", if_exists=True)
    op.drop_table("geo_evaluation_records", if_exists=True)
    op.drop_index("ix_geo_evaluation_runs_prompt_set_id", table_name="geo_evaluation_runs", if_exists=True)
    op.drop_index("ix_geo_evaluation_runs_project_id", table_name="geo_evaluation_runs", if_exists=True)
    op.drop_table("geo_evaluation_runs", if_exists=True)
    op.drop_index("ix_geo_prompts_project_id", table_name="geo_prompts", if_exists=True)
    op.drop_index("ix_geo_prompts_prompt_set_id", table_name="geo_prompts", if_exists=True)
    op.drop_table("geo_prompts", if_exists=True)
    op.drop_index("ix_geo_prompt_sets_project_id", table_name="geo_prompt_sets", if_exists=True)
    op.drop_table("geo_prompt_sets", if_exists=True)
