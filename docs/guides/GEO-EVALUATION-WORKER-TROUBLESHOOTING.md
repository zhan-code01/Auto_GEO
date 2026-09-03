# GEO 测评 Worker 问题排查与修复记录

> 日期：2026-08-05
> 作者：AI Agent（Trae）
> 涉及模块：`backend/config.py`、`backend/workers/geo_evaluation_worker.py`、`backend/geo_evaluation_worker_runner.spec`、`frontend/electron/main/geo-evaluation-engine.ts`

---

## 一、问题概述

用户点击"收录监控 → 生成基线"后，出现两个连续问题：

1. **浏览器无法拉起**：Worker 进程启动失败，没有任何浏览器窗口弹出。
2. **浏览器拉起但未登录**：Worker 能拉起浏览器，也能提问，但豆包等平台显示未登录状态，无法获取回答。

---

## 二、问题 1：Worker 进程启动失败

### 2.1 症状

- 点击"生成基线"后，服务器日志显示设备注册成功、心跳正常、run 状态为 `running`。
- 客户端没有拉取浏览器，也没有任何报错提示。
- 日志文件 `%APPDATA%\auto-geo-frontend\logs\geo-evaluation-worker.log` 不存在。

### 2.2 根因

Worker 进程在启动时，`backend/config.py` 中的环境变量校验直接抛出 `ValueError`，导致进程崩溃退出。具体有三处校验：

| 校验项 | 原条件 | 问题 |
|--------|--------|------|
| `DATABASE_URL` | `not getattr(sys, 'frozen', False)` | 只覆盖 PyInstaller exe 模式，不覆盖 Python 回退模式 |
| `AUTO_GEO_ENCRYPTION_KEY` | `not getattr(sys, 'frozen', False)` | 同上 |
| `RAGFLOW_API_KEY` | `not getattr(sys, 'frozen', False)` | 同上 |

Worker 进程（无论是 exe 打包还是 Python 回退模式）**不需要数据库连接、不需要加解密 Cookie、不需要 RAGFlow**，它只通过 HTTP API 与后端通信并操作浏览器。但这些校验在 Python 模式下仍然会触发。

### 2.3 修复

在 `backend/config.py` 第 98 行统一定义 `_is_worker_process` 标志，识别三种 worker 场景：

```python
_is_worker_process = (
    getattr(sys, 'frozen', False)              # PyInstaller exe 模式
    or os.getenv('AUTOGEO_WORKER_TOKEN') is not None  # 设置了 worker token
    or any('geo_evaluation_worker' in a for a in sys.argv)  # argv 含 worker 关键字
)
```

将三处校验统一改为：

```python
if not DATABASE_URL and not _is_worker_process:
    raise ValueError(...)

if not _encryption_key and not _is_worker_process:
    raise ValueError(...)

if not RAGFLOW_API_KEY and not _is_worker_process:
    raise ValueError(...)
```

### 2.4 附带修复：PyInstaller spec 文件

`backend/geo_evaluation_worker_runner.spec` 中 `EXE()` 的 `distpath` 参数不被 PyInstaller 识别（它只认全局变量 `distpath`），导致 exe 输出到 `backend/dist/` 而非预期的 `backend/scripts/dist/`。

修复方式：在 spec 文件顶部定义全局变量 `distpath`，移除 `EXE()` 中的 `distpath` 参数。

```python
# 全局变量（PyInstaller 通过它指定输出目录）
distpath = os.path.join(BACKEND_ROOT, 'scripts', 'dist')

exe = EXE(
    ...
    # 不要在这里写 distpath=...
)
```

---

## 三、问题 2：浏览器拉起但未登录

### 3.1 症状

- Worker 能正常拉起浏览器（headed 模式，可见窗口）。
- 豆包页面显示"登录"按钮（未登录状态）。
- 客户端"账号管理"页面显示豆包"已授权"。
- Worker 能发送问题，但无法获取回答（因为未登录）。

### 3.2 根因

**Worker 的 `--session-path` 参数只用于任务结束后保存 session，从未用于启动时加载。**

完整的 session 流转链路：

```
授权流程 (local-auth.ts):
  1. 用户扫码登录豆包
  2. 保存 session → %APPDATA%\AutoGeo\sessions\doubao.json  ✅
  3. 同步 session → 服务器 /api/auth/sync-local-storage-state  ✅

Worker 启动 (geo_evaluation_worker.py):
  1. 从服务器 payload API 获取 platform_sessions
  2. 如果服务器返回空或无效 → storage_state = None/空dict → 干净浏览器 → 未登录！
  3. --session-path 只用于 _save_local_session()（任务结束后保存），从未用于加载！
```

服务器端 session 可能因为以下原因返回空或无效：
- `validate_session` 的 7 天过期检查
- HTTP cookie 验证失败（服务器无法用加密 key 解密）
- 加密/解密过程异常
- 返回了一个结构存在但 `cookies: []`、`origins: []` 的空 session

而本地 `%APPDATA%\AutoGeo\sessions\doubao.json` 是授权时刚保存的、确认有效的 session（包含 27 个 cookies + 1 个 origin），但 Worker 根本不用它。

### 3.3 修复

在 `backend/workers/geo_evaluation_worker.py` 的 `run()` 方法中，增加 session 有效性判断和本地回退逻辑：

```python
async def run(self) -> None:
    payload = await self.api.payload()
    self.storage_state = (payload.get("platform_sessions") or {}).get(self.platform)

    # 判断服务器 session 是否有效：必须有 cookies 或 origins
    server_session_valid = bool(
        self.storage_state
        and (self.storage_state.get("cookies") or self.storage_state.get("origins"))
    )

    if not server_session_valid:
        emit("server_session_invalid", ...)

    # 服务器 session 无效时，回退读取本地授权会话文件
    if not server_session_valid and self.local_session_path and self.local_session_path.exists():
        try:
            local_state = json.loads(self.local_session_path.read_text(encoding="utf-8"))
            if local_state and (local_state.get("cookies") or local_state.get("origins")):
                self.storage_state = local_state
                emit("session_loaded_from_local", ...)
            else:
                emit("session_local_file_empty", ...)
        except Exception as exc:
            emit("session_local_load_failed", ...)

    if not self.storage_state or not (
        self.storage_state.get("cookies") or self.storage_state.get("origins")
    ):
        emit("session_missing", ...)
```

**关键改进**：
- 不再简单判断 `not self.storage_state`（空 dict `{}` 是 falsy 但 `{"cookies": [], "origins": []}` 是 truthy）
- 改为检查 `cookies` 和 `origins` 是否非空列表
- 服务器 session 无效时自动回退本地文件
- 新增 `server_session_invalid`、`session_loaded_from_local` 等诊断事件，方便排查

### 3.4 为什么服务器 session 会无效

服务器端 payload API（`client_geo_evaluation.py`）获取 session 的逻辑：

1. 优先从 `run.account_id` 关联的 `Account.storage_state` 解密获取
2. 如果没有 account，调用 `secure_session_manager.load_session()` 获取

可能失败的原因：
- Account 记录不存在或 `storage_state` 字段为空
- 加密 key 不匹配（服务器和客户端使用不同的 `AUTO_GEO_ENCRYPTION_KEY`）
- `secure_session_manager` 的 7 天过期检查
- HTTP cookie 验证失败（服务器无法访问豆包验证 cookie 有效性）

本地 session 文件是授权时由 Electron 主进程直接保存的 Playwright `storageState`，不经过服务器加密/验证，因此更可靠。

---

## 四、构建与打包流程

### 4.1 完整构建命令

```bash
# 1. 重建 worker exe（输出到 backend/scripts/dist/）
cd backend
pyinstaller geo_evaluation_worker_runner.spec --noconfirm

# 2. 构建前端 renderer
cd ../frontend
npm run build:renderer

# 3. 打包 Electron 安装包
npx electron-builder --win
```

### 4.2 关键文件路径

| 文件 | 说明 |
|------|------|
| `backend/geo_evaluation_worker_runner.spec` | PyInstaller 打包配置 |
| `backend/scripts/dist/geo_evaluation_worker_runner.exe` | Worker exe 输出目录 |
| `frontend/electron-builder.yml` | Electron 打包配置 |
| `frontend/dist/AutoGeo-1.0.0-win-x64.exe` | 最终安装包 |
| `frontend/electron/main/geo-evaluation-engine.ts` | Worker 进程管理（Electron 主进程） |
| `frontend/electron/main/local-auth.ts` | 本地授权与会话管理 |

### 4.3 electron-builder.yml 关键配置

```yaml
extraResources:
  - from: ../backend          # 打包整个 backend 目录
    to: backend
    filter:
      - '**/*'
      - '!**/__pycache__'
      - '!**/*.pyc'
      # ... 排除项
  - from: ../backend/scripts/dist   # 单独打包 worker exe
    to: backend/scripts/dist
    filter:
      - '**/*.exe'
```

安装后 exe 路径：`<安装目录>\resources\backend\scripts\dist\geo_evaluation_worker_runner.exe`

---

## 五、日志与诊断

### 5.1 日志文件位置

```
%APPDATA%\AutoGeo\logs\geo-evaluation-worker.log
```

注意：`%APPDATA%` 展开后通常是 `C:\Users\<用户名>\AppData\Roaming`。

### 5.2 关键诊断事件

Worker 通过 stdout 输出 JSON 事件，Electron 主进程将其写入日志文件：

| 事件 | 含义 |
|------|------|
| `worker_started` | Worker 启动，含 `session_loaded` 字段 |
| `server_session_invalid` | 服务器 session 无效（cookies/origins 为空） |
| `session_loaded_from_local` | 成功从本地文件加载 session |
| `session_local_file_empty` | 本地 session 文件存在但为空 |
| `session_local_load_failed` | 本地 session 文件读取/解析失败 |
| `session_missing` | 服务器和本地都没有有效 session |
| `browser_started` | 浏览器启动成功，含 `session_loaded` 字段 |
| `worker_failed` | Worker 执行失败，含错误信息和 traceback |

### 5.3 手动检查本地 session 文件

```powershell
# 检查 session 文件是否存在
Test-Path "$env:APPDATA\auto-geo-frontend\sessions\doubao.json"

# 查看文件大小和修改时间
Get-Item "$env:APPDATA\auto-geo-frontend\sessions\doubao.json" | Select-Object Length, LastWriteTime

# 快速验证 cookies 数量
$json = Get-Content "$env:APPDATA\auto-geo-frontend\sessions\doubao.json" -Raw | ConvertFrom-Json
Write-Host "Cookies: $($json.cookies.Count), Origins: $($json.origins.Count)"
```

---

## 六、后续注意事项

### 6.1 重新授权

如果本地 session 文件也过期或无效，用户需要重新授权：
1. 在客户端"账号管理"页面点击"重新授权"
2. 扫码登录对应平台
3. 授权完成后 session 会自动保存到本地并同步到服务器

### 6.2 服务器端 session 过期

服务器端 `secure_session_manager` 有 7 天过期检查。如果用户超过 7 天未使用，服务器 session 会过期，但本地 session 文件仍然有效（由本地回退逻辑兜底）。

### 6.3 加密 key 变更

如果服务器的 `AUTO_GEO_ENCRYPTION_KEY` 发生变更，所有已加密的 server-side session 都会解密失败。此时本地 session 文件不受影响（本地文件是明文 JSON），本地回退逻辑可以继续工作。

### 6.4 构建缓存问题

- PyInstaller 有缓存机制，修改 Python 源码后如果 exe 没有更新，使用 `--noconfirm` 参数强制重建
- Docker 构建缓存可能导致 Dockerfile 修改不生效，使用 `--no-cache` 强制重建
- Electron 的 `node_modules` 缓存可能导致依赖更新不生效，删除 `node_modules` 后重新 `npm install`

---

## 七、修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `backend/config.py` | 三处环境变量校验改用 `_is_worker_process` 标志 |
| `backend/workers/geo_evaluation_worker.py` | `run()` 方法增加 session 有效性判断和本地回退逻辑 |
| `backend/geo_evaluation_worker_runner.spec` | 修复 `distpath` 参数（改为全局变量） |
