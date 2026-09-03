# AutoGeo 后端服务

> FastAPI + Playwright 智能文章发布系统后端

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 安装 Playwright 浏览器

```bash
playwright install chromium
```

如果下载慢，使用国内镜像：
```bash
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
playwright install chromium
```

### 3. 启动服务

```bash
python main.py
```

**服务地址**：`http://127.0.0.1:8001`

**API文档**：`http://127.0.0.1:8001/docs`

## API 接口

### 账号管理

| 方法 | 路径 | 说明 |
|-----|------|------|
| GET | `/api/accounts` | 获取账号列表 |
| POST | `/api/accounts` | 创建账号 |
| GET | `/api/accounts/{id}` | 获取账号详情 |
| PUT | `/api/accounts/{id}` | 更新账号 |
| DELETE | `/api/accounts/{id}` | 删除账号 |
| POST | `/api/accounts/auth/start` | 开始授权 |
| GET | `/api/accounts/auth/status/{task_id}` | 查询授权状态 |
| POST | `/api/accounts/auth/confirm/{task_id}` | 确认授权完成 |
| DELETE | `/api/accounts/auth/task/{task_id}` | 取消授权任务 |

### 文章管理

| 方法 | 路径 | 说明 |
|-----|------|------|
| GET | `/api/articles` | 获取文章列表 |
| POST | `/api/articles` | 创建文章 |
| GET | `/api/articles/{id}` | 获取文章详情 |
| PUT | `/api/articles/{id}` | 更新文章 |
| DELETE | `/api/articles/{id}` | 删除文章 |

### 发布管理

| 方法 | 路径 | 说明 |
|-----|------|------|
| POST | `/api/publish/start` | 开始发布任务 |
| GET | `/api/publish/status/{task_id}` | 查询发布状态 |
| DELETE | `/api/publish/task/{task_id}` | 取消发布任务 |

### 其他接口

| 方法 | 路径 | 说明 |
|-----|------|------|
| GET | `/` | 服务信息 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/platforms` | 支持的平台列表 |
| WS | `/ws` | WebSocket 连接 |

## Docker 部署

### 镜像仓库

| 仓库 | 地址 | 说明 |
|-----|------|------|
| 阿里云ACR（广州） | `crpi-lwz264sedmauvivo.cn-guangzhou.personal.cr.aliyuncs.com/opencaio/auto_geo_backend` | 优先使用 |
| GHCR | `ghcr.io/architecture-matrix/auto_geo_backend` | 备用 |

### 手动部署

```bash
# 拉取镜像（阿里云ACR优先）
docker pull crpi-lwz264sedmauvivo.cn-guangzhou.personal.cr.aliyuncs.com/opencaio/auto_geo_backend:latest

# 创建数据目录
mkdir -p ~/autogeo/data ~/autogeo/logs ~/autogeo/database ~/autogeo/cookies

# 启动容器
docker run -d \
  --name autogeo-backend \
  --restart unless-stopped \
  -p 8001:8001 \
  -v ~/autogeo/data:/app/data \
  -v ~/autogeo/logs:/app/logs \
  -v ~/autogeo/database:/app/database \
  -v ~/autogeo/cookies:/app/.cookies \
  -e ENVIRONMENT=production \
  -e HOST=0.0.0.0 \
  -e PYTHONUNBUFFERED=1 \
  -e RAGFLOW_BASE_URL=https://ragflow.xinzhixietong.com \
  crpi-lwz264sedmauvivo.cn-guangzhou.personal.cr.aliyuncs.com/opencaio/auto_geo_backend:latest
```

### 健康检查

```bash
# 检查容器状态
docker ps | grep autogeo-backend

# 检查服务健康
curl http://localhost:8001/api/health

# 查看日志
docker logs autogeo-backend --tail 100 -f
```

## 目录结构

```
backend/
├── main.py                 # 服务入口
├── config.py               # 配置文件
├── requirements.txt        # 依赖清单
├── api/                    # API 路由
│   ├── account.py          # 账号 API
│   ├── article.py          # 文章 API
│   └── publish.py          # 发布 API
├── database/               # 数据库
│   └── models.py           # 数据模型
├── schemas/                # Pydantic 模型
└── services/               # 业务服务
    └── playwright/         # Playwright 服务
        └── publishers/      # 各平台发布器
```

## 开发说明

### 数据存储

- **数据库文件**: `database/auto_geo.db`
- **Cookie存储**: `../.cookies/` 目录
- **日志文件**: `../logs/auto_geo.log`

---

**更新日期**: 2026-02-25
