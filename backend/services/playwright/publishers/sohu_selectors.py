# -*- coding: utf-8 -*-
"""
搜狐号 CSS selectors - v1.0

搜狐号创作后台 (mp.sohu.com/mpfe/v4/...) 用的是 Vue + Element UI (mp-/el- 前缀)
+ Quill 富文本编辑器 (.ql-editor)。

选择器来源：
  - 旧版 sohu.py (v18.6) 沉淀的 DOM 结构 (firstpage -> 点"发布内容" -> 图文编辑器)
  - Element UI 通用 class 命名 (el-dialog / el-button / el-radio)
  - Quill 编辑器通用结构 (.ql-editor / .ql-toolbar)

注意：搜狐后台改版较多，所有选择器都配多层兜底，失败时统一落 debug 快照
      (backend/debug/sohu/) 便于事后定位。
"""

# === 登录 ===
LOGIN_URL = "https://mp.sohu.com/"
# URL 中出现这些片段视为"未登录/被踢到登录或安全验证流程"
LOGIN_URL_INDICATOR = [
    "passport",
    "login",
    "signin",
    "sso",
    "/auth/",
    "captcha",
    "verify",
    "security",
]
LOGIN_SUCCESS_ELEMENT = [
    '[class*="avatar"]',
    '[class*="user-info"]',
    '[class*="userName"]',
    '[class*="nickname"]',
    '[class*="account"]',
    ".header-user",
]

# === 发布入口 ===
# 搜狐号后台首页（内容管理 firstpage），登录后导航到这里，再点"发布内容"进图文编辑器
PUBLISH_URL = "https://mp.sohu.com/mpfe/v4/contentManagement/firstpage"
# firstpage 上"发布内容"按钮（多文案/多结构兜底）
PUBLISH_ENTRY_BUTTON = [
    'button:has-text("发布内容")',
    'span:has-text("发布内容")',
    'a:has-text("发布内容")',
    '[class*="publish"]:has-text("发布")',
    'li:has-text("发布内容")',
]

# === 编辑器就绪标识 ===
# 搜狐号图文编辑器：input 标题 + Quill 正文 (.ql-editor)
EDITOR_READY_SELECTORS = [
    ".ql-editor",
    'input[placeholder*="标题"]',
    'input[placeholder="请输入标题（5-72字）"]',
    '[class*="title"] input',
    '[contenteditable="true"]',
]

# === 干扰弹窗（新手引导 / 活动浮层 / 引导遮罩）===
# 搜狐后台用 introjs 新手引导 + Element 遮罩，会挡住编辑器和发布按钮
INTERFERENCE_REMOVE = [
    ".introjs-overlay",
    ".introjs-helperLayer",
    ".introjs-fixedTooltip",
    ".wp-guide-mask",
    ".p-guide",
    ".v-modal",
    ".el-overlay",
    '[class*="guide-mask"]',
    '[class*="introjs"]',
]
INTERFERENCE_CLOSE_BTN = [
    'button:has-text("知道了")',
    'button:has-text("我知道了")',
    'button:has-text("完成")',
    'button:has-text("下一步")',
    'button:has-text("跳过")',
    'button:has-text("不用了")',
    'button:has-text("稍后再说")',
    'button:has-text("确定")',
    'button:has-text("关闭")',
    ".introjs-skipbutton",
    ".el-icon--close",
    '[class*="modal"] [class*="close"]',
    '[aria-label="Close"]',
    '[aria-label="close"]',
]

# === 标题（搜狐号标题限制 5-72 字）===
TITLE_INPUT = [
    # 当前版 input（v18.6 实践值）
    'input[placeholder="请输入标题（5-72字）"]',
    'input[placeholder*="5-72"]',
    'input[placeholder*="标题"]',
    # 通用兜底
    'input[class*="title"]',
    'div[class*="title"] input',
    "#title",
    'input[name="title"]',
]

# === 正文（Quill 富文本编辑器）===
# 搜狐号正文是 Quill，.ql-editor 是 contenteditable；文字/图片都通过 paste 事件注入
CONTENT_EDITOR = [
    ".ql-editor",
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][class*="content"]',
    "div[class*='editor'] [contenteditable='true']",
    '[contenteditable="true"]',
]
CONTENT_EDITOR_PRIMARY = ".ql-editor"  # 主注入目标

# === 展示封面 ===
# 搜狐号封面是一个独立上传区（非正文内），点"+"图标/区域触发上传弹窗
COVER_ADD_ICON = [
    "i.iconfont.mp-icon-upload",
    ".upload-file i.iconfont",
    'i[class*="iconfont"][class*="upload"]',
    '[class*="cover"] [class*="iconfont"]',
]
COVER_ADD_AREA = [
    "div.upload-file.mp-upload",
    ".upload-file",
    '[class*="cover"] [class*="upload"]',
    '[class*="cover-add"]',
]
# 封面上传弹窗（Element / 搜狐自研 mp-dialog）
COVER_DIALOG = ".mp-dialog, .el-dialog"
COVER_FILE_INPUT = [
    '.mp-dialog input[type="file"]',
    '.el-dialog input[type="file"]',
    'input[type="file"]',
]
# 弹窗"本地上传"Tab（按文本定位，data-v 属性不稳定）
COVER_LOCAL_TAB_TEXT = "本地上传"
COVER_CONFIRM = [
    'button:has-text("完成")',
    'button:has-text("确定")',
    'button:has-text("确认")',
    '.el-button--primary:has-text("确定")',
    '.mp-dialog button:has-text("确定")',
    '.el-dialog button:has-text("确定")',
]
COVER_SUCCESS_INDICATOR = [
    # 封面预览图出现 / upload-tip 消失 / 出现"替换"/"删除"按钮
    "div.upload-file.mp-upload img",
    'div[class*="cover"] img',
    "text=替换",
    "text=更换",
    "text=重新上传",
]

# === AI 内容声明（位置随版本变化，失败不阻断）===
AI_DECLARATION_LABELS = [
    "内容由 AI 生成",
    "AI 生成",
    "人工智能生成",
    "声明为 AI 生成",
]

# === 发布按钮 ===
# 搜狐号图文发布主按钮：li.publish-report-btn（v18.6 实践值）+ 文案兜底
PUBLISH_BUTTON = [
    'li.publish-report-btn:has-text("发布")',
    'li.publish-report-btn.active.positive-button:has-text("发布")',
    'button:has-text("发布")',
    'button[class*="primary"]:has-text("发布")',
    'button[class*="publish"]',
    '[class*="publish"]:has-text("发布")',
]
# 发布时要排除的干扰文案按钮（定时发布 / 发布设置 等）
PUBLISH_BUTTON_EXCLUDE_TEXT = [
    "定时发布",
    "发布设置",
    "发布视频",
    "发布图文",
    "存为草稿",
    "保存草稿",
]

# === 发布二次确认弹窗 ===
PUBLISH_CONFIRM = [
    'button:has-text("确认发布")',
    'button:has-text("确定发布")',
    'button:has-text("继续发布")',
    'button:has-text("确认")',
    'button:has-text("确定")',
    '.el-button--primary:has-text("确认")',
    '.mp-dialog button:has-text("确认")',
]

# === 发布成功 ===
SUCCESS_INDICATOR = [
    "text=发布成功",
    "text=提交成功",
    "text=审核中",
    "text=已发布",
    '[class*="success"]',
]
# 发布成功后 URL 通常跳转回内容管理 / 文章列表
SUCCESS_URL_PATTERN = r"(contentManagement|articleList|article_list|manage|home|list)"

# === 发布失败 / 内容校验提示 ===
PUBLISH_FAIL_INDICATORS = [
    "text=发布失败",
    "text=内容违规",
    "text=包含敏感词",
    "text=不符合规范",
    "text=请设置封面",
    "text=请选择封面",
    "text=请输入标题",
    "text=请输入正文",
    "text=正文不能为空",
    "text=标题字数",
    "text=上传失败",
    "text=不能为空",
]

# === 限流 / 风控 / 安全验证 ===
CAPTCHA_INDICATOR = 'div:has-text("安全验证"), [class*="captcha"], [class*="verify"]'
RATE_LIMIT_INDICATORS = [
    "text=频率过高",
    "text=操作频繁",
    "text=今日已达上限",
    "text=请稍后再试",
    "text=发布次数已达",
]
