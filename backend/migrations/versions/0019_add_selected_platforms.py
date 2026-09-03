"""Add selected_platforms and baseline_platforms to projects.

Revision ID: 0019_add_selected_platforms
Revises: 0018_geo_evaluation_tables
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_add_selected_platforms"
down_revision = "0018_geo_evaluation_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects",
        sa.Column("selected_platforms", sa.JSON(), nullable=True, comment="收录监控选中的AI平台列表"),
    )
    op.add_column(
        "projects",
        sa.Column("baseline_platforms", sa.JSON(), nullable=True, comment="基线建立时实际使用的AI平台列表"),
    )
    op.create_index(
        "ix_projects_baseline_at",
        "projects",
        ["baseline_at"],
        if_not_exists=True,
    )


def downgrade():
    op.drop_index("ix_projects_baseline_at", table_name="projects", if_exists=True)
    op.drop_column("projects", "baseline_platforms")
    op.drop_column("projects", "selected_platforms")
