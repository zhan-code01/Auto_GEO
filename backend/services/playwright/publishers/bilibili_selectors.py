# -*- coding: utf-8 -*-
"""
B站专栏 CSS/XPath selectors - v3.0 增强版

B站创作中心已多次改版，selectors 需要同时覆盖新旧两套 UI：
  - 旧版: Quill.js 编辑器 (`.ql-editor`)
  - 新版: 自研编辑器 (可能的 class 名)

参考来源：
  - MPP (MediaPublishPlatform) platform_configs.py
  - social-auto-upload bilibili uploader
  - COSE browser extension injector
"""

# ═══════════════════════════════════════════════════════════
# 登录态检测
# ═══════════════════════════════════════════════════════════

LOGIN_URL_INDICATOR = [
    "login",
    "passport",
    "signin",
    "account.bilibili.com",
]

LOGIN_SUCCESS_ELEMENT = [
    # B站创作中心 header 中的用户信息
    '.header-avatar-wrap',
    '.header-login-panel__avatar',
    '.user-con',
    '[class*="user-avatar"]',
    '[class*="avatar"][class*="header"]',
    '.bili-avatar',
    # 用户名/昵称
    '[class*="user-name"]',
    '[class*="userName"]',
    '.username-text',
    '.user-nick',
    '.nickname',
    # 创作中心header
    '.creator-header .avatar',
    '.m-header-avatar',
    # 更多通用元素
    'img[class*="avatar"]',
    '[class*="Avatar"]',
    '[class*="logoFace"]',
]

# ═══════════════════════════════════════════════════════════
# 干扰弹窗
# ═══════════════════════════════════════════════════════════

INTERFERENCE_POPUPS = [
    'div[class*="modal"]:visible',
    'div[class*="popup"]:visible',
    'div[class*="guide"]:visible',
    'div[class*="mask"]:visible',
    '.bili-modal__wrapper',
    '[class*="dialog"]:visible',
    '[class*="notice"]:visible',
]

CLOSE_POPUP_BTN = [
    'button:has-text("知道了")',
    'button:has-text("我知道了")',
    'button:has-text("关闭")',
    'button:has-text("跳过")',
    'button:has-text("下一步")',
    'button:has-text("完成")',
    'button:has-text("立即体验")',
    'button:has-text("开始体验")',
    'button:has-text("不用了")',
    'button:has-text("稍后再说")',
    'div:has-text("知道了")',
    'div:has-text("我知道了")',
    'div:has-text("下一步")',
    'span:has-text("知道了")',
    'span:has-text("我知道了")',
    'span:has-text("下一步")',
    '.close-btn',
    '[class*="close"]',
    '.bili-modal__close',
    'span[class*="close"]',
    'i[class*="close"]',
    '[class*="dialog-close"]',
    '.el-icon-close',
]

# ═══════════════════════════════════════════════════════════
# 专栏编辑器 URL
# ═══════════════════════════════════════════════════════════

# 按优先级排列：新 → 旧
ARTICLE_EDITOR_URLS = [
    # 新版创作中心专栏编辑（2024+）
    "https://member.bilibili.com/platform/upload-text/edit",
    # 旧版专栏编辑器入口
    "https://member.bilibili.com/platform/upload/text/edit",
    # 最旧版
    "https://member.bilibili.com/article-editor",
    "https://member.bilibili.com/article/post_text",
]

# 专栏"新建/新的创作"入口
NEW_ARTICLE_BUTTON = [
    'a:has-text("专栏投稿")',
    'a:has-text("专栏")',
    'button:has-text("新的创作")',
    'button:has-text("新建创作")',
    'button:has-text("开始创作")',
    'button:has-text("写专栏")',
    'button:has-text("发布专栏")',
    'a:has-text("新的创作")',
    'a:has-text("写文章")',
    'text=新的创作',
    'text=新建创作',
    '[class*="new"]:has-text("创作")',
    '[class*="create-btn"]',
    '.create-article-btn',
]

# ═══════════════════════════════════════════════════════════
# 标题输入（新旧编辑器兼容）
# ═══════════════════════════════════════════════════════════

ARTICLE_TITLE_INPUT = [
    # Codegen observed in the iframe editor
    'input[placeholder="请输入标题（建议30字以内）"]',
    'textarea[placeholder="请输入标题（建议30字以内）"]',
    # 新版选择器
    'input[placeholder*="请输入文章标题"]',
    'input[placeholder*="输入文章标题"]',
    'input[placeholder*="文章标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    '[contenteditable="true"][placeholder*="标题"]',
    # 旧版 MPP 选择器
    'input.input-val[type="text"][placeholder*="标题"]',
    'input[placeholder*="请输入标题"]',
    'input[placeholder*="标题"]',
    '.article-title input',
    '.article-title [contenteditable="true"]',
    'input[class*="title"]',
    'textarea[placeholder*="标题"]',
    # 通用
    '[data-placeholder*="标题"]',
    # XPath 备选
    'xpath=//input[@placeholder[contains(., "标题")]]',
    'xpath=//textarea[@placeholder[contains(., "标题")]]',
    'xpath=//*[@data-placeholder[contains(., "标题")]]',
]

# ═══════════════════════════════════════════════════════════
# 正文输入（富文本编辑器 — 新旧兼容）
# ═══════════════════════════════════════════════════════════

ARTICLE_CONTENT_INPUT = [
    # 新版 B站 自研编辑器（可能是 class 名）
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][placeholder*="正文"]',
    '[contenteditable="true"][data-placeholder*="内容"]',
    '[contenteditable="true"][placeholder*="内容"]',
    # 新版通用 contenteditable
    '.editor-body [contenteditable="true"]',
    '.article-content [contenteditable="true"]',
    '.content-editor [contenteditable="true"]',
    # 旧版 Quill.js
    'div.ql-editor.ql-blank[contenteditable="true"]',
    'div.ql-editor[contenteditable="true"]',
    '.ql-editor',
    # ProseMirror / TipTap (新版可能使用)
    '.ProseMirror[contenteditable="true"]',
    '.tiptap[contenteditable="true"]',
    '[contenteditable="true"]',
    # 备选
    '.editor-body',
    '.article-editor-body',
    # XPath
    'xpath=//div[contains(@class, "ql-editor")]',
    'xpath=//*[@contenteditable="true" and contains(@data-placeholder, "正文")]',
    'xpath=//*[@contenteditable="true" and contains(@data-placeholder, "内容")]',
]

# ═══════════════════════════════════════════════════════════
# 封面上传
# ═══════════════════════════════════════════════════════════

COVER_UPLOAD_AREA = [
    '.cover-upload-area',
    'div[class*="cover"]',
    '.article-cover',
    '[class*="cover-wrap"]',
    '[class*="cover-upload"]',
]

COVER_FILE_INPUT = [
    'input[type="file"][accept*="image"]',
    'input[type="file"][accept*=".jpg"]',
    'input[type="file"][accept*=".png"]',
    'input[type="file"]',
]

COVER_UPLOAD_BTN = [
    'span:has-text("上传封面")',
    'div:has-text("上传封面")',
    'button:has-text("上传封面")',
    'div:has-text("封面")',
    'button:has-text("添加封面")',
    'button:has-text("更换封面")',
    'div[class*="cover-upload"]',
    'div[class*="cover"] >> text=上传',
    '[class*="add-cover"]',
    '.cover-add-btn',
]

COVER_SUCCESS_INDICATOR = [
    'img[class*="cover"]',
    'img[class*="preview"]',
    '.cover-preview img',
    'div[class*="cover-preview"]',
    'text=替换',
    'text=更换',
    '[class*="cover-img"]',
    '[class*="cover-pic"]',
]

# ═══════════════════════════════════════════════════════════
# 标签输入
# ═══════════════════════════════════════════════════════════

PUBLISH_TAG_INPUT = [
    'input[placeholder*="标签"]',
    '.tag-input input',
    'input[placeholder*="话题"]',
    'input[class*="tag"]',
    'input[placeholder*="添加标签"]',
    'input[placeholder*="搜索标签"]',
    # XPath 备选
    'xpath=//input[@placeholder[contains(., "标签") or contains(., "话题")]]',
]

# ═══════════════════════════════════════════════════════════
# 分类选择
# ═══════════════════════════════════════════════════════════

CATEGORY_SELECTORS = [
    'div[class*="category"]',
    'select[class*="category"]',
    '.article-category',
    '[class*="category-select"]',
    '[class*="type-select"]',
]

# ═══════════════════════════════════════════════════════════
# AI声明/设置
# ═══════════════════════════════════════════════════════════

AI_DECLARATION_INDICATORS = [
    'text=AI声明',
    'text=AI辅助',
    'text=AI辅助创作声明',
    'text=声明',
    'text=AI生成',
    '[class*="declare"]',
    'label:has-text("AI")',
    'span:has-text("AI")',
]

AI_DECLARATION_CHECKBOX = [
    'input[type="checkbox"][id*="ai"]',
    'input[type="checkbox"][id*="declare"]',
    'input[type="checkbox"][name*="ai"]',
    '.ai-checkbox input',
    '[class*="declare"] input[type="checkbox"]',
]

PUBLISH_SETTINGS_TOGGLE = [
    'button:has-text("发布设置")',
    'text=发布设置',
    '[class*="setting"]:has-text("发布设置")',
    'div:has-text("发布设置")',
    '[class*="publish-setting"]',
]

# ═══════════════════════════════════════════════════════════
# 发布按钮（按优先级排列）
# ═══════════════════════════════════════════════════════════

# 编辑器上的发布按钮
ARTICLE_SUBMIT_BTN = [
    # Codegen observed in the iframe editor
    'button:has-text("发布")',
    # 最精确
    'button:has-text("立即投稿")',
    'span.submit-add:has-text("立即投稿")',
    # 专栏发布
    'button:has-text("发布文章")',
    'button:has-text("发布专栏")',
    # 通用发布
    '.publish-btn:has-text("发布")',
    '[class*="publish"]:has-text("发布")',
    'button:has-text("投稿")',
    'button[class*="submit"]',
    'button[class*="publish"]',
    # 更多变体
    '[class*="submit-btn"]',
    '.submit-btn',
    # XPath
    'xpath=//button[contains(., "发布") or contains(., "投稿")]',
    'xpath=//span[contains(., "发布") or contains(., "投稿")]',
]

# 弹窗/对话框中的确认发布按钮
PUBLISH_SUBMIT_BTN = [
    'button:has-text("确认发布")',
    'button:has-text("确定发布")',
    'button:has-text("确认投稿")',
    'button:has-text("确定投稿")',
    'button:has-text("确认")',
    'button:has-text("确定")',
    '.confirm-publish-btn',
    'button[class*="confirm"]',
]

# 发布确认弹窗专用（不应包含"发布"这种泛泛的词，否则会重新点击发布按钮）
CONFIRM_DIALOG_BTNS = [
    # 精确的确认按钮
    'button:has-text("确认发布")',
    'button:has-text("确定发布")',
    'button:has-text("确认投稿")',
    'button:has-text("确定投稿")',
    # 泛确认
    'button:has-text("确认")',
    'button:has-text("确定")',
    # 弹窗中的确认
    '.modal button:has-text("确认")',
    '.dialog button:has-text("确认")',
    '[class*="modal"] button:has-text("确定")',
    '[class*="dialog"] button:has-text("确定")',
]

# ═══════════════════════════════════════════════════════════
# 成功指示
# ═══════════════════════════════════════════════════════════

PUBLISH_SUCCESS_KEYWORDS = [
    "发布成功",
    "投稿成功",
    "提交成功",
    "已提交成功",
    "已发布",
    "文章发布",
    "专栏发布成功",
    "专栏已提交成功",
    "你的专栏已提交成功",
    "内容已提交",
]

PUBLISH_SUCCESS_ELEMENT = [
    '[class*="success"]',
    '[class*="finish"]',
    '.upload-success',
    '.publish-success',
    '[class*="result-success"]',
    '.result-success',
]

# ═══════════════════════════════════════════════════════════
# 限流/风控
# ═══════════════════════════════════════════════════════════

RATE_LIMIT_INDICATORS = [
    'text=频率过高',
    'text=操作频繁',
    'text=发布频率',
    'text=请稍后再试',
    'text=今日已达上限',
    'text=验证',
    'text=滑块',
    'text=人机验证',
    'text=安全验证',
]

# ═══════════════════════════════════════════════════════════
# 账号信息（认证用）
# ═══════════════════════════════════════════════════════════

ACCOUNT_NICKNAME = [
    '[class*="name"]',
    '[class*="nickname"]',
    '.username-text',
    '.user-nick',
]
ACCOUNT_FOLLOWER = '[class*="follower"], [class*="fans"]'
ACCOUNT_AVATAR = '[class*="avatar"] img'

# ═══════════════════════════════════════════════════════════
# 数据分析
# ═══════════════════════════════════════════════════════════

ANALYTICS_VIEWS = '[class*="play"], [class*="view"]'
ANALYTICS_LIKES = '[class*="like"], [class*="coin"]'
ANALYTICS_COMMENTS = '[class*="comment"], [class*="reply"]'
ANALYTICS_FAVORITES = '[class*="collect"], [class*="fav"]'
ANALYTICS_SHARES = '[class*="share"], [class*="forward"]'
ANALYTICS_COINS = '[class*="coin"]'
ANALYTICS_DANMAKU = '[class*="danmaku"], [class*="dm"]'
