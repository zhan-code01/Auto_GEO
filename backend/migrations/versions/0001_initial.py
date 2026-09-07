"""
初始数据库迁移
创建所有核心表结构
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建初始表结构"""

    # 检测是否为PostgreSQL
    dialect = op.get_context().dialect.name
    is_postgres = dialect == "postgresql"

    # accounts 表
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("account_name", sa.String(length=100), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("cookies", sa.Text(), nullable=True),
        sa.Column("storage_state", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("status", sa.Integer(), default=1),
        sa.Column("last_auth_time", sa.DateTime(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_accounts_platform", "accounts", ["platform"])
    op.create_index("idx_accounts_status", "accounts", ["status"])

    # clients 表
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("contact_person", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), default=1),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # projects 表
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("domain_keyword", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("status", sa.Integer(), default=1),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_projects_client_id", "projects", ["client_id"])

    # keywords 表
    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=200), nullable=False),
        sa.Column("difficulty_score", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_keywords_project_id", "keywords", ["project_id"])

    # geo_articles 表
    op.create_table(
        "geo_articles",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("keyword_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("ai_score", sa.Integer(), nullable=True),
        sa.Column("readability_score", sa.Integer(), nullable=True),
        sa.Column("quality_status", sa.String(length=20), default="pending"),
        sa.Column("platform", sa.String(length=50), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("publish_status", sa.String(length=20), default="draft"),
        sa.Column("publish_time", sa.DateTime(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("target_platforms", sa.JSON(), nullable=True),
        sa.Column("publish_strategy", sa.String(length=20), default="draft"),
        sa.Column("retry_count", sa.Integer(), default=0),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("publish_logs", sa.Text(), nullable=True),
        sa.Column("platform_url", sa.String(length=500), nullable=True),
        sa.Column("index_status", sa.String(length=20), default="uncheck"),
        sa.Column("last_check_time", sa.DateTime(), nullable=True),
        sa.Column("index_details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_geo_articles_keyword_id", "geo_articles", ["keyword_id"])
    op.create_index("idx_geo_articles_project_id", "geo_articles", ["project_id"])
    op.create_index("idx_geo_articles_publish_status", "geo_articles", ["publish_status"])
    op.create_index("idx_geo_articles_created_at", "geo_articles", ["created_at"])

    # publish_records 表
    op.create_table(
        "publish_records",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("publish_status", sa.Integer(), default=0),
        sa.Column("platform_url", sa.String(length=500), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["geo_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_publish_records_article_id", "publish_records", ["article_id"])
    op.create_index("idx_publish_records_account_id", "publish_records", ["account_id"])

    # 其他表的创建...（根据需要添加）

    # ==================== 创建后续 migration 依赖的基础表 ====================
    # 这些表在后续 migration 中被引用（FK、add_column 等），必须在此处创建。
    # 对于已有旧库（表可能已被 create_all 创建），使用 IF NOT EXISTS 确保幂等。
    # 对于全新 PostgreSQL 空库，这些表为后续 migration 提供依赖。
    #
    # 注意：此处只创建最小 schema，后续 migration 会增量添加字段；
    # 0007_reconcile 会在最终补齐所有 ORM 所需字段。

    # ---------- users ----------
    if is_postgres:
        op.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                email VARCHAR(200) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) NOT NULL UNIQUE,
                email VARCHAR(200) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ---------- site_projects ----------
    if is_postgres:
        op.execute("""
            CREATE TABLE IF NOT EXISTS site_projects (
                id SERIAL PRIMARY KEY,
                name TEXT,
                site_id TEXT UNIQUE,
                config_data JSONB,
                deploy_path TEXT,
                preview_url TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS site_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                site_id TEXT UNIQUE,
                config_data TEXT,
                deploy_path TEXT,
                preview_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ---------- auto_publish_tasks ----------
    if is_postgres:
        op.execute("""
            CREATE TABLE IF NOT EXISTS auto_publish_tasks (
                id SERIAL PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                article_ids JSONB NOT NULL DEFAULT '[]',
                account_ids JSONB NOT NULL DEFAULT '[]',
                declare_ai_content BOOLEAN DEFAULT TRUE,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                status VARCHAR(20) DEFAULT 'pending',
                exec_type VARCHAR(20) DEFAULT 'immediate',
                scheduled_at TIMESTAMP,
                interval_minutes INTEGER,
                total_count INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                error_msg TEXT,
                last_error_at TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS auto_publish_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                article_ids TEXT NOT NULL DEFAULT '[]',
                account_ids TEXT NOT NULL DEFAULT '[]',
                declare_ai_content BOOLEAN DEFAULT 1,
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                status VARCHAR(20) DEFAULT 'pending',
                exec_type VARCHAR(20) DEFAULT 'immediate',
                scheduled_at TIMESTAMP,
                interval_minutes INTEGER,
                total_count INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                error_msg TEXT,
                last_error_at TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ---------- PG 注释 ----------
    if is_postgres:
        op.execute("COMMENT ON TABLE accounts IS '账号表'")
        op.execute("COMMENT ON TABLE clients IS '客户表'")
        op.execute("COMMENT ON TABLE projects IS '项目表'")
        op.execute("COMMENT ON TABLE keywords IS '关键词表'")
        op.execute("COMMENT ON TABLE geo_articles IS 'GEO文章表'")
        op.execute("COMMENT ON TABLE publish_records IS '发布记录表'")
        op.execute("COMMENT ON TABLE users IS '用户表'")
        op.execute("COMMENT ON TABLE site_projects IS '建站项目表'")
        op.execute("COMMENT ON TABLE auto_publish_tasks IS '自动发布任务表'")

    print("✅ 初始表结构创建完成（含 users / site_projects / auto_publish_tasks）")


def downgrade() -> None:
    """回滚：删除所有表"""
    op.drop_table("publish_records")
    op.drop_table("geo_articles")
    op.drop_table("keywords")
    op.drop_table("projects")
    op.drop_table("clients")
    op.drop_table("accounts")
    print("✅ 所有表已删除")
