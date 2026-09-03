"""Add client location for GEO prompt region expansion.

Revision ID: 0022_add_client_location
Revises: 0021_add_related_project_name_to_geo_records
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_add_client_location"
down_revision = "0021_add_related_project_name_to_geo_records"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "clients",
        sa.Column("location", sa.String(length=100), nullable=True, comment="公司所在地，用于GEO测评地域扩展"),
    )


def downgrade():
    op.drop_column("clients", "location")
