"""
SiteProject AI generation fields.

为 site_projects 表添加 AI 网页生成所需的字段：
- source: 生成方式（manual=手填 ai=AI生成）
- structured_data: AI 提取的结构化企业数据 JSON
- client_id: 关联客户ID
- template_id: 使用的模板ID

Revision ID: 0015_siteproject_ai_fields
Revises: 0014_knowledge_category_client_cascade
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0015_siteproject_ai_fields"
down_revision = "0014_knowledge_category_client_cascade"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [c["name"] for c in inspector.get_columns(table_name)]


def upgrade():
    # SQLite/PostgreSQL 都支持 ADD COLUMN（幂等：先检查列是否存在）
    if not _column_exists("site_projects", "source"):
        op.add_column(
            "site_projects",
            sa.Column("source", sa.String(20), server_default="manual",
                      comment="生成方式：manual=手填 ai=AI生成"),
        )
    if not _column_exists("site_projects", "structured_data"):
        op.add_column(
            "site_projects",
            sa.Column("structured_data", sa.JSON, nullable=True,
                      comment="AI 提取的结构化企业数据"),
        )
    if not _column_exists("site_projects", "client_id"):
        op.add_column(
            "site_projects",
            sa.Column("client_id", sa.Integer,
                      sa.ForeignKey("clients.id", ondelete="SET NULL"),
                      nullable=True, comment="关联客户ID（AI生成时来源）"),
        )
    if not _column_exists("site_projects", "template_id"):
        op.add_column(
            "site_projects",
            sa.Column("template_id", sa.String(50), server_default="tech",
                      comment="使用的模板ID"),
        )


def downgrade():
    for col in ["template_id", "client_id", "structured_data", "source"]:
        if _column_exists("site_projects", col):
            op.drop_column("site_projects", col)
