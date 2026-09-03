# AutoGeo 部署指南（宝塔面板版）

## 目录结构

```
deploy/
├── README.md                 # 本文件
├── backend/                 # 后端 API 服务
│   ├── docker-compose.yml
│   ├── deploy.sh
│   └── .env.example
├── nginx/                   # Nginx 配置
│   ├── conf.d/
│   └── ssl/
├── production/              # 生产环境（含自建 PostgreSQL）
└── scripts/                 # 辅助脚本
    └── backup.sh
```

## 快速开始

### 第一步：准备共享 PostgreSQL 数据库（必需）

后端不内置数据库，需有一个外部 PostgreSQL 实例供其使用，约定如下：

- 容器名：`n8n_postgres`
- 网络：`n8n_network`
- 用户：`n8n`
- 数据库：`autogeo`（后端启动时自动创建，也可手动创建）

数据库就绪后继续下一步。

---

### 第二步：配置宝塔 Nginx

后端只提供 API 服务（8001 端口），需要在宝塔添加反向代理：

**创建配置文件**：`/www/server/panel/vhost/nginx/autogeo.conf`

```nginx
server {
    listen 80;
    server_name your-domain-or-ip;

    location /api/ {
        proxy_pass http://localhost:8001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /docs {
        proxy_pass http://localhost:8001/docs;
    }

    # WebSocket 支持
    location /ws {
        proxy_pass http://localhost:8001/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**重载 Nginx：**
```bash
/www/server/nginx/sbin/nginx -s reload
```

---

### 第三步：部署后端

```bash
cd backend

# 1. 配置环境变量（注意：文件名为 .env.backend）
cp .env.example .env.backend
nano .env.backend
```

**关键配置：**

```bash
# PostgreSQL 密码（数据库用户 n8n）
N8N_DB_PASSWORD=xxx

# 后端数据库连接串（密码特殊字符需 URL 编码，如 @ 编码为 %40）
DATABASE_URL=postgresql://n8n:xxx@n8n_postgres:5432/autogeo

# 加密密钥（生成: openssl rand -base64 32）
AUTO_GEO_ENCRYPTION_KEY=xxx

# JWT 签名密钥（后端启动强制校验，必填）
JWT_SECRET_KEY=xxx

# DeepSeek API
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_API_URL=https://api.deepseek.com/v1

# RAGFlow（后端启动强制校验，暂时不用也需填非空占位符）
RAGFLOW_API_KEY=xxx
```

```bash
# 2. 执行部署
./deploy.sh
```

访问：`http://your-server-ip/api`

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                   部署架构                               │
├─────────────────┬─────────────────┬─────────────────────┤
│  共享 PostgreSQL │   后端服务      │     前端（静态）     │
│  (n8n_postgres) │   (1容器)       │                     │
├─────────────────┼─────────────────┼─────────────────────┤
│  PostgreSQL ←───┼─── backend      │    /var/www/html    │
│                 │   (API:8001)    │                     │
└─────────────────┴─────────────────┴─────────────────────┘
         │                              ▲
         └───── 宝塔 Nginx:80 ──────────┘
```

### 核心设计
- **后端不再自带数据库**，复用共享 PostgreSQL（容器 `n8n_postgres`）
- **后端不再带 Nginx**，使用宝塔 Nginx 做反向代理

---

## 宝塔环境路径速查

| 项目 | 路径 |
|------|------|
| Nginx 配置目录 | `/www/server/panel/vhost/nginx/` |
| Nginx 主程序 | `/www/server/nginx/sbin/nginx` |
| Nginx 重载命令 | `/www/server/nginx/sbin/nginx -s reload` |
| 网站目录 | `/www/wwwroot/` |

---

## 常用命令

| 操作 | 命令 |
|------|------|
| 部署后端 | `cd backend && ./deploy.sh` |
| 后端日志 | `cd backend && docker-compose logs -f` |
| 停止后端 | `cd backend && docker-compose down` |
| 重载 Nginx | `/www/server/nginx/sbin/nginx -s reload` |

---

## 注意事项

1. **必须先准备共享 PostgreSQL**（容器 `n8n_postgres`），后端依赖该数据库
2. **需要配置宝塔 Nginx** 反向代理到后端 8001 端口
3. 后端会自动在 n8n_postgres 中创建 `autogeo` 数据库
4. 确保防火墙开放 80（http）端口

---

## 故障排查

### 后端无法连接数据库
```bash
# 检查共享 PostgreSQL（n8n_postgres）是否运行
docker ps | grep n8n_postgres

# 检查密码是否正确
docker exec n8n_postgres psql -U n8n -c "\l"
```

### Nginx 配置测试
```bash
/www/server/nginx/sbin/nginx -t
```

### 查看 Nginx 错误日志
```bash
tail -f /www/server/nginx/logs/error.log
```
