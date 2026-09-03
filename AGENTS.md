# Repository Guidelines

## 项目结构与模块组织

AutoGeo 是一个前后端一体的自动化平台项目：

- `backend/`：Python FastAPI 后端，包含 API、数据库模型、迁移、Playwright 自动化、静态资源与模板。
- `frontend/`：Vue 3 + Vite + Electron 前端，主要 UI 在 `frontend/src`，桌面端入口在 `frontend/electron`。
- `tests/`：测试目录，包含 `unit/`、`integration/`、`e2e/`，公共 fixture 在 `tests/conftest.py`。
- `deploy/production/`：生产 Docker Compose 部署配置。
- `extensions/cookie-sync/`：浏览器 Cookie 同步插件。
- `docs/`：架构、部署、功能方案和实施文档。

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
