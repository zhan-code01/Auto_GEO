"""Add LangGraph PostgresSaver checkpoint tables.

Revision ID: 0034_langgraph_checkpoint
Revises: 0033_user_agent_facts

创建 LangGraph PostgresSaver 所需的 4 张表（来自 langgraph-checkpoint-postgres 2.0.1）：
- checkpoints: 主状态记录（thread_id + checkpoint_id 复合主键）
- checkpoint_writes: 增量写入记录
- checkpoint_blobs: 二进制状态序列化
- checkpoint_migrations: schema 版本管理

注意：PostgresSaver.setup() 也会自动创建这些表，此迁移脚本是为了
显式化管理 schema，便于 alembic upgrade 一并部署。
"""

from alembic import op
import sqlalchemy as sa


revision = "0034_langgraph_checkpoint"
down_revision = "0033_user_agent_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 checkpoint 表。

    PostgresSaver.setup() 内部会执行相同 DDL，重复执行是幂等的（IF NOT EXISTS）。
    这里显式建表是为了让 alembic upgrade head 一次到位，避免运行时第一次 setup() 拖慢启动。
    """
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            channel TEXT NOT NULL,
            type TEXT,
            blob BYTEA NOT NULL,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_blobs (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL,
            version TEXT NOT NULL,
            type TEXT,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS checkpoint_migrations (
            v INTEGER NOT NULL PRIMARY KEY
        );
    """)
    # 索引：按 thread_id 查最近 checkpoint 时常用
    op.execute("""
        CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx
        ON checkpoints (thread_id, checkpoint_ns, checkpoint_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx
        ON checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations;")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs;")
    op.execute("DROP TABLE IF EXISTS checkpoint_writes;")
    op.execute("DROP TABLE IF EXISTS checkpoints;")
