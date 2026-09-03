"""Add user_agent_facts table for Agent V2 long-term memory.

Revision ID: 0033_user_agent_facts
Revises: 0032_add_client_website
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_user_agent_facts"
down_revision = "0032_add_client_website"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_agent_facts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "system_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
            comment="系统用户ID（一人一条）",
        ),
        sa.Column("facts", sa.JSON(), nullable=True, comment="用户长期事实 JSON"),
        sa.Column(
            "onboarding_stage",
            sa.String(50),
            nullable=True,
            comment="引导流程当前阶段",
        ),
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            default=False,
            nullable=False,
            server_default=sa.text("false"),
            comment="引导是否已完成",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        comment="Agent V2 用户长期事实表",
    )


def downgrade() -> None:
    op.drop_table("user_agent_facts")
