import type { Page } from 'playwright'

export interface ManualDetection {
  manualRequired: boolean
  reason?: string
  errorCode?: string
  riskType?: string
  pageUrl?: string
  pageTitle?: string
}

const URL_MARKERS = [
  'login',
  'signin',
  'passport',
  'captcha',
  'verify',
  'security',
  'risk',
  'challenge',
  'auth',
]

interface TextMarker {
  text: string
  code: string
  type: string
  message: string
}

const TEXT_MARKERS: TextMarker[] = [
  // 登录类
  { text: '请登录', code: 'AUTH_REQUIRED', type: 'auth', message: '平台要求登录，请在本地浏览器完成登录后继续' },
  { text: '登录后', code: 'AUTH_REQUIRED', type: 'auth', message: '平台登录态失效，请重新登录后继续' },
  { text: '扫码登录', code: 'AUTH_REQUIRED', type: 'auth', message: '平台要求扫码登录，请在本地浏览器完成扫码' },
  { text: '请重新登录', code: 'AUTH_REQUIRED', type: 'auth', message: '平台要求重新登录' },

  // 验证码类
  { text: '验证码', code: 'CAPTCHA_REQUIRED', type: 'captcha', message: '平台要求验证码验证，请人工完成后继续' },
  { text: '人机验证', code: 'CAPTCHA_REQUIRED', type: 'captcha', message: '平台要求人机验证，请人工完成' },
  { text: '滑块', code: 'CAPTCHA_REQUIRED', type: 'captcha', message: '平台要求滑块验证，请人工完成' },
  { text: '拖动滑块', code: 'CAPTCHA_REQUIRED', type: 'captcha', message: '平台要求拖动滑块验证，请人工完成' },

  // 安全验证类
  { text: '安全验证', code: 'SECURITY_VERIFY', type: 'security', message: '平台要求安全验证，请人工完成' },
  { text: '身份验证', code: 'SECURITY_VERIFY', type: 'security', message: '平台要求身份验证，请人工完成' },
  { text: '短信验证', code: 'SECURITY_VERIFY', type: 'security', message: '平台要求短信验证，请人工完成' },

  // 风控类
  { text: '账号异常', code: 'ACCOUNT_RISK', type: 'risk_control', message: '平台提示账号异常，请人工检查账号状态' },
  { text: '账户异常', code: 'ACCOUNT_RISK', type: 'risk_control', message: '平台提示账户异常，请人工检查' },
  { text: '风险提示', code: 'RISK_CONTROL', type: 'risk_control', message: '平台触发风险提示，请人工确认' },
  { text: '检测到风险', code: 'RISK_CONTROL', type: 'risk_control', message: '平台检测到风险，请人工处置' },
  { text: '异常访问', code: 'RISK_CONTROL', type: 'risk_control', message: '平台提示异常访问，请人工处置' },

  // 频率限制类
  { text: '操作频繁', code: 'RATE_LIMITED', type: 'rate_limited', message: '平台提示操作频繁，请稍后或人工确认' },
  { text: '请求频繁', code: 'RATE_LIMITED', type: 'rate_limited', message: '平台提示请求频繁，请稍后再试' },
  { text: '访问频繁', code: 'RATE_LIMITED', type: 'rate_limited', message: '平台提示访问频繁，请稍后再试' },
  { text: '稍后再试', code: 'RATE_LIMITED', type: 'rate_limited', message: '平台要求稍后再试，可能触发频率限制' },
  { text: '异常请求', code: 'RISK_CONTROL', type: 'risk_control', message: '平台返回异常请求，可能触发风控' },

  // 限制类
  { text: '违反用户使用规范', code: 'ACCOUNT_RESTRICTED', type: 'risk_control', message: '平台提示账号或请求受限，请人工检查' },

  // 豆包专用标记
  { text: '扫码登录', code: 'AUTH_REQUIRED', type: 'auth', message: '豆包要求扫码登录，请在本地浏览器完成扫码' },
  { text: '登录豆包', code: 'AUTH_REQUIRED', type: 'auth', message: '豆包要求登录，请在本地浏览器完成登录' },
  { text: '请使用抖音账号登录', code: 'AUTH_REQUIRED', type: 'auth', message: '豆包要求使用抖音账号登录' },
  { text: '请登录后查看', code: 'AUTH_REQUIRED', type: 'auth', message: '豆包要求登录后才能继续' },

  // 英文标记
  { text: 'complete the verification', code: 'CAPTCHA_REQUIRED', type: 'captcha', message: 'platform requires verification' },
  { text: 'verify you are human', code: 'CAPTCHA_REQUIRED', type: 'captcha', message: 'platform human verification required' },
  { text: 'security verification', code: 'SECURITY_VERIFY', type: 'security', message: 'platform security verification required' },
  { text: 'too many requests', code: 'RATE_LIMITED', type: 'rate_limited', message: 'platform rate limited' },
  { text: 'rate limit', code: 'RATE_LIMITED', type: 'rate_limited', message: 'platform rate limited' },
]

const SELECTOR_MARKERS = [
  'iframe[src*="captcha"]',
  'iframe[src*="verify"]',
  'iframe[src*="challenge"]',
  '[role="dialog"] [class*="captcha"]',
  '[role="dialog"] [id*="captcha"]',
  '[role="dialog"] [class*="verify"]',
  '[role="dialog"] [id*="verify"]',
  '[role="dialog"] [class*="challenge"]',
  '[role="dialog"] [class*="slider"]',
  '[class*="captcha-modal"]',
  '[class*="verify-modal"]',
  // 豆包登录弹窗
  '[class*="login-modal"]',
  '[class*="LoginModal"]',
  '[class*="login-dialog"]',
  '[class*="auth-modal"]',
  'div[class*="web-login"]',
  'div[class*="loginContainer"]',
  '[data-testid*="login"]',
  'header button:has-text("登录")',
  'button[class*="login"]:has-text("登录")',
]

const AUTH_URL_CODES = new Set(['login', 'signin', 'passport', 'auth'])

export function looksLikeManualIntervention(message: string): boolean {
  const text = (message || '').toLowerCase()
  return (
    URL_MARKERS.some((marker) => text.includes(marker)) ||
    TEXT_MARKERS.some((marker) => message.includes(marker.text))
  )
}

export async function detectManualIntervention(
  page: Page,
  platform?: string,
  stage?: string,
): Promise<ManualDetection> {
  const pageUrl = page.url()
  const lowerUrl = pageUrl.toLowerCase()
  let urlSurface = lowerUrl
  try {
    const parsed = new URL(pageUrl)
    // 平台的新对话页可能带有 `?from_login=1` 等正常来源参数。
    // 登录/风控 URL 判断只检查域名和路径，避免把查询参数误判为登录页。
    urlSurface = `${parsed.hostname}${parsed.pathname}`.toLowerCase()
  } catch {
    // 非标准 URL 时保留原始字符串兜底。
  }
  const pageTitle = await page.title().catch(() => '')
  const stageLabel = stage || '当前步骤'
  const platformLabel = platform || '平台'

  // 1. URL 标记
  const urlMarker = URL_MARKERS.find((marker) => urlSurface.includes(marker))
  if (urlMarker) {
    return {
      manualRequired: true,
      reason: `${platformLabel} 在 ${stageLabel} 进入登录或安全验证页面：${pageUrl}`,
      errorCode: AUTH_URL_CODES.has(urlMarker) ? 'AUTH_REQUIRED' : 'SECURITY_VERIFY',
      riskType: urlMarker,
      pageUrl,
      pageTitle,
    }
  }

  // 2. 验证控件选择器
  for (const selector of SELECTOR_MARKERS) {
    try {
      const locator = page.locator(selector).first()
      if ((await locator.count()) > 0 && (await locator.isVisible({ timeout: 500 }).catch(() => false))) {
        const authSelector = /login|auth/i.test(selector)
        return {
          manualRequired: true,
          reason: `${platformLabel} 在 ${stageLabel} 出现验证控件 ${selector}，请人工处理`,
          errorCode: authSelector ? 'AUTH_REQUIRED' : 'CAPTCHA_REQUIRED',
          riskType: authSelector ? 'auth' : 'captcha',
          pageUrl,
          pageTitle,
        }
      }
    } catch {
      // 继续做文本检测
    }
  }

  // 3. 只检查当前可见的弹窗、告警和提示，不扫描历史对话或整页正文。
  const bodyText = await page
    .evaluate(() => {
      const selectors = [
        '[role="dialog"]',
        '[role="alert"]',
        '[aria-live="assertive"]',
        '[class*="toast"]',
        '[class*="Toast"]',
        '[class*="captcha"]',
        '[class*="verify"]',
        '[class*="error-message"]',
      ].join(',')
      return Array.from(document.querySelectorAll(selectors))
        .filter((node) => {
          const element = node as HTMLElement
          const style = window.getComputedStyle(element)
          return element.offsetParent !== null
            && style.display !== 'none'
            && style.visibility !== 'hidden'
            && style.opacity !== '0'
        })
        .map((node) => (node as HTMLElement).innerText || '')
        .join('\n')
        .slice(0, 10000)
    })
    .catch(() => '')
  const hit = TEXT_MARKERS.find((marker) => bodyText.includes(marker.text))
  if (hit) {
    if (hit.type === 'auth' && await hasUsableChatInput(page)) {
      return { manualRequired: false, pageUrl, pageTitle }
    }
    return {
      manualRequired: true,
      reason: `${hit.message}（${platformLabel} / ${stageLabel}）`,
      errorCode: hit.code,
      riskType: hit.type,
      pageUrl,
      pageTitle,
    }
  }

  return { manualRequired: false, pageUrl, pageTitle }
}

async function hasUsableChatInput(page: Page): Promise<boolean> {
  const selectors = [
    'textarea[placeholder*="发消息"]',
    'textarea[placeholder*="DeepSeek"]',
    '[data-testid="chat-input-content-measure"] [contenteditable="true"]',
    '[role="textbox"]',
    'textarea',
    'div[contenteditable="true"]',
  ]
  for (const selector of selectors) {
    const locator = page.locator(selector).last()
    if ((await locator.count().catch(() => 0)) && (await locator.isVisible().catch(() => false))) {
      return true
    }
  }
  return false
}
