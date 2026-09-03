# -*- coding: utf-8 -*-
"""
抖音创作者平台 CSS/XPath selectors
移植自 Content Pilot (MIT) + 增强多重回退
"""

# === 登录 ===
LOGIN_QR_CODE = 'img[class*="qrcode"], canvas[class*="qr"], .qrcode-image img'

# === 导航 ===
NAV_PUBLISH = 'a[href*="publish"], [class*="upload"]'
NAV_DATA = 'a[href*="data"], [class*="data"]'

# === 发布页 - 视频/图片上传 ===
PUBLISH_VIDEO_UPLOAD = 'input[type="file"][accept*="video"]'
PUBLISH_IMAGE_UPLOAD = 'input[type="file"][accept*="image"]'

# === 发布页 - 文本输入 ===
PUBLISH_TITLE_INPUT = [
    'input[placeholder*="标题"]',
    '[class*="title"] input',
    '[class*="caption"] input',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="作品标题"]',
]

PUBLISH_DESC_INPUT = [
    '[contenteditable="true"]',
    '[class*="description"] textarea',
    'textarea[placeholder*="描述"]',
    'textarea[placeholder*="添加"]',
    '.ql-editor',
    'div[contenteditable="true"]',
]

PUBLISH_TAG_INPUT = [
    '[class*="tag"] input',
    '[placeholder*="话题"]',
    'input[placeholder*="#"]',
    'input[placeholder*="标签"]',
]

# === 发布按钮 ===
PUBLISH_SUBMIT_BTN = [
    'button[class*="submit"]',
    'button[class*="publish"]',
    'button:has-text("发布")',
    'button:has-text("发送")',
    'button[type="submit"]',
]

# === 成功/状态 ===
PUBLISH_SUCCESS = '[class*="success"], [class*="published"], [class*="result"]'
CREATOR_HOME_INDICATOR = '[class*="user-info"], [class*="header-user"], .creator-layout'

# === 账号信息 ===
ACCOUNT_NICKNAME = '[class*="nickname"], [class*="user-name"], [class*="name"]'
ACCOUNT_FOLLOWER = '[class*="follower"], [class*="fans"]'

# === 数据分析 ===
ANALYTICS_VIEWS = '[class*="play"], [class*="view"]'
ANALYTICS_LIKES = '[class*="like"], [class*="digg"]'
ANALYTICS_COMMENTS = '[class*="comment"]'
ANALYTICS_SHARES = '[class*="share"]'

# === 图片模式 ===
IMAGE_MODE_SWITCH = [
    'button:has-text("发布图文")',
    'div:has-text("发布图文")',
    'span:has-text("发布图文")',
    'button:has-text("图文")',
    'div:has-text("图文")',
    '.image-mode-btn',
    'span:has-text("图文")',
    '[class*="mode"] >> text=图文',
]
