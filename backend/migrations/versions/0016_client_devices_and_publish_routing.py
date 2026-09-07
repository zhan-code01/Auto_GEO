"""Client devices and publish task routing.

本地客户端发布架构（文档 §6.1）：

1. 新增 client_devices 表（§6.1.1）：标识在线的本地客户端设备，发布任务可派发到指定设备。
   设备本身不持有平台登录态——登录态保存在客户端本机（session_location=local_only）。

2. 为 auto_publish_tasks 补齐任务路由字段（§6.1.3）：execution_mode / assigned_device_id /
   claimed_by_device_id / claim_expires_at / manual_required / manual_message。这些列虽已在
   ORM 模型（AutoPublishTask）中声明、并由 fix_database.py 在 SQLite legacy 上镜像，但 PG 生产库
   此前无对应迁移，会触发 OperationalError。本迁移在 PG 上幂等补齐。

Account 的 auth_mode / device_id / session_location 三列已由既有迁移与 fix_database 落地。

Revision ID: 0016_client_devices_and_publish_routing
Revises: 0015_siteproject_ai_fields
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


revision = "0016_client_devices_and_publish_routing"
down_revision = "0015_siteproject_ai_fields"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa_inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {c["name"] for c in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column_name):
        op.add_column(table_name, column)


def upgrade():
    # 1. client_devices 表（幂等）
    if not _table_exists("client_devices"):
        op.create_table(
            "client_devices",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("device_id", sa.String(length=64), nullable=False),
            sa.Column("device_name", sa.String(length=200), nullable=True),
            sa.Column("os", sa.String(length=20), nullable=True),
            sa.Column("app_version", sa.String(length=30), nullable=True),
            sa.Column("capabilities", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default="offline"),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("device_id", name="uq_client_devices_device_id"),
            comment="客户端设备表：管理用户的本地客户端设备（Electron 客户端实例）",
        )
    op.create_index("ix_client_devices_user_id", "client_devices", ["user_id"], if_not_exists=True)
    op.create_index("ix_client_devices_device_id", "client_devices", ["device_id"], if_not_exists=True)
    op.create_index("ix_client_devices_last_seen_at", "client_devices", ["last_seen_at"], if_not_exists=True)

    # 2. auto_publish_tasks 路由列（PG 此前缺失，补齐；SQLite legacy 已由 fix_database 兜底）
    _add_column_if_missing(
        "auto_publish_tasks",
        "execution_mode",
        sa.Column(
            "execution_mode",
            sa.String(length=20),
            server_default="cloud_browser",
            comment="执行模式：local_client/cloud_browser/api/manual",
        ),
    )
    _add_column_if_missing(
        "auto_publish_tasks",
        "assigned_device_id",
        sa.Column("assigned_device_id", sa.String(length=64), nullable=True, comment="指定执行设备ID"),
    )
    _add_column_if_missing(
        "auto_publish_tasks",
        "claimed_by_device_id",
        sa.Column("claimed_by_device_id", sa.String(length=64), nullable=True, comment="实际领取设备ID"),
    )
    _add_column_if_missing(
        "auto_publish_tasks",
        "claim_expires_at",
        sa.Column("claim_expires_at", sa.DateTime(), nullable=True, comment="任务领取锁过期时间"),
    )
    _add_column_if_missing(
        "auto_publish_tasks",
        "manual_required",
        sa.Column("manual_required", sa.Boolean(), server_default=sa.text("false"), comment="是否需要人工接管"),
    )
    _add_column_if_missing(
        "auto_publish_tasks",
        "manual_message",
        sa.Column("manual_message", sa.Text(), nullable=True, comment="人工接管原因"),
    )
    op.create_index(
        "ix_auto_publish_tasks_assigned_device_id", "auto_publish_tasks", ["assigned_device_id"], if_not_exists=True
    )

    # 3. accounts 本地客户端授权列（§6.1.2 / §7.3）
    #    模型与 fix_database（SQLite legacy）已声明，但 PG 此前无对应迁移，此处幂等补齐。
    _add_column_if_missing(
        "accounts",
        "auth_mode",
        sa.Column(
            "auth_mode",
            sa.String(length=20),
            server_default="cloud_browser",
            comment="授权模式：cloud_browser=服务器浏览器 local_client=本地客户端 api=官方API",
        ),
    )
    _add_column_if_missing(
        "accounts",
        "device_id",
        sa.Column("device_id", sa.String(length=64), nullable=True, comment="本地客户端设备ID（local_client 模式）"),
    )
    _add_column_if_missing(
        "accounts",
        "session_location",
        sa.Column(
            "session_location",
            sa.String(length=20),
            server_default="server",
            comment="会话位置：server=服务器保存 local_only=仅本地",
        ),
    )
    op.create_index("ix_accounts_device_id", "accounts", ["device_id"], if_not_exists=True)


def downgrade():
    # 谨慎起见不自动 drop 业务列/表，避免误删数据；如需回滚请手动处理。
    pass
