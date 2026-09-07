# -*- coding: utf-8 -*-
"""
百家号 CSS/XPath selectors - v2.0

百家号用的是自研富文本编辑器 (cheetah 组件)，不是 Quill.js。
选择器容易因版本更新失效，所以多层备选。

参考来源：
  - MPP platform_configs.py (百家号字段完整定义)
  - social-auto-upload baijiahao_uploader
  - 百家号 2024-2026 创作中心 DOM 分析
"""

# === 登录 ===
LOGIN_URL = "https://baijiahao.baidu.com/builder/theme/bjh/login"
LOGIN_URL_INDICATOR = ["login", "passport", "theme/bjh", "passport.baidu.com"]
LOGIN_QR_CODE = 'img[class*="qrcode"], .qrcode-img, canvas[class*="qr"]'
LOGIN_SUCCESS_ELEMENT = [
    ".header-avatar",
    '[class*="avatar"]',
    ".user-info",
    ".user-name",
    '[class*="user-info"]',
    '[class*="userName"]',
    '[class*="nickname"]',
]

# === 创作中心/编辑器 ===
CREATOR_HOME = "https://baijiahao.baidu.com/builder/rc/home"
CREATOR_IMAGE_EDIT_URL = "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1"
CREATOR_VIDEO_URL = "https://baijiahao.baidu.com/builder/rc/edit?type=videoV2&is_from_cms=1"

# === 干扰弹窗 ===
HEALTH_CHECK_POPUP = [
    'div:has-text("内容健康度")',
    'div:has-text("健康度")',
    'div:has-text("温馨提示")',
]

IMAGE_ARTICLE_ENTRY = [
    'button:has-text("发布图文")',
    'a:has-text("发布图文")',
    '[role="button"]:has-text("发布图文")',
    'div:has-text("发布图文")',
    "text=发布图文",
]

CLOSE_POPUP_BTN = [
    ".cheetah-tour-footer button.cheetah-btn-primary",
    '.cheetah-tour-footer button:has-text("下一步")',
    '.cheetah-tour-footer button:has-text("完成")',
    ".cheetah-tour-close",
    '.cheetah-popover button:has-text("我知道了")',
    '.cheetah-popover button:has-text("知道了")',
    '.cheetah-popover button:has-text("完成")',
    'button:has-text("知道了")',
    'button:has-text("我知道了")',
    'button:has-text("关闭")',
    'button:has-text("确定")',
    'button:has-text("跳过")',
    'button:has-text("下一步")',
    'button:has-text("上一步")',
    'button:has-text("完成")',
    'button:has-text("不用了")',
    'div:has-text("知道了")',
    'div:has-text("我知道了")',
    'div:has-text("下一步")',
    'div:has-text("完成")',
    'span:has-text("知道了")',
    'span:has-text("我知道了")',
    'span:has-text("下一步")',
    'span:has-text("完成")',
    ".close-btn",
    '[class*="close"]',
    'span[class*="close"]',
    'i[class*="close"]',
]

# === 标题 ===
TITLE_INPUT = [
    # 当前版 (2026) Lexical 编辑器: contenteditable div
    '[data-lexical-editor="true"]',
    '[data-testid="news-title-input"] [contenteditable="true"]',
    'div[class*="titleInput"] [contenteditable="true"]',
    # 旧版兼容
    "#formMain > form > div.left-area-content-box > div:nth-child(2) > "
    "div.form-inner-wrap.tags-container.videov2-title-wrap > div > "
    "div.cheetah-public.cheetah-textArea > textarea",
    # 通用
    'textarea[placeholder*="请输入标题"]',
    'input[placeholder*="请输入标题"]',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    'div[class*="title"] textarea',
    'div[class*="title"] input',
    "#title",
    ".title-input textarea",
    # XPath
    'xpath=//textarea[contains(@placeholder, "标题")]',
    'xpath=//input[contains(@placeholder, "标题")]',
]

# === 正文 ===
CONTENT_INPUT = [
    # 当前版 (2026) UEditor: iframe 中的 contenteditable body
    "iframe#ueditor_0",
    "#ueditor",
    "#ueditorContainer",
    # 旧版兼容
    "#desc",
    'xpath=//textarea[@id="desc"]',
    # 通用富文本
    '[contenteditable="true"][data-placeholder*="请输入正文"]',
    '[contenteditable="true"][data-placeholder*="正文"]',
    'textarea[placeholder*="请输入正文"]',
    'textarea[placeholder*="正文"]',
    "div.editor-wrapper [contenteditable]",
    'div[class*="editor"] [contenteditable]',
    'div[class*="content"] [contenteditable]',
    ".ql-editor",
    '[contenteditable="true"]',
    # XPath
    'xpath=//textarea[@id="desc"]',
]

# === UEditor API ===
UEDITOR_API_REF = "UE_V2.instants['ueditorInstant0']"
UEDITOR_CONTAINER = "#edui1_iframeholder"
UEDITOR_IFRAME = "iframe#ueditor_0"

# === UEditor 图片插入（正文配图）===
# 工具栏「图片」按钮：UEditor 原生 class + cheetah 包装 + title 文本，多层兜底
UEDITOR_IMAGE_BUTTON = [
    ".edui-button-image",
    'div[class*="edui"][class*="image"]',
    '[data-id="image"]',
    '.edui-default .edui-toolbar [title*="图片"]',
    'div[title*="图片"]',
]
# 图片上传弹窗
UEDITOR_IMAGE_DIALOG = [
    ".edui-dialog",
    'div[class*="edui-dialog"]',
    'div[class*="dialog"]:has-text("图片")',
    '.cheetah-modal:has-text("插入图片")',
]
# 「本地上传」tab
UEDITOR_LOCAL_UPLOAD_TAB = [
    "text=本地上传",
    'div:has-text("本地上传")',
    'span:has-text("本地上传")',
    'a:has-text("本地上传")',
]
# 上传 input（弹窗内）
UEDITOR_IMAGE_FILE_INPUT = 'input[type="file"]'
# 上传后可能的确认按钮
UEDITOR_IMAGE_CONFIRM = [
    'button:has-text("确定")',
    'button:has-text("完成")',
    'button:has-text("确认")',
]

# === 封面 ===
COVER_BUTTON = [
    # MPP 精确选择器
    "div.d820b38cbcd0c526-icon",
    "div._73a3a52aab7e3a36-content",
    "#formMain > form > div.left-area-content-box > "
    "div.form-item-line-content-cover > div.form-inner-wrap > "
    "div.d01689d7d733c6fb-coverWrap > div:nth-child(1) > div > "
    "span > div > span > div > div > div > div > div.d820b38cbcd0c526-icon",
    # 通用
    "text=选择封面",
    'div:has-text("选择封面")',
    '[class*="cover"]:has-text("选择封面")',
    '[class*="cover"]',
    'span:has-text("上传封面")',
    'div:has-text("上传封面")',
    'div[class*="cover"] div[class*="upload"]',
    ".cover-upload-btn",
    # XPath
    "xpath=//body/div[1]/div/div[1]/div/div[2]/div/div/div/"
    "div[2]/div/form/div[1]/div[1]/div[2]/div[1]/div[1]/div/"
    "span/div/span/div/div/div/div",
]

COVER_FILE_INPUT = 'input[type="file"][accept*="image"]'
COVER_ALL_FILE_INPUT = 'input[type="file"]'

COVER_CONFIRM = [
    # MPP 精确选择器
    'button.cheetah-btn.cheetah-btn-primary.cheetah-btn-solid:has-text("确定")',
    "#rc-tabs-0-panel-1 > div > div._37e9eeb539c7e75d-footer > button.cheetah-btn.css-zneqgo",
    # 通用
    'button.cheetah-btn-primary:has-text("确定")',
    'button:has-text("确定")',
    'button:has-text("完成")',
    'button:has-text("确认")',
    'button:has(span:has-text("确定"))',
    ".cover-confirm-btn",
    # XPath
    'xpath=//button[contains(@class, "cheetah-btn-primary")][contains(., "确定")]',
    'xpath=//button[contains(., "确定")]',
]

COVER_SUCCESS_INDICATOR = [
    'img[class*="cover"]',
    ".cover-preview img",
    'div[class*="cover-preview"]',
    "text=替换",
    "text=更换",
]

# === 分类/标签 ===
TAG_INPUT = [
    'input[placeholder*="标签"]',
    ".tag-input input",
    'input[placeholder*="关键词"]',
    'input[placeholder*="话题"]',
    'xpath=//input[@placeholder[contains(., "标签") or contains(., "关键词")]]',
]

# === 发布按钮 ===
PUBLISH_BUTTON = [
    # MPP 精确选择器
    "#new-operator-content > div > span > span.op-list-right > div:nth-child(3) > button",
    "xpath=/html/body/div[1]/div/div[1]/div/div[2]/div/div/div/div[3]/div/span/span[2]/div[3]/button",
    # 通用
    'button.cheetah-btn-primary:has-text("发布")',
    'button[class*="primary"]:has-text("发布")',
    'button:has-text("发布")',
    'button[class*="publish"]',
    'button[class*="submit"]',
    '[class*="publish"]:has-text("发布")',
    'button[type="submit"]:has-text("发布")',
]

# === 发布确认弹窗 ===
PUBLISH_CONFIRM = [
    'button:has-text("确认发布")',
    'button:has-text("确定发布")',
    'button:has-text("继续发布")',
    'button:has-text("确认")',
    'button:has-text("确定")',
    'button:has-text("继续")',
    ".confirm-btn",
    'div[class*="modal"] button:has-text("确定")',
]

# === 发布成功 ===
SUCCESS_INDICATOR = [
    "text=发布成功",
    "text=提交成功",
    "text=审核中",
    "text=已发布",
    '[class*="success"]',
    ".publish-success",
    ".toast-success",
]

# === 安全验证 ===
CAPTCHA_INDICATOR = 'div:has-text("安全验证")'
CAPTCHA_CLOSE = [
    'button:has-text("关闭")',
    ".captcha-close",
    '[class*="captcha-close"]',
]

# === 发布失败（内容审核/违规）===
PUBLISH_FAIL_INDICATORS = [
    "text=审核不通过",
    "text=内容违规",
    "text=发布失败",
    "text=包含敏感词",
    "text=不符合规范",
    "text=请设置封面",
    "text=请输入标题",
    "text=请输入正文",
]

# === 限流/风控 ===
RATE_LIMIT_INDICATORS = [
    "text=频率过高",
    "text=操作频繁",
    "text=今日已达上限",
    "text=请稍后再试",
    "text=发布次数已达",
]

# === cheetah-tour 新手引导（多步骤浮层） ===
CHEETAH_TOUR_MASK = ".cheetah-tour-mask"
CHEETAH_TOUR_NEXT_BTN = [
    ".cheetah-tour-footer button.cheetah-tour-next-btn",
    ".cheetah-tour-footer .cheetah-btn-primary",
    '.cheetah-tour-footer button:has-text("下一步")',
    'button.cheetah-tour-next-btn:has-text("下一步")',
]
CHEETAH_TOUR_CLOSE_BTN = [
    ".cheetah-tour-close",
    "button.cheetah-tour-close",
]
CHEETAH_TOUR_DONE_BTN = [
    '.cheetah-tour-footer button:has-text("完成")',
    '.cheetah-tour-footer button:has-text("我知道了")',
    '.cheetah-tour-footer button:has-text("知道了")',
    '.cheetah-tour-footer .cheetah-btn-primary:has-text("完成")',
]
CHEETAH_TOUR_PREV_BTN = [
    '.cheetah-tour-footer button:has-text("上一步")',
]

# === cheetah-popconfirm（功能提示弹窗） ===
CHEETAH_POPCONFIRM = ".cheetah-popconfirm"
CHEETAH_POPCONFIRM_CONFIRM_BTN = [
    ".cheetah-popconfirm button.cheetah-btn-primary",
    ".cheetah-popconfirm-buttons button",
    '.cheetah-popconfirm button:has-text("我知道了")',
    '.cheetah-popconfirm button:has-text("知道了")',
    '.cheetah-popconfirm button:has-text("确定")',
]

# === 引导浮层通用指标文字（用于检测是否还有引导浮层） ===
GUIDE_INDICATOR_TEXTS = [
    "1/4",
    "2/4",
    "3/4",
    "4/4",
    "下一步",
    "上一步",
    "完成",
    "我知道了",
    "AI工具收起",
    "一键填写功能",
    "新手引导",
]
