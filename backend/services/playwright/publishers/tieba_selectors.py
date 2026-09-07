# -*- coding: utf-8 -*-
"""
百度贴吧 (tieba.baidu.com) CSS selectors - v1.0

贴吧 PC 端"图文主题帖"发布路径（来源：用户 codegen 实录 + 头条式多级兜底）：
  首页"发贴" → "选择吧"输入吧名 → 选中下拉吧名 → #tb-editor-title 标题
  → #tb-editor-content 正文（图文穿插）→ "发布"

与头条的结构差异：
  - 贴吧正文/标题不是 ProseMirror，而是贴吧自研的 contenteditable div
    (#tb-editor-title / #tb-editor-content)，内部各含 <p>(role=paragraph)。
  - 贴吧独有"选择吧"一步——必须先指定目标吧才能发帖（吧名来自账号绑定时配置）。

登录态由外层 storage_state 注入（百度 BDUSS/STOKEN cookie），这里只做检测不做登录。
选择器易随改版失效，所有关键步骤都配多层兜底 + JS 评分兜底，失败落 backend/debug/tieba/。

⚠️ 图片上传：CONTENT_IMAGE_TOOLBAR_BTN 已由 codegen 实录校准（工具栏第 4 个
   .action-icon = 图片按钮，点击弹**文件选择器**）；点完普通图片直接插入正文，
   一般无裁剪确认框（IMAGE_CROP_CONFIRM_BTN 仅“视频封面”类才用到，作兜底保留）。
"""

# === 登录 / 首页 ===
HOME_URL = "https://tieba.baidu.com/"
LOGIN_URL = "https://tieba.baidu.com/"
# URL 出现这些片段视为"未登录 / 被踢到百度 passport 登录或安全验证"
LOGIN_URL_INDICATOR = [
    "passport",
    "wappass",
    "login",
    "signin",
    "/sso/",
    "/auth/",
    "captcha",
    "verify",
]
# 首页登录成功标识（右上角用户名 / 头像 / 用户菜单）
LOGIN_SUCCESS_ELEMENT = [
    '[class*="user_name"]',
    '[class*="userinfo"]',
    '[class*="u_username"]',
    '[class*="nav_user"]',
    'a[href*="/home/main"]',
    '[class*="avatar"]',
]
# 未登录标识（顶部"登录"入口）——出现即认为未登录
LOGGED_OUT_TEXT = ["登录", "请登录", "登录百度账号"]

# === 发帖入口："发贴"按钮（注意贴吧用"发贴"字样，exact 匹配）===
POST_ENTRY_BTN = [
    "text=发贴",
    'a:has-text("发贴")',
    'button:has-text("发贴")',
    '[class*="post"] :has-text("发贴")',
    "text=发帖",
    'a:has-text("发帖")',
]
# 兜底：直接导航到综合发帖页（首页发贴按钮打开的目标；随版本可能变化）
POST_PANEL_URL_FALLBACK = "https://tieba.baidu.com/"

# === 选择吧（贴吧独有）===
# "选择吧"输入框：填入吧名后弹出下拉候选，需从下拉选中匹配项
FORUM_INPUT = [
    'input[placeholder="选择吧"]',
    'input[placeholder*="选择吧"]',
    'input[placeholder*="选择"]',
    'input[placeholder*="吧名"]',
    '[class*="forum"] input',
    '[class*="poster"] input[type="text"]',
]
# 下拉候选项容器/条目（填入吧名后出现）。优先选文本精确等于吧名的项，否则第一项。
FORUM_SUGGEST_ITEM = [
    '[class*="drop"] [class*="item"]',
    '[class*="suggest"] li',
    '[class*="suggest"] [class*="item"]',
    '[class*="forum-list"] li',
    '[class*="ba-list"] [class*="item"]',
    'ul[class*="list"] li',
    '[class*="menu"] [class*="item"]',
]

# === 标题 ===
# ⚠️ 真机快照证明：发帖 modal 在 Shadow DOM 里，`page.content()` 序列化不到，
#    `#tb-editor-title` 这个 id 在真实 DOM 里根本不存在（0 匹配）。
#    Playwright 的 get_by_placeholder / get_by_text / get_by_role 能穿透 open shadow DOM
#    （选吧正是靠 get_by_text 成功的），所以标题/正文一律**优先用占位符文字定位**。
# 贴吧主题帖标题上限约 27~30 字（截图占位符写“5-31个字”），保守取 27。
# 占位符文案（截图实录，用子串匹配以抗“(5-31个字)”这类括号变化）：
TITLE_PLACEHOLDER_TEXTS = [
    "请输入贴子标题",
    "请输入标题",
    "贴子标题",
    "输入标题",
]
TITLE_EDITOR = "#tb-editor-title"
TITLE_INPUT = [
    # 占位符路径（真机唯一可靠）——input 与 contenteditable 两种形态都覆盖
    'input[placeholder*="标题"]',
    'textarea[placeholder*="标题"]',
    '[data-placeholder*="标题"]',
    '[aria-placeholder*="标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    # 旧臆想路径（真机不存在，保留仅作历史/其他版本兜底）
    '#tb-editor-title [contenteditable="true"]',
    "#tb-editor-title div[contenteditable]",
    "#tb-editor-title p",
    "#tb-editor-title div",
    "#tb-editor-title",
    '[class*="editor-title"] [contenteditable]',
]

# === 正文 ===
# 同上：优先占位符文字定位。占位符文案（截图实录）：
CONTENT_PLACEHOLDER_TEXTS = [
    "请输入正文",
    "输入正文",
    "说点什么",
    "分享新鲜事",
]
CONTENT_EDITOR = "#tb-editor-content"
CONTENT_INPUT = [
    # 占位符路径（真机唯一可靠）
    'textarea[placeholder*="正文"]',
    'textarea[placeholder*="内容"]',
    '[data-placeholder*="正文"]',
    '[data-placeholder*="内容"]',
    '[aria-placeholder*="正文"]',
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][data-placeholder*="内容"]',
    # 旧臆想路径（真机不存在，保留仅作兜底）
    '#tb-editor-content [contenteditable="true"]',
    "#tb-editor-content div[contenteditable]",
    "#tb-editor-content p",
    "#tb-editor-content div",
    "#tb-editor-content",
    '[class*="editor-content"] [contenteditable]',
]

# === 正文配图（⚠️ codegen 未录，推断 + 真机待校准）===
# 贴吧编辑器工具栏"图片"按钮：点击后通常触发隐藏 input[type=file] 或 file chooser
CONTENT_IMAGE_TOOLBAR_BTN = [
    # ✅ codegen 实录（2026-07-14）：编辑器工具栏第 4 个 .action-icon 即“图片”，
    #    点击弹**文件选择器**（codegen 录不到选文件动作，故当时只见一个 click）。
    "div:nth-child(4) > .action-icon > use",
    "div:nth-child(4) > .action-icon",
    # 兜底推断（类名/标题）
    '[class*="toolbar"] [class*="img"]',
    '[class*="tool"] [class*="image"]',
    '[class*="editor"] [title*="图片"]',
    'button[title*="图片"]',
    'div[title*="图片"]',
    '[class*="upload-img"]',
    '[aria-label*="图片"]',
]
# 图片文件 input（优先直接注入，最稳）
IMAGE_FILE_INPUT = 'input[type="file"][accept*="image"]'
IMAGE_ALL_FILE_INPUT = 'input[type="file"]'
# 图片上传成功标识（正文里出现 img，或缩略图/上传完成态）
IMAGE_SUCCESS_INDICATOR = [
    "#tb-editor-content img",
    '[class*="editor-content"] img',
    '[class*="img-item"]',
    '[class*="upload-item"]',
    '[class*="thumb"] img',
]
# 图片上传后的裁剪/封面确认弹框的“确认/完成/上传”按钮（2026-07-14 卡点）。
# 贴吧上传图片有时弹“视频封面/裁剪”确认框，不点确认会一直卡住 → 必须自动点掉。
IMAGE_CROP_CONFIRM_BTN = [
    'button:has-text("确定")',
    'button:has-text("确认")',
    'button:has-text("完成")',
    'button:has-text("上传")',
    'button:has-text("插入")',
    'button:has-text("确认裁剪")',
    'button:has-text("使用")',
    '[class*="crop"] button:has-text("确")',
    '[class*="dialog"] button:has-text("确")',
    '[class*="modal"] button:has-text("确")',
]

# === 发布按钮（"发布"，exact）===
PUBLISH_BUTTON = [
    "text=发布",
    'button:has-text("发布")',
    'a:has-text("发布")',
    '[class*="submit"]:has-text("发布")',
    '[class*="poster"] [class*="btn"]:has-text("发布")',
    'button[class*="primary"]:has-text("发布")',
    "text=发表",
    'button:has-text("发表")',
]
# 发布二次确认 / 协议弹窗（若有）
PUBLISH_CONFIRM = [
    'button:has-text("确认发布")',
    'button:has-text("确定")',
    'button:has-text("确认")',
    'button:has-text("继续")',
    'button:has-text("同意")',
]

# === 发布成功 ===
SUCCESS_INDICATOR = [
    "text=发表成功",
    "text=发布成功",
    "text=发贴成功",
    "text=提交成功",
    "text=回复成功",
]
# 发帖成功通常跳转到帖子详情页 /p/{tid} 或吧内列表
SUCCESS_URL_PATTERN = r"(tieba\.baidu\.com/p/\d+|/f\?kw=)"

# === 发布失败 / 内容校验提示 ===
PUBLISH_FAIL_INDICATORS = [
    "text=发表失败",
    "text=发布失败",
    "text=请先选择吧",
    "text=请选择要发表的吧",
    "text=标题不能为空",
    "text=请输入标题",
    "text=内容不能为空",
    "text=请输入正文",
    "text=内容包含",
    "text=含有不适宜",
    "text=含有敏感",
    "text=不符合",
    "text=发帖过于频繁",
    "text=操作过于频繁",
    "text=你的帐号异常",
]

# === 限流 / 风控 / 安全验证（百度常用滑块/字符验证码）===
CAPTCHA_INDICATOR = (
    '[class*="passMod"], [class*="vcode"], [class*="captcha"], '
    '[class*="verify"], div:has-text("请拖动滑块"), div:has-text("安全验证")'
)
RATE_LIMIT_INDICATORS = [
    "text=发帖过于频繁",
    "text=操作过于频繁",
    "text=请稍后再试",
    "text=今日发帖已达上限",
    "text=你的帐号异常",
]

# === 干扰弹窗（贴吧偶有活动浮层 / 客户端引导 / 登录引导）===
# ⚠️ 只保留“文字明确 = 消除提示”的按钮。
#    绝不能放裸 [class*="close"] / .icon-close / [aria-label*=close]——
#    历史事故（2026-07-13）：发帖面板是挂在 <body> 末尾的 modal，
#    `[class*="close"]` + `.last` 会抓到“面板自己的关闭按钮”，把发帖面板点没了，
#    随后选吧被跳过、标题填写失败。文字类关闭按钮语义是“消除这个提示”，
#    不会误伤编辑器（编辑器不会有“知道了/跳过”这类按钮）。
#    也不要放“取消 / 关闭”——它们可能是“取消草稿 / 关闭编辑器”。
INTERFERENCE_CLOSE_BTN = [
    'button:has-text("知道了")',
    'button:has-text("我知道了")',
    'button:has-text("跳过")',
    'button:has-text("稍后再说")',
    'button:has-text("以后再说")',
    'button:has-text("暂不需要")',
    'button:has-text("暂不")',
]
