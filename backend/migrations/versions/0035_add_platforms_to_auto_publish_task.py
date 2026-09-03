"""Add platforms column to auto_publish_tasks.

Revision ID: 0035_add_platforms_to_auto_publish_task
Revises: 0034_langgraph_checkpoint

为 auto_publish_tasks 表新增 platforms JSON 列，持久化任务涉及的平台列表。
这样即使账号被删除或禁用，任务卡片上仍能正确显示平台标签。
同时为历史数据回填 platforms 值（基于 account_ids 关联的账号平台）。
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0035_add_platforms_to_auto_publish_task"
down_revision = "0034_langgraph_checkpoint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 幂等：列已存在则跳过添加（上次迁移部分成功的情况）
    col_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'auto_publish_tasks' AND column_name = 'platforms'"
        )
    ).scalar()
    if not col_exists:
        op.add_column(
            "auto_publish_tasks",
            sa.Column("platforms", sa.JSON(), nullable=True, comment="平台列表 ['zhihu','baidu']"),
        )

    # 回填历史数据：根据 account_ids 关联的账号平台
    result = conn.execute(sa.text("SELECT id, account_ids FROM auto_publish_tasks WHERE platforms IS NULL"))
    rows = result.fetchall()
    for task_id, account_ids in rows:
        if not account_ids:
            continue
        ids_str = ",".join(str(int(aid)) for aid in account_ids)
        platforms_result = conn.execute(
            sa.text(f"SELECT DISTINCT platform FROM accounts WHERE id IN ({ids_str})"),
        )
        platforms = [row[0] for row in platforms_result.fetchall()]
        if platforms:
            # 序列化为 JSON 字符串，避免 psycopg2 把 Python list 当作 text[] 数组
            platforms_json = json.dumps(platforms)
            conn.execute(
                sa.text("UPDATE auto_publish_tasks SET platforms = :p WHERE id = :tid"),
                {"p": platforms_json, "tid": task_id},
            )
    # 不手动 commit，由 alembic 统一管理事务，确保列添加、回填、版本标记更新原子生效


def downgrade() -> None:
    conn = op.get_bind()
    col_exists = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'auto_publish_tasks' AND column_name = 'platforms'"
        )
    ).scalar()
    if col_exists:
        op.drop_column("auto_publish_tasks", "platforms")
