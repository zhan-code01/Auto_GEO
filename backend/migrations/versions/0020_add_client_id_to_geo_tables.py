# -*- coding: utf-8 -*-
"""
Add client_id to GEO evaluation tables.

Add question_distribution to geo_prompt_sets (stores the 50/20/20/5/5 question type distribution).
Add related_project_name to geo_prompts (which project this question relates to).

Revision ID: 0020_add_client_id_to_geo_tables
Revises: 0019_add_selected_platforms
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_add_client_id_to_geo_tables"
down_revision = "0019_add_selected_platforms"
branch_labels = None
depends_on = None


def upgrade():
    # 1. geo_prompt_sets: add client_id + question_distribution
    op.add_column(
        "geo_prompt_sets",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column(
        "geo_prompt_sets",
        sa.Column("question_distribution", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_geo_prompt_sets_client_id", "geo_prompt_sets", ["client_id"], if_not_exists=True,
    )
    # Backfill client_id from project.client_id for existing rows
    op.execute("""
        UPDATE geo_prompt_sets
        SET client_id = (
            SELECT p.client_id
            FROM projects p
            WHERE p.id = geo_prompt_sets.project_id
            LIMIT 1
        )
        WHERE client_id IS NULL
    """)

    # 2. geo_prompts: add client_id + related_project_name
    op.add_column(
        "geo_prompts",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column(
        "geo_prompts",
        sa.Column("related_project_name", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_geo_prompts_client_id", "geo_prompts", ["client_id"], if_not_exists=True,
    )
    # Backfill client_id from geo_prompt_sets.client_id
    op.execute("""
        UPDATE geo_prompts
        SET client_id = (
            SELECT gps.client_id
            FROM geo_prompt_sets gps
            WHERE gps.id = geo_prompts.prompt_set_id
            LIMIT 1
        )
        WHERE client_id IS NULL
    """)

    # 3. geo_evaluation_runs: add client_id
    op.add_column(
        "geo_evaluation_runs",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index(
        "ix_geo_evaluation_runs_client_id", "geo_evaluation_runs", ["client_id"], if_not_exists=True,
    )
    # Backfill from project
    op.execute("""
        UPDATE geo_evaluation_runs
        SET client_id = (
            SELECT p.client_id
            FROM projects p
            WHERE p.id = geo_evaluation_runs.project_id
            LIMIT 1
        )
        WHERE client_id IS NULL
    """)

    # 4. geo_evaluation_records: add client_id
    op.add_column(
        "geo_evaluation_records",
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index(
        "ix_geo_evaluation_records_client_id", "geo_evaluation_records", ["client_id"], if_not_exists=True,
    )
    # Backfill from run
    op.execute("""
        UPDATE geo_evaluation_records
        SET client_id = (
            SELECT ger.client_id
            FROM geo_evaluation_runs ger
            WHERE ger.id = geo_evaluation_records.run_id
            LIMIT 1
        )
        WHERE client_id IS NULL
    """)

    # 5. Company-level GEO evaluation can be created without a specific project.
    # Existing 0018 tables required project_id, so relax those constraints to match
    # the current ORM model and client-level API behavior.
    op.alter_column("geo_prompt_sets", "project_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("geo_prompts", "project_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("geo_evaluation_runs", "project_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("geo_evaluation_records", "project_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.alter_column("geo_evaluation_records", "project_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("geo_evaluation_runs", "project_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("geo_prompts", "project_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("geo_prompt_sets", "project_id", existing_type=sa.Integer(), nullable=False)

    # Drop client_id indexes and columns (reverse order)
    op.drop_index("ix_geo_evaluation_records_client_id", table_name="geo_evaluation_records", if_exists=True)
    op.drop_column("geo_evaluation_records", "client_id")

    op.drop_index("ix_geo_evaluation_runs_client_id", table_name="geo_evaluation_runs", if_exists=True)
    op.drop_column("geo_evaluation_runs", "client_id")

    op.drop_column("geo_prompts", "related_project_name")
    op.drop_index("ix_geo_prompts_client_id", table_name="geo_prompts", if_exists=True)
    op.drop_column("geo_prompts", "client_id")

    op.drop_column("geo_prompt_sets", "question_distribution")
    op.drop_index("ix_geo_prompt_sets_client_id", table_name="geo_prompt_sets", if_exists=True)
    op.drop_column("geo_prompt_sets", "client_id")
