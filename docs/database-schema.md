# Auto_GEO 数据库表结构文档

> 本文档描述 Auto_GEO 项目完整的数据库 Schema，基于 Alembic migration 0001~0007 生成。
> 适用于 SQLite 开发环境和 PostgreSQL 生产环境迁移参考。

---

## 一、数据库概览

| 项目 | 说明 |
|---|---|
| ORM 框架 | SQLAlchemy 2.x |
| 迁移工具 | Alembic |
| 迁移文件路径 | `backend/migrations/versions/` |
| 迁移顺序 | 0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007 |
| PostgreSQL 支持 | 是（推荐生产环境使用） |
| SQLite 支持 | 是（仅用于本地开发调试） |

---

## 二、表清单（按迁移顺序）

| # | 表名 | 说明 | 引入版本 |
|---|---|---|---|
| 1 | `accounts` | 平台账号（自媒体账号） | 0001 |
| 2 | `clients` | 客户信息 | 0001 |
| 3 | `projects` | 项目 | 0001 |
| 4 | `keywords` | 关键词 | 0001 |
| 5 | `geo_articles` | GEO 文章 | 0001 |
| 6 | `publish_records` | 发布记录 | 0001 |
| 7 | `users` | 系统用户 | 0001 |
| 8 | `site_projects` | 建站项目 | 0001 |
| 9 | `auto_publish_tasks` | 自动发布任务 | 0001 |
| 10 | `system_configs` | 系统配置 | 0003 |
| 11 | `account_groups` | 账号分组 | 0004 |
| 12 | `account_operation_logs` | 账号操作日志 | 0004 |
| 13 | `feishu_user_bindings` | 飞书用户绑定 | 0005 |
| 14 | `feishu_events` | 飞书事件持久化 | 0005 |
| 15 | `keyword_usage_records` | 关键词使用记录 | 0005 |
| 16 | `project_members` | 项目成员 | 0006 |
| 17 | `feishu_binding_codes` | 飞书绑定码 | 0006 |
| 18 | `scheduled_tasks` | 定时任务 | 0007 |
| 19 | `question_variants` | 问题变体 | 0007 |
| 20 | `index_check_records` | 收录检测记录 | 0007 |
| 21 | `knowledge_categories` | 知识分类（RAGFlow） | 0007 |
| 22 | `knowledge_items` | 知识条目（RAGFlow） | 0007 |
| 23 | `reference_articles` | 参考文章采集 | 0007 |
| 24 | `auto_publish_records` | 自动发布明细记录 | 0007 |
| 25 | `conversation_sessions` | 对话会话（AI） | 0007 |
| 26 | `conversation_messages` | 对话消息（AI） | 0007 |
| 27 | `user_agent_preferences` | 用户偏好设置 | 0007 |

---

## 三、详细表结构

---

### 3.1 `accounts` — 平台账号表

**引入版本：** 0001_initial
**说明：** 存储各 AI 平台（知乎、头条、小红书等）的登录账号。

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `platform` | String(50) | 否 | — | 平台标识，如 `zhihu`、`toutiao` |
| `account_name` | String(100) | 否 | — | 账号显示名称 |
| `username` | String(100) | 是 | — | 平台内的用户名 |
| `cookies` | Text | 是 | — | 登录态 Cookies |
| `storage_state` | Text | 是 | — | Playwright StorageState JSON |
| `user_agent` | String(500) | 是 | — | User-Agent 字符串 |
| `status` | Integer | 是 | `1` | 状态：1=正常 0=禁用 |
| `last_auth_time` | DateTime | 是 | — | 最后认证时间 |
| `remark` | Text | 是 | — | 备注 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `user_id` | Integer | 是 | — | 所属用户ID（外键→users） |
| `deleted_at` | DateTime | 是 | — | 软删除时间 |
| `group_id` | Integer | 是 | — | 账号分组ID（外键→account_groups） |
| `tags` | JSON / Text | 是 | — | 标签列表（JSON数组） |
| `health_score` | Integer | 是 | `100` | 健康度评分 0-100 |
| `last_check_time` | DateTime | 是 | — | 最后检测时间 |
| `auth_expires_at` | DateTime | 是 | — | 预估过期时间 |
| `browser_type` | String(20) | 是 | `playwright` | 浏览器类型 |
| `adspower_profile_id` | String(100) | 是 | — | AdsPower Profile ID |

**索引：**
- `idx_accounts_platform` ON (`platform`)
- `idx_accounts_status` ON (`status`)
- `ix_accounts_user_id` ON (`user_id`)
- `ix_accounts_deleted_at` ON (`deleted_at`)
- `ix_accounts_group_id` ON (`group_id`)

**外键：**
- `user_id` → `users(id)` ON DELETE SET NULL
- `group_id` → `account_groups(id)` ON DELETE SET NULL

---

### 3.2 `clients` — 客户信息表

**引入版本：** 0001_initial

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `name` | String(200) | 否 | — | 客户名称 |
| `company_name` | String(200) | 是 | — | 公司名称 |
| `contact_person` | String(100) | 是 | — | 联系人 |
| `phone` | String(50) | 是 | — | 联系电话 |
| `email` | String(200) | 是 | — | 邮箱 |
| `industry` | String(100) | 是 | — | 所属行业 |
| `address` | String(500) | 是 | — | 地址 |
| `description` | Text | 是 | — | 描述 |
| `status` | Integer | 是 | `1` | 状态：1=正常 0=禁用 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `user_id` | Integer | 是 | — | 所属用户ID（外键→users） |

**索引：**
- `ix_clients_user_id` ON (`user_id`) — 0007 补建

**外键：**
- `user_id` → `users(id)` ON DELETE SET NULL

---

### 3.3 `projects` — 项目表

**引入版本：** 0001_initial

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `client_id` | Integer | 是 | — | 关联客户ID（外键→clients） |
| `name` | String(200) | 否 | — | 项目名称 |
| `company_name` | String(200) | 是 | — | 公司名称 |
| `domain_keyword` | String(200) | 是 | — | 域名关键词 |
| `description` | Text | 是 | — | 项目描述 |
| `industry` | String(100) | 是 | — | 行业 |
| `status` | Integer | 是 | `1` | 状态 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `user_id` | Integer | 是 | — | 所属用户ID（外键→users） |
| `deleted_at` | DateTime | 是 | — | 软删除时间 |

**索引：**
- `idx_projects_client_id` ON (`client_id`)
- `ix_projects_user_id` ON (`user_id`)
- `ix_projects_deleted_at` ON (`deleted_at`)

**外键：**
- `client_id` → `clients(id)` ON DELETE CASCADE
- `user_id` → `users(id)` ON DELETE SET NULL

---

### 3.4 `keywords` — 关键词表

**引入版本：** 0001_initial

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `project_id` | Integer | 否 | — | 所属项目ID（外键→projects） |
| `keyword` | String(200) | 否 | — | 关键词文本 |
| `difficulty_score` | Integer | 是 | — | 竞争难度评分 |
| `status` | String(20) | 是 | `active` | 状态：active / inactive |
| `keyword_type` | String(20) | 是 | `keyword` | 类型：keyword / phrase |
| `created_at` | DateTime | 是 | NOW | 创建时间 |

**索引：**
- `idx_keywords_project_id` ON (`project_id`)

**外键：**
- `project_id` → `projects(id)` ON DELETE CASCADE

---

### 3.5 `geo_articles` — GEO文章表

**引入版本：** 0001_initial

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `keyword_id` | Integer | 否 | — | 关联关键词ID（外键→keywords） |
| `project_id` | Integer | 是 | — | 关联项目ID（外键→projects） |
| `title` | Text | 是 | — | 文章标题 |
| `content` | Text | 否 | — | 文章正文 |
| `quality_score` | Integer | 是 | — | 质量评分 |
| `ai_score` | Integer | 是 | — | AI 检测评分 |
| `readability_score` | Integer | 是 | — | 可读性评分 |
| `quality_status` | String(20) | 是 | `pending` | 质量状态：pending / approved / rejected |
| `platform` | String(50) | 是 | — | 目标发布平台 |
| `account_id` | Integer | 是 | — | 发布账号ID |
| `publish_status` | String(20) | 是 | `draft` | 发布状态：draft / published / failed |
| `publish_time` | DateTime | 是 | — | 发布时间 |
| `scheduled_at` | DateTime | 是 | — | 计划发布时间 |
| `target_platforms` | JSON | 是 | — | 目标平台列表 |
| `publish_strategy` | String(20) | 是 | `draft` | 发布策略 |
| `retry_count` | Integer | 是 | `0` | 重试次数 |
| `error_msg` | Text | 是 | — | 错误信息 |
| `publish_logs` | Text | 是 | — | 发布日志 |
| `platform_url` | String(500) | 是 | — | 发布后平台URL |
| `index_status` | String(20) | 是 | `uncheck` | 收录状态：uncheck / indexed / not_indexed |
| `last_check_time` | DateTime | 是 | — | 最后检测时间 |
| `index_details` | Text | 是 | — | 收录详情 |
| `fact_risk_score` | Integer | 是 | — | 事实风险评估 0-100 |
| `duplication_score` | Integer | 是 | — | 重复度 0-100 |
| `platform_risk_score` | Integer | 是 | — | 平台合规风险 0-100 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `user_id` | Integer | 是 | — | 所属用户ID（外键→users） |
| `deleted_at` | DateTime | 是 | — | 软删除时间 |

**索引：**
- `idx_geo_articles_keyword_id` ON (`keyword_id`)
- `idx_geo_articles_project_id` ON (`project_id`)
- `idx_geo_articles_publish_status` ON (`publish_status`)
- `idx_geo_articles_created_at` ON (`created_at`)
- `ix_geo_articles_user_id` ON (`user_id`)
- `ix_geo_articles_deleted_at` ON (`deleted_at`)

**外键：**
- `keyword_id` → `keywords(id)` ON DELETE CASCADE
- `project_id` → `projects(id)` ON DELETE CASCADE
- `user_id` → `users(id)` ON DELETE SET NULL

---

### 3.6 `publish_records` — 发布记录表

**引入版本：** 0001_initial

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `article_id` | Integer | 否 | — | 文章ID（外键→geo_articles） |
| `account_id` | Integer | 否 | — | 账号ID（外键→accounts） |
| `publish_status` | Integer | 是 | `0` | 发布状态：0=进行中 1=成功 2=失败 |
| `platform_url` | String(500) | 是 | — | 发布后平台URL |
| `error_msg` | Text | 是 | — | 错误信息 |
| `retry_count` | Integer | 是 | `0` | 重试次数 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `published_at` | DateTime | 是 | — | 发布时间 |

**索引：**
- `idx_publish_records_article_id` ON (`article_id`)
- `idx_publish_records_account_id` ON (`account_id`)

**外键：**
- `article_id` → `geo_articles(id)` ON DELETE CASCADE
- `account_id` → `accounts(id)` ON DELETE CASCADE

---

### 3.7 `users` — 系统用户表

**引入版本：** 0001_initial
**增强版本：** 0003_add_user_auth_system_config

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `username` | String(50) | 否 | — | 用户名（唯一） |
| `email` | String(200) | 否 | — | 邮箱（唯一） |
| `password_hash` | String(255) | 否 | — | 密码哈希（bcrypt） |
| `role` | String(20) | 否 | `user` | 角色：admin / user |
| `is_active` | Boolean | 否 | `1` | 是否激活 |
| `last_login` | DateTime | 是 | — | 最后登录时间 |
| `login_count` | Integer | 否 | `0` | 登录次数 |
| `failed_login_attempts` | Integer | 否 | `0` | 连续登录失败次数 |
| `locked_until` | DateTime | 是 | — | 账户锁定截止时间 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |

**索引：**
- `ix_users_username` UNIQUE ON (`username`)
- `ix_users_email` UNIQUE ON (`email`)
- `ix_users_role` ON (`role`)
- `ix_users_is_active` ON (`is_active`)
- `ix_users_last_login` ON (`last_login`)

---

### 3.8 `site_projects` — 建站项目表

**引入版本：** 0001_initial

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `user_id` | Integer | 是 | — | 所属用户ID（外键→users） |
| `name` | String | 是 | — | 项目名称 |
| `site_id` | String | 是 | — | 唯一标识（唯一） |
| `config_data` | JSON / Text | 是 | — | 网站配置数据 |
| `deploy_path` | String | 是 | — | 生成的本地路径 |
| `preview_url` | String | 是 | — | 预览URL |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `deleted_at` | DateTime | 是 | — | 软删除时间 |

**索引：**
- `ix_sp_site_id` UNIQUE ON (`site_id`)
- `ix_sp_user_id` ON (`user_id`)
- `ix_site_projects_deleted_at` ON (`deleted_at`)

**外键：**
- `user_id` → `users(id)` ON DELETE SET NULL

---

### 3.9 `auto_publish_tasks` — 自动发布任务表

**引入版本：** 0001_initial
**增强版本：** 0006

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `name` | String(200) | 否 | — | 任务名称 |
| `description` | Text | 是 | — | 任务描述 |
| `article_ids` | JSON | 否 | `[]` | 文章ID列表 |
| `account_ids` | JSON | 否 | `[]` | 账号ID列表 |
| `declare_ai_content` | Boolean | 是 | `1` | 是否声明AI创作 |
| `user_id` | Integer | 是 | — | 数据归属用户ID（外键→users） |
| `triggered_by_user_id` | Integer | 是 | — | 触发任务的系统用户ID（外键→users） |
| `feishu_event_id` | String(200) | 是 | — | 关联的飞书事件ID |
| `status` | String(20) | 是 | `pending` | 任务状态：pending / running / completed / failed |
| `exec_type` | String(20) | 是 | `immediate` | 执行类型：immediate / scheduled / interval |
| `scheduled_at` | DateTime | 是 | — | 计划执行时间 |
| `interval_minutes` | Integer | 是 | — | 间隔分钟数 |
| `total_count` | Integer | 是 | `0` | 总发布任务数 |
| `completed_count` | Integer | 是 | `0` | 已完成数量 |
| `failed_count` | Integer | 是 | `0` | 失败数量 |
| `error_msg` | Text | 是 | — | 错误信息 |
| `last_error_at` | DateTime | 是 | — | 最后错误时间 |
| `started_at` | DateTime | 是 | — | 开始时间 |
| `completed_at` | DateTime | 是 | — | 完成时间 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_apt_user_id` ON (`user_id`)
- `ix_apt_triggered_by_user_id` ON (`triggered_by_user_id`)

**外键：**
- `user_id` → `users(id)` ON DELETE SET NULL
- `triggered_by_user_id` → `users(id)` ON DELETE SET NULL

---

### 3.10 `system_configs` — 系统配置表

**引入版本：** 0003_add_user_auth_system_config

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `config_key` | String(100) | 否 | — | 配置键（唯一） |
| `config_value` | Text | 是 | — | 配置值（JSON字符串或纯文本） |
| `category` | String(50) | 否 | `general` | 配置分类：general / auth / security / email / storage |
| `description` | Text | 是 | — | 配置描述 |
| `value_type` | String(20) | 否 | `string` | 值类型：string / int / float / bool / json |
| `is_editable` | Boolean | 否 | `1` | 是否可通过界面编辑 |
| `is_sensitive` | Boolean | 否 | `0` | 是否为敏感配置（如密码、密钥） |
| `is_active` | Boolean | 否 | `1` | 是否启用 |
| `sort_order` | Integer | 否 | `0` | 排序权重 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `updated_by` | Integer | 是 | — | 最后更新用户ID（外键→users） |

**索引：**
- `ix_system_configs_config_key` ON (`config_key`)
- `ix_system_configs_category` ON (`category`)
- `ix_system_configs_is_active` ON (`is_active`)

**外键：**
- `updated_by` → `users(id)` ON DELETE SET NULL

---

### 3.11 `account_groups` — 账号分组表

**引入版本：** 0004_account_enhancements

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `name` | String(100) | 否 | — | 分组名称 |
| `icon` | String(50) | 是 | — | 分组图标 |
| `color` | String(20) | 是 | `#409EFF` | 分组颜色 |
| `user_id` | Integer | 否 | — | 所属用户ID（外键→users） |
| `sort_order` | Integer | 是 | `0` | 排序权重 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_account_groups_user_id` ON (`user_id`)

**外键：**
- `user_id` → `users(id)` ON DELETE CASCADE

---

### 3.12 `account_operation_logs` — 账号操作日志表

**引入版本：** 0004_account_enhancements

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `account_id` | Integer | 是 | — | 账号ID（外键→accounts） |
| `user_id` | Integer | 是 | — | 操作用户ID（外键→users） |
| `operation` | String(50) | 否 | — | 操作类型 |
| `detail` | JSON | 是 | — | 操作详情 |
| `ip_address` | String(50) | 是 | — | 操作IP |
| `created_at` | DateTime | 是 | NOW | 创建时间 |

**索引：**
- `ix_aol_account_id` ON (`account_id`)
- `ix_aol_user_id` ON (`user_id`)
- `ix_aol_operation` ON (`operation`)

**外键：**
- `account_id` → `accounts(id)` ON DELETE CASCADE
- `user_id` → `users(id)` ON DELETE SET NULL

---

### 3.13 `feishu_user_bindings` — 飞书用户绑定表

**引入版本：** 0005_feishu_optimization

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `open_id` | String(200) | 否 | — | 飞书用户 open_id（唯一） |
| `union_id` | String(200) | 是 | — | 飞书 union_id |
| `system_user_id` | Integer | 否 | — | 绑定的系统用户ID（外键→users） |
| `default_client_id` | Integer | 是 | — | 默认客户ID（外键→clients） |
| `default_project_id` | Integer | 是 | — | 默认项目ID（外键→projects） |
| `status` | Integer | 是 | `1` | 绑定状态：1=已绑定 0=已解绑 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_fub_open_id` UNIQUE ON (`open_id`)
- `ix_fub_system_user_id` ON (`system_user_id`)

**外键：**
- `system_user_id` → `users(id)` ON DELETE CASCADE
- `default_client_id` → `clients(id)` ON DELETE SET NULL
- `default_project_id` → `projects(id)` ON DELETE SET NULL

---

### 3.14 `feishu_events` — 飞书事件持久化表

**引入版本：** 0005_feishu_optimization

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `event_id` | String(200) | 否 | — | 飞书事件唯一ID（唯一） |
| `message_id` | String(200) | 是 | — | 飞书消息ID |
| `open_id` | String(200) | 是 | — | 发送者 open_id |
| `chat_id` | String(200) | 是 | — | 会话ID |
| `event_type` | String(100) | 是 | — | 事件类型 |
| `raw_payload` | Text | 是 | — | 原始请求体 |
| `raw_text` | Text | 是 | — | 提取的用户消息文本 |
| `status` | String(20) | 是 | `received` | 处理状态 |
| `error_msg` | Text | 是 | — | 处理错误信息 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `processed_at` | DateTime | 是 | — | 处理完成时间 |

**索引：**
- `ix_fe_event_id` UNIQUE ON (`event_id`)
- `ix_fe_open_id` ON (`open_id`)

---

### 3.15 `keyword_usage_records` — 关键词使用记录表

**引入版本：** 0005_feishu_optimization

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `project_id` | Integer | 是 | — | 所属项目ID（外键→projects） |
| `keyword_id` | Integer | 是 | — | 关键词ID（外键→keywords） |
| `keyword_text` | String(200) | 否 | — | 关键词文本 |
| `article_id` | Integer | 是 | — | 生成的文章ID（外键→geo_articles） |
| `source` | String(50) | 是 | `auto` | 使用来源 |
| `used_by_user_id` | Integer | 是 | — | 触发使用的用户ID（外键→users） |
| `used_at` | DateTime | 是 | NOW | 使用时间 |

**索引：**
- `ix_kur_project_id` ON (`project_id`)
- `ix_kur_keyword_id` ON (`keyword_id`)
- `ix_kur_used_by_user_id` ON (`used_by_user_id`)

**外键：**
- `project_id` → `projects(id)` ON DELETE SET NULL
- `keyword_id` → `keywords(id)` ON DELETE SET NULL
- `article_id` → `geo_articles(id)` ON DELETE SET NULL
- `used_by_user_id` → `users(id)` ON DELETE SET NULL

---

### 3.16 `project_members` — 项目成员表

**引入版本：** 0006_add_project_members_and_task_attribution

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `project_id` | Integer | 否 | — | 项目ID（外键→projects） |
| `user_id` | Integer | 否 | — | 用户ID（外键→users） |
| `role` | String(20) | 是 | `owner` | 角色：owner / editor / viewer |
| `status` | Integer | 是 | `1` | 状态：1=正常 0=已移除 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |

**索引：**
- `ix_pm_project_id` ON (`project_id`)
- `ix_pm_user_id` ON (`user_id`)

**外键：**
- `project_id` → `projects(id)` ON DELETE CASCADE
- `user_id` → `users(id)` ON DELETE CASCADE

---

### 3.17 `feishu_binding_codes` — 飞书绑定码表

**引入版本：** 0006_add_project_members_and_task_attribution

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `code` | String(20) | 否 | — | 绑定码（6位随机字符，唯一） |
| `system_user_id` | Integer | 否 | — | 待绑定的系统用户ID（外键→users） |
| `status` | Integer | 是 | `0` | 状态：0=待使用 1=已使用 -1=已过期 |
| `used_by_open_id` | String(200) | 是 | — | 使用此码的飞书 open_id |
| `expires_at` | DateTime | 否 | — | 过期时间（生成后30分钟有效） |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `used_at` | DateTime | 是 | — | 使用时间 |

**索引：**
- `ix_fbc_code` UNIQUE ON (`code`)
- `ix_fbc_system_user_id` ON (`system_user_id`)

**外键：**
- `system_user_id` → `users(id)` ON DELETE CASCADE

---

### 3.18 `scheduled_tasks` — 定时任务表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `name` | String(100) | 否 | — | 任务名称 |
| `task_key` | String(50) | 否 | — | 任务标识符（唯一） |
| `cron_expression` | String(50) | 否 | — | Cron 表达式 |
| `is_active` | Boolean | 是 | `1` | 是否启用 |
| `description` | Text | 是 | — | 任务描述 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `idx_scheduled_tasks_task_key` UNIQUE ON (`task_key`)

---

### 3.19 `question_variants` — 问题变体表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `keyword_id` | Integer | 否 | — | 关键词ID（外键→keywords） |
| `question` | Text | 否 | — | 问题变体 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |

**索引：**
- `ix_qv_keyword_id` ON (`keyword_id`)

**外键：**
- `keyword_id` → `keywords(id)` ON DELETE CASCADE

---

### 3.20 `index_check_records` — 收录检测记录表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `keyword_id` | Integer | 否 | — | 关键词ID（外键→keywords） |
| `platform` | String(50) | 否 | — | 检测平台 |
| `question` | Text | 否 | — | 检测时使用的问题 |
| `answer` | Text | 是 | — | AI 回答内容 |
| `keyword_found` | Boolean | 是 | — | 是否包含关键词 |
| `company_found` | Boolean | 是 | — | 是否包含公司名 |
| `check_phase` | String(20) | 是 | `ongoing` | 检测阶段 |
| `keyword_count` | Integer | 是 | — | 关键词出现次数 |
| `company_count` | Integer | 是 | — | 公司名出现次数 |
| `company_matched` | String(200) | 是 | — | 实际命中的公司分层词 |
| `confidence` | Float | 是 | — | 置信度 0~1 |
| `check_time` | DateTime | 是 | NOW | 检测时间 |

**索引：**
- `ix_icr_keyword_id` ON (`keyword_id`)
- `ix_icr_check_phase` ON (`check_phase`)
- `ix_icr_check_time` ON (`check_time`)

**外键：**
- `keyword_id` → `keywords(id)` ON DELETE CASCADE

---

### 3.21 `knowledge_categories` — 知识分类表（RAGFlow）

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `user_id` | Integer | 是 | — | 所属用户ID（外键→users） |
| `ragflow_dataset_id` | String(100) | 是 | — | RAGFlow 知识库ID（唯一） |
| `name` | String(200) | 否 | — | 企业/分类名称 |
| `industry` | String(100) | 是 | — | 所属行业 |
| `description` | Text | 是 | — | 分类描述 |
| `tags` | String(500) | 是 | — | 标签 |
| `color` | String(20) | 是 | `#6366f1` | 主题颜色 |
| `status` | Integer | 是 | `1` | 状态 |
| `sync_status` | String(20) | 是 | `pending` | 同步状态 |
| `ragflow_synced` | Boolean | 是 | `0` | 是否已同步到RAGFlow |
| `ragflow_synced_at` | DateTime | 是 | — | 同步时间 |
| `last_sync_at` | DateTime | 是 | — | 最后同步时间 |
| `knowledge_count` | Integer | 是 | `0` | 知识数量 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_kc_user_id` ON (`user_id`)
- `ix_kc_ragflow_dataset_id` UNIQUE ON (`ragflow_dataset_id`)

**外键：**
- `user_id` → `users(id)` ON DELETE SET NULL

---

### 3.22 `knowledge_items` — 知识条目表（RAGFlow）

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `ragflow_document_id` | String(100) | 是 | — | RAGFlow 文档ID（唯一） |
| `ragflow_dataset_id` | String(100) | 否 | — | 所属 RAGFlow 知识库ID |
| `category_id` | Integer | 否 | — | 分类ID（外键→knowledge_categories） |
| `title` | String(200) | 否 | — | 知识标题 |
| `content` | Text | 否 | — | 知识内容 |
| `type` | String(50) | 是 | `other` | 知识类型 |
| `status` | Integer | 是 | `1` | 状态 |
| `sync_status` | String(20) | 是 | `pending` | 同步状态 |
| `ragflow_synced` | Boolean | 是 | `0` | 是否已同步到RAGFlow |
| `ragflow_synced_at` | DateTime | 是 | — | 同步时间 |
| `ragflow_parsed` | Boolean | 是 | `0` | 文档是否已解析 |
| `last_sync_at` | DateTime | 是 | — | 最后同步时间 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_ki_ragflow_document_id` UNIQUE ON (`ragflow_document_id`)
- `ix_ki_ragflow_dataset_id` ON (`ragflow_dataset_id`)
- `ix_ki_category_id` ON (`category_id`)

**外键：**
- `category_id` → `knowledge_categories(id)` ON DELETE CASCADE

---

### 3.23 `reference_articles` — 参考文章采集表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `title` | String(500) | 否 | — | 文章标题 |
| `url` | String(1000) | 否 | — | 原文链接（唯一） |
| `content` | Text | 否 | — | 文章正文 |
| `summary` | Text | 是 | — | 文章摘要 |
| `platform` | String(50) | 否 | — | 来源平台 |
| `author` | String(200) | 是 | — | 作者名称 |
| `publish_time` | String(50) | 是 | — | 原文发布时间 |
| `likes` | Integer | 是 | `0` | 点赞数 |
| `reads` | Integer | 是 | `0` | 阅读量 |
| `comments` | Integer | 是 | `0` | 评论数 |
| `keyword` | String(200) | 是 | — | 采集关键词 |
| `collected_at` | DateTime | 是 | NOW | 采集时间 |
| `ragflow_synced` | Boolean | 是 | `0` | 是否已同步到RAGFlow |
| `ragflow_doc_id` | String(100) | 是 | — | RAGFlow 文档ID |
| `ragflow_sync_time` | DateTime | 是 | — | RAGFlow 同步时间 |
| `status` | Integer | 是 | `1` | 状态 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_ra_platform` ON (`platform`)
- `ix_ra_keyword` ON (`keyword`)

---

### 3.24 `auto_publish_records` — 自动发布明细记录表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `task_id` | Integer | 否 | — | 所属任务ID（外键→auto_publish_tasks） |
| `article_id` | Integer | 否 | — | 文章ID（外键→geo_articles） |
| `account_id` | Integer | 否 | — | 账号ID（外键→accounts） |
| `status` | String(20) | 是 | `pending` | 状态 |
| `platform_url` | String(500) | 是 | — | 发布后链接 |
| `error_msg` | Text | 是 | — | 错误信息 |
| `retry_count` | Integer | 是 | `0` | 重试次数 |
| `max_retries` | Integer | 是 | `3` | 最大重试次数 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `started_at` | DateTime | 是 | — | 开始时间 |
| `completed_at` | DateTime | 是 | — | 完成时间 |

**索引：**
- `ix_apr_task_id` ON (`task_id`)
- `ix_apr_article_id` ON (`article_id`)
- `ix_apr_account_id` ON (`account_id`)

**外键：**
- `task_id` → `auto_publish_tasks(id)` ON DELETE CASCADE
- `article_id` → `geo_articles(id)` ON DELETE CASCADE
- `account_id` → `accounts(id)` ON DELETE CASCADE

---

### 3.25 `conversation_sessions` — AI 对话会话表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | String(120) | 否 | — | 会话ID（主键） |
| `source` | String(50) | 是 | `web` | 来源 |
| `channel` | String(50) | 是 | `web` | 通道 |
| `system_user_id` | Integer | 否 | — | 系统用户ID（外键→users） |
| `external_user_id` | String(200) | 是 | — | 外部用户ID |
| `external_chat_id` | String(200) | 是 | — | 外部会话ID |
| `status` | String(30) | 是 | `active` | 状态 |
| `current_intent` | String(80) | 是 | — | 当前意图 |
| `slots` | JSON | 是 | — | 结构化任务槽位 |
| `summary` | Text | 是 | — | 会话摘要 |
| `title` | String(120) | 是 | — | 会话标题 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |
| `expires_at` | DateTime | 是 | — | 过期时间 |

**索引：**
- `ix_cs_source` ON (`source`)
- `ix_cs_channel` ON (`channel`)
- `ix_cs_system_user_id` ON (`system_user_id`)
- `ix_cs_external_user_id` ON (`external_user_id`)
- `ix_cs_external_chat_id` ON (`external_chat_id`)
- `ix_cs_status` ON (`status`)
- `ix_cs_current_intent` ON (`current_intent`)

**外键：**
- `system_user_id` → `users(id)` ON DELETE CASCADE

---

### 3.26 `conversation_messages` — AI 对话消息表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `conversation_id` | String(120) | 否 | — | 会话ID（外键→conversation_sessions） |
| `role` | String(30) | 否 | — | 角色 |
| `content` | Text | 否 | — | 消息内容 |
| `message_metadata` | JSON | 是 | — | 消息元数据 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |

**索引：**
- `ix_cm_conversation_id` ON (`conversation_id`)
- `ix_cm_role` ON (`role`)
- `ix_cm_created_at` ON (`created_at`)

**外键：**
- `conversation_id` → `conversation_sessions(id)` ON DELETE CASCADE

---

### 3.27 `user_agent_preferences` — 用户偏好设置表

**引入版本：** 0007_reconcile_postgresql_schema

| 字段名 | 类型 | 可空 | 默认值 | 说明 |
|---|---|---|---|---|
| `id` | Integer | 否 | 自增 | 主键 |
| `system_user_id` | Integer | 否 | — | 系统用户ID（唯一，外键→users） |
| `default_project_id` | Integer | 是 | — | 默认项目ID（外键→projects） |
| `default_platforms` | JSON | 是 | — | 默认发布平台列表 |
| `default_publish_strategy` | String(30) | 是 | — | 默认发布策略 |
| `require_confirmation_before_publish` | Boolean | 否 | `1` | 发布前是否确认 |
| `tone_preference` | String(50) | 是 | — | 语气偏好 |
| `onboarding_dismissed` | Boolean | 否 | `0` | 是否已关闭新用户引导 |
| `created_at` | DateTime | 是 | NOW | 创建时间 |
| `updated_at` | DateTime | 是 | NOW | 更新时间 |

**索引：**
- `ix_uap_system_user_id` UNIQUE ON (`system_user_id`)
- `ix_uap_default_project_id` ON (`default_project_id`)

**外键：**
- `system_user_id` → `users(id)` ON DELETE CASCADE
- `default_project_id` → `projects(id)` ON DELETE SET NULL

---

## 四、实体关系摘要

```
users (1) ─── (N) accounts
      └─── (N) projects ─── (N) keywords ─── (N) question_variants
                     └─── (N) geo_articles ─── (N) publish_records
                                                    └─── accounts
                     └─── (N) project_members ─── users
                     └─── (N) keyword_usage_records
      └─── (N) site_projects
      └─── (N) knowledge_categories ─── (N) knowledge_items
      └─── (N) reference_articles
      └─── (N) conversation_sessions ─── (N) conversation_messages
      └─── (1) user_agent_preferences
      └─── (N) feishu_user_bindings
      └─── (N) feishu_binding_codes
      └─── (N) account_groups ─── (N) accounts
      └─── (N) account_operation_logs
      └─── (N) auto_publish_tasks ─── (N) auto_publish_records
      └─── (N) system_configs
      └─── (N) scheduled_tasks
```

---

## 五、PostgreSQL 生产环境部署

### 5.1 启动命令

```bash
# 进入容器后执行 Alembic 迁移
alembic upgrade head

# 查看当前迁移版本
alembic current

# 查看迁移历史
alembic history
```

### 5.2 初始化超级管理员

```bash
python scripts/init_admin.py
```

### 5.3 关键配置项（环境变量）

| 变量名 | 说明 | 示例 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://user:pass@host:5432/dbname` |
| `DB_POOL_SIZE` | 连接池大小 | `5` |
| `DB_MAX_OVERFLOW` | 最大溢出连接 | `10` |

### 5.4 备份与恢复

```bash
# 备份
pg_dump -h host -U user dbname > backup.sql

# 恢复
psql -h host -U user dbname < backup.sql
```

---

## 六、版本信息

| 项目 | 内容 |
|---|---|
| 文档生成时间 | 2026-06-12 |
| 数据库迁移版本范围 | 0001_initial ~ 0007_reconcile_postgresql_schema |
| 对应 ORM 模型文件 | `backend/database/models.py` |