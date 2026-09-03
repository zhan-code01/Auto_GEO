# -*- coding: utf-8 -*-
"""
今日头条 (头条号) CSS selectors - v1.0

头条号创作平台 (mp.toutiao.com/profile_v4/graphic/publish) 用的是字节跳动自研
byte-* 组件 + ProseMirror 富文本编辑器。

选择器容易因后台改版失效，所以多层备选。选择器来源：
  - 旧版 toutiao.py (v61.1) 沉淀的 DOM 结构
  - 字节 byte-design 通用 class 命名 (byte-input / byte-radio / byte-modal / byte-btn)
  - ProseMirror 编辑器通用结构

注意：头条后台 SPA 改版频繁，所有选择器都要配多层兜底 + DOM 评分兜底
      (见 toutiao.py 各步骤实现)。失败时统一落 debug 快照便于事后定位。
"""

# === 登录 ===
LOGIN_URL = "https://mp.toutiao.com/"
# URL 中出现这些片段视为"未登录/被踢到登录或安全验证流程"
LOGIN_URL_INDICATOR = [
    "passport",
    "login",
    "signin",
    "sso",
    "/auth/",
    "captcha",
    "verify",
    "security_check",
]
LOGIN_SUCCESS_ELEMENT = [
    '[class*="avatar"]',
    '[class*="user-info"]',
    '[class*="userName"]',
    '[class*="nickname"]',
    '[class*="account-info"]',
    '.header-user',
]

# === 发布入口 ===
# profile_v4 图文发布页（图文，非视频）
PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish?is_new_connect=0&is_new_user=0"

# === 编辑器就绪标识 ===
# 头条图文编辑器：byte-input 标题 + ProseMirror 正文，任一出现即视为编辑器已加载
EDITOR_READY_SELECTORS = [
    ".ProseMirror",
    'textarea.byte-input__inner',
    'div[data-placeholder*="标题"]',
    'div[data-placeholder*="请输入标题"]',
    '[class*="article-editor"] [contenteditable="true"]',
    ".ql-editor",
    '[contenteditable="true"]',
]

# === 干扰弹窗（新手引导 / 新功能提醒 / 活动浮层 / 手机验证引导）===
# 头条新版后台常弹不透明遮罩挡住发布按钮，需要移除/关闭
INTERFERENCE_REMOVE = [
    ".creation-helper",
    ".add-desktop-prepare",
    ".portal-container",
    ".guide-mask",
    ".byte-drawer__wrapper",
    '[class*="guide-mask"]',
]
INTERFERENCE_CLOSE_BTN = [
    'button:has-text("知道了")',
    'button:has-text("我知道了")',
    'button:has-text("知道了")',
    'button:has-text("完成")',
    'button:has-text("下一步")',
    'button:has-text("跳过")',
    'button:has-text("不用了")',
    'button:has-text("稍后再说")',
    'button:has-text("确定")',
    'button:has-text("关闭")',
    '.byte-icon--close',
    '[class*="modal"] [class*="close"]',
    '[aria-label="Close"]',
    '[aria-label="close"]',
]

# === 标题（头条标题限制 5-30 字）===
TITLE_INPUT = [
    'textarea[placeholder="请输入文章标题（2～30个字）"]',
    'input[placeholder="请输入文章标题（2～30个字）"]',
    'textarea[placeholder*="文章标题"]',
    'input[placeholder*="文章标题"]',
    # 当前版 byte-input 组件
    'textarea.byte-input__inner',
    '.title-input textarea',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    # V4 后台 data-placeholder 写法
    'div[data-placeholder="请输入标题（5-30个字）"]',
    'div[data-placeholder*="请输入标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    # 通用兜底
    'div[class*="title"] textarea',
    'div[class*="title"] input',
    '#title',
    'input[name="title"]',
]

# === 正文（ProseMirror 富文本编辑器）===
CONTENT_INPUT = [
    'div:has-text("请输入正文")',
    # ProseMirror（头条正文主编辑器，contenteditable）
    ".ProseMirror",
    # 通用富文本兜底
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][class*="article"]',
    "div[class*='editor'] [contenteditable='true']",
    ".ql-editor",
    '[contenteditable="true"]',
]

# === 正文配图 ===
# 头条正文是 ProseMirror，图片通过 paste(File) 注入，无独立 input；
# 这里保留备用选择器，供工具栏上传兜底
CONTENT_IMAGE_TOOLBAR_BTN = [
    'button[title*="图片"]',
    'div[title*="图片"]',
    '[class*="toolbar"] [class*="image"]',
]

# === 展示封面（底部"展示封面"区域，单图/三图）===
# "单图"单选按钮（展示封面默认三图，单图封面更稳）
COVER_SINGLE_RADIO = [
    'div:has-text("展示封面") .byte-radio:has-text("单图")',
    '.byte-radio:has-text("单图")',
    '[class*="cover"] [class*="radio"]:has-text("单图")',
    'text=单图',
]
# 封面添加入口（截图确认：预览区"+"图标 + 右下角"预览"文字，点击触发 file chooser）
COVER_ADD = [
    # 按"展示封面"标签区域内的可点击封面框定位
    'div:has-text("展示封面") [class*="cover"] [class*="add"]',
    '[class*="article-cover"] [class*="add"]',
    "div.article-cover-add",
    'div:has-text("展示封面") >> .article-cover-add',
    'div[class*="article-cover"] >> div:has-text("+")',
    '[class*="cover-add"]',
    '[class*="cover"] [class*="upload"]',
    # "预览"文字所在的预览区（点击触发上传）
    '[class*="cover"]:has-text("预览")',
]
COVER_FILE_INPUT = 'input[type="file"][accept*="image"]'
COVER_ALL_FILE_INPUT = 'input[type="file"]'
COVER_CONFIRM = [
    'button:has-text("完成")',
    'button:has-text("确定")',
    'button:has-text("确认")',
    '.byte-btn-primary:has-text("完成")',
]
COVER_SUCCESS_INDICATOR = [
    ".article-cover-preview",
    'div:has-text("展示封面") >> .article-cover-preview',
    'img[class*="article-cover"]',
    'img[src*="toutiao"]',
    "text=替换",
    "text=更换",
    'div[class*="cover-preview"]',
]

# === AI 内容声明（头条号有"内容由 AI 生成"声明选项，位置随版本变化）===
AI_DECLARATION_LABELS = [
    "内容由 AI 生成",
    "AI 生成",
    "人工智能生成",
    "声明为 AI 生成",
]

# === 发布按钮 ===
PUBLISH_BUTTON = [
    # 头条图文发布主按钮文本"预览并发布"
    'button:has-text("预览并发布")',
    'button.byte-btn-primary:has-text("预览并发布")',
    'button[class*="primary"]:has-text("预览并发布")',
    # 某些版本直接是"发布"
    'button.byte-btn-primary:has-text("发布")',
    'button[class*="primary"]:has-text("发布")',
    'button:has-text("发布")',
    'button[class*="publish"]',
    'button[class*="submit"]',
    '[class*="publish"]:has-text("发布")',
    'button[type="submit"]:has-text("发布")',
]

# === 发布二次确认（手机预览弹窗的"确认发布"）===
PUBLISH_CONFIRM = [
    'button:has-text("确认发布")',
    'button:has-text("确认发布")',
    'button:has-text("确定发布")',
    'button:has-text("继续发布")',
    '.byte-modal__footer button:has-text("确认发布")',
    '.byte-modal__footer button.byte-btn-primary',
    'button:has-text("确认")',
    'button:has-text("确定")',
]

# === 发布成功 ===
SUCCESS_INDICATOR = [
    "text=发布成功",
    "text=提交成功",
    "text=审核中",
    "text=已发布",
    '[class*="success"]',
    ".publish-success",
]
# 发布成功后 URL 通常跳转到内容管理 / 文章列表
SUCCESS_URL_PATTERN = r"(articles|content_manage|content|graphic/home|manage|home)"

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
