# GitHub Actions 工作流说明

## 工作流概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CI/CD 工作流架构                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Push/PR                                                                    │
│      │                                                                       │
│      ▼                                                                       │
│   ┌─────────────┐                                                           │
│   │  CI (ci.yml) │ ◄── 所有分支的代码检查（前后端分离执行）                   │
│   └─────────────┘                                                           │
│          │                                                                   │
│   Push to main/master                                                        │
│      │                                                                       │
│      ├──► ┌─────────────────────┐                                           │
│      │    │ deploy-backend.yml  │ ◄── 仅 backend/** 变更时触发               │
│      │    │ 后端自动部署         │                                           │
│      │    └─────────────────────┘                                           │
│      │                                                                       │
│      └──► ┌─────────────────────┐                                           │
│           │ deploy-frontend.yml │ ◄── 仅 frontend/** 变更时触发              │
│           │ 前端自动部署         │                                           │
│           └─────────────────────┘                                           │
│                                                                              │
│   Manual Trigger                                                             │
│      │                                                                       │
│      ▼                                                                       │
│   ┌─────────────────────┐                                                   │
│   │ deploy-all.yml      │ ◄── 手动触发，可选部署前后端                       │
│   │ 全量部署           │                                                   │
│   └─────────────────────┘                                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 工作流详细说明

### 1. CI 工作流 (`ci.yml`)

**触发条件**: 所有分支的 push 和 PR

**功能**:
- 智能检测变更文件（前后端分离）
- 后端：Ruff 代码检查、MyPy 类型检查、单元测试
- 前端：npm test、npm run build

**特点**:
- 前后端独立执行，互不影响
- 仅检测到有变更的部分才会执行对应 CI

### 2. 后端部署 (`deploy-backend.yml`)

**触发条件**:
- push 到 main/master 分支且 `backend/**` 有变更
- 手动触发 (workflow_dispatch)

**执行步骤**:
1. Lint & Type Check
2. Unit Tests
3. Build Docker Image
4. Push to Aliyun ACR
5. Deploy to Server (SSH)

**服务器操作**:
```bash
# 自动执行
cd ~/Auto_GEO
git pull
cd deploy
docker-compose -f docker-compose.backend.yml pull backend
docker-compose -f docker-compose.backend.yml up -d
# 健康检查
curl http://localhost:8001/api/health
```

### 3. 前端部署 (`deploy-frontend.yml`)

**触发条件**:
- push 到 main/master 分支且 `frontend/**` 有变更
- 手动触发 (workflow_dispatch)

**执行步骤**:
1. npm ci
2. npm run test
3. npm run build (使用生产环境配置)
4. SCP 上传到服务器
5. Reload Nginx

**服务器目录**:
```
~/Auto_GEO/deploy/nginx/html/
├── index.html
├── assets/
└── ...
```

### 4. 全量部署 (`deploy-all.yml`)

**触发条件**: 仅手动触发

**参数选项**:
- `deploy_backend`: 是否部署后端 (boolean)
- `deploy_frontend`: 是否部署前端 (boolean)
- `skip_tests`: 是否跳过测试 (boolean)

**使用场景**:
- 首次部署
- 需要同时更新前后端
- 手动回滚

## 环境变量配置

在 GitHub Repository Settings -> Secrets and variables -> Actions 中配置：

### 必需 Secrets

| 名称 | 说明 | 示例 |
|------|------|------|
| `SERVER_HOST` | 服务器IP或域名 | `1.2.3.4` |
| `SERVER_USER` | SSH用户名 | `root` |
| `SERVER_SSH_KEY` | SSH私钥 | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `SERVER_PORT` | SSH端口（可选）| `22` |
| `ALIYUN_ACR_USERNAME` | 阿里云ACR用户名 | `username` |
| `ALIYUN_ACR_PASSWORD` | 阿里云ACR密码 | `password` |

### 可选 Secrets

| 名称 | 说明 |
|------|------|
| `GITLEAKS_LICENSE` | Gitleaks 许可证（组织账号）|

## 服务器准备

### 1. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable docker && sudo systemctl start docker

sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. 克隆项目

```bash
cd ~
git clone https://github.com/Architecture-Matrix/Auto_GEO.git
```

### 3. 配置环境变量

```bash
cd ~/Auto_GEO/deploy
cp .env.simple.example .env.backend
vim .env.backend
```

必须修改：
- `DB_PASSWORD`
- `AUTO_GEO_ENCRYPTION_KEY`
- `CORS_ORIGINS`（添加服务器IP）
- `DEEPSEEK_API_KEY`

### 4. 配置 SSH 密钥

在 GitHub Secrets 中添加 `SERVER_SSH_KEY`，内容为服务器私钥：

```bash
# 在服务器上生成密钥（如果没有）
ssh-keygen -t ed25519 -C "github-actions"
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys

# 复制私钥到 GitHub Secrets
cat ~/.ssh/id_ed25519
```

## 使用指南

### 自动部署

1. 开发代码
2. Push 到 main/master 分支
3. 根据变更文件自动触发：
   - 修改 `backend/**` → 自动部署后端
   - 修改 `frontend/**` → 自动部署前端
   - 同时修改 → 同时部署

### 手动部署

1. 进入 Actions 页面
2. 选择 `Deploy All (Backend + Frontend)`
3. 点击 `Run workflow`
4. 选择需要部署的组件
5. 点击运行

### 查看部署状态

- GitHub Actions 页面显示实时状态
- 部署成功后会在 Summary 显示访问地址
- 失败时会显示错误日志

## 故障排查

### 后端部署失败

```bash
# 在服务器上查看日志
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml logs backend

# 检查健康状态
curl http://localhost:8001/api/health
```

### 前端部署失败

```bash
# 检查文件是否上传成功
ls -la ~/Auto_GEO/deploy/nginx/html/

# 检查 Nginx 状态
cd ~/Auto_GEO/deploy
docker-compose -f docker-compose.backend.yml ps nginx
docker-compose -f docker-compose.backend.yml logs nginx
```

### 权限问题

```bash
# 确保目录权限正确
sudo chown -R $USER:$USER ~/Auto_GEO

# Docker 权限
sudo usermod -aG docker $USER
# 重新登录生效
```

## 注意事项

1. **首次部署**: 建议先手动在服务器上执行 `./deploy-simple.sh` 确保配置正确
2. **数据库**: 首次部署会自动初始化，后续部署会保留数据
3. **CORS**: 修改前端地址后需要在 `.env.backend` 中更新 `CORS_ORIGINS`
4. **镜像**: 后端镜像推送到阿里云 ACR，确保配置正确的凭证
