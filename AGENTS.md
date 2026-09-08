# Repository Guidelines

## 适用范围与信息源

本文件适用于 `Auto_GEO-main-master/` 仓库内的开发、测试和文档代理。稳定的工程规则写在这里；阶段性目标、指标阈值和方案细节以 `docs/` 中的对应文档为准；实际可执行命令以 `package.json`、`pyproject.toml` 和 `.github/workflows/` 为准。发生冲突时，先核对这些源文件，不要凭记忆猜测命令。

除非任务明确要求，代理不得执行生产部署、真实平台发布、真实 Cookie 操作或真实 AI/外部平台写操作。测试应优先使用 mock、沙箱账号和专用测试数据库。

## 项目结构与模块组织

AutoGeo 是一个前后端一体的自动化平台项目：

- `backend/`：Python FastAPI 后端，包含 API、数据库模型、迁移、Playwright 自动化、静态资源与模板。
- `frontend/`：Vue 3 + Vite + Electron 前端，主要 UI 在 `frontend/src`，桌面端入口在 `frontend/electron`。
- `tests/unit/`、`tests/integration/`：后端 pytest 单元和集成测试，公共 fixture 在 `tests/conftest.py`。
- `frontend/e2e/`：前端 Playwright E2E，依赖后端与种子数据，默认不在主 CI 执行。
- `backend/migrations/versions/`：Alembic 迁移文件；日常迁移命令从 `backend/` 目录执行。
- `deploy/production/`：生产 Docker Compose 部署配置和运行手册。
- `extensions/cookie-sync/`：浏览器 Cookie 同步插件。
- `docs/`：架构、部署、功能方案和实施文档。

`tests/e2e/` 当前没有实际测试文件，不要把它当作现有 E2E 测试入口。

## 开工前 checklist

代码、数据库或运行时行为变更前先过一遍；纯文档、注释或格式变更只执行相关检查：

1. **限定改动范围**：如果任务属于当前 Geo 优化项，阅读 `docs/AutoGEO优化方案_2026-09.md` 对应小节；普通 bug 修复、依赖升级、文档和部署维护不受该方案的阶段顺序限制。
2. **读相关既有实现**：命中本文件列出的实现位置时，先读完整上下文和相关测试，只修改该职责范围。
3. **建立可复现基线**：按“本地开发、检查与测试”章节准备 Python 3.12、Node 20、依赖、环境变量和专用 PostgreSQL 测试库；只运行与改动范围匹配的检查，并记录已有失败。
4. **识别口径与契约面**：改动问题集、判卷 prompt、指标定义、平台门槛或记录字段语义（`measurement_type`/`round_no`/`replicate_no`/`retry_count`/`phase`、引用状态）时，使用版本号或新列承接，禁止静默改口径，并同步数据契约文档。
5. **迁移先库后码**：加列/加表先写带可执行 `downgrade` 的 Alembic 迁移，在一次性 PostgreSQL 测试库验证 upgrade/downgrade，再修改模型和业务代码；禁止在生产库执行 downgrade。
6. **新能力守则**：执行/外呼类新能力一律走配置开关、白名单和确认门；API Key 仅经环境变量，不入代码、提交、异常和日志。
7. **按风险补测试**：按变更类型补单元、集成、前端 E2E、迁移回滚或部署校验，不为无关改动强行凑三层测试。
8. **收尾同步文档**：若实现改变了本文件的目录、命令、数据契约或指针，把对应内容改准；细粒度实现记录留在代码注释和方案文档。

## 当前优化主线（仅适用于相关优化项）

当前阶段的 Geo 优化项遵循版本化方案 **`docs/AutoGEO优化方案_2026-09.md`**。接手相关优化项前先读对应小节，不要仅凭仓库现状扩大改动面。普通 bug 修复、依赖升级、文档维护和部署维护不必套用下面的阶段顺序。

- **执行主线顺序不可颠倒**：引用证据链修复（P0）→ 指标可信度/份额口径（P0）→ 平台接入/权威信源（P1）→ 效果承诺与 Agent 行动层（P2）。
  "第 0 周口径冻结"（问题集/判卷 prompt 版本/指标定义/平台门槛）是后续一切对比的基准，改动即破坏同口径。
- **方案已点名的既有实现位置**（涉及即先读对应小节）：
  - 平台硬编码：`backend/services/geo_evaluation_run_service.py`（`AI_EVALUATION_PLATFORMS`，现 3 平台）→ 注册表化方向。
  - 引用证据链（P0 已实现）：状态契约在 `backend/services/geo_citation.py`，抽取与判卷三态区分见方案 §六.1。动引用/判卷类字段前先读对应小节，勿用 `bool()` 抹平引用状态。
  - Agent 工具**三处同步**：`backend/services/agent_v2/nodes/agent_node.py` 与 `backend/services/agent_v2/nodes/tools_node.py` 各有一份 `_TASK_TYPE_TOOLS` 拷贝，加上 `backend/services/agent_v2/tools/` 的 `@register_tool` 注册表，三处须同步改，**漏一处会静默失效**；新增执行类工具须注册为需 `confirm`，不得开放 Agent 自主发布。
  - **口径版本化**：判卷 prompt（`geo_response_judge_service.py`）与份额指标（`geo_evaluation_analytics_service.py`）任何改动以新版本号生效，旧版本数据按版本号分组对比，禁止静默改口径。
- 竞品/来源分析相关前置调研与差距核查报告可能位于工作区外的同级 `../research/`；它只是可选背景资料，不入库，也不能作为任务执行的必要前置条件。

## 工程红线（跨所有相关优化项）

1. **灰度与回滚**：新能力一律走"配置开关 + 白名单"。
   统一灰度机制为**规划中**（方案 §工程通则）：`AUTOGEO_AGENT_V2_BYPASS_USER_IDS`（白名单）> `AUTOGEO_AGENT_V2_ENABLED`（全局），
   平台启用集 `GEO_EVALUATION_PLATFORMS_ENABLED`（CSV）；运行时以轻量配置表为准（现存通用表 `system_configs`），环境变量仅作初始默认。
   后端代码当前**没有**这些开关的读取逻辑，落地前不得当作现存机制依赖；仓库现存的近似先例是发布审批白名单 `PUBLISH_APPROVAL_BYPASS_USERS`（`backend/config.py`）。
   `deploy/backend/docker-compose.yml` 里的 `AUTOGEO_AGENT_V2_BYPASS_USERS` 与方案变量名不一致且后端未读取，落地时需一并对齐。
    指标以自然日为粒度汇总；平台停用阈值、告警方式和运行时配置以方案及当前实现为准，不要在代理任务中自行发明阈值。
2. **数据迁移**：新表/新列一律 alembic 迁移、**先库后码**；存量行回填默认值（写法参照现行迁移的 `server_default` 模式，如 `0016_client_devices_and_publish_routing.py` 的 `execution_mode='cloud_browser'`；方案中的 `geo_evaluation_records.placement_type` 为规划列，尚未落地）；每个迁移提供可执行 downgrade，发布前在本地验证 up/down 可逆。
3. **安全红线**：服务商 API Key 仅经环境变量管理，不入代码仓库、不写日志；生产强制 PostgreSQL（`alembic upgrade head`）。
4. **测试要求**：遵循下方按变更类型划分的验证矩阵。CI 当前后端执行 Ruff、Ruff format、MyPy 和单元测试；前端主 CI 执行 type-check、build 和按条件启用的 E2E，具体以 `.github/workflows/` 为准。
5. **质量闸门（达标才上线，不强行推进）**：引用证据不可观测 → 不发布 QCR 类对外指标；Judge 校准不达标 → 来源/引用类指标仅展示趋势、不做对外承诺；平台无法稳定采集 → 降级人工采样（Manual）。

## 数据契约要点（易踩坑）

- 测评记录字段语义**不可混用**：`measurement_type`（baseline/recheck/experiment，对比实验语义）、`round_no`（同一 run 内轮次）、`replicate_no`（独立重复）、`retry_count`（失败重试）；`phase` 保留为执行侧阶段标记，两者共存，映射写入数据契约。
- 引用证据状态须在报表区分；内部四态常量以 `geo_citation.py` 为准、勿另写字符串。判卷只对真实采集引用计支撑，勿用 `bool()` 把「未采集/零条/采集异常」抹平（词汇与映射见方案 §六.1 及代码注释）。
- 平台覆盖数 ≠ 注册了执行器：须**同时**满足回答成功率、引用可观测率、解析准确率、人工复核一致性四项门槛才计入。
- `answer_share`（总和=100%）与 `mention_rate`（可 >100%）语义不同，勿沿用旧的单值 `share`（口径错误，只读保留、停止更新）。

## 构建、测试与本地开发命令

### 环境前置条件

- Python 3.12；后端依赖：`pip install -r backend/requirements.txt`。
- Node.js 20；前端依赖：`cd frontend && npm ci`。依赖变更必须同步提交 `frontend/package-lock.json`。
- 从 `.env.example` 创建本地 `.env` 并填写 `DATABASE_URL`、`AUTO_GEO_ENCRYPTION_KEY` 等必需变量。不要把真实 `.env` 提交到仓库。
- 后端测试使用独立 PostgreSQL 数据库，并设置 `TEST_DATABASE_URL` 指向数据库名包含 `test` 的实例；不要用开发库或生产库运行会清理数据的测试。
- 需要浏览器自动化时，按后端依赖安装 Chromium；前端 Playwright 测试还需要后端服务和种子数据。

### 本地开发

```bash
cd frontend && npm run dev
```

启动前端开发环境。

### 前端检查

```bash
cd frontend && npm run build:renderer
cd frontend && npm run type-check
cd frontend && npx eslint .
```

分别构建 Vite 渲染端、执行 Vue/TypeScript 类型检查和只读 ESLint 检查。当前 `npm run lint` 包含 `--fix`，只有明确需要自动修复时才执行。

```bash
cd frontend && npm test
```

运行 `frontend/e2e/` 下的 Playwright 测试；执行前确认后端、测试数据和浏览器环境已准备好。

### 后端检查与测试

CI 等价的后端检查从 `backend/` 目录执行：

```bash
cd backend
ruff check .
ruff format --check .
mypy api/ services/ --ignore-missing-imports
cd ..
pytest tests/unit -v
```

集成测试需在专用 PostgreSQL 测试库和所需服务就绪后单独执行：

```bash
pytest tests/integration -v
```

不要使用没有测试库保护的 `pytest tests` 作为默认命令；它可能包含需要外部服务的测试，且测试 fixture 会主动清理测试数据。

### 数据库迁移

日常 Alembic 操作从 `backend/` 目录执行，迁移文件位于 `backend/migrations/versions/`：

```bash
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

上述回滚与重升仅在一次性测试库执行；生产环境只允许按部署流程备份并执行升级。根目录 `alembic.ini` 是兼容入口，若从仓库根目录执行必须显式使用 `alembic -c alembic.ini ...`。

### 生产部署

生产部署是有外部副作用的操作，只有用户明确要求时才执行。首次部署前必须按 `deploy/production/README.md` 将 `.env.example` 复制为 `.env` 并填写配置，完成密钥、数据库和备份确认，再运行该目录提供的部署脚本或 Compose 命令；不要在普通开发任务中直接执行 `docker compose up -d --build`。

## 代码风格与命名规范

Python 目标版本为 3.12，Ruff 行宽为 120；前端 CI 使用 Node.js 20。API 路由放在 `backend/api`，业务逻辑优先放在 `backend/services`。

前端使用 Vue SFC、TypeScript、Pinia 和 Element Plus。组件使用 PascalCase，变量和函数使用 camelCase。新增样式和交互应贴合现有后台工具风格，避免无关重构。

## 测试规范

后端测试放入 `tests/unit` 或 `tests/integration`，文件命名使用 `test_*.py`；前端 E2E 放入 `frontend/e2e/`。涉及数据库、授权、部署、Playwright 会话的改动应补充针对性测试。外部 AI、平台采集、发布和 Cookie 流程默认使用 mock 或沙箱，不得在测试中操作真实账号。

按变更类型选择验证范围：

- 后端服务/API：相关单元测试、Ruff、format、MyPy；涉及数据库或 HTTP 契约时补集成测试。
- 前端组件/页面：`type-check`、只读 ESLint、渲染构建；关键用户流程补 `frontend/e2e/` 测试。
- 数据库模型/迁移：专用 PostgreSQL 测试库上验证 upgrade、数据回填和 downgrade，不在生产库验证回滚。
- 部署配置：执行 Compose 配置校验、镜像构建或部署 smoke test；涉及真实服务器时必须得到明确授权。

## 提交与 PR 规范

近期提交信息为「类型前缀: 中文描述」，例如 `feat: 引用证据链 P0 收口基线`、`ci: backend pytest 改为仓库根运行`。提交应保持范围清晰、描述直接。

PR 应包含：

- 改动内容与原因。
- 影响模块，例如 `backend/api`、`frontend/src`、`deploy/production`。
- 已执行的命令和结果。
- UI 改动截图。
- 涉及 `.env`、Docker、Nginx、noVNC 或数据库迁移时写明部署注意事项。

## 安全与配置提示

不要提交真实 `.env`、密钥、Cookie、token 或浏览器会话文件；配置示例只更新 `.env.example`。生产环境必须配置 PostgreSQL `DATABASE_URL`、32 字节 `AUTO_GEO_ENCRYPTION_KEY`、JWT 密钥以及相关 API Key，密钥不得出现在代码、提交、异常或日志中。

跨主机传输 Cookie 或 `storage_state` 的授权流程必须使用 HTTPS；本机 localhost 调试不应被当作生产安全保证。不要把带有 token 的 URL、请求头、Cookie 或完整数据库连接串写入日志。

不要手工编辑或提交运行产物和缓存，例如 `frontend/out`、`frontend/dist*`、`logs/`、`playwright-report/`、`.pytest_cache/`、`.ruff_cache/` 和 `.cookies/`，除非任务明确要求更新发布产物。
