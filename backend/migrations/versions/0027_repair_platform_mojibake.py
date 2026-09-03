"""Repair legacy mojibake in AI platform account names.

Revision ID: 0027_repair_platform_mojibake
Revises: 0026_smart_article_question_pool
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_repair_platform_mojibake"
down_revision = "0026_smart_article_question_pool"
branch_labels = None
depends_on = None


ACCOUNT_NAME_REPAIRS = {
    "璞嗗寘账号": "豆包账号",
    "閫氫箟鍗冮棶账号": "通义千问账号",
}


def upgrade() -> None:
    accounts = sa.table(
        "accounts",
        sa.column("account_name", sa.String(length=100)),
    )
    for broken, repaired in ACCOUNT_NAME_REPAIRS.items():
        op.execute(accounts.update().where(accounts.c.account_name == broken).values(account_name=repaired))


def downgrade() -> None:
    accounts = sa.table(
        "accounts",
        sa.column("account_name", sa.String(length=100)),
    )
    for broken, repaired in ACCOUNT_NAME_REPAIRS.items():
        op.execute(accounts.update().where(accounts.c.account_name == repaired).values(account_name=broken))
