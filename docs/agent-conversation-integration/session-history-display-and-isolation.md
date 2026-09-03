# AutoGEO 后台 Agent · 历史会话展示与记忆隔离 落地方案

> 版本：v1 · 2026-06-09
> 范围：让用户在聊天界面看到历史会话列表、切换并恢复历史对话；同时把"给用户看的对话历史"与"agent 内部的工作记忆"干净地隔离。
> 关联：`docs/agent-conversation-integration/agent-workflow-gap-analysis.md`（已部分过时，本方案以其已实现的会话持久化为基础）。

---

## 0. 一句话结论

**复用已有的 `conversation_sessions` / `conversation_messages` 两张表，不新建表。** 只需：① 给会话加一个 `title` 字段（列表展示用）；② 把"展示接口"和"agent 记忆"在 API 契约上拆开（展示层只吐 `messages` + 派生展示数据，不吐原始 `slots`）；③ 前端从"纯内存"改为"按 session_id 拉取历史"。隔离的本质是**展示层只读 messages，记忆层（slots）只归 agent**，二者通过 `conversation_id` 关联但互不污染。

---

## 1. 背景与现状

### 1.1 要解决的问题
- 用户在聊天界面看不到过去的会话，刷新页面 / 重开浏览器后历史消失。
- 担心"展示历史"会和"agent 的记忆"耦合，互相干扰。

### 1.2 已经具备的基础（后端，已落地并验证）
| 能力 | 位置 | 状态 |
|---|---|---|
| 会话持久化 | `conversation_sessions`（含 `slots`/`summary`/`status`） | ✅ |
| 消息持久化 | `conversation_messages`（`role`/`content`/`metadata`/`created_at`） | ✅ |
| 会话列表接口 | `GET /api/conversation/sessions` | ✅（本方案将精简其返回） |
| 会话详情接口 | `GET /api/conversation/sessions/{id}` | ✅（本方案将加 `include_slots` 开关） |
| 用户隔离 | 所有接口按 `system_user_id == current_user.id` 过滤 | ✅ |
| LLM 多轮记忆 | `memory.get_context_for_llm`（取最近 8 条 + summary + slots） | ✅ |

### 1.3 前端现状（`frontend/src/views/agent/AgentChat.vue`，需改造）
```ts
const sessionId = ref('')                       // 内存，刷新即丢
const messages  = ref<ChatMessage[]>([welcome]) // 内存，刷新即丢
// sendMessage → conversationApi.sendMessage({message, session_id})
// resetChat    → 清空 sessionId + messages
```
- **没有**会话列表、**没有**历史加载、**没有**刷新恢复。
- 当前是"单一活动会话"模型，不符合"历史会话展示"目标。

> ⚠️ 前端改造属于**业务逻辑改动**，不在项目"前端只改样式"的约束范围内，实施前需单独确认（见 §6.4）。

---

## 2. 推荐方案总览

### 2.1 架构分层
```
┌─────────────────────────── 前端（展示层）───────────────────────────┐
│  会话列表侧边栏              对话区                                  │
│  GET /sessions        ←→   GET /sessions/{id} → messages[]           │
│  (title/状态/预览)          (只渲染 messages + 派生展示：execution_plan)│
└───────────────────────────────┬─────────────────────────────────────┘
                                │ 只读 messages / 派生字段
                                │ 永不直接读写 slots
┌───────────────────────────────▼─────────────────────────────────────┐
│                        后端 API 契约层                                │
│  展示契约：title / status / messages / execution_plan / next_questions│
│  内部契约：slots（仅 include_slots=true 或 agent 内部使用）            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌─────────────────────────── 数据层（已存在）──────────────────────────┐
│  conversation_sessions        conversation_messages                  │
│   ├── title      (新增)        ├── role                              │
│   ├── status     (含 archived) ├── content                           │
│   ├── slots      (记忆·agent)  ├── metadata                          │
│   └── summary    (记忆·agent)  └── created_at                        │
│   ← 记忆层（agent 读写）        ← 历史层（append-only，展示+LLM上下文） │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 三条核心决策
1. **不新建表**：`conversation_sessions` + `conversation_messages` 已足够，避免引入同步成本。
2. **加 `title` 列**：会话列表必须有可读标题，首条用户消息兜底生成。
3. **展示契约与记忆字段在 API 层拆分**：前端永远拿不到原始 `slots`，只能拿到从 `slots` 派生的"展示字段"（`execution_plan` / `missing_slots` / `next_questions`）。

---

## 3. 数据层设计

### 3.1 复用现有两张表（不新建）
- `conversation_messages`：对话历史，append-only。
- `conversation_sessions`：会话元信息 + agent 记忆（`slots`/`summary`）。

### 3.2 `conversation_sessions` 增加 `title` 字段
```python
# backend/database/models.py → class ConversationSession
title = Column(String(120), nullable=True, comment="会话标题，用于列表展示")
```
- 可空（兼容历史会话，列表展示时用首条消息兜底）。
- 最长 120 字符。

### 3.3 同步 `backend/scripts/fix_database.py`（项目铁律）
> 加列必须同步 fix_database，否则线上 SQLite 表会缺列、查询 500。
> 参见记忆 `db-model-migration-rule`。

在 `check_and_fix_database()` 的列检查列表中追加（针对 `conversation_sessions` 表）：
```python
# conversation_sessions 表加列
cursor.execute("PRAGMA table_info(conversation_sessions)")
conv_cols = [c[1] for c in cursor.fetchall()]
conv_columns_to_check = [
    ("title", "VARCHAR(120)"),
]
for col_name, col_def in conv_columns_to_check:
    if col_name not in conv_cols:
        cursor.execute(
            f"ALTER TABLE conversation_sessions ADD COLUMN {col_name} {col_def}"
        )
        conn.commit()
        logger.success(f"✓ conversation_sessions.{col_name} 列添加成功")
```

### 3.4 `title` 生成策略（首版：规则，零 LLM 成本）
在 `AgentOrchestrator.handle_web_message` 收到用户消息后，若 `session.title` 为空，则用首条用户消息截断生成：
```python
# orchestrator.py，在 memory.add_message(user) 之后
if not session.title:
    title_raw = request.message.strip().replace("\n", " ")
    title = (title_raw[:24] + "…") if len(title_raw) > 24 else title_raw
    session.title = title or "新对话"
    db.commit()
```
- 优点：简单、确定、无额外调用。
- 后续可选增强（阶段 3）：任务完成时让 LLM 把标题改写成更友好的语义（如"小爱科技·智慧物流→知乎"），但**非首版必需**。

### 3.5 软归档，不做硬删除
- 新增会话状态 `archived`（归档，列表默认不显示，但数据保留，agent 仍可读）。
- **不做"删除单条消息"**：会破坏 `get_context_for_llm` 的上下文连续性，得不偿失。
- 归档接口：`POST /api/conversation/sessions/{id}/archive`（见 §4.3）。

---

## 4. 接口层契约（展示 vs 内部）

### 4.1 会话列表 `GET /api/conversation/sessions`（精简，不含 slots）
**请求**：`?status=active&limit=20&offset=0`（默认排除 `archived`）
**响应**：
```jsonc
{
  "success": true,
  "data": {
    "total": 12,
    "items": [
      {
        "id": "web_1_a1b2c3...",
        "title": "帮我写一篇关于智慧物流的文章…",
        "status": "waiting_user",          // active/waiting_user/confirm_required/completed/...
        "current_intent": "generate_and_publish",
        "last_message": "已开始为项目「小爱科技」生成…",  // 最后一条消息预览
        "last_message_role": "assistant",
        "updated_at": "2026-06-09T21:30:00"
      }
    ]
  }
}
```
- `last_message` 由后端子查询取该会话最新一条 `conversation_messages` 的前 N 字。
- **不含 `slots`**。

### 4.2 会话详情 `GET /api/conversation/sessions/{id}`（默认精简，可开启 slots）
**请求**：`?include_slots=false`（默认 false）
**响应（默认，展示用）**：
```jsonc
{
  "success": true,
  "data": {
    "session": {
      "id": "web_1_a1b2c3...",
      "title": "帮我写一篇关于智慧物流的文章…",
      "status": "waiting_user",
      "current_intent": "generate_and_publish",
      "execution_plan": {                  // 从 slots 派生的展示字段
        "intent": "generate_and_publish",
        "steps": ["resolve_project", "resolve_accounts", ...],
        "executable": false,
        "requires_confirmation": true,
        "missing_slots": ["account"]
      },
      "created_at": "...", "updated_at": "..."
      // 注意：没有原始 slots
    },
    "messages": [
      {"id": 1, "role": "user", "content": "...", "metadata": {}, "created_at": "..."},
      {"id": 2, "role": "assistant", "content": "...", "metadata": {...}, "created_at": "..."}
    ]
  }
}
```
**响应（`include_slots=true`，管理/调试用）**：在 `session` 下额外返回 `slots` 原始 JSON。

> `execution_plan` 由 `TaskPlanner` 基于当前 `slots` 现算（纯函数，无副作用），既是展示数据又不泄露内部 ID（`account_ids`/`project_id` 不直接暴露，只暴露 `missing_slots` 这种语义）。

### 4.3 归档 `POST /api/conversation/sessions/{id}/archive`
```jsonc
// 请求：无 body
// 响应：
{ "success": true, "data": { "id": "...", "status": "archived" } }
```
- 仅将会话 `status` 置为 `archived`，不删数据。
- 归档后该会话不出现在默认列表；用户仍可通过直接进入会话 ID 查看（或后续做"已归档"视图）。

### 4.4 展示 DTO（建议显式定义，避免字段散落）
```python
# backend/services/agent/schemas.py 新增
class SessionListItem(BaseModel):
    id: str
    title: Optional[str]
    status: str
    current_intent: Optional[str]
    last_message: Optional[str]
    last_message_role: Optional[str]
    updated_at: Optional[str]

class SessionDetail(BaseModel):
    id: str
    title: Optional[str]
    status: str
    current_intent: Optional[str]
    execution_plan: Optional[Dict[str, Any]]
    slots: Optional[Dict[str, Any]] = None   # 仅 include_slots=True 时填充
    created_at: Optional[str]
    updated_at: Optional[str]
```

---

## 5. 隔离原则（三层）

| 层 | 含义 | 本方案如何保证 |
|---|---|---|
| **展示隔离** | 用户看到的是"对话内容"，不是 agent 的内部任务状态 | 展示接口默认不返回 `slots`，只返回 `messages` + 派生的 `execution_plan` |
| **读写隔离** | 用户操作历史（切换/归档）不破坏 agent 任务；agent 更新 `slots` 不污染对话原文 | `messages` 与 `slots` 是同会话下不同字段；归档只改 `status`，不动 `slots`/`messages`；删单条消息**不做** |
| **用户/会话隔离** | 不同用户、不同会话互不串数据 | 所有接口按 `system_user_id == current_user.id` 过滤（已具备）|

> 关键认知：**隔离不是"把数据存到两个地方"，而是"对同一份会话数据，展示层和记忆层只各取所需"。** `conversation_messages` 同时服务于"前端展示"和"LLM 上下文"，这是合理的复用，不是耦合——因为它是 append-only 的事实，谁读都不会改它。真正的"可变状态"只有 `slots`，而它只归 agent 写。

---

## 6. 前端交互设计

### 6.1 布局（左侧会话列表 + 右侧对话区）
```
┌──────────────┬───────────────────────────────────┐
│ + 新对话      │  AutoGEO 智能体                    │
│              │  ─────────────────────────────────│
│ ▸ 智慧物流…   │  [消息列表，来自 GET /sessions/{id}]│
│   知乎发布…   │                                    │
│   查进度…     │                                    │
│              │  ─────────────────────────────────│
│ (已归档)      │  [输入框]                  [发送]  │
└──────────────┴───────────────────────────────────┘
```

### 6.2 数据流
1. **进入页面**：`GET /sessions` → 渲染侧边栏；若无会话，自动新建一个（`sessionId=''` 发首条消息时后端创建）。
2. **点击会话**：`GET /sessions/{id}` → 用返回的 `messages` 替换右侧消息区；`sessionId` 切到该 id。
3. **发消息**：`POST /message` 带 `session_id` → 把回复 append 到右侧 + 刷新侧边栏该项的 `last_message`/`updated_at`。
4. **新对话**：清空右侧、`sessionId=''`、首条消息后端创建新会话并返回新 id。
5. **归档**：`POST /sessions/{id}/archive` → 从侧边栏移除（默认视图）。

### 6.3 刷新恢复
- `sessionId` 持久化到 `localStorage`（或 URL query `?s=xxx`）。
- 页面加载：若 `localStorage` 有 `sessionId`，`GET /sessions/{id}` 恢复；否则进新对话。
- 这一步把当前"刷新即丢"彻底解决。

### 6.4 ⚠️ 前端属逻辑改动，需确认
当前项目约束"前端只改样式不改逻辑"（记忆 `frontend-styling-only-no-logic`）。本节涉及的状态管理、接口调用、路由全部是**逻辑改动**。**实施前需你明确放行**，或单独作为一个前端任务处理。后端阶段（§7 阶段 1）不依赖前端，可先行。

---

## 7. 落地步骤（分阶段 + 验收）

### 阶段 1：后端（低风险，可立即实施，无需动前端）
| # | 改动 | 文件 |
|---|---|---|
| 1.1 | `ConversationSession` 加 `title` 字段 | `backend/database/models.py` |
| 1.2 | fix_database 同步加列（铁律） | `backend/scripts/fix_database.py` |
| 1.3 | 首条用户消息生成 title | `backend/services/agent/orchestrator.py` |
| 1.4 | `GET /sessions` 返回精简 + `last_message` 预览 | `backend/api/conversation.py` |
| 1.5 | `GET /sessions/{id}` 加 `include_slots` + 返回 `execution_plan` | `backend/api/conversation.py` |
| 1.6 | 新增 `POST /sessions/{id}/archive` | `backend/api/conversation.py` |
| 1.7 | 新增展示 DTO | `backend/services/agent/schemas.py` |

**验收**：
- `curl GET /sessions` 返回带 `title`/`last_message` 的列表，无 `slots`。
- `curl GET /sessions/{id}` 默认无 `slots`、有 `execution_plan`；`?include_slots=true` 有 `slots`。
- `curl POST /sessions/{id}/archive` 后该会话不再出现在默认列表。
- 首条消息后 `conversation_sessions.title` 被填充。
- 现有 `/message`、飞书、发布链路回归无异常。

### 阶段 2：前端（需放行逻辑改动）
| # | 改动 | 文件 |
|---|---|---|
| 2.1 | 新增会话列表侧边栏组件 | `AgentChat.vue` 或拆子组件 |
| 2.2 | 会话切换 / 新建 / 归档交互 | `AgentChat.vue` |
| 2.3 | `sessionId` 持久化 + 刷新恢复 | `AgentChat.vue` + `localStorage` |
| 2.4 | API 封装补 `listSessions`/`getSession`/`archiveSession` | `frontend/src/services/api/index.ts` |

**验收**：刷新页面历史不丢；切换会话能恢复各自消息；归档后从列表消失。

### 阶段 3：可选增强（非必需）
- LLM 在任务完成时把 `title` 改写成语义化标题。
- 会话搜索（按 title/content）。
- "已归档"视图与恢复。

---

## 8. 改动文件清单（阶段 1 后端）

```
backend/database/models.py                       # ConversationSession + title
backend/scripts/fix_database.py                  # 同步 title 列（铁律）
backend/services/agent/orchestrator.py           # 首条消息写 title
backend/services/agent/schemas.py                # SessionListItem / SessionDetail DTO
backend/api/conversation.py                      # 列表精简 / 详情 include_slots / 归档
```
> 均为**追加或参数化**改动，不破坏现有 `/message` 与飞书/发布链路。

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 / 回滚 |
|---|---|---|
| 忘记同步 `fix_database.py` 加 `title` 列 | 线上查询 `title` 报 500 | 严格按 §3.3 同步；启动后用 `PRAGMA table_info` 验证 |
| 详情接口默认不返回 `slots` 破坏现有调用 | 当前无前端调用该接口，风险低 | 提供 `include_slots=true` 兜底；灰度观察 |
| 前端改造影响现有单会话体验 | 切换/刷新逻辑 bug | 保留"无 sessionId 即新建"兼容；前端独立验收 |
| `last_message` 子查询性能 | 会话多时列表慢 | 首版可接受（SQLite 单用户场景）；后续可加 `last_message_at` 冗余列 |

回滚：阶段 1 全部为追加式改动，回滚 = revert 这几个文件 + 删 `title` 列（或保留空列无副作用）。

---

## 10. 为什么不选其他方案

- **方案 B：新建一张"展示用历史表"** —— 否决。会和 `conversation_messages` 双写，引入一致性 bug，收益为零（messages 本就是 append-only 的事实，展示层直接读即可）。
- **方案 C：把 slots 也存一份给前端** —— 否决。这恰恰是用户担心的"耦合"，且 `slots` 含 `account_ids` 等内部 ID，暴露给前端既无必要也有泄露风险。
- **方案 D：用 LLM 给每个会话实时生成标题** —— 首版否决。增加延迟和成本，规则截断已满足列表可读性；列为阶段 3 可选增强。

---

## 11. 一句话交付

后端阶段 1（§7）是低风险纯追加改动，**我可以立即实施并跑通验收**；前端阶段 2 属逻辑改动，**需要你明确放行**后我再做。要我现在开始阶段 1 吗？
