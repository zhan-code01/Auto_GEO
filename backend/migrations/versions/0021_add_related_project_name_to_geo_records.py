"""Add related_project_name to GEO evaluation records.

Revision ID: 0021_add_related_project_name_to_geo_records
Revises: 0020_add_client_id_to_geo_tables
Create Date: 2026-06-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_add_related_project_name_to_geo_records"
down_revision = "0020_add_client_id_to_geo_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "geo_evaluation_records",
        sa.Column("related_project_name", sa.String(length=500), nullable=True),
    )


def downgrade():
    op.drop_column("geo_evaluation_records", "related_project_name")
