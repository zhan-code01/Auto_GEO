# B站 & 百家号 GEO 图文发布方案

> 版本: v1.0  
> 日期: 2026-06-08  
> 适用项目: Auto-GEO 自动发布系统

---

## 目录

- [1. 背景与结论](#1-背景与结论)
- [2. 平台 API 支持情况](#2-平台-api-支持情况)
- [3. 开源参考方案](#3-开源参考方案)
- [4. B站专栏发布方案](#4-b站专栏发布方案)
- [5. 百家号图文发布方案](#5-百家号图文发布方案)
- [6. 方案架构对比](#6-方案架构对比)
- [7. 使用指南](#7-使用指南)
- [8. 注意事项与风险](#8-注意事项与风险)

---

## 1. 背景与结论

### 1.1 需求

GEO 文章自动生成后，需要快速发布到 B站专栏 和 百家号。

### 1.2 结论

**两个平台都没有公开的图文发布 API，必须走 Playwright 浏览器自动化路线。**

本项目的实现状态：

| 平台 | 文件 | 版本 | 状态 |
|------|------|------|------|
| **B站专栏** | `backend/services/playwright/publishers/bilibili.py` | v2.0 | ✅ 可直接使用 |
| **B站选择器** | `backend/services/playwright/publishers/bilibili_selectors.py` | v2.0 | ✅ 可直接使用 |
| **百家号** | `backend/services/playwright/publishers/baijiahao.py` | v17.0 | ✅ 可直接使用 |
| **百家号选择器** | `backend/services/playwright/publishers/baijiahao_selectors.py` | v1.0 | ✅ 选择器参考库 |

---

## 2. 平台 API 支持情况

### 2.1 九大内容平台 API 对比

| 平台 | 官方发布 API | 认证门槛 | 个人可用 | 适合 API 直发 |
|------|:--:|:--:|:--:|:--:|
| **知乎** | ✅ 完整 | 低 | ✅ | ⭐⭐⭐ |
| **微博** | ✅ 长文 | 中 | ✅ (需审核) | ⭐⭐ |
| **小红书** | ⚠️ 有 | 高 | ❌ 企业 only | ⭐ |
| **抖音** | ⚠️ 视频 | 中高 | ❌ 企业 | ⭐ |
| **B站** | ❌ 无 | — | — | ❌ |
| **百家号** | ❌ 无 | — | — | ❌ |
| **搜狐号** | ❌ 无 | — | — | ❌ |
| **头条号** | ❌ 无 | — | — | ❌ |
| **快手** | ❌ 无 | — | — | ❌ |

### 2.2 B站开放平台

- **地址**: [openhome.bilibili.com](https://openhome.bilibili.com)
- **现状**: 主要面向游戏/直播/电商场景
- **专栏 API**: **不对外开放**，只能通过网页端发布
- **替代方案**: Playwright 浏览器自动化模拟人工操作

### 2.3 百家号开放平台

- 百度百家号**没有面向开发者的文章发布 API**
- 只能通过网页端 `baijiahao.baidu.com/builder` 手动发布
- **替代方案**: Playwright 浏览器自动化模拟人工操作

---

## 3. 开源参考方案

### 3.1 参考项目总览

| 项目 | GitHub | Stars | 技术栈 | 类型 | B站 | 百家号 |
|------|--------|-------|--------|------|:---:|:---:|
| **social-auto-upload** | dreammis/social-auto-upload | ⭐12,400+ | Python + Playwright | 视频向 | ✅ | ✅ |
| **MPP (MediaPublishPlatform)** | funfan0517/MediaPublishPlatform | ⭐109 | Python + Playwright + Vue | 图文+视频 | ✅ | ✅ |
| **COSE** | doocs/cose | ⭐653 | JavaScript (Chrome扩展) | 图文 | ✅ | ✅ |
| **PostBot** | gitcoffee-os/postbot | — | 浏览器扩展 | 图文+视频 | ✅ | ✅ |
| **TurboPush** | xueyc1f/turbopush-website | — | Tauri + React | 图文+视频 | ✅ | ✅ |

### 3.2 各项目参考价值

**social-auto-upload**（主要参考）:
- 社区最大，12,400+ stars
- Cookie 持久化（storage_state）机制成熟
- 百家号上传流程（`uploader/baijiahao_uploader/main.py`）经过大量用户验证
- 异步重试装饰器 `@async_retry` 保证稳定性
- 不足：视频向为主，图文能力弱

**MPP (MediaPublishPlatform)**（selector 参考）:
- 基于 social-auto-upload 二次开发，补了图文能力
- `platform_configs.py` 提供最详细的 CSS + XPath 选择器
- B站和百家号的 selector 非常精确，经过 DOM 验证
- MIT 许可证，可直接复用

**COSE**（DOM 策略参考）:
- Chrome 扩展，30+ 平台
- 本地运行，不上传数据
- 策略参考：自动检测登录态、标签页分组
- 适合作为日常手动发布的工具

### 3.3 借鉴的核心技术点

1. **Cookie 持久化**: `storage_state` JSON 文件，一次登录长期复用
2. **多层选择器**: CSS + XPath 双保险，每个关键元素 3-5 个备选
3. **三级兜底策略**: 常规方法 → JS增强 → 强制注入
4. **异步重试**: 上传/发布等关键操作带超时重试
5. **频率控制**: 防止触发平台风控
6. **干扰清理**: 自动关闭弹窗、引导、遮罩层

---

## 4. B站专栏发布方案

### 4.1 发布流程

```
┌────────────────────────────────────────────────────────────┐
│  B站专栏发布流程 (bilibili.py v2.0)                         │
│                                                            │
│  Step 0:  _check_rate_limit()     ← 🆕 频率控制             │
│  Step 1:  _navigate_to_editor()   ← 导航到编辑器             │
│  Step 2:  _ensure_logged_in()     ← 🆕 双重登录检测          │
│  Step 3:  _close_interference()   ← 🆕 关闭干扰弹窗          │
│  Step 4:  _download_cover()       ← 🆕 双源备用封面          │
│  Step 5:  _fill_title()           ← 增强选择器               │
│  Step 6:  _fill_content()         ← 🆕 三级兜底策略          │
│  Step 7:  _upload_cover()         ← 🆕 状态确认+重试         │
│  Step 8:  _add_tags()             ← 标签                     │
│  Step 9:  _set_category()         ← 🆕 分类设置              │
│  Step 10: _set_ai_declaration()   ← AI声明                   │
│  Step 11: _click_publish()        ← 🆕 多级确认弹窗          │
│  Step 12: _wait_for_result()      ← 🆕 限流实时检测          │
└────────────────────────────────────────────────────────────┘
```

### 4.2 v2.0 相比 v1.0 的改进

| # | 改进点 | 说明 | 参考来源 |
|---|--------|------|----------|
| 1 | **频率控制** | 每小时≤5篇，每24h≤15篇，间隔≥5分钟 | 知乎 `_check_rate_limit()` |
| 2 | **双重登录检测** | URL检查 + 页面用户元素验证 | social-auto-upload cookie验证 |
| 3 | **干扰弹窗关闭** | 自动关闭引导/活动弹窗，JS移除高z-index遮罩 | 百家号 `_smash_interferences()` |
| 4 | **URL从config读** | `self.config["publish_url"]` 替代硬编码 | 项目BasePublisher模式 |
| 5 | **封面备用源** | pollinations.ai → picsum 双重保障 | toutiao.py 多级备用策略 |
| 6 | **三级兜底正文** | keyboard.type → textarea.fill → JS注入 | MPP + social-auto-upload |
| 7 | **封面状态确认** | 上传后检查预览图/替换按钮 | MPP thumbnail_finish selector |
| 8 | **多级确认弹窗** | 循环处理最多3层确认弹窗 | toutiao.py 循环确认逻辑 |
| 9 | **限流检测** | 实时检测"频率过高"等提示并立即中止 | 知乎限流检测 |

### 4.3 Selector 策略

每个关键元素都有 CSS + XPath 双层备选：

```python
ARTICLE_TITLE_INPUT = [
    # MPP 精确选择器
    'input.input-val[type="text"][placeholder*="标题"]',
    # 通用选择器
    'input[placeholder*="标题"]',
    '.article-title input',
    'input[class*="title"]',
    # XPath 备选
    'xpath=//input[@placeholder[contains(., "标题")]]',
]
```

### 4.4 核心代码入口

```python
from backend.services.playwright.publishers.base import registry

# 获取B站发布器
publisher = registry.get("bilibili")

# 发布文章
result = await publisher.publish(
    page=page,           # Playwright Page对象
    article=article,     # 文章对象 (title, content)
    account=account,     # 账号对象
    declare_ai_content=True  # 是否声明AI创作
)
# 返回: {"success": True/False, "platform_url": "...", "error_msg": "..."}
```

---

## 5. 百家号图文发布方案

### 5.1 发布流程

```
┌────────────────────────────────────────────────────────────┐
│  百家号图文发布流程 (baijiahao.py v17.0)                     │
│                                                            │
│  Step 1:  _inject_stealth_vaccine()  ← 💉 反检测疫苗        │
│  Step 2:  _navigate_to_editor()      ← 导航到编辑器          │
│  Step 3:  _smash_interferences()     ← 🧹 Shadow DOM清场     │
│  Step 4:  _download_relevant_images()← 📷 下载4张AI图片      │
│  Step 5:  _split_content_to_chunks() ← ✂️ 正文分4块          │
│  Step 6:  _physical_upload_cover()   ← 🎯 DNA锚点封面        │
│  Step 7:  _inject_content_with_images()← 🖼️ 文字图片交叉     │
│  Step 8:  _physical_write_title()    ← 📝 execCommand标题    │
│  Step 9:  _reconfirm_cover()         ← 🔄 封面二次确认       │
│  Step 10: _physical_publish()        ← 🚀 发布+确认          │
│  Step 11: _wait_for_publish_result() ← ⏳ 等待结果           │
│                                                            │
│  特色: 封面先行 → 正文 → 标题 (百家号特有的"倒序"策略)       │
└────────────────────────────────────────────────────────────┘
```

### 5.2 核心技术

#### 5.2.1 隐身疫苗（反检测）

```python
async def _inject_stealth_vaccine(self, page: Page):
    await page.add_init_script("""() => {
        // 覆盖 webdriver 标记
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        // 伪造 Chrome 运行时环境
        window.chrome = {
            runtime: {},
            loadTimes: Date.now,
            csi: () => {},
            app: {}
        };
        // 跳过百家号新手引导
        localStorage.setItem('BAIDU_BJ_GUIDE_STATE', 'true');
        localStorage.setItem('BJ_TOUR_COMPLETED', 'true');
    }""")
```

#### 5.2.2 iframe 编辑器穿透

百家号的正文编辑器在 iframe 内部，需要先定位 iframe，再通过 `content_frame()` 获取：

```python
# 遍历所有iframe找到 contenteditable 区域
for i in range(iframes):
    iframe_locator = page.locator("iframe").nth(i)
    iframe_element = await iframe_locator.element_handle()
    frame = await iframe_element.content_frame()
    has_editor = await frame.evaluate("""() => {
        return document.querySelector('[contenteditable="true"]') !== null;
    }""")
```

#### 5.2.3 DataTransfer 图片注入

不通过 `input[type=file]`，而是将图片 Base64 编码后通过剪贴板事件注入：

```python
await frame.evaluate("""(b64) => {
    const byteCharacters = atob(b64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const dt = new DataTransfer();
    dt.items.add(new File(
        [new Uint8Array(byteNumbers)], "img.jpg",
        { type: 'image/jpeg' }
    ));
    const ce = document.querySelector('[contenteditable="true"]');
    ce.dispatchEvent(new ClipboardEvent('paste', {
        clipboardData: dt, bubbles: true
    }));
}""", b64)
```

#### 5.2.4 DNA 锚点封面

百家号封面区域有独特的 CSS class（哈希值），必须在弹窗中选择"本地上传"：

```python
# 定位 DNA 锚点
target = page.locator("div._73a3a52aab7e3a36-content").last
await target.click(force=True)

# 等待弹窗 → 点击"本地上传"
async with page.expect_file_chooser(timeout=5000) as fc_info:
    # 点击"本地上传"按钮
    local_btn = page.locator('div:has-text("本地上传")')
    await local_btn.click(force=True)
    file_chooser = await fc_info.value

# 注入文件
await file_chooser.set_files(image_path)
```

#### 5.2.5 Shadow DOM 穿透清场

百家号页面使用 Shadow DOM 封装组件，常规 `document.querySelectorAll` 无法穿透。使用递归遍历：

```python
await page.evaluate("""() => {
    function scanAndSmash(root) {
        root.querySelectorAll('*').forEach(el => {
            // 移除高 z-index 弹窗
            if (parseInt(getComputedStyle(el).zIndex) > 500) {
                el.remove();
            }
            // 递归进入 Shadow DOM
            if (el.shadowRoot) scanAndSmash(el.shadowRoot);
        });
    }
    scanAndSmash(document);
}""")
```

### 5.3 核心代码入口

```python
from backend.services.playwright.publishers.base import registry

# 获取百家号发布器
publisher = registry.get("baijiahao")

# 发布文章
result = await publisher.publish(
    page=page,
    article=article,
    account=account,
    declare_ai_content=True
)
# 返回: {"success": True/False, "platform_url": "...", "error_msg": "..."}
```

---

## 6. 方案架构对比

### 6.1 B站 v2.0 vs 百家号 v17.0

| 维度 | B站 bilibili.py v2.0 | 百家号 baijiahao.py v17.0 |
|------|---------------------|--------------------------|
| **代码行数** | ~310 行 | ~792 行 |
| **编辑器类型** | Quill.js 富文本 (`.ql-editor`) | iframe + contenteditable |
| **正文输入** | 三级兜底 (keyboard.type/fill/JS) | execCommand('insertHTML') |
| **图片插入** | input[type=file] | DataTransfer (ClipboardEvent) |
| **封面策略** | 上传后确认 | DNA锚点 + 文件选择器 |
| **弹窗清理** | 选择器按钮 + JS z-index | Shadow DOM穿透 + 暴力移除 |
| **反检测** | 无 | 隐身疫苗 (webdriver/navigator覆盖) |
| **频率控制** | ✅ 5次/时, 15次/天 | ❌ 待添加 |
| **限流检测** | ✅ 实时检测 | ⚠️ 仅安全验证检测 |
| **发布顺序** | 标题→内容→封面→发布 | 封面→内容→标题→发布（倒序） |
| **选择器管理** | 独立 selectors 文件 | 硬编码在代码中 |

### 6.2 共同遵循的架构

```
BasePublisher (base.py)
  ├── platform_id: str
  ├── config: Dict
  └── publish(page, article, account) → Dict
        │
        ├── BilibiliPublisher (bilibili.py)
        ├── BaijiahaoPublisher (baijiahao.py)
        ├── ZhihuPublisher (zhihu.py)
        ├── ToutiaoPublisher (toutiao.py)
        └── ... 其他平台
```

---

## 7. 使用指南

### 7.1 前置条件

1. **B站账号**: 已在浏览器中登录 B站创作中心
2. **百家号账号**: 已在浏览器中登录百家号
3. **Cookie 持久化**: 确保 `storage_state` 已保存（通过 `PlaywrightManager` 管理）

### 7.2 配置检查

在 `backend/config.py` 中确认平台配置：

```python
# B站
"bilibili": {
    "id": "bilibili",
    "name": "B站专栏",
    "code": "BL",
    "login_url": "https://passport.bilibili.com/login",
    "publish_url": "https://member.bilibili.com/platform/upload/text/new-article",
    "color": "#FB7299",
},

# 百家号
"baijiahao": {
    "id": "baijiahao",
    "name": "百家号",
    "code": "BJH",
    "login_url": "https://baijiahao.baidu.com/builder/rc/static/login/index",
    "publish_url": "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1",
    "color": "#2932E1",
},
```

### 7.3 注册确认

在 `backend/services/playwright/publishers/__init__.py` 中确认已导入：

```python
from .bilibili import BilibiliPublisher
from .baijiahao import BaijiahaoPublisher
```

### 7.4 快速手动发布（COSE 浏览器扩展）

如果只是临时需要手动发布几篇文章，可以直接使用 COSE：

1. 安装 [COSE Chrome 扩展](https://md.doocs.org)
2. 打开 `md.doocs.org` 编辑器
3. 粘贴 Markdown 内容
4. 勾选 "B站专栏" 和 "百家号"
5. 点击发布

---

## 8. 注意事项与风险

### 8.1 浏览器自动化风险

| 风险 | 等级 | 应对措施 |
|------|:----:|----------|
| DOM 变化导致选择器失效 | 🔴 高 | 多层选择器备选 + XPath 兜底 |
| 平台安全验证（滑块/点选） | 🟡 中 | 实时检测 + 人工介入 |
| 频率限制 / 风控 | 🟡 中 | 内置频率控制 + 发布间隔 |
| Cookie 过期 | 🟡 中 | storage_state 持久化 + 登录检测 |
| 平台改版（URL变化） | 🟢 低 | 从 config 读取 URL |

### 8.2 登录态管理

- B站和百家号都使用 Cookie 方式维持登录态
- 首次使用需要手动扫码登录
- `PlaywrightManager` 负责 `storage_state` 的保存和恢复
- 如果登录态失效，会自动检测并抛出异常

### 8.3 内容合规

- B站专栏有审核机制，发布后需要等待审核
- 百家号文章也会经过内容审核
- AI 声明有助于合规（默认开启）
- 避免发布违规内容，否则可能触发限流或封号

### 8.4 Selector 维护

百家号使用自研 cheetah 组件（React 渲染），CSS class 名包含哈希值（如 `_73a3a52aab7e3a36-content`），容易因版本更新失效。建议：

1. 定期检查选择器有效性
2. 使用 XPath 作为稳定备选
3. 关注 MPP 项目的 `platform_configs.py` 更新

---

## 附录

### A. 相关文件清单

```
backend/services/playwright/publishers/
├── base.py                   # 发布器基类 (ABC)
├── __init__.py               # 注册所有发布器
├── bilibili.py               # B站专栏 v2.0 ⭐
├── bilibili_selectors.py     # B站选择器 v2.0 ⭐
├── baijiahao.py              # 百家号 v17.0 ⭐
├── baijiahao_selectors.py    # 百家号选择器 v1.0 ⭐ (参考库)
├── zhihu.py                  # 知乎
├── toutiao.py                # 今日头条
├── xiaohongshu.py            # 小红书
├── douyin.py                 # 抖音
├── kuaishou.py               # 快手
├── weibo.py                  # 微博
├── sohu.py                   # 搜狐号
└── note_utils.py             # 笔记工具函数

backend/config.py              # 平台配置
backend/services/playwright_mgr.py  # Playwright管理器
backend/services/playwright/humanize.py  # 人类化操作模拟
```

### B. 参考来源

| 参考 | 链接 | 借鉴内容 |
|------|------|----------|
| social-auto-upload | [github.com/dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload) | Cookie管理、重试机制、登录流程 |
| MPP | [github.com/funfan0517/MediaPublishPlatform](https://github.com/funfan0517/MediaPublishPlatform) | Selector配置、百家号图文支持 |
| COSE | [github.com/doocs/cose](https://github.com/doocs/cose) | 多平台DOM策略、扩展架构 |
| B站开放平台 | [openhome.bilibili.com](https://openhome.bilibili.com) | 官方API文档（确认专栏API不对外开放） |
| 百家号 | [baijiahao.baidu.com](https://baijiahao.baidu.com) | 网页端发布流程 |
