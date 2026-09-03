import type { Page } from 'playwright'
import { BasePublisher } from './base'

export class DouyinPublisher extends BasePublisher {
  platform = 'douyin'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }
  publishUrl = 'https://creator.douyin.com/creator-micro/content/post/image'
  maxInlineImages = 9

  titleSelector = [
    'input[placeholder*="标题"]',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="作品标题"]',
    'input[placeholder*="添加标题"]',
    '[class*="title"] input',
    '[class*="caption"] input',
  ].join(', ')

  contentSelector = [
    'textarea[placeholder*="描述"]',
    'textarea[placeholder*="添加"]',
    'textarea[placeholder*="正文"]',
    'textarea[placeholder*="内容"]',
    '[class*="description"] textarea',
    '[class*="desc"] textarea',
    '.ql-editor',
    '.ProseMirror',
    'div[contenteditable="true"]',
    '[contenteditable="true"]',
  ].join(', ')

  protected async afterNavigate(page: Page): Promise<boolean> {
    await this.dismissCommonPopups(page)
    await this.tryEnterImageTextMode(page)
    return true
  }

  protected async handleCover(page: Page, article: any): Promise<void> {
    const images = this.getArticleImagePaths(article)
    if (images.length === 0) {
      const cover = this.getCoverImagePath(article)
      if (cover) images.push(cover)
    }
    if (images.length === 0) {
      throw new Error('抖音图文发布需要至少一张本地图片，请先生成或选择封面/配图')
    }

    const uploaded = await this.uploadFilesBySelectors(
      page,
      [
        'input[type="file"][accept*="image"]',
        'input[type="file"][accept*=".jpg"]',
        'input[type="file"]',
      ],
      images.slice(0, this.maxInlineImages),
      '图文图片',
    )
    if (!uploaded) {
      throw new Error('抖音图片上传入口未找到或上传失败')
    }
  }

  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) return

    const filled = await this.fillEditableBySelectors(page, this.contentSelector, plain)
    if (!filled) {
      throw new Error('抖音正文/描述编辑器未找到或填充失败')
    }
  }

  protected async clickPublish(page: Page): Promise<void> {
    await this.dismissCommonPopups(page)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)).catch(() => undefined)
    await page.waitForTimeout(800)

    const clicked = await this.findAndClickPublishButton(page)
    if (!clicked) {
      throw new Error('抖音发布按钮未找到')
    }

    await this.clickConfirmIfPresent(page)
  }

  protected async waitForResult(page: Page): Promise<string> {
    const deadline = Date.now() + 90_000
    const successTexts = ['发布成功', '提交成功', '发布完成', '作品已发布', '审核中']
    const failureTexts = ['发布失败', '上传失败', '内容违规', '验证码', '安全验证', '操作频繁', '请上传', '未上传']

    while (Date.now() < deadline) {
      await page.waitForTimeout(1_500)

      const url = page.url()
      const text = await page.locator('body').innerText({ timeout: 3_000 }).catch(() => '')

      const failure = failureTexts.find((item) => text.includes(item))
      if (failure) {
        throw new Error(`抖音发布失败或需要人工处理: ${failure}`)
      }

      if (successTexts.some((item) => text.includes(item))) {
        return url
      }

      if (/creator\.douyin\.com/.test(url) && /(content|manage|data|home)/i.test(url) && !/content\/upload/i.test(url)) {
        return url
      }
    }

    throw new Error('抖音发布结果等待超时')
  }

  private async tryEnterImageTextMode(page: Page): Promise<void> {
    if (!/content\/post\/image/i.test(page.url())) {
      await page.goto('https://creator.douyin.com/creator-micro/content/post/image', {
        waitUntil: 'domcontentloaded',
        timeout: 30_000,
      }).catch(() => undefined)
      await page.waitForTimeout(1500)
    }

    const candidates = [
      'button:has-text("图文")',
      'a:has-text("图文")',
      'div:has-text("图文发布")',
      'button:has-text("发布图文")',
      'a:has-text("发布图文")',
      'button:has-text("图片")',
    ]

    for (const selector of candidates) {
      const item = page.locator(selector).first()
      if (await item.isVisible({ timeout: 1_000 }).catch(() => false)) {
        await item.click({ timeout: 5_000 }).catch(() => undefined)
        await page.waitForTimeout(1_000)
        break
      }
    }
  }
}
