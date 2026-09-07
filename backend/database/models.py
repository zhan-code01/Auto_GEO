# -*- coding: utf-8 -*-
"""
数据模型定义 - 工业级完整版
包含基础发布、GEO、监控、知识库及AI招聘所有表结构
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    Boolean,
    func,
    ForeignKey,
    JSON,
    Float,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, backref
from backend.database import Base
from datetime import datetime

# 表参数：允许扩展现有表
TABLE_ARGS = {"extend_existing": True}


class Account(Base):
    """账号表 — 第三方平台账号（知乎/百家号/头条等）"""

    __tablename__ = "accounts"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(50), nullable=False, index=True)
    account_name = Column(String(100), nullable=False)
    username = Column(String(100), nullable=True)  # 平台内的用户名
    cookies = Column(Text, nullable=True)
    storage_state = Column(Text, nullable=True)
    user_agent = Column(String(500), nullable=True)
    status = Column(Integer, default=1, comment="状态：1=正常 0=禁用 -1=授权过期")
    last_auth_time = Column(DateTime, nullable=True)
    remark = Column(Text, nullable=True)

    # 用户隔离（迁移 0002 添加，此处补齐 ORM 声明）
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属系统用户ID"
    )

    # 软删除
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    # 分组与标签（Phase 2）
    group_id = Column(
        Integer, ForeignKey("account_groups.id", ondelete="SET NULL"), nullable=True, index=True, comment="账号分组ID"
    )
    tags = Column(JSON, nullable=True, comment="标签列表，如 ['主账号', '高权重']")

    # 健康度（Phase 3）
    health_score = Column(Integer, default=100, comment="健康度评分 0-100，100=最佳")
    last_check_time = Column(DateTime, nullable=True, comment="最后健康检测时间")
    auth_expires_at = Column(DateTime, nullable=True, comment="预估授权过期时间")

    # 浏览器类型（Phase 6）
    browser_type = Column(String(20), default="playwright", comment="浏览器类型：playwright/adspower")
    adspower_profile_id = Column(String(100), nullable=True, comment="AdsPower 配置文件ID")

    # 本地客户端发布（Phase 0：本地客户端架构）
    auth_mode = Column(
        String(20),
        default="cloud_browser",
        comment="授权模式：cloud_browser=服务器浏览器 local_client=本地客户端 api=官方API",
    )
    device_id = Column(String(64), nullable=True, index=True, comment="本地客户端设备ID（local_client 模式）")
    session_location = Column(
        String(20),
        default="server",
        comment="会话位置：server=服务器保存 local_only=仅本地",
    )

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关联关系
    publish_records = relationship("PublishRecord", back_populates="account", cascade="all, delete-orphan")
    owner = relationship("User", backref="accounts", foreign_keys=[user_id])
    group = relationship("AccountGroup", back_populates="accounts", foreign_keys=[group_id])

    @property
    def is_authorized(self) -> bool:
        """账号是否真正持有登录凭证（按授权模式分流判断）。

        status=1 只表示"启用"，不代表已登录。授权判据必须区分 session_location，
        否则会误杀本地客户端授权：
        - local_only（本地客户端，auth_mode=local_client）：平台登录态只存在用户
          本机（sessions/<platform>.json），服务器按设计不落 cookies/storage_state，
          只保存绑定元信息。以「已绑定设备（device_id）」作为已授权凭证。
        - server（云端浏览器，auth_mode=cloud_browser）：登录态存服务器，必须同时
          存在 cookies 与 storage_state 才算已授权。

        发布前置校验、账号列表/详情、前端可选性判断都以此为唯一口径，既避免"未登录
        也能选择发布 → 打开浏览器跳登录页 → 白白转人工"，也避免"本地客户端已授权却被
        误判未登录"。运行时会话是否失效由发布时客户端本机检测兜底（转人工）。
        """
        if self.session_location == "local_only":
            return bool(self.device_id)
        return bool(self.cookies and self.storage_state)


class ScheduledTask(Base):
    """
    定时任务配置表
    """

    __tablename__ = "scheduled_tasks"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="任务名称")
    task_key = Column(String(50), unique=True, nullable=False, comment="任务标识符(代码中对应key)")
    cron_expression = Column(String(50), nullable=False, comment="Cron表达式")
    is_active = Column(Boolean, default=True, comment="是否启用")
    description = Column(Text, nullable=True, comment="任务描述")

    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Task {self.name} : {self.cron_expression}>"


# ==================== 客户管理相关表 ====================


class Client(Base):
    """
    客户表
    存储客户/公司信息，一个客户可以有多个项目
    """

    __tablename__ = "clients"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 用户隔离（数据归属）
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属用户ID"
    )

    name = Column(String(200), nullable=False, comment="客户名称")
    company_name = Column(String(200), nullable=True, comment="公司名称")
    contact_person = Column(String(100), nullable=True, comment="联系人")
    phone = Column(String(50), nullable=True, comment="联系电话")
    email = Column(String(200), nullable=True, comment="邮箱")
    industry = Column(String(100), nullable=True, comment="行业")
    location = Column(String(100), nullable=True, comment="公司所在地，用于GEO测评地域扩展")
    address = Column(String(500), nullable=True, comment="地址")
    website = Column(String(500), nullable=True, comment="公司官网")

    # 备注和状态
    description = Column(Text, nullable=True, comment="客户描述/备注")
    status = Column(Integer, default=1, comment="状态：1=活跃 0=停用")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    projects = relationship("Project", back_populates="client", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Client {self.name}>"


# ==================== 已废弃的 Article 类 ====================
# 旧的 Article 模型已被 GeoArticle 替代，保留此注释以防历史引用问题
# class Article(Base):
#     """
#     文章表
#     存储文章内容和基本信息
#     """
#     __tablename__ = "articles"
#     __table_args__ = TABLE_ARGS
#
#     id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
#     title = Column(String(200), nullable=False, comment="文章标题")
#     content = Column(Text, nullable=False, comment="文章正文内容（Markdown/HTML）")
#     ... (其余字段已移除)
# =========================================================


class PublishRecord(Base):
    """
    发布记录表
    记录文章到各平台的发布状态
    """

    __tablename__ = "publish_records"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 外键
    article_id = Column(
        Integer, ForeignKey("geo_articles.id", ondelete="CASCADE"), nullable=False, index=True, comment="文章ID"
    )
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True, comment="账号ID"
    )

    # 发布状态
    publish_status = Column(Integer, default=0, comment="发布状态：0=待发布 1=发布中 2=成功 3=失败")

    # 结果
    platform_url = Column(String(500), nullable=True, comment="发布后的文章链接")
    error_msg = Column(Text, nullable=True, comment="错误信息")

    # 重试
    retry_count = Column(Integer, default=0, comment="重试次数")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    published_at = Column(DateTime, nullable=True, comment="实际发布时间")

    # 关联关系
    article = relationship("GeoArticle", back_populates="publish_records")
    account = relationship("Account", back_populates="publish_records")

    def __repr__(self):
        return f"<PublishRecord article_id={self.article_id} account_id={self.account_id} status={self.publish_status}>"


# ==================== GEO相关表 ====================


class Project(Base):
    """
    项目表
    存储项目信息，一个客户可以有多个项目
    """

    __tablename__ = "projects"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 用户隔离（迁移 0002 添加，此处补齐 ORM 声明）
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属用户ID"
    )

    # 关联客户
    client_id = Column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True, comment="客户ID"
    )

    # 项目信息
    name = Column(String(200), nullable=False, comment="项目名称")
    company_name = Column(String(200), nullable=True, comment="公司名称")
    domain_keyword = Column(String(200), nullable=True, comment="领域关键词，用于关键词蒸馏")
    description = Column(Text, nullable=True, comment="项目描述")
    industry = Column(String(100), nullable=True, comment="行业")

    # 状态
    status = Column(Integer, default=1, comment="状态：1=活跃 0=停用")

    # 收录诊断：基线快照建立时间（NULL 表示尚未建立基线；对比报表据此区分"使用前/使用后"）
    baseline_at = Column(DateTime, nullable=True, comment="基线快照建立时间")

    # 收录监控：用户选择的 AI 平台列表（null = 默认全部已授权平台；baseline_platforms 记录基线建立时实际使用的平台）
    selected_platforms = Column(JSON, nullable=True, comment="收录监控选中的AI平台列表")
    baseline_platforms = Column(JSON, nullable=True, comment="基线建立时实际使用的AI平台列表")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    client = relationship("Client", back_populates="projects")
    keywords = relationship("Keyword", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Project {self.name}>"


class Keyword(Base):
    """
    关键词表
    存储AI分析出的高价值关键词
    """

    __tablename__ = "keywords"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True, comment="项目ID"
    )
    keyword = Column(String(200), nullable=False, comment="关键词")
    difficulty_score = Column(Integer, nullable=True, comment="难度评分（0-100）")
    keyword_type = Column(
        String(20), default="keyword", comment="类型：keyword=关键词 question=搜索问题 smart_question=智能文章问题"
    )

    # 状态
    status = Column(String(20), default="active", comment="状态：active=活跃 inactive=停用")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 关联关系
    project = relationship("Project", back_populates="keywords")
    articles = relationship("GeoArticle", back_populates="keyword", cascade="all, delete-orphan")
    question_variants = relationship("QuestionVariant", back_populates="keyword", cascade="all, delete-orphan")
    index_records = relationship("IndexCheckRecord", back_populates="keyword", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Keyword {self.keyword}>"


class QuestionVariant(Base):
    """
    问题变体表
    存储基于关键词生成的不同问法
    """

    __tablename__ = "question_variants"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    keyword_id = Column(
        Integer, ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False, index=True, comment="关键词ID"
    )
    question = Column(Text, nullable=False, comment="问题变体")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 关联关系
    keyword = relationship("Keyword", back_populates="question_variants")

    def __repr__(self):
        return f"<QuestionVariant {self.question[:30]}...>"


class IndexCheckRecord(Base):
    """
    收录检测记录表
    存储AI平台收录检测结果
    """

    __tablename__ = "index_check_records"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    keyword_id = Column(
        Integer, ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False, index=True, comment="关键词ID"
    )
    platform = Column(String(50), nullable=False, comment="检测平台：doubao/qianwen/deepseek")
    question = Column(Text, nullable=False, comment="检测时使用的问题")
    answer = Column(Text, nullable=True, comment="AI回答内容")

    # 检测结果
    keyword_found = Column(Boolean, nullable=True, comment="是否包含关键词")
    company_found = Column(Boolean, nullable=True, comment="是否包含公司名")

    # 收录诊断增强：base.py check() 已算出，原仅存两个布尔，这里补齐以便前后对比与精细化诊断
    check_phase = Column(String(20), default="ongoing", comment="检测阶段：baseline=基线快照 ongoing=日常复测")
    keyword_count = Column(Integer, nullable=True, comment="关键词出现次数")
    company_count = Column(Integer, nullable=True, comment="公司名出现次数")
    company_matched = Column(String(200), nullable=True, comment="实际命中的公司分层词")
    confidence = Column(Float, nullable=True, comment="置信度 0~1")

    # 时间戳
    check_time = Column(DateTime, default=func.now(), comment="检测时间")

    # 关联关系
    keyword = relationship("Keyword", back_populates="index_records")

    def __repr__(self):
        return f"<IndexCheckRecord keyword_id={self.keyword_id} platform={self.platform}>"


class GeoArticle(Base):
    """
    GEO文章表
    存储AI生成的文章及质检信息
    """

    __tablename__ = "geo_articles"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 用户隔离（迁移 0002 添加，此处补齐 ORM 声明）
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属用户ID"
    )

    keyword_id = Column(
        Integer, ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False, index=True, comment="关键词ID"
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True, comment="项目ID"
    )
    title = Column(Text, nullable=True, comment="文章标题")
    content = Column(Text, nullable=False, comment="文章正文内容")

    # 质检相关
    quality_score = Column(Integer, nullable=True, comment="质量评分（0-100）")
    ai_score = Column(Integer, nullable=True, comment="AI味检测分数（0-100，越高越像AI）")
    readability_score = Column(Integer, nullable=True, comment="可读性评分（0-100）")
    quality_status = Column(String(20), default="pending", comment="质检状态：pending=待检查 passed=通过 failed=未通过")

    # 发布相关
    platform = Column(String(50), nullable=True, comment="目标发布平台：仅在配置发布时填写，生成阶段为空")
    account_id = Column(Integer, nullable=True, comment="目标账号ID：仅在配置发布时填写，生成阶段为空")
    publish_status = Column(
        String(20),
        default="draft",
        comment="发布状态：draft=草稿 generating=生成中 completed=已生成待分发 scheduled=已配置定时发布 publishing=发布中 published=已发布 failed=发布失败",
    )
    publish_time = Column(DateTime, nullable=True, comment="发布时间")
    scheduled_at = Column(DateTime, nullable=True, comment="定时发布时间：仅在定时发布时设置")

    # 发布策略字段（新增）
    target_platforms = Column(
        JSON, nullable=True, comment="预设目标平台列表（JSON数组）：如 ['zhihu', 'sohu', 'baijiahao']，用于多平台发布"
    )
    publish_strategy = Column(
        String(20), default="draft", comment="发布策略：draft=仅生成草稿 immediate=生成后立即发布 scheduled=定时发布"
    )

    # 来源与批次（文章管理按来源/批次筛选用）
    source = Column(
        String(30),
        default="manual",
        comment="文章来源：manual=手动 agent_excel=Agent Excel 批量生成 smart_article=智能文章生成",
    )
    generation_batch_id = Column(
        Integer, nullable=True, index=True, comment="批量生成批次ID（ArticleGenerationBatch.id）"
    )

    # 强壮性与重试 (Added back from v1)
    retry_count = Column(Integer, default=0)
    error_msg = Column(Text, nullable=True)
    publish_logs = Column(Text, nullable=True)
    platform_url = Column(String(500), nullable=True)

    # 效果监测 (Added back from v1)
    index_status = Column(String(20), default="uncheck")
    last_check_time = Column(DateTime, nullable=True)
    index_details = Column(Text, nullable=True)

    # 质量风险评估（Phase 5 质量检查流水线）
    fact_risk_score = Column(Integer, nullable=True, comment="事实风险评估 0-100，越低越安全")
    duplication_score = Column(Integer, nullable=True, comment="与历史文章重复度 0-100，越低越原创")
    platform_risk_score = Column(Integer, nullable=True, comment="平台合规风险 0-100，越低越安全")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    keyword = relationship("Keyword", back_populates="articles")
    publish_records = relationship("PublishRecord", back_populates="article", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GeoArticle id={self.id} keyword_id={self.keyword_id}>"


# ==================== 知识库相关表 ====================


class KnowledgeCategory(Base):
    """
    知识库分类表（企业分类）
    存储企业/客户的知识库分类信息
    RAGFlow为主存储，SQLite为缓存
    """

    __tablename__ = "knowledge_categories"
    __table_args__ = TABLE_ARGS

    # 主键（本地ID）
    id = Column(Integer, primary_key=True, autoincrement=True, comment="本地主键ID")

    # 用户隔离（数据归属）：每个用户只看到自己创建的知识库分类
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属用户ID"
    )

    # 关联客户（支持级联删除）
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属客户ID（级联删除）",
    )

    # RAGFlow唯一标识（主数据源）
    ragflow_dataset_id = Column(
        String(100), unique=True, nullable=True, index=True, comment="RAGFlow知识库ID（唯一标识，主数据源）"
    )

    # 元数据字段（从RAGFlow同步的缓存）
    name = Column(String(200), nullable=False, comment="企业/分类名称")
    industry = Column(String(100), nullable=True, comment="所属行业")
    description = Column(Text, nullable=True, comment="分类描述")
    tags = Column(String(500), nullable=True, comment="标签，逗号分隔")
    color = Column(String(20), default="#6366f1", comment="主题颜色")

    # 状态
    status = Column(Integer, default=1, comment="状态：1=活跃 0=停用")

    # 同步状态管理
    sync_status = Column(
        String(20), default="pending", comment="同步状态：pending=待同步 synced=已同步 syncing=同步中 error=同步失败"
    )
    ragflow_synced = Column(Boolean, default=False, comment="是否已同步到RAGFlow（已废弃，使用sync_status）")
    ragflow_synced_at = Column(DateTime, nullable=True, comment="同步时间")
    last_sync_at = Column(DateTime, nullable=True, comment="最后同步时间")

    # 统计字段（从RAGFlow同步）
    knowledge_count = Column(Integer, default=0, comment="知识数量（缓存）")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    items = relationship("Knowledge", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<KnowledgeCategory {self.name} (RAGFlow: {self.ragflow_dataset_id})>"


class Knowledge(Base):
    """
    知识库条目表
    存储企业相关的知识内容
    RAGFlow为主存储，SQLite为缓存
    """

    __tablename__ = "knowledge_items"
    __table_args__ = TABLE_ARGS

    # 主键（本地ID）
    id = Column(Integer, primary_key=True, autoincrement=True, comment="本地主键ID")

    # RAGFlow唯一标识（主数据源）
    ragflow_document_id = Column(
        String(100), unique=True, nullable=True, index=True, comment="RAGFlow文档ID（唯一标识，主数据源）"
    )

    # 关联到RAGFlow知识库
    ragflow_dataset_id = Column(String(100), nullable=False, index=True, comment="所属RAGFlow知识库ID")

    # 向后兼容的外键关系（用于SQLAlchemy关系映射，实际主要使用ragflow_dataset_id）
    category_id = Column(
        Integer,
        ForeignKey("knowledge_categories.id", ondelete="CASCADE"),
        nullable=False,  # 与数据库表结构保持一致
        index=True,
        comment="分类ID（向后兼容，实际主要使用ragflow_dataset_id）",
    )

    # 元数据字段（从RAGFlow同步的缓存）
    title = Column(String(200), nullable=False, comment="知识标题")
    content = Column(Text, nullable=False, comment="知识内容（本地缓存摘要，完整内容在RAGFlow中）")
    type = Column(
        String(50),
        default="other",
        comment="知识类型：company_intro=企业介绍 product=产品服务 industry=行业知识 faq=常见问题 other=其他",
    )

    # 状态
    status = Column(Integer, default=1, comment="状态：1=启用 0=停用")

    # 同步状态管理
    sync_status = Column(
        String(20), default="pending", comment="同步状态：pending=待同步 synced=已同步 syncing=同步中 error=同步失败"
    )
    ragflow_synced = Column(Boolean, default=False, comment="是否已同步到RAGFlow（已废弃，使用sync_status）")
    ragflow_synced_at = Column(DateTime, nullable=True, comment="同步时间")
    ragflow_parsed = Column(Boolean, default=False, comment="文档是否已解析")
    last_sync_at = Column(DateTime, nullable=True, comment="最后同步时间")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系（保留向后兼容）
    category = relationship("KnowledgeCategory", back_populates="items")

    def __repr__(self):
        return f"<Knowledge {self.title} (RAGFlow: {self.ragflow_document_id})>"


# ==================== 用户相关表 ====================


class User(Base):
    """
    用户表
    存储系统用户信息，支持用户认证和角色管理
    """

    __tablename__ = "users"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    username = Column(String(100), nullable=False, unique=True, index=True, comment="用户名")
    email = Column(String(200), nullable=True, unique=True, index=True, comment="邮箱")
    password_hash = Column(String(255), nullable=False, comment="密码哈希（bcrypt）")

    # 角色管理
    role = Column(String(20), default="user", nullable=False, index=True, comment="角色：admin=管理员 user=普通用户")

    # 状态管理
    is_active = Column(Boolean, default=True, nullable=False, index=True, comment="是否激活：True=激活 False=禁用")
    status = Column(Integer, default=1, comment="状态：1=活跃 0=禁用（保留字段，优先使用is_active）")

    # 登录追踪
    last_login = Column(DateTime, nullable=True, comment="最后登录时间")
    login_count = Column(Integer, default=0, comment="登录次数")

    # 安全相关
    failed_login_attempts = Column(Integer, default=0, comment="连续登录失败次数")
    locked_until = Column(DateTime, nullable=True, comment="账户锁定截止时间")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<User {self.username} role={self.role} active={self.is_active}>"

    @property
    def is_admin(self) -> bool:
        """检查是否为管理员"""
        return self.role == "admin"

    @property
    def is_locked(self) -> bool:
        """检查账户是否被锁定"""
        if self.locked_until is None:
            return False
        from datetime import datetime

        return datetime.now() < self.locked_until


# ==================== 系统配置表 ====================


class SystemConfig(Base):
    """
    系统配置表
    存储系统级别的配置项，支持key-value存储和配置分类
    """

    __tablename__ = "system_configs"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 配置键值
    config_key = Column(String(100), nullable=False, unique=True, index=True, comment="配置键（唯一标识符）")
    config_value = Column(Text, nullable=True, comment="配置值（JSON字符串或纯文本）")

    # 配置分类
    category = Column(
        String(50),
        default="general",
        nullable=False,
        index=True,
        comment="配置分类：general=通用 auth=认证 security=安全 email=邮件 storage=存储",
    )

    # 配置描述
    description = Column(Text, nullable=True, comment="配置项描述/说明")

    # 数据类型（用于类型转换提示）
    value_type = Column(
        String(20),
        default="string",
        nullable=False,
        comment="值类型：string=字符串 int=整数 float=浮点数 bool=布尔 json=JSON对象",
    )

    # 是否可编辑
    is_editable = Column(Boolean, default=True, nullable=False, comment="是否可通过界面编辑：True=可编辑 False=只读")

    # 是否敏感配置（如API密钥）
    is_sensitive = Column(
        Boolean, default=False, nullable=False, comment="是否为敏感配置（如密码、密钥）：True=敏感 False=普通"
    )

    # 状态
    is_active = Column(Boolean, default=True, nullable=False, index=True, comment="是否启用：True=启用 False=禁用")

    # 排序权重
    sort_order = Column(Integer, default=0, comment="排序权重（越小越靠前）")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="最后更新用户ID")

    def __repr__(self):
        return f"<SystemConfig {self.config_key}={self.config_value[:30] if self.config_value else None}>"

    def get_value(self):
        """
        根据value_type自动转换并返回配置值
        """
        import json
        from datetime import datetime

        if self.config_value is None:
            return None

        try:
            if self.value_type == "string":
                return self.config_value
            elif self.value_type == "int":
                return int(self.config_value)
            elif self.value_type == "float":
                return float(self.config_value)
            elif self.value_type == "bool":
                return self.config_value.lower() in ("true", "1", "yes", "on")
            elif self.value_type == "json":
                return json.loads(self.config_value)
            else:
                return self.config_value
        except (ValueError, json.JSONDecodeError) as e:
            return self.config_value

    def set_value(self, value):
        """
        根据value_type自动转换并设置配置值
        """
        import json

        if value is None:
            self.config_value = None
            return

        try:
            if self.value_type == "string":
                self.config_value = str(value)
            elif self.value_type == "int":
                self.config_value = str(int(value))
            elif self.value_type == "float":
                self.config_value = str(float(value))
            elif self.value_type == "bool":
                self.config_value = "true" if bool(value) else "false"
            elif self.value_type == "json":
                self.config_value = json.dumps(value, ensure_ascii=False)
            else:
                self.config_value = str(value)
        except (ValueError, TypeError) as e:
            self.config_value = str(value)


# ==================== 参考文章表（爆火文章收集）====================


class ReferenceArticle(Base):
    """
    参考文章表
    存储从各平台采集的爆火/热门文章，用于内容创作参考
    """

    __tablename__ = "reference_articles"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 基本信息
    title = Column(String(500), nullable=False, comment="文章标题")
    url = Column(String(1000), nullable=False, unique=True, comment="原文链接")
    content = Column(Text, nullable=False, comment="文章正文（已清洗）")
    summary = Column(Text, nullable=True, comment="文章摘要")

    # 来源信息
    platform = Column(String(50), nullable=False, index=True, comment="来源平台：zhihu/toutiao等")
    author = Column(String(200), nullable=True, comment="作者名称")
    publish_time = Column(String(50), nullable=True, comment="原文发布时间")

    # 热度指标
    likes = Column(Integer, default=0, comment="点赞数")
    reads = Column(Integer, default=0, comment="阅读量")
    comments = Column(Integer, default=0, comment="评论数")

    # 采集信息
    keyword = Column(String(200), nullable=True, index=True, comment="采集时使用的关键词")
    collected_at = Column(DateTime, default=func.now(), comment="采集时间")

    # RAGFlow 同步状态
    ragflow_synced = Column(Boolean, default=False, comment="是否已同步到RAGFlow")
    ragflow_doc_id = Column(String(100), nullable=True, comment="RAGFlow文档ID")
    ragflow_sync_time = Column(DateTime, nullable=True, comment="RAGFlow同步时间")

    # 状态
    status = Column(Integer, default=1, comment="状态：1=正常 0=已删除")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<ReferenceArticle {self.title[:30]}... ({self.platform})>"


# ==================== AEO网站信息收集表 ====================
class SiteProject(Base):
    __tablename__ = "site_projects"

    id = Column(Integer, primary_key=True, index=True)

    # 用户隔离（迁移 0002 添加，此处补齐 ORM 声明）
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属用户ID"
    )
    name = Column(String, comment="项目名称，如：极速物流官网")
    site_id = Column(String, unique=True, index=True, comment="唯一标识，用于生成路径")

    # 核心配置：存储前端传来的那个大 JSON
    config_data = Column(JSON, comment="网站的全量配置数据")

    # AI 生成模式专用
    source = Column(String(20), default="manual", comment="生成方式：manual=手填 ai=AI生成")
    structured_data = Column(JSON, nullable=True, comment="AI 提取的结构化企业数据（换模板时复用，不重调 AI）")
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联客户ID（AI生成时来源）",
    )
    template_id = Column(String(50), default="tech", comment="使用的模板ID")

    # 状态管理
    deploy_path = Column(String, nullable=True, comment="生成的本地 index.html 路径")
    preview_url = Column(String, nullable=True, comment="本地预览 URL")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ==================== 客户端设备管理 ====================


class ClientDevice(Base):
    """
    客户端设备表
    管理用户的本地客户端设备（Electron 客户端实例）
    """

    __tablename__ = "client_devices"
    # 同一台电脑（同一 device_id）可被多个账号分别登记：每个账号拥有自己的设备记录，
    # 换账号登录不再冲突（多账号共用一台机器是支持的场景）。
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_client_devices_user_device"),
        TABLE_ARGS,
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 归属用户
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户ID",
    )

    # 设备标识
    device_id = Column(
        String(64), nullable=False, index=True, comment="客户端生成的设备ID（同一安装可被多账号分别登记）"
    )
    device_name = Column(String(200), nullable=True, comment="用户可识别的设备名称（如 hostname）")
    os = Column(String(20), nullable=True, comment="操作系统：windows/mac/linux")
    app_version = Column(String(30), nullable=True, comment="客户端版本号")

    # 能力声明
    capabilities = Column(JSON, nullable=True, comment="支持的平台和能力，如 {local_publish:true, platforms:[...]}")

    # 状态
    status = Column(String(20), default="offline", comment="设备状态：online/offline/disabled")

    # 时间戳
    last_seen_at = Column(DateTime, nullable=True, comment="最后心跳时间")
    created_at = Column(DateTime, default=func.now(), comment="注册时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    owner = relationship("User", backref="client_devices", foreign_keys=[user_id])

    def __repr__(self):
        return f"<ClientDevice device_id={self.device_id} status={self.status}>"


# ==================== 自动发布任务系统 ====================


class AutoPublishTask(Base):
    """
    自动发布任务表
    用于管理用户创建的后台发布任务队列
    """

    __tablename__ = "auto_publish_tasks"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 任务基本信息
    name = Column(String(200), nullable=False, comment="任务名称")
    description = Column(Text, nullable=True, comment="任务描述")

    # 发布配置（JSON格式存储文章和账号ID列表）
    article_ids = Column(JSON, nullable=False, comment="文章ID列表 [1,2,3]")
    account_ids = Column(JSON, nullable=False, comment="账号ID列表 [1,2,3]")
    # 任务涉及的平台列表（持久化，避免账号被删/禁用后丢失平台信息）
    platforms = Column(JSON, nullable=True, comment="平台列表 ['zhihu','baidu']")

    # 发布选项
    declare_ai_content = Column(Boolean, default=True, comment="是否勾选AI创作内容声明")

    # 数据归属（权限隔离：列表/详情/操作按此列过滤，admin 可见全部）
    # 与 triggered_by_user_id（审计/追溯用，可能因用户删除而置空）分开，
    # 避免归属判断受外键级联影响。
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="数据归属用户ID（权限隔离用）",
    )

    # 触发信息
    triggered_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="触发此任务的系统用户ID",
    )
    feishu_event_id = Column(
        String(200),
        nullable=True,
        comment="关联的飞书事件ID（可追溯）",
    )

    # 任务状态
    status = Column(
        String(20),
        default="pending",
        comment="任务状态：pending=待执行 running=执行中 completed=已完成 failed=失败 cancelled=已取消",
    )

    # 执行类型
    exec_type = Column(
        String(20), default="immediate", comment="执行类型：immediate=立即执行 scheduled=定时执行 interval=间隔执行"
    )

    # 本地客户端发布（Phase 0：本地客户端架构）
    execution_mode = Column(
        String(20),
        default="cloud_browser",
        comment="执行模式：local_client=本地客户端 cloud_browser=服务器浏览器 api=官方API manual=仅草稿",
    )
    assigned_device_id = Column(String(64), nullable=True, index=True, comment="指定执行设备ID")
    claimed_by_device_id = Column(String(64), nullable=True, comment="实际领取设备ID")
    claim_expires_at = Column(DateTime, nullable=True, comment="任务领取锁过期时间")
    manual_required = Column(Boolean, default=False, comment="是否需要人工接管")
    manual_message = Column(Text, nullable=True, comment="人工接管原因")

    # 定时配置
    scheduled_at = Column(DateTime, nullable=True, comment="计划执行时间")
    interval_minutes = Column(Integer, nullable=True, comment="间隔执行分钟数")

    # 执行结果
    total_count = Column(Integer, default=0, comment="总发布任务数（文章数×账号数）")
    completed_count = Column(Integer, default=0, comment="已完成数量")
    failed_count = Column(Integer, default=0, comment="失败数量")

    # 错误信息
    error_msg = Column(Text, nullable=True, comment="错误信息")
    last_error_at = Column(DateTime, nullable=True, comment="最后错误时间")

    # 执行时间
    started_at = Column(DateTime, nullable=True, comment="实际开始时间")
    completed_at = Column(DateTime, nullable=True, comment="实际完成时间")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系：一对多，级联删除子记录
    records = relationship(
        "AutoPublishRecord", back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self):
        return f"<AutoPublishTask {self.name} status={self.status}>"


class AutoPublishRecord(Base):
    """
    自动发布子任务记录表
    记录每个自动发布任务中的单次发布结果
    """

    __tablename__ = "auto_publish_records"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 关联自动发布任务
    task_id = Column(
        Integer,
        ForeignKey("auto_publish_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属自动发布任务ID",
    )

    # 发布目标和内容
    article_id = Column(
        Integer, ForeignKey("geo_articles.id", ondelete="CASCADE"), nullable=False, index=True, comment="文章ID"
    )
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True, comment="账号ID"
    )

    # 发布状态
    status = Column(
        String(20),
        default="pending",
        comment="状态：pending=待发布 publishing=发布中 manual_required=人工接管 success=成功 failed=失败 skipped=跳过",
    )

    # 发布结果
    platform_url = Column(String(500), nullable=True, comment="发布后的文章链接")
    error_msg = Column(Text, nullable=True, comment="错误信息")

    # 重试信息
    retry_count = Column(Integer, default=0, comment="重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    # 关联关系
    # 艹！级联删除配置：删除任务时自动删除关联的发布记录
    task = relationship("AutoPublishTask", back_populates="records")
    article = relationship("GeoArticle")
    account = relationship("Account")

    def __repr__(self):
        return f"<AutoPublishRecord task_id={self.task_id} article_id={self.article_id} status={self.status}>"


# ==================== 发布审批相关表（Phase 1：服务器审批式发布）====================


class PublishApprovalLog(Base):
    """
    发布审批日志表

    每次客户端请求发布审批（before_write / before_fill_body / before_submit）
    都写入一行，无论通过还是拒绝。

    用于：
      - 审计（谁在什么时候发布什么到哪个平台）
      - 排查（客户端显示"服务器拒绝"，运营能查到对应日志）
      - 安全（异常行为模式分析）
    """

    __tablename__ = "publish_approval_logs"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("auto_publish_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    record_id = Column(Integer, ForeignKey("auto_publish_records.id", ondelete="SET NULL"), nullable=True, index=True)
    device_id = Column(String(64), nullable=True, index=True)

    # 审批检查点
    checkpoint = Column(
        String(30),
        nullable=False,
        comment="审批检查点: before_write / before_fill_body / before_submit",
    )

    # 审批结果
    approved = Column(Boolean, nullable=False, server_default="false")
    reason_code = Column(String(50), nullable=True, comment="拒绝原因代码")
    reason = Column(String(500), nullable=True, comment="拒绝原因描述")

    # 审批令牌（仅通过时记录）
    approval_token = Column(String(100), nullable=True, comment="审批通过时的一次性令牌")
    expires_at = Column(DateTime, nullable=True, comment="令牌过期时间")

    # 审计字段
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(String(200), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)

    def __repr__(self):
        return (
            f"<PublishApprovalLog user={self.user_id} task={self.task_id} {self.checkpoint} approved={self.approved}>"
        )


class UserPublishQuota(Base):
    """
    用户发布配额表

    控制每个用户每天/每月能发布多少条。
    未创建配额记录的用户视为无限（向后兼容老用户）。

    设计为一人一条（user_id 唯一），运行时自动重置计数。
    """

    __tablename__ = "user_publish_quotas"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
        comment="所属系统用户ID",
    )

    # 套餐级别
    tier = Column(String(20), server_default="free", comment="套餐级别: free / pro / enterprise")

    # 配额上限
    daily_limit = Column(Integer, server_default="50", comment="每日发布上限")
    monthly_limit = Column(Integer, server_default="1000", comment="每月发布上限")

    # 已使用计数
    used_today = Column(Integer, server_default="0", comment="今日已使用次数")
    used_this_month = Column(Integer, server_default="0", comment="本月已使用次数")

    # 重置时间戳
    reset_date = Column(Date, nullable=True, comment="今日计数上次重置日期")
    month_reset_date = Column(Date, nullable=True, comment="本月计数上次重置月份")

    # 平台白名单(空/None = 全部允许)
    platform_whitelist = Column(JSON, nullable=True, comment="允许发布的平台列表")

    # 时间戳
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<UserPublishQuota user={self.user_id} tier={self.tier} today={self.used_today}/{self.daily_limit}>"


# ==================== 账号分组表 ====================


class AccountGroup(Base):
    """
    账号分组表
    用于对平台账号进行分组管理
    """

    __tablename__ = "account_groups"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name = Column(String(100), nullable=False, comment="分组名称")
    icon = Column(String(50), nullable=True, comment="分组图标")
    color = Column(String(20), default="#409EFF", comment="分组颜色")

    # 归属用户
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属用户ID"
    )

    # 排序与状态
    sort_order = Column(Integer, default=0, comment="排序权重（越小越靠前）")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    accounts = relationship("Account", back_populates="group", foreign_keys="Account.group_id")
    owner = relationship("User", backref="account_groups", foreign_keys=[user_id])

    def __repr__(self):
        return f"<AccountGroup {self.name} (user_id={self.user_id})>"


# ==================== 账号操作日志表 ====================


class AccountOperationLog(Base):
    """
    账号操作日志表
    记录对平台账号的所有关键操作
    """

    __tablename__ = "account_operation_logs"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 关联账号和用户
    account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True, comment="账号ID"
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="操作用户ID"
    )

    # 操作类型
    operation = Column(
        String(50),
        nullable=False,
        index=True,
        comment="操作类型：create/update/delete/auth_start/auth_success/auth_fail/check_pass/check_fail",
    )

    # 操作详情
    detail = Column(JSON, nullable=True, comment="操作详情（JSON）")
    ip_address = Column(String(50), nullable=True, comment="操作IP地址")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="操作时间")

    # 关联关系
    account = relationship("Account", backref="operation_logs")
    user = relationship("User", backref="account_operation_logs")

    def __repr__(self):
        return f"<AccountOperationLog {self.operation} account_id={self.account_id}>"


# ==================== 飞书用户绑定表 ====================


class FeishuUserBinding(Base):
    """
    飞书用户绑定表
    将飞书 open_id 映射到系统用户，实现用户级闭环
    """

    __tablename__ = "feishu_user_bindings"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 飞书身份
    open_id = Column(String(200), nullable=False, unique=True, index=True, comment="飞书用户 open_id")
    union_id = Column(String(200), nullable=True, comment="飞书 union_id（跨应用统一标识）")

    # 系统用户绑定
    system_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定的系统用户ID",
    )

    # 默认配置
    default_client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        comment="默认客户ID",
    )
    default_project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        comment="默认项目ID",
    )

    # 状态
    status = Column(Integer, default=1, comment="绑定状态：1=已绑定 0=已解绑")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="绑定时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    user = relationship("User", backref="feishu_bindings", foreign_keys=[system_user_id])

    def __repr__(self):
        return f"<FeishuUserBinding open_id={self.open_id} user_id={self.system_user_id}>"


# ==================== 飞书事件表 ====================


class FeishuEvent(Base):
    """
    飞书事件持久化表
    记录所有从飞书接收到的 Webhook 事件，用于幂等去重和排查
    """

    __tablename__ = "feishu_events"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 事件标识
    event_id = Column(String(200), nullable=False, unique=True, index=True, comment="飞书事件唯一ID")
    message_id = Column(String(200), nullable=True, comment="飞书消息ID")

    # 来源信息
    open_id = Column(String(200), nullable=True, index=True, comment="发送者 open_id")
    chat_id = Column(String(200), nullable=True, comment="会话ID")
    event_type = Column(String(100), nullable=True, comment="事件类型")

    # 原始数据
    raw_payload = Column(Text, nullable=True, comment="原始请求体（JSON）")
    raw_text = Column(Text, nullable=True, comment="提取的用户消息文本")

    # 处理状态
    status = Column(
        String(20),
        default="received",
        comment="处理状态：received=已接收 processing=处理中 processed=已处理 error=处理失败",
    )
    error_msg = Column(Text, nullable=True, comment="处理错误信息")

    # 时间戳
    created_at = Column(DateTime, default=func.now(), comment="接收时间")
    processed_at = Column(DateTime, nullable=True, comment="处理完成时间")

    def __repr__(self):
        return f"<FeishuEvent event_id={self.event_id} status={self.status}>"


# ==================== 关键词使用记录表 ====================


class KeywordUsageRecord(Base):
    """
    关键词使用记录表
    追踪关键词被用于文章生成的历史，支持加权随机选择时的新鲜度惩罚
    """

    __tablename__ = "keyword_usage_records"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 关联信息
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属项目ID",
    )
    keyword_id = Column(
        Integer,
        ForeignKey("keywords.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关键词ID",
    )
    keyword_text = Column(String(200), nullable=False, comment="关键词文本（冗余字段，方便查询）")

    # 文章关联
    article_id = Column(
        Integer,
        ForeignKey("geo_articles.id", ondelete="SET NULL"),
        nullable=True,
        comment="生成的文章ID",
    )

    # 来源与操作人
    source = Column(String(50), default="auto", comment="使用来源：feishu=飞书触发 manual=手动 api=API auto=自动调度")
    used_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="触发使用的用户ID",
    )

    # 时间戳
    used_at = Column(DateTime, default=func.now(), comment="使用时间")

    def __repr__(self):
        return f"<KeywordUsageRecord keyword={self.keyword_text} article_id={self.article_id}>"


# ==================== 项目成员表 ====================


class ProjectMember(Base):
    """
    项目成员表
    记录用户对项目的权限，支持团队协作场景
    """

    __tablename__ = "project_members"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目ID",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    role = Column(
        String(20),
        default="owner",
        comment="角色：owner=拥有者 editor=编辑者 viewer=观察者",
    )
    status = Column(Integer, default=1, comment="状态：1=正常 0=已移除")

    created_at = Column(DateTime, default=func.now(), comment="添加时间")

    # 关联关系
    project = relationship("Project", backref="members")
    user = relationship("User", backref="project_memberships")

    def __repr__(self):
        return f"<ProjectMember project_id={self.project_id} user_id={self.user_id} role={self.role}>"


# ==================== Agent 会话记忆表 ====================


class ConversationSession(Base):
    """
    Agent 会话表
    保存后台/Web/外部平台对话的结构化任务状态。
    """

    __tablename__ = "conversation_sessions"
    __table_args__ = TABLE_ARGS

    id = Column(String(120), primary_key=True, comment="会话ID")
    source = Column(String(50), default="web", index=True, comment="来源：web/feishu/openclaw")
    channel = Column(String(50), default="web", index=True, comment="通道：web/feishu/other")
    system_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="系统用户ID",
    )
    external_user_id = Column(String(200), nullable=True, index=True, comment="外部用户ID")
    external_chat_id = Column(String(200), nullable=True, index=True, comment="外部会话ID")
    status = Column(
        String(30),
        default="active",
        index=True,
        comment="active/waiting_user/running/confirm_required/completed/failed/cancelled",
    )
    current_intent = Column(String(80), nullable=True, index=True, comment="当前意图")
    slots = Column(JSON, nullable=True, comment="结构化任务槽位")
    summary = Column(Text, nullable=True, comment="会话摘要")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")
    expires_at = Column(DateTime, nullable=True, comment="过期时间")
    title = Column(String(120), nullable=True, comment="会话标题，用于列表展示")

    user = relationship("User", backref="conversation_sessions", foreign_keys=[system_user_id])
    messages = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<ConversationSession id={self.id} user_id={self.system_user_id} status={self.status}>"


class ConversationMessage(Base):
    """
    Agent 消息表
    保存完整 message history，用于回放、审计和后续 LLM 上下文。
    """

    __tablename__ = "conversation_messages"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    conversation_id = Column(
        String(120),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID",
    )
    role = Column(String(30), nullable=False, index=True, comment="user/assistant/system/tool")
    content = Column(Text, nullable=False, comment="消息内容")
    message_metadata = Column(JSON, nullable=True, comment="消息元数据")
    created_at = Column(DateTime, default=func.now(), index=True, comment="创建时间")

    session = relationship("ConversationSession", back_populates="messages")

    def __repr__(self):
        return f"<ConversationMessage conversation_id={self.conversation_id} role={self.role}>"


# ==================== 用户长期 Agent 偏好表 ====================


class UserAgentPreference(Base):
    """
    用户长期 Agent 偏好
    保存默认项目、默认平台、发布前是否必须确认、语气偏好等长期设置。
    一人一条（system_user_id 唯一）。
    """

    __tablename__ = "user_agent_preferences"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    system_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="系统用户ID（一人一条）",
    )
    default_project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="默认项目ID",
    )
    default_platforms = Column(JSON, nullable=True, comment="默认发布平台列表")
    default_publish_strategy = Column(
        String(30),
        nullable=True,
        comment="默认发布策略：immediate/review_first",
    )
    require_confirmation_before_publish = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="发布前是否必须人工确认",
    )
    tone_preference = Column(String(50), nullable=True, comment="语气偏好")
    # 新用户主动引导：用户点「跳过」或完成接入后置 True，不再主动打扰
    onboarding_dismissed = Column(Boolean, default=False, nullable=False, comment="是否已关闭新用户引导")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", backref="agent_preference", foreign_keys=[system_user_id])

    def __repr__(self):
        return f"<UserAgentPreference user_id={self.system_user_id}>"


# ==================== Agent V2 用户长期事实表 ====================


class UserAgentFact(Base):
    """Agent V2 用户长期事实表。

    保存跨会话事实：公司/行业/常选平台/默认 client_id 等。
    一人一条（system_user_id 唯一）。与 UserAgentPreference（偏好）分离：
    - facts = 客观事实（公司名、行业、常选平台）
    - preferences = 主观偏好（语气、确认策略）
    """

    __tablename__ = "user_agent_facts"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    system_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="系统用户ID（一人一条）",
    )
    facts = Column(JSON, nullable=True, comment="用户长期事实 JSON")
    onboarding_stage = Column(String(50), nullable=True, comment="引导流程当前阶段")
    onboarding_completed = Column(Boolean, default=False, nullable=False, comment="引导是否已完成")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    user = relationship("User", backref="agent_facts", foreign_keys=[system_user_id])

    def __repr__(self):
        return f"<UserAgentFact user_id={self.system_user_id} onboarding={self.onboarding_stage}>"


# ==================== 浏览器插件绑定表 ====================


class ExtensionPairingCode(Base):
    """
    插件绑定码表
    临时绑定码，用户在 AutoGeo Web 生成后输入到浏览器插件完成绑定
    """

    __tablename__ = "extension_pairing_codes"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    code = Column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
        comment="绑定码（6位随机字符）",
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="待绑定的系统用户ID",
    )

    platform = Column(
        String(50),
        nullable=True,
        comment="目标平台：doubao/qianwen/deepseek 或 NULL 表示通用",
    )

    scene = Column(
        String(50),
        nullable=True,
        comment="场景：account_auth/index_monitor 等",
    )

    status = Column(
        Integer,
        default=0,
        comment="状态：0=待使用 1=已使用 -1=已过期",
    )

    expires_at = Column(
        DateTime,
        nullable=False,
        comment="过期时间（生成后5分钟有效）",
    )

    used_at = Column(DateTime, nullable=True, comment="使用时间")
    created_at = Column(DateTime, default=func.now(), comment="生成时间")

    # 关联关系
    user = relationship("User", backref="extension_pairing_codes", foreign_keys=[user_id])

    def __repr__(self):
        return f"<ExtensionPairingCode code={self.code} user_id={self.user_id} status={self.status}>"


class BrowserExtensionBinding(Base):
    """
    浏览器插件绑定表
    记录插件和用户的绑定关系，用 extension_token (hash) 进行鉴权
    """

    __tablename__ = "browser_extension_bindings"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定的系统用户ID",
    )

    extension_id = Column(
        String(200),
        nullable=False,
        comment="Chrome Extension ID (chrome.runtime.id)",
    )

    device_name = Column(
        String(200),
        nullable=True,
        comment="设备名称：如 'Chrome on Windows'",
    )

    token_hash = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="extension_token 的 SHA256 hash（不存明文）",
    )

    last_seen_at = Column(DateTime, nullable=True, comment="最后活跃时间")

    revoked_at = Column(DateTime, nullable=True, comment="撤销时间（NULL=有效）")

    created_at = Column(DateTime, default=func.now(), comment="绑定时间")

    # 关联关系
    user = relationship("User", backref="browser_extension_bindings", foreign_keys=[user_id])

    def __repr__(self):
        return f"<BrowserExtensionBinding user_id={self.user_id} extension_id={self.extension_id} revoked={self.revoked_at is not None}>"


# ==================== 飞书绑定码表 ====================


class FeishuBindingCode(Base):
    """
    飞书绑定码表
    临时绑定码，用户在管理后台生成后通过飞书发送完成绑定
    """

    __tablename__ = "feishu_binding_codes"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    code = Column(
        String(20),
        nullable=False,
        unique=True,
        index=True,
        comment="绑定码（6位随机字符）",
    )

    system_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="待绑定的系统用户ID",
    )

    status = Column(
        Integer,
        default=0,
        comment="状态：0=待使用 1=已使用 -1=已过期",
    )

    used_by_open_id = Column(
        String(200),
        nullable=True,
        comment="使用此码的飞书 open_id",
    )

    expires_at = Column(
        DateTime,
        nullable=False,
        comment="过期时间（生成后30分钟有效）",
    )

    created_at = Column(DateTime, default=func.now(), comment="生成时间")
    used_at = Column(DateTime, nullable=True, comment="使用时间")

    # 关联关系
    user = relationship("User", backref="feishu_binding_codes", foreign_keys=[system_user_id])

    def __repr__(self):
        return f"<FeishuBindingCode code={self.code} user_id={self.system_user_id} status={self.status}>"


# ==================== Excel 批量文章生成相关表 ====================


class AgentExcelImportBatch(Base):
    """后台智能体 Excel 导入批次表。

    用户上传一份 Excel 后生成一条批次记录，承载解析、行级校验、统计与状态流转。
    批次本身按 user_id 隔离；下属行（AgentExcelImportRow）通过 batch 归属间接隔离。
    """

    __tablename__ = "agent_excel_import_batches"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="上传用户ID（数据隔离）",
    )

    file_name = Column(String(500), nullable=True, comment="原始文件名")
    file_hash = Column(String(64), nullable=True, index=True, comment="文件 SHA256，用于去重/追溯")

    # 状态：uploaded → validating → ready → processing → completed → partial_failed / failed
    status = Column(String(20), default="uploaded", comment="批次状态")

    total_rows = Column(Integer, default=0, comment="总行数（不含表头）")
    valid_rows = Column(Integer, default=0, comment="有效行数")
    invalid_rows = Column(Integer, default=0, comment="无效行数（缺必填字段等）")

    default_article_count = Column(Integer, default=5, comment="默认每个项目生成篇数")

    # 字段映射快照（{canonical_field: excel_header}）+ 行级错误明细
    field_mapping = Column(JSON, nullable=True, comment="解析出的字段映射")
    error_report = Column(JSON, nullable=True, comment="行级错误汇总 JSON")

    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    rows = relationship(
        "AgentExcelImportRow", back_populates="batch", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self):
        return f"<AgentExcelImportBatch id={self.id} status={self.status} valid={self.valid_rows}>"


class AgentExcelImportRow(Base):
    """Excel 导入行表：每一行对应一个「公司+项目」的生成任务候选。

    status：valid（可生成）/ invalid（缺必填字段）/ processed（已建客户/项目）/ failed
    raw_data 保留原始单元格值；normalized_data 保留按 canonical 字段标准化后的值。
    """

    __tablename__ = "agent_excel_import_rows"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    batch_id = Column(
        Integer,
        ForeignKey("agent_excel_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属导入批次",
    )

    row_index = Column(Integer, nullable=False, comment="Excel 行号（含表头，通常从 2 开始）")

    raw_data = Column(JSON, nullable=True, comment="原始单元格值（表头→值）")
    normalized_data = Column(JSON, nullable=True, comment="标准化数据（canonical_field→值）")

    # 匹配/创建后回填（阶段3）
    client_id = Column(Integer, nullable=True, index=True, comment="匹配/创建的客户ID")
    project_id = Column(Integer, nullable=True, index=True, comment="匹配/创建的项目ID")

    status = Column(String(20), default="valid", comment="valid/invalid/processed/failed")
    error_msg = Column(Text, nullable=True, comment="校验/处理错误信息")

    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    batch = relationship("AgentExcelImportBatch", back_populates="rows")

    def __repr__(self):
        return f"<AgentExcelImportRow batch_id={self.batch_id} row={self.row_index} status={self.status}>"


class ArticleGenerationBatch(Base):
    """文章批量生成批次表。

    一个导入批次可派生多个生成批次（按项目/篇数）。批次状态由下属 job 状态汇总。
    """

    __tablename__ = "article_generation_batches"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="归属用户ID（数据隔离）",
    )
    import_batch_id = Column(
        Integer,
        ForeignKey("agent_excel_import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="来源 Excel 导入批次",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="项目ID（单项目批次时填；多项目由 job 记录）",
    )
    project_ids = Column(
        JSON,
        nullable=True,
        comment="多项目批次 project_id 列表（非 Excel 来源，如「每个项目各生成 N 篇」）",
    )

    source = Column(String(30), default="agent_excel", comment="生成来源：agent_excel/manual/agent_batch")
    requested_count = Column(Integer, default=5, comment="期望生成篇数（总）")
    article_count = Column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
        comment="每项目生成篇数（生成时设定，覆盖 Excel 列；execute_batch 据此为每项目蒸馏问题）",
    )
    queued_count = Column(Integer, default=0, comment="入队任务数")
    success_count = Column(Integer, default=0, comment="成功数量")
    failed_count = Column(Integer, default=0, comment="失败数量")

    # pending → preparing_questions → generating → waiting_callback → completed / partial_failed / failed
    status = Column(String(30), default="pending", comment="批次状态")
    note = Column(Text, nullable=True, comment="备注（如补蒸馏后仍不足的原因）")

    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    jobs = relationship(
        "ArticleGenerationJob", back_populates="batch", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self):
        return f"<ArticleGenerationBatch id={self.id} status={self.status} ok={self.success_count}>"


class ArticleGenerationJob(Base):
    """文章批量生成任务表：一个搜索问题 → 一篇文章。

    幂等键 idempotency_key = sha256(user_id + project_id + keyword_id + generation_profile)
    防止同一搜索问题重复生成。
    """

    __tablename__ = "article_generation_jobs"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    batch_id = Column(
        Integer,
        ForeignKey("article_generation_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属生成批次",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="归属用户ID",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="项目ID",
    )
    keyword_id = Column(
        Integer,
        ForeignKey("keywords.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="搜索问题（keyword_type=question）ID",
    )

    article_id = Column(Integer, nullable=True, index=True, comment="生成成功的文章ID")
    idempotency_key = Column(String(64), nullable=True, index=True, comment="幂等键")

    # pending → triggering → waiting_callback（等回调）→ completed / failed / skipped
    status = Column(String(20), default="pending", comment="任务状态")
    attempt_count = Column(Integer, default=0, comment="已尝试次数（触发失败自动重试用）")
    max_attempts = Column(Integer, default=2, comment="最大尝试次数（含首次）")
    error_msg = Column(Text, nullable=True, comment="失败原因")
    last_error_at = Column(DateTime, nullable=True, comment="最后错误时间")

    queued_at = Column(DateTime, default=func.now(), comment="入队时间")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")

    batch = relationship("ArticleGenerationBatch", back_populates="jobs")

    def __repr__(self):
        return f"<ArticleGenerationJob batch_id={self.batch_id} keyword_id={self.keyword_id} status={self.status}>"


# ==================== 智能文章生成相关表 ====================


class SmartArticleQuestion(Base):
    """智能文章项目问题池。

    问题与文章任务分离保存：问题可以先被规划和展示，之后再由用户选择生成文章。
    删除采用软删除，保证历史问题仍可参与去重。
    """

    __tablename__ = "smart_article_questions"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_question", name="uq_smart_article_questions_project_question"),
        TABLE_ARGS,
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    generation_batch_id = Column(
        Integer, ForeignKey("smart_article_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    question = Column(Text, nullable=False)
    normalized_question = Column(String(255), nullable=False)
    source = Column(String(20), nullable=False, default="ai", comment="ai/manual")
    intent_type = Column(String(30), nullable=False, default="manual")
    context_type = Column(String(20), nullable=False, default="general")
    brand_entry_reason = Column(Text, nullable=True)
    retrieval_terms = Column(JSON, nullable=True)
    has_article = Column(Boolean, nullable=False, default=False, index=True)
    article_id = Column(Integer, ForeignKey("geo_articles.id", ondelete="SET NULL"), nullable=True, index=True)
    article_generation_status = Column(String(20), nullable=False, default="idle")
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    jobs = relationship("SmartArticleJob", back_populates="question_record")
    evaluation_prompts = relationship("GeoPrompt", back_populates="smart_article_question")

    def __repr__(self):
        return f"<SmartArticleQuestion project_id={self.project_id} question={self.question[:24]!r}>"


class SmartArticleBatch(Base):
    """智能文章生成批次。与 Excel 批量生成完全隔离。"""

    __tablename__ = "smart_article_batches"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_type = Column(
        String(30), nullable=False, default="article_generation", comment="question_generation/article_generation"
    )
    mode = Column(String(20), nullable=False, default="auto", comment="auto/manual")
    requested_count = Column(Integer, nullable=False, default=1)
    planned_count = Column(Integer, nullable=False, default=0)
    queued_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="pending")
    input_question = Column(Text, nullable=True)
    question_prompt_version = Column(String(50), nullable=True)
    filter_prompt_version = Column(String(50), nullable=True)
    query_rewrite_prompt_version = Column(String(50), nullable=True)
    article_prompt_version = Column(String(50), nullable=True)
    expanded_terms = Column(JSON, nullable=True, comment="问题生成时AI拓展的相关表达")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)

    jobs = relationship("SmartArticleJob", back_populates="batch", cascade="all, delete-orphan", passive_deletes=True)

    def __repr__(self):
        return f"<SmartArticleBatch id={self.id} status={self.status} ok={self.success_count}>"


class SmartArticleJob(Base):
    """智能文章生成任务：一个最终用户问题对应一篇文章。"""

    __tablename__ = "smart_article_jobs"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("smart_article_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(
        Integer,
        ForeignKey("smart_article_questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question = Column(Text, nullable=False)
    intent_type = Column(String(30), nullable=False, default="manual")
    context_type = Column(String(20), nullable=False, default="general")
    brand_entry_reason = Column(Text, nullable=True)
    retrieval_terms = Column(JSON, nullable=True)
    initial_queries = Column(JSON, nullable=True)
    retrieval_queries = Column(JSON, nullable=True)
    retrieval_rounds = Column(Integer, nullable=False, default=0)
    query_rewrite_used = Column(Boolean, nullable=False, default=False)
    query_rewrite_prompt_version = Column(String(50), nullable=True)
    retrieval_raw_count = Column(Integer, nullable=False, default=0)
    retrieval_valid_count = Column(Integer, nullable=False, default=0)
    knowledge_enabled = Column(Boolean, nullable=False, default=False)
    knowledge_refs = Column(JSON, nullable=True)
    keyword_id = Column(Integer, ForeignKey("keywords.id", ondelete="SET NULL"), nullable=True, index=True)
    article_id = Column(Integer, nullable=True, index=True)
    idempotency_key = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(30), nullable=False, default="pending")
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    error_msg = Column(Text, nullable=True)
    queued_at = Column(DateTime, default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    batch = relationship("SmartArticleBatch", back_populates="jobs")
    question_record = relationship("SmartArticleQuestion", back_populates="jobs")

    def __repr__(self):
        return f"<SmartArticleJob batch_id={self.batch_id} question={self.question[:20]!r} status={self.status}>"


# ==================== GEO 五指标测评相关表 ====================


class GeoPromptSet(Base):
    """GEO 测评问题集表

    记录公司的一套测评问题集。一个公司可以有多套问题集，
    但同一时间只使用一套 active。baseline 使用的问题集必须 frozen。
    """

    __tablename__ = "geo_prompt_sets"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    # 测评粒度改为公司级别
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属公司ID",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联项目ID（用于内容追踪，可为空）",
    )
    name = Column(String(200), nullable=True, comment="问题集名称")
    question_count = Column(Integer, default=100, comment="问题数量")
    question_distribution = Column(JSON, nullable=True, comment="问题类型分布：{type: count}")
    generation_model = Column(String(100), nullable=True, comment="生成使用的模型")
    generation_prompt = Column(Text, nullable=True, comment="生成提示词")
    status = Column(
        String(20),
        default="active",
        comment="状态：active=当前使用 archived=已归档 frozen=已冻结",
    )
    version = Column(Integer, default=1, comment="版本号")
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者用户ID",
    )
    frozen_at = Column(DateTime, nullable=True, comment="冻结时间")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    client = relationship("Client", backref="geo_prompt_sets")
    project = relationship("Project", backref="geo_prompt_sets")
    prompts = relationship("GeoPrompt", back_populates="prompt_set", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GeoPromptSet id={self.id} client_id={self.client_id} status={self.status}>"


class GeoPrompt(Base):
    """GEO 测评问题表

    保存具体的测评问题。不要复用 Keyword 表，GEO 测评问题应有独立类型和版本管理。
    """

    __tablename__ = "geo_prompts"
    __table_args__ = (
        UniqueConstraint(
            "prompt_set_id",
            "smart_article_question_id",
            name="uq_geo_prompts_set_smart_question",
        ),
        TABLE_ARGS,
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    prompt_set_id = Column(
        Integer,
        ForeignKey("geo_prompt_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属问题集ID",
    )
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属公司ID",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联项目ID（可为空）",
    )
    smart_article_question_id = Column(
        Integer,
        ForeignKey("smart_article_questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="来源智能文章问题ID",
    )
    # 业务维度：问题中涉及的项目名称（如涉及多个项目则用逗号分隔）
    related_project_name = Column(String(500), nullable=True, comment="问题涉及的项目名称")
    question = Column(Text, nullable=False, comment="测评问题")
    question_type = Column(
        String(30),
        nullable=False,
        default="recommendation",
        comment="问题类型：recommendation/scenario/comparison/business_understanding/reputation/brand_awareness",
    )
    intent_tags = Column(JSON, nullable=True, comment="意图标签")
    competitor_names = Column(JSON, nullable=True, comment="竞品名称列表")
    sort_order = Column(Integer, default=0, comment="排序序号")
    status = Column(String(20), default="active", comment="状态：active/inactive")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    prompt_set = relationship("GeoPromptSet", back_populates="prompts")
    client = relationship("Client")
    project = relationship("Project")
    smart_article_question = relationship("SmartArticleQuestion", back_populates="evaluation_prompts")
    evaluation_records = relationship("GeoEvaluationRecord", back_populates="prompt", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GeoPrompt id={self.id} type={self.question_type}>"


class GeoEvaluationRun(Base):
    """GEO 测评任务表

    记录一次 baseline 或 ongoing 测评任务。前端按钮触发后创建 run，
    任务进度从该表读取。公司级别粒度。
    """

    __tablename__ = "geo_evaluation_runs"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    # 公司级别粒度
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属公司ID",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联项目ID（可为空，用于生成部分业务问题）",
    )
    prompt_set_id = Column(
        Integer,
        ForeignKey("geo_prompt_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="使用的问题集ID",
    )
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="本次测评固定使用的授权账户",
    )
    phase = Column(
        String(20),
        nullable=False,
        comment="检测阶段：baseline=使用前基线 ongoing=使用后复测",
    )
    platforms = Column(JSON, nullable=True, comment="检测平台列表，如 ['doubao', 'qianwen']")
    prompt_ids = Column(JSON, nullable=True, comment="本次任务固定使用的问题ID列表")
    rounds = Column(Integer, default=1, comment="测试轮数")
    status = Column(
        String(20),
        default="pending",
        comment="任务状态：pending/running/completed/failed/cancelled",
    )
    total_planned = Column(Integer, default=0, comment="计划检测总数")
    total_completed = Column(Integer, default=0, comment="已完成数")
    total_failed = Column(Integer, default=0, comment="失败数")
    current_platform = Column(String(50), nullable=True, comment="当前正在执行的平台")
    current_round = Column(Integer, nullable=True, comment="当前轮次")
    current_progress = Column(Integer, default=0, comment="当前进度(已提问数)")
    claimed_device_id = Column(String(64), nullable=True, index=True, comment="领取任务的本地客户端设备ID")
    heartbeat_at = Column(DateTime, nullable=True, comment="本地客户端最近一次任务心跳")
    interruption_reason = Column(
        String(50), nullable=True, comment="中断原因：client_offline/consecutive_failures/client_error"
    )
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="完成时间")
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者用户ID",
    )
    error_message = Column(Text, nullable=True, comment="错误信息")
    evaluation_schema_version = Column(String(20), nullable=True, comment="评估规则版本")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 关联关系
    client = relationship("Client")
    project = relationship("Project")
    prompt_set = relationship("GeoPromptSet", backref="evaluation_runs")
    account = relationship("Account")
    records = relationship("GeoEvaluationRecord", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GeoEvaluationRun id={self.id} phase={self.phase} status={self.status}>"


class GeoEvaluationRecord(Base):
    """GEO 测评记录表（五指标主记录表）

    保存每一次平台提问和评估结果。新版五指标展示优先读取本表聚合结果。
    旧表 IndexCheckRecord 保留兼容历史页面。公司级别粒度。
    """

    __tablename__ = "geo_evaluation_records"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    run_id = Column(
        Integer,
        ForeignKey("geo_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属任务ID",
    )
    # 公司级别粒度
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属公司ID",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联项目ID（可为空）",
    )
    prompt_set_id = Column(
        Integer,
        ForeignKey("geo_prompt_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="使用的问题集ID",
    )
    prompt_id = Column(
        Integer,
        ForeignKey("geo_prompts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="对应问题ID",
    )
    # 问题中涉及的项目名称（如问题涉及特定业务线）
    related_project_name = Column(String(500), nullable=True, comment="问题涉及的项目名称")
    platform = Column(String(50), nullable=False, index=True, comment="检测平台")
    phase = Column(String(20), nullable=False, comment="检测阶段：baseline/ongoing")
    round_no = Column(Integer, nullable=False, default=1, comment="轮次：1/2/3")

    # 原始问答
    question = Column(Text, nullable=False, comment="提问内容")
    answer = Column(Text, nullable=True, comment="AI 原始回答")
    raw_citations = Column(JSON, nullable=True, comment="原始引用来源")
    context_cleaned = Column(Boolean, default=True, comment="是否清空了上下文")

    # 执行状态
    success = Column(Boolean, default=False, comment="提问是否成功")
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 五指标评估字段
    brand_mentioned = Column(Boolean, nullable=True, comment="品牌是否被提及")
    matched_names = Column(JSON, nullable=True, comment="匹配到的品牌名称")
    is_recommended = Column(Boolean, nullable=True, comment="是否被推荐")
    recommendation_rank = Column(Integer, nullable=True, comment="推荐排名")
    ranking_score = Column(Float, nullable=True, comment="排名分 0-100")
    citation_supported = Column(Boolean, nullable=True, comment="平台是否支持引用")
    own_source_cited = Column(Boolean, nullable=True, comment="是否引用了我方来源")
    cited_urls = Column(JSON, nullable=True, comment="引用 URL 列表")
    cited_domains = Column(JSON, nullable=True, comment="引用域名列表")
    sentiment = Column(
        String(30),
        nullable=True,
        comment="情感：strongly_positive/positive/neutral/negative/strongly_negative/not_mentioned",
    )
    sentiment_score = Column(Float, nullable=True, comment="情感分 0-100")
    visibility_score = Column(Float, nullable=True, comment="单条 AI 可见度综合分")

    # 评估元数据
    evidence = Column(JSON, nullable=True, comment="评估证据片段")
    judge_model = Column(String(100), nullable=True, comment="评估使用的模型")
    judge_raw_output = Column(JSON, nullable=True, comment="评估器原始输出")
    schema_version = Column(String(20), nullable=True, comment="评估 schema 版本")

    asked_at = Column(DateTime, nullable=True, comment="提问时间")
    evaluated_at = Column(DateTime, nullable=True, comment="评估时间")
    created_at = Column(DateTime, default=func.now(), comment="创建时间")

    # 关联关系
    run = relationship("GeoEvaluationRun", back_populates="records")
    client = relationship("Client")
    project = relationship("Project")
    prompt = relationship("GeoPrompt", back_populates="evaluation_records")

    def __repr__(self):
        return f"<GeoEvaluationRecord id={self.id} platform={self.platform} round={self.round_no}>"


class ClientContentProfile(Base):
    """客户内容画像表：从上传资料中结构化抽取的推荐字段。

    source：excel（Excel 行自带）/ ragflow_extract（资料抽取）/ manual
    profile_json 存结构化字段；confidence_json 存各字段置信度；source_document_ids 存来源 RAGFlow 文档。
    """

    __tablename__ = "client_content_profiles"
    __table_args__ = TABLE_ARGS

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="归属用户ID（数据隔离）",
    )
    client_id = Column(
        Integer,
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="公司/客户ID",
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="项目ID（公司通用画像为空）",
    )

    source = Column(String(30), default="ragflow_extract", comment="来源：excel/manual/ragflow_extract")
    profile_json = Column(JSON, nullable=True, comment="结构化画像（industry/product_service/...）")
    confidence_json = Column(JSON, nullable=True, comment="字段置信度 {field: 0~1}")
    source_document_ids = Column(JSON, nullable=True, comment="来源 RAGFlow 文档ID列表")

    status = Column(String(20), default="active", comment="active/archived")

    created_at = Column(DateTime, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<ClientContentProfile client_id={self.client_id} project_id={self.project_id} source={self.source}>"
