# 后台智能体模块（v2）技术架构设计

> 目标：废弃旧的 `backend/services/agent/`（orchestrator / tool_loop / intent_recognizer / agent_memory 那套手写编排），
> 用 **Langgraph** 重新构建一个新模块 `backend/agent/`。
> 核心业务变更：**新链路 = 先生成「用户问题」→ 再基于问题生成文章**；旧的「先蒸馏关键词 → 再生成」链路作废。

---

## 0. 旧模块的问题（为什么要重做）

| 问题 | 说明 |
|---|---|
| 手写编排大脑 | `orchestrator.py` 自己实现 tool-loop、记忆预处理、SOP 闸门，逻辑耦合严重，难以扩展 |
| 意图识别是「正则 + LLM JSON」双路 | `intent_recognizer.py` 大量手写正则（`_extract_platforms` 等），易碎、难维护 |
| 记忆方案非框架原生 | `agent_memory.py` 自己落库，没有 checkpoint / 跨线程长期记忆概念 |
| 闸门是「声明式 + 运行时拦截」 | `prerequisite_gates` 只拦不提示，且 LLM 仍能在 prompt 里看到不该调的 tool |
| **链路已过时** | 仍依赖 `has_keywords`（蒸馏）作为生成前置；而新业务前置应为 **`has_questions`（已生成用户问题）** |
| 有两套未接线的半成品 | `intent_recognition/`、`execution/` 子包只被自己引用，没接进主流程 |

**结论**：不增量改，直接新建 `backend/agent/`，旧目录标记 deprecated 后删除。

---

## 1. 技术选型

| 维度 | 选型 | 说明 |
|---|---|---|
| 图编排 | **Langgraph** (`langgraph`) | StateGraph + PostgresSaver(checkpoint) + PostgresStore(长期记忆) |
| LLM | DeepSeek / OpenAI 兼容 | `ChatOpenAI(base_url=..., api_key=..., model=...)`（沿用现有 `AUTOGEO_CONVERSATION_LLM_*`） |
| 工具定义 | `langchain_core.tools.@tool` | 每个业务 tool 一个函数，带 schema |
| 意图路由 | 轻量 LLM 结构化分类器 | `.with_structured_output(IntentSchema)`，快、便宜、稳定 |
| 工具执行 | Langgraph `create_react_agent` 或自建 ReAct 节点 | 在「已路由的意图分支」内做 tool-calling |
| 短期记忆 | `AsyncPostgresSaver`（线程级 checkpoint） | 对话历史 / 图状态按 `thread_id`（=session）持久化 |
| 长期记忆 | `AsyncPostgresStore`（跨线程） | 用户偏好、跨会话学到的项目事实 |
| 业务工作记忆 | 现有 Postgres 表（复用） | `working_memory` JSON（项目/问题/文章/平台）、`UserAgentPreference` |
| 高风险确认 | Langgraph `interrupt()` + `Command(resume=)` | 发布类操作暂停等用户确认 |

---

## 2. 状态设计（AgentState）

```python
from typing import TypedDict, Annotated, List, Optional
from langchain_core.messages import BaseMessage

class WorkingMemory(TypedDict):
    active_project_id: Optional[int]          # 当前项目
    question_ids: List[int]                    # 已生成的用户问题
    selected_question_ids: List[int]           # 用户选定要写文章的问题
    article_ids: List[int]                     # 已生成文章
    bound_platforms: List[str]                 # 已绑定平台（来自 Account 表）
    current_stage: str                         # onboarding→questions→article→publish

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]  # 对话
    user_id: str
    thread_id: str                             # = session_id
    working_memory: WorkingMemory              # 业务工作记忆（也落库）
    current_intent: Optional[str]              # 意图路由结果
    extracted_slots: dict                      # 意图抽取出的实体
    gate_result: Optional[dict]                # 护栏检查结果
    pending_confirmation: Optional[dict]       # 待确认的高风险操作
    next_actions: List[dict]                   # 给前端的动作按钮
```

> `working_memory` 既存在于图 state（运行时），也异步落库到 `conversation_sessions.slots`，
> 供护栏节点、UI、跨会话恢复读取。

---

## 3. 图结构（Langgraph StateGraph）

```
START
  │
  ▼
load_context ───── 从 PostgresSaver + 业务表载入 working_memory / 历史摘要
  │
  ▼
intent_router ──── 轻量 LLM 分类：query_platforms / generate_questions /
  │                generate_article / publish / manage_account / general_chat
  │
  ├─► [query/manage/chat] ──► tool_executor ──► memory_writer ──► responder ──► END
  │
  ├─► [generate_questions] ─► tool_executor ──► memory_writer ──► responder ──► END
  │
  ├─► [generate_article] ──► guardrail ──┬─ 不通过 ──► responder(引导先生成问题) ──► END
  │                                     └─ 通过 ──► tool_executor ──► memory_writer ──► responder ──► END
  │
  └─► [publish] ──► guardrail ──┬─ 不通过 ──► responder(引导补全前置) ──► END
                                └─ 通过 ──► confirm(interrupt) ──► tool_executor
                                                                      │ (用户确认后 Command(resume))
                                                                      ▼
                                                                memory_writer ──► responder ──► END
```

**关键设计**：`tool_executor` 在调用 LLM 前，会先用 `get_tools_for_state(state)` 做**动态工具裁剪**——
只有当前阶段允许的工具才放进 `tools` 列表（例如 `has_questions=False` 时，根本不把
`generate_article_from_question` 暴露给 LLM）。这是「防提前生成文章」的第一道、也是最强的保证。

---

## 4. 意图识别设计（两阶段）

**第 1 阶段：路由分类（intent_router 节点）**
- 用便宜的 LLM + `with_structured_output(IntentSchema)` 输出：
  ```json
  { "intent": "generate_questions", "slots": { "project_hint": "某客户", "count": 5 } }
  ```
- 固定意图枚举，避免正则：
  `query_platforms` / `generate_questions` / `generate_article` / `publish` /
  `manage_account` / `general_chat` / `knowledge_upload`
- 同时做实体抽取（project_hint / platform / count / question_ids），写入 `extracted_slots`。

**第 2 阶段：工具选择（tool_executor 内的 ReAct）**
- 在已路由分支内，用 `create_react_agent(llm, tools=allowed_tools)` 让 LLM 从**裁剪后的工具子集**里挑并调用。
- 这样不会一次性把 30+ 工具全丢给 LLM，降低误调、省 token。

> 废弃旧的 `intent_recognizer.py` 正则规则，全部改为 LLM 结构化路由；规则只保留极少量「关键词快捷路由」
> （如「我绑了哪些平台」直接命中 `query_platforms`）作为兜底加速。

---

## 5. 模块与工具清单（每个模块的工具）

### 模块 A：平台账号（account）
| 工具 | 类型 | 说明 | 前置 |
|---|---|---|---|
| `list_bound_platforms` | 只读 | 查用户已绑定平台列表（回答「我绑了哪些平台」） | 无 |
| `start_platform_binding(platform)` | 写 | 发起绑定授权 | 无 |
| `check_binding_status(platform)` | 只读 | 查绑定状态 | 无 |
| `unbind_platform(platform)` | 写(高) | 解绑 | 无 |

### 模块 B：项目/客户（project）
| 工具 | 说明 |
|---|---|
| `create_project(name, company, ...)` | 建项目（设 active_project_id） |
| `list_projects()` | 列项目 |
| `get_project(project_id)` | 项目详情 |
| `update_project(...)` | 改项目 |

### 模块 C：用户问题生成（questions）★ 新链路核心
| 工具 | 说明 | 产出 |
|---|---|---|
| `generate_user_questions(project_id, count)` | 基于项目资料，用 `SmartArticleQuestionPlanner` 生成 N 个用户可能提的问题 | `question_ids` |
| `list_user_questions(project_id)` | 列已生成、未使用的问题 | — |
| `select_user_questions(question_ids)` | 用户选定要写文章的问题 | `selected_question_ids` |
| `refine_question(question_id, feedback)` | 按反馈调整某问题 | — |

> 该模块是「文章生成」的**唯一前置**。生成后 `working_memory.has_questions=True`。

### 模块 D：文章生成（article）★ 依赖模块 C
| 工具 | 说明 | 前置（闸门） |
|---|---|---|
| `generate_article_from_question(question_ids, count)` | 基于选中的问题生成文章（调 `SmartArticleService`） | **必须 has_questions + selected_question_ids** |
| `list_articles(project_id)` | 列文章 | 无 |
| `get_article(article_id)` | 文章详情 | 无 |
| `update_article(...)` | 改文章 | 无 |

### 模块 E：发布（publish）★ 依赖 D + 模块 A
| 工具 | 说明 | 前置 |
|---|---|---|
| `prepare_publish(article_id, platforms)` | 质检 + 建发布任务 | has_article + has_bound_platform |
| `confirm_publish(task_id)` | 确认发布（interrupt 暂停） | requires_confirm |
| `cancel_publish(task_id)` | 取消 | 无 |
| `query_publish_status(task_id)` | 查发布进度 | 无 |

### 模块 F：知识库/资料（knowledge）
| 工具 | 说明 |
|---|---|
| `upload_knowledge(project_id, file)` | 上传资料入库（供问题生成检索） |
| `list_knowledge(project_id)` | 列资料 |

### 模块 G：通用查询/闲聊（query/chat）
| 工具 | 说明 |
|---|---|
| `query_task_status(...)` | 查各种任务状态 |
| `general_chat(...)` | 闲聊 / 产品 FAQ |

---

## 6. 记忆设计（两层 + 业务层）

```
┌─ 短期记忆：Langgraph AsyncPostgresSaver（按 thread_id=session）
│     → messages 历史、gate_result、pending_confirmation、当前图状态
│     → 断点续跑、发布确认 interrupt 后恢复都靠它
│
├─ 长期记忆：Langgraph AsyncPostgresStore（跨线程，user_id 维度）
│     → UserAgentPreference：默认项目、默认平台、发布前是否需确认、语气
│     → 学到的项目事实（如「A 客户主营 B 行业」）
│
└─ 业务工作记忆：working_memory（落库 conversation_sessions.slots）
      → active_project_id / question_ids / selected_question_ids /
        article_ids / bound_platforms / current_stage
      → 护栏节点、UI、跨会话恢复都读它
```

- **long-term + short-term = Langgraph 官方推荐组合**（`checkpointer` 管对话，`store` 管跨会话）。
- `working_memory` 是本项目特有的「业务槽」，在 `memory_writer` 节点里同步落库，
  因为它既被图使用，也被 UI / 护栏 / `list_user_questions` 等直接查库的逻辑使用。

---

## 7. 护栏设计：如何防止「还没生成问题就生成文章」★

采用**三道防线**，层层兜底：

1. **工具遮罩（最强、第一道）**
   `get_tools_for_state(state)` 在调用 LLM 前计算可用工具集：
   ```python
   if not working_memory["question_ids"]:
       allowed.remove("generate_article_from_question")  # 根本不暴露给 LLM
   ```
   LLM 看不到这个 tool，自然无法调用。

2. **护栏节点（guardrail，第二道）**
   即使 LLM 绕过遮罩（如 function_call 伪造），`guardrail` 节点在 `tool_executor` 前检查：
   - `generate_article_from_question` 要求 `working_memory.has_questions == True` 且 `selected_question_ids` 非空。
   - 不通过 → 返回 `gate_result`，路由到 `responder` 并引导：「还没生成用户问题，
     先调用 `generate_user_questions` 吧」，同时给出动作按钮。

3. **工具内部断言（第三道，兜底）**
   `generate_article_from_question` handler 第一行再次校验问题存在，
   不存在直接抛 `GuardrailError`，绝不让文章生成器跑起来。

> 同理，`prepare_publish` 用同一套护栏：要求 `has_article` + `has_bound_platform`，
> 回答你提到的「用户绑定平台可查询」——`list_bound_platforms` 是只读工具，护栏读 `working_memory.bound_platforms`。

---

## 8. 高风险操作确认（发布）

- `prepare_publish` 标记 `requires_confirm=True`。
- `guardrail` 通过后进入 `confirm` 节点，调用 `interrupt({"task": ..., "platforms": ...})`
  暂停图，把「确认发布」卡片推给前端。
- 用户点确认 → 前端发 `Command(resume={"confirm": true})` → 图从 checkpoint 恢复，
  执行真正的 `tool_executor` → 建发布任务。
- 这是 Langgraph 原生的「人在回路」机制，比旧模块的 `_confirmed` 参数更可靠。

---

## 9. 与现有代码的对接（复用，不重写）

| 现有资产 | 新模块如何复用 |
|---|---|
| `backend/services/smart_article/question_planner.py` | `generate_user_questions` 直接调用 `SmartArticleQuestionPlanner.plan()` |
| `backend/services/smart_article/service.py` | `generate_article_from_question` 调 `SmartArticleService.process_smart_article_job()` |
| `backend/database/models.py` 的 `Account` | `list_bound_platforms` / publish 护栏直接查 `Account` 表 |
| `backend/services/agent/task_executor.py` | 发布链路执行可复用其 `generate_and_prepare_publish` |
| `SmartArticleQuestion` / `SmartArticleJob` 表 | 问题/文章状态持久化，护栏据此判断 `has_questions` |

---

## 10. 迁移 / 废弃计划

1. 新建 `backend/agent/`（v2），实现上述 StateGraph。
2. 新增 API：`POST /api/agent/v2/message`、`POST /api/agent/v2/confirm`。
3. 旧 `backend/services/agent/` 标记 `# DEPRECATED`，路由切到 v2 后观察一周。
4. 观察期无问题 → 删除旧目录（orchestrator / tool_loop / intent_recognizer / agent_memory /
   memory_* / entity_resolver / missing_slot_checker / slot_catalog / flow / prerequisite_gate / tool_*.py）。
5. 前端对话入口从 `conversation.py` 切到 v2。

---

## 11. 建议目录结构

```
backend/agent/
  __init__.py
  graph.py              # StateGraph 定义、节点装配、compile
  state.py              # AgentState / WorkingMemory
  nodes/
    load_context.py
    intent_router.py    # 轻量 LLM 分类器
    guardrail.py        # 前置闸门 + 工具遮罩逻辑
    tool_executor.py    # ReAct 工具执行（create_react_agent）
    memory_writer.py    # 落库 working_memory / 长期偏好
    responder.py        # 生成回复 + next_actions
    confirm.py          # interrupt 确认节点
  tools/
    account_tools.py
    project_tools.py
    question_tools.py   # ★ 新链路核心
    article_tools.py
    publish_tools.py
    knowledge_tools.py
    query_tools.py
  memory/
    checkpointer.py     # AsyncPostgresSaver
    store.py            # AsyncPostgresStore (长期)
  factory.py            # 单例 graph + 绑定 DB
```
