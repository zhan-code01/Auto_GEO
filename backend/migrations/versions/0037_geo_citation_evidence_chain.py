"""Add citation evidence-chain fields to GEO evaluation records.

Revision ID: 0037_geo_citation_evidence_chain
Revises: 0036_client_devices_multi_account

背景：引用证据链修复（AutoGEO优化方案_2026-09 优化项六 P0）。
旧 worker 把 citations 写死为 []，导致「未采集」「抓取成功但零条」「抓取异常」
在落库后被 bool() 抹平，cited_domains 不可信。本次为 geo_evaluation_records
补齐两个证据元数据字段：

  - citation_status  ：三态（captured/empty/unavailable/not_supported），
                       存量行回填 NULL 表示「历史数据未标注引用状态」。
  - capture_method    ：采集方式（clipboard/dom/dom-visible-candidate/network/…），
                       worker 已在请求体传该方法，但此前无列承接、被丢弃。

先库后码：先迁移，后改模型/worker/判卷/聚合。降级脚本删除两列（可逆）。
"""

from alembic import op
import sqlalchemy as sa


revision = "0037_geo_citation_evidence_chain"
down_revision = "0036_client_devices_multi_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_evaluation_records",
        sa.Column(
            "citation_status",
            sa.String(length=20),
            nullable=True,
            comment="引用状态：captured/empty/unavailable/not_supported",
        ),
    )
    op.add_column(
        "geo_evaluation_records",
        sa.Column(
            "capture_method",
            sa.String(length=30),
            nullable=True,
            comment="回答/引用采集方式：clipboard/dom/dom-visible-candidate/network 等",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_evaluation_records", "capture_method")
    op.drop_column("geo_evaluation_records", "citation_status")
