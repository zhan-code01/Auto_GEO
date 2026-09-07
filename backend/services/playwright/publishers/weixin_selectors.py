# -*- coding: utf-8 -*-
"""
微信公众号 CSS/XPath selectors - v1.0

微信公众号后台 (mp.weixin.qq.com) 用的是 UEditor + 微信自研组件。
新版本在过渡到 Tiptap 编辑器，所以选择器需要多层兜底。

参考来源：
  - 微信公众号 2024-2026 后台 DOM 分析
  - social-auto-upload weixin_uploader
  - MPP platform_configs.py
"""

# === 登录 ===
LOGIN_URL_INDICATOR = [
    "mp.weixin.qq.com/cgi-bin/login",
    "mp.weixin.qq.com/cgi-bin/home?t=login",
    "/cgi-bin/loginpage",
    "wx2.qq.com/cgi-bin/login",
    "passport.weixin.qq.com",
]
LOGIN_QR_CODE = 'img[class*="qrcode"], .login__type__container__scan img'
LOGIN_SUCCESS_ELEMENT = [
    ".account_name",
    ".weui-desktop-account__name",
    "#nickname",
    ".nickname",
    '[class*="nickname"]',
    ".main_avatar",
    '[class*="avatar"]',
]

# === 编辑器入口（草稿箱 → 写新图文）===
DRAFT_BOX_URL = "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&lang=zh_CN"

NEW_ARTICLE_BTN = [
    'button:has-text("写新图文")',
    'a:has-text("写新图文")',
    '.weui-desktop-btn_primary:has-text("写新图文")',
    '[role="button"]:has-text("写新图文")',
    'div:has-text("写新图文")',
    "text=写新图文",
]

# 兜底入口：先点"图文消息"卡片，再点写新图文
IMAGE_ARTICLE_ENTRY = [
    'div:has-text("图文消息")',
    'a:has-text("图文消息")',
    '[class*="appmsg"]:has-text("图文")',
]

# === 干扰弹窗 ===
CLOSE_POPUP_BTN = [
    '.weui-desktop-dialog__btn:has-text("知道了")',
    ".weui-desktop-dialog__close",
    'button:has-text("知道了")',
    'button:has-text("我知道了")',
    'button:has-text("完成")',
    'button:has-text("下一步")',
    'button:has-text("跳过")',
    'button:has-text("关闭")',
    'button:has-text("确定")',
    '[class*="close"]',
    '[aria-label="Close"]',
    '[aria-label="close"]',
    'i[class*="close"]',
    'span[class*="close"]',
]

GUIDE_TEXT = [
    "知道了",
    "我知道了",
    "完成",
    "下一步",
    "跳过",
    "关闭",
    "稍后",
    "确定",
    "开始体验",
]

# === 标题 ===
TITLE_INPUT = [
    "#title",
    "textarea#title",
    'textarea[placeholder*="请输入标题"]',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    ".title-area textarea",
    ".title_input textarea",
    'div[class*="title"] textarea',
    'div[class*="title"] input',
    # 新版编辑器
    '[contenteditable="true"][data-placeholder*="标题"]',
    # XPath 兜底
    'xpath=//textarea[contains(@placeholder, "标题")]',
]

# === 正文（微信公众号 UEditor）===
CONTENT_INPUT = [
    "#ueditor_0",
    ".edui-body-container",
    "iframe#ueditor_0_iframe",
    ".editor_area",
    ".rich_media_editor",
    '[contenteditable="true"][class*="editor"]',
    'div[class*="editable"][contenteditable="true"]',
    # Tiptap 新版
    ".ProseMirror",
    # 通用兜底
    '[contenteditable="true"]',
]

# 内容区域的 placeholder 文本（用于 JS 兜底匹配）
CONTENT_PLACEHOLDER = [
    "请输入正文",
    "在此输入正文",
    "输入正文",
]

# === 封面 ===
COVER_BUTTON = [
    ".js_cover_area",
    ".appmsg-cover",
    ".weui-desktop-card__cover",
    'div:has-text("封面图片")',
    'button:has-text("从正文选择")',
    '[class*="cover-upload"]',
]

COVER_FILE_INPUT = [
    'input[type="file"][accept*="image"]',
    '.js_cover_upload input[type="file"]',
    '.appmsg-cover input[type="file"]',
    '.weui-desktop-card__cover input[type="file"]',
    'input[type="file"]',
]

COVER_CONFIRM = [
    'button:has-text("完成")',
    'button:has-text("确定")',
    ".weui-desktop-dialog__btn-primary",
    ".js_cover_done",
]

# 摘要（封面摘要，部分版本必填）
DIGEST_INPUT = [
    "#digest",
    "textarea#digest",
    'textarea[placeholder*="摘要"]',
    ".digest-area textarea",
]

# === 发布按钮 ===
PUBLISH_BUTTON = [
    "#js_send",
    'button:has-text("保存并群发")',
    'button:has-text("群发")',
    '.weui-desktop-btn_primary:has-text("群发")',
    'a:has-text("保存并群发")',
    '[role="button"]:has-text("群发")',
]

# 仅保存草稿（备用，主流程不用）
SAVE_DRAFT_BUTTON = [
    "#js_save",
    'button:has-text("保存")',
    'button:has-text("保存为草稿")',
]

# 二次确认弹窗
PUBLISH_CONFIRM = [
    'button:has-text("确定")',
    'button:has-text("确认群发")',
    ".weui-desktop-dialog__btn-primary",
    ".js_dialog_confirm",
    ".weui-desktop-modal__btn-primary",
]

# === 扫码/验证 ===
SCAN_QRCODE = [
    ".qrcode-layer",
    ".js_scan_qrcode",
    'canvas[class*="qr"]',
    'img[class*="qrcode"]',
    ".balloon",
]

CAPTCHA_INDICATOR = ".captcha-container, .weui-desktop-captcha"

# === 成功/失败提示 ===
SUCCESS_TEXT = [
    "群发成功",
    "发布成功",
    "已群发",
    "提交成功",
    "正在群发",
    "已发送",
    "图文消息列表",
]

FAIL_TEXT = [
    "发布失败",
    "群发失败",
    "内容违规",
    "请添加封面",
    "请上传封面",
    "请输入标题",
    "请输入正文",
    "敏感词",
    "频次过高",
    "超过限制",
    "操作频繁",
    "包含违法",
    "未通过审核",
]

# === URL 跳转检测 ===
SUCCESS_URL_PATTERNS = [
    r"appmsg_list",
    r"send_ok",
    r"success",
    r"history",
    r"card_list",
]
