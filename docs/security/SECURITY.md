# AutoGeo 安全配置说明

> **开发者提醒**：安全不是儿戏！认真读这篇文档！

---

## 1. 加密机制

### 1.1 加密算法

| 项目 | 说明 |
|-----|------|
| **算法** | AES-256 (Fernet) |
| **密钥派生** | PBKDF2HMAC + SHA256 |
| **迭代次数** | 100,000 |
| **盐值** | `auto_geo_salt` (固定，生产环境建议修改) |

### 1.2 加密内容

系统自动加密以下敏感数据并存储到数据库：

- **Cookies** - 用户登录后的浏览器Cookie
- **Storage State** - localStorage 和 sessionStorage 数据

```
原始数据 → JSON序列化 → AES-256加密 → Base64编码 → 数据库
```

### 1.3 代码位置

- 加密服务：`backend/services/crypto.py`
- 密钥配置：`backend/config.py:44-47`
- 存储调用：`backend/api/account.py:255-256`

---

## 2. 加密密钥配置

### 2.1 环境变量

```bash
AUTO_GEO_ENCRYPTION_KEY=your-32-byte-encryption-key-here
```

### 2.2 生成密钥

**方法 1：使用 Python secrets 模块（推荐）**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**方法 2：使用 OpenSSL**
```bash
openssl rand -base64 32
```

**方法 3：手动输入**
- 长度至少 32 个字符
- 包含大小写字母、数字、特殊符号
- 例如：`My-Super-Secret-Key-32-Chars-Long!!`

### 2.3 配置步骤

1. **复制环境变量模板**
   ```bash
   cp .env.example .env
   ```

2. **编辑 .env 文件，填入密钥**
   ```bash
   AUTO_GEO_ENCRYPTION_KEY=你生成的32字节密钥
   ```

3. **重启后端服务**
   ```bash
   cd backend
   python main.py
   ```

---

## 3. 安全注意事项

### ⚠️ 重要警告

1. **生产环境必须设置自定义密钥**
   - 默认密钥硬编码在代码中，任何人都能解密你的数据！
   - 一旦设置密钥，不要轻易更改，否则已加密的数据无法解密！

2. **密钥丢失的后果**
   - 所有已保存的账号 Cookies 将无法解密
   - 用户需要重新进行授权登录

3. **.env 文件管理**
   - `.env` 已加入 `.gitignore`，不会被提交到 git
   - 生产环境部署时确保 `.env` 文件权限正确

4. **数据库备份**
   - 定期备份数据库文件
   - 备份文件同样需要加密存储

---

## 4. .gitignore 已排除

以下敏感文件/目录不会被提交到 git：

| 项目 | 说明 |
|-----|------|
| `.env` | 环境变量配置 |
| `.cookies/` | Cookie 存储目录 |
| `*.db` | 数据库文件 |
| `browser_context/` | 浏览器上下文 |
| `logs/` | 日志文件 |

---

## 5. 故障排查

### 问题：已授权账号显示未授权

**可能原因**：加密密钥发生了变化

**解决方案**：
1. 检查 `.env` 文件中的 `AUTO_GEO_ENCRYPTION_KEY` 是否一致
2. 如果密钥确实改变了，需要重新对所有账号进行授权

### 问题：启动报错 "Key derivation failed"

**可能原因**：密钥格式不正确

**解决方案**：
1. 确保密钥是有效的 ASCII/UTF-8 字符串
2. 密钥长度至少 32 字节
3. 不要使用包含换行符的密钥

---

**开发者备注**：安全无小事，该配置的配置好，别到时候数据泄露了怪开发者没提醒你！
