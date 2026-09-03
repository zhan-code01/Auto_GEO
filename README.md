# AutoGeo — 智能多平台内容发布与 AI 搜索优化平台

AutoGeo 是一套面向 GEO（Generative Engine Optimization，生成式引擎优化）/ SEO 运营的一体化自动化平台：以 LLM 大模型生成内容，以 Playwright 浏览器自动化完成多平台账号授权与文章发布，并以 AI 平台问答测评来量化内容的 AI 搜索收录效果，形成「选题 → 生成 → 授权 → 发布 → 收录测评 → 数据复盘」的完整运营闭环。

项目采用前后端分离架构：前端为 Vue 3 + Vite + Electron 桌面应用（同时支持浏览器 H5 模式），后端为 FastAPI + PostgreSQL + Playwright 服务。

## 核心能力

| 模块 | 说明 |
| --- | --- |
| 智能文章生成 | 多角色协作研究、关键词蒸馏、参考知识库检索，一键生成结构化长文 |
| 多平台发布 | 覆盖知乎、百家号、搜狐号、头条号、微信公众号、小红书、B 站、抖音、CSDN 等 40+ 内容平台 |
| 账号与授权 | 多平台账号加密存储，支持云端远程授权（noVNC）与本地浏览器桥接授权 |
| 本地客户端发布 | Electron 客户端注册设备、拉取发布任务，通过本地浏览器 + AdsPower 指纹浏览器执行发布 |
| GEO 收录测评 | 基于豆包 / DeepSeek / 通义千问的 AI 平台问答，对文章收录情况进行多指标测评 |
| 定时任务 | APScheduler 驱动的自动发布、自动测评、自动同步 |
| 数据报表 | ECharts 可视化的发布、收录、账号等多维度统计 |
| 预警与通知 | 飞书机器人消息推送，发布 / 测评异常实时预警 |
| 知识库管理 | 接入 RAGFlow，支持文档上传、同步、去重与相似度检索 |
| 智能建站 | 基于模板的站点快速生成 |
| Agent 智能体 | 基于 LangGraph 的多智能体对话（SSE 流式输出），支持 Excel 批量文章生成 |
| 发布审批 | 支持配额、平台、时间窗口、IP 等多重发布前审批 |

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Element Plus、ECharts、wangEditor、Electron |
| 后端 | Python 3.12、FastAPI、SQLAlchemy、Alembic、Pydantic、Loguru |
| 自动化 | Playwright、APScheduler、LangGraph / LangChain |
| 数据库 | PostgreSQL（SQLAlchemy ORM + Alembic 迁移） |
| 三方服务 | DeepSeek、火山方舟 ARK（豆包 / DeepSeek-R1）、RAGFlow、飞书、AdsPower |

## 架构概览

```text
┌─────────────────┐        HTTP / WebSocket (SSE)       ┌────────────────────────────────┐
│   Vue 3 前端     │ ──────────────────────────────────▶ │         FastAPI 后端 (8001)     │
│  Electron / H5  │                                     │  API 路由 · 业务服务 · 定时任务  │
└─────────────────┘                                     │  Playwright 自动化 · Agent V2   │
                                                        └──────────┬───────────┬─────────┘
                                                                   │           │
                                                     ┌─────────────▼──┐   ┌────▼──────────────┐
                                                     │   PostgreSQL    │   │   第三方服务       │
                                                     │     数据库       │   │ DeepSeek / 豆包   │
                                                     └────────────────┘   │ RAGFlow / 飞书    │
                                                                          │ AdsPower          │
                                                                          └───────────────────┘
```

- 前端默认通过 `VITE_API_BASE_URL` 指向后端服务，开发态与 H5 模式、Electron 桌面端共用同一套渲染端代码。
- 后端按 `api`（路由）/ `services`（业务逻辑）/ `models`（数据模型）/ `migrations`（迁移）分层组织。

## 目录结构

```text
Auto_GEO
├── backend/                    # FastAPI 后端（API、服务、模型、迁移、Playwright 自动化）
├── frontend/                   # Vue 3 + Vite + Electron 前端（含 H5 模式与本地发布客户端）
├── deploy/
│   ├── production/             # 生产环境 Docker Compose（postgres + backend + frontend + noVNC）
│   ├── backend/                # 宝塔单后端部署配置（兼容）
│   └── nginx/                  # Nginx 反向代理配置
├── tests/                      # 单元 / 集成 / e2e 测试（conftest.py 提供公共 fixture）
├── docs/                       # 架构、方案与实施文档
├── extensions/cookie-sync/     # 浏览器 Cookie 同步插件
├── .github/workflows/          # CI / CD / Electron 打包工作流
├── docker-compose.local.yml    # 本地开发 PostgreSQL
├── .env.example                # 项目环境变量模板
├── AGENTS.md                   # 仓库开发规范
└── SETUP.md                    # 安装与配置说明
```

## 快速开始（本地开发）

### 环境要求

- Python 3.12
- Node.js 18+（推荐 20+）
- Docker（用于本地 PostgreSQL，或自备 PostgreSQL 实例）

### 1. 启动本地数据库

```bash
docker compose -f docker-compose.local.yml up -d postgres
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
playwright install chromium

# 配置环境变量（复制根目录模板，按需填写）
cp ../.env.example .env

# 初始化数据库表结构
alembic upgrade head

# 返回仓库根目录启动后端（默认 0.0.0.0:8001）
cd ..
python -m backend.main
```

> 关键环境变量说明：`DATABASE_URL` 必须指向 PostgreSQL；`AUTO_GEO_ENCRYPTION_KEY`、`JWT_SECRET_KEY` 为必填密钥；`RAGFLOW_API_KEY` 必填（暂未启用 RAGFlow 时可填写占位符）；`DEEPSEEK_API_KEY`、`VOLCENGINE_ARK_API_KEY` 等按需配置。完整变量见根目录 [.env.example](./.env.example)。

### 3. 启动前端

```bash
cd frontend
npm install

# Electron 桌面端
npm run dev

# 或浏览器 H5 模式（http://localhost:5173）
npm run dev:h5
```

前端环境变量可参考 [frontend/.env.example](./frontend/.env.example)，其中 `VITE_API_BASE_URL` 用于指定后端地址。

## 生产部署

生产环境采用 Docker Compose 一键编排后端、前端（Nginx 托管）与远程浏览器授权服务（noVNC）：

```bash
cd deploy/production
cp .env.example .env
# 编辑 .env，填写生产密钥、数据库密码、后端域名等

./deploy.sh    # 首次构建并启动
./update.sh    # 后续增量更新
```

也可直接使用 Docker Compose：

```bash
cd deploy/production
docker compose --env-file .env -f docker-compose.yml up -d --build
```

> 生产环境必须配置 `DATABASE_URL`、`AUTO_GEO_ENCRYPTION_KEY` 及所需 API Key。任何传输 Cookie 或浏览器会话（storage_state）的授权流程都应使用 HTTPS。部署注意事项详见 [deploy/production/README.md](./deploy/production/README.md)。

## 测试与代码检查

```bash
# 后端测试与 lint（仓库根目录）
pytest tests
ruff check backend tests

# 前端类型检查 / lint / 测试
cd frontend
npm run type-check
npm run lint
npm test
```

## CI/CD

GitHub Actions 工作流位于 [.github/workflows](./.github/workflows)，覆盖以下环节：

| 工作流 | 文件 | 说明 |
| --- | --- | --- |
| CI | `ci.yml` | 按变更范围自动触发：后端 ruff + mypy + pytest，前端 Playwright 测试 + type-check + build |
| Deploy Backend | `deploy-backend.yml` | 后端部署到远程服务器 |
| Deploy Frontend | `deploy-frontend.yml` | 前端构建并部署 |
| Deploy All | `deploy-all.yml` | 后端 + 前端一键全量部署 |
| Electron Build & Release | `electron-build.yml` | 跨平台打包 Windows / Linux / macOS 桌面客户端并发布 |

各工作流所需 Secrets 配置方式见 [.github/workflows/README.md](./.github/workflows/README.md)。

## 文档

更详细的设计与实施文档位于 [docs/](./docs/) 目录，包括系统架构、各功能方案与部署实施说明。仓库开发规范见 [AGENTS.md](./AGENTS.md)，安装配置补充说明见 [SETUP.md](./SETUP.md)。

## 安全提示

- 不要提交真实的 `.env`、密钥、Cookie、token 或浏览器会话文件到仓库。
- 生产环境必须配置强随机 `AUTO_GEO_ENCRYPTION_KEY` 与 `JWT_SECRET_KEY`。
- 涉及 Cookie / `storage_state` 的授权与同步流程务必走 HTTPS。
