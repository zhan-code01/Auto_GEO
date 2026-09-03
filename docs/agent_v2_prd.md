# 智能体 V2 重构 PRD（基于 LangGraph + 生成用户问题链路）

| 项 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 创建日期 | 2026-08-03 |
| 状态 | 评审中 |
| 关联模块 | `backend/services/agent_v2/`（新建）、`backend/services/smart_article/`（复用） |
| 废弃模块 | `backend/services/agent/`（整个老目录） |

---

## 一、背景与目标

### 1.1 背景

当前系统存在两套并行的文章生成链路：

| 链路 | 入口 | 状态 | 问题 |
|---|---|---|---|
| **老蒸馏链路** | `agent/` 智能体 → `ArticleGenerationBatchService` → `ProjectQuestionService` | 已废弃 | 走关键词蒸馏，质量差；智能体架构本身已半废弃 |
| **新问题链路** | `smart_article/` 模块（REST API） | 生产可用 | 走"生成用户问题→生成文章"，质量好；但**智能体完全没接入** |

老智能体模块（`backend/services/agent/`）存在严重的设计缺陷（详见 `OPTIMIZATION_PLAN.md`）：
- `orchestrator.py` 1271 行承载 7 种职责
- 意图识别新旧两套并存且漂移（`intent_recognizer.py` vs `intent_recognition/`）
- `tool_registry_v2.py` 因 handler 签名不匹配实际不可用
- `OPTIMIZATION_PLAN` 标记 Phase 3-5 完成，但 `orchestrator_v2.py`/`tool_index.py`/`state.py` 文件根本不存在
- 记忆合并两套语义共存（`AgentMemory.merge_slots` vs `MemoryMerger.merge`）
- 跨会话事实无处可存

### 1.2 目标

废弃老智能体，基于 LangGraph 重建新智能体模块，实现：

1. **统一接入 smart_article 新链路**：所有文章生成必须经过"问题→文章"链路，从工具签名层面杜绝无问题生成
2. **图驱动编排**：用 LangGraph StateGraph 替代 if-else，状态流转可视化、可测试
3. **引导式流程**：新客户首次进入自动引导（建客户→传知识库→建项目→生成问题→生成文章→绑定平台→发布）
4. **防跳步机制**：三层防护（图条件边 + Gate 节点 + 工具自检），LLM 无法绕过问题生成直接调文章工具
5. **三层记忆**：会话短期记忆 / 用户长期事实 / 用户偏好，解决跨会话事实断层
6. **完整工具集**：覆盖客户/知识库/项目/问题/文章/发布/账号 9 大模块全生命周期

### 1.3 非目标

- 不重构 `smart_article/` 模块本身（它已生产可用，只做适配封装）
- 不重构 Playwright 发布器（复用现有 `publishers/`）
- 不重构 RAGFlow 集成（复用现有 `ragflow_client.py` + `knowledge_ingestion_service.py`）
- 不动前端（仅新增 `/api/agent-v2/*` 端点，前端切换调用）

---

## 二、核心概念与数据关系

### 2.1 实体关系链

```
User（系统用户，登录账号）
  │
  └─ Client（客户/公司，业务实体）
        │
        ├─ KnowledgeCategory（知识库分类，绑定 Client）
        │     └─ Knowledge（知识条目，对应 RAGFlow document）
        │
        └─ Project（GEO 内容项目）
              │
              ├─ SmartArticleQuestion（用户问题，问题池）
              │     └─ SmartArticleJob（文章生成任务）
              │           └─ GeoArticle（文章）
              │                 └─ PublishRecord（发布记录）
              │
              └─ Keyword（关键词，兼容老链路）
```

### 2.2 关键概念澄清

| 概念 | 说明 |
|---|---|
| **User** | 系统登录账号，admin 可管理。普通用户只能操作自己的 Client |
| **Client** | 业务客户公司。**知识库绑定在 Client 上**（一个 Client 一个 RAGFlow dataset） |
| **Project** | GEO 内容项目，归属 Client。一个 Client 可有多个 Project |
| **SmartArticleQuestion** | 用户问题，问题池。`has_article` 标记是否已生成文章 |
| **GeoArticle** | 文章，归属 Project 和 Keyword |
| **Account** | 第三方平台账号（知乎/百家号等），**一对一绑定平台** |

### 2.3 引导流程主链路

```
新建客户      → 上传知识库           → 建项目         → 生成问题          → 生成文章                    → 绑定平台          → 发布
   │                │                    │                 │                   │                            │                 │
create_client   upload_knowledge_files  create_project   plan_question_batch  generate_articles_from_questions  start_platform_auth  publish_articles
```

---

## 三、新架构总体设计

### 3.1 设计原则

| 原则 | 说明 |
|---|---|
| **图驱动** | LangGraph StateGraph 显式化节点和边，条件路由防跳步 |
| **状态单一来源** | 整个对话状态 = `AgentState`（TypedDict），所有节点读写同一个 state |
| **Tool 只暴露新链路** | 文章生成必须经过 smart_article 问题链路，不接老蒸馏路径 |
| **强 Gate 防跳步** | 三层防护：图条件边 + Gate 节点 + Tool 自检 |
| **记忆三层分离** | 会话短期 / 用户长期事实 / 用户偏好 |
| **适配器模式** | `adapters/` 层包装现有服务，不在 Tool 里直接调 Service |
| **Action 按钮机制** | 工具返回 `actions` 列表，前端渲染成按钮（预览/登录/上传等） |

### 3.2 LangGraph 图结构

```
                    ┌─────────────────┐
                    │  LOAD_CONTEXT   │  ← 取 session / 用户事实 / 偏好
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  INTENT_ROUTER  │  ← 意图分类（LLM + 规则短路）
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   SLOT_CHECK    │  ← 必填字段检查，缺失则引导式追问
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┬───────────────┐
        │                    │                    │               │
   ┌────▼─────┐       ┌──────▼──────┐      ┌──────▼─────┐   ┌─────▼─────┐
   │   CHAT   │       │  QUERY_FLOW │      │ ARTICLE_   │   │ BINDING_  │
   │  (闲聊)  │       │ (查询类)    │      │ FLOW (文章)│   │ FLOW(绑定)│
   └──────────┘       └──────┬──────┘      └──────┬─────┘   └─────┬─────┘
                             │                    │               │
                             │              ┌─────▼─────┐         │
                             │              │ QUESTION_ │         │
                             │              │ GATE      │ ← 关键!│
                             │              └─────┬─────┘         │
                             │                    │               │
                             │           ┌────────┴────────┐      │
                             │           ▼                 ▼      │
                             │   ┌──────────────┐  ┌───────────┐  │
                             │   │ PLAN_QUESTIONS│  │GEN_ARTICLES│ │
                             │   │ (生成问题池)  │  │(从问题生文)│  │
                             │   └──────────────┘  └───────────┘  │
                             │           │                 │      │
                             └───────────┴─────────────────┴──────┘
                                                   │
                                            ┌──────▼──────┐
                                            │ PUBLISH_FLOW│ (可选)
                                            └─────────────┘
                                                   │
                                            ┌──────▼──────┐
                                            │   AGGREGATE │ ← 结果回写 state
                                            └─────────────┘
                                                   │
                                            ┌──────▼──────┐
                                            │ PERSIST_MEM │ ← 写库 + 摘要
                                            └─────────────┘
                                                   │
                                            ┌──────▼──────┐
                                            │   RESPOND   │
                                            └─────────────┘

注：SLOT_CHECK 缺失槽位时直接到 RESPOND（带追问文案），用户下一轮回复后
    重新进 LOAD_CONTEXT → INTENT_ROUTER → SLOT_CHECK，槽位累积直到齐全。
```

### 3.3 目录结构

```
backend/services/agent_v2/                    # 全新目录，不动 agent/ 老目录
├── __init__.py
├── graph.py                                  # LangGraph 图定义（节点+边）
├── state.py                                  # AgentState TypedDict
├── nodes/
│   ├── __init__.py
│   ├── load_context.py
│   ├── intent_router.py                      # 含 rule_shortcut + llm_classify
│   ├── slot_check.py                         # 必填槽位检查 + 引导式追问
│   ├── question_gate.py
│   ├── plan_questions.py
│   ├── gen_articles.py
│   ├── query_flow.py
│   ├── binding_flow.py
│   ├── chat_flow.py
│   ├── publish_flow.py
│   ├── aggregate.py
│   ├── persist_mem.py
│   └── respond.py
├── tools/
│   ├── __init__.py                           # tool registry，单一来源
│   ├── base.py                               # @tool 装饰器 + Gate 基类
│   ├── user_tools.py                         # 系统用户管理（admin）
│   ├── client_tools.py                       # 客户管理
│   ├── knowledge_tools.py                    # 知识库管理
│   ├── project_tools.py                      # 项目管理
│   ├── question_tools.py                     # 问题管理
│   ├── article_tools.py                      # 文章管理
│   ├── account_tools.py                      # 平台账号管理
│   ├── publish_tools.py                      # 发布执行
│   └── system_tools.py                       # 系统统计与诊断
├── memory/
│   ├── __init__.py
│   ├── session_store.py                      # 会话短期记忆
│   ├── fact_store.py                         # user_agent_facts 读写（新）
│   ├── preference_store.py                   # 用户偏好
│   ├── merger.py                             # 唯一的 merge 实现
│   ├── extractor.py                          # 事实/槽位抽取
│   └── summary.py                            # 摘要
├── intent/
│   ├── __init__.py
│   ├── rule_shortcut.py                      # 高频规则短路
│   ├── llm_router.py                         # LLM 路由
│   └── schema.py                             # intent 定义 + examples
├── adapters/                                 # 包装现有服务供 tool 调用
│   ├── __init__.py
│   ├── smart_article_adapter.py              # 包装 SmartArticleService
│   ├── question_pool_adapter.py              # 包装 SmartArticleQuestionPoolService
│   ├── knowledge_adapter.py                  # 包装 KnowledgeIngestionService
│   ├── publish_adapter.py                    # 包装 PlaywrightManager + AutoPublishTaskService
│   ├── account_adapter.py                    # 包装 AccountService
│   ├── client_adapter.py                     # 包装 Client CRUD
│   └── project_adapter.py                    # 包装 Project CRUD
├── actions.py                                # Action 类型定义（按钮）
└── api.py                                    # FastAPI 路由 /api/agent-v2/*
```

---

## 四、AgentState 状态定义

```python
# backend/services/agent_v2/state.py
from typing import TypedDict, Literal, Optional, Any
from datetime import datetime

class Action(TypedDict):
    type: str                  # preview_article / open_browser_auth / upload_knowledge / ...
    label: str                 # 按钮文案
    payload: dict              # 按钮数据

class ExecutionStatus(TypedDict):
    status: Literal[
        "completed", "need_clarification", "confirm_required",
        "running", "failed", "cancelled",
        "prerequisite_blocked", "waiting_user"
    ]
    message: Optional[str]

class AgentState(TypedDict):
    # ===== 输入 =====
    user_id: int
    session_id: str
    message: str
    attachments: list[dict]                    # 用户上传的附件

    # ===== 上下文（LOAD_CONTEXT 填充） =====
    history: list[dict]                        # 最近 N 条对话
    session_slots: dict                        # 当前会话槽位
    user_facts: dict                           # 跨会话事实（公司/行业/常选平台）
    preferences: dict                          # 用户偏好
    effective_slots: dict                      # 合并后的有效槽位（session > facts > preferences）
    onboarding_stage: Optional[str]            # 引导流程当前阶段（来自 user_facts）
    onboarding_completed: bool                 # 引导是否已完成（避免重复触发）

    # ===== 意图（INTENT_ROUTER 填充） =====
    intent: Literal[
        "chat", "query", "plan_questions",
        "generate_articles", "publish",
        "manage_binding", "manage_client",
        "manage_project", "manage_knowledge",
        "manage_user", "unknown"
    ]
    intent_slots: dict                         # 意图级别抽到的槽位
    confidence: float
    pending_intents: list[str]                 # 组合意图的后续意图队列
    pending_actions: list[dict]                # 暂存的后续动作（异步任务完成后触发）

    # ===== 槽位检查（SLOT_CHECK 填充） =====
    slots_ok: bool                             # 必填槽位是否齐全
    resolved_slots: dict                       # SLOT_CHECK 解析后的最终槽位（含多候选解析）
    missing_slots: list[str]                   # 缺失的必填槽位（用于追问）

    # ===== 文章流（ARTICLE_FLOW 填充） =====
    client_id: Optional[int]
    project_id: Optional[int]
    question_ids: list[int]                    # 已选问题
    questions_ready: bool                      # GATE 计算结果
    batch_id: Optional[int]
    article_ids: list[int]
    article_mode: Literal["from_questions", "batch"]  # 区分两种生成模式

    # ===== 发布流（PUBLISH_FLOW 填充） =====
    account_ids: list[int]
    publish_task_id: Optional[int]

    # ===== 异步任务追踪 =====
    async_task_refs: list[dict]                # 本轮触发的异步任务引用 [{task_type, task_id, query_tool}]

    # ===== 输出 =====
    reply: str
    actions: list[Action]
    status: ExecutionStatus
    slots_patch: dict                          # 待回写会话记忆
    facts_patch: list[dict]                    # 待回写用户事实
```

---

## 五、完整工具清单

### 5.1 模块 1：系统用户管理（admin 专用）

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `list_users` | `keyword?`, `role?`, `page?`, `limit?` | `{total, items:[{id,username,email,role,is_active}]}` | `api/user.py:475` |
| `create_user` | `username`, `password`, `email?`, `role?` | `{id, username, role}` | `api/user.py:220` |
| `update_user` | `user_id`, `email?`, `password?`, `role?`, `is_active?` | `{...}` | `api/user.py:569` |
| `delete_user` | `user_id` | `{id, username}` | `api/user.py:714` |
| `reset_user_password` | `user_id`, `new_password` | `{success}` | `api/user.py:612` |
| `unlock_user` | `user_id` | `{id, failed_login_attempts}` | `api/user.py:821` |

**Gate**：所有工具要求 `current_user.role == "admin"`。

### 5.2 模块 2：客户管理（引导流程第一步）

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `list_clients` | `keyword?`, `industry?`, `page?` | `{total, items:[{id,company_name,industry,project_count}]}` | `api/client.py:43` |
| `get_client` | `client_id` | `{...详情, projects:[...]}` | `api/client.py:124` |
| `create_client` | `company_name`, `industry`, `location`, `website`, `contact_person?`, `phone?`, `email?`, `description?` | `{client_id}` | `api/client.py:201` |
| `update_client` | `client_id`, `...可选字段` | `{success}` | `api/client.py:245` |
| `delete_client` | `client_id` | `{success}` | `api/client.py:410` |
| `get_client_stats` | - | `{total, active, industry_distribution}` | `api/client.py:451` |

**必填字段**：`company_name`、`industry`、`location`、`website`。

**引导时机**：新用户首次进入 → 检测无客户 → 引导 `create_client`。

### 5.3 模块 3：知识库管理

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `upload_knowledge_files` | `client_id`, `files[]`(docx/pdf/txt/md), `category?`, `description?` | `{uploaded, failed, category_id, ragflow_dataset_id, parse_triggered, document_ids[]}` | `api/knowledge.py:795` + `knowledge_ingestion_service.py:285` |
| `list_knowledge_categories` | `client_id?` | `[{category_id, name, doc_count, sync_status}]` | `tool_upload.py:116` |
| `list_knowledge_documents` | `category_id` | `[{doc_id, title, status, sync_status}]` | `knowledge.py` |
| `get_knowledge_parse_status` | `dataset_id`, `document_ids[]` | `[{doc_id, status, is_ready}]` | `knowledge.py:2280` + `ragflow_client.py:792` |
| `delete_knowledge_document` | `category_id`, `doc_id` | `{success}` | `ragflow_delete_service.py` |
| `delete_knowledge_category` | `category_id` | `{success}` | `knowledge.py:506` |
| `check_knowledge_ready` | `client_id` | `{has_docs, all_parsed, doc_count}` | `knowledge_ingestion_service.has_client_documents` |

**约束**：
- 支持格式：`.pdf`、`.doc`、`.docx`、`.txt`、`.md`
- 单文件 10MB，一次最多 5 个
- 上传同步，解析异步（RAGFlow 后台切分+向量化）
- `is_ready=true` 才可用于文章生成检索

**引导时机**：`create_client` 成功后 → 引导 `upload_knowledge_files` → 上传后提示"还有资料吗？没有的话可以建项目了"。

**Gate**：`generate_articles` 前可选检查 `check_knowledge_ready`（知识库未就绪不阻断，但提示质量可能下降）。

### 5.4 模块 4：项目管理

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `list_projects` | `client_id?` | `[{id, name, company_name, domain_keyword, status}]` | `api/keywords.py:149` |
| `get_project` | `project_id` | `{...详情}` | `api/keywords.py:164` |
| `create_project` | `client_id?`, `name`, `company_name`, `domain_keyword`, `description?`, `industry?` | `{id, name, ...}` | `api/keywords.py:174` |
| `update_project` | `project_id`, `...可选字段` | `{...}` | `api/keywords.py:201` |
| `delete_project` | `project_id` | `{success}` | `api/keywords.py:226` |

**必填字段**：`name`、`company_name`、`domain_keyword`。

**引导时机**：知识库上传完成（或用户跳过）→ 引导 `create_project` → 建项目后引导 `plan_question_batch`。

### 5.5 模块 5：问题管理（核心：生成用户问题）

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `list_questions` | `project_id`, `has_article?`(可选过滤), `generation_batch_id?`(可选过滤，**需扩展**) | `[{question_id, question, intent_type, has_article, article_id, article_generation_status}]` | `question_pool_service.py:108` |
| `plan_question_batch` | `project_id`, `count?`(默认 5), `mode`("auto"/"manual"), `input_question?`(manual 时必填) | `{question_batch_id, status, planned_count, queued_count}` | `question_pool_service.py:25` + 异步 `run_batch` |
| `get_question_batch_status` | `batch_id` | `{status, requested_count, planned_count, queued_count, success_count, failed_count, expanded_terms[]}` | `question_pool_service.py:133` |
| `delete_questions` | `question_ids[]` | `{deleted: n}` | `question_pool_service.py:119` |
| `select_questions_for_generation` | `question_ids[]` | `{selected: n, invalid: [...]}` | 校验 `has_article=False` |

**关键设计**：
- `list_questions` 返回的每条问题都带 `has_article` 标记，前端可区分"已生成/未生成"
- `plan_question_batch` 走 `smart_article` 的 `SmartArticleQuestionPlanner`（两阶段 Prompt + 75% 推荐型比例约束）
- 问题池有唯一约束 `(project_id, normalized_question)`，自动去重
- **异步行为**：`plan_question_batch` API 同步只返回 `{batch_id, status:"pending"}`，真正的 LLM 规划在 `BackgroundTasks` 里跑。状态机：`pending` → `planning_questions` → `saving_questions` → `completed` / `failed`
- **完成事件通知**：无回调、无 WebSocket 主动推送，只能轮询 `get_question_batch_status` 直到 `status` 变 `completed`。本批次 question_ids 通过 `list_questions?generation_batch_id={batch_id}` 拉取

**需扩展的底层改动（Phase 2）**：
1. `SmartArticleQuestionPoolService.list_questions`（`question_pool_service.py:108`）需新增 `generation_batch_id` 过滤参数。当前只支持 `project_id` 和 `has_article` 过滤，**不带 `generation_batch_id` 过滤会混入同项目历史问题**。ORM 字段 `SmartArticleQuestion.generation_batch_id` 已存在（`models.py:1970`），扩展成本极低
2. `get_question_batch_status` 出参字段对齐：PRD 原写 `{status, total, planned_count}`，实际接口返回的是 `{status, requested_count, planned_count, queued_count, success_count, failed_count, ...}`，工具层需按实际字段解析

**引导时机**：`create_project` 成功后 → 引导 `plan_question_batch`（"要生成几个用户问题吗？"）。

### 5.6 模块 6：文章管理

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `list_articles` | `project_id?`, `publish_status?`, `limit?` | `[{article_id, title, status, publish_status, created_at}]` | `api/geo.py:318` |
| `get_article` | `article_id` | `{id, title, content, ...}` + **预览按钮 Action** | `api/geo.py:377` |
| `delete_article` | `article_id` | `{success}` | `api/geo.py:428` |
| `generate_articles_from_questions` | `question_ids[]` | `{article_batch_id, accepted_question_ids[], skipped_question_ids[]}` | `smart_article/service.py:63` `create_selection_batch`（同步返回 batch+skipped，文章异步生成） |
| `generate_articles_batch` | `project_id`, `count`, `mode?`(默认 auto) | `{question_batch_id, article_batch_id, planned_count, question_ids[]}` | adapter 同步封装：`plan_batch_sync` → `generate_articles_sync`（详见 7.5 节） |
| `get_article_batch_status` | `batch_id` | `{status, requested_count, planned_count, queued_count, success_count, failed_count, processing_count, note, jobs[]}` | `smart_article/service.py` `get_batch` |
| `retry_article_job` | `job_id` | `{job_id, status}` | `smart_article/service.py:342` |

**关键设计：`generate_articles_batch` 全自动链路**

用户说"根据 XXX 项目生成 5 篇文章"时，此工具通过 adapter 层同步封装自动执行（详见 7.5 节）：
1. 调 `QuestionPoolAdapter.plan_batch_sync(project_id, count=5, mode="auto")` 同步等待 LLM 规划完成，拿到本批次 `question_ids`
2. 不暂停确认，调 `QuestionPoolAdapter.generate_articles_sync(question_ids)` 创建文章生成任务（异步在后台跑）
3. 返回 `{question_batch_id, article_batch_id, planned_count, question_ids}`

底层仍走"问题→文章"链路，但对用户透明。**这是用户明确要求的"不用确认直接生成"行为**。

**Gate**：`generate_articles_from_questions` 强制校验所有 `question_ids` 必须 `has_article=False` 且非 `generating`（第三层 Tool 自检，详见 7.4 节）。

**Action 按钮**：
- `get_article` 返回 `preview_article` 按钮，前端点击打开文章预览弹窗
- `list_articles` 可返回 `preview_article` / `publish_article` 按钮组（**注：文章编辑功能已废弃，不提供 `edit_article` 按钮**）

### 5.7 模块 7：发布平台账号管理

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `list_user_bindings` | `platform?` | `[{platform, account_id, account_name, username, is_authorized, last_auth_time, status}]` | `api/account.py:140` |
| `list_publish_platforms` | - | `[{platform_id, name, login_url, is_publishable}]` | `api/publish.py:141` |
| `start_platform_auth` | `platform`, `account_name?`, `account_id?` | `{task_id, login_url}` + **拉起浏览器按钮 Action** | `api/account.py:491` + `playwright_mgr.py:197` |
| `get_auth_status` | `task_id` | `{status, account_id?}` | `api/account.py:552` |
| `confirm_auth` | `task_id` | `{account_id, platform}` | `api/account.py:625` |
| `cancel_auth` | `task_id` | `{success}` | `api/account.py:712` |
| `check_account_status` | `account_id?` 或 `use_browser: bool` | `{checked, valid, expired}` | `api/account.py:739` |
| `delete_account` | `account_id`, `hard?` | `{success}` | `api/account.py:353` |
| `list_account_groups` | - | `[{group_id, name, account_count}]` | `api/account.py:796` |
| `create_account_group` | `name`, `icon?`, `color?` | `{group_id}` | `api/account.py:833` |
| `delete_account_group` | `group_id` | `{success}` | `api/account.py:884` |

**关键设计**：
- `list_user_bindings` 就是用户问"我绑了哪些平台"的查询工具
- `list_publish_platforms` 返回 19 个支持平台（知乎/百家号/搜狐/头条/小红书/抖音/快手/微博/B站/微信公众号/简书/掘金/企鹅号/CSDN/网易号/博客园/豆瓣/百度贴吧等）
- `start_platform_auth` 拉起本地 Chrome（headless=False），用户扫码登录后保存加密 cookies
- **Action 按钮**：`start_platform_auth` 返回 `open_browser_auth` 按钮，前端点击打开浏览器登录窗口

**引导时机**：文章生成中 → 引导 `list_publish_platforms` + `start_platform_auth`（"文章生成中，要不要先绑定发布平台？"）。

### 5.8 模块 8：发布执行

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `publish_articles` | `article_ids[]`, `account_ids[]`, `declare_ai_content?`, `execution_mode?`(默认 cloud_browser) | `{task_id, total_count}` | `api/auto_publish.py:242` |
| `get_publish_task_status` | `task_id` | `{status, completed_count, failed_count, records[]}` | `api/auto_publish.py:165` |
| `cancel_publish_task` | `task_id` | `{success}` | `api/auto_publish.py:544` |
| `retry_publish_task` | `task_id` | `{success}` | `api/auto_publish.py:576` |
| `list_publish_records` | `article_id?`, `account_id?` | `[{record_id, article_id, account_id, status, platform_url}]` | `api/publish.py:449` |
| `retry_publish_record` | `record_id` | `{success}` | `api/publish.py:502` |

**Gate**：`publish_articles` 前置检查所有 `account_ids` 必须 `is_authorized=true`，否则提示"请先登录 XX 平台"并返回 `start_platform_auth` Action。

**引导时机**：文章生成完成 + 平台已绑定 → 引导 `publish_articles`（"文章生成完成，要发布到哪些平台？"）。

### 5.9 模块 9：系统统计与诊断（admin 辅助）

| 工具名 | 入参 | 出参 | 底层实现 |
|---|---|---|---|
| `get_system_stats` | - | `{users, projects, accounts, articles}` | `api/admin.py:357` |
| `get_detailed_stats` | - | `{...详细业务统计}` | `api/admin.py:576` |
| `check_ragflow_status` | - | `{configured, reachable, dataset_count}` | `ragflow_client.py` |

**Gate**：要求 `current_user.role == "admin"`。

---

## 六、引导式流程设计

### 6.1 引导流程图

```
新用户首次进入
    │
    ▼
[CHECK_ONBOARDING] 检查用户是否已有客户
    │
    ├─ 无客户 → [GUIDE_CREATE_CLIENT]
    │              │ "您好！我是您的内容运营助手。我们先创建第一个客户吧。"
    │              │ "请提供：公司名称、行业、所在地、官网"
    │              ▼
    │           create_client 工具
    │              │
    │              ▼
    │           [GUIDE_UPLOAD_KNOWLEDGE]
    │              │ "已为您创建客户【XX公司】。建议上传公司资料构建知识库，"
    │              │ "知识库会让生成的文章更贴合您的业务。"
    │              │ Action: [上传知识库] 按钮
    │              ▼
    │           upload_knowledge_files 工具
    │              │
    │              ▼
    │           [PROMPT_MORE_KNOWLEDGE]
    │              │ "资料已上传，正在解析中。还有其他资料吗？"
    │              │ "没有的话可以开始建项目了。"
    │              │ 用户: "没有了" / "还有"
    │              ▼
    │           [GUIDE_CREATE_PROJECT]
    │              │ "好的，我们来建第一个项目。"
    │              │ "请提供：项目名称、公司名称、领域关键词"
    │              ▼
    │           create_project 工具
    │              │
    │              ▼
    │           [GUIDE_PLAN_QUESTIONS]
    │              │ "项目【XX】建好了。要生成几个用户问题吗？"
    │              │ "这些问题会作为文章生成的起点。"
    │              ▼
    │           plan_question_batch 工具
    │              │
    │              ▼
    │           [GUIDE_GENERATE_ARTICLES]
    │              │ "已生成 N 个用户问题。要把这些问题都生成文章吗？"
    │              │ Action: [查看问题] [全部生成] 按钮
    │              ▼
    │           generate_articles_from_questions 工具
    │              │
    │              ▼
    │           [GUIDE_BIND_PLATFORM]
    │              │ "文章正在生成中。要不要先绑定发布平台？"
    │              │ "支持知乎、百家号、CSDN 等 19 个平台。"
    │              │ Action: [查看支持平台] [绑定平台] 按钮
    │              ▼
    │           start_platform_auth 工具
    │              │
    │              ▼
    │           [GUIDE_PUBLISH]
    │              │ "文章生成完成，平台已绑定。要发布到哪些平台？"
    │              ▼
    │           publish_articles 工具
    │
    └─ 有客户 → [NORMAL_CHAT] 正常对话模式
                    │
                    ▼
                INTENT_ROUTER 路由到对应工具
```

### 6.2 引导流程的关键规则

1. **引导只触发一次**：仅对"零客户 + `onboarding_completed != true`"的用户触发；引导跑到 `publish` 阶段或用户主动跳过后，标记 `onboarding_completed = true`，后续不再触发
2. **引导不是强制的**：用户随时可以打断说"我想直接生成文章"，系统走正常路由
3. **每个引导节点都带 Action 按钮**：用户可点击按钮或文字回复
4. **引导状态持久化**：记录用户当前引导阶段到 `user_agent_facts`，跨会话可恢复
5. **跳过机制**：用户说"跳过"可跳过当前步骤；说"不要引导了"可关闭引导并标记 `onboarding_completed = true`
6. **Gate 机制仍然生效**：即使用户跳过引导直接说"生成文章"，QUESTION_GATE 仍会检查问题池
7. **打断即暂停**：用户在引导流程中突然提其他需求（如"看下我的文章"），系统立即响应该请求，引导流程暂停但状态保留，用户下次回来从暂停处继续

### 6.2.1 多客户场景的引导触发逻辑

| 用户状态 | 触发逻辑 |
|---|---|
| 零客户 + `onboarding_completed != true` | 走完整引导流程 |
| 已有客户 + `onboarding_completed = true` | 不触发引导，走正常 SLOT_CHECK |
| 引导流程跑到 `publish` 阶段 | 标记 `onboarding_completed = true`，后续不再触发 |
| 引导中途用户说"跳过" | 标记 `onboarding_completed = true`（用户主动放弃即视为完成） |
| 已有客户新建客户 B | 走正常 `create_client` + SLOT_CHECK 流程；创建成功后给一个**轻提示 Action**"是否上传知识库？"（可点击可忽略，不强制） |

**关键**：引导流程的价值是"教会新用户系统怎么用"，学会后就该退场。已有客户的用户新建客户不再强制走完整引导链路，仅给轻提示。

### 6.3 引导阶段定义

```python
ONBOARDING_STAGES = [
    "create_client",           # 新建客户
    "upload_knowledge",        # 上传知识库
    "create_project",          # 建项目
    "plan_questions",          # 生成问题
    "generate_articles",       # 生成文章
    "bind_platform",           # 绑定平台
    "publish",                 # 发布
    "completed",               # 引导完成
]
```

存储在 `user_agent_facts` 表，`fact_key="onboarding_stage"`。

---

## 七、防跳步 Gate 机制（核心）

### 7.1 三层防护

| 层级 | 机制 | 说明 |
|---|---|---|
| **第一层：图条件边** | LangGraph 的 `add_conditional_edges` | `INTENT_ROUTER → generate_articles` 意图时按槽位分流：有 `question_ids` 强制进 `QUESTION_GATE`；有 `count` 走 `gen_articles_batch`（绕过 GATE 但工具内部自带规划）。**LLM 没有直连到 `gen_articles` 或 `gen_articles_batch` 的边，必须经过 `intent_router` 路由** |
| **第二层：Gate 节点** | `QUESTION_GATE` 节点逻辑 | 检查问题池是否就绪，未就绪路由到 `PLAN_QUESTIONS`。仅对 `from_questions` 模式生效 |
| **第三层：Tool 自检** | 工具自身校验 | `generate_articles_from_questions` 校验 `question_ids` 有效（`has_article=False` 且非 `generating`）；`generate_articles_batch` 内部 adapter 同步规划问题后串接前者的校验逻辑，等效兜底 |

### 7.2 第一层：图条件边

```python
# graph.py
def route_after_intent(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "generate_articles":
        # 关键：根据槽位区分两种子路径
        slots = state.get("resolved_slots", {}) or state.get("intent_slots", {})
        if slots.get("question_ids"):
            # 用户显式指定了问题 → 走 GATE 强校验
            state["article_mode"] = "from_questions"
            return "question_gate"
        elif slots.get("count") or slots.get("project_id"):
            # 用户只给 project_id + count → 走 batch 模式，绕过 GATE
            # 工具内部自动规划问题再生成，第三层 Tool 自检兜底
            state["article_mode"] = "batch"
            return "gen_articles_batch"
        else:
            # 槽位不足 → SLOT_CHECK 已应拦截，这里兜底走 GATE 反问
            return "question_gate"
    if intent == "plan_questions":
        return "plan_questions"
    if intent == "publish":
        return "publish_flow"
    if intent == "manage_binding":
        return "binding_flow"
    if intent == "query":
        return "query_flow"
    return "chat_flow"

graph.add_conditional_edges("intent_router", route_after_intent, {
    "question_gate": "question_gate",
    "gen_articles_batch": "gen_articles_batch",   # 新增节点：直接调 generate_articles_batch 工具
    "plan_questions": "plan_questions",
    "publish_flow": "publish_flow",
    "binding_flow": "binding_flow",
    "query_flow": "query_flow",
    "chat_flow": "chat_flow",
})

def route_after_question_gate(state: AgentState) -> str:
    if state["questions_ready"]:
        return "gen_articles"            # 走 generate_articles_from_questions 工具
    return "plan_questions"              # ← 问题没就绪，回去规划

graph.add_conditional_edges("question_gate", route_after_question_gate, {
    "gen_articles": "gen_articles",
    "plan_questions": "plan_questions",
})
```

**关键设计**：
- `gen_articles` 节点调 `generate_articles_from_questions` 工具（用户显式指定问题，GATE 强校验）
- `gen_articles_batch` 节点调 `generate_articles_batch` 工具（用户给 count，工具内部自动规划+生成，不暂停）
- 两条路径都经过第三层 Tool 自检兜底
- LLM 没有"跳"到 `gen_articles` 或 `gen_articles_batch` 的直连边，必须经过 `intent_router` 的路由判断

### 7.3 第二层：QUESTION_GATE 节点

```python
# nodes/question_gate.py
def question_gate(state: AgentState) -> AgentState:
    project_id = state.get("project_id")
    if not project_id:
        return {**state, "questions_ready": False,
                "reply": "请先指定项目，我再帮您规划用户问题。",
                "status": {"status": "need_clarification"}}

    # 查问题池
    questions = question_pool_adapter.list_questions(project_id, has_article=False)
    valid_question_ids = {q.id for q in questions}
    selected = state.get("question_ids", [])

    if selected and all(qid in valid_question_ids for qid in selected):
        # 用户已明确选了问题，且都是未生成的 → 放行
        return {**state, "questions_ready": True}

    if questions:
        # 池里有未用问题，但用户没选 → 反问
        return {**state, "questions_ready": False,
                "reply": f"项目下有 {len(questions)} 个待生成问题，要全部生成还是选若干？",
                "actions": [{
                    "type": "select_questions",
                    "label": "选择问题",
                    "payload": {"project_id": project_id, "questions": [...]}
                }],
                "status": {"status": "need_clarification"}}

    # 池里没有未生成问题 → 必须先规划
    return {**state, "questions_ready": False,
            "reply": "项目问题池已空，我先帮您规划一批用户问题？",
            "actions": [{
                "type": "plan_questions",
                "label": "生成问题",
                "payload": {"project_id": project_id}
            }],
            "status": {"status": "need_clarification"}}
```

### 7.4 第三层：Tool 自检（兜底）

```python
# tools/article_tools.py
@tool(
    name="generate_articles_from_questions",
    requires=["question_ids"],
    gate="questions_are_unused",
)
async def generate_articles_from_questions(ctx: ExecutionContext):
    question_ids = ctx.params["question_ids"]
    questions = await question_pool_adapter.get_many(question_ids)
    # 兜底校验：所有问题必须 has_article=False 且非 generating
    invalid = [q for q in questions
               if q.has_article or q.article_generation_status == "generating"]
    if invalid:
        return ToolOutcome.error(
            f"以下问题已生成过文章或正在生成中：{[q.id for q in invalid]}",
            need_clarification=True,
        )
    # 调用 adapter 创建文章生成批次（文章异步生成，立即返回 batch_id）
    # 注意：与 7.5 节 generate_articles_batch 共用同一个 QuestionPoolAdapter
    # generate_articles_sync 内部调 SmartArticleService.create_selection_batch
    return await question_pool_adapter.generate_articles_sync(
        user=ctx.user, project_id=ctx.params.get("project_id"),
        question_ids=question_ids,
    )
```

### 7.5 `generate_articles_batch` 全自动链路（用户要求的不确认模式）

**关键背景（基于代码现状的修正）**：底层 `SmartArticleQuestionPoolService.create_batch` + `run_batch` 是**异步的**——API `POST /api/smart-articles/question-batches` 同步只返回 `{batch_id, status:"pending"}`，真正的 LLM 问题规划在 FastAPI `BackgroundTasks` 里跑。`list_questions` 接口不支持按 `generation_batch_id` 过滤，轮询完成后用 `list_questions?project_id=...` 拉取会**混入历史问题**。

**Adapter 层同步封装方案**：智能体 adapter 不走 HTTP API，而是直接调 service 层并 `await` 后台逻辑，绕过 FastAPI 的 BackgroundTasks 机制：

```python
# adapters/question_pool_adapter.py
from backend.services.smart_article.question_pool_service import (
    SmartArticleQuestionPoolService, run_smart_question_batch,
)
from backend.services.smart_article.service import SmartArticleService, run_smart_article_batch
from backend.database.models import SmartArticleQuestion
from backend.database.session import SessionLocal

class QuestionPoolAdapter:
    async def plan_batch_sync(self, user, project_id: int, count: int, mode: str = "auto",
                              custom_questions: list[str] | None = None) -> tuple[int, list[int]]:
        """
        同步封装：创建问题批次 + 等待 LLM 规划完成 + 返回本批次的 question_ids。
        绕过 FastAPI BackgroundTasks，直接 await run_smart_question_batch。
        """
        db = SessionLocal()
        try:
            # 1. 创建批次记录（同步，status=pending）
            batch = SmartArticleQuestionPoolService(db).create_batch(
                user=user, project_id=project_id, count=count,
                mode=mode, custom_questions=custom_questions,
            )
            # 2. 同步等待 LLM 规划完成（阻塞当前协程，不阻塞事件循环）
            await run_smart_question_batch(batch.id)
            # 3. 直接查 ORM 拿本批次的问题（避免 list_questions 混入历史问题）
            questions = db.query(SmartArticleQuestion).filter(
                SmartArticleQuestion.generation_batch_id == batch.id
            ).all()
            question_ids = [q.id for q in questions]
            return batch.id, question_ids
        finally:
            db.close()

    async def generate_articles_sync(self, user, project_id: int, question_ids: list[int]) -> int:
        """
        同步封装：创建文章批次 + 等待文章生成启动（不等全部生成完）+ 返回 batch_id。
        文章生成是长任务，这里只等 jobs 创建完成，实际生成在后台继续跑。
        """
        db = SessionLocal()
        try:
            batch, skipped = SmartArticleService(db).create_selection_batch(
                current_user=user, project_id=project_id, question_ids=question_ids,
            )
            # 不 await run_smart_article_batch，让它在后台跑
            # 通过 BackgroundTasks 或 asyncio.create_task 触发
            import asyncio
            asyncio.create_task(run_smart_article_batch(batch.id))
            return batch.id
        finally:
            db.close()
```

**工具实现**：

```python
# tools/article_tools.py
@tool(
    name="generate_articles_batch",
    requires=["project_id", "count"],
)
async def generate_articles_batch(ctx: ExecutionContext):
    """用户说"根据 XXX 项目生成 5 篇文章"时的全自动链路。"""
    project_id = ctx.params["project_id"]
    count = ctx.params["count"]

    # 第一步：同步规划问题（adapter 内部 await run_smart_question_batch）
    question_batch_id, question_ids = await question_pool_adapter.plan_batch_sync(
        user=ctx.user, project_id=project_id, count=count, mode="auto",
    )

    # 第二步：创建文章生成任务（异步在后台跑，不等待完成）
    article_batch_id = await question_pool_adapter.generate_articles_sync(
        user=ctx.user, project_id=project_id, question_ids=question_ids,
    )

    return ToolOutcome.ok(
        data={
            "question_batch_id": question_batch_id,
            "article_batch_id": article_batch_id,
            "planned_count": count,
            "question_ids": question_ids,
        },
        reply=f"已自动规划 {len(question_ids)} 个用户问题并开始生成文章，"
              f"预计需要几分钟，可随时查询进度。",
        actions=[{
            "type": "view_batch_progress",
            "label": "查看生成进度",
            "payload": {"batch_id": article_batch_id},
            "interaction": "frontend_direct",
        }],
        async_task_refs=[{
            "task_type": "article_batch",
            "task_id": article_batch_id,
            "query_tool": "get_article_batch_status",
        }],
    )
```

**关键设计点**：
1. **Adapter 层同步封装**：`plan_batch_sync` 内部直接 `await run_smart_question_batch(batch.id)`，绕过 FastAPI BackgroundTasks，让工具一次调用就能拿到 question_ids
2. **ORM 直接查询**：用 `SmartArticleQuestion.generation_batch_id == batch.id` 精确查本批次问题，避免 `list_questions` 混入历史问题
3. **文章生成保持异步**：`generate_articles_sync` 只等 jobs 创建完成，实际生成用 `asyncio.create_task` 在后台跑，工具立即返回 `batch_id`
4. **阻塞协程不阻塞事件循环**：`await run_smart_question_batch` 是 async 调用，不会阻塞其他请求，但当前工具调用会等待 LLM 规划完成（约 10-60 秒，取决于 reasoning_tokens 消耗）
5. **超时风险**：LLM 规划可能耗时较长（`AIGenerationService` 超时 200 秒，`question_planner` 最多 3 轮迭代），工具调用期间 SSE 流需保持打开，前端显示"正在规划问题..."中间状态

**与 `generate_articles_from_questions` 的关系**：
- `generate_articles_from_questions`：用户显式指定 question_ids，走 QUESTION_GATE 强校验，调 `SmartArticleService.create_selection_batch` + 后台 `run_smart_article_batch`
- `generate_articles_batch`：用户给 project_id + count，adapter 同步规划问题后串接 `generate_articles_from_questions` 的后半段

### 7.6 槽位填充与引导式追问（必填字段缺失处理）

#### 7.6.1 机制概述

每个工具声明 `required_slots`（必填槽位）。工具执行前由 `SLOT_CHECK` 节点检查，缺失时**不报错**，而是用引导式提问让用户补充。这是除 QUESTION_GATE 之外的第二类 Gate，覆盖所有工具的必填字段。

#### 7.6.2 图结构补充

在 `INTENT_ROUTER` 之后、具体 FLOW 之前，统一加一层 `SLOT_CHECK` 节点：

```
INTENT_ROUTER
    │
    ▼
SLOT_CHECK  ← 新增：检查目标工具的 required_slots
    │
    ├─ 槽位齐全 → 路由到对应 FLOW（query/article/binding/...）
    │
    ├─ 槽位缺失 → 追问用户 → 等待下一轮 → 再次 SLOT_CHECK
    │
    └─ 多候选（如项目名匹配多个）→ 让用户选 → 等待下一轮
```

#### 7.6.3 槽位检查的三种结果

| 结果 | 处理 | 示例 |
|---|---|---|
| **齐全** | 直接执行工具 | 用户说"删除项目 123" → project_id 已有 → 执行 |
| **缺失** | 引导式追问 | 用户说"建项目" → 缺 name/company_name/domain_keyword → 反问 |
| **多候选** | 让用户选 | 用户说"看阿里云的文章" → 匹配到 2 个阿里云项目 → 让用户选 |

#### 7.6.4 引导式追问设计原则

1. **一次只问最关键的 1-2 项**：不要一次列 5 个必填字段让用户填表单，而是对话式逐步引导
2. **给示例和提示**：不只问"请提供公司名称"，而是"请提供公司名称（如：广州百盛千鲜食品有限公司）"
3. **利用 user_facts 预填**：如果用户事实里已有 `company`，直接预填并确认"我用您之前的公司【XX】可以吗？"
4. **多候选时给选择按钮**：匹配到多个时返回 `select_project` / `select_client` Action，前端渲染选择弹窗
5. **槽位部分填充时保留**：用户上一轮提供了 company_name，本轮提供 industry，两轮合并而非重问

#### 7.6.5 槽位检查实现

```python
# nodes/slot_check.py
def slot_check(state: AgentState) -> AgentState:
    intent = state["intent"]
    target_tool = INTENT_PRIMARY_TOOL.get(intent)  # 意图对应的主工具
    if not target_tool:
        return {**state, "slots_ok": True}  # 无主工具的意图（chat）直接放行

    tool = tool_registry.get(target_tool)
    required = tool.required_slots  # 如 ["company_name", "industry", "location", "website"]
    slots = {**state.get("session_slots", {}), **state.get("intent_slots", {})}

    # 1. 检查必填字段是否齐全
    missing = [r for r in required if not slots.get(r)]
    if not missing:
        return {**state, "slots_ok": True, "resolved_slots": slots}

    # 2. 部分缺失 → 引导式追问（一次最多问 2 项）
    ask = missing[:2]
    return {
        **state,
        "slots_ok": False,
        "reply": _build_slot_question(ask, slots, state["user_facts"]),
        "status": {"status": "need_clarification", "message": "等待用户补充信息"},
    }

def _build_slot_question(missing: list[str], slots: dict, facts: dict) -> str:
    """生成引导式追问文案，带示例和 user_facts 预填。"""
    prompts = {
        "company_name": "请提供公司名称（如：广州百盛千鲜食品有限公司）",
        "industry": "请提供所属行业（如：食品、教育、医疗）",
        "location": "请提供所在地（如：广州、北京、上海）",
        "website": "请提供公司官网（如：https://example.com）",
        "name": "请提供项目名称（如：阿里云产品评测）",
        "domain_keyword": "请提供领域关键词（如：云服务器、SaaS）",
        "project_id": "请指定项目，或告诉我项目名称我来帮您查找",
        "client_id": "请指定客户，或告诉我公司名称我来帮您查找",
        "question_ids": "请先选择要生成文章的问题",
        "article_ids": "请指定要发布的文章",
        "account_ids": "请指定发布到哪些平台账号",
    }
    # 利用 user_facts 预填建议
    if "company_name" in missing and facts.get("company"):
        prompts["company_name"] = f"是否使用您之前的公司【{facts['company']}】？（回复确认或提供新公司名）"

    lines = [prompts.get(m, f"请提供 {m}") for m in missing]
    return "为了帮您完成操作，还需要以下信息：\n" + "\n".join(f"• {l}" for l in lines)
```

#### 7.6.6 多候选处理

```python
# nodes/slot_check.py
def resolve_ambiguous(state: AgentState, field: str, hint: str) -> AgentState:
    """模糊匹配到多个候选时，让用户选。"""
    if field == "project_id":
        candidates = project_adapter.search_by_name(state["user_id"], hint)
        if len(candidates) > 1:
            return {
                **state,
                "slots_ok": False,
                "reply": f"找到 {len(candidates)} 个匹配的项目，请选择：",
                "actions": [{
                    "type": "select_project",
                    "label": "选择项目",
                    "payload": {"candidates": [{"id": p.id, "name": p.name} for p in candidates]}
                }],
                "status": {"status": "need_clarification"},
            }
        if len(candidates) == 1:
            return {**state, "slots_ok": True, "resolved_slots": {field: candidates[0].id}}
    # 类似处理 client_id 等
    ...
```

#### 7.6.7 跨轮槽位累积

用户补充槽位时，新槽位与已有槽位合并，不重问已填项：

```python
# 用户第一轮："建项目" → intent=manage_project, 缺 name/company_name/domain_keyword
# 系统追问："请提供项目名称、公司名称、领域关键词"
#
# 用户第二轮："项目叫阿里云评测，公司是阿里云"
# → intent_slots = {name: "阿里云评测", company_name: "阿里云"}
# → 仍缺 domain_keyword
# → 系统只问："请提供领域关键词（如：云服务器、SaaS）"
#
# 用户第三轮："云服务器"
# → 槽位齐全 → 执行 create_project
```

实现：`SLOT_CHECK` 节点读 `session_slots`（已有）+ `intent_slots`（本轮新抽）合并后检查，缺失项追问时跳过已有项。

#### 7.6.8 各工具必填槽位清单

| 工具 | required_slots | 缺失时追问示例 |
|---|---|---|
| `create_client` | `company_name`, `industry`, `location`, `website` | "请提供公司名称、行业、所在地、官网" |
| `update_client` | `client_id` | "请指定要修改的客户" |
| `delete_client` | `client_id` | "请指定要删除的客户" |
| `create_project` | `name`, `company_name`, `domain_keyword` | "请提供项目名称、公司名称、领域关键词" |
| `update_project` | `project_id` | "请指定要修改的项目" |
| `delete_project` | `project_id` | "请指定要删除的项目" |
| `plan_question_batch` | `project_id` | "请指定项目，或告诉我项目名称" |
| `generate_articles_batch` | `project_id`, `count` | "请指定项目，以及要生成几篇文章" |
| `generate_articles_from_questions` | `question_ids` | QUESTION_GATE 已处理 |
| `get_article` | `article_id` | "请指定要查看的文章，或告诉我文章标题" |
| `delete_article` | `article_id` | "请指定要删除的文章" |
| `start_platform_auth` | `platform` | "请指定要绑定的平台（如：百家号、知乎）" |
| `publish_articles` | `article_ids`, `account_ids` | "请指定要发布的文章和目标平台账号" |
| `upload_knowledge_files` | `client_id`, `files` | "请指定客户，并上传文件" |
| `delete_knowledge_document` | `category_id`, `doc_id` | "请指定要删除的文档" |

#### 7.6.9 与引导流程的关系

| 场景 | 走 SLOT_CHECK | 走引导流程 |
|---|---|---|
| 用户主动说"建客户" | 是（缺字段就追问） | 否 |
| 新用户首次进入 | 否（直接走引导） | 是 |
| 引导流程被打断后回来 | 否（继续引导） | 是 |
| 用户跳过引导后操作 | 是 | 否 |

**关键**：引导流程和 SLOT_CHECK 互补。引导流程负责"带新用户走完整链路"，SLOT_CHECK 负责"用户主动操作时补齐必填字段"。两者都用 `need_clarification` 状态等待用户回复。

---

## 八、记忆与 Slot 管理

记忆系统的核心是 **Slot（槽位）**——结构化的对话状态字段。记忆是存储，slot 是字段化的记忆视图。三层记忆里都包含 slot。

### 8.1 Slot 分类体系

#### 8.1.1 按生命周期分（对应三层存储）

| 类型 | 存储位置 | 生命周期 | 示例 |
|---|---|---|---|
| **会话级 slot** | `conversation_sessions.slots` (JSON) | 单会话内有效，新会话不继承 | 本轮 intent、临时 question_ids、当前操作目标 |
| **用户事实 slot** | `user_agent_facts` (新表) | 跨会话，需显式失效 | company、industry、preferred_platforms、default_project_id |
| **用户偏好 slot** | `user_agent_preferences` (复用) | 跨会话，用户主动改 | tone、require_confirmation_before_publish |

#### 8.1.2 按用途分

| 类型 | 说明 | 示例 |
|---|---|---|
| **工具入参 slot** | 直接作为工具参数 | `project_id`、`client_id`、`question_ids` |
| **上下文 slot** | 影响 LLM 决策，不直接传工具 | `current_topic`、`last_action` |
| **派生 slot** | 由其他 slot 计算得出 | `available_questions_count`、`project_summary` |

### 8.2 Slot 来源与合并优先级

| 来源 | 优先级 | 说明 | 示例 |
|---|---|---|---|
| `user_message` | 60（最高） | 用户本轮明确说的 | "项目叫阿里云" → name="阿里云" |
| `tool_result` | 50 | 工具返回值 | create_client 返回 client_id=123 |
| `db_resolver` | 45 | 数据库解析（名称→ID） | "阿里云项目" → project_id=456 |
| `llm_extract` | 40 | LLM 从消息抽取 | LLM 识别出 count=5 |
| `history` | 20 | 历史消息回填 | 上一轮提过的 company_name |
| `preference` | 15 | 用户偏好 | default_project_id |
| `default` | 5（最低） | 系统默认值 | count 默认 5 |

### 8.3 Slot 合并规则（6 条）

```python
# memory/merger.py
def merge(current: dict, patch: dict, source: str, confidence: float) -> dict:
    """
    6 条合并规则（优先级从高到低）:
    1. 纠正强制覆盖: 检测到"不是X，是Y" → 强制覆盖，无视来源
    2. DB ID 保护: db_resolver 设的 ID 不被 llm_extract 覆盖
    3. 来源优先级: 高来源覆盖低来源
    4. 置信度比较: 同来源时高置信度覆盖低
    5. 空值写入: 旧空新非空 → 写入
    6. 同值刷新: 值相同 → 只更新 last_used_at
    """
```

### 8.4 Slot 失效机制（依赖图）

某 slot 变化时，依赖它的 slot 必须失效，避免拿旧上下文做新操作：

```python
# memory/merger.py
DEPENDENCY_INVALIDATION = {
    "company_name":  ["client_id", "project_id"],                   # 公司名变 → 客户ID、项目ID失效
    "client_id":     ["project_id"],                                # 客户变 → 项目失效
    "project_id":    ["question_ids", "article_ids", "keyword_ids"],# 项目变 → 问题/文章失效
    "question_ids":  ["article_ids"],                               # 问题变 → 文章失效
    "platforms":     ["account_ids"],                               # 平台变 → 账号失效
    "category_id":   ["document_ids"],                              # 分类变 → 文档失效
}

def invalidate_dependencies(slots: dict, changed_key: str) -> dict:
    """某 slot 变化时，级联失效依赖 slot。"""
    for dep in DEPENDENCY_INVALIDATION.get(changed_key, []):
        if dep in slots:
            slots.pop(dep, None)  # 失效 = 删除，下轮重新解析
    return slots
```

**示例**：用户说"改用阿里云项目" → `project_id` 变 → `question_ids`、`article_ids` 级联失效 → 系统不会拿旧项目的 question_ids 去生成文章。

### 8.5 Slot 完整生命周期

```
[用户消息]
    │
    ▼
[INTENT_ROUTER] ── 抽取 intent_slots（LLM 从消息抽槽位）
    │
    ▼
[SLOT_CHECK] ── 合并 session_slots + intent_slots + user_facts + preferences
    │           → 检查必填字段
    │           → 缺失则追问，齐全则放行
    │
    ▼
[工具执行] ── 工具返回 slots_patch（如 client_id=123）
    │
    ▼
[AGGREGATE] ── merge(current, slots_patch, source="tool_result")
    │           → 触发依赖失效（如 company_name 变 → 失效 project_id）
    │
    ▼
[PERSIST_MEM] ── 写入三层存储:
    │           1. session_slots → conversation_sessions.slots
    │           2. 稳定事实 → user_agent_facts（如 company、industry）
    │           3. 偏好信号 → user_agent_preferences
    │
    ▼
[下一轮 LOAD_CONTEXT] ── 重新读三层 → 合并成 effective_slots
```

### 8.6 Slot 读取与注入

```python
# nodes/load_context.py
def load_context(state: AgentState) -> AgentState:
    session = session_store.get_or_create(state["user_id"], state["session_id"])
    session_slots = session.slots or {}
    user_facts = fact_store.load_all(state["user_id"])        # 跨会话事实
    preferences = preference_store.load(state["user_id"])

    # 合并成 effective_slots（优先级: session > facts > preferences）
    effective_slots = {
        **preferences,        # 最低
        **user_facts,         # 中
        **session_slots,      # 最高（本轮上下文）
    }

    return {
        **state,
        "history": session_store.get_recent_messages(session.id, limit=8, char_budget=6000),
        "session_slots": session_slots,
        "user_facts": user_facts,
        "preferences": preferences,
        "effective_slots": effective_slots,  # 给 LLM 和 SLOT_CHECK 用
    }
```

`effective_slots` 注入到 LLM 的 system prompt，让 LLM 知道"用户公司是 XX、行业是 XX、当前在操作项目 YY"。

### 8.7 Slot 升级规则（会话 slot → 用户事实）

不是所有会话 slot 都要升级为跨会话事实。判断标准：

| 判断维度 | 升级为 user_fact | 保留为 session_slot |
|---|---|---|
| 稳定性 | 跨会话稳定（公司、行业） | 单会话内变动（本轮选的问题） |
| 来源 | 工具结果确认（create_client 成功） | 用户临时输入 |
| 失效条件 | 显式纠正或删除客户 | 会话结束或依赖失效 |

**自动升级规则**：

| 触发工具 | 升级的 user_fact |
|---|---|
| `create_client` 成功 | `company`、`industry`、`location` |
| `create_project` 成功 | `default_project_id` |
| `start_platform_auth` 成功 | 追加到 `preferred_platforms` |
| 引导流程推进 | `onboarding_stage` |

### 8.8 三层存储设计

```
┌─────────────────────────────────────────────┐
│  Layer 1: 会话短期记忆 (session-scoped)      │
│  表: conversation_sessions + messages        │
│  字段: slots(JSON), summary, history         │
│  生命周期: 90 天 TTL                          │
│  用途: 当前对话上下文、槽位、最近消息         │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  Layer 2: 用户长期事实 (user-scoped, NEW)    │
│  表: user_agent_facts (新建)                 │
│  字段: user_id, fact_key, fact_value,        │
│        fact_type, confidence, source,        │
│        last_used_at, invalidated_at          │
│  示例: company="百盛千鲜", industry="食品",  │
│        preferred_platforms=["baijiahao"...], │
│        onboarding_stage="create_project"     │
│  用途: 跨会话稳定事实，LOAD_CONTEXT 时注入    │
└─────────────────────────────────────────────┘
┌─────────────────────────────────────────────┐
│  Layer 3: 用户偏好 (user-scoped)             │
│  表: user_agent_preferences (复用)           │
│  字段: default_project_id, tone,             │
│        require_confirmation_before_publish   │
│  用途: 行为偏好，非事实                       │
└─────────────────────────────────────────────┘
```

### 8.9 新建迁移：`user_agent_facts` 表

```python
# backend/migrations/versions/0033_create_user_agent_facts.py
"""create user_agent_facts table

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        "user_agent_facts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fact_key", sa.String(64), nullable=False),
        sa.Column("fact_value", sa.JSON, nullable=False),
        sa.Column("fact_type", sa.String(32), nullable=False),  # string/list/number/bool
        sa.Column("confidence", sa.Float, server_default="0.5"),
        sa.Column("source", sa.String(32), nullable=False),     # user_message/tool_result/llm_extract
        sa.Column("last_used_at", sa.DateTime),
        sa.Column("invalidated_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("user_id", "fact_key", name="uq_user_facts"),
    )
    op.create_index("ix_user_facts_user_id", "user_agent_facts", ["user_id"])
    op.create_index("ix_user_facts_key", "user_agent_facts", ["fact_key"])

def downgrade():
    op.drop_table("user_agent_facts")
```

### 8.10 记忆写入流程（PERSIST_MEM 节点）

```python
# nodes/persist_mem.py
def persist_mem(state: AgentState) -> AgentState:
    # 1. 会话级：merge slots_patch 到 session.slots
    merged = memory_merger.merge(
        state["session_slots"], state["slots_patch"],
        source="tool_result", confidence=1.0
    )
    # 触发依赖失效
    for changed_key in state["slots_patch"].keys():
        merged = memory_merger.invalidate_dependencies(merged, changed_key)
    session_store.update_slots(state["session_id"], merged)

    # 2. 用户级：抽取稳定事实，写入 user_agent_facts
    for fact in state.get("facts_patch", []):
        fact_store.upsert(state["user_id"], fact)

    # 3. 摘要：消息超 20 条或 12000 字符时触发
    summary.maybe_update(state["session_id"])

    # 4. 偏好：检测到偏好信号时更新
    preference_store.maybe_update(state["user_id"], state["message"])

    return state
```

### 8.11 事实抽取规则

| fact_key | 抽取来源 | 示例值 |
|---|---|---|
| `company` | create_client 工具结果 | `"百盛千鲜"` |
| `industry` | create_client 工具结果 | `"食品"` |
| `location` | create_client 工具结果 | `"广州"` |
| `preferred_platforms` | start_platform_auth 工具结果 | `["baijiahao", "zhihu"]` |
| `default_project_id` | create_project 工具结果 | `123` |
| `onboarding_stage` | 引导流程当前阶段 | `"create_project"` |
| `tone_preference` | 用户明确表达 | `"professional"` |

### 8.12 与老架构的关键差异

| 老架构 | 新架构 |
|---|---|
| `AgentMemory.merge_slots` + `MemoryMerger.merge` 两套合并 | 统一用 `MemoryMerger.merge` |
| 跨会话事实只能塞进 preference 白名单字段 | 独立 `user_agent_facts` 表，通用 key-value |
| 槽位失效靠 `DEPENDENCY_INVALIDATION` 静态表 | 保留静态表 + 工具 `produces_slots`/`invalidates_slots` 显式声明 |
| 摘要规则与 LLM 各写一份 | 单一 `summary_updater` |
| slot 无 schema，纯 dict 传递 | slot 来源、优先级、合并规则、失效图全部显式化 |

---

## 九、意图识别设计

### 9.1 设计：LLM 主导 + 规则快路径（单模型）

**模型选型**：统一使用项目中已配置的 `deepseek-v4-flash` 模型（一个会消耗 reasoning_tokens 的推理模型别名，详见 `backend/services/ai_generation_service.py` 和 `backend/config.py:727-730`），路由层和回复层共用同一模型，简化部署与配置。

**复用现有 LLM 客户端**：项目无 `llm_client.py`，实际 LLM 客户端是 `AIGenerationService` 单例（`backend/services/ai_generation_service.py:572-576`），通过 `get_ai_service()` 无参工厂获取。智能体路由层和回复层直接复用此单例，不新增 LLM 客户端。

```python
# nodes/intent_router.py
from backend.services.ai_generation_service import get_ai_service  # 复用项目已有的单例

def intent_router(state: AgentState) -> AgentState:
    msg = state["message"]

    # 1. 规则短路（高频、确定性强的意图）
    if quick := rule_shortcut(msg, state):
        return {**state, "intent": quick.intent, "intent_slots": quick.slots,
                "confidence": 1.0}

    # 2. LLM 路由（deepseek-v4-flash，强制 JSON 输出）
    ai_service = get_ai_service()  # 单例，模型名在 __init__ 时从环境变量读取
    result = llm_router.classify(
        ai_service=ai_service,
        message=msg,
        history=state["history"],
        available_intents=INTENT_SCHEMA,
        user_facts=state["user_facts"],
    )
    return {**state, "intent": result.intent,
            "intent_slots": result.slots, "confidence": result.confidence,
            "pending_intents": result.pending_intents}
```

**单模型架构的延迟与成本控制**：
- 路由调用：调用 `ai_service.chat_json(...)`（OpenAI 兼容协议，强制 `response_format={"type":"json_object"}`），限制 `max_tokens=512`（推理模型 reasoning_tokens 占用大，需预留空间），单次路由延迟目标 < 1500ms（含 reasoning_tokens 消耗）
- 回复调用：闲聊意图可复用本次 LLM 上下文直接生成回复，避免二次调用；其他意图工具执行后再调 LLM 生成回复
- 历史消息只传最近 4 轮 + 摘要，不传全文
- **超时与重试**：复用现有 `AIGenerationService` 配置（HTTP 超时 200 秒，`chat_json` 内置最多 3 次重试，间隔 1 秒）
- **Prompt Caching 现状**：项目代码未主动配置 prompt caching，但 DeepSeek API 侧自动启用（响应返回 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`）。路由层 system prompt 固定，天然有利于缓存命中，无需额外代码改动

**注意事项（基于代码现状的修正）**：
1. 现有 `AIGenerationService._chat` 不支持流式输出（payload 无 `stream` 参数）。SSE 流式回复（第十三章）需要扩展 `AIGenerationService` 新增 `chat_json_stream` / `chat_stream` 方法，payload 加 `"stream": true` 并用 `httpx.AsyncClient.stream(...)` 读取 SSE 响应，逐 chunk 解析 `delta.content` 转成 `text_delta` 事件
2. `get_ai_service()` 是无参单例，不支持按模型名取实例。智能体全程用同一个模型实例即可，无需多模型切换

### 9.2 规则短路清单（仅 4 类，避免与 LLM 漂移）

| 规则 | 触发示例 | 路由到 |
|---|---|---|
| 绑定查询 | "我绑了哪些平台" / "绑定的账号" | `query` + `list_user_bindings` |
| 状态查询 | "进度怎么样" / "生成完了吗" | `query` + `get_article_batch_status` / `get_publish_task_status` |
| 确认/取消 | "确认" / "取消" | 对应 `confirm_task` / `cancel_task` |
| 闲聊兜底 | 没有动词的短句 | `chat` |

**规则只识别这 4 类，其他全部交给 LLM**，从源头消除漂移。

### 9.3 LLM Intent Schema

```json
{
  "intent": "generate_articles",
  "description": "用户想生成文章。可能表述：写文章/生成一批文章/给XX项目出N篇内容",
  "required_slots_hint": ["project_id 或 project_hint"],
  "examples": ["帮我给阿里云项目写5篇文章", "生成一批内容"]
}
```

每个 intent 都给 `description + examples + required_slots_hint`，LLM 输出 `{intent, slots, confidence, reasoning, pending_intents}`，强制 JSON。

### 9.4 支持的意图清单

| Intent | 说明 | 路由到 |
|---|---|---|
| `chat` | 闲聊 | `chat_flow` |
| `query` | 查询类（绑定/进度/列表） | `query_flow` |
| `plan_questions` | 生成用户问题 | `plan_questions` |
| `generate_articles` | 生成文章 | `question_gate` 或 `gen_articles_batch`（按槽位分流） |
| `publish` | 发布文章 | `publish_flow` |
| `manage_binding` | 平台账号绑定 | `binding_flow` |
| `manage_client` | 客户管理 | 对应工具 |
| `manage_project` | 项目管理 | 对应工具 |
| `manage_knowledge` | 知识库管理 | 对应工具 |
| `manage_user` | 用户管理（admin） | 对应工具 |
| `unknown` | 无法识别 | `chat_flow` 兜底 |

**注**：Excel 批量导入功能当前阶段不实现，待后续按需补充对应工具与意图。

### 9.5 组合意图处理（拆分多步执行）

用户可能一句话包含多个意图，如"生成5篇文章并发布到百家号"。处理策略：**拆分多步顺序执行**，不识别为单一组合意图。

#### 9.5.1 拆分规则

LLM 路由器输出 `intent` 时，若检测到多个意图，输出 `intent_list`（按依赖顺序排序）：

```python
# 意图依赖顺序（前置意图必须先完成）
INTENT_DEPENDENCY = {
    "plan_questions":      [],                 # 无前置
    "generate_articles":   ["plan_questions"], # 生成文章依赖问题
    "publish":             ["generate_articles"],  # 发布依赖文章
    "manage_binding":      [],                 # 无前置
}

# LLM 路由输出
{
    "intent_list": ["generate_articles", "publish"],
    "primary_intent": "generate_articles",  # 第一个意图
    "pending_intents": ["publish"],          # 后续意图排队
    "slots": {"project_id": 123, "count": 5, "platform": "baijiahao"}
}
```

#### 9.5.2 执行流程

```
用户："生成5篇文章并发布到百家号"
    │
    ▼
INTENT_ROUTER 输出 intent_list = ["generate_articles", "publish"]
    │
    ▼
执行 primary_intent = generate_articles
    │ → 按槽位分流（见 7.2 节）：
    │   - 有 question_ids → QUESTION_GATE → GEN_ARTICLES
    │   - 有 count + project_id → GEN_ARTICLES_BATCH（绕过 GATE，adapter 同步规划）
    │ → 返回 batch_id，文章异步生成中
    │
    ▼
AGGREGATE 检测到 pending_intents = ["publish"]
    │ → 把 publish 意图 + slots 暂存到 session_slots.pending_actions
    │ → 回复用户："已开始生成5篇文章，生成完成后会自动提醒您发布到百家号"
    │
    ▼
WebSocket 监听 batch_completed 事件
    │ → 文章生成完成
    │ → 触发 pending_action: publish
    │ → 反问用户："文章已生成完成，现在发布到百家号吗？"
    │ → 用户确认后执行 publish_articles
```

#### 9.5.3 pending_actions 存储

```python
# 暂存在 session_slots 里
session_slots["pending_actions"] = [
    {
        "intent": "publish",
        "slots": {"platform": "baijiahao", "account_ids": [123]},
        "trigger": "batch_completed",        # 触发条件
        "trigger_payload": {"batch_id": 456}, # 触发参数
        "created_at": "2026-08-03T..."
    }
]
```

#### 9.5.4 设计要点

1. **不识别为组合意图**：避免组合意图膨胀（generate_and_publish、generate_and_bind...），保持意图原子性
2. **顺序执行**：前置意图完成后才触发后续意图
3. **异步衔接**：前置是异步任务时（如生成文章），后续意图等 WebSocket 通知后再触发
4. **用户确认**：后续意图触发前反问用户（"现在发布吗？"），避免误操作
5. **可取消**：用户可随时说"取消后续发布"，清空 pending_actions

---

## 十、异步任务通知（WebSocket，仅在线推送）

### 10.1 设计原则

文章生成、发布都是异步任务（可能几分钟到几十分钟）。用户发起后可能关闭窗口或切换会话。**统一用 WebSocket 推送完成通知**，仅推送给当前在线的会话；用户离线时不持久化通知，pending_actions 同样不持久化，避免引入额外的存储表与重入逻辑。

**离线场景的退化处理**：用户离线时异步任务完成的通知会丢失。用户下次进入会话时若主动询问进度（如"文章生成完了吗"），通过 `query` 意图调用 `get_article_batch_status` 等查询工具获取结果。pending_actions 中的后续意图也需用户主动触发（如"现在发布吧"），系统不再主动反问。

### 10.2 WebSocket 事件类型

| 事件类型 | 触发时机 | 推送内容 | 用户侧表现 |
|---|---|---|---|
| `question_batch_completed` | 问题批次生成完成 | `{batch_id, question_count, questions[]}` | 提示"已生成 N 个问题" |
| `article_batch_completed` | 文章批次生成完成 | `{batch_id, success_count, failed_count, article_ids[]}` | 提示"文章生成完成" + 触发 pending_actions |
| `article_job_failed` | 单篇文章生成失败 | `{job_id, article_id, error_msg}` | 提示"文章 X 生成失败：原因" |
| `publish_task_progress` | 发布任务进度更新 | `{task_id, completed, failed, total}` | 更新发布进度条 |
| `publish_task_completed` | 发布任务完成 | `{task_id, success_count, failed_count}` | 提示"发布完成" |
| `auth_complete` | 平台登录授权完成 | `{task_id, platform, account_id, success}` | 提示"百家号登录成功" |
| `knowledge_parse_done` | 知识库文档解析完成 | `{dataset_id, doc_id, is_ready}` | 提示"资料解析完成，可用于生成" |

### 10.3 推送机制

```python
# services/websocket_manager.py（复用现有）
async def notify_user(user_id: int, event: dict):
    """推送给用户的所有在线会话（多窗口都能收到）。仅在线推送，离线不持久化。"""
    connections = ws_manager.get_user_connections(user_id)
    if not connections:
        return  # 用户离线，直接放弃推送，不持久化
    for connection in connections:
        await connection.send_json(event)

# 异步任务完成后调用
async def on_article_batch_completed(batch_id: int):
    batch = await smart_article_service.get_batch(batch_id)
    await ws_manager.notify_user(batch.user_id, {
        "type": "article_batch_completed",
        "data": {
            "batch_id": batch_id,
            "success_count": batch.success_count,
            "failed_count": batch.failed_count,
            "article_ids": [j.article_id for j in batch.jobs if j.status == "success"],
        }
    })
    # 触发 pending_actions 检查（仅在线用户有效）
    await trigger_pending_actions(batch.user_id, "batch_completed", {"batch_id": batch_id})
```

### 10.4 跨会话处理（仅在线）

- 用户在会话 A 发起任务 → 任务在后台跑
- 用户切换到会话 B（仍在线）→ WebSocket 推送到用户所有连接
- 任务完成时 → 在线的会话收到通知 + 检查 pending_actions
- 用户全部离线 → 通知放弃，pending_actions 不触发；用户下次回来需主动询问进度

### 10.5 pending_actions 触发流程（仅在线）

```python
# nodes/persist_mem.py 或专门的 trigger 节点
async def trigger_pending_actions(user_id: int, event_type: str, payload: dict):
    """异步任务完成后，检查是否有待执行的后续意图（仅推送给在线用户）。"""
    connections = ws_manager.get_user_connections(user_id)
    if not connections:
        return  # 用户离线，不触发 pending_actions

    session = session_store.get_active_session(user_id)
    pending = session.slots.get("pending_actions", [])

    for action in pending:
        if action["trigger"] == event_type and _match_payload(action["trigger_payload"], payload):
            await ws_manager.notify_user(user_id, {
                "type": "pending_action_trigger",
                "data": {
                    "intent": action["intent"],
                    "slots": action["slots"],
                    "message": f"前置任务已完成，现在执行{INTENT_LABEL[action['intent']]}吗？",
                }
            })
            # 用户确认后，前端发一条新 message 触发执行
            # 用户离线则不触发，pending_actions 保留在 session_slots 中，等用户回来主动询问
```

### 10.6 离线用户的退化体验

| 场景 | 在线用户 | 离线用户 |
|---|---|---|
| 文章生成完成 | WebSocket 实时推送 + 反问"现在发布吗？" | 不推送，用户回来后主动问"文章好了吗" → 走 `query` 意图查询 |
| pending_actions 触发 | 自动反问 | 不触发，用户需主动发起后续意图（如"现在发布吧"） |
| 发布任务进度 | 实时进度条 | 不更新，用户回来后查询 `get_publish_task_status` |

**取舍**：牺牲离线场景的自动化体验，换取架构简化（不引入 `pending_actions` 表和 `agent_notifications` 表）。后续若离线场景痛点突出，可再升级为持久化方案。

---

## 十一、附件处理

### 11.1 上传流程（先上传拿 path）

用户在对话中上传知识库文档时，分两步：

```
步骤1: 前端先调 /api/upload 上传文件，拿到 file_path
    │ POST /api/upload (multipart)
    │ 返回 {file_path: "/static/uploads/xxx.pdf", filename: "公司介绍.pdf"}
    │
步骤2: 前端把 file_path 放到 message 的 attachments 里发给智能体
    │ POST /api/agent-v2/message
    │ body: {
    │   "message": "上传这份资料到知识库",
    │   "attachments": [
    │     {"type": "file", "path": "/static/uploads/xxx.pdf", "filename": "公司介绍.pdf"}
    │   ]
    │ }
    │
步骤3: 智能体识别附件意图，调用 upload_knowledge_files 工具
    │ → 工具内部把 path 转成 bytes，调 KnowledgeIngestionService.upload_files
```

### 11.2 附件数据结构

```python
class Attachment(TypedDict):
    type: Literal["file", "image"]  # file=文档, image=图片
    path: str                       # /static/uploads/xxx.pdf
    filename: str                   # 原始文件名
    size: Optional[int]             # 字节大小
    content_type: Optional[str]     # MIME 类型
```

### 11.3 附件意图识别

| 用户消息 | 识别意图 | 处理 |
|---|---|---|
| "上传这份资料到知识库" + 附件 | `manage_knowledge` + `upload_knowledge_files` | 调工具上传 |
| "解析这份公司资料" + 附件 | `manage_knowledge` + `upload_knowledge_files`(profile_ingest) | 上传 + 抽取客户信息 |
| "加到知识库" + 附件 | `manage_knowledge` + `upload_knowledge_files`(knowledge_ingest) | 仅上传，不抽取 |
| 纯附件无文字 | `manage_knowledge` + 反问"要上传到哪个客户的知识库？" | SLOT_CHECK 追问 client_id |

### 11.4 多附件处理

用户一次上传多个文件：
- 前端循环调 /api/upload 拿多个 path
- attachments 列表带多个 file
- 智能体一次调 upload_knowledge_files(files=[...]) 批量上传

---

## 十二、Action 按钮机制

### 12.1 Action 类型定义

```python
# actions.py
class Action(TypedDict):
    type: str          # Action 类型
    label: str         # 按钮文案
    payload: dict      # 按钮数据
    interaction: Literal["frontend_direct", "via_agent"]  # 交互方式

# Action 类型清单
ACTION_TYPES = {
    # ===== 只读操作：前端直连 REST API，不走智能体 =====
    "preview_article": {"interaction": "frontend_direct", "desc": "打开文章预览弹窗", "api": "GET /api/geo/{id}"},
    "open_browser_auth": {"interaction": "frontend_direct", "desc": "打开浏览器登录窗口", "api": "POST /api/account/{task_id}/auth"},
    "view_batch_progress": {"interaction": "frontend_direct", "desc": "打开批次进度面板", "api": "GET /api/smart-article/batch/{id}"},
    "navigate_to_client": {"interaction": "frontend_direct", "desc": "跳转客户管理页", "api": "前端路由"},
    "navigate_to_project": {"interaction": "frontend_direct", "desc": "跳转项目管理页", "api": "前端路由"},
    "navigate_to_article": {"interaction": "frontend_direct", "desc": "跳转文章管理页", "api": "前端路由"},
    # ===== 写操作：发 message 给智能体，便于记录上下文和槽位 =====
    "upload_knowledge": {"interaction": "via_agent", "desc": "打开文件上传弹窗，上传后发 message"},
    "select_questions": {"interaction": "via_agent", "desc": "打开问题多选弹窗，选中后回填 session_slots"},
    "select_project": {"interaction": "via_agent", "desc": "打开项目选择弹窗（多候选时），选中后回填"},
    "select_client": {"interaction": "via_agent", "desc": "打开客户选择弹窗（多候选时），选中后回填"},
    "plan_questions": {"interaction": "via_agent", "desc": "触发问题生成"},
    "generate_articles": {"interaction": "via_agent", "desc": "触发文章生成"},
    "publish_article": {"interaction": "via_agent", "desc": "触发发布流程"},
}
```

### 12.2 Action 出现场景

| 场景 | Action Type | 说明 |
|---|---|---|
| 用户说"查看 XXX 文章" | `preview_article` + `publish_article` | 预览（前端直连）+ 发布（走智能体） |
| 用户说"绑定百家号" | `open_browser_auth` | 前端直连拉起浏览器登录 |
| 引导上传知识库 | `upload_knowledge` | 走智能体（需绑定 client_id） |
| 引导选问题生成文章 | `select_questions` | 走智能体（多选回填 session_slots） |
| 项目名模糊匹配到多个 | `select_project` | 走智能体（用户选择回填 project_id） |
| 客户名模糊匹配到多个 | `select_client` | 走智能体（用户选择回填 client_id） |
| 查询生成进度 | `view_batch_progress` | 前端直连 REST API |
| 引导建项目 | `navigate_to_project` | 前端路由跳转 |

### 12.3 交互方式设计原则

| 维度 | 前端直连（frontend_direct） | 走智能体（via_agent） |
|---|---|---|
| 适用操作 | 只读：预览、跳转、查看进度、浏览器登录 | 写操作：生成、发布、删除、选择 |
| 调用方式 | 前端直接调 REST API | 前端发一条 message 给 `/api/agent-v2/message` |
| 上下文记录 | 不记录到对话历史 | 记录到对话历史，槽位回填到 session_slots |
| 智能体介入 | 否 | 是 |
| 示例 | `preview_article` 点击 → `GET /api/geo/{id}` | `select_project` 选中 → 发 message "用项目 123" → 智能体识别意图后回填 project_id |

**关键**：只读操作前端直连减少智能体调用成本；写操作走智能体保证可追溯性和槽位累积。

---

## 十三、API 设计（SSE 流式）

### 13.1 新增 API 端点

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/agent-v2/message` | POST (SSE) | 智能体对话主入口，**返回 Server-Sent Events 流** |
| `/api/agent-v2/sessions` | GET | 会话列表 |
| `/api/agent-v2/sessions/{session_id}` | GET | 会话详情 |
| `/api/agent-v2/sessions/{session_id}` | DELETE | 删除会话 |
| `/api/agent-v2/sessions/{session_id}/messages` | GET | 会话消息历史 |
| `/api/agent-v2/preferences` | GET | 获取用户偏好 |
| `/api/agent-v2/preferences` | PUT | 更新用户偏好 |
| `/api/agent-v2/facts` | GET | 获取用户事实（admin 可查任意用户） |

### 13.2 请求 Schema

```python
# 请求（普通 JSON body，响应是 SSE 流）
class AgentMessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    attachments: list[dict] = []
```

### 13.3 SSE 事件类型

`/api/agent-v2/message` 响应 `Content-Type: text/event-stream`，按顺序推送以下事件：

| 事件 | 时机 | data 内容 | 说明 |
|---|---|---|---|
| `intent` | 意图识别完成 | `{intent, slots, confidence, pending_intents}` | 前端可显示"正在执行 XXX" |
| `slot_check` | 槽位检查完成 | `{slots_ok, missing_slots, resolved_slots}` | 槽位缺失时前端可高亮追问 |
| `tool_start` | 工具开始执行 | `{tool_name, params}` | 前端显示工具执行中状态 |
| `tool_end` | 工具执行完成 | `{tool_name, result, actions}` | 前端渲染 Action 按钮 |
| `text_delta` | LLM 回复生成中（流式分片） | `{delta: "..."}` | 打字机效果，逐字累加 |
| `async_task_started` | 异步任务已启动 | `{task_type, task_id, query_tool}` | 提示"任务已提交，可继续其他操作" |
| `clarification` | 需要用户补充信息 | `{reply, missing_slots, actions}` | 引导式追问 |
| `error` | 执行异常 | `{code, message}` | 错误提示 |
| `done` | 本轮响应结束 | `{status, session_id, slots_patch}` | 关闭 SSE 流 |

### 13.4 SSE 事件流示例

```
用户："给阿里云项目生成5篇文章"

event: intent
data: {"intent":"generate_articles","slots":{"project_hint":"阿里云","count":5},"confidence":0.92,"pending_intents":[]}

event: slot_check
data: {"slots_ok":true,"resolved_slots":{"project_id":123,"count":5},"missing_slots":[]}

event: tool_start
data: {"tool_name":"generate_articles_batch","params":{"project_id":123,"count":5}}

event: text_delta
data: {"delta":"已"}

event: text_delta
data: {"delta":"开始"}

event: text_delta
data: {"delta":"生成5篇文章"}

event: tool_end
data: {"tool_name":"generate_articles_batch","result":{"question_batch_id":789,"article_batch_id":456,"planned_count":5,"question_ids":[101,102,103,104,105]},"actions":[{"type":"view_batch_progress","label":"查看生成进度","payload":{"batch_id":456},"interaction":"frontend_direct"}]}

event: async_task_started
data: {"task_type":"article_batch","task_id":456,"query_tool":"get_article_batch_status"}

event: done
data: {"status":"running","session_id":"sess_xxx","slots_patch":{"project_id":123,"article_batch_id":456,"question_batch_id":789}}
```

### 13.5 异步任务的后续通知

SSE 流在 `async_task_started` + `done` 后关闭。后续异步任务进度通过 WebSocket 推送（详见第十章）：

```
WebSocket 事件（独立通道，不在 SSE 流里）：
{
  "type": "article_batch_completed",
  "data": {"batch_id": 456, "success_count": 5, "failed_count": 0, "article_ids": [...]}
}
```

### 13.6 SSE 实现要点

#### 后端实现

- 后端用 FastAPI 的 `StreamingResponse` + `text/event-stream`
- 每个事件按 `event: xxx\ndata: {...}\n\n` 格式输出
- **LLM 回复流式输出需扩展 `AIGenerationService`**：现有 `_chat` 方法不支持流式（payload 无 `stream` 参数），需新增 `chat_stream` 方法，payload 加 `"stream": true`，用 `httpx.AsyncClient.stream("POST", ...)` 读取 SSE 响应，逐 chunk 解析 `delta.content` 转成 `text_delta` 事件
- 工具执行同步阻塞时，先发 `tool_start`，工具返回后发 `tool_end`
- 异步任务（如文章生成）工具立即返回 `batch_id`，发 `async_task_started` 后结束流
- **`generate_articles_batch` 工具的特殊处理**：该工具内部 `plan_batch_sync` 会阻塞 10-60 秒等待 LLM 规划完成，期间 SSE 流需保持打开，每隔 5 秒发一个 `progress` 心跳事件（`{"stage":"planning_questions","elapsed_sec":15}`），防止前端超时断开

#### 前端实现（基于现有架构）

**技术选型：`fetch` + `ReadableStream`（不用 `EventSource`）**

理由：
1. 现有 JWT 认证用 `Authorization: Bearer <token>` 请求头，`EventSource` 不支持自定义请求头
2. `fetch` + `ReadableStream` 可设任意头，与现有 axios 拦截器的 JWT 注入逻辑一致
3. Electron 42 的 Chromium 原生支持 `fetch` 流式读取，无需改动主进程 / preload / IPC
4. 与现有 WebSocket 架构对称（都在渲染进程处理实时通信）

**新增文件**：

| 文件 | 作用 |
|---|---|
| `frontend/src/services/sse/index.ts` | SSE 客户端服务（单例，参考 `services/websocket/index.ts` 结构），用 `fetch` + `ReadableStream` + `AbortController` 实现 |
| `frontend/src/composables/useSSE.ts` | SSE composable，参考 `useWebSocket.ts`，提供 `sendMessage(message, attachments)` 和事件订阅器 |

**SSE 客户端核心实现**：

```typescript
// frontend/src/services/sse/index.ts（伪代码）
class SSEClient {
  private controller: AbortController | null = null

  async sendMessage(url: string, body: any, token: string, handlers: SSEHandlers): Promise<void> {
    this.controller = new AbortController()
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,  // JWT 头，EventSource 做不到
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal: this.controller.signal,
    })

    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    if (!response.body) throw new Error('No response body')

    // 用 ReadableStream 手动解析 text/event-stream
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // 按 \n\n 分割事件
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const eventStr of events) {
        this.dispatchEvent(eventStr, handlers)
      }
    }
  }

  private dispatchEvent(eventStr: string, handlers: SSEHandlers) {
    const lines = eventStr.split('\n')
    let eventType = ''
    let data = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) eventType = line.slice(7)
      else if (line.startsWith('data: ')) data += line.slice(6)
    }
    const parsed = JSON.parse(data)
    switch (eventType) {
      case 'intent': handlers.onIntent?.(parsed); break
      case 'slot_check': handlers.onSlotCheck?.(parsed); break
      case 'tool_start': handlers.onToolStart?.(parsed); break
      case 'tool_end': handlers.onToolEnd?.(parsed); break
      case 'text_delta': handlers.onTextDelta?.(parsed.delta); break  // 打字机效果
      case 'async_task_started': handlers.onAsyncTask?.(parsed); break
      case 'clarification': handlers.onClarification?.(parsed); break
      case 'error': handlers.onError?.(parsed); break
      case 'done': handlers.onDone?.(parsed); break
      case 'progress': handlers.onProgress?.(parsed); break  // 心跳/阶段进度
    }
  }

  cancel() { this.controller?.abort() }
}
```

**与现有架构的集成**：
- **不复用 axios 实例**：axios 的响应拦截器（返回 `response.data`）和 `timeout: 300000` 会破坏流式读取，SSE 客户端独立实现
- **URL 协商复用现有逻辑**：参考 `services/api/index.ts:24-34` 的 `isElectronApp` + `isLocalhostUrl` 模式构造 SSE 端点 URL
- **Vite 代理无需改动**：`/api` 代理已支持 SSE 透传（基于 http-proxy，默认不缓冲响应），开发环境 `proxyTimeout: 600000`（10 分钟）够用
- **Electron 主进程无需改动**：SSE 在渲染进程直接处理，不通过 IPC 桥接（避免过度设计）
- **与 WebSocket 共存**：SSE 负责 LLM token 流 + 工具执行中间状态，WebSocket（已完整接入）负责异步任务完成通知 + pending_actions 触发，职责清晰不冲突

---

## 十四、迁移策略

### 14.1 并存期策略

```
阶段 1（开发期）:
  - 新建 agent_v2/ 目录，不动 agent/ 老目录
  - 新增 /api/agent-v2/* 端点
  - 老 /api/agent/* 保留

阶段 2（灰度期）:
  - 前端增加切换开关，部分用户走 v2
  - 监控 v2 错误率和用户反馈

阶段 3（切换期）:
  - 前端默认走 v2
  - 老 /api/agent/* 标记 deprecated

阶段 4（下线期）:
  - 删除 agent/ 老目录
  - 删除 /api/agent/* 端点
  - 清理相关测试
```

### 14.2 数据迁移

1. **新建 `user_agent_facts` 表**（迁移 0033）
2. **从 `UserAgentPreference` 迁移历史偏好**到 `user_agent_facts`（可选，保持兼容）
3. **会话数据兼容**：`conversation_sessions` / `conversation_messages` 表结构不变，v2 直接复用

### 14.3 老目录清理清单

迁移完成后删除：
- `backend/services/agent/orchestrator.py`
- `backend/services/agent/intent_recognizer.py`
- `backend/services/agent/task_executor.py`
- `backend/services/agent/task_planner.py`
- `backend/services/agent/tool_loop.py`
- `backend/services/agent/tool_registry.py`
- `backend/services/agent/tool_registry_v2.py`
- `backend/services/agent/contracts/`
- `backend/services/agent/execution/`
- `backend/services/agent/intent_recognition/`
- `backend/services/agent/OPTIMIZATION_PLAN.md`
- `backend/services/agent/TOOL_REGISTRY_V2_MIGRATION.md`

保留并迁入 `agent_v2/`：
- `tool_*.py` 的业务逻辑（重写为 adapters）
- `agent_memory.py` 的会话存储逻辑（重写为 `memory/session_store.py`）
- `memory_merger.py` 的合并逻辑（迁入 `memory/merger.py`）
- `summary_updater.py` 的摘要逻辑（迁入 `memory/summary.py`）

---

## 十五、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| LangGraph 学习成本 | 开发效率 | 先写最小 demo 跑通"问题→文章"链路验证可行性 |
| smart_article 服务异步任务 | 工具返回时文章可能未生成完 | 工具返回 `batch_id` + 进度查询工具 + WebSocket 推送 |
| 浏览器登录是阻塞操作 | 用户体验 | `start_platform_auth` 立即返回 `task_id`，前端轮询 + WebSocket 通知 |
| 知识库解析异步 | 生成文章时知识库可能未就绪 | `check_knowledge_ready` 工具 + Gate 提示（不阻断，仅警告） |
| 老目录删除影响 | 现有功能可能依赖 | 并存期充分测试，灰度切换，最后才删 |
| LLM 路由准确率 | 意图识别错误 | 规则短路高频场景 + LLM 兜底 + 用户反馈循环 |
| 引导流程被打断 | 用户体验 | 引导状态持久化到 `user_agent_facts`，跨会话可恢复 |
| 单模型架构延迟 | 路由+回复串行调用导致响应慢 | prompt caching（API 侧自动启用）+ 闲聊意图复用 LLM 上下文 + 强制 JSON 限制 max_tokens=512 |
| 离线用户通知丢失 | pending_actions 不触发 | 离线场景退化：用户回来主动询问进度，走 query 意图查询 |
| SSE 连接超时 | 长任务期间连接断开 | 异步任务立即返回 task_id 后关闭 SSE，后续走 WebSocket 推送 |
| `list_questions` 混入历史问题 | `generate_articles_batch` 拿不到精确的本批次 question_ids | adapter 层直接查 ORM `SmartArticleQuestion.generation_batch_id == batch.id`，绕过 `list_questions`；同时 Phase 2 扩展 `list_questions` 支持 `generation_batch_id` 过滤参数 |
| LLM 客户端不支持流式 | 现有 `AIGenerationService._chat` 无 `stream` 参数，SSE 打字机效果无法实现 | Phase 1 扩展 `AIGenerationService` 新增 `chat_stream` 方法，payload 加 `"stream": true`，用 `httpx.AsyncClient.stream(...)` 读取 SSE 响应 |
| `generate_articles_batch` 工具阻塞时间长 | `plan_batch_sync` 内部 `await run_smart_question_batch` 阻塞 10-60 秒 | SSE 流保持打开，每隔 5 秒发 `progress` 心跳事件防止前端超时；工具执行期间前端显示"正在规划问题..."中间状态 |
| `AIGenerationService` 超时 200 秒 | LLM 规划或回复生成超时 | 复用现有 3 次重试机制；工具层捕获 `RuntimeError` 转成 `error` SSE 事件，提示用户重试 |
| `asyncio.create_task` 任务丢失 | 进程重启时未完成的文章生成任务丢失 | 复用现有 `SmartArticleBatch` 表的 `status` 字段，进程重启后通过扫描 `status="generating"` 的批次恢复任务（现有 `smart_article` 模块已实现此机制） |

---

## 十六、实施计划

### Phase 1：基础设施
- 新建 `agent_v2/` 目录骨架
- 实现 `state.py` + `graph.py` 最小图
- 实现迁移 0033 建 `user_agent_facts` 表
- 实现 `memory/session_store.py` + `memory/fact_store.py`
- **扩展 `AIGenerationService` 新增 `chat_stream` 方法**（支持 SSE 流式输出，payload 加 `"stream": true`）
- 写最小 demo 跑通 LOAD_CONTEXT → INTENT_ROUTER → CHAT → RESPOND

### Phase 2：核心工具
- 实现 `adapters/` 层（smart_article / question_pool / knowledge / publish / account / client / project）
- **扩展 `SmartArticleQuestionPoolService.list_questions` 支持 `generation_batch_id` 过滤参数**
- **实现 `QuestionPoolAdapter.plan_batch_sync` + `generate_articles_sync`**（adapter 层同步封装，绕过 BackgroundTasks）
- 实现工具：client / project / question / article 模块
- 实现 QUESTION_GATE 节点 + 防跳步验证（含 `gen_articles_batch` 双路径分流）

### Phase 3：完整工具
- 实现工具：knowledge / account / publish / user / system 模块
- 实现 Action 按钮机制（含 `interaction` 字段区分前端直连/走智能体）
- 实现意图识别（rule_shortcut + llm_router，单模型 deepseek-v4-flash）

### Phase 4：引导流程
- 实现 CHECK_ONBOARDING 节点
- 实现引导流程各阶段 + `onboarding_completed` 标记逻辑
- 实现引导状态持久化

### Phase 5：API 与测试
- 实现 `/api/agent-v2/*` 端点（SSE 流式，`StreamingResponse` + `text/event-stream`）
- **前端新增 `services/sse/index.ts` + `composables/useSSE.ts`**（用 `fetch` + `ReadableStream`，不用 `EventSource`，支持 JWT 头）
- 实现异步任务 WebSocket 推送（仅在线，复用现有 `ws_manager`）
- 写单元测试（每个节点 + 每个工具）
- 写集成测试（完整引导流程）
- 写 e2e 测试（防跳步验证 + 双路径分流验证 + SSE 流式接收验证）

### Phase 6：灰度与下线
- 前端切换开关 + SSE 事件流前端解析
- 灰度发布
- 监控
- 老目录清理

---

## 十七、验收标准

### 17.1 功能验收

- [ ] 用户说"我绑了哪些平台" → 返回已绑定平台列表
- [ ] 用户说"根据 XXX 项目生成 5 篇文章" → 自动生成 5 个问题 + 5 篇文章（不确认，走 `gen_articles_batch` 路径）
- [ ] 用户说"把这5个问题生成文章" → 走 `question_gate` → `gen_articles` 路径，校验问题有效性
- [ ] 用户说"查看 XXX 文章" → 返回文章内容 + 预览按钮（前端直连 REST API）
- [ ] 用户说"把 XXX 文章发布到百家号" → 触发发布流程
- [ ] 新用户首次进入 → 自动引导建客户 → 传知识库 → 建项目 → ... → 标记 `onboarding_completed=true`
- [ ] 已完成引导的用户新建客户 B → 不再触发引导，仅给"是否上传知识库"轻提示
- [ ] LLM 试图直接调 `generate_articles_from_questions` 但无 `question_ids` → 被 Gate 拦截
- [ ] 用户说"建客户"但只提供了公司名 → 系统追问"请提供行业、所在地、官网"（带示例）
- [ ] 用户跨轮补充槽位 → 系统不重问已填项，只问剩余缺失项
- [ ] 用户说"看阿里云的文章"匹配到多个项目 → 系统返回选择按钮让用户选
- [ ] 老用户公司名已在 user_facts → 建客户时系统问"是否使用之前的公司【XX】？"
- [ ] 用户点击 `preview_article` 按钮 → 前端直接调 REST API，不发 message 给智能体
- [ ] 用户点击 `select_project` 按钮 → 前端发 message 给智能体，槽位回填到 session_slots
- [ ] SSE 流式响应：用户能看到打字机效果 + 工具执行中间状态
- [ ] 异步任务完成时在线用户收到 WebSocket 通知 + pending_actions 反问

### 17.2 架构验收

- [ ] `orchestrator.py` 不超过 300 行（老版本 1271 行）
- [ ] 意图识别只有一套实现（无漂移）
- [ ] 记忆合并只有一套实现
- [ ] 槽位契约只在 Tool 上声明（单一来源）
- [ ] 所有工具通过 adapters 调用底层服务（无直接耦合）
- [ ] LLM 路由与回复共用同一 `deepseek-v4-flash` 模型（单模型架构）
- [ ] 文章生成双路径分流：`question_ids` 走 GATE，`count` 走 batch

### 17.3 性能验收

- [ ] 单次对话响应时间 < 3 秒（不含异步任务）
- [ ] LLM 路由调用延迟 < 1500ms（含 reasoning_tokens 消耗，与第九章 9.1 节目标一致）
- [ ] LLM 路由准确率 > 90%
- [ ] 防跳步拦截率 100%（含 `gen_articles_batch` 路径的 Tool 自检兜底）
- [ ] SSE 首 token 延迟 < 500ms（用户感知响应快）

---

## 附录 A：支持的平台清单

| 平台 ID | 名称 | 支持发布 |
|---|---|---|
| zhihu | 知乎 | 是 |
| baijiahao | 百家号 | 是 |
| sohu | 搜狐号 | 是 |
| toutiao | 头条号 | 是 |
| xiaohongshu | 小红书 | 是 |
| douyin | 抖音 | 是 |
| kuaishou | 快手 | 是 |
| weibo | 微博 | 是 |
| bilibili | B站专栏 | 是 |
| weixin | 微信公众号 | 是 |
| jianshu | 简书 | 是 |
| juejin | 掘金 | 是 |
| penguin | 企鹅号 | 是 |
| csdn | CSDN | 是 |
| wangyi | 网易号 | 是 |
| cnblogs | 博客园 | 是 |
| douban | 豆瓣 | 是 |
| tieba | 百度贴吧 | 是 |

## 附录 B：关键文件引用

| 模块 | 关键文件 |
|---|---|
| smart_article 服务 | `backend/services/smart_article/service.py` |
| 问题池服务 | `backend/services/smart_article/question_pool_service.py` |
| 知识库入库 | `backend/services/knowledge_ingestion_service.py` |
| RAGFlow 客户端 | `backend/services/ragflow_client.py` |
| Playwright 管理器 | `backend/services/playwright_mgr.py` |
| 自动发布服务 | `backend/services/auto_publish_task_service.py` |
| 客户 API | `backend/api/client.py` |
| 项目 API | `backend/api/keywords.py` |
| 账号 API | `backend/api/account.py` |
| 发布 API | `backend/api/publish.py`、`backend/api/auto_publish.py` |
| 知识库 API | `backend/api/knowledge.py` |
| 数据模型 | `backend/database/models.py` |
