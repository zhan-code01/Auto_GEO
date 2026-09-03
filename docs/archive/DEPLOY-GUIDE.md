# AutoGeo CI/CD 自动化部署指南

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CI/CD 自动化部署架构                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   GitHub Repository                                                          │
│      │                                                                       │
│      ├── Push backend/** ──► ┌─────────────────────┐                        │
│      │                       │ deploy-backend.yml  │ ──► 构建镜像 ──► 部署   │
│      │                       └─────────────────────┘                        │
│      │                                                                       │
│      ├── Push frontend/** ──►┌─────────────────────┐                        │
│      │                       │ deploy-frontend.yml │ ──► 构建 ──► SCP 部署   │
│      │                       └─────────────────────┘                        │
│      │                                                                       │
│      └── Manual Trigger ────►┌─────────────────────┐                        │
│                              │ deploy-all.yml      │ ──► 可选部署前后端      │
│                              └─────────────────────┘                        │
│                                      │                                       │
│                                      ▼                                       │
│                           ┌─────────────────────┐                           │
│                           │   你的服务器         │                           │
│                           │  ┌───────────────┐  │                           │
│                           │  │ Nginx (80)   │  │                           │
│                           │  │  ├── /api/* ──┼──┼──► Backend (8001)        │
│                           │  │  ├── /ws ────┼──┼──► WebSocket              │
│                           │  │  └── /* ─────┼──┼──► Frontend (静态文件)     │
│                           │  └───────────────┘  │                           │
│                           │         │           │                           │
│                           │         ▼           │                           │
│                           │  ┌───────────────┐  │                           │
│                           │  │ PostgreSQL   │  │                           │
│                           │  └───────────────┘  │                           │
│                           └─────────────────────┘                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 前置准备

### 1. 服务器准备

```bash
# SSH 登录到你的服务器
ssh root@your-server-ip

# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo systemctl enable docker && sudo systemctl start docker

# 2. 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 3. 克隆项目到 ~/Auto_GEO
cd ~
git clone https://github.com/Architecture-Matrix/Auto_GEO.git

# 4. 配置环境变量
cd ~/Auto_GEO/deploy
cp .env.simple.example .env.backend
vim .env.backend
```

**必须修改的 .env.backend 配置：**

```bash
# 数据库密码（强密码）
DB_PASSWORD=YourStrongPassword123

# 加密密钥（生成命令：python3 -c "import secrets; print(secrets.token_urlsafe(32))"）
AUTO_GEO_ENCRYPTION_KEY=your-32-byte-key-here

# 你的服务器IP或域名
CORS_ORIGINS=http://your-server-ip,http://localhost:5173

# DeepSeek API Key（用于AI生成）
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
```

### 2. 配置 GitHub Secrets

在 GitHub 仓库页面：Settings -> Secrets and variables -> Actions -> New repository secret

| Secret 名称 | 说明 | 获取方式 |
|------------|------|---------|
| `SERVER_HOST` | 服务器IP或域名 | 你的服务器公网IP |
| `SERVER_USER` | SSH用户名 | 通常是 `root` |
| `SERVER_SSH_KEY` | SSH私钥 | 见下方生成步骤 |
| `SERVER_PORT` | SSH端口（可选）| 默认 `22` |
| `ALIYUN_ACR_USERNAME` | 阿里云ACR用户名 | 阿里云控制台 |
| `ALIYUN_ACR_PASSWORD` | 阿里云ACR密码 | 阿里云控制台 |

**生成 SSH 密钥：**

```bash
# 在服务器上执行
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions

# 添加公钥到 authorized_keys
cat ~/.ssh/github_actions.pub >> ~/.ssh/authorized_keys

# 查看私钥（复制到 GitHub Secrets）
cat ~/.ssh/github_actions
```

将私钥完整内容（包括 `-----BEGIN OPENSSH PRIVATE KEY-----` 和 `-----END OPENSSH PRIVATE KEY-----`）复制到 `SERVER_SSH_KEY`。

### 3. 首次手动部署（可选）

```bash
# 在服务器上执行
cd ~/Auto_GEO/deploy
chmod +x deploy-simple.sh
./deploy-simple.sh
```

## 工作流说明

### 自动部署

#### 后端自动部署

**触发条件：**
- Push 到 `main` 或 `master` 分支
- 修改了 `backend/**` 目录下的文件

**执行流程：**
1. 代码检查 (Ruff + MyPy)
2. 单元测试
3. 构建 Docker 镜像
4. 推送到阿里云 ACR
5. SSH 到服务器拉取镜像并重启

#### 前端自动部署

**触发条件：**
- Push 到 `main` 或 `master` 分支
- 修改了 `frontend/**` 目录下的文件

**执行流程：**
1. 安装依赖
2. 运行测试
3. 构建生产版本
4. SCP 上传到服务器 `~/Auto_GEO/deploy/nginx/html/`
5. Reload Nginx

### 手动部署

**触发方式：**
1. 进入 GitHub 仓库 Actions 页面
2. 选择 `Deploy All (Backend + Frontend)`
3. 点击 `Run workflow`
4. 选择要部署的组件
5. 点击运行

**适用场景：**
- 首次部署
- 需要同时部署前后端
- 强制重新部署

## 目录结构

服务器上的目录结构：

```
~/Auto_GEO/
├── backend/                    # 后端代码（自动更新）
├── frontend/                   # 前端代码（自动更新）
├── deploy/
│   ├── docker-compose.backend.yml
│   ├── .env.backend           # 环境变量（手动配置）
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── conf.d/default.conf
│   │   └── html/              # 前端静态文件（自动部署）
│   │       ├── index.html
│   │       └── assets/
│   └── backups/               # 数据库备份
├── nginx/                     # Nginx 配置（开发用）
└── ...
```

## 验证部署

### 后端验证

```bash
# 在服务器上检查容器状态
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml ps

# 检查后端健康状态
curl http://localhost:8001/api/health

# 查看后端日志
docker-compose -f docker-compose.backend.yml logs -f backend
```

### 前端验证

```bash
# 检查前端文件
ls -la ~/Auto_GEO/deploy/nginx/html/

# 检查 Nginx 状态
docker-compose -f docker-compose.backend.yml ps nginx
```

### 浏览器访问

- 前端页面: `http://your-server-ip/`
- API 文档: `http://your-server-ip/docs`
- 健康检查: `http://your-server-ip/api/health`

## 常见问题

### 1. GitHub Actions 部署失败

**检查 Secrets 配置：**
```bash
# 在服务器上测试 SSH 连接（本地）
ssh -i ~/.ssh/github_actions root@your-server-ip
```

**检查服务器目录权限：**
```bash
# 在服务器上
ls -la ~/
# 确保 Auto_GEO 目录存在且可写
```

### 2. 后端启动失败

```bash
# 查看日志
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml logs backend

# 常见错误：
# - 环境变量缺失：检查 .env.backend
# - 数据库连接失败：检查 postgres 是否启动
# - 端口冲突：检查 8001 端口是否被占用
```

### 3. 前端无法访问

```bash
# 检查文件是否上传成功
ls -la ~/Auto_GEO/deploy/nginx/html/

# 检查 Nginx 配置
docker-compose -f docker-compose.backend.yml exec nginx nginx -t

# 重启 Nginx
docker-compose -f docker-compose.backend.yml restart nginx
```

### 4. CORS 跨域错误

修改 `~/Auto_GEO/deploy/.env.backend`：

```bash
# 添加你的前端地址
CORS_ORIGINS=http://your-server-ip,http://localhost:5173,http://127.0.0.1:5173
```

然后重启后端：
```bash
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml restart backend
```

## 更新部署

### 更新代码

```bash
# 本地开发后
 git add .
 git commit -m "feat: xxx"
 git push origin main

# GitHub Actions 会自动部署
```

### 更新环境变量

```bash
# 在服务器上修改
cd ~/Auto_GEO/deploy
vim .env.backend

# 重启服务
docker-compose -f docker-compose.backend.yml restart
```

### 更新 Nginx 配置

```bash
# 本地修改 nginx/conf.d/default.conf
 git add .
 git commit -m "chore: update nginx config"
 git push origin main

# 手动重载 Nginx（或等待下次前端部署）
ssh root@your-server-ip "cd ~/Auto_GEO/deploy && docker-compose -f docker-compose.backend.yml exec -T nginx nginx -s reload"
```

## 备份与恢复

### 数据库备份

```bash
# 自动备份（每天凌晨执行）
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml exec -T postgres pg_dump -U autogeo autogeo > backups/auto_geo_$(date +%Y%m%d_%H%M%S).sql

# 手动备份
docker-compose -f docker-compose.backend.yml exec -T postgres pg_dump -U autogeo autogeo > backup.sql
```

### 数据库恢复

```bash
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml exec -T postgres psql -U autogeo autogeo < backup.sql
```

## 安全建议

1. **修改默认密码**：首次部署后立即修改 `DB_PASSWORD`
2. **使用强密钥**：`AUTO_GEO_ENCRYPTION_KEY` 使用随机生成的 32 字节密钥
3. **配置防火墙**：仅开放 80/443 端口
4. **启用 HTTPS**：使用 Certbot 配置 SSL
5. **定期更新**：及时更新 Docker 镜像和系统补丁

## 性能优化

### 调整资源限制

编辑 `docker-compose.backend.yml`：

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '4'      # 根据服务器配置调整
          memory: 4G
```

### 数据库优化

```bash
# 进入 PostgreSQL
docker-compose -f docker-compose.backend.yml exec postgres psql -U autogeo

# 查看慢查询
SELECT * FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;
```

---

**部署完成！** 访问 `http://your-server-ip/` 查看应用。
