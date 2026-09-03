"""
PostgreSQL Schema Reconciliation — 幂等补齐 ORM 模型所需全部表和字段

本 migration 解决的核心问题：
1. 历史上由 create_all() 建表或 alembic stamp head 跳过的库缺少字段/表
2. fix_database.py 只针对 SQLite，PostgreSQL 缺少 index_check_records 增强字段
3. 较新模型 (conversation_sessions/messages, user_agent_preferences 等) 未被 Alembic 覆盖

安全保证：
- 字段不存在才添加（IF NOT EXISTS 语义）
- 表不存在才创建
- 不删除现有字段
- 不清空数据
- 不做破坏性重建表

Revision ID: 0007_reconcile_postgresql_schema
Revises: 0006_add_project_members_and_task_attribution
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

# revision identifiers
revision = '0007_reconcile_postgresql_schema'
down_revision = '0006_add_project_members_and_task_attribution'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    """检查表是否已存在"""
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name, column_name):
    """检查列是否已存在"""
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(index_name):
    """检查索引是否已存在"""
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return False
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
        {"name": index_name}
    )
    return result.fetchone() is not None


def _add_column_if_not_exists(table_name, column_name, column_obj):
    """安全添加列，已存在则跳过"""
    if not _column_exists(table_name, column_name):
        op.add_column(table_name, column_obj)


def _create_index_if_not_exists(index_name, table_name, columns, unique=False):
    """安全创建索引，已存在则跳过"""
    if not _index_exists(index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    """幂等补齐 PostgreSQL schema，使其与 models.py 完全一致"""

    dialect = op.get_context().dialect.name
    if dialect != 'postgresql':
        print("SKIP: 0007_reconcile_postgresql_schema is PostgreSQL-only")
        return

    # ====================================================================
    # 一、创建 ORM 中存在但 Alembic 从未管理过的表
    # ====================================================================

    # ---------- scheduled_tasks ----------
    if not _table_exists('scheduled_tasks'):
        op.create_table(
            'scheduled_tasks',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('name', sa.String(100), nullable=False, comment='任务名称'),
            sa.Column('task_key', sa.String(50), nullable=False, unique=True, comment='任务标识符'),
            sa.Column('cron_expression', sa.String(50), nullable=False, comment='Cron表达式'),
            sa.Column('is_active', sa.Boolean(), server_default='1', comment='是否启用'),
            sa.Column('description', sa.Text(), nullable=True, comment='任务描述'),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )

    # ---------- question_variants ----------
    if not _table_exists('question_variants'):
        op.create_table(
            'question_variants',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('keyword_id', sa.Integer(), nullable=False, comment='关键词ID'),
            sa.Column('question', sa.Text(), nullable=False, comment='问题变体'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['keyword_id'], ['keywords.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_qv_keyword_id', 'question_variants', ['keyword_id'])

    # ---------- index_check_records ----------
    if not _table_exists('index_check_records'):
        op.create_table(
            'index_check_records',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('keyword_id', sa.Integer(), nullable=False, comment='关键词ID'),
            sa.Column('platform', sa.String(50), nullable=False, comment='检测平台'),
            sa.Column('question', sa.Text(), nullable=False, comment='检测时使用的问题'),
            sa.Column('answer', sa.Text(), nullable=True, comment='AI回答内容'),
            sa.Column('keyword_found', sa.Boolean(), nullable=True, comment='是否包含关键词'),
            sa.Column('company_found', sa.Boolean(), nullable=True, comment='是否包含公司名'),
            sa.Column('check_phase', sa.String(20), server_default='ongoing', comment='检测阶段'),
            sa.Column('keyword_count', sa.Integer(), nullable=True, comment='关键词出现次数'),
            sa.Column('company_count', sa.Integer(), nullable=True, comment='公司名出现次数'),
            sa.Column('company_matched', sa.String(200), nullable=True, comment='实际命中的公司分层词'),
            sa.Column('confidence', sa.Float(), nullable=True, comment='置信度 0~1'),
            sa.Column('check_time', sa.DateTime(), server_default=sa.func.now(), comment='检测时间'),
            sa.ForeignKeyConstraint(['keyword_id'], ['keywords.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_icr_keyword_id', 'index_check_records', ['keyword_id'])

    # ---------- knowledge_categories ----------
    if not _table_exists('knowledge_categories'):
        op.create_table(
            'knowledge_categories',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户ID'),
            sa.Column('ragflow_dataset_id', sa.String(100), nullable=True, unique=True, comment='RAGFlow知识库ID'),
            sa.Column('name', sa.String(200), nullable=False, comment='企业/分类名称'),
            sa.Column('industry', sa.String(100), nullable=True, comment='所属行业'),
            sa.Column('description', sa.Text(), nullable=True, comment='分类描述'),
            sa.Column('tags', sa.String(500), nullable=True, comment='标签'),
            sa.Column('color', sa.String(20), server_default='#6366f1', comment='主题颜色'),
            sa.Column('status', sa.Integer(), server_default='1', comment='状态'),
            sa.Column('sync_status', sa.String(20), server_default='pending', comment='同步状态'),
            sa.Column('ragflow_synced', sa.Boolean(), server_default='0', comment='是否已同步到RAGFlow'),
            sa.Column('ragflow_synced_at', sa.DateTime(), nullable=True, comment='同步时间'),
            sa.Column('last_sync_at', sa.DateTime(), nullable=True, comment='最后同步时间'),
            sa.Column('knowledge_count', sa.Integer(), server_default='0', comment='知识数量'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_kc_user_id', 'knowledge_categories', ['user_id'])
        _create_index_if_not_exists('ix_kc_ragflow_dataset_id', 'knowledge_categories', ['ragflow_dataset_id'], unique=True)

    # ---------- knowledge_items ----------
    if not _table_exists('knowledge_items'):
        op.create_table(
            'knowledge_items',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('ragflow_document_id', sa.String(100), nullable=True, unique=True, comment='RAGFlow文档ID'),
            sa.Column('ragflow_dataset_id', sa.String(100), nullable=False, comment='所属RAGFlow知识库ID'),
            sa.Column('category_id', sa.Integer(), nullable=False, comment='分类ID'),
            sa.Column('title', sa.String(200), nullable=False, comment='知识标题'),
            sa.Column('content', sa.Text(), nullable=False, comment='知识内容'),
            sa.Column('type', sa.String(50), server_default='other', comment='知识类型'),
            sa.Column('status', sa.Integer(), server_default='1', comment='状态'),
            sa.Column('sync_status', sa.String(20), server_default='pending', comment='同步状态'),
            sa.Column('ragflow_synced', sa.Boolean(), server_default='0', comment='是否已同步到RAGFlow'),
            sa.Column('ragflow_synced_at', sa.DateTime(), nullable=True, comment='同步时间'),
            sa.Column('ragflow_parsed', sa.Boolean(), server_default='0', comment='文档是否已解析'),
            sa.Column('last_sync_at', sa.DateTime(), nullable=True, comment='最后同步时间'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['category_id'], ['knowledge_categories.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_ki_ragflow_document_id', 'knowledge_items', ['ragflow_document_id'], unique=True)
        _create_index_if_not_exists('ix_ki_ragflow_dataset_id', 'knowledge_items', ['ragflow_dataset_id'])
        _create_index_if_not_exists('ix_ki_category_id', 'knowledge_items', ['category_id'])

    # ---------- reference_articles ----------
    if not _table_exists('reference_articles'):
        op.create_table(
            'reference_articles',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('title', sa.String(500), nullable=False, comment='文章标题'),
            sa.Column('url', sa.String(1000), nullable=False, unique=True, comment='原文链接'),
            sa.Column('content', sa.Text(), nullable=False, comment='文章正文'),
            sa.Column('summary', sa.Text(), nullable=True, comment='文章摘要'),
            sa.Column('platform', sa.String(50), nullable=False, comment='来源平台'),
            sa.Column('author', sa.String(200), nullable=True, comment='作者名称'),
            sa.Column('publish_time', sa.String(50), nullable=True, comment='原文发布时间'),
            sa.Column('likes', sa.Integer(), server_default='0', comment='点赞数'),
            sa.Column('reads', sa.Integer(), server_default='0', comment='阅读量'),
            sa.Column('comments', sa.Integer(), server_default='0', comment='评论数'),
            sa.Column('keyword', sa.String(200), nullable=True, comment='采集关键词'),
            sa.Column('collected_at', sa.DateTime(), server_default=sa.func.now(), comment='采集时间'),
            sa.Column('ragflow_synced', sa.Boolean(), server_default='0', comment='是否已同步到RAGFlow'),
            sa.Column('ragflow_doc_id', sa.String(100), nullable=True, comment='RAGFlow文档ID'),
            sa.Column('ragflow_sync_time', sa.DateTime(), nullable=True, comment='RAGFlow同步时间'),
            sa.Column('status', sa.Integer(), server_default='1', comment='状态'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_ra_platform', 'reference_articles', ['platform'])
        _create_index_if_not_exists('ix_ra_keyword', 'reference_articles', ['keyword'])

    # ---------- site_projects ----------
    if not _table_exists('site_projects'):
        op.create_table(
            'site_projects',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户ID'),
            sa.Column('name', sa.String(), nullable=True, comment='项目名称'),
            sa.Column('site_id', sa.String(), nullable=True, unique=True, comment='唯一标识'),
            sa.Column('config_data', sa.JSON(), nullable=True, comment='网站配置数据'),
            sa.Column('deploy_path', sa.String(), nullable=True, comment='生成的本地路径'),
            sa.Column('preview_url', sa.String(), nullable=True, comment='预览URL'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_sp_site_id', 'site_projects', ['site_id'], unique=True)
        _create_index_if_not_exists('ix_sp_user_id', 'site_projects', ['user_id'])

    # ---------- auto_publish_tasks ----------
    if not _table_exists('auto_publish_tasks'):
        op.create_table(
            'auto_publish_tasks',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('name', sa.String(200), nullable=False, comment='任务名称'),
            sa.Column('description', sa.Text(), nullable=True, comment='任务描述'),
            sa.Column('article_ids', sa.JSON(), nullable=False, comment='文章ID列表'),
            sa.Column('account_ids', sa.JSON(), nullable=False, comment='账号ID列表'),
            sa.Column('declare_ai_content', sa.Boolean(), server_default='1', comment='是否声明AI创作'),
            sa.Column('user_id', sa.Integer(), nullable=True, comment='数据归属用户ID'),
            sa.Column('triggered_by_user_id', sa.Integer(), nullable=True, comment='触发用户ID'),
            sa.Column('feishu_event_id', sa.String(200), nullable=True, comment='关联飞书事件ID'),
            sa.Column('status', sa.String(20), server_default='pending', comment='任务状态'),
            sa.Column('exec_type', sa.String(20), server_default='immediate', comment='执行类型'),
            sa.Column('scheduled_at', sa.DateTime(), nullable=True, comment='计划执行时间'),
            sa.Column('interval_minutes', sa.Integer(), nullable=True, comment='间隔分钟数'),
            sa.Column('total_count', sa.Integer(), server_default='0', comment='总发布任务数'),
            sa.Column('completed_count', sa.Integer(), server_default='0', comment='已完成数量'),
            sa.Column('failed_count', sa.Integer(), server_default='0', comment='失败数量'),
            sa.Column('error_msg', sa.Text(), nullable=True, comment='错误信息'),
            sa.Column('last_error_at', sa.DateTime(), nullable=True, comment='最后错误时间'),
            sa.Column('started_at', sa.DateTime(), nullable=True, comment='开始时间'),
            sa.Column('completed_at', sa.DateTime(), nullable=True, comment='完成时间'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_apt_user_id', 'auto_publish_tasks', ['user_id'])
        _create_index_if_not_exists('ix_apt_triggered_by_user_id', 'auto_publish_tasks', ['triggered_by_user_id'])

    # ---------- auto_publish_records ----------
    if not _table_exists('auto_publish_records'):
        op.create_table(
            'auto_publish_records',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('task_id', sa.Integer(), nullable=False, comment='所属任务ID'),
            sa.Column('article_id', sa.Integer(), nullable=False, comment='文章ID'),
            sa.Column('account_id', sa.Integer(), nullable=False, comment='账号ID'),
            sa.Column('status', sa.String(20), server_default='pending', comment='状态'),
            sa.Column('platform_url', sa.String(500), nullable=True, comment='发布后链接'),
            sa.Column('error_msg', sa.Text(), nullable=True, comment='错误信息'),
            sa.Column('retry_count', sa.Integer(), server_default='0', comment='重试次数'),
            sa.Column('max_retries', sa.Integer(), server_default='3', comment='最大重试次数'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('started_at', sa.DateTime(), nullable=True, comment='开始时间'),
            sa.Column('completed_at', sa.DateTime(), nullable=True, comment='完成时间'),
            sa.ForeignKeyConstraint(['task_id'], ['auto_publish_tasks.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['article_id'], ['geo_articles.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_apr_task_id', 'auto_publish_records', ['task_id'])
        _create_index_if_not_exists('ix_apr_article_id', 'auto_publish_records', ['article_id'])
        _create_index_if_not_exists('ix_apr_account_id', 'auto_publish_records', ['account_id'])

    # ---------- conversation_sessions ----------
    if not _table_exists('conversation_sessions'):
        op.create_table(
            'conversation_sessions',
            sa.Column('id', sa.String(120), nullable=False, comment='会话ID'),
            sa.Column('source', sa.String(50), server_default='web', comment='来源'),
            sa.Column('channel', sa.String(50), server_default='web', comment='通道'),
            sa.Column('system_user_id', sa.Integer(), nullable=False, comment='系统用户ID'),
            sa.Column('external_user_id', sa.String(200), nullable=True, comment='外部用户ID'),
            sa.Column('external_chat_id', sa.String(200), nullable=True, comment='外部会话ID'),
            sa.Column('status', sa.String(30), server_default='active', comment='状态'),
            sa.Column('current_intent', sa.String(80), nullable=True, comment='当前意图'),
            sa.Column('slots', sa.JSON(), nullable=True, comment='结构化任务槽位'),
            sa.Column('summary', sa.Text(), nullable=True, comment='会话摘要'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(), nullable=True, comment='过期时间'),
            sa.Column('title', sa.String(120), nullable=True, comment='会话标题'),
            sa.ForeignKeyConstraint(['system_user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_cs_source', 'conversation_sessions', ['source'])
        _create_index_if_not_exists('ix_cs_channel', 'conversation_sessions', ['channel'])
        _create_index_if_not_exists('ix_cs_system_user_id', 'conversation_sessions', ['system_user_id'])
        _create_index_if_not_exists('ix_cs_external_user_id', 'conversation_sessions', ['external_user_id'])
        _create_index_if_not_exists('ix_cs_external_chat_id', 'conversation_sessions', ['external_chat_id'])
        _create_index_if_not_exists('ix_cs_status', 'conversation_sessions', ['status'])
        _create_index_if_not_exists('ix_cs_current_intent', 'conversation_sessions', ['current_intent'])

    # ---------- conversation_messages ----------
    if not _table_exists('conversation_messages'):
        op.create_table(
            'conversation_messages',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('conversation_id', sa.String(120), nullable=False, comment='会话ID'),
            sa.Column('role', sa.String(30), nullable=False, comment='角色'),
            sa.Column('content', sa.Text(), nullable=False, comment='消息内容'),
            sa.Column('message_metadata', sa.JSON(), nullable=True, comment='消息元数据'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['conversation_id'], ['conversation_sessions.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_cm_conversation_id', 'conversation_messages', ['conversation_id'])
        _create_index_if_not_exists('ix_cm_role', 'conversation_messages', ['role'])
        _create_index_if_not_exists('ix_cm_created_at', 'conversation_messages', ['created_at'])

    # ---------- user_agent_preferences ----------
    if not _table_exists('user_agent_preferences'):
        op.create_table(
            'user_agent_preferences',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('system_user_id', sa.Integer(), nullable=False, unique=True, comment='系统用户ID'),
            sa.Column('default_project_id', sa.Integer(), nullable=True, comment='默认项目ID'),
            sa.Column('default_platforms', sa.JSON(), nullable=True, comment='默认发布平台列表'),
            sa.Column('default_publish_strategy', sa.String(30), nullable=True, comment='默认发布策略'),
            sa.Column('require_confirmation_before_publish', sa.Boolean(), server_default='1', nullable=False, comment='发布前是否确认'),
            sa.Column('tone_preference', sa.String(50), nullable=True, comment='语气偏好'),
            sa.Column('onboarding_dismissed', sa.Boolean(), server_default='0', nullable=False, comment='是否已关闭新用户引导'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['system_user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['default_project_id'], ['projects.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_index_if_not_exists('ix_uap_system_user_id', 'user_agent_preferences', ['system_user_id'], unique=True)
        _create_index_if_not_exists('ix_uap_default_project_id', 'user_agent_preferences', ['default_project_id'])

    # ====================================================================
    # 二、补齐已有表缺失的列
    # ====================================================================

    # ---------- index_check_records: 5 个增强字段（当前 500 的根因）----------
    if _table_exists('index_check_records'):
        _add_column_if_not_exists('index_check_records', 'check_phase',
            sa.Column('check_phase', sa.String(20), server_default='ongoing', comment='检测阶段'))
        _add_column_if_not_exists('index_check_records', 'keyword_count',
            sa.Column('keyword_count', sa.Integer(), nullable=True, comment='关键词出现次数'))
        _add_column_if_not_exists('index_check_records', 'company_count',
            sa.Column('company_count', sa.Integer(), nullable=True, comment='公司名出现次数'))
        _add_column_if_not_exists('index_check_records', 'company_matched',
            sa.Column('company_matched', sa.String(200), nullable=True, comment='实际命中的公司分层词'))
        _add_column_if_not_exists('index_check_records', 'confidence',
            sa.Column('confidence', sa.Float(), nullable=True, comment='置信度 0~1'))

        # 建议索引
        _create_index_if_not_exists('ix_icr_check_phase', 'index_check_records', ['check_phase'])
        _create_index_if_not_exists('ix_icr_check_time', 'index_check_records', ['check_time'])
        _create_index_if_not_exists('ix_icr_keyword_id', 'index_check_records', ['keyword_id'])

    # ---------- keywords: keyword_type ----------
    if _table_exists('keywords'):
        _add_column_if_not_exists('keywords', 'keyword_type',
            sa.Column('keyword_type', sa.String(20), server_default='keyword', comment='类型'))

    # ---------- clients: user_id（迁移 0002 遗漏） ----------
    if _table_exists('clients'):
        _add_column_if_not_exists('clients', 'user_id',
            sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户ID'))
        if _column_exists('clients', 'user_id'):
            _create_index_if_not_exists('ix_clients_user_id', 'clients', ['user_id'])
            # 尝试添加外键（幂等：已存在则跳过）
            try:
                op.create_foreign_key('fk_clients_user_id', 'clients', 'users', ['user_id'], ['id'], ondelete='SET NULL')
            except Exception:
                pass  # 外键已存在

    # ---------- knowledge_categories: 补齐同步字段 ----------
    if _table_exists('knowledge_categories'):
        _add_column_if_not_exists('knowledge_categories', 'sync_status',
            sa.Column('sync_status', sa.String(20), server_default='pending', comment='同步状态'))
        _add_column_if_not_exists('knowledge_categories', 'last_sync_at',
            sa.Column('last_sync_at', sa.DateTime(), nullable=True, comment='最后同步时间'))
        _add_column_if_not_exists('knowledge_categories', 'knowledge_count',
            sa.Column('knowledge_count', sa.Integer(), server_default='0', comment='知识数量'))

    # ---------- knowledge_items: 补齐同步字段 ----------
    if _table_exists('knowledge_items'):
        _add_column_if_not_exists('knowledge_items', 'sync_status',
            sa.Column('sync_status', sa.String(20), server_default='pending', comment='同步状态'))
        _add_column_if_not_exists('knowledge_items', 'last_sync_at',
            sa.Column('last_sync_at', sa.DateTime(), nullable=True, comment='最后同步时间'))

    # ---------- auto_publish_tasks: user_id ----------
    if _table_exists('auto_publish_tasks'):
        _add_column_if_not_exists('auto_publish_tasks', 'user_id',
            sa.Column('user_id', sa.Integer(), nullable=True, comment='数据归属用户ID'))
        if _column_exists('auto_publish_tasks', 'user_id'):
            _create_index_if_not_exists('ix_apt_user_id', 'auto_publish_tasks', ['user_id'])
            try:
                op.create_foreign_key('fk_apt_user_id', 'auto_publish_tasks', 'users', ['user_id'], ['id'], ondelete='SET NULL')
            except Exception:
                pass

    # ---------- conversation_sessions: title ----------
    if _table_exists('conversation_sessions'):
        _add_column_if_not_exists('conversation_sessions', 'title',
            sa.Column('title', sa.String(120), nullable=True, comment='会话标题'))

    # ---------- user_agent_preferences: onboarding_dismissed ----------
    if _table_exists('user_agent_preferences'):
        _add_column_if_not_exists('user_agent_preferences', 'onboarding_dismissed',
            sa.Column('onboarding_dismissed', sa.Boolean(), server_default='0', nullable=False, comment='是否已关闭新用户引导'))

    # ---------- accounts: 补齐 0001 中可能缺失的 created_at/updated_at ----------
    if _table_exists('accounts'):
        _add_column_if_not_exists('accounts', 'username',
            sa.Column('username', sa.String(100), nullable=True, comment='平台内的用户名'))

    # ====================================================================
    # 三、为已有表补建索引（之前 create_all 建表可能缺少索引）
    # ====================================================================

    # accounts
    if _table_exists('accounts'):
        _create_index_if_not_exists('ix_accounts_user_id', 'accounts', ['user_id'])
        _create_index_if_not_exists('ix_accounts_deleted_at', 'accounts', ['deleted_at'])
        _create_index_if_not_exists('ix_accounts_group_id', 'accounts', ['group_id'])

    # geo_articles
    if _table_exists('geo_articles'):
        _create_index_if_not_exists('ix_geo_articles_user_id', 'geo_articles', ['user_id'])

    # projects
    if _table_exists('projects'):
        _create_index_if_not_exists('ix_projects_user_id', 'projects', ['user_id'])

    # site_projects
    if _table_exists('site_projects'):
        _create_index_if_not_exists('ix_site_projects_user_id', 'site_projects', ['user_id'])

    # knowledge_categories
    if _table_exists('knowledge_categories'):
        _create_index_if_not_exists('ix_knowledge_categories_user_id', 'knowledge_categories', ['user_id'])

    print("✅ PostgreSQL schema reconciliation 完成 — 表和字段已对齐 ORM 模型")


def downgrade():
    """回滚：移除本 migration 添加的表和列

    注意：由于本 migration 是 reconciliation 性质，downgrade 会删除它创建的所有表，
    以及删除它添加的所有列。请确认生产环境确实需要回滚后再执行。
    """
    dialect = op.get_context().dialect.name
    if dialect != 'postgresql':
        print("SKIP: 0007_reconcile_postgresql_schema downgrade is PostgreSQL-only")
        return

    # 删除本 migration 创建的表（倒序，处理外键依赖）
    for table in [
        'user_agent_preferences',
        'conversation_messages',
        'conversation_sessions',
        'auto_publish_records',
        'auto_publish_tasks',
        'site_projects',
        'reference_articles',
        'knowledge_items',
        'knowledge_categories',
        'index_check_records',
        'question_variants',
        'scheduled_tasks',
    ]:
        if _table_exists(table):
            op.drop_table(table)

    # 删除本 migration 添加的列（仅对可能由其他 migration 创建的表）
    for table, col in [
        ('index_check_records', 'check_phase'),
        ('index_check_records', 'keyword_count'),
        ('index_check_records', 'company_count'),
        ('index_check_records', 'company_matched'),
        ('index_check_records', 'confidence'),
        ('keywords', 'keyword_type'),
        ('clients', 'user_id'),
        ('knowledge_categories', 'sync_status'),
        ('knowledge_categories', 'last_sync_at'),
        ('knowledge_categories', 'knowledge_count'),
        ('knowledge_items', 'sync_status'),
        ('knowledge_items', 'last_sync_at'),
        ('auto_publish_tasks', 'user_id'),
        ('conversation_sessions', 'title'),
        ('user_agent_preferences', 'onboarding_dismissed'),
    ]:
        if _column_exists(table, col):
            op.drop_column(table, col)

    print("✅ PostgreSQL schema reconciliation 已回滚")
