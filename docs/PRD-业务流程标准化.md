# AutoGEO 系统化标准业务流程 PRD

**版本**: v2.0
**创建日期**: 2026-05-12
**状态**: 正式发布
**项目代号**: AutoGEO

---

## 1. 产品概述

### 1.1 产品定位

AutoGEO 是一款面向企业的**GEO（Generative Engine Optimization）全流程自动化平台**，帮助品牌在国产AI搜索引擎（豆包、千问、DeepSeek、腾讯元宝、Kimi）的回答中获得品牌曝光。

### 1.2 核心价值主张

- **获客增长**: 提升品牌关键词在AI回答中的出现频率
- **降本增效**: 从关键词分析到内容发布一站式自动化
- **数据驱动**: 实时收录监控与效果分析

### 1.3 目标用户

- 数字营销团队
- SEO/SEM专员
- 品牌运营人员
- 内容创作者

### 1.4 支持的AI平台

| 平台 | 所属公司 | 支持状态 |
|------|---------|---------|
| 豆包 | 字节跳动 | ✅ 已支持 |
| 通义千问 | 阿里巴巴 | ✅ 已支持 |
| DeepSeek | DeepSeek | ✅ 已支持 |
| 腾讯元宝 | 腾讯 | ✅ 已支持 |
| Kimi | 月之暗面 | ✅ 已支持 |

---

## 2. 系统架构概览

### 2.1 技术栈

```
┌────────────────────────────────────────────────────────────────┐
│                        AutoGEO 系统架构                         │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────┐        ┌──────────────────────────────┐ │
│  │   前端应用        │        │         后端服务              │ │
│  │  (Vue3 + Vite)   │◄──────►│    (FastAPI + SQLAlchemy)    │ │
│  │                  │        │                              │ │
│  │  • Element Plus  │        │  • RESTful API               │ │
│  │  • WangEditor    │        │  • WebSocket 实时推送         │ │
│  │  • Axios         │ HTTP   │  • APScheduler 定时任务       │ │
│  │  • Vue Router    │ WS     │  • Playwright 自动化          │ │
│  └──────────────────┘        └──────────┬─────────────────────┘ │
│                                         │                      │
│                                         ▼                      │
│                          ┌──────────────────────────┐         │
│                          │     数据存储层            │         │
│                          │  ┌─────────────────────┐ │         │
│                          │  │ SQLite/PostgreSQL  │ │         │
│                          │  │ (SQLAlchemy ORM)   │ │         │
│                          │  └─────────────────────┘ │         │
│                          │  ┌─────────────────────┐ │         │
│                          │  │ RAGFlow 知识库      │ │         │
│                          │  │ (向量检索)          │ │         │
│                          │  └─────────────────────┘ │         │
│                          └──────────────────────────┘         │
│                                         │                      │
│                                         ▼                      │
│                          ┌──────────────────────────┐         │
│                          │      外部集成             │         │
│                          │  • DeepSeek API          │         │
│                          │  • 各平台网页版           │         │
│                          │  • SMTP/钉钉Webhook      │         │
│                          └──────────────────────────┘         │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 模块划分

| 模块 | 前端路径 | 后端路径 | 说明 |
|------|---------|---------|------|
| 客户管理 | `views/client/` | `api/client.py` | CRM基础功能 |
| GEO项目 | `views/geo/` | `api/geo.py` | 项目管理与文章生成 |
| 知识库 | `views/knowledge/` | `api/knowledge.py` | RAGFlow集成 |
| 智能建站 | `views/site-builder/` | `api/site_builder.py` | 静态站点生成 |
| 文章管理 | `views/article/` | `api/article.py` | 文章CRUD |
| 账号管理 | `views/account/` | `api/account.py` | 多平台账号 |
| 发布任务 | `views/publish/` | `api/auto_publish.py` | 批量发布调度 |
| 收录监控 | `views/geo/Monitor.vue` | `api/index_check.py` | AI收录检测 |
| 定时任务 | `views/scheduler/` | `services/scheduler_service.py` | 自动化调度 |
| 系统设置 | `views/settings/` | `api/` | 配置管理 |

---

## 3. 标准业务流程 (SOP)

### 3.1 业务流程总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AutoGEO 标准业务流程                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │
│  │ 客户录入  │──►│ 项目创建  │──►│ 知识配置  │──►│ 关键词蒸馏│──►│ 文章生成  │  │
│  │ (CRM)    │   │ (Project)│   │ (RAGFlow)│   │ (AI)     │   │ (LLM)    │  │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘   └────┬─────┘  │
│       │                                                           │        │
│       │                                                           ▼        │
│       │                                                    ┌──────────┐   │
│       │                                                    │ 质量检查  │   │
│       │                                                    │ (质检)   │   │
│       │                                                    └────┬─────┘   │
│       │                                                         │        │
│       │    ┌────────────────────────────────────────────────────┘        │
│       │    │                                                              │
│       ▼    ▼                                                              │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐              │
│   │ 收录监控  │◄──│ 数据报表  │◄──│ 发布执行  │◄──│ 发布配置  │              │
│   │ (检测)   │   │ (分析)   │   │ (分发)   │   │ (调度)   │              │
│   └──────────┘   └──────────┘   └──────────┘   └──────────┘              │
│                                                                              │
│   【监控预警】◄────────────────────────────────────────────────────────────  │
│   收录掉落/任务失败/异常通知                                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 详细业务流程

#### SOP-01: 客户管理流程

**目标**: 建立客户档案，为后续项目创建提供基础

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   客户录入      │────►│   信息完善      │────►│   项目关联      │
│   (必填)        │     │   (可选)        │     │   (后续)        │
└────────────────┘     └────────────────┘     └────────────────┘
```

**字段规范**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | String | ✅ | 客户名称 |
| company_name | String | ❌ | 公司名称 |
| contact_person | String | ❌ | 联系人 |
| phone | String | ❌ | 联系电话 |
| email | String | ❌ | 邮箱 |
| industry | String | ❌ | 所属行业 |
| description | Text | ❌ | 客户描述 |
| status | Integer | ✅ | 1=活跃 0=停用 |

**API端点**:
- `GET /api/clients` - 客户列表
- `POST /api/clients` - 创建客户
- `PUT /api/clients/{id}` - 更新客户
- `DELETE /api/clients/{id}` - 删除客户

---

#### SOP-02: GEO项目管理流程

**目标**: 为客户创建GEO优化项目，配置基础信息

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   选择客户      │────►│   项目配置      │────►│   绑定知识库    │
│               │     │   • 名称        │     │   • 行业知识    │
│               │     │   • 领域词      │     │   • 企业介绍    │
│               │     │   • 描述        │     │   • 产品服务    │
└────────────────┘     └────────────────┘     └────────────────┘
```

**字段规范**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| client_id | Integer | ✅ | 关联客户ID |
| name | String | ✅ | 项目名称 |
| company_name | String | ❌ | 公司名称 |
| domain_keyword | String | ❌ | 领域关键词，用于蒸馏 |
| description | Text | ❌ | 项目描述 |
| industry | String | ❌ | 行业 |
| status | Integer | ✅ | 1=活跃 0=停用 |

**关联关系**:
- 一个客户可拥有多个项目
- 一个项目可包含多个关键词
- 一个项目可生成多篇文章

---

#### SOP-03: 知识库管理流程

**目标**: 构建企业知识库，为AI生成提供上下文

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   创建分类      │────►│   上传文档      │────►│   同步RAGFlow  │
│   (企业维度)    │     │   • Word       │     │   • 向量解析    │
│               │     │   • PDF        │     │   • 索引构建    │
│               │     │   • 文本        │     │   • 检索测试    │
└────────────────┘     └────────────────┘     └────────────────┘
```

**知识分类**:
- `company_intro` - 企业介绍
- `product` - 产品服务
- `industry` - 行业知识
- `faq` - 常见问题
- `other` - 其他

**同步状态**:
- `pending` - 待同步
- `syncing` - 同步中
- `synced` - 已同步
- `error` - 同步失败

---

#### SOP-04: 关键词蒸馏流程

**目标**: AI智能分析，提取高价值GEO关键词

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   输入企业信息  │────►│   AI分析       │────►│   关键词产出    │
│   • 公司名称    │     │   (DeepSeek)   │     │   • 关键词      │
│   • 行业领域    │     │               │     │   • 难度分      │
│   • 产品描述    │     │               │     │   • 搜索意图    │
└────────────────┘     └────────────────┘     └────────────────┘
                             │
                             ▼
                      ┌────────────────┐
                      │   生成问题变体  │
                      │   • 问答形式    │
                      │   • 场景化      │
                      └────────────────┘
```

**输出格式**:
```json
{
  "keywords": [
    {
      "keyword": "中小企业CRM",
      "difficulty_score": 75,
      "search_intent": "commercial",
      "question_variants": [
        "推荐一款适合中小企业的CRM系统",
        "中小企业如何选择CRM软件"
      ]
    }
  ]
}
```

---

#### SOP-05: GEO文章生成流程

**目标**: 基于关键词和知识库，自动生成高质量文章

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   选择关键词    │────►│   配置生成参数  │────►│   AI生成文章    │
│               │     │   • 风格        │     │   (DeepSeek)   │
│               │     │   • 字数        │     │               │
│               │     │   • 知识库引用  │     │               │
└────────────────┘     └────────────────┘     └───────┬───────┘
                                                      │
                                                      ▼
                                               ┌──────────────┐
                                               │   质量检查    │
                                               │   • AI味检测  │
                                               │   • 可读性    │
                                               │   • 原创性    │
                                               └──────┬───────┘
                                                      │
                                               合格 ◄─┴─► 不合格
                                               │         │
                                               ▼         ▼
                                         ┌────────┐  ┌────────┐
                                         │ 待发布  │  │ 重新生成│
                                         └────────┘  └────────┘
```

**文章状态流转**:
```
draft ──► generating ──► completed ──► scheduled ──► publishing ──► published
                    │      │      │
                    └──────┴──────┴──► failed
```

**状态说明**:
- `draft` - 草稿（仅标题/关键词）
- `generating` - 生成中
- `completed` - 已生成待分发
- `scheduled` - 已配置定时发布
- `publishing` - 发布中
- `published` - 已发布
- `failed` - 发布失败

---

#### SOP-06: 文章发布流程

**目标**: 将文章自动发布到多个内容平台

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   选择文章      │────►│   配置发布      │────►│   创建任务      │
│   (可多选)      │     │   • 目标平台    │     │   • 立即执行    │
│               │     │   • 目标账号    │     │   • 定时执行    │
│               │     │   • 发布时间    │     │   • 间隔执行    │
└────────────────┘     └────────────────┘     └───────┬───────┘
                                                      │
                                                      ▼
                                               ┌──────────────┐
                                               │  任务调度执行  │
                                               │ (Task Queue) │
                                               └──────┬───────┘
                                                      │
                                                      ▼
                                               ┌──────────────┐
                                               │  Playwright  │
                                               │  自动化发布   │
                                               └──────┬───────┘
                                                      │
                                               ┌──────┴──────┐
                                               ▼             ▼
                                          ┌────────┐   ┌────────┐
                                          │  成功   │   │  失败   │
                                          │ 记链接  │   │ 记错误  │
                                          └────────┘   └────────┘
```

**执行类型**:
- `immediate` - 立即执行
- `scheduled` - 定时执行
- `interval` - 间隔执行

**支持平台**:
- 知乎
- 百家号
- 搜狐号
- 今日头条
- 小红书
- 抖音

---

#### SOP-07: 收录监控流程

**目标**: 检测关键词在各AI平台的收录情况

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   选择关键词    │────►│   配置检测      │────►│   执行检测      │
│               │     │   • AI平台      │     │   (Playwright) │
│               │     │   • 问题变体    │     │               │
│               │     │   • 检测深度    │     │               │
└────────────────┘     └────────────────┘     └───────┬───────┘
                                                      │
                                                      ▼
                                               ┌──────────────┐
                                               │   AI平台交互  │
                                               │  1. 打开网页   │
                                               │  2. 输入问题   │
                                               │  3. 获取回答   │
                                               │  4. 匹配分析   │
                                               └──────┬───────┘
                                                      │
                                                      ▼
                                               ┌──────────────┐
                                               │   结果记录    │
                                               │ • 收录/未收录 │
                                               │ • 品牌提及    │
                                               │ • 排名位置    │
                                               └──────────────┘
```

**检测维度**:
- `keyword_found` - 是否包含关键词
- `company_found` - 是否包含公司名
- `answer` - AI回答内容（用于分析）

**定时检测**:
- 执行时间: 每天凌晨 2:00-6:00
- 检测范围: 所有活跃关键词
- AI平台: 豆包、千问、DeepSeek、元宝、Kimi
- 失败重试: 最多2次

---

#### SOP-08: 定时任务调度流程

**目标**: 自动化执行重复性任务

**流程图**:
```
┌────────────────┐     ┌────────────────┐     ┌────────────────┐
│   配置定时任务  │────►│   APScheduler  │────►│   任务执行      │
│   • Cron表达式 │     │   调度器        │     │   • 收录检测    │
│   • 任务类型    │     │               │     │   • 数据报表    │
│   • 启用状态    │     │               │     │   • 预警检查    │
└────────────────┘     └────────────────┘     └───────┬───────┘
                                                      │
                                               ┌──────┴──────┐
                                               ▼             ▼
                                          ┌────────┐   ┌────────┐
                                          │  成功   │   │  失败   │
                                          │ 记日志  │   │ 重试/告警│
                                          └────────┘   └────────┘
```

**内置任务**:
- `daily_index_check` - 每日收录检测
- `daily_report` - 每日报表生成
- `weekly_report` - 每周报表生成

---

## 4. 数据模型关系

### 4.1 ER图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            数据模型关系图                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────┐         ┌──────────┐         ┌──────────┐                    │
│   │  Client  │◄────────│ Project  │◄────────│ Keyword  │                    │
│   │  客户     │  1:N   │  项目     │  1:N   │  关键词   │                    │
│   └──────────┘         └──────────┘         └────┬─────┘                    │
│                                                  │                          │
│                                                  │ 1:N                       │
│                                                  ▼                          │
│   ┌──────────┐         ┌──────────┐         ┌──────────┐                    │
│   │  Account │◄────────│ Publish  │────────►│GeoArticle│                    │
│   │  账号     │   1:N  │  Record  │   N:1  │  GEO文章  │                    │
│   └──────────┘         └──────────┘         └──────────┘                    │
│                                                  │                          │
│                                                  │                          │
│                         ┌──────────┐            │                           │
│                         │IndexCheck│◄───────────┘                           │
│                         │  Record  │                                       │
│                         │收录检测记录│                                       │
│                         └──────────┘                                       │
│                                                                              │
│   ┌──────────────────┐     ┌──────────────────┐                            │
│   │ KnowledgeCategory │────►│    Knowledge     │                            │
│   │    知识分类       │ 1:N │    知识条目       │                            │
│   └──────────────────┘     └──────────────────┘                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 核心表结构

#### 客户表 (clients)
```sql
CREATE TABLE clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) NOT NULL,
    company_name VARCHAR(200),
    contact_person VARCHAR(100),
    phone VARCHAR(50),
    email VARCHAR(200),
    industry VARCHAR(100),
    description TEXT,
    status INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 项目表 (projects)
```sql
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    company_name VARCHAR(200),
    domain_keyword VARCHAR(200),
    description TEXT,
    industry VARCHAR(100),
    status INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 关键词表 (keywords)
```sql
CREATE TABLE keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    keyword VARCHAR(200) NOT NULL,
    difficulty_score INTEGER,
    status VARCHAR(20) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### GEO文章表 (geo_articles)
```sql
CREATE TABLE geo_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER REFERENCES keywords(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT,
    content TEXT NOT NULL,
    quality_score INTEGER,
    ai_score INTEGER,
    readability_score INTEGER,
    quality_status VARCHAR(20) DEFAULT 'pending',
    platform VARCHAR(50),
    account_id INTEGER,
    publish_status VARCHAR(20) DEFAULT 'draft',
    publish_time DATETIME,
    scheduled_at DATETIME,
    target_platforms JSON,
    publish_strategy VARCHAR(20) DEFAULT 'draft',
    retry_count INTEGER DEFAULT 0,
    error_msg TEXT,
    index_status VARCHAR(20) DEFAULT 'uncheck',
    last_check_time DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### 收录检测记录表 (index_check_records)
```sql
CREATE TABLE index_check_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER REFERENCES keywords(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    keyword_found BOOLEAN,
    company_found BOOLEAN,
    check_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. API 接口规范

### 5.1 统一响应格式

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

### 5.2 分页列表格式

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "limit": 20
  }
}
```

### 5.3 核心接口清单

#### 客户管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/clients` | 客户列表 |
| POST | `/api/clients` | 创建客户 |
| PUT | `/api/clients/{id}` | 更新客户 |
| DELETE | `/api/clients/{id}` | 删除客户 |

#### GEO项目
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/geo/projects` | 项目列表 |
| POST | `/api/geo/projects` | 创建项目 |
| GET | `/api/geo/projects/{id}` | 项目详情 |
| PUT | `/api/geo/projects/{id}` | 更新项目 |
| DELETE | `/api/geo/projects/{id}` | 删除项目 |

#### 关键词管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/keywords` | 关键词列表 |
| POST | `/api/keywords/extract` | AI提取关键词 |
| POST | `/api/keywords` | 手动添加关键词 |
| DELETE | `/api/keywords/{id}` | 删除关键词 |

#### 文章生成
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/geo/articles` | 文章列表 |
| POST | `/api/geo/articles/generate` | AI生成文章 |
| GET | `/api/geo/articles/{id}` | 文章详情 |
| PUT | `/api/geo/articles/{id}` | 更新文章 |
| DELETE | `/api/geo/articles/{id}` | 删除文章 |

#### 发布任务
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auto-publish/tasks` | 任务列表 |
| POST | `/api/auto-publish/tasks` | 创建任务 |
| POST | `/api/auto-publish/tasks/{id}/run` | 立即执行任务 |
| GET | `/api/auto-publish/tasks/{id}` | 任务详情 |
| DELETE | `/api/auto-publish/tasks/{id}` | 取消任务 |

#### 收录检测
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/index-check` | 执行收录检测 |
| GET | `/api/index-check/records` | 检测记录 |
| GET | `/api/index-check/summary` | 收录汇总 |
| POST | `/api/index-check/batch` | 批量检测 |

#### 知识库
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/categories` | 分类列表 |
| POST | `/api/knowledge/categories` | 创建分类 |
| GET | `/api/knowledge/items` | 知识条目 |
| POST | `/api/knowledge/items` | 添加知识 |
| POST | `/api/knowledge/upload` | 上传文档 |

---

## 6. 前端页面路由

### 6.1 路由表

| 路径 | 组件 | 标题 | 权限 |
|------|------|------|------|
| `/dashboard` | DashboardPage | 首页 | 全部 |
| `/clients` | ClientPage | 客户管理 | 全部 |
| `/clients/projects` | Projects | GEO项目管理 | 全部 |
| `/knowledge` | KnowledgePage | 知识库管理 | 全部 |
| `/site-builder` | ConfigWizard | 智能建站 | 全部 |
| `/geo/keywords` | Keywords | 关键词蒸馏 | 全部 |
| `/geo/articles` | Articles | GEO文章生成 | 全部 |
| `/articles` | ArticleList | 文章管理 | 全部 |
| `/articles/add` | ArticleEdit | 新建文章 | 全部 |
| `/articles/edit/:id` | ArticleEdit | 编辑文章 | 全部 |
| `/accounts` | AccountList | 账号管理 | 全部 |
| `/accounts/add` | AccountAdd | 添加账号 | 全部 |
| `/auto-publish` | AutoPublishPage | 发布任务管理 | 全部 |
| `/publish` | PublishPage | 平台发布监控 | 全部 |
| `/geo/monitor` | Monitor | 收录监控 | 全部 |
| `/data-report` | DataReport | 数据报表 | 全部 |
| `/scheduler` | SchedulerPage | 定时任务 | 全部 |
| `/settings` | SettingsPage | 系统设置 | 全部 |

### 6.2 侧边栏菜单顺序

```javascript
[
  { title: '首页', path: '/dashboard', icon: 'House', order: 1 },
  { title: '客户管理', path: '/clients', icon: 'UserFilled', order: 2 },
  { title: 'GEO项目管理', path: '/clients/projects', icon: 'Grid', order: 3 },
  { title: '知识库管理', path: '/knowledge', icon: 'Reading', order: 4 },
  { title: '智能建站', path: '/site-builder', icon: 'Platform', order: 5 },
  { title: '关键词蒸馏', path: '/geo/keywords', icon: 'MagicStick', order: 6 },
  { title: 'GEO文章生成', path: '/geo/articles', icon: 'EditPen', order: 7 },
  { title: '文章管理', path: '/articles', icon: 'Document', order: 8 },
  { title: '账号管理', path: '/accounts', icon: 'User', order: 9 },
  { title: '发布任务管理', path: '/auto-publish', icon: 'List', order: 10 },
  { title: '平台发布监控', path: '/publish', icon: 'Monitor', order: 11 },
  { title: '收录监控', path: '/geo/monitor', icon: 'Monitor', order: 12 },
  { title: '数据报表', path: '/data-report', icon: 'DataAnalysis', order: 13 },
  { title: '定时任务', path: '/scheduler', icon: 'Timer', order: 14 },
  { title: '系统设置', path: '/settings', icon: 'Setting', order: 15 }
]
```

---

## 7. 质量保障体系

### 7.1 质量标准

| 维度 | 检测方法 | 通过阈值 |
|-----|---------|---------|
| 关键词密度 | 正则计数 | 2%-5% |
| AI味检测 | 本地模型 | < 50% |
| 内容原创性 | 相似度对比 | > 70% |
| 结构完整性 | 规则检测 | 必须通过 |
| 敏感词检测 | 敏感词库 | 0个 |
| 平台合规性 | 规则检测 | 必须通过 |

### 7.2 发布前检查清单

- [ ] 文章标题完整
- [ ] 正文内容长度达标（>500字）
- [ ] 关键词自然融入
- [ ] 无敏感词汇
- [ ] 配图合规
- [ ] 目标平台选择正确
- [ ] 目标账号状态正常

---

## 8. 监控告警体系

### 8.1 监控指标

| 指标类型 | 指标名称 | 告警阈值 |
|---------|---------|---------|
| 收录指标 | 收录掉落 | 连续2天未收录 |
| 收录指标 | 命中率下降 | 周环比下降>15% |
| 任务指标 | 发布失败率 | 失败率>20% |
| 系统指标 | 任务执行超时 | 超过预期时间2倍 |
| 账号指标 | 账号异常 | 登录失败/被封禁 |

### 8.2 通知渠道

- 站内消息
- 邮件通知
- Webhook（钉钉/企业微信）

---

## 9. 附录

### 9.1 术语表

| 术语 | 英文 | 说明 |
|-----|------|------|
| GEO | Generative Engine Optimization | AI搜索引擎优化 |
| RAG | Retrieval-Augmented Generation | 检索增强生成 |
| AI味 | AI Flavor | AI生成内容的特征 |
| 收录 | Indexing | 关键词出现在AI回答中 |
| 掉落 | Drop | 已收录的关键词不再出现 |
| 命中率 | Hit Rate | 关键词在AI回答中的出现频率 |

### 9.2 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|-----|------|----------|--------|
| v1.0 | 2025-01-14 | 初始版本 | 开发者 |
| v1.1 | 2025-01-14 | 修正AI平台、聚焦核心指标 | 开发者 |
| v2.0 | 2026-05-12 | 系统化业务流程PRD | AI架构师 |

---

**文档结束**
