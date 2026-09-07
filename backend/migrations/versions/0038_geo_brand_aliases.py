"""Add GEO brand alias lookup table.

Revision ID: 0038_geo_brand_aliases
Revises: 0037_geo_citation_evidence_chain

背景：份额口径重写（AutoGEO优化方案_2026-09 优化项六 P0 之"补品牌别名表 + 系统性实体归一化"）。
判卷落库的 matched_names 是 LLM 自由文本，缺别名/规范名归一并导致同一品牌多种写法被算成多个实体。
本次新建 geo_brand_aliases（作用域：client/project，双 NULL=全局；含客户级/项目级行），
聚合读时按"精确 alias → canonical_name"归一到规范名。表初始为空，本切片无 CRUD/UI，
行由后续 CRUD 切片写入；未命中表的写法走代码内置文本归一化回退。

先库后码：先迁移，后改模型与聚合。downgrade 删表（可逆）。

注意（唯一性边界）：client_id/project_id 可空；PostgreSQL 下复合唯一把 NULL 视为互不相同，
同一 alias 的多条全局行仍可插入。本次空表无写路径，因此不加 partial unique index；
后续 CRUD 切片上线写入前，须补 WHERE client_id IS NULL AND project_id IS NULL 等 partial unique index。
"""

from alembic import op
import sqlalchemy as sa


revision = "0038_geo_brand_aliases"
down_revision = "0037_geo_citation_evidence_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_brand_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column(
            "client_id",
            sa.Integer(),
            nullable=True,
            comment="作用域：所属公司ID；NULL + project_id 亦 NULL = 全局行",
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            nullable=True,
            comment="作用域：所属项目ID；双 NULL 为全局；不表示 client_id NULL + project_id 非空",
        ),
        sa.Column("alias", sa.String(length=255), nullable=False, comment="原始写法（matched_names/回答中出现的拼写）"),
        sa.Column("canonical_name", sa.String(length=255), nullable=False, comment="归一后的规范品牌名"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alias",
            "client_id",
            "project_id",
            name="uq_geo_brand_aliases_alias_scope",
        ),
    )
    op.create_index("ix_geo_brand_aliases_client_id", "geo_brand_aliases", ["client_id"])
    op.create_index("ix_geo_brand_aliases_project_id", "geo_brand_aliases", ["project_id"])
    op.create_index("ix_geo_brand_aliases_alias", "geo_brand_aliases", ["alias"])


def downgrade() -> None:
    op.drop_index("ix_geo_brand_aliases_alias", table_name="geo_brand_aliases")
    op.drop_index("ix_geo_brand_aliases_project_id", table_name="geo_brand_aliases")
    op.drop_index("ix_geo_brand_aliases_client_id", table_name="geo_brand_aliases")
    op.drop_table("geo_brand_aliases")
