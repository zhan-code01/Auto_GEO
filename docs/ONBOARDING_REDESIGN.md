# AutoGEO 智能体引导程序重设计（V2 状态机 + 常驻进度）

> 状态：进行中（P1–P4 ✅；P5 废弃 V1 已标记 deprecation ✅；P6 验收测试已编写并运行 ✅）
> 背景：当前线上引导卡片由 V2 的 LLM 自由生成，不稳定；经核查，V1 的 `onboarding.py`/`orchestrator.py`/`flow.py` **并非死代码**——仍被上线的 `/api/conversation/message`（V1 对话路径，含 Excel 导入管线）加载并调用。因此 P5 的结论是**标记废弃（deprecation），而非删除**。
> 决策（2026-08-07）：完全摈弃 V1 智能体，引导与中途流程引导统一搬上 `agent_v2`；采用**样式 C**（聊天顶部常驻进度条 + 对话内推下一步卡片）。
> 关键发现（2026-08-10）：前端 AgentChat.vue **早已实现每一步对应的弹窗/选择 modal**，action 类型已在 `actions.py` 注册。因此引导的“骨架”现成，本方案只需新增“算下一步该给哪些 action + 持久化进度”，前端照现有机制渲染即可。

---

## 1. 核心原则

1. **引导 = 确定性状态机**，不是 LLM 自由发挥。每步“该推什么、显示哪些按钮”由代码按**数据库实况**算出，可测、可控。
2. **职责分离**（稳定性关键）：LLM 只负责理解话术 + 执行工具；代码负责算下一步 + 生成按钮 + 持久化进度。
3. **可打断、可跳步**：用户跑去聊别的也不影响引导；下一轮仍按 DB 实况重算。
4. **复用已有字段与组件**：
   - 进度字段：`UserAgentFact.onboarding_completed`（必需 6 步全完成置 True）。
   - 跳过字段：`UserAgentPreference.onboarding_dismissed`（注意：在 preference 表，不在 fact 表）。
   - 按钮渲染：复用已注册的 action 类型（`show_client_form` / `show_project_form` / `upload_files` / `generate_questions` / `generate_articles` / `show_add_account` / `show_article_list`），前端 `onAction` 已能渲染这些类型对应的弹窗。
5. **步骤对齐真实模块**：每个引导步骤对应前端一个真实、菜单可见、仍在使用的功能模块（已下线模块如「关键词蒸馏」不纳入）。

## 2. 引导流程（用户视角的全链路）

欢迎语（丰富，写清完整工作流 + 新建客户所需字段）→ 首屏卡片仅 `[新建用户]` `[跳过引导]`。
点 `[新建用户]` → 弹窗填字段自动保存（或对话框手动输入）→ 回复中说明下一步所需参数 → 卡片 `[上传资料(可选)]` `[新建项目]`。
- 上传资料为可选增强：用户不点也继续，之后不再出现，不阻塞流程。
- 选 `[新建项目]` → 弹窗填字段保存（或对话框回复）。
- 后续按“规划问题 → 生成文章 → 绑定账号 → 去发布”逐步推进；每步按钮带 payload 直连工具。

**必需 6 步（进度条 x/6，决定完成判定）**：

| # | 步骤 | 对应前端模块 | 完成判定（DB 实况） | 引导按钮 action |
|---|------|------|------|------|
| 1 | 建客户 | 客户管理 `/clients` | `clients` 有该用户记录 | `show_client_form` |
| 2 | 建项目 | GEO 项目管理 `/clients/projects` | `projects` 有该用户记录 | `show_project_form` |
| 3 | 规划问题（生成问题） | 智能文章生成 步骤01 | `smart_article_questions`（未删除）有该用户记录 | `generate_questions`(默认 count=1) |
| 4 | 生成文章 | 智能文章生成 步骤02 | `geo_articles` 有该用户记录且 `publish_status != 'draft'` | `generate_articles`(默认 count=1) |
| 5 | 绑定发布账号 | 账号管理 `/accounts` | `accounts`（未删除）有该用户记录 | `show_add_account` |
| 6 | 审核发布首篇 | 智能文章生成 步骤03 / 发布 | `geo_articles` 有该用户记录且 `publish_status == 'published'` | `show_article_list`（去发布） |

> 步骤 3/4/6 同属「智能文章生成」模块那条“规划问题 → 生成文章 → 审核发布”工作流轨。
> **上传企业资料为可选增强**：不计入完成判定、不阻塞流程；仅在“客户已建、项目未建”时提示一次。

## 3. 状态机实现（`backend/services/agent_v2/onboarding.py`）

`STEPS` 列表定义每步的 `key / label / action(类型,文案,payload) / deps(前置步)`。
`compute_onboarding_state(db, user_id, is_admin)` 逻辑：

1. `is_admin` → 直接返回不引导。
2. 读 `UserAgentPreference.onboarding_dismissed` → 跳过则不再推卡片。
3. 查 6 步 DB 实况 → `done` 映射。
4. 必需全完成 → `fact_store.set_onboarding_completed(True)`（幂等）。
5. 已完成 → 返回不活跃。
6. 否则算 `next_actions`：**未做完 且 所有前置已满足**的步 → 用 `make_action` 生成（复用已注册类型）。
   - 例：项目已建、问题未建 → 返回 `[生成问题, 绑定发布账号]`（两步前置均满足）；问题已建、文章未建 → `[生成文章, 绑定发布账号]`；文章已建、账号未建 → `[绑定发布账号, 去发布]`。
7. 可选：`client 已建 && project 未建` → `optional_actions=[上传资料(可选)]`。

返回结构：`{active, dismissed, completed, checklist:[{key,label,done}], next_actions:[action], optional_actions:[action], can_skip}`。

## 4. 触发与注入方式（已确定，最简方案）

**不改造 SSE 流**，改为**前端轮询专用接口**（解耦、好测、不与现有 per-tool 建议打架）：

- `GET /api/agent-v2/onboarding` → 返回 `compute_onboarding_state` 结果。
- `POST /api/agent-v2/onboarding/dismiss` → `set_onboarding_dismissed(True)` 写库。
- 前端（P3/P4）在**聊天打开时**及**每轮操作后（点 action / 收助手消息）**调用 `GET /onboarding` 刷新：渲染顶部常驻进度条 + 对话内“下一步”卡片。

> 为什么不用 SSE metadata 注入：原聊天流不携带引导状态（仅 `/facts` 查接口带 `onboarding_*` 字段，且未用于引导渲染）；轮询接口更独立、可控，且天然实现“每轮重算抗跑偏”。

## 5. 三项已确认的产品决策

1. **文章数校验（严格）**：生成文章时若请求的 article 数 > 当前问题数 → 报「操作不合法」。即“1 个问题最多生成 1 篇”。**注意：当前 `generate_articles` 自动模式会自行规划问题再生成、并不拦截**，因此该校验为**新增逻辑（待 P2 实现）**。
2. **引导期内只显示统一卡片**：onboarding 进行中时屏蔽工具自带的“下一步”建议，只展示统一引导卡片，避免重复。
3. **跳过按钮常驻**：欢迎卡有跳过；进入步骤后，顶部进度条也常驻「跳过」，用户随时可退出引导。

## 6. 边界与健壮性

- 用户跑偏聊别的：不强制拉回；下一轮重算照常。
- 老用户（已有数据）→ 6 步判定全完成 → `completed=True` → 不弹。
- 跳过：`dismissed=True` 写库 → 刷新/重启/新开窗口均不弹。
- admin：不引导。
- 进度真相 = DB 实况 + `dismissed` / `completed` 字段，不依赖会话上下文（本地 `MemorySaver` 重启无妨）。

## 7. 实施步骤（roadmap）

| 阶段 | 内容 | 状态 |
|------|------|------|
| P1 后端状态机 | `services/agent_v2/onboarding.py`（`compute_onboarding_state` + `set_onboarding_dismissed`）+ 注入 `GET/POST /api/agent-v2/onboarding` 接口 | ✅ 已完成（2026-08-10） |
| P2 文章数校验 | 在 `generate_articles` 增加“articles ≤ questions”硬校验，超限返回「操作不合法」；引导按钮默认 count=1、手动输入 ≤ 问题数；项目已有问题时基于已有未生成文章的问题生成（不再自规划），0 问题时保留原自动规划 | ✅ 已完成（2026-08-10） |
| P3 前端进度条 | `AgentChat.vue` 顶部常驻进度条，读 `checklist` 渲染 6 步 x/6；`active=false` 时隐藏；常驻「跳过」按钮 | ✅ 已完成（2026-08-10） |
| P4 前端卡片+欢迎语+跳过持久化 | 每轮拉 `GET /onboarding` 渲染 `next_actions/optional_actions` 为卡片；欢迎语面板带完整流程；「跳过」调 `POST /onboarding/dismiss`；引导期内屏蔽工具自带建议（displayActions 返回空）；`generate_questions/generate_articles` 接入 `_DIRECT_TOOL_ROUTING` 直达工具 | ✅ 已完成（2026-08-10） |
| P5 废弃 V1 | 经核查 `onboarding.py`/`flow.py` 仍被上线的 V1 `/api/conversation/message` 路径（orchestrator/prerequisite_gate/tool_project 引用）**实际调用**，属活代码而非死代码。结论改为**标记废弃**：在 `onboarding.py`、`flow.py` 文件头加 `[DEPRECATED]` 注释说明已被 `agent_v2/onboarding.py` 取代，并在 orchestrator/prerequisite_gate/tool_project 的引用处加 `[DEPRECATED]` 行内注释；**不删除**，待 V1 路径整体退役后一并清理 | ✅ 已完成（2026-08-10） |
| P6 测试 | 空用户全流程、可选上传可跳过仍完成、跳步、跑偏、跳过持久化、老用户不弹、admin 不弹、文章数超限报错（`illegal_operation`）| ✅ 已完成（2026-08-10，`tests/unit/test_onboarding_state.py`）|

## 8. 附：为什么这样设计（回应“会不会不稳定”）

市面上成熟产品（Notion / Slack / GitHub / Linear / Stripe 入门清单、空状态引导）几乎都是**确定性清单/状态机**，LLM 最多当“陪聊助手”、不碰控制流。让 LLM 全权决定每一步和按钮，是实验性 demo 的做法，已知会“该推不推、偶尔推错”。本方案把引导逻辑收归代码、LLM 留在擅长处，等于采用被验证过的稳妥形态。且本项目前端弹窗脚手架已存在，落地成本可控。
