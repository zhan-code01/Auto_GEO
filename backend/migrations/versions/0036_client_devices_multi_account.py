"""Allow one physical client (device_id) to be registered by multiple accounts.

Revision ID: 0036_client_devices_multi_account
Revises: 0035_add_platforms_to_auto_publish_task

背景：同一台电脑（同一 device_id）此前只能绑定一个账号，换账号登录会被
「该设备ID已被其他账号占用」(409) 拦截。现在改为按 (user_id, device_id)
组合唯一：每个账号拥有自己的设备记录，多账号共用一台机器不再冲突。

变更：
  - 删除 client_devices.device_id 全局唯一约束（uq_client_devices_device_id）
  - 新增 (user_id, device_id) 组合唯一约束（uq_client_devices_user_device）
"""
from alembic import op


revision = "0036_client_devices_multi_account"
down_revision = "0035_add_platforms_to_auto_publish_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        # SQLite 不支持 ALTER TABLE DROP CONSTRAINT，需走 batch 模式
        with op.batch_alter_table("client_devices") as batch_op:
            batch_op.drop_constraint("uq_client_devices_device_id", type_="unique")
            batch_op.create_unique_constraint("uq_client_devices_user_device", ["user_id", "device_id"])
    else:
        # 1. 删除 device_id 上的全局唯一性（两种历史形态都处理）：
        #    - 迁移 0016 创建的唯一约束 uq_client_devices_device_id
        #    - 早期 create_all（模型 unique=True）留下的唯一索引 ix_client_devices_device_id
        op.execute("ALTER TABLE client_devices DROP CONSTRAINT IF EXISTS uq_client_devices_device_id")
        op.execute("DROP INDEX IF EXISTS ix_client_devices_device_id")
        # 2. 以非唯一索引重建 device_id（保留按设备 ID 的管理查询能力）
        op.execute("CREATE INDEX IF NOT EXISTS ix_client_devices_device_id ON client_devices (device_id)")
        # 3. 新增 (user_id, device_id) 组合唯一约束（先清理残留再添加，保证幂等可重跑）
        op.execute("ALTER TABLE client_devices DROP CONSTRAINT IF EXISTS uq_client_devices_user_device")
        op.execute(
            "ALTER TABLE client_devices ADD CONSTRAINT uq_client_devices_user_device "
            "UNIQUE (user_id, device_id)"
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("client_devices") as batch_op:
            batch_op.drop_constraint("uq_client_devices_user_device", type_="unique")
            batch_op.create_unique_constraint("uq_client_devices_device_id", ["device_id"])
    else:
        op.execute("ALTER TABLE client_devices DROP CONSTRAINT IF EXISTS uq_client_devices_user_device")
        op.execute("DROP INDEX IF EXISTS ix_client_devices_device_id")
        op.execute(
            "ALTER TABLE client_devices ADD CONSTRAINT uq_client_devices_device_id UNIQUE (device_id)"
        )
