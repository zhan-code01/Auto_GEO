# 历史会话展示与记忆隔离 · 后端实现（阶段 1）

> 对应方案：[`../session-history-display-and-isolation.md`](../session-history-display-and-isolation.md) §7 阶段 1
> 交付形态：**补丁集 + 应用器**，应用前你的源码原封不动（已验证）。

---

## 0. 一句话说明

本目录把方案 §7 阶段 1（后端）的全部改动做成**可预检、可回滚、自动适配换行符**的应用器
[`apply_patches.py`](apply_patches.py)。运行 `--check` 即可确认所有改动点都能精确命中，
真正应用只需去掉 `--check`。**应用之前，项目源代码不会被修改**（已用反向 grep 验证）。

---

## 1. 对方案的评估结论：同意后端路线，但有 3 处修正

方案的后端技术判断扎实，**我同意阶段 1 的路线**：复用两张表不新建表、加 `title` 列、
展示层默认不返回 `slots` 只返回派生 `execution_plan`、同步 `fix_database`、软归档不硬删除。

核对源码后，相对方案原文有 **3 处修正**（已在补丁中落实）：

| # | 方案原文 | 实际情况 | 补丁中的处理 |
|---|---|---|---|
| 1 | §3.4 说改 `agent/orchestrator.py` 的 `AgentOrchestrator.handle_web_message` | 方案路径其实**是对的**：`conversation_orchestrator.py` 只是 wrapper，真正实现确实在 `agent/orchestrator.py` 的 `AgentOrchestrator` | 在 `handle_web_message` 的 `add_message(user)` 之后写 `title`（补丁 3b） |
| 2 | §4.2 说 `execution_plan` 由 `TaskPlanner`「纯函数现算」 | `TaskPlanner.build_plan` 的 `missing_slots` 是**入参**，planner 自己不算（见 `schemas.py` 注释）。纯靠它算出的 `missing_slots` 恒为空，`executable` 会误判为 `true` | 新增 `AgentOrchestrator.derive_execution_plan`，**复用**既有的 `_resolve_business_slots` / `_missing_slots_and_questions` 现算真实缺失槽位（补丁 3c + 5b）。这比方案原文更准 |
| 3 | §4.4 DTO 放 `schemas.py` | `SessionListItem` / `SessionDetail` 放 `schemas.py` 没问题 | 照办（补丁 4）。`task_planner.py` 因此**无需改动** |

> 注：修正 2 让详情接口每次现算时会查库解析业务槽位（纯读、无副作用），开销可接受，
> 且 `execution_plan` 反映的是「当前真实状态」而非静态默认值。

---

## 2. 改动清单（5 个文件 / 10 处）

| 文件 | 改动 | 补丁 id |
|---|---|---|
| `backend/database/models.py` | `ConversationSession` 增加 `title` 列 | `1-models-title` |
| `backend/scripts/fix_database.py` | `check_and_fix_database` 补 `conversation_sessions.title` 列检查（项目铁律） | `2-fixdb-title` |
| `backend/services/agent/orchestrator.py` | 导入 `ConversationSession` | `3a-orch-import` |
| `backend/services/agent/orchestrator.py` | 首条用户消息截断写 `session.title` | `3b-orch-title` |
| `backend/services/agent/orchestrator.py` | 新增 `derive_execution_plan`（展示用，复用业务解析） | `3c-orch-plan` |
| `backend/services/agent/schemas.py` | 新增 `SessionListItem` / `SessionDetail` DTO | `4-schemas-dto` |
| `backend/api/conversation.py` | 详情接口加 `include_slots` 开关 | `5a-conv-detail-param` |
| `backend/api/conversation.py` | 详情返回 `execution_plan` + `title`，`slots` 按开关 | `5b-conv-detail-body` |
| `backend/api/conversation.py` | 列表返回 `title`/`last_message` 预览，默认排除 `archived`，去 `slots` | `5c-conv-list` |
| `backend/api/conversation.py` | 新增 `POST /sessions/{id}/archive` | `5d-conv-archive` |

全部为**追加或参数化**改动，不破坏现有 `/message`、飞书、发布链路。

---

## 3. 如何应用

> 应用前你的源码不会被改动。可以先 `--check` 预检，再决定是否应用。

### 3.1 推荐：用应用器（自动适配 CRLF/LF，幂等）

```powershell
# 在项目根目录 d:\GEO\Auto_GEO-main 下

# 1) 预检：确认 10 处锚点全部命中（不写任何文件）
python docs/agent-conversation-integration/implementation/apply_patches.py --check

# 2) 应用
python docs/agent-conversation-integration/implementation/apply_patches.py

# 3) 回滚（如需，方案 §9）
python docs/agent-conversation-integration/implementation/apply_patches.py --reverse
```

> 为什么不用 `git apply`：5 个目标文件换行符不统一（`orchestrator.py` 是 CRLF，其余 LF），
> 标准 `.patch` 很容易因行尾不匹配而失败。应用器在「归一化(LF)空间」匹配、按原文件换行符
> 写回，彻底绕开该问题，且已应用项会自动跳过、可重复运行。

### 3.2 应用后必做：重启后端

`title` 列由 `fix_database.check_and_fix_database()` 在启动时自动补加（补丁 2）。所以：

```powershell
# 重启后端；首次启动日志应出现：✓ conversation_sessions.title 列添加成功
```

也可先手动验证列已加（见 §4.1）。

### 3.3 备选：标准 `.patch`（git 用户）

`patches/` 下提供了 5 个标准 unified diff（由 `gen_patches.py` 基于当前源码生成）。
如需使用：

```powershell
git apply --whitespace=fix docs/agent-conversation-integration/implementation/patches/0001-models-title-column.patch
# …依次 0002 ~ 0005（注意 orchestrator.py 是 CRLF，建议加 --whitespace=fix）
```

> 仍推荐用 §3.1 的应用器，更省心。

---

## 4. 验收（方案 §7 阶段 1 验收点）

> 接口验收需要一个登录 token（替换 `<TOKEN>`）。schema 检查无需 token。

### 4.1 数据库：`title` 列已加

```powershell
python docs/agent-conversation-integration/implementation/verify_schema.py
# 期望：conversation_sessions.title 列存在
```

或手动：

```powershell
python -c "import sqlite3;c=sqlite3.connect('backend/database/auto_geo_v3.db');print([r[1] for r in c.execute('PRAGMA table_info(conversation_sessions)')])"
```

### 4.2 首条消息后 `title` 被填充

```powershell
# 发一条消息（首次会创建会话）
$body = '{"message":"帮我写一篇关于智慧物流的文章","session_id":null}'
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/conversation/message `
  -Headers @{Authorization='Bearer <TOKEN>'} -ContentType 'application/json' -Body $body

# 列表里应能看到 title（取首条消息前 24 字）
Invoke-RestMethod -Uri 'http://localhost:8000/api/conversation/sessions?limit=5' `
  -Headers @{Authorization='Bearer <TOKEN>'}
```

### 4.3 列表精简：有 `title`/`last_message`，**无 `slots`**

```powershell
Invoke-RestMethod -Uri 'http://localhost:8000/api/conversation/sessions?limit=5' `
  -Headers @{Authorization='Bearer <TOKEN>'}
# 期望 items[] 含 id/title/status/current_intent/last_message/last_message_role/updated_at
# 期望 items[] 不含 slots
```

### 4.4 详情：默认无 `slots`、有 `execution_plan`；`include_slots=true` 有 `slots`

```powershell
$sid='<上一步拿到的会话 id>'

# 默认：无 slots，有 execution_plan
Invoke-RestMethod -Uri "http://localhost:8000/api/conversation/sessions/$sid" `
  -Headers @{Authorization='Bearer <TOKEN>'}

# 调试用：含原始 slots
Invoke-RestMethod -Uri "http://localhost:8000/api/conversation/sessions/$sid`?include_slots=true" `
  -Headers @{Authorization='Bearer <TOKEN>'}
```

### 4.5 归档：软归档后从默认列表消失

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/conversation/sessions/$sid/archive" `
  -Headers @{Authorization='Bearer <TOKEN>'}
# 期望 { data: { id, status: 'archived' } }；之后 GET /sessions 默认不再返回它
# 显式查归档：GET /sessions?status=archived
```

### 4.6 回归

- `POST /message` 正常（title 不影响主流程）。
- `POST /sessions/{id}/confirm`、`/cancel` 正常。
- 飞书 / 发布链路无异常（本补丁未触碰）。

---

## 5. 隔离原则（方案 §5，落地保证）

| 层 | 保证 |
|---|---|
| 展示隔离 | 列表/详情默认不返回 `slots`，只返回 `messages` + 派生 `execution_plan` |
| 读写隔离 | 归档只改 `status`，不动 `slots`/`messages`；不提供删单条消息（保护 LLM 上下文） |
| 用户/会话隔离 | 所有接口按 `system_user_id == current_user.id` 过滤（既有能力，未改动） |

---

## 6. 回滚

```powershell
python docs/agent-conversation-integration/implementation/apply_patches.py --reverse
```

回滚后 5 个文件恢复原状。`title` 列保留为空列也无副作用（或手动 `ALTER TABLE` 删除）。

---

## 7. 文件清单

```
implementation/
├── README.md              # 本文件
├── apply_patches.py       # 主应用器（--check / 应用 / --reverse，适配 CRLF/LF）
├── verify_schema.py       # 验收：检查 conversation_sessions.title 列
├── gen_patches.py         # 基于当前源码生成标准 .patch（只读，不改源码）
└── patches/               # 标准 unified diff（备选）
    ├── 0001-models-title-column.patch
    ├── 0002-fix-database-title-column.patch
    ├── 0003-orchestrator-title-and-display-plan.patch
    ├── 0004-schemas-display-dto.patch
    └── 0005-conversation-api-display-isolation.patch
```

> 前端阶段（方案 §7 阶段 2）属业务逻辑改动，受项目「前端只改样式」约束，**不在本交付内**，
> 需另行放行。
