# 智能建站部署后预览不刷新 401 问题优化方案

## 1. 问题现象

部署到服务器后，智能建站页面左侧表单可以编辑，但右侧预览区域一直停留在：

```text
Ready...
AI 引擎已就绪
```

浏览器 Network 中失败请求为：

```text
POST http://8.163.39.114/api/sites/build
Status Code: 401 Unauthorized
```

这说明右侧不刷新不是 iframe 本身的问题，而是“生成预览站点”的接口被认证拦截了。

## 2. 预览刷新链路

智能建站正常刷新流程应该是：

```text
用户修改左侧配置
-> 前端 debounce 触发 generate()
-> POST /api/sites/build
-> 后端生成 backend/static/sites/{site_id}/index.html
-> 返回 site_id 和 preview_url
-> 前端设置 iframe src
-> 右侧预览刷新
```

当前卡在第二步：

```text
POST /api/sites/build -> 401 Unauthorized
```

所以后续 `site_id`、`preview_url` 都拿不到，右侧自然不会刷新。

## 3. 根因分析

### 3.1 请求没有携带 Authorization

截图中的请求头没有：

```text
Authorization: Bearer <token>
```

后端如果要求 `/api/*` 必须登录，缺少这个头就会返回 401。

### 3.2 智能建站页面绕过了统一 API 封装

项目里统一 API 实例在：

```text
frontend/src/services/api/index.ts
```

该实例会自动从 `localStorage` 读取 token，并加入请求头：

```ts
config.headers.Authorization = `Bearer ${token}`
```

但智能建站页面当前直接使用：

```ts
import axios from 'axios';
axios.post(`${apiBase}/sites/build`, ...)
axios.post(`${apiBase}/sites/deploy`, ...)
```

这类原生 axios 请求不会自动走项目封装的拦截器，因此不会自动带 token。

### 3.3 当前仓库与服务器部署版本可能不一致

当前仓库的 `backend/middleware/auth_middleware.py` 白名单里已经包含：

```text
/api/sites/build
/api/sites/deploy
```

如果服务器上仍然返回 401，通常说明至少存在一种情况：

1. 服务器运行的后端代码不是当前最新版本。
2. 容器或进程没有重启，仍在使用旧代码。
3. 线上白名单没有包含 `/api/sites/build`。
4. 线上请求路径经过 Nginx 转发后发生变化，导致白名单没有命中。
5. 前端请求没有 token，而后端又没有放行该接口。

### 3.4 静态资源也需要确认放行

即使 `/api/sites/build` 成功，右侧 iframe 还会加载：

```text
/static/sites/{site_id}/index.html
/static/uploads/...
```

这些静态资源必须允许浏览器直接访问。否则 iframe 可能出现空白、图片不显示或二次 401。

## 4. 推荐修复策略

智能建站属于后台产品功能，推荐采用“登录态方案”：

```text
页面 API 请求带 JWT
静态预览资源公开访问
```

即：

- `/api/sites/build`：需要登录，前端带 `Authorization`。
- `/api/sites/deploy`：需要登录，前端带 `Authorization`。
- `/api/upload`：需要登录，前端带 `Authorization`。
- `/static/sites/`：公开访问，用于 iframe 预览。
- `/static/uploads/`：公开访问，用于图片资源展示。

这样既保证后台操作安全，又保证生成网页可以直接在浏览器里打开。

## 5. 可执行方案 A：登录态方案

### 5.1 前端统一走 API 封装

把智能建站里的原生 axios 调用切换成项目统一请求方法。

目标：

```text
所有 /api/* 请求都经过 frontend/src/services/api/index.ts
```

好处：

1. 自动携带 JWT。
2. 统一处理 401。
3. 统一处理 API Base URL。
4. 避免某些页面能请求、某些页面不能请求。

智能建站需要覆盖的请求：

```text
POST /api/sites/build
POST /api/sites/deploy
POST /api/upload
```

### 5.2 文件上传也要带 token

Element Plus 的 `ElUpload` 不会自动使用 axios 拦截器。

因此上传组件需要显式传：

```text
Authorization: Bearer <token>
```

否则如果 `/api/upload` 受认证保护，图片上传也会 401。

### 5.3 后端保持接口受保护

如果智能建站是后台能力，建议从白名单中移除：

```text
/api/sites/build
/api/sites/deploy
```

并确保前端请求都带 token。

注意：如果短期不想动权限策略，也可以先保留白名单，但长期建议不要让部署接口公开。

### 5.4 登录态失效时给出明确提示

当前页面右侧只是停在 Ready，不容易知道原因。

建议前端在 401 时显示：

```text
登录已过期，请重新登录后生成预览
```

同时停止 loading，避免用户误以为是生成慢。

## 6. 可执行方案 B：公开建站方案

如果产品设计是“未登录也允许使用智能建站”，则采用公开接口方案。

后端白名单必须包含：

```text
/api/sites/build
/api/sites/deploy
/api/upload
```

静态资源前缀必须放行：

```text
/static
```

但这个方案有明显风险：

- 任何人都可以调用建站接口消耗服务器资源。
- 任何人都可以上传文件。
- 任何人都可以尝试部署到远程服务器或 OSS。
- 容易被刷接口。

如果采用公开方案，至少要补充：

1. 验证码。
2. IP 限流。
3. 文件大小限制。
4. 上传类型白名单。
5. 禁止公开保存 SFTP/OSS 密钥。
6. 发布接口仍建议需要登录。

因此公开方案只适合临时演示，不建议用于生产。

## 7. 服务器部署排查清单

### 7.1 确认服务器后端代码版本

检查服务器上的 `backend/middleware/auth_middleware.py` 是否包含：

```text
/api/sites/build
/api/sites/deploy
```

如果本地有、服务器没有，说明部署代码不是最新。

### 7.2 确认服务已重启

即使代码已经上传，如果后端进程或 Docker 容器没有重启，旧代码仍然生效。

需要确认：

```text
后端进程已重启
Docker 容器已重新 build 并启动
Nginx 配置已 reload
```

### 7.3 确认 Nginx 转发路径

推荐 Nginx 转发：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8001/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /static/ {
    proxy_pass http://127.0.0.1:8001/static/;
}
```

要避免把 `/api/sites/build` 转成 `/sites/build` 或 `/api/api/sites/build`。

### 7.4 确认前端环境变量

部署后的前端应使用正确的 API 地址：

```text
VITE_API_BASE_URL=/api
```

或者：

```text
VITE_API_BASE_URL=http://8.163.39.114/api
```

如果前端构建时写死了旧地址，需要重新 build 前端。

### 7.5 确认浏览器是否存在 token

在浏览器控制台检查：

```js
localStorage.getItem('autogeo_token')
```

如果为空：

1. 当前用户没有登录。
2. 登录态存储 key 不一致。
3. 401 拦截器清掉了 token。
4. 前端页面不走统一请求实例，导致 token 没有被带上。

## 8. 推荐落地顺序

### 第一阶段：快速恢复预览

1. 确认服务器白名单是否包含 `/api/sites/build`。
2. 如果缺失，先同步代码并重启后端。
3. 确认 `/static` 前缀可以访问。
4. 打开智能建站，确认 `/api/sites/build` 不再 401。

这一步可以先让右侧预览恢复。

### 第二阶段：统一认证方案

1. 明确智能建站是否必须登录。
2. 推荐选择登录态方案。
3. 前端智能建站所有 API 请求改走统一 API 封装。
4. 文件上传显式携带 `Authorization`。
5. 后端发布类接口保持认证保护。

### 第三阶段：完善错误体验

1. 401 时显示“登录已过期，请重新登录”。
2. 403 时显示“当前账号无权限使用智能建站”。
3. 500 时显示后端 detail，并记录日志。
4. 右侧预览区域显示具体失败原因，而不是一直 Ready。

## 9. 推荐最终策略

生产环境推荐：

```text
/api/sites/build     需要登录
/api/sites/deploy    需要登录
/api/upload          需要登录
/static/sites/       公开访问
/static/uploads/     公开访问
```

前端推荐：

```text
智能建站页面不要直接 import axios
统一使用 services/api/index.ts 中的请求实例
ElUpload 显式传 Authorization header
```

这样可以同时解决：

- 部署后 `/api/sites/build` 401。
- 右侧 iframe 不刷新。
- 上传图片失败。
- 发布接口安全性不足。
- 各页面请求行为不一致。

## 10. 结论

这次错误的直接原因是：

```text
POST /api/sites/build 返回 401，导致预览站点没有生成，右侧 iframe 没有可刷新的 URL。
```

核心优化方向是统一认证和统一请求封装。短期可以通过确认服务器白名单和重启服务恢复预览；长期应让智能建站 API 全部走统一 axios 实例并携带 JWT，同时保持 `/static/sites/` 公开访问。这样部署到服务器后，左侧配置修改才能稳定触发右侧预览刷新。
