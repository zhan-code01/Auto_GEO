/**
 * AutoGeo publish engine - CSDN publisher.
 *
 * The flow is intentionally aligned with backend/services/playwright/publishers/csdn.py:
 * close editor overlays, fill title/body, optionally add tags, click the precise
 * publish button, confirm the dialog if present, then treat either CSDN success
 * URLs or success toasts as a successful publish.
 */

import type { Page } from 'playwright'
import { BasePublisher } from './base'

export class CsdnPublisher extends BasePublisher {
  platform = 'csdn'
  publishUrl = 'https://mp.csdn.net/mp_blog/creation/editor'
  maxInlineImages = 8
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }
  loginMarkers = ['text=登录', 'text=登录CSDN', 'text=扫码登录']

  titleSelector = [
    'input[placeholder*="请输入文章标题"]',
    'textarea[placeholder*="请输入文章标题"]',
    'input[placeholder*="标题"]',
    'textarea[placeholder*="标题"]',
    '.article-bar__title input',
    '.article-title input',
    '#txtTitle',
  ].join(', ')

  contentSelector = [
    '.editor-content',
    '.editor-body',
    '.w-e-text-container [contenteditable="true"]',
    '.bytemd-editor .CodeMirror textarea',
    '.CodeMirror textarea',
    '.cm-content[contenteditable="true"]',
    'textarea[placeholder*="正文"]',
    'textarea[placeholder*="内容"]',
    'div[contenteditable="true"]',
  ].join(', ')

  protected async afterNavigate(page: Page): Promise<boolean> {
    await this.dismissCommonPopups(page)
    await this.closeCsdnGuide(page)
    await this.openEditorIfNeeded(page)
    return true
  }

  protected async fillContent(page: Page, content: string): Promise<void> {
    const cleanContent = this.markdownToPlainText(content || '')
    if (!cleanContent) return
    const filled = await this.fillEditableBySelectors(page, this.contentSelector, cleanContent)
    if (!filled) throw new Error('CSDN 正文编辑器未找到或填充失败')
  }

  protected async handleCover(page: Page, article: any): Promise<void> {
    const images = this.getArticleImagePaths(article)
    const cover = this.getCoverImagePath(article)
    const files = cover ? [cover, ...images.filter((image) => image !== cover)] : images
    if (files.length === 0) return

    const uploaded = await this.uploadFilesBySelectors(
      page,
      [
        'input[type="file"][accept*="image"]',
        'input[type="file"][accept*=".png"]',
        'input[type="file"]',
      ],
      files.slice(0, this.maxInlineImages),
      '文章图片',
    )
    if (!uploaded) {
      console.warn('[csdn] 未找到图片上传入口，继续纯文本发布')
    }
  }

  protected async addTags(page: Page, article?: any): Promise<void> {
    const tags = this.deriveTags(article, article?.title || '', article?.content || '')
    if (!tags.length) return

    try {
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      await page.waitForTimeout(500)

      const addBtn = page
        .locator('button:has-text("添加文章标签"), span:has-text("添加文章标签"), [role="button"]:has-text("添加文章标签")')
        .first()
      if ((await addBtn.count()) > 0 && (await addBtn.isVisible({ timeout: 2000 }).catch(() => false))) {
        await addBtn.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined)
        await addBtn.click()
        await page.waitForTimeout(500)
      }

      const tagInput = page
        .locator('input[placeholder*="标签"], input[placeholder*="添加"], input[placeholder*="Enter"], input[placeholder*="文章标签"]')
        .first()
      if ((await tagInput.count()) === 0) return

      for (const tag of tags) {
        await tagInput.click()
        await tagInput.fill('')
        await tagInput.fill(tag)
        await page.waitForTimeout(300)
        await tagInput.press('Enter')
        await page.waitForTimeout(500)
      }
      await page.keyboard.press('Escape').catch(() => undefined)
    } catch (err: any) {
      console.warn(`[csdn] 添加标签失败（非致命）: ${err?.message ?? err}`)
    }
  }

  protected async clickPublish(page: Page): Promise<void> {
    await this.dismissCommonPopups(page)
    await this.closeCsdnGuide(page)

    for (const name of ['发布博客', '发布文章', '保存并发布', '发布']) {
      try {
        const btn = page.getByRole('button', { name }).last()
        if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 3000 }).catch(() => false))) {
          if (await this.isDisabled(btn)) continue
          await btn.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined)
          await btn.click({ force: true })
          await page.waitForTimeout(2000)
          await this.clickPublishConfirmationInDialog(page)
          return
        }
      } catch {
        continue
      }
    }

    const clicked = await this.findAndClickPublishButton(page)
    if (!clicked) throw new Error('CSDN 发布按钮未找到')
    await this.clickConfirmIfPresent(page)
  }

  protected async waitForResult(page: Page): Promise<string> {
    const deadline = Date.now() + 60_000
    const successTexts = ['发布成功', '文章已发布', '已发布', '保存成功', '审核中']
    const failureTexts = ['发布失败', '验证码', '安全验证', '请登录', '操作频繁', '标题不能为空', '内容不能为空']

    while (Date.now() < deadline) {
      await page.waitForTimeout(1500)
      const url = page.url()
      if (/creation\/success\//i.test(url) || /blog\.csdn\.net\/.+\/article\/details\/\d+/i.test(url)) {
        return url
      }
      const text = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '')
      if (successTexts.some((item) => text.includes(item))) return url
      const failure = failureTexts.find((item) => text.includes(item))
      if (failure) throw new Error(`CSDN 发布失败或需要人工处理: ${failure}`)
    }
    throw new Error('CSDN 发布结果等待超时')
  }

  private deriveTags(article: any, title: string, content: string): string[] {
    const raw = (Array.isArray(article?.tags) ? article.tags : [])
      .concat(Array.isArray(article?.keywords) ? article.keywords : [])
      .map((tag: any) => String(tag))
    const fromText = `${title}\n${this.markdownToPlainText(content)}`.match(/[\u4e00-\u9fffA-Za-z0-9]{2,12}/g) || []
    const stop = new Set(['我们', '你们', '他们', '这个', '那个', '可以', '进行', '使用', '文章', '内容', '标题'])
    const result: string[] = []
    const seen = new Set<string>()
    for (const word of [...raw, ...fromText]) {
      const clean = String(word).replace(/[^\w\u4e00-\u9fff]/g, '').trim()
      if (!clean || seen.has(clean) || stop.has(clean)) continue
      result.push(clean.slice(0, 12))
      seen.add(clean)
      if (result.length >= 3) break
    }
    return result
  }

  private async clickPublishConfirmationInDialog(page: Page): Promise<void> {
    try {
      const clicked = await page.evaluate(() => {
        const visible = (el: Element | null): boolean => {
          if (!el) return false
          const rect = el.getBoundingClientRect()
          const style = window.getComputedStyle(el)
          return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden'
        }
        const scopes = Array.from(
          document.querySelectorAll("[role='dialog'], .el-dialog, .el-drawer, [class*='modal'], [class*='dialog'], [class*='drawer']"),
        ).filter(visible)
        const labels = ['确认发布', '保存并发布', '发布文章', '发布博客', '发布']
        for (const scope of scopes) {
          const buttons = Array.from(scope.querySelectorAll('button, [role="button"]')).filter(visible)
          const target = buttons.find((button) => {
            const el = button as HTMLElement
            const text = (el.innerText || el.textContent || '').replace(/\s+/g, '').trim()
            if (!labels.includes(text)) return false
            const disabled =
              (button as HTMLButtonElement).disabled ||
              button.getAttribute('disabled') !== null ||
              button.getAttribute('aria-disabled') === 'true' ||
              /disabled|is-disabled/.test(String(button.className || ''))
            return !disabled
          })
          if (target) {
            ;(target as HTMLElement).click()
            return true
          }
        }
        return false
      })
      if (clicked) await page.waitForTimeout(1500)
    } catch (err: any) {
      console.debug(`[csdn] 发布确认弹窗处理失败: ${err?.message ?? err}`)
    }
  }

  private async isDisabled(locator: any): Promise<boolean> {
    try {
      return Boolean(
        await locator.evaluate((el: any) => {
          return (
            el.disabled ||
            el.getAttribute('disabled') !== null ||
            el.getAttribute('aria-disabled') === 'true' ||
            /disabled|is-disabled/.test(String(el.className || ''))
          )
        }),
      )
    } catch {
      return false
    }
  }

  private async closeCsdnGuide(page: Page): Promise<void> {
    await page.keyboard.press('Escape').catch(() => undefined)
    const guideClose = [
      'div[class*="guide"] button',
      'div[class*="driver"] button',
      'div[class*="mask"]',
      'div[class*="overlay"]',
      'span[class*="skip"]',
      'button:has-text("跳过")',
      'button:has-text("知道了")',
      'button:has-text("我知道了")',
    ]
    for (const sel of guideClose) {
      const item = page.locator(sel).first()
      if ((await item.count().catch(() => 0)) > 0 && (await item.isVisible({ timeout: 300 }).catch(() => false))) {
        await item.click({ force: true }).catch(() => undefined)
        await page.waitForTimeout(300)
      }
    }
  }

  private async openEditorIfNeeded(page: Page): Promise<void> {
    const currentUrl = page.url()
    if (/editor|creation/i.test(currentUrl)) return

    const candidates = [
      'a:has-text("写文章")',
      'button:has-text("写文章")',
      'a:has-text("发布文章")',
      'button:has-text("发布文章")',
      'a:has-text("创作")',
      'button:has-text("创作")',
    ]

    for (const selector of candidates) {
      const element = page.locator(selector).first()
      if (await element.isVisible({ timeout: 1000 }).catch(() => false)) {
        await element.click({ timeout: 5000 }).catch(() => undefined)
        await page.waitForLoadState('domcontentloaded', { timeout: 10_000 }).catch(() => undefined)
        await page.waitForTimeout(1000)
        break
      }
    }
  }
}
