/**
 * AutoGeo publish engine - shared publisher base.
 *
 * This mirrors the backend publisher contract closely enough for the local EXE:
 * navigate to the platform editor, clear common popups, fill title/body, run
 * optional platform hooks, submit, then return a structured result.
 */

import * as fs from 'fs'
import * as path from 'path'
import type { Page } from 'playwright'

type PublishResult = {
  success: boolean
  url?: string
  platform_url?: string
  error?: string
  error_msg?: string
  manual_required?: boolean
  manual_reason?: string
}

type RateState = {
  timestamps: number[]
}

const RATE_STATE: Record<string, RateState> = {}

export abstract class BasePublisher {
  abstract platform: string
  abstract publishUrl: string
  abstract titleSelector: string
  abstract contentSelector: string

  maxInlineImages = 8
  rateLimit?: { maxPerHour?: number; maxPerDay?: number; minIntervalMinutes?: number }
  loginMarkers?: string[]

  async publish(page: Page, article: any, account: any): Promise<PublishResult> {
    try {
      const rate = this.checkRateLimitPublic(this.platform)
      if (!rate.allowed) {
        return { success: false, error: rate.reason || '发布频率限制' }
      }

      await this.navigateToEditor(page)
      await this.dismissCommonPopups(page)

      const afterNavigateOk = await this.afterNavigate?.(page)
      if (afterNavigateOk === false) {
        return { success: false, error: `${this.platform} 发布页初始化失败` }
      }

      const manualReason = await this.detectManualIntervention(page)
      if (manualReason || this.isLoginPage(page.url())) {
        return {
          success: false,
          manual_required: true,
          manual_reason: manualReason || `${this.platform} 需要登录或人工验证`,
        }
      }

      await this.fillTitle(page, article?.title || '')
      await this.fillContent(page, article?.content || '')

      if (this.handleCover) await this.handleCover(page, article)
      if (this.addTags) await this.addTags(page, article)

      const beforeSubmitOk = await this.beforeSubmit?.(page)
      if (beforeSubmitOk === false) {
        return { success: false, error: `${this.platform} 提交前校验失败` }
      }

      await this.clickPublish(page)
      const url = await this.waitForResult(page)
      this.recordPublishSuccessPublic(this.platform)
      return { success: true, url, platform_url: url }
    } catch (err: any) {
      const reason = err?.message || String(err)
      if (this.looksLikeManualIntervention(reason)) {
        return { success: false, manual_required: true, manual_reason: reason }
      }
      return { success: false, error: reason, error_msg: reason }
    }
  }

  protected async fillTitle(page: Page, title: string): Promise<void> {
    if (!title) return
    const ok = await this.fillEditableBySelectors(page, this.titleSelector, title)
    if (!ok) {
      throw new Error(`${this.platform} 标题输入框未找到或填充失败`)
    }
  }

  protected abstract fillContent(page: Page, content: string | null): Promise<void>
  protected abstract waitForResult(page: Page): Promise<string>

  protected async clickPublish(page: Page): Promise<void> {
    const clicked = await this.findAndClickPublishButton(page)
    if (!clicked) throw new Error(`${this.platform} 发布按钮未找到`)
    await this.clickConfirmIfPresent(page)
  }

  protected async afterNavigate?(page: Page): Promise<boolean>
  protected async handleCover?(page: Page, article?: any): Promise<void>
  protected async beforeSubmit?(page: Page): Promise<boolean>
  protected async addTags?(page: Page, article?: any): Promise<void>

  protected async navigateToEditor(page: Page): Promise<void> {
    await page.goto(this.publishUrl, { waitUntil: 'domcontentloaded', timeout: 45_000 })
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => undefined)
    await page.waitForTimeout(1500)
  }

  protected async fillEditableBySelectors(page: Page, selectorList: string, text: string): Promise<boolean> {
    const selectors = selectorList.split(',').map((s) => s.trim()).filter(Boolean)
    for (const sel of selectors) {
      const nodes = page.locator(sel)
      const count = await nodes.count().catch(() => 0)
      for (let i = 0; i < count; i++) {
        const node = nodes.nth(i)
        if (!(await node.isVisible({ timeout: 800 }).catch(() => false))) continue

        try {
          await node.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined)
          await node.click({ force: true })
          await page.waitForTimeout(150)

          const tagName = await node.evaluate((el: any) => String(el.tagName || '').toLowerCase()).catch(() => '')
          const editable = await node.evaluate((el: any) => Boolean(el.isContentEditable)).catch(() => false)

          if (tagName === 'input' || tagName === 'textarea') {
            await node.fill('')
            await node.fill(text)
          } else if (editable) {
            await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A')
            await page.keyboard.press('Backspace')
            await page.keyboard.insertText(text).catch(async () => {
              await page.keyboard.type(text, { delay: 5 })
            })
          } else {
            const injected = await node.evaluate((el: any, value: string) => {
              const target =
                el.querySelector?.('textarea,input,[contenteditable="true"]') || el
              if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
                target.value = value
                target.dispatchEvent(new Event('input', { bubbles: true }))
                target.dispatchEvent(new Event('change', { bubbles: true }))
                return true
              }
              if (target.isContentEditable) {
                target.textContent = value
                target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }))
                return true
              }
              return false
            }, text)
            if (!injected) continue
          }

          await page.waitForTimeout(250)
          const filledLength = await node
            .evaluate((el: any) => {
              const target = el.querySelector?.('textarea,input,[contenteditable="true"]') || el
              if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') return String(target.value || '').length
              return String(target.innerText || target.textContent || '').length
            })
            .catch(() => 0)
          if (filledLength >= Math.min(Math.max(text.trim().length / 3, 1), 20)) return true
        } catch {
          continue
        }
      }
    }
    return false
  }

  protected markdownToPlainText(content: string, dropFirstH1 = true): string {
    if (!content) return ''
    let text = String(content)
    text = text.replace(/!\[[^\]]*]\([^)]+\)/g, '')
    text = text.replace(/<h[1-6][^>]*>(.*?)<\/h[1-6]>/gis, '\n\n$1\n\n')
    text = text.replace(/<p[^>]*>(.*?)<\/p>/gis, '$1\n\n')
    text = text.replace(/<br\s*\/?>/gi, '\n')
    text = text.replace(/<li[^>]*>(.*?)<\/li>/gis, '\n- $1')
    text = text.replace(/<[^>]+>/g, '')
    text = this.decodeHtml(text)

    const lines = text.split(/\r?\n/).map((raw, index) => {
      let line = raw.trim()
      const heading = /^(#{1,6})\s+(.+)$/.exec(line)
      if (heading) {
        if (dropFirstH1 && index === 0 && heading[1] === '#') return ''
        line = heading[2].trim()
      }
      return line
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/__(.*?)__/g, '$1')
        .replace(/(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)/g, '$1')
        .replace(/_([^_]+)_/g, '$1')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/\[([^\]]+)]\([^)]+\)/g, '$1')
    })

    const cleaned: string[] = []
    let previousEmpty = false
    for (const line of lines) {
      if (!line) {
        if (!previousEmpty) cleaned.push('')
        previousEmpty = true
      } else {
        cleaned.push(line)
        previousEmpty = false
      }
    }
    return cleaned.join('\n').trim()
  }

  protected async findAndClickPublishButton(page: Page): Promise<boolean> {
    const labels = ['发布', '发布文章', '发布博客', '发表', '提交', '确认发布', '立即发布', '保存']
    for (const label of labels) {
      const button = page.getByRole('button', { name: new RegExp(`^\\s*${label}\\s*$`) }).last()
      if ((await button.count()) > 0 && (await button.isVisible({ timeout: 800 }).catch(() => false))) {
        if (!(await button.isEnabled().catch(() => true))) continue
        await button.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined)
        await button.click({ force: true })
        return true
      }
    }

    const selectors = [
      'button:has-text("发布")',
      'button:has-text("发表")',
      'button:has-text("提交")',
      '[role="button"]:has-text("发布")',
      '.publish-btn',
      '.btn-publish',
      '.submit-btn',
      '#publish-btn',
      'button[class*="publish"]',
      'button[class*="submit"]',
    ]
    for (const sel of selectors) {
      const buttons = page.locator(sel)
      const count = await buttons.count().catch(() => 0)
      for (let i = count - 1; i >= 0; i--) {
        const button = buttons.nth(i)
        if (!(await button.isVisible({ timeout: 800 }).catch(() => false))) continue
        if (!(await button.isEnabled().catch(() => true))) continue
        await button.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined)
        await button.click({ force: true })
        return true
      }
    }
    return false
  }

  protected async dismissCommonPopups(page: Page): Promise<void> {
    await page.keyboard.press('Escape').catch(() => undefined)
    const selectors = [
      'button:has-text("知道了")',
      'button:has-text("我知道了")',
      'button:has-text("关闭")',
      'button:has-text("取消")',
      'button:has-text("跳过")',
      '[aria-label="关闭"]',
      '.close-btn',
      '[class*="close"]',
    ]
    for (let round = 0; round < 2; round++) {
      let closed = false
      for (const sel of selectors) {
        const item = page.locator(sel).first()
        if ((await item.count().catch(() => 0)) === 0) continue
        if (!(await item.isVisible({ timeout: 300 }).catch(() => false))) continue
        await item.click({ force: true }).catch(() => undefined)
        closed = true
        await page.waitForTimeout(250)
      }
      if (!closed) break
    }
  }

  protected async clickConfirmIfPresent(page: Page): Promise<void> {
    const labels = ['确认发布', '确定发布', '仍要发布', '确认', '确定', '提交', '发布']
    await page.waitForTimeout(800)
    for (const label of labels) {
      const button = page.getByRole('button', { name: new RegExp(`^\\s*${label}\\s*$`) }).last()
      if ((await button.count()) > 0 && (await button.isVisible({ timeout: 500 }).catch(() => false))) {
        if (!(await button.isEnabled().catch(() => true))) continue
        await button.click({ force: true })
        await page.waitForTimeout(500)
        return
      }
    }
  }

  protected async tryClickButton(
    page: Page,
    labels: string[],
    options: { timeoutMs?: number; exclude?: string[] } = {},
  ): Promise<boolean> {
    const timeout = options.timeoutMs ?? 1000
    const exclude = options.exclude ?? []
    for (const label of labels) {
      const candidates = page.locator(`button:has-text("${label}"), [role="button"]:has-text("${label}"), a:has-text("${label}")`)
      const count = await candidates.count().catch(() => 0)
      for (let i = count - 1; i >= 0; i--) {
        const candidate = candidates.nth(i)
        if (!(await candidate.isVisible({ timeout }).catch(() => false))) continue
        const text = (await candidate.innerText().catch(() => '')).trim()
        if (exclude.some((item) => text.includes(item))) continue
        if (!(await candidate.isEnabled().catch(() => true))) continue
        await candidate.click({ force: true })
        return true
      }
    }
    return false
  }

  protected async detectManualIntervention(page: Page): Promise<string | null> {
    const url = page.url().toLowerCase()
    if (this.isLoginPage(url)) return '需要登录'
    const markers = [
      ...(this.loginMarkers || []),
      '验证码',
      '安全验证',
      '扫码登录',
      '请登录',
      '登录后',
      '操作频繁',
      '账号异常',
    ]
    const body = await page.locator('body').innerText({ timeout: 1500 }).catch(() => '')
    const hit = markers.find((marker) => {
      if (marker.startsWith('text=')) return body.includes(marker.slice(5))
      return body.includes(marker)
    })
    return hit ? `检测到人工介入提示: ${hit.replace(/^text=/, '')}` : null
  }

  protected looksLikeManualIntervention(message: string): boolean {
    return /登录|验证码|验证|扫码|安全|频繁|人工|账号异常|manual|captcha/i.test(message || '')
  }

  protected checkRateLimitPublic(platform: string): { allowed: boolean; reason?: string } {
    const limit = this.rateLimit
    if (!limit) return { allowed: true }

    const now = Date.now()
    const state = (RATE_STATE[platform] ||= { timestamps: [] })
    state.timestamps = state.timestamps.filter((ts) => now - ts < 24 * 60 * 60 * 1000)
    const last = state.timestamps[state.timestamps.length - 1]
    if (last && limit.minIntervalMinutes && now - last < limit.minIntervalMinutes * 60 * 1000) {
      return { allowed: false, reason: `距离上次发布不足 ${limit.minIntervalMinutes} 分钟` }
    }
    if (limit.maxPerHour && state.timestamps.filter((ts) => now - ts < 60 * 60 * 1000).length >= limit.maxPerHour) {
      return { allowed: false, reason: `每小时最多发布 ${limit.maxPerHour} 篇` }
    }
    if (limit.maxPerDay && state.timestamps.length >= limit.maxPerDay) {
      return { allowed: false, reason: `每天最多发布 ${limit.maxPerDay} 篇` }
    }
    return { allowed: true }
  }

  protected recordPublishSuccessPublic(platform: string): void {
    const state = (RATE_STATE[platform] ||= { timestamps: [] })
    state.timestamps.push(Date.now())
  }

  protected async saveDebugSnapshot(page: Page, stage: string): Promise<void> {
    console.debug(`[${this.platform}] debug snapshot skipped: ${stage} ${page.url()}`)
  }

  protected async insertArticleImages(_page: Page, _article: any): Promise<void> {
    // Platform publishers that support inline images can override this hook.
  }

  protected getCoverImagePath(article: any): string | null {
    const candidates = [
      article?.cover_path,
      article?.coverPath,
      article?.cover_image_path,
      article?.coverImagePath,
      article?.cover_url,
      article?.coverUrl,
      ...this.getArticleImagePaths(article),
    ]
    for (const candidate of candidates) {
      const normalized = this.normalizeLocalImagePath(candidate)
      if (normalized) return normalized
    }
    return null
  }

  protected getArticleImagePaths(article: any): string[] {
    const values: any[] = []
    const keys = [
      'image_paths',
      'imagePaths',
      'local_image_paths',
      'localImagePaths',
      'images',
      'image_urls',
      'imageUrls',
    ]

    for (const key of keys) {
      const value = article?.[key]
      if (Array.isArray(value)) {
        values.push(...value)
      } else if (typeof value === 'string') {
        const trimmed = value.trim()
        if (trimmed.startsWith('[')) {
          try {
            const parsed = JSON.parse(trimmed)
            if (Array.isArray(parsed)) values.push(...parsed)
            else values.push(value)
          } catch {
            values.push(value)
          }
        } else {
          values.push(...trimmed.split(/[,\n;]/g))
        }
      }
    }

    const result: string[] = []
    const seen = new Set<string>()
    for (const value of values) {
      const candidate = typeof value === 'string'
        ? value
        : value?.path || value?.local_path || value?.localPath || value?.file_path || value?.filePath || value?.url
      const normalized = this.normalizeLocalImagePath(candidate)
      if (!normalized || seen.has(normalized)) continue
      seen.add(normalized)
      result.push(normalized)
      if (result.length >= this.maxInlineImages) break
    }
    return result
  }

  protected async uploadFilesBySelectors(
    page: Page,
    selectorList: string | string[],
    files: string[],
    label = '图片',
  ): Promise<boolean> {
    const usableFiles = files.map((file) => this.normalizeLocalImagePath(file)).filter((file): file is string => Boolean(file))
    if (usableFiles.length === 0) return false

    const selectors = Array.isArray(selectorList)
      ? selectorList
      : selectorList.split(',').map((selector) => selector.trim()).filter(Boolean)

    for (const selector of selectors) {
      const inputs = page.locator(selector)
      const count = await inputs.count().catch(() => 0)
      for (let i = 0; i < count; i++) {
        const input = inputs.nth(i)
        try {
          await input.setInputFiles(usableFiles)
          await page.waitForTimeout(2500)
          console.log(`[${this.platform}] 已上传${label}: ${usableFiles.length} 个文件 (${selector})`)
          return true
        } catch (err: any) {
          console.debug(`[${this.platform}] 上传${label}失败 (${selector}): ${err?.message ?? err}`)
        }
      }
    }
    return false
  }

  protected async assertNoVisibleText(page: Page, texts: string[], prefix: string): Promise<void> {
    for (const text of texts) {
      const node = page.getByText(text, { exact: false }).first()
      if ((await node.count().catch(() => 0)) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) {
        throw new Error(`${prefix}: ${text}`)
      }
    }
  }

  protected isLoginPage(url: string): boolean {
    const lower = String(url || '').toLowerCase()
    return ['/login', 'signin', '/auth', 'passport', 'account/login'].some((part) => lower.includes(part))
  }

  protected _escapeHtml(text: string): string {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;')
  }

  private decodeHtml(text: string): string {
    return text
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;|&apos;/g, "'")
  }

  private normalizeLocalImagePath(value: any): string | null {
    if (typeof value !== 'string') return null
    let trimmed = value.trim().replace(/^file:\/\//i, '')
    if (/^\/[A-Za-z]:[\\/]/.test(trimmed)) {
      trimmed = trimmed.slice(1)
    }
    if (!trimmed || /^https?:\/\//i.test(trimmed) || /^data:/i.test(trimmed)) return null
    let decoded = trimmed
    try {
      decoded = decodeURIComponent(trimmed)
    } catch {
      decoded = trimmed
    }
    const normalized = path.normalize(decoded)
    const ext = path.extname(normalized).toLowerCase()
    if (!['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'].includes(ext)) return null
    return fs.existsSync(normalized) ? normalized : null
  }
}
