"""Add website column to clients table.

Revision ID: 0032_add_client_website
Revises: 0031_yxer_local_bindings_and_record_extension
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_add_client_website"
down_revision = "0031_yxer_local_bindings_and_record_extension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("website", sa.String(length=500), nullable=True, comment="公司官网"))


def downgrade() -> None:
    op.drop_column("clients", "website")
