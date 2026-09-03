import { BasePublisher } from './base'
import type { Page } from 'playwright'

export class JianshuPublisher extends BasePublisher {
  platform = 'jianshu'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }
  publishUrl = 'https://www.jianshu.com/writer'
  maxInlineImages = 8

  titleSelector = [
    'input[placeholder*="标题"]',
    'textarea[placeholder*="标题"]',
    'input[name*="title"]',
    '.title-input input',
  ].join(', ')

  contentSelector = [
    '#editor',
    '.public-DraftEditor-content',
    '.ql-editor',
    '.editor-view',
    '[contenteditable="true"]',
    'textarea',
  ].join(', ')

  protected async afterNavigate(page: Page): Promise<boolean> {
    await this.openWriterIfNeeded(page)
    return true
  }

  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) return
    const ok = await this.fillEditableBySelectors(page, this.contentSelector, plain)
    if (!ok) throw new Error('简书正文编辑器未找到或填充失败')
  }

  protected async handleCover(page: Page, article: any): Promise<void> {
    const images = this.getArticleImagePaths(article)
    const cover = this.getCoverImagePath(article)
    const files = cover ? [cover, ...images.filter((image) => image !== cover)] : images
    if (files.length === 0) return

    const uploaded = await this.uploadFilesBySelectors(
      page,
      ['input[type="file"][accept*="image"]', 'input[type="file"]'],
      files.slice(0, this.maxInlineImages),
      '文章图片',
    )
    if (!uploaded) {
      console.warn('[jianshu] 未找到图片上传入口，继续纯文本发布')
    }
  }

  protected async clickPublish(page: Page): Promise<void> {
    const clicked = await this.findAndClickPublishButton(page)
    if (!clicked) throw new Error('简书发布按钮未找到')
    await this.clickConfirmIfPresent(page)
  }

  protected async waitForResult(page: Page): Promise<string> {
    const deadline = Date.now() + 45_000
    while (Date.now() < deadline) {
      const url = page.url()
      if (/jianshu\.com\/p\/[0-9a-z]+/i.test(url) || (!url.includes('/writer') && url.includes('jianshu.com'))) {
        return url
      }
      for (const text of ['发布成功', '已发布', '审核中']) {
        const node = page.getByText(text, { exact: false }).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) return url
      }
      for (const text of ['发布失败', '验证码', '登录', '操作频繁', '安全验证']) {
        const node = page.getByText(text, { exact: false }).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) {
          throw new Error(`简书发布受阻: ${text}`)
        }
      }
      await page.waitForTimeout(1000)
    }
    throw new Error('简书发布结果未确认')
  }

  private async openWriterIfNeeded(page: Page): Promise<void> {
    const candidates = [
      'a:has-text("写文章")',
      'button:has-text("写文章")',
      'a:has-text("新建文章")',
      'button:has-text("新建文章")',
      '[class*="new"]:has-text("文章")',
    ]
    for (const selector of candidates) {
      try {
        const button = page.locator(selector).first()
        if ((await button.count()) > 0 && (await button.isVisible({ timeout: 800 }).catch(() => false))) {
          await button.click({ force: true })
          await page.waitForTimeout(1500)
          return
        }
      } catch {
        continue
      }
    }
  }
}
