# Repository Guidelines

## 项目结构与模块组织

AutoGeo 是一个前后端一体的自动化平台项目：

- `backend/`：Python FastAPI 后端，包含 API、数据库模型、迁移、Playwright 自动化、静态资源与模板。
- `frontend/`：Vue 3 + Vite + Electron 前端，主要 UI 在 `frontend/src`，桌面端入口在 `frontend/electron`。
- `tests/`：测试目录，包含 `unit/`、`integration/`、`e2e/`，公共 fixture 在 `tests/conftest.py`。
- `deploy/production/`：生产 Docker Compose 部署配置。
- `extensions/cookie-sync/`：浏览器 Cookie 同步插件。
- `docs/`：架构、部署、功能方案和实施文档。

## 当前开发主线（2026-09 起）

本阶段（2026 Q4）全部开发遵循方案 **`docs/AutoGEO优化方案_2026-09.md`**（已入库版本化）。
接手任一优化项前先通读该方案对应小节——**不要仅凭仓库现状自行扩大改动面**。

- **执行主线顺序不可颠倒**：引用证据链修复（P0）→ 指标可信度/份额口径（P0）→ 平台接入/权威信源（P1）→ 效果承诺与 Agent 行动层（P2）。
  "第 0 周口径冻结"（问题集/判卷 prompt 版本/指标定义/平台门槛）是后续一切对比的基准，改动即破坏同口径。
- **方案已点名的既有实现位置**（涉及即先读对应小节）：
  - 平台硬编码：`backend/services/geo_evaluation_run_service.py`（`AI_EVALUATION_PLATFORMS`，现 3 平台）→ 注册表化方向。
  - 引用证据链断裂：`backend/workers/geo_evaluation_worker.py`（`citations` 固定 `[]`）——引用须在 Electron 执行器内抽取，后端只承接状态区分/关联/脱敏。
  - Agent 工具**双清单**：`backend/services/agent_v2/nodes/agent_node.py` 的 `_TASK_TYPE_TOOLS` 与 `backend/services/agent_v2/tools/` 的注册表须同步改，**漏一处会静默失效**；新增执行类工具须注册为需 `confirm`，不得开放 Agent 自主发布。
  - **口径版本化**：判卷 prompt（`geo_response_judge_service.py`）与份额指标（`geo_evaluation_analytics_service.py`）任何改动以新版本号生效，旧版本数据按版本号分组对比，禁止静默改口径。
- 竞品/来源分析相关前置调研与差距核查报告在工作区 `research/` 目录（仓库外的同级 `../research/`，由原 `Geo/` 改名而来），作为背景资料，不入库。

## 工程红线（跨所有优化项，来自方案 §〇.5）

1. **灰度与回滚**：新能力一律走"配置开关 + 白名单"。
   环境变量优先级：`AUTOGEO_AGENT_V2_BYPASS_USER_IDS`（白名单）> `AUTOGEO_AGENT_V2_ENABLED`（全局）；
   平台启用集 `GEO_EVALUATION_PLATFORMS_ENABLED`（CSV）。运行时以轻量配置表为准，环境变量仅作初始默认。
   指标以自然日为粒度汇总；单平台风控连续 2 次超阈值、成功率连续 2 次过低即自动停用并飞书告警，无需重启服务。
2. **数据迁移**：新表/新列一律 alembic 迁移、**先库后码**；存量行回填默认值（如 `placement_type='organic'`）；每个迁移提供可执行 downgrade，发布前在本地验证 up/down 可逆。
3. **安全红线**：服务商 API Key 仅经环境变量管理，不入代码仓库、不写日志；生产强制 PostgreSQL（`alembic upgrade head`）。
4. **测试要求**：每项优化至少 单元（服务层）/集成（API 端到端）/回归（发布链路不受影响）三层用例；后端 `ruff + pytest`、前端 `type-check + lint` 纳入 CI（沿用现有 GitHub Actions）。
5. **质量闸门（达标才上线，不强行推进）**：引用证据不可观测 → 不发布 QCR 类对外指标；Judge 校准不达标 → 来源/引用类指标仅展示趋势、不做对外承诺；平台无法稳定采集 → 降级人工采样（Manual）。

## 数据契约要点（易踩坑）

- 测评记录字段语义**不可混用**：`measurement_type`（baseline/recheck/experiment，对比实验语义）、`round_no`（同一 run 内轮次）、`replicate_no`（独立重复）、`retry_count`（失败重试）；`phase` 保留为执行侧阶段标记，两者共存，映射写入数据契约。
- 引用三态须在报表区分：平台无引用能力=`null`；抓取成功但零条=`[]`；抓取异常=`unavailable`。
- 平台覆盖数 ≠ 注册了执行器：须**同时**满足回答成功率、引用可观测率、解析准确率、人工复核一致性四项门槛才计入。
- `answer_share`（总和=100%）与 `mention_rate`（可 >100%）语义不同，勿沿用旧的单值 `share`（口径错误，只读保留、停止更新）。

## 构建、测试与本地开发命令

常用命令如下：

```bash
cd frontend && npm run dev
```
启动前端开发环境。

```bash
cd frontend && npm run build:renderer
cd frontend && npm run type-check
cd frontend && npm run lint
```
分别用于构建 Vite 渲染端、检查 Vue/TypeScript 类型、执行 ESLint 自动修复。

```bash
cd frontend && npm test
```
运行前端 Playwright 测试。

```bash
pytest tests
ruff check backend tests
```
在仓库根目录运行后端测试与 Python lint。

```bash
cd deploy/production && docker compose --env-file .env -f docker-compose.yml up -d --build
```
构建并启动生产 Docker 服务。

## 代码风格与命名规范

Python 目标版本为 3.12，Ruff 行宽为 120。API 路由放在 `backend/api`，业务逻辑优先放在 `backend/services`。

前端使用 Vue SFC、TypeScript、Pinia 和 Element Plus。组件使用 PascalCase，变量和函数使用 camelCase。新增样式和交互应贴合现有后台工具风格，避免无关重构。

## 测试规范

后端测试放入 `tests/unit`、`tests/integration` 或 `tests/e2e`，文件命名使用 `test_*.py`。涉及数据库、授权、部署、Playwright 会话的改动应补充针对性测试。前端交互优先使用 Playwright，并在提交前运行 `npm run type-check`。

## 提交与 PR 规范

近期提交信息多为简短中文描述，例如 `数据迁移`、`部署优化`。提交应保持范围清晰、描述直接。

PR 应包含：

- 改动内容与原因。
- 影响模块，例如 `backend/api`、`frontend/src`、`deploy/production`。
- 已执行的命令和结果。
- UI 改动截图。
- 涉及 `.env`、Docker、Nginx、noVNC 或数据库迁移时写明部署注意事项。

## 安全与配置提示

不要提交真实 `.env`、密钥、Cookie、token 或浏览器会话文件。生产环境必须配置 `DATABASE_URL`、`AUTO_GEO_ENCRYPTION_KEY` 以及相关 API Key。任何传输 Cookie 或 `storage_state` 的授权流程都应使用 HTTPS。
