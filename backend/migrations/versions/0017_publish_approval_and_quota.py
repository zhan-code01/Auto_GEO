"""Publish approval gate + user publish quota tables.

本地客户端发布审批机制（Phase 1：服务器审批式发布）：

1. 新增 publish_approval_logs 表：记录每一次客户端请求审批的结果
   - 谁(user_id)、什么时候(at)、审批哪个任务/记录、什么步骤(checkpoint)、结果(approved)
   - 用于审计、事后追溯、漏单排查
   - 可观测性：客户端显示"服务器拒绝原因"，运营能查到对应日志

2. 新增 user_publish_quotas 表：每用户的发布配额
   - 每日/每月可发布次数上限
   - 已使用次数（运行时累加）
   - 重置日期
   - 套餐级别字段，便于商业化分层

设计原则：
- 审批通过由本表持久化，客户端每次执行关键步骤都先打日志
- 即使服务器宕机也能从这张表审计历史
- 配额查询是 O(1) 主键查找，对客户端每步审批的延迟影响可忽略

Revision ID: 0017_publish_approval_and_quota
Revises: 0016_client_devices_and_publish_routing
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_publish_approval_and_quota"
down_revision = "0016_client_devices_and_publish_routing"
branch_labels = None
depends_on = None


def upgrade():
    # 1. publish_approval_logs 表
    op.create_table(
        "publish_approval_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("auto_publish_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "record_id", sa.Integer(), sa.ForeignKey("auto_publish_records.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("device_id", sa.String(length=64), nullable=True),
        sa.Column(
            "checkpoint",
            sa.String(length=30),
            nullable=False,
            comment="审批检查点: before_write/before_fill_body/before_submit",
        ),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "reason_code",
            sa.String(length=50),
            nullable=True,
            comment="拒绝原因代码: QUOTA_EXCEEDED/PLATFORM_DENIED/DEVICE_OFFLINE/...",
        ),
        sa.Column("reason", sa.String(length=500), nullable=True, comment="拒绝原因描述"),
        sa.Column("approval_token", sa.String(length=100), nullable=True, comment="审批通过时的令牌"),
        sa.Column("expires_at", sa.DateTime(), nullable=True, comment="令牌过期时间"),
        sa.Column("client_ip", sa.String(length=64), nullable=True, comment="客户端 IP（审计用）"),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        comment="发布审批日志表: 每次客户端请求审批都记录一行",
    )
    op.create_index("ix_approval_logs_user_id", "publish_approval_logs", ["user_id"], if_not_exists=True)
    op.create_index("ix_approval_logs_task_id", "publish_approval_logs", ["task_id"], if_not_exists=True)
    op.create_index("ix_approval_logs_record_id", "publish_approval_logs", ["record_id"], if_not_exists=True)
    op.create_index("ix_approval_logs_device_id", "publish_approval_logs", ["device_id"], if_not_exists=True)
    op.create_index("ix_approval_logs_created_at", "publish_approval_logs", ["created_at"], if_not_exists=True)
    op.create_index("ix_approval_logs_approved", "publish_approval_logs", ["approved"], if_not_exists=True)

    # 2. user_publish_quotas 表
    op.create_table(
        "user_publish_quotas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tier", sa.String(length=20), server_default="free", comment="套餐级别: free/pro/enterprise"),
        sa.Column("daily_limit", sa.Integer(), server_default="50", comment="每日发布上限"),
        sa.Column("monthly_limit", sa.Integer(), server_default="1000", comment="每月发布上限"),
        sa.Column("used_today", sa.Integer(), server_default="0", comment="今日已使用次数"),
        sa.Column("used_this_month", sa.Integer(), server_default="0", comment="本月已使用次数"),
        sa.Column("reset_date", sa.Date(), nullable=True, comment="今日计数上次重置日期"),
        sa.Column("month_reset_date", sa.Date(), nullable=True, comment="本月计数上次重置月份"),
        sa.Column("platform_whitelist", sa.JSON(), nullable=True, comment="允许发布的平台列表(空=全部允许)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_user_publish_quotas_user_id"),
        comment="用户发布配额表: 控制每个用户每天/每月能发布多少条",
    )
    op.create_index("ix_user_quotas_user_id", "user_publish_quotas", ["user_id"], if_not_exists=True)


def downgrade():
    op.drop_index("ix_user_quotas_user_id", table_name="user_publish_quotas", if_exists=True)
    op.drop_table("user_publish_quotas", if_exists=True)

    op.drop_index("ix_approval_logs_approved", table_name="publish_approval_logs", if_exists=True)
    op.drop_index("ix_approval_logs_created_at", table_name="publish_approval_logs", if_exists=True)
    op.drop_index("ix_approval_logs_device_id", table_name="publish_approval_logs", if_exists=True)
    op.drop_index("ix_approval_logs_record_id", table_name="publish_approval_logs", if_exists=True)
    op.drop_index("ix_approval_logs_task_id", table_name="publish_approval_logs", if_exists=True)
    op.drop_index("ix_approval_logs_user_id", table_name="publish_approval_logs", if_exists=True)
    op.drop_table("publish_approval_logs", if_exists=True)
