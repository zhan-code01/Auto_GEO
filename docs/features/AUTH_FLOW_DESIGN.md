# 账号授权功能改进方案

**版本**: v2.1
**日期**: 2025-01-09
**状态**: ✅ 已实施

---

## 一、需求概述

### 当前问题
- 授权依赖自动检测登录状态，平台改版可能失效
- 用户无法主动控制授权时机
- 登录检测可能误判

### 目标
实现**手动点击"授权完成"按钮**的授权流程，包含完善的失败处理机制。

---

## 二、新授权流程

```
┌─────────────────────────────────────────────────────────────────┐
│  前端界面                                                       │
│                                                               │
│  [点击"去授权"]                                               │
│  ↓                                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Playwright 浏览器窗口 (独立窗口)                       │   │
│  │                                                          │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ 平台登录页 (知乎/百家号/搜狐/头条的登录页)       │   │   │
│  │  │                                                  │   │   │
│  │  │  [输入账号密码] / [扫码] / [输入验证码]          │   │   │
│  │  │                                                  │   │   │
│  │  │  用户手动完成登录流程                             │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │                                                          │   │
│  │  [✓ 授权完成] ← 注入的悬浮按钮 (右上角)                 │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                               │
│  [用户点击"授权完成"]                                         │
│  ↓                                                             │
│  后端提取 cookie/storage_state → 保存到数据库                    │
│  ↓                                                             │
│  浏览器自动关闭 → 前端显示"授权成功"                             │
│                                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、核心实现：方案A - 注入悬浮按钮

### 3.1 注入按钮代码

**文件**: `backend/services/playwright_mgr.py`

```python
async def _inject_auth_button(self, page: Page, task_id: str):
    """注入授权完成悬浮按钮"""
    button_html = """
    <div id="auto-geo-auth-btn" style="
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 999999;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        cursor: pointer;
        font-family: Arial, sans-serif;
        font-size: 14px;
        font-weight: bold;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        transition: all 0.3s;
    ">
        ✓ 授权完成
    </div>
    <script>
    (function() {
        const btn = document.getElementById('auto-geo-auth-btn');
        if (btn) {
            btn.onclick = function() {
                btn.textContent = '正在保存...';
                btn.style.pointerEvents = 'none';

                fetch('http://127.0.0.1:8000/api/accounts/auth/confirm/' + '%s', {
                    method: 'POST',
                    mode: 'cors'
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        btn.textContent = '✓ 授权成功！';
                        btn.style.background = '#4caf50';
                        setTimeout(() => window.close(), 1000);
                    } else {
                        btn.textContent = '✗ ' + (data.message || '失败 - 重试');
                        btn.style.background = '#f44336';
                        btn.style.pointerEvents = 'auto';
                    }
                })
                .catch(err => {
                    btn.textContent = '✗ 网络错误 - 重试';
                    btn.style.background = '#f44336';
                    btn.style.pointerEvents = 'auto';
                });
            };
        }
    })();
    </script>
    """ % task_id

    await page.evaluate(button_html)
```

### 3.2 新增确认授权 API

**文件**: `backend/api/account.py`

```python
@router.post("/auth/confirm/{task_id}", response_model=ApiResponse)
async def confirm_auth(task_id: str, db: Session = Depends(get_db)):
    """
    用户手动确认授权完成

    开发者我提取当前浏览器的 cookie 和 storage！
    """
    task = playwright_mgr.get_auth_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="授权任务不存在")

    if task.status == "success":
        return ApiResponse(success=True, message="授权已完成")

    # 提取当前页面状态
    cookies = await task.context.cookies()
    storage_state = await task.page.evaluate("""
        () => {
            return {
                localStorage: {...localStorage},
                sessionStorage: {...sessionStorage}
            };
        }
    """) or {}

    # 验证是否真的登录了（简单检查：是否有有效cookie）
    if not cookies or len(cookies) < 3:
        return ApiResponse(success=False, message="未检测到登录信息，请先在平台完成登录")

    # 保存到数据库
    try:
        from services.crypto import encrypt_cookies, encrypt_storage_state
        from database.models import Account

        if task.account_id:
            # 更新现有账号
            account = db.query(Account).filter(Account.id == task.account_id).first()
            if account:
                account.cookies = encrypt_cookies(cookies)
                account.storage_state = encrypt_storage_state(storage_state)
                account.status = 1
                account.last_auth_time = task.created_at
        else:
            # 创建新账号
            account_name = task.account_name or f"{PLATFORMS[task.platform]['name']}账号"
            account = Account(
                platform=task.platform,
                account_name=account_name,
                cookies=encrypt_cookies(cookies),
                storage_state=encrypt_storage_state(storage_state),
                status=1,
                last_auth_time=task.created_at
            )
            db.add(account)

        db.commit()
        task.status = "success"
        task.cookies = cookies
        task.storage_state = storage_state

        logger.info(f"授权确认成功: {task_id}")

        return ApiResponse(success=True, message="授权成功！账号已保存")

    except Exception as e:
        logger.error(f"授权确认失败: {e}")
        db.rollback()
        return ApiResponse(success=False, message=f"保存失败: {str(e)}")
```

---

## 四、失败处理机制

### 4.1 按钮状态

| 状态 | 显示文字 | 背景色 | 可点击 |
|-----|---------|-------|-------|
| 初始 | ✓ 授权完成 | 紫色渐变 | 是 |
| 保存中 | 正在保存... | 橙色 | 否 |
| 成功 | ✓ 授权成功！ | 绿色 | 否 (1秒后关闭窗口) |
| 失败 | ✗ 失败 - 重试 | 红色 | 是 |
| 未登录 | ⚠ 请先登录 | 橙色 | 是 |

### 4.2 失败场景处理

| 失败场景 | 检测方式 | 处理方式 |
|---------|---------|---------|
| 未登录就点击 | cookies < 3 | 提示"未检测到登录信息"，可重试 |
| 网络请求失败 | fetch catch | 提示"网络错误 - 重试" |
| 保存数据库失败 | API 返回 error | 提示具体错误信息，可重试 |
| 平台页面加载失败 | goto 异常 | 前端显示错误，提供重试 |
| 超时未操作 | 5分钟无操作 | 自动关闭窗口 |

---

## 五、修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `backend/services/playwright_mgr.py` | 1. 添加 `_inject_auth_button` 方法<br>2. 修改 `create_auth_task` 调用注入方法<br>3. 移除 `_check_login_status` 自动检测逻辑 |
| `backend/api/account.py` | 1. 新增 `confirm_auth` API 端点 |
| `backend/schemas/__init__.py` | 无需修改 (ApiResponse 已存在) |
| `frontend/src/views/account/AccountList.vue` | 1. 修改授权流程，移除自动轮询<br>2. 添加授权进行中状态显示 |
| `frontend/src/stores/modules/account.ts` | 简化授权逻辑，移除自动保存调用 |

---

## 六、验证步骤

### 6.1 正常流程测试

1. 点击"添加账号" → 选择平台 → 输入账号名称
2. 点击"去授权登录"
3. 浏览器窗口打开，右上角显示"✓ 授权完成"按钮
4. 在登录页完成登录（扫码/密码/验证码等）
5. 点击"授权完成"按钮
6. 按钮变为"正在保存..."
7. 保存成功后按钮变为"✓ 授权成功！"
8. 浏览器窗口自动关闭
9. 前端账号列表刷新，新账号出现

### 6.2 失败场景测试

1. **不登录直接点击完成** → 按钮提示"未检测到登录信息"
2. **网络断开后点击** → 按钮显示"网络错误 - 重试"
3. **超时未操作** → 5分钟后窗口自动关闭

---

## 七、特殊场景说明

### 7.1 手机验证码登录
- 在真实浏览器中输入手机号获取验证码
- 输入验证码完成登录
- 点击"授权完成"按钮

### 7.2 二维码扫码登录
- 平台显示二维码
- 手机扫码确认
- 浏览器自动跳转
- 点击"授权完成"按钮

### 7.3 账号已登录状态
- 打开页面时账号已经是登录状态
- 直接点击"授权完成"按钮
- 后端提取当前 cookie 并保存

---

**开发者备注**: 这个方案的核心是把控制权交给用户，不再依赖不可靠的自动检测！
