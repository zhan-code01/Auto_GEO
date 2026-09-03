# 智能建站发布模块错误分析与最终优化方案

## 1. 背景与目标

当前智能建站在“发布上线配置”中支持两种发布方式：

- 远程服务器 (SFTP)
- 云对象存储 (OSS/S3)

截图中的直接错误是：

```text
POST /api/sites/deploy 500 Internal Server Error
```

Electron 的 CSP 警告、Tailwind CDN 警告不是这次发布失败的主因。真正的问题在后端 `/api/sites/deploy` 发布链路：上传、权限、访问 URL 生成、服务器响应头或云存储响应头任一环节出错，都会被统一包装成 500。

最终目标：

1. 点击“确认发布”后，前端直接打开一个浏览器可访问的网页 URL。
2. 不把生成网页作为下载文件交付。
3. SFTP 和 OSS/S3 都返回可浏览 URL，而不是本地文件路径或附件下载链接。
4. 后端返回明确错误原因，避免所有失败都变成泛化 500。
5. 前端表单提前校验，减少错误配置。

## 2. 当前代码链路

前端入口：

```text
frontend/src/views/site-builder/ConfigWizard.vue
```

当前发布成功后已有打开逻辑：

```js
if (res.data.code === 200) {
  if (res.data.data && res.data.data.url) window.open(res.data.data.url, '_blank');
}
```

后端入口：

```text
backend/api/site_builder.py
```

发布服务：

```text
backend/services/deploy_service.py
```

当前 SFTP 逻辑：

1. 根据 `site_id` 找到 `backend/static/sites/{site_id}`。
2. 使用 Paramiko 连接远程服务器。
3. 上传整个站点目录到 `{remote_root}/{folder_name}`。
4. 如果填写 `custom_domain`，返回 `{custom_domain}/{folder_name}/index.html`。
5. 如果未填写 `custom_domain`，返回 `http://{host}/{folder_name}/index.html`。

当前 OSS/S3 逻辑：

1. 根据 `site_id` 找到本地站点目录。
2. 使用 boto3 创建 S3 client。
3. 遍历上传所有文件。
4. 每个对象设置 `ContentType` 和 `ACL=public-read`。
5. 拼接 `index.html` 对象 URL 返回前端。

## 3. 主要问题判断

### 3.1 500 只是表象

`backend/api/site_builder.py` 当前会把所有异常都变成 500：

```python
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

所以这些问题都会表现为同一个 500：

- SFTP 服务器无法连接。
- SSH 账号密码错误。
- 远程目录不存在或没有写权限。
- Nginx root 与上传目录不一致。
- 防火墙未开放 HTTP/HTTPS 端口。
- 返回 URL 拼错。
- OSS/S3 Endpoint、Bucket、AccessKey 或 SecretKey 错误。
- OSS/S3 Bucket 不允许公开访问。
- `index.html` 响应头导致浏览器下载而不是渲染。

### 3.2 SFTP 上传成功不等于网页可访问

SFTP 只是“把文件传到服务器”。浏览器能否打开网页，还依赖 Web 服务配置，例如 Nginx：

```nginx
server {
    listen 80;
    server_name example.com;
    root /var/www/html;
    index index.html;
}
```

如果代码上传到 `/var/www/html/demo/index.html`，浏览器 URL 应该是：

```text
http://example.com/demo/index.html
```

如果 Nginx root 实际是 `/usr/share/nginx/html`，但前端填写上传路径 `/var/www/html`，文件虽然传上去了，浏览器也看不到。

### 3.3 SFTP 返回 URL 需要使用“访问域名”，不是 SSH 主机

当前未填写 `custom_domain` 时返回：

```text
http://{host}/{folder_name}/index.html
```

这有几个风险：

- SSH 主机 IP 不一定是公网访问 IP。
- 服务器可能只开放 443，不开放 80。
- 网站可能绑定了域名或 CDN，而不是裸 IP。
- Web root 与 SFTP 上传路径可能不一致。

因此 SFTP 也必须有一个明确字段：

```text
public_base_url
```

例如：

```text
https://www.example.com
```

发布成功后返回：

```text
https://www.example.com/demo/index.html
```

### 3.4 SFTP 服务器也可能导致下载

正常 Nginx/Apache 会把 `.html` 按 `text/html` 返回并在浏览器渲染。但如果服务器配置了错误的 MIME 类型或附件响应头，浏览器会下载。

需要确认：

```text
Content-Type: text/html
Content-Disposition: inline 或不设置
```

如果响应头是：

```text
Content-Disposition: attachment
```

浏览器就会下载。

### 3.5 OSS/S3 的对象元数据也会导致下载

OSS/S3 上传 `index.html` 时必须设置：

```text
Content-Type: text/html; charset=utf-8
Content-Disposition: inline
```

否则对象访问可能被浏览器当作下载文件。

## 4. 后端通用优化方案

### 4.1 统一发布结果模型

建议 SFTP 和 OSS/S3 都返回同一结构：

```json
{
  "status": "success",
  "message": "发布成功",
  "url": "https://www.example.com/demo/index.html",
  "entry": "index.html",
  "uploaded_files": 12,
  "target_path": "/var/www/html/demo"
}
```

前端只依赖 `data.url` 打开浏览器。

### 4.2 统一新增字段 `public_base_url`

建议把原来的 `custom_domain` 升级为更明确的字段：

```text
public_base_url
```

兼容策略：

- 后端先读取 `public_base_url`。
- 如果没有，再兼容旧字段 `custom_domain`。
- 两者都没有时，SFTP 才兜底使用 `http://{sftp_host}`。

### 4.3 站点路径统一加 slug

当前 `_sanitize_name(project_name)` 会把项目名转为安全目录名，这是对的，但需要兜底：

```text
folder_name = sanitize(project_name) or site_id[:8]
```

避免项目名全是中文或特殊字符时生成空目录名。

更稳的目录规则：

```text
{project_slug}-{site_id[:8]}
```

例如：

```text
turbo_logistics-2f37a443
```

这样可以避免不同项目重名覆盖。

### 4.4 错误码不要全部返回 500

建议定义自定义异常或错误映射：

| 场景 | 状态码 | 错误提示 |
| --- | --- | --- |
| 参数缺失 | 400 | 发布配置不完整 |
| 站点目录不存在 | 404 | 站点预览已失效，请重新生成 |
| SFTP 认证失败 | 401 | SFTP 用户名或密码错误 |
| SFTP 无写权限 | 403 | 上传目录没有写权限 |
| SFTP 连接失败 | 502 | 无法连接远程服务器 |
| OSS 凭证错误 | 401/403 | OSS 凭证无效或权限不足 |
| Bucket/Endpoint 错误 | 400/404 | Bucket 与 Endpoint 不匹配 |
| 上传成功但访问检测失败 | 502 | 文件已上传，但网页 URL 无法访问 |

## 5. SFTP 最终优化方案

### 5.1 前端表单字段

SFTP 表单建议调整为：

```text
SSH 主机: sftp_host
SSH 端口: sftp_port
用户名: sftp_user
密码: sftp_pass
上传路径: sftp_path
访问域名: public_base_url
站点目录名: publish_slug，可选
```

字段说明：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `sftp_host` | `1.2.3.4` | SSH/SFTP 连接地址 |
| `sftp_port` | `22` | SSH 端口 |
| `sftp_user` | `root` 或 `www` | 远程用户 |
| `sftp_pass` | `******` | 登录密码 |
| `sftp_path` | `/var/www/html` | Nginx/Apache 可访问的 Web root |
| `public_base_url` | `https://www.example.com` | 浏览器访问域名 |
| `publish_slug` | `turbo-logistics` | 可选，自定义发布目录 |

前端校验：

- SFTP 模式下 `sftp_host`、`sftp_port`、`sftp_user`、`sftp_pass`、`sftp_path` 必填。
- 强烈建议 `public_base_url` 必填。
- `public_base_url` 必须以 `http://` 或 `https://` 开头。
- `sftp_path` 必须是绝对路径，例如 `/var/www/html`。

### 5.2 后端上传流程

推荐流程：

1. 校验参数。
2. 生成安全发布目录名。
3. 连接 SFTP。
4. 确认远程根目录存在。
5. 创建目标目录。
6. 递归上传文件。
7. 对 HTML/CSS/JS/图片设置合理文件权限。
8. 关闭连接。
9. 拼接浏览器访问 URL。
10. 可选：后端请求一次 URL 做访问检测。

### 5.3 远程目录创建要递归

当前 `_upload_dir()` 只在当前层级 `mkdir`，如果父目录不存在会失败。

建议增加 `ensure_remote_dir(sftp, path)`：

```python
def ensure_remote_dir(sftp, remote_dir):
    parts = [p for p in remote_dir.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current += f"/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)
```

这样 `/var/www/html/demo` 的任意层级缺失都可以自动创建。

### 5.4 文件权限建议

上传后建议设置：

```text
目录: 755
文件: 644
```

原因：

- Nginx/Apache 需要读权限。
- 不应该给网页文件可执行权限。

示例：

```python
sftp.chmod(remote_dir, 0o755)
sftp.chmod(remote_file, 0o644)
```

### 5.5 URL 生成规则

后端统一生成：

```text
{public_base_url}/{folder_name}/index.html
```

规则：

- `public_base_url` 去掉末尾 `/`。
- `folder_name` 使用安全 slug。
- 永远返回 `index.html` 的 HTTP/HTTPS URL。
- 不返回 SFTP 路径。
- 不返回本地文件下载地址。

示例：

```text
public_base_url = https://www.example.com
folder_name = turbo-logistics-2f37a443
url = https://www.example.com/turbo-logistics-2f37a443/index.html
```

### 5.6 访问检测

发布完成后建议用后端 `httpx.head()` 或 `httpx.get()` 检测返回 URL：

检查项：

- HTTP 状态码是 200。
- `Content-Type` 包含 `text/html`。
- `Content-Disposition` 不包含 `attachment`。

如果上传成功但访问失败，返回：

```text
文件已上传到服务器，但访问 URL 无法打开。请检查 Nginx root、域名解析、防火墙和 public_base_url。
```

如果发现下载响应头，返回：

```text
文件已上传，但服务器返回 Content-Disposition: attachment，请调整 Nginx/Apache 响应头为 inline。
```

### 5.7 推荐 Nginx 配置

如果 `sftp_path=/var/www/html`，推荐配置：

```nginx
server {
    listen 80;
    server_name example.com;

    root /var/www/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    types {
        text/html html htm;
        text/css css;
        application/javascript js;
        image/png png;
        image/jpeg jpg jpeg;
        image/svg+xml svg;
        image/webp webp;
    }

    default_type application/octet-stream;
}
```

如果发布目录是 `/var/www/html/turbo-logistics-2f37a443/index.html`，访问地址就是：

```text
http://example.com/turbo-logistics-2f37a443/index.html
```

HTTPS 场景推荐：

```text
public_base_url = https://example.com
```

### 5.8 SFTP 常见错误与提示

| 错误 | 原因 | 修复 |
| --- | --- | --- |
| Authentication failed | 用户名或密码错误 | 检查 SSH 账号 |
| Permission denied | 上传目录无写权限 | 换目录或调整权限 |
| No such file | 父目录不存在 | 后端递归创建目录 |
| 上传成功但打不开 | Nginx root 不匹配 | 确认 `sftp_path` 是 Web root |
| 打开变下载 | MIME 或响应头错误 | 设置 `Content-Type: text/html`，不要设置 attachment |
| 返回 404 | URL 拼接或域名配置错 | 检查 `public_base_url` 和目录名 |

## 6. OSS/S3 最终优化方案

### 6.1 前端表单字段

OSS/S3 表单建议为：

```text
Endpoint
Bucket
AccessKey
SecretKey
Region，可选
访问域名 public_base_url
是否使用对象 ACL use_public_acl
```

示例：

```text
Endpoint: https://oss-cn-shenzhen.aliyuncs.com
Bucket: autogeoext
访问域名: https://autogeoext.oss-cn-shenzhen.aliyuncs.com
```

如果已绑定 CDN 或自定义域名：

```text
访问域名: https://www.example.com
```

### 6.2 不默认使用 `ACL=public-read`

当前固定上传：

```python
ExtraArgs={"ContentType": content_type, "ACL": "public-read"}
```

建议改为：

```python
ExtraArgs={
    "ContentType": content_type,
    "ContentDisposition": "inline",
}
```

只有用户显式开启对象 ACL 时才追加：

```python
ExtraArgs["ACL"] = "public-read"
```

### 6.3 设置正确对象元数据

上传时明确设置：

| 文件类型 | Content-Type | Content-Disposition |
| --- | --- | --- |
| `.html` | `text/html; charset=utf-8` | `inline` |
| `.css` | `text/css; charset=utf-8` | `inline` |
| `.js` | `application/javascript; charset=utf-8` | `inline` |
| 图片 | 对应 image 类型 | `inline` |

这样访问 `index.html` 时浏览器会渲染页面，而不是下载。

### 6.4 访问 URL 优先级

后端返回 URL 的优先级：

1. 用户填写的 `public_base_url`。
2. Bucket 静态网站托管域名。
3. 对象访问 URL。

最终返回：

```text
{public_base_url}/index.html
```

或者带发布目录：

```text
{public_base_url}/{folder_name}/index.html
```

### 6.5 阿里云 OSS 配置建议

建议在 OSS 控制台完成：

1. Bucket 区域与 Endpoint 保持一致，例如深圳区域：

```text
https://oss-cn-shenzhen.aliyuncs.com
```

2. 开启静态网站托管：

```text
默认首页: index.html
默认 404: index.html 或 404.html
```

3. 配置 Bucket Policy 或 CDN 回源策略，让网页资源可读。
4. 如果 Bucket 禁止 ACL，不要传 `ACL=public-read`。
5. 确认 `index.html` 响应头：

```text
Content-Type: text/html; charset=utf-8
Content-Disposition: inline
```

## 7. 前端交互优化

### 7.1 发布按钮逻辑

点击“确认发布”后：

1. 前端校验当前 tab 对应字段。
2. 调用 `POST /api/sites/deploy`。
3. 后端返回 `data.url`。
4. 前端优先 `window.open(data.url, '_blank')`。
5. 如果弹窗被拦截，在弹窗内显示“打开站点”按钮和 URL。

### 7.2 成功提示

建议替换为：

```text
发布成功，已生成可访问网页
```

同时显示：

```text
打开站点
复制链接
```

### 7.3 错误提示

前端继续读取：

```js
error.response?.data?.detail
```

但后端应返回结构化 detail：

```json
{
  "code": "SFTP_WEB_URL_NOT_ACCESSIBLE",
  "message": "文件已上传，但网页 URL 无法访问。",
  "suggestion": "请检查 public_base_url、Nginx root、防火墙和域名解析。"
}
```

前端展示 `message`，并把 `suggestion` 放在详情或二级提示中。

## 8. 推荐接口返回格式

成功：

```json
{
  "code": 200,
  "data": {
    "status": "success",
    "method": "sftp",
    "url": "https://www.example.com/turbo-logistics-2f37a443/index.html",
    "entry": "index.html",
    "uploaded_files": 12,
    "target_path": "/var/www/html/turbo-logistics-2f37a443",
    "message": "发布成功"
  }
}
```

失败：

```json
{
  "detail": {
    "code": "SFTP_PERMISSION_DENIED",
    "message": "远程上传目录没有写权限。",
    "suggestion": "请确认 SFTP 用户可以写入 /var/www/html，或改用有权限的上传路径。"
  }
}
```

OSS/S3 ACL 失败：

```json
{
  "detail": {
    "code": "OSS_BUCKET_ACL_DISABLED",
    "message": "Bucket 禁用了对象 ACL，请关闭公开 ACL 上传。",
    "suggestion": "改用 Bucket Policy、静态网站托管或 CDN 公开访问。"
  }
}
```

## 9. 实施顺序

### 第一阶段：快速修复

1. SFTP 增加 `public_base_url` 字段，并优先用它生成浏览器访问 URL。
2. SFTP 发布目录增加 `site_id` 后缀，避免重名覆盖。
3. SFTP 递归创建远程目录，上传后设置目录 755、文件 644。
4. SFTP 发布后可选检测 URL，确认 `Content-Type` 是 `text/html` 且不是下载响应。
5. OSS/S3 移除默认 `ACL=public-read`。
6. OSS/S3 上传时设置 `ContentDisposition=inline` 和正确 `Content-Type`。
7. 后端错误改成结构化 detail，不再所有异常都返回泛化 500。

### 第二阶段：体验优化

1. 前端发布弹窗按 tab 做字段校验。
2. 发布成功后显示“打开站点”和“复制链接”。
3. 如果浏览器拦截 `window.open`，保留可点击链接。
4. 增加“测试连接”按钮：
   - SFTP 测试 SSH 登录和上传目录权限。
   - OSS/S3 测试 Bucket、Endpoint、凭证和写权限。

### 第三阶段：产品化增强

1. 保存发布配置，避免重复输入。
2. SecretKey 和 SFTP 密码加密存储，不在前端回显明文。
3. 增加发布历史、发布版本、回滚能力。
4. 支持自定义发布路径前缀。
5. 支持 CDN 缓存刷新。

## 10. 最终结论

本模块要修的不是“下载按钮”，而是完整发布链路。SFTP 和 OSS/S3 都必须把生成站点发布到一个 Web 服务可以读取的位置，并返回 HTTP/HTTPS URL。

SFTP 的关键是：上传路径必须对应 Nginx/Apache 的 Web root，返回 URL 必须使用 `public_base_url`，并确认服务器用 `text/html` 渲染 `index.html`。

OSS/S3 的关键是：对象要有正确 `Content-Type` 和 `Content-Disposition=inline`，不要默认强制 `public-read ACL`，并优先返回静态网站域名、自定义域名或 CDN 域名。

这样点击“确认发布”后，用户看到的是浏览器直接打开的网页，而不是下载文件，也不是一个无法访问的服务器路径。
