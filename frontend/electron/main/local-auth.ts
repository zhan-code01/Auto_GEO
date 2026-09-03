/**
 * AutoGeo 本地平台登录授权模块
 *
 * 负责在 Electron 桌面端打开真实浏览器窗口，让用户扫码/输入密码登录各平台，
 * 检测登录完成状态，保存浏览器会话到本地，并调用服务端 API 完成帐号绑定。
 *
 * 依赖：
 *  - Playwright (chromium)：启动真实 Chrome 浏览器窗口
 *  - Electron app.getPath('userData')：会话文件存储目录
 *  - Node 内置 fetch：与服务端通信（Node 18+）
 *
 * 安全性说明：
 *  会话文件保存浏览器的完整 storageState（含 cookies、localStorage），
 *  仅存储在本地 userData 目录，不会上传至服务器。
 */

import { app } from 'electron'
import { chromium } from 'playwright'
import type { Browser, BrowserContext, Page } from 'playwright'
import * as fs from 'fs'
import * as path from 'path'
import * as os from 'os'

// ==================== 会话文件管理 ====================

/** 获取会话文件存储目录（自动创建） */
export function getSessionDir(): string {
  const dir = path.join(app.getPath('userData'), 'sessions')
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true })
    console.log('[LocalAuth] 创建会话目录:', dir)
  }
  return dir
}

/** 获取指定平台（及可选账号）的会话文件路径 */
export function getSessionPath(platform: string, accountId?: number | null): string {
  const file = accountId ? `${platform}_${accountId}.json` : `${platform}.json`
  return path.join(getSessionDir(), file)
}

/** 检查指定平台（及可选账号）的会话文件是否存在 */
export function hasSession(platform: string, accountId?: number | null): boolean {
  return fs.existsSync(getSessionPath(platform, accountId))
}

/** 读取并解析本地会话 JSON 文件，不存在返回 null */
export function loadSession(platform: string, accountId?: number | null): object | null {
  const sessionPath = getSessionPath(platform, accountId)
  if (!fs.existsSync(sessionPath)) {
    console.log('[LocalAuth] 会话文件不存在:', sessionPath)
    return null
  }
  try {
    const raw = fs.readFileSync(sessionPath, 'utf-8')
    return JSON.parse(raw)
  } catch (err: any) {
    console.error('[LocalAuth] 读取会话文件失败:', sessionPath, err.message)
    return null
  }
}

/** 保存指定平台（及可选账号）的浏览器会话 JSON。 */
export function saveSession(platform: string, storageState: object, accountId?: number | null): void {
  const sessionPath = getSessionPath(platform, accountId)
  const sessionData = JSON.stringify(storageState, null, 2)
  fs.writeFileSync(sessionPath, sessionData, 'utf-8')
  console.log(`[LocalAuth] 会话已保存: ${sessionPath} (${sessionData.length} 字节)`)
}

/** 删除指定平台（及可选账号）的会话文件 */
export function deleteSession(platform: string, accountId?: number | null): boolean {
  const sessionPath = getSessionPath(platform, accountId)
  try {
    if (fs.existsSync(sessionPath)) {
      fs.unlinkSync(sessionPath)
      console.log('[LocalAuth] 已删除会话文件:', sessionPath)
      return true
    }
    return false
  } catch (err: any) {
    console.error('[LocalAuth] 删除会话文件失败:', sessionPath, err.message)
    return false
  }
}

/** 列出某平台下所有账号级会话文件路径（不含平台级文件） */
export function listAccountSessionPaths(platform: string): string[] {
  const prefix = `${platform}_`
  try {
    return fs
      .readdirSync(getSessionDir())
      .filter((name) => name.startsWith(prefix) && name.endsWith('.json'))
      .map((name) => path.join(getSessionDir(), name))
  } catch {
    return []
  }
}

/**
 * 从 JWT 载荷中解码 user_id（JWT 载荷是 base64url，无需密钥即可读取）。
 * 用于把「同机多账号」的本地会话文件按用户隔离（AI 平台没有 Account 记录，
 * 只能以 user_id 作为隔离键）。
 */
export function decodeJwtUserId(token?: string | null): number | null {
  if (!token) return null
  try {
    const part = token.split('.')[1]
    if (!part) return null
    const payload = JSON.parse(Buffer.from(part, 'base64url').toString('utf-8'))
    const uid = Number(payload?.user_id)
    return Number.isFinite(uid) && uid > 0 ? uid : null
  } catch {
    return null
  }
}

/** 判断某平台是否存在可用的本地会话（平台级或任意账号级） */
export function hasUsableSession(platform: string): boolean {
  const candidates: (object | null)[] = [loadSession(platform)]
  for (const sessionPath of listAccountSessionPaths(platform)) {
    try {
      candidates.push(JSON.parse(fs.readFileSync(sessionPath, 'utf-8')))
    } catch {
      candidates.push(null)
    }
  }
  const nowSeconds = Date.now() / 1000
  return candidates.some((session) => {
    if (!session || typeof session !== 'object') return false
    const cookies = Array.isArray((session as any).cookies) ? (session as any).cookies : []
    if (cookies.length === 0) return false
    return cookies.some((cookie: any) => {
      const expires = Number(cookie?.expires)
      return !Number.isFinite(expires) || expires < 0 || expires > nowSeconds
    })
  })
}

// ==================== 平台 URL 硬编码配置 ====================

/**
 * 平台登录页与首页 URL 对照表。
 *
 * 优先通过 /api/client/accounts/bind/start 获取实时 URL，
 * 如果服务端不可达，则回退到此硬编码配置。
 */
const PLATFORM_URLS: Record<string, { login_url: string; home_url: string }> = {
  zhihu: {
    login_url: 'https://www.zhihu.com/signin',
    home_url: 'https://www.zhihu.com',
  },
  baijiahao: {
    // 百家号使用百度统一登录，登录后跳转回百家号
    login_url: 'https://baijiahao.baidu.com/builder/rc/login?redirect_url=https://baijiahao.baidu.com/builder/rc/static/edit/index',
    home_url: 'https://baijiahao.baidu.com/builder/rc/static/edit/index',
  },
  xiaohongshu: {
    login_url: 'https://creator.xiaohongshu.com/login',
    home_url: 'https://creator.xiaohongshu.com',
  },
  toutiao: {
    login_url: 'https://mp.toutiao.com/auth/page/login/',
    home_url: 'https://mp.toutiao.com',
  },
  bilibili: {
    login_url: 'https://passport.bilibili.com/login',
    home_url: 'https://member.bilibili.com',
  },
  douyin: {
    login_url: 'https://creator.douyin.com',
    home_url: 'https://creator.douyin.com',
  },
  kuaishou: {
    login_url: 'https://cp.kuaishou.com',
    home_url: 'https://cp.kuaishou.com',
  },
  jianshu: {
    login_url: 'https://www.jianshu.com/sign_in',
    home_url: 'https://www.jianshu.com',
  },
  juejin: {
    login_url: 'https://juejin.cn/',
    home_url: 'https://juejin.cn',
  },
  csdn: {
    login_url: 'https://passport.csdn.net/login',
    home_url: 'https://mp.csdn.net',
  },
  tieba: {
    // 贴吧走百度统一登录，登录页即首页（同页弹窗扫码），登录后停留在 tieba.baidu.com
    login_url: 'https://tieba.baidu.com/',
    home_url: 'https://tieba.baidu.com/',
  },
  cnblogs: {
    // 博客园登录
    login_url: 'https://account.cnblogs.com/signin',
    home_url: 'https://www.cnblogs.com',
  },
  weixin: {
    // 微信公众号平台登录
    login_url: 'https://mp.weixin.qq.com/',
    home_url: 'https://mp.weixin.qq.com',
  },
  wangyi: {
    // 网易号登录
    login_url: 'https://mp.163.com/',
    home_url: 'https://mp.163.com',
  },
  sohu: {
    // 搜狐号登录
    login_url: 'https://mp.sohu.com/',
    home_url: 'https://mp.sohu.com',
  },
  douban: {
    // 豆瓣登录
    login_url: 'https://www.douban.com/accounts/login',
    home_url: 'https://www.douban.com',
  },
  penguin: {
    // 企鹅号（腾讯内容开放平台）登录
    login_url: 'https://om.qq.com/',
    home_url: 'https://om.qq.com',
  },
  weibo: {
    // 微博登录
    login_url: 'https://weibo.com/login.php',
    home_url: 'https://weibo.com',
  },
  doubao: {
    login_url: 'https://www.doubao.com/chat/',
    home_url: 'https://www.doubao.com/chat/',
  },
  qianwen: {
    login_url: 'https://qianwen.com/',
    home_url: 'https://qianwen.com/',
  },
  deepseek: {
    login_url: 'https://chat.deepseek.com/',
    home_url: 'https://chat.deepseek.com/',
  },
}

const AI_GEO_PLATFORMS = new Set(['doubao', 'qianwen', 'deepseek'])

type LoginProbeResult = {
  ok: boolean
  method?: 'api' | 'dom'
  reason?: string
}

// ==================== Chrome 浏览器查找 ====================

export function findChromeExe(): string | null {
  let candidates: string[]
  switch (os.platform()) {
    case 'win32':
      candidates = [
        path.join(process.env['PROGRAMFILES'] || 'C:\\Program Files', 'Google\\Chrome\\Application\\chrome.exe'),
        path.join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Google\\Chrome\\Application\\chrome.exe'),
        path.join(process.env['LOCALAPPDATA'] || '', 'Google\\Chrome\\Application\\chrome.exe'),
      ]
      break
    case 'darwin':
      candidates = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
      break
    default:
      candidates = ['/usr/bin/google-chrome-stable', '/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/snap/bin/chromium']
  }
  for (const p of candidates) {
    if (p && fs.existsSync(p)) return p
  }
  return null
}

// ==================== 类型定义 ====================

/** 授权结果 */
interface AuthResult {
  success: boolean
  platform: string
  nickname?: string
  error?: string
}

/** 服务端帐号验证结果 */
interface VerifyResult {
  active: boolean
  requires_reauth: boolean
}

/** 服务端帐号绑定确认返回 */
interface AccountResponse {
  account: {
    id: number
    platform: string
    account_name: string
    active: boolean
  }
}

// ==================== 登录检测 ====================

/**
 * 等待用户在浏览器中完成登录。
 *
 * 检测策略（按平台）：
 *  - 知乎：检测 cookies 中是否包含有效的 z_c0
 *  - 百家号：URL 从 /login 跳转到 /builder 或 /static/edit
 *  - 小红书：检测 cookies 中是否包含 web_session 或 a1
 *  - 头条号：URL 从 /login 跳转到主页
 *  - 通用兜底：URL 中不再包含 login / signin / passport 关键词
 *
 * @param page Playwright 页面对象
 * @param platform 平台标识
 * @param timeoutMs 超时时间（毫秒），默认 3 分钟（扫码登录需要时间）
 * @returns 是否成功检测到登录
 */
async function waitForLogin(
  page: Page,
  platform: string,
  timeoutMs: number = 180000
): Promise<boolean> {
  const startTime = Date.now()
  let lastUrl = ''

  console.log(`[LocalAuth] 等待用户在 ${platform} 完成登录...（超时 ${timeoutMs / 1000}s）`)

  while (Date.now() - startTime < timeoutMs) {
    try {
      // 每 2 秒检查一次，避免频繁轮询
      await page.waitForTimeout(2000)
      const currentUrl = page.url()

      // --- 平台专用检测 ---

      if (platform === 'zhihu') {
        const cookies = await page.context().cookies()
        const zc0 = cookies.find(c => c.name === 'z_c0')
        if (zc0 && zc0.value && zc0.value.trim() !== '') {
          console.log('[LocalAuth] 检测到知乎登录态（z_c0 cookie 存在）')
          return true
        }
      }

      if (platform === 'baijiahao') {
        const cookies = await page.context().cookies()
        // 百家号需要检测百度 cookie + 百家号创作中心特定 cookie
        const hasBaiduLoginCookie = cookies.some(c =>
          ['BDUSS', 'BDUSS_BFESS', 'STOKEN', 'BAIDUID_BFESS'].includes(c.name) && c.value
        )
        // 额外检测是否已跳转到百家号创作中心（不是登录页）
        const currentUrl = page.url()
        const isOnBaijiahaoHome = /baijiahao\.baidu\.com/.test(currentUrl) && !/login|signin/i.test(currentUrl)
        if (hasBaiduLoginCookie && isOnBaijiahaoHome) {
          console.log('[LocalAuth] 检测到百家号登录态（百度 cookie + 创作中心页面）')
          return true
        } else if (hasBaiduLoginCookie) {
          console.log('[LocalAuth] 检测到百度 cookie，但尚未跳转到百家号创作中心，继续等待...')
        }
      }

      if (platform === 'tieba') {
        const cookies = await page.context().cookies()
        // 贴吧走百度统一登录。BDUSS 是百度登录成功后才写入的关键 cookie，
        // 授权用干净会话（见下方 newContext，不注入旧会话），BDUSS 不会是旧值，
        // 出现即代表本次登录成功。
        const hasBaiduLoginCookie = cookies.some(c =>
          ['BDUSS', 'BDUSS_BFESS', 'STOKEN'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 关键：百度登录是「同页弹窗扫码」，URL 自始至终停在 tieba.baidu.com，
        // 不会「从登录页跳到非登录页」，所以通用 URL 跳转兜底对贴吧永远不成立，
        // 只能靠 cookie + 域名判定。
        const isOnTieba = /tieba\.baidu\.com/.test(currentUrl)
        if (hasBaiduLoginCookie && isOnTieba) {
          console.log('[LocalAuth] 检测到贴吧登录态（百度 BDUSS cookie 存在）')
          return true
        } else if (!hasBaiduLoginCookie) {
          console.log('[LocalAuth] 贴吧未检测到百度登录 cookie，继续等待...')
        }
      }

      if (platform === 'xiaohongshu') {
        const cookies = await page.context().cookies()
        // 小红书登录 cookie
        const hasXHSCookie = cookies.some(c =>
          ['web_session', 'a1', 'webId'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须在小红书域名上
        const currentUrl = page.url()
        const isOnXHS = /xiaohongshu\.com/.test(currentUrl)

        // 检查页面是否显示登录/注册按钮
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '登录/注册']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        if (hasXHSCookie && isOnXHS && !hasLoginButton) {
          console.log('[LocalAuth] 检测到小红书登录态')
          return true
        }
      }

      if (platform === 'toutiao') {
        // 头条号登录后可能落在 profile_v4/index、profile_v4/graphic/publish、content/article 等路径。
        // 只要确定在头条号域名、不在登录页、且页面上没有登录/注册/扫码按钮，即认为已登录。
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '扫码登录', '手机号登录']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        const isOnToutiao = /mp\.toutiao\.com/.test(currentUrl)
        const isOnLoginPage = /login|auth\/page/i.test(currentUrl)
        if (isOnToutiao && !isOnLoginPage && !hasLoginButton) {
          console.log('[LocalAuth] 检测到头条号登录态（非登录页 + 无登录按钮）')
          return true
        }
      }

      if (platform === 'bilibili') {
        const cookies = await page.context().cookies()
        // B站登录 cookie
        const hasBiliCookie = cookies.some(c =>
          ['SESSDATA', 'bili_jct', 'DedeUserID'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须在 B站域名上
        const currentUrl = page.url()
        const isOnBili = /bilibili\.com/.test(currentUrl)

        // 检查页面是否显示登录/注册按钮
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '登录/注册', '登录注册']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        if (hasBiliCookie && isOnBili && !hasLoginButton) {
          console.log('[LocalAuth] 检测到 B站登录态')
          return true
        }
      }

      if (platform === 'douyin') {
        const cookies = await page.context().cookies()
        // 抖音创作者平台特有的 cookie（sid_guard, uid_tt 是抖音专属的）
        // 不检测 sessionid，因为它太常见会导致误检测
        const hasDouyinCookie = cookies.some(c =>
          ['sid_guard', 'uid_tt', 'sessionid_ss'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须确认 URL 在抖音创作者域名上
        const currentUrl = page.url()
        const isOnDouyinCreator = /creator\.douyin\.com/.test(currentUrl)
        if (hasDouyinCookie && isOnDouyinCreator) {
          console.log('[LocalAuth] 检测到抖音创作者登录态')
          return true
        }
      }

      if (platform === 'kuaishou') {
        const cookies = await page.context().cookies()
        // 快手创作者登录 cookie
        const hasKSCookie = cookies.some(c =>
          ['kuaishou.server.web_ph', 'userId', 'did'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须在快手域名上
        const currentUrl = page.url()
        const isOnKS = /kuaishou\.com/.test(currentUrl)

        // 检查页面是否显示登录/注册按钮
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '登录/注册', '快手登录']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        if (hasKSCookie && isOnKS && !hasLoginButton) {
          console.log('[LocalAuth] 检测到快手创作者登录态')
          return true
        }
      }

      if (platform === 'jianshu') {
        const cookies = await page.context().cookies()
        // 简书真正的登录 cookie，只有登录成功才会写入
        const hasJianshuLoginCookie = cookies.some(c =>
          ['remember_user_token', '_m7e_session_core'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须在简书域名上
        const currentUrl = page.url()
        const isOnJianshu = /jianshu\.com/.test(currentUrl)

        // 关键：检查页面是否显示登录/注册按钮（未登录状态）
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '登录/注册', '登录 | 注册']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        if (hasJianshuLoginCookie && isOnJianshu && !hasLoginButton) {
          console.log('[LocalAuth] 检测到简书登录态（cookie + 简书域名 + 无登录按钮）')
          return true
        } else if (!hasJianshuLoginCookie) {
          console.log('[LocalAuth] 简书未检测到登录 cookie，继续等待...')
        } else if (hasLoginButton) {
          console.log('[LocalAuth] 简书检测到登录/注册按钮，未登录状态，继续等待...')
        }
      }

      if (platform === 'juejin') {
        const cookies = await page.context().cookies()
        // 掘金（字节系）登录 cookie，登录成功才会写入；未登录时不会有 sessionid
        const hasJuejinCookie = cookies.some(c =>
          ['sessionid', 'sessionid_ss', 'passport_csrf_token'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须在掘金域名上
        const isOnJuejin = /juejin\.cn/.test(currentUrl)

        // 关键：检查页面是否还显示登录/注册按钮（掘金登录是弹窗，URL 可能一直停在非登录页，
        // 只靠“URL 不含 login”的通用兜底会在用户还没登录时误判成功，故必须 cookie + 无登录按钮双判）
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '登录/注册']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        if (hasJuejinCookie && isOnJuejin && !hasLoginButton) {
          console.log('[LocalAuth] 检测到掘金登录态（cookie + 掘金域名 + 无登录按钮）')
          return true
        } else if (!hasJuejinCookie) {
          console.log('[LocalAuth] 掘金未检测到登录 cookie，继续等待...')
        } else if (hasLoginButton) {
          console.log('[LocalAuth] 掘金检测到登录/注册按钮，未登录状态，继续等待...')
        }
      }

      if (platform === 'csdn') {
        const cookies = await page.context().cookies()
        // CSDN 登录 cookie
        const hasCSDNCookie = cookies.some(c =>
          ['UserName', 'UserToken', 'uuid_tt_dd'].includes(c.name) && c.value && c.value.trim() !== ''
        )
        // 必须在 CSDN 域名上
        const currentUrl = page.url()
        const isOnCSDN = /csdn\.net/.test(currentUrl)

        // 检查页面是否显示登录/注册按钮（未登录状态）
        let hasLoginButton = false
        try {
          hasLoginButton = await page.evaluate(function(): boolean {
            const texts = ['登录', '注册', '登录/注册', '登录 | 注册', 'github登录']
            for (var i = 0; i < texts.length; i++) {
              var elements = document.querySelectorAll('button, a, div, span')
              for (var j = 0; j < elements.length; j++) {
                var el = elements[j] as HTMLElement
                var elText = (el.textContent || '').trim()
                if (elText === texts[i] && el.offsetWidth > 0 && el.offsetHeight > 0) {
                  return true
                }
              }
            }
            return false
          })
        } catch (e) {
          hasLoginButton = false
        }

        if (hasCSDNCookie && isOnCSDN && !hasLoginButton) {
          console.log('[LocalAuth] 检测到 CSDN 登录态（cookie + CSDN域名 + 无登录按钮）')
          return true
        } else if (!hasCSDNCookie) {
          console.log('[LocalAuth] CSDN 未检测到登录 cookie，继续等待...')
        } else if (hasLoginButton) {
          console.log('[LocalAuth] CSDN 检测到登录/注册按钮，未登录状态，继续等待...')
        }
      }

      if (platform === 'doubao') {
        const doubaoLogin = await hasDoubaoLoginState(page)
        if (doubaoLogin.ok) {
          console.log(`[LocalAuth] 豆包登录态确认: ${doubaoLogin.method || 'unknown'}`)
          return true
        }
      }

      if (platform === 'qianwen') {
        const cookies = await page.context().cookies()
        if (cookies.some(c => ['tongyi_sso_ticket', 'tongyi_sso_ticket_hash', 'login_aliyunid'].includes(c.name) && c.value)) {
          console.log('[LocalAuth] 检测到通义千问登录态')
          return true
        }
      }

      if (platform === 'deepseek') {
        const deepseekLogin = await hasDeepSeekLoginState(page)
        if (deepseekLogin.ok) {
          console.log(`[LocalAuth] DeepSeek login state confirmed by ${deepseekLogin.method || 'unknown'}`)
          return true
        }
      }

      // --- 通用兜底检测 ---
      // URL 中不再包含登录相关路径，说明已跳转到登录后的页面
      const isLoginPage = /(login|signin|passport|auth)/i.test(currentUrl)
      if (!AI_GEO_PLATFORMS.has(platform) && !isLoginPage && lastUrl && isLoginPageUrl(lastUrl, platform)) {
        // 从登录页跳转到了非登录页，大概率登录成功
        console.log('[LocalAuth] 检测到登录完成（URL 跳转离开登录页）:', currentUrl)
        return true
      }

      lastUrl = currentUrl
    } catch (err: any) {
      if (isTargetClosedError(err)) {
        console.warn('[LocalAuth] 授权浏览器窗口已关闭')
        return false
      }
      // 页面可能正在跳转中，忽略临时错误
      console.warn('[LocalAuth] 轮询检测异常（可忽略）:', err.message)
    }
  }

  console.warn(`[LocalAuth] 登录等待超时（${timeoutMs / 1000}s）`)
  return false
}

async function hasDoubaoLoginState(page: Page): Promise<LoginProbeResult> {
  try {
    if (!/doubao\.com/i.test(page.url())) {
      return { ok: false }
    }

    const result = await page.evaluate(async () => {
      const isVisible = (element: Element | null) => {
        if (!element) return false
        const style = window.getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
      }
      const bodyText = document.body?.innerText || ''
      const hasLoginPrompt =
        /登录|手机号|验证码|\+86|下一步|用户协议|隐私政策|扫码登录|抖音一键登录/i.test(bodyText) &&
        Array.from(document.querySelectorAll('input, button, [class*="login"], [class*="passport"]')).some(isVisible)
      const hasChatInput = Array.from(
        document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [class*="chat-input"], [class*="editor"]'),
      ).some(isVisible)
      const hasConversationUi =
        Array.from(document.querySelectorAll('[data-foundation-type="receive-message-action-bar"], [data-message-id]')).some(isVisible) ||
        /历史对话|新对话/.test(bodyText)

      try {
        const response = await fetch('/api/user/info', {
          credentials: 'include',
          headers: { accept: 'application/json' },
        })
        const text = await response.text()
        if (response.ok) {
          let data: any = null
          try {
            data = JSON.parse(text)
          } catch {
            data = null
          }

          const hasUserIdentity = (value: any, depth = 0): boolean => {
            if (!value || typeof value !== 'object' || depth > 5) return false
            if (Array.isArray(value)) return value.some(item => hasUserIdentity(item, depth + 1))
            if (
              value.uid ||
              value.user_id ||
              value.userId ||
              value.id ||
              value.name ||
              value.nickname ||
              value.avatar ||
              value.phone ||
              value.email
            ) {
              return true
            }
            return Object.values(value).some(item => hasUserIdentity(item, depth + 1))
          }

          if (hasUserIdentity(data)) {
            return { ok: true, status: response.status, via: 'api' }
          }
        }
        return { ok: !hasLoginPrompt && hasChatInput && hasConversationUi, status: response.status, via: 'dom' }
      } catch {
        return { ok: !hasLoginPrompt && hasChatInput && hasConversationUi, status: 0, via: 'dom' }
      }
    })

    if (!result.ok) {
      console.log(`[LocalAuth] 豆包登录未确认: status=${result.status || 0}`)
    }
    return { ok: Boolean(result.ok), method: result.via === 'api' ? 'api' : result.via === 'dom' ? 'dom' : undefined }
  } catch (err: any) {
    if (isTargetClosedError(err)) {
      throw err
    }
    console.warn('[LocalAuth] 豆包登录探测失败:', err.message)
    return { ok: false }
  }
}

async function hasDeepSeekLoginState(page: Page): Promise<LoginProbeResult> {
  try {
    if (!/chat\.deepseek\.com/i.test(page.url())) {
      return { ok: false }
    }

    const result = await page.evaluate(async () => {
      const isVisible = (element: Element | null) => {
        if (!element) return false
        const style = window.getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
      }
      const visibleText = (selector: string) =>
        Array.from(document.querySelectorAll(selector)).some(element => {
          const style = window.getComputedStyle(element)
          const rect = element.getBoundingClientRect()
          return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
        })

      const bodyText = document.body?.innerText || ''
      const hasLoginPrompt =
        /登录|注册|验证码|手机号|邮箱登录|扫码登录|sign in|sign up|log in/i.test(bodyText) &&
        visibleText('input[type="password"], input[type="tel"], input[type="email"], [class*="login"], [class*="signin"]')
      const hasChatShell =
        /开启新对话|新对话|快速模式|专家模式|联网搜索|使用快速模式开始对话|Start a new chat|DeepThink/i.test(bodyText) ||
        visibleText('textarea, [contenteditable="true"], [class*="chat-input"], [class*="new-chat"]')
      const hasChatInput = Array.from(
        document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], [id*="chat-input"], [class*="chat-input"]'),
      ).some(isVisible)
      const hasConversationUi =
        Array.from(
          document.querySelectorAll(
            '[class*="conversation"], [class*="chat-session"], [class*="message"], [class*="sidebar"], [data-testid*="conversation"]',
          ),
        ).some(isVisible) || /历史对话|暂无历史对话|新对话|Start a new chat|DeepThink|深度思考/.test(bodyText)

      try {
        const response = await fetch('/api/v0/users/current', {
          credentials: 'include',
          headers: { accept: 'application/json' },
        })
        const text = await response.text()

        let data: any = null
        if (response.ok) {
          try {
            data = JSON.parse(text)
          } catch {
            data = null
          }
        }

        const hasUserIdentity = (value: any, depth = 0): boolean => {
          if (!value || typeof value !== 'object' || depth > 4) return false
          if (Array.isArray(value)) return value.some(item => hasUserIdentity(item, depth + 1))
          if (
            value.id ||
            value.user_id ||
            value.userId ||
            value.uid ||
            value.email ||
            value.phone ||
            value.name ||
            value.nickname ||
            value.avatar
          ) {
            return true
          }
          return Object.values(value).some(item => hasUserIdentity(item, depth + 1))
        }
        const hasUser = hasUserIdentity(data)
        if (hasUser) {
          return { ok: true, status: response.status, via: 'api', reason: 'current-user api returned identity' }
        }
        return {
          ok: !hasLoginPrompt && hasChatShell && (hasChatInput || hasConversationUi),
          status: response.status,
          via: 'dom',
          reason: `dom fallback after api without identity: login=${hasLoginPrompt}, shell=${hasChatShell}, input=${hasChatInput}, conversation=${hasConversationUi}`,
        }
      } catch {
        return {
          ok: !hasLoginPrompt && hasChatShell && (hasChatInput || hasConversationUi),
          status: 0,
          via: 'dom',
          reason: `dom fallback after api failure: login=${hasLoginPrompt}, shell=${hasChatShell}, input=${hasChatInput}, conversation=${hasConversationUi}`,
        }
      }
    })

    if (!result.ok) {
      console.log(`[LocalAuth] DeepSeek login not confirmed: status=${result.status}, reason=${result.reason || 'unknown'}`)
    }
    return {
      ok: Boolean(result.ok),
      method: result.via === 'api' ? 'api' : result.via === 'dom' ? 'dom' : undefined,
      reason: result.reason,
    }
  } catch (err: any) {
    if (isTargetClosedError(err)) {
      throw err
    }
    console.warn('[LocalAuth] DeepSeek login probe failed:', err.message)
    return { ok: false }
  }
}

function withBrowserVerifiedLogin(
  storageState: object,
  platform: string,
  loginVerification?: LoginProbeResult,
): object {
  if (!loginVerification?.ok || !loginVerification.method || !AI_GEO_PLATFORMS.has(platform)) {
    return storageState
  }

  return {
    ...(storageState as Record<string, any>),
    browser_verified_login: {
      platform,
      verified_at: Date.now() / 1000,
      method: loginVerification.method,
      reason: loginVerification.reason || `${platform} browser-side login probe confirmed`,
    },
  }
}

function isTargetClosedError(err: any): boolean {
  const message = String(err?.message || err || '')
  return /target page, context or browser has been closed|page has been closed|browser has been closed/i.test(message)
}

/** 判断是否仍是登录相关页面 */
function isLoginPageUrl(url: string, platform: string): boolean {
  // 某些平台主页也可能会触发 login 关键词（如"未登录"提示），需要更精细判断
  if (platform === 'zhihu' && url === 'https://www.zhihu.com/') {
    return false
  }
  return /(login|signin|passport|auth)/i.test(url)
}

// ==================== 昵称提取 ====================

/**
 * 从页面中提取用户昵称。
 *
 * @param page Playwright 页面对象
 * @param platform 平台标识
 * @returns 提取到的昵称，失败返回 "未知用户"
 */
async function extractNickname(page: Page, platform: string): Promise<string> {
  try {
    switch (platform) {
      case 'zhihu': {
        // 知乎个人主页 / 首页导航栏中提取用户名
        const selectors = [
          '.AppHeader-profile .AppHeader-profileItem button',
          '.AppHeader-userInfo .AppHeader-userName',
          '[class*="ProfileHeader"] [class*="name"]',
          'meta[name="description"]',
        ]
        for (const sel of selectors) {
          try {
            const el = await page.$(sel)
            if (el) {
              const text =
                sel === 'meta[name="description"]'
                  ? await el.getAttribute('content')
                  : await el.textContent()
              if (text && text.trim()) {
                const cleaned = text.trim().replace(/[-\s–—].*$/, '').slice(0, 30)
                if (cleaned.length > 0) {
                  console.log(`[LocalAuth] 知乎昵称提取成功: ${cleaned}`)
                  return cleaned
                }
              }
            }
          } catch {
            // continue to next selector
          }
        }
        break
      }

      case 'baijiahao': {
        const selectors = [
          '.header-avatar-name',
          '.user-name',
          '[class*="avatar"] [class*="name"]',
          '.header-user .name',
        ]
        for (const sel of selectors) {
          try {
            const el = await page.$(sel)
            const text = await el?.textContent()
            if (text && text.trim().length > 0) {
              console.log(`[LocalAuth] 百家号昵称提取成功: ${text.trim()}`)
              return text.trim().slice(0, 30)
            }
          } catch {
            // continue
          }
        }
        break
      }

      case 'xiaohongshu': {
        const selectors = [
          '.user-name',
          '.creator-name',
          '[class*="sideBar"] [class*="name"]',
          '[class*="UserInfo"] [class*="name"]',
        ]
        for (const sel of selectors) {
          try {
            const el = await page.$(sel)
            const text = await el?.textContent()
            if (text && text.trim().length > 0) {
              console.log(`[LocalAuth] 小红书昵称提取成功: ${text.trim()}`)
              return text.trim().slice(0, 30)
            }
          } catch {
            // continue
          }
        }
        break
      }

      case 'toutiao': {
        const selectors = [
          '.author-name',
          '.user-name',
          '.mp-header .name',
          '[class*="userInfo"] [class*="name"]',
        ]
        for (const sel of selectors) {
          try {
            const el = await page.$(sel)
            const text = await el?.textContent()
            if (text && text.trim().length > 0) {
              console.log(`[LocalAuth] 头条号昵称提取成功: ${text.trim()}`)
              return text.trim().slice(0, 30)
            }
          } catch {
            // continue
          }
        }
        break
      }

      case 'bilibili':
      case 'douyin':
      case 'kuaishou':
      case 'jianshu':
      case 'juejin':
      case 'csdn': {
        const selectors = [
          '.user-name',
          '.nickname',
          '.name',
          '[class*="user"] [class*="name"]',
          '[class*="nick"]',
          '[class*="avatar"] [class*="name"]',
        ]
        for (const sel of selectors) {
          try {
            const el = await page.$(sel)
            const text = await el?.textContent()
            if (text && text.trim().length > 0) {
              console.log(`[LocalAuth] ${platform} 昵称提取成功: ${text.trim()}`)
              return text.trim().slice(0, 30)
            }
          } catch {
            // continue
          }
        }
        break
      }
    }

    // 通用兜底：尝试读取页面 <title>
    try {
      const title = await page.title()
      if (title && title.length > 0 && title.length < 60) {
        console.log(`[LocalAuth] 从页面标题提取昵称: ${title}`)
        return title.slice(0, 30)
      }
    } catch {
      // ignore
    }
  } catch (err: any) {
    console.warn('[LocalAuth] 昵称提取失败:', err.message)
  }

  return '未知用户'
}

// ==================== 服务端 API 调用 ====================

/**
 * 通用的带认证头的 fetch 封装。
 * 支持自动 JSON 解析与错误处理。
 */
async function apiFetch(
  url: string,
  options: RequestInit & { token?: string } = {}
): Promise<any> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  }

  if (options.token) {
    headers['Authorization'] = `Bearer ${options.token}`
    delete (options as any).token
  }

  const res = await fetch(url, { ...options, headers })
  const text = await res.text()

  let data: any
  try {
    data = JSON.parse(text)
  } catch {
    data = { _raw: text }
  }

  if (!res.ok) {
    const detail = data?.detail || data?.message || `HTTP ${res.status}`
    throw new Error(detail)
  }

  return data
}

/**
 * 调用服务端 /api/client/accounts/bind/start 获取登录 URL。
 * 如果服务端不可达，回退到硬编码的平台 URL。
 */
async function fetchBindStart(
  serverBaseUrl: string,
  token: string,
  platform: string,
  deviceId: string,
  accountId?: number
): Promise<{ login_url: string; home_url: string }> {
  if (AI_GEO_PLATFORMS.has(platform)) {
    const fallback = PLATFORM_URLS[platform]
    if (fallback) return fallback
  }

  try {
    console.log('[LocalAuth] 请求服务端获取登录 URL...')
    const response = await apiFetch(`${serverBaseUrl}/api/client/accounts/bind/start`, {
      method: 'POST',
      token,
      body: JSON.stringify({ platform, device_id: deviceId, account_id: accountId }),
    })
    const data = response?.data || response
    const fallback = PLATFORM_URLS[platform]
    console.log('[LocalAuth] 服务端返回 URL:', data)
    return {
      login_url: data.login_url || fallback?.login_url,
      home_url: data.home_url || fallback?.home_url || data.login_url || fallback?.login_url,
    }
  } catch (err: any) {
    console.warn('[LocalAuth] 服务端 bind/start 失败，使用本地硬编码 URL:', err.message)
    const fallback = PLATFORM_URLS[platform]
    if (fallback) {
      return fallback
    }
    throw new Error(`无法获取平台 ${platform} 的登录 URL：服务端不可达且无本地配置`)
  }
}

/**
 * 调用服务端 /api/client/accounts/bind/confirm 完成帐号绑定确认。
 */
async function fetchBindConfirm(
  serverBaseUrl: string,
  token: string,
  platform: string,
  accountName: string,
  deviceId: string,
  username?: string,
  accountId?: number
): Promise<AccountResponse> {
  console.log('[LocalAuth] 向服务端确认帐号绑定...')
  const body: Record<string, string | number> = {
    platform,
    account_name: accountName,
    device_id: deviceId,
  }
  if (username) {
    body.username = username
  }
  if (accountId) {
    body.account_id = accountId
  }

  const response = await apiFetch(`${serverBaseUrl}/api/client/accounts/bind/confirm`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
  return response?.data || response
}

async function syncAiStorageStateToServer(
  serverBaseUrl: string,
  token: string,
  platform: string,
  storageState: object,
  accountName?: string,
  accountId?: number,
  loginVerification?: LoginProbeResult,
): Promise<void> {
  if (!AI_GEO_PLATFORMS.has(platform)) return
  console.log('[LocalAuth] 同步 AI 平台 storageState 到 AutoGEO 后端...')
  await apiFetch(`${serverBaseUrl}/api/auth/sync-local-storage-state`, {
    method: 'POST',
    token,
    body: JSON.stringify({
      project_id: 1,
      platform,
      storage_state: storageState,
      account_name: accountName,
      account_id: accountId,
      login_verified: Boolean(loginVerification?.ok),
      verification_method: loginVerification?.method,
    }),
  })
  console.log('[LocalAuth] AI 平台 storageState 同步成功')
}

/**
 * 内容平台会话漫游：把绑定得到的登录态加密上传服务器。
 * 同账号其它电脑发布时若本机无会话，会调用下载接口自动拉取（见 publish-engine）。
 */
async function uploadRoamingSession(
  serverBaseUrl: string,
  token: string,
  platform: string,
  accountId: number,
  storageState: object,
): Promise<void> {
  console.log(`[LocalAuth] 上传漫游会话: platform=${platform} accountId=${accountId}`)
  await apiFetch(`${serverBaseUrl}/api/auth/roam-session/upload`, {
    method: 'POST',
    token,
    body: JSON.stringify({
      platform,
      account_id: accountId,
      storage_state: storageState,
    }),
  })
  console.log('[LocalAuth] 漫游会话上传成功')
}

/**
 * 上传指定账号的本地会话到服务器（漫游）。
 * 用于发布后回传刷新过的会话、以及批量同步本机会话。
 * 非当前用户的账号会被服务器 403 拒绝并静默跳过。
 */
export async function uploadLocalSession(
  serverBaseUrl: string,
  token: string,
  platform: string,
  accountId: number,
): Promise<boolean> {
  try {
    const session = loadSession(platform, accountId)
    if (!session) return false
    await apiFetch(`${serverBaseUrl}/api/auth/roam-session/upload`, {
      method: 'POST',
      token,
      body: JSON.stringify({ platform, account_id: accountId, storage_state: session }),
    })
    console.log(`[LocalAuth] 本机会话已上传(漫游): platform=${platform} accountId=${accountId}`)
    return true
  } catch (err: any) {
    // 403（不属于当前用户）/ 404 等一律静默跳过，不阻断主流程
    console.warn(
      `[LocalAuth] 本机会话上传跳过: platform=${platform} accountId=${accountId} ${err?.message || ''}`,
    )
    return false
  }
}

/**
 * 批量上传本机所有内容平台会话到服务器（会话漫游）。
 * 发布引擎启动时调用：历史绑定无需重新扫码，新电脑登录同账号即可直接发布。
 * 文件命名 {platform}_{accountId}.json；AI 平台与平台级旧文件不在此列。
 */
export async function uploadAllLocalSessions(serverBaseUrl: string, token: string): Promise<void> {
  try {
    const dir = getSessionDir()
    const files = fs.existsSync(dir) ? fs.readdirSync(dir) : []
    const tasks: Promise<boolean>[] = []
    for (const name of files) {
      const m = /^(.+)_(\d+)\.json$/.exec(name)
      if (!m) continue
      const platform = m[1]
      const accountId = Number(m[2])
      if (!AI_GEO_PLATFORMS.has(platform) && Number.isInteger(accountId) && accountId > 0) {
        tasks.push(uploadLocalSession(serverBaseUrl, token, platform, accountId))
      }
    }
    const results = await Promise.all(tasks)
    console.log(`[LocalAuth] 本机会话批量上传完成: 成功 ${results.filter(Boolean).length}/${results.length}`)
  } catch (err: any) {
    console.warn('[LocalAuth] 本机会话批量上传异常（忽略）:', err?.message || String(err))
  }
}

// ==================== 核心授权流程 ====================

/**
 * 启动本地浏览器授权流程。
 *
 * 流程：
 *  1. 从服务端获取登录 URL（失败则用硬编码回退）
 *  2. 启动 Chromium 浏览器（可见窗口）
 *  3. 导航到登录页
 *  4. 等用户完成登录（扫码/密码）
 *  5. 保存浏览器会话到本地 JSON
 *  6. 提取用户昵称
 *  7. 调用服务端 bind/confirm 完成绑定
 *  8. 关闭浏览器
 *
 * @param platform 平台标识（zhihu / baijiahao / xiaohongshu / toutiao）
 * @param serverBaseUrl 服务端 API 地址（如 http://127.0.0.1:8000）
 * @param token 用户的 JWT Bearer Token
 * @param deviceId 本地设备 ID
 * @returns 授权结果
 */
export async function startLocalAuth(
  platform: string,
  serverBaseUrl: string,
  token: string,
  deviceId: string,
  accountName?: string,
  accountId?: number
): Promise<AuthResult> {
  console.log(`[LocalAuth] ========== 开始本地授权流程 ==========`)
  console.log(`[LocalAuth] 平台: ${platform}`)
  console.log(`[LocalAuth] 服务端: ${serverBaseUrl}`)

  let browser: Browser | null = null
  let context: BrowserContext | null = null

  try {
    // 1. 获取登录 URL
    const urls = await fetchBindStart(serverBaseUrl, token, platform, deviceId, accountId)
    console.log(`[LocalAuth] 登录页: ${urls.login_url}`)
    console.log(`[LocalAuth] 首页: ${urls.home_url}`)

    // 2. 查找 Chrome 浏览器可执行文件（EXE 打包后 Playwright 自带 chromium 可能不可用）
    const exePath = findChromeExe()
    if (!exePath) {
      return { success: false, platform, error: '未找到 Chrome 浏览器，请安装 Google Chrome 后重试' }
    }
    console.log(`[LocalAuth] Chrome 路径: ${exePath}`)

    // 3. 启动 Chromium 浏览器（可见模式，用户需要交互）
    console.log('[LocalAuth] 正在启动 Chromium 浏览器...')
    browser = await chromium.launch({
      executablePath: exePath,
      headless: false,
      args: [
        // 禁用一些自动化检测标识，避免部分平台反爬
        '--disable-blink-features=AutomationControlled',
        // 使用系统代理（用户可能挂了代理访问外网）
        ...(os.platform() === 'linux' ? ['--no-sandbox'] : []),
      ],
    })

    // 3. 创建上下文（授权登录使用干净会话，登录成功后再按账号覆盖保存）
    context = await browser.newContext({
      // 模拟真实用户代理
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      viewport: { width: 1280, height: 800 },
      locale: 'zh-CN',
    })

    const page = await context.newPage()

    // 4. 导航到登录页面
    console.log(`[LocalAuth] 正在打开登录页: ${urls.login_url}`)
    await page.goto(urls.login_url, { waitUntil: 'domcontentloaded', timeout: 30000 })

    // 5. 等待用户完成登录
    const loggedIn = await waitForLogin(page, platform)

    if (!loggedIn) {
      console.warn('[LocalAuth] 用户未在超时时间内完成登录')
      await context.close()
      await browser.close()
      return {
        success: false,
        platform,
        error: '登录超时，请重试',
      }
    }

    // 登录完成后，跳转到首页以确保 cookies 已完全写入，然后提取昵称
    console.log('[LocalAuth] 登录成功！正在跳转到首页...')
    try {
      if (urls.home_url) {
        await page.goto(urls.home_url, { waitUntil: 'domcontentloaded', timeout: 15000 })
      }
      // 给页面一些时间加载
      await page.waitForTimeout(3000)
    } catch {
      console.warn('[LocalAuth] 跳转首页失败，继续后续流程')
    }

    const loginVerification =
      platform === 'deepseek'
        ? await hasDeepSeekLoginState(page)
        : platform === 'doubao'
          ? await hasDoubaoLoginState(page)
          : undefined

    // 6. 提取登录态（暂不落盘，待拿到 account_id 后按账号保存）
    console.log('[LocalAuth] 正在提取浏览器会话...')
    const state = withBrowserVerifiedLogin(await context.storageState(), platform, loginVerification)

    await syncAiStorageStateToServer(serverBaseUrl, token, platform, state, accountName, accountId, loginVerification)

    // 7. 提取昵称
    const nickname = await extractNickname(page, platform)
    console.log(`[LocalAuth] 提取到昵称: ${nickname}`)

    // 8. 调用服务端确认绑定，拿到最终 account_id
    let bindResult: AccountResponse | null = null
    if (!AI_GEO_PLATFORMS.has(platform)) {
      try {
        bindResult = await fetchBindConfirm(
          serverBaseUrl,
          token,
          platform,
          accountName || nickname,
          deviceId,
          nickname,
          accountId,
        )
        console.log('[LocalAuth] 服务端绑定确认成功:', bindResult)
      } catch (err: any) {
        throw new Error(`服务端账号绑定失败：${err.message || '未知错误'}`)
      }
    }

    // 9. 按账号保存本地会话（同平台多账号互相隔离）
    // 内容平台用服务端 account_id 作隔离键；AI 平台（豆包/千问/DeepSeek）没有 Account 记录，
    // 用 JWT 里的 user_id 作隔离键，避免同机多账号互相覆盖登录态。
    let finalAccountId = bindResult?.account?.id ?? accountId
    if (!finalAccountId && AI_GEO_PLATFORMS.has(platform)) {
      finalAccountId = decodeJwtUserId(token) ?? undefined
    }
    const sessionPath = getSessionPath(platform, finalAccountId)
    fs.writeFileSync(sessionPath, JSON.stringify(state, null, 2), 'utf-8')
    console.log(`[LocalAuth] 会话已保存: ${sessionPath}`)

    // 9.1 内容平台：上传漫游会话到服务器（同账号其它电脑可直接发布，失败不影响本机）
    if (finalAccountId && !AI_GEO_PLATFORMS.has(platform)) {
      uploadRoamingSession(serverBaseUrl, token, platform, finalAccountId, state).catch((err: any) => {
        console.warn('[LocalAuth] 漫游会话上传失败（不影响本机发布）:', err?.message || String(err))
      })
    }

    // 10. 关闭浏览器
    await context.close()
    await browser.close()
    browser = null
    context = null

    console.log(`[LocalAuth] ========== 授权流程完成 ==========`)
    return {
      success: true,
      platform,
      nickname: bindResult?.account?.account_name || accountName || nickname,
    }
  } catch (err: any) {
    console.error('[LocalAuth] 授权流程异常:', err.message)
    const errorMessage = isTargetClosedError(err)
      ? '授权浏览器窗口已关闭，未完成授权'
      : err.message || '未知错误'
    // 确保清理浏览器资源
    try {
      if (context) await context.close()
      if (browser) await browser.close()
    } catch {
      // 忽略关闭时的异常
    }
    return {
      success: false,
      platform,
      error: errorMessage,
    }
  }
}

/**
 * 验证帐号授权状态（检查是否需要重新授权）。
 *
 * @param platform 平台标识
 * @param serverBaseUrl 服务端 API 地址
 * @param token 用户的 JWT Bearer Token
 * @param accountId 服务端帐号 ID
 * @returns 是否活跃、是否需要重新授权
 */
export async function verifyAuth(
  platform: string,
  serverBaseUrl: string,
  token: string,
  accountId: number
): Promise<VerifyResult> {
  console.log(`[LocalAuth] 验证帐号状态: platform=${platform}, accountId=${accountId}`)
  try {
    const response = await apiFetch(
      `${serverBaseUrl}/api/client/accounts/${accountId}/verify-result`,
      {
        method: 'GET',
        token,
      }
    )
    const data: VerifyResult = response?.data || response
    console.log(`[LocalAuth] 验证结果: active=${data.active}, requiresReauth=${data.requires_reauth}`)
    return data
  } catch (err: any) {
    console.error('[LocalAuth] 帐号验证 API 调用失败:', err.message)
    throw new Error(`帐号验证失败: ${err.message}`)
  }
}

/**
 * 通过已有会话重新登录（无需用户交互，直接验证会话是否有效）。
 *
 * 适用场景：用户之前已完成授权，重启应用后需要检查会话是否仍然有效。
 *
 * @param platform 平台标识
 * @param serverBaseUrl 服务端 API 地址
 * @param token 用户的 JWT Bearer Token
 * @param deviceId 本地设备 ID
 * @returns 授权结果
 */
export async function reauthWithSession(
  platform: string,
  serverBaseUrl: string,
  token: string,
  deviceId: string
): Promise<AuthResult> {
  console.log(`[LocalAuth] ========== 使用已有会话重新验证 ==========`)
  console.log(`[LocalAuth] 平台: ${platform}`)

  const sessionPath = getSessionPath(platform)
  if (!fs.existsSync(sessionPath)) {
    return {
      success: false,
      platform,
      error: '本地无已保存的会话',
    }
  }

  let storageState: any
  try {
    storageState = JSON.parse(fs.readFileSync(sessionPath, 'utf-8'))
  } catch {
    return {
      success: false,
      platform,
      error: '会话文件损坏',
    }
  }

  let browser: Browser | null = null
  let context: BrowserContext | null = null

  try {
    const urls = PLATFORM_URLS[platform]
    if (!urls) {
      return { success: false, platform, error: `未知平台: ${platform}` }
    }

    // 无头模式启动，仅验证会话有效性
    const exePath = findChromeExe()
    if (!exePath) {
      return { success: false, platform, error: '未找到 Chrome 浏览器' }
    }
    browser = await chromium.launch({
      executablePath: exePath,
      headless: true,
      args: os.platform() === 'linux' ? ['--no-sandbox'] : [],
    })

    context = await browser.newContext({
      storageState,
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      viewport: { width: 1280, height: 800 },
      locale: 'zh-CN',
    })

    const page = await context.newPage()
    await page.goto(urls.home_url, { waitUntil: 'domcontentloaded', timeout: 20000 })
    await page.waitForTimeout(2000)

    // 检查登录态
    const loggedIn = await waitForLogin(page, platform, 15000)

    // 获取最新 cookies（可能有刷新）
    if (loggedIn) {
      const freshState = await context.storageState()
      fs.writeFileSync(sessionPath, JSON.stringify(freshState, null, 2), 'utf-8')
      console.log('[LocalAuth] 会话仍然有效，已刷新')

      const nickname = await extractNickname(page, platform)

      // 确认绑定仍然有效
      try {
        await fetchBindConfirm(serverBaseUrl, token, platform, nickname, deviceId)
      } catch (err: any) {
        console.warn('[LocalAuth] 绑定确认失败（非致命）:', err.message)
      }

      await context.close()
      await browser.close()

      return { success: true, platform, nickname }
    }

    await context.close()
    await browser.close()

    return {
      success: false,
      platform,
      error: '会话已过期，需要重新登录',
    }
  } catch (err: any) {
    console.error('[LocalAuth] 重新验证异常:', err.message)
    try {
      if (context) await context.close()
      if (browser) await browser.close()
    } catch {
      // ignore
    }
    return {
      success: false,
      platform,
      error: err.message || '未知错误',
    }
  }
}

/**
 * 纯会话验证（真相引擎）——「一键检测所有」专用。
 *
 * 与 reauthWithSession 的区别：**不做任何副作用**：
 *   - 不刷新本地会话文件
 *   - 不上报服务端绑定确认（fetchBindConfirm）
 *   - 不弹窗、不改变任何本地/远端状态
 * 只返回结构化判定结果，由调用方决定如何回写 status。
 *
 * 铁律（与后端 client_publish.report_result / account.check-result 严格一致）：
 *   - waitForLogin 判定为已登录            → { auth_status: 'ok' }          （验证通过）
 *   - 浏览器正常导航，但已弹回登录页        → { auth_status: 'logged_out' } （确定登出）
 *   - 浏览器崩溃 / 网络异常 / 无法启动 /
 *     导航正常但不在登录页也无法确认登录     → { auth_status: 'unknown' }    （绝不据此推断失效）
 */
export interface SessionVerifyResult {
  auth_status: 'ok' | 'logged_out' | 'unknown'
  nickname?: string
  error?: string
}

export async function verifySessionState(platform: string, accountId?: number | null): Promise<SessionVerifyResult> {
  console.log(`[LocalAuth] ========== 验证会话状态（真相引擎）platform=${platform} accountId=${accountId ?? '-'} ==========`)

  const sessionPath = getSessionPath(platform, accountId)
  if (!fs.existsSync(sessionPath)) {
    return { auth_status: 'unknown', error: '本地无已保存的会话' }
  }

  let storageState: any
  try {
    storageState = JSON.parse(fs.readFileSync(sessionPath, 'utf-8'))
  } catch {
    return { auth_status: 'unknown', error: '会话文件损坏' }
  }

  let browser: Browser | null = null
  let context: BrowserContext | null = null

  try {
    const urls = PLATFORM_URLS[platform]
    if (!urls) {
      return { auth_status: 'unknown', error: `未知平台: ${platform}` }
    }

    const exePath = findChromeExe()
    if (!exePath) {
      return { auth_status: 'unknown', error: '未找到 Chrome 浏览器' }
    }

    browser = await chromium.launch({
      executablePath: exePath,
      headless: true,
      args: os.platform() === 'linux' ? ['--no-sandbox'] : [],
    })

    context = await browser.newContext({
      storageState,
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      viewport: { width: 1280, height: 800 },
      locale: 'zh-CN',
    })

    const page = await context.newPage()
    await page.goto(urls.home_url, { waitUntil: 'domcontentloaded', timeout: 20000 })
    await page.waitForTimeout(2000)

    const loggedIn = await waitForLogin(page, platform, 15000)

    if (loggedIn) {
      const nickname = await extractNickname(page, platform).catch(() => undefined)
      await context.close().catch(() => {})
      await browser.close().catch(() => {})
      return { auth_status: 'ok', nickname }
    }

    // 未检测到登录态：只有当 URL 明确落在登录页时才判定为「确定登出」，
    // 否则保持 unknown（可能是检测兜底未命中，而非真的登出，绝不据此猜失效）。
    const finalUrl = page.url()
    const onLoginPage = /(login|signin|sign-in|passport|account\/login|auth\/|sso|oauth|qr|passport\.)/i.test(finalUrl)
    await context.close().catch(() => {})
    await browser.close().catch(() => {})

    if (onLoginPage) {
      console.log(`[LocalAuth] 会话验证：URL 落在登录页 → 确定登出 (${finalUrl})`)
      return { auth_status: 'logged_out', error: '会话已过期，被弹回登录页' }
    }
    console.log(`[LocalAuth] 会话验证：未确认登录态，但也不在登录页 → 无法判定 (${finalUrl})`)
    return { auth_status: 'unknown', error: '未在登录页也未确认登录态（无法判定）' }
  } catch (err: any) {
    console.error('[LocalAuth] 会话验证异常:', err?.message)
    try {
      if (context) await context.close().catch(() => {})
      if (browser) await browser.close().catch(() => {})
    } catch {
      // ignore
    }
    return { auth_status: 'unknown', error: err?.message || '未知错误' }
  }
}
