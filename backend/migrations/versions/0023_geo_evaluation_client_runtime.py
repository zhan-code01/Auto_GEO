"""Add local-client runtime fields to GEO evaluation runs.

Revision ID: 0023_geo_evaluation_client_runtime
Revises: 0022_add_client_location
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_geo_evaluation_client_runtime"
down_revision = "0022_add_client_location"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "geo_evaluation_runs",
        sa.Column("claimed_device_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "geo_evaluation_runs",
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "geo_evaluation_runs",
        sa.Column("interruption_reason", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_geo_evaluation_runs_claimed_device_id",
        "geo_evaluation_runs",
        ["claimed_device_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_geo_evaluation_runs_claimed_device_id", table_name="geo_evaluation_runs")
    op.drop_column("geo_evaluation_runs", "interruption_reason")
    op.drop_column("geo_evaluation_runs", "heartbeat_at")
    op.drop_column("geo_evaluation_runs", "claimed_device_id")
