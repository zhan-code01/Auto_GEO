"""Bind a GEO evaluation run to one authorized account.

Revision ID: 0024_geo_evaluation_account_binding
Revises: 0023_geo_evaluation_client_runtime
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_geo_evaluation_account_binding"
down_revision = "0023_geo_evaluation_client_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("geo_evaluation_runs", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_index("ix_geo_evaluation_runs_account_id", "geo_evaluation_runs", ["account_id"])
    op.create_foreign_key(
        "fk_geo_evaluation_runs_account_id",
        "geo_evaluation_runs",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_geo_evaluation_runs_account_id", "geo_evaluation_runs", type_="foreignkey")
    op.drop_index("ix_geo_evaluation_runs_account_id", table_name="geo_evaluation_runs")
    op.drop_column("geo_evaluation_runs", "account_id")
