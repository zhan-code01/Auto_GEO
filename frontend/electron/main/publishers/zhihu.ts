/**
 * AutoGeo 发布引擎 - 知乎（Zhihu）发布器
 *
 * 对齐后端 backend/services/playwright/publishers/zhihu.py 的关键能力：
 *  - 发布频率限制（每小时3篇、每天10篇、最小间隔3分钟）
 *  - 发布前添加话题（addTags 钩子，对齐 _handle_publish_process 的话题逻辑）
 *  - 发布按钮 + 确认弹窗的多次重试（避免卡在 edit 页）
 *  - 结果判定（对齐 _wait_for_publish_result）：
 *      · URL 命中 /p/<id> 即视为成功（含 /p/<id>/edit，文章已创建）
 *      · 或出现「发布成功/文章已发布/审核中」提示
 *      · 超时兜底：URL 含 /p/ 即算成功，避免「实际已发布却被误报超时失败」
 *      · 检测限流/验证文字 → 立即判失败
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

export class ZhihuPublisher extends BasePublisher {
  platform = 'zhihu'
  publishUrl = 'https://zhuanlan.zhihu.com/write'
  maxInlineImages = 8

  // 对齐后端 ZhihuPublisher 频率限制（MAX_PER_HOUR / MAX_PER_DAY / MIN_INTERVAL_MINUTES）
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // 知乎登录态文本标记
  loginMarkers = ['text=登录知乎', 'text=加入知乎', 'text=密码登录', 'text=扫码登录']

  titleSelector = [
    'textarea[placeholder*="标题"]',
    '.WriteIndex-titleInput',
    '.Editable-title textarea',
    '[data-testid="editor-title"] textarea',
  ].join(', ')

  contentSelector = [
    '.public-DraftEditor-content',
    '[data-testid="editor-content"]',
    'div[contenteditable="true"]',
  ].join(', ')

  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) return
    const ok = await this.fillEditableBySelectors(page, this.contentSelector, plain)
    if (!ok) throw new Error('知乎正文编辑器未找到或填充失败')
  }

  protected async handleCover(page: Page, article: any): Promise<void> {
    const cover = this.getCoverImagePath(article)
    if (!cover) return

    const uploaded = await this.uploadFilesBySelectors(
      page,
      ['input[type="file"][accept*="image"]', 'input[type="file"]'],
      [cover],
      '文章图片',
    )
    if (!uploaded) {
      console.warn('[zhihu] 未找到图片上传入口，继续纯文本发布')
    }
  }

  /**
   * 发布前添加话题（对齐后端 _handle_publish_process 的话题逻辑）。
   * 知乎话题在发布面板里，输入后回车或点建议项。失败不致命。
   */
  protected async addTags(page: Page, article?: any): Promise<void> {
    const topic = String(article?.title || '').slice(0, 8) || '科技'
    try {
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      await page.waitForTimeout(500)

      const addTopic = page.locator("button:has-text('添加话题')").first()
      if ((await addTopic.count()) > 0 && (await addTopic.isVisible({ timeout: 2000 }).catch(() => false))) {
        await addTopic.click()
        await page.waitForTimeout(500)
      }

      const input = page.locator("input[placeholder*='话题']").first()
      if ((await input.count()) > 0) {
        await input.fill(topic)
        await page.waitForTimeout(1500)
        const suggestion = page.locator('.Suggestion-item, .PublishPanel-suggestionItem').first()
        if ((await suggestion.count()) > 0 && (await suggestion.isVisible({ timeout: 2000 }).catch(() => false))) {
          await suggestion.click()
        } else {
          await input.press('Enter')
        }
        console.log(`[zhihu] 已添加话题: ${topic}`)
      }
    } catch (err: any) {
      console.warn(`[zhihu] 话题添加失败（非致命）: ${err?.message ?? err}`)
    }
  }

  protected async clickPublish(page: Page): Promise<void> {
    const clicked = await this.clickZhihuPublishButton(page)
    if (!clicked) throw new Error('知乎发布按钮未找到')
    await page.waitForTimeout(1200)
    await this.clickZhihuConfirmIfPresent(page)
    await page.waitForTimeout(1200)

    // 对齐后端 _handle_publish_process：仍在编辑页就再点一次发布（避免卡在 edit 页）
    if (this.isZhihuEditorUrl(page.url())) {
      const finalClicked = await this.clickZhihuPublishButton(page)
      if (finalClicked) {
        await page.waitForTimeout(1200)
        await this.clickZhihuConfirmIfPresent(page)
      }
    }
  }

  protected async waitForResult(page: Page): Promise<string> {
    const deadline = Date.now() + 60_000
    while (Date.now() < deadline) {
      const url = page.url()
      // 1. URL 命中文章页即成功（含 /p/<id>/edit，对齐后端 _wait_for_publish_result L665）
      if (this.isZhihuPublishedArticleUrl(url)) return url
      // 2. 仍在编辑页（/write 新建态）就再点一次发布；
      //    /p/<id>/edit 已被上面 isZhihuPublishedArticleUrl 截获判成功，不会走到这里。
      if (this.isZhihuEditorUrl(url)) {
        const finalClicked = await this.clickZhihuPublishButton(page)
        if (finalClicked) {
          await page.waitForTimeout(1200)
          await this.clickZhihuConfirmIfPresent(page)
        }
      }
      // 3. 成功提示文字
      for (const text of ['发布成功', '文章已发布', '审核中']) {
        const node = page.getByText(text, { exact: false }).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) {
          // 检测到成功提示即判定为发布成功，不再额外要求 URL 必须跳转到 /p/<id> 形式。
          // 知乎有时弹出「发布成功」toast 后不立即跳转，旧逻辑会一直等到超时再报失败。
          console.log(`[zhihu] 检测到成功提示文字: ${text}`)
          return page.url()
        }
      }
      // 4. 受阻文字（验证/登录异常 + 对齐后端限流文字）→ 立即判失败
      //    '发布失败' 不在此列：它可能出现在帮助说明/历史记录里，会导致已发布文章被误判失败。
      for (const text of [
        '验证码',
        '安全验证',
        '请重新登录',
        '操作频繁',
        '近期发布频率过高',
        '请24小时后重试',
        '发布频率过高',
      ]) {
        const node = page.getByText(text, { exact: false }).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) {
          throw new Error(`知乎发布受阻: ${text}`)
        }
      }
      await page.waitForTimeout(1000)
    }
    // 超时兜底（对齐后端 _wait_for_publish_result L694）：
    // URL 已跳到 zhuanlan.zhihu.com 且命中 /p/<id>（含 edit），或出现成功提示 → 视为成功。
    const finalUrl = page.url()
    if (this.isZhihuPublishedArticleUrl(finalUrl)) return finalUrl
    for (const text of ['发布成功', '文章已发布', '审核中']) {
      const node = page.getByText(text, { exact: false }).first()
      if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) {
        console.log(`[zhihu] 超时前检测到成功提示文字: ${text}`)
        return finalUrl
      }
    }
    throw new Error('知乎发布结果未确认')
  }

  /**
   * 文章页判定（对齐后端 _wait_for_publish_result 的 "/p/" in url）：
   * hostname 必须是 zhuanlan.zhihu.com，pathname 以 /p/<id> 开头即可。
   * 注意：/p/<id>/edit 也算成功 —— 后端认为文章已创建即成功，避免误报失败。
   */
  protected isZhihuPublishedArticleUrl(url: string): boolean {
    try {
      const parsed = new URL(url)
      if (parsed.hostname.toLowerCase() !== 'zhuanlan.zhihu.com') return false
      return /^\/p\/\d+(?:\/edit)?\/?$/i.test(parsed.pathname)
    } catch {
      return false
    }
  }

  protected isZhihuEditorUrl(url: string): boolean {
    try {
      const parsed = new URL(url)
      if (parsed.hostname.toLowerCase() !== 'zhuanlan.zhihu.com') return false
      return parsed.pathname === '/write' || /^\/p\/\d+\/edit\/?$/i.test(parsed.pathname)
    } catch {
      return false
    }
  }

  private async clickZhihuPublishButton(page: Page): Promise<boolean> {
    const exactNames = [/^\s*发布\s*$/u, /^\s*发布文章\s*$/u, /^\s*发表\s*$/u, /^\s*立即发布\s*$/u, /^\s*确认发布\s*$/u]
    for (const name of exactNames) {
      const button = page.getByRole('button', { name }).last()
      if ((await button.count()) > 0 && (await button.isVisible({ timeout: 1000 }).catch(() => false))) {
        if (!(await button.isEnabled().catch(() => true))) continue
        await button.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {})
        await button.click({ force: true })
        return true
      }
    }

    const selectors = [
      'button:has-text("发布")',
      'button:has-text("发表")',
      '[role="button"]:has-text("发布")',
      '[role="button"]:has-text("发表")',
    ]
    for (const sel of selectors) {
      const buttons = page.locator(sel)
      const count = await buttons.count().catch(() => 0)
      for (let i = count - 1; i >= 0; i--) {
        const button = buttons.nth(i)
        if (!(await button.isVisible({ timeout: 1000 }).catch(() => false))) continue
        if (!(await button.isEnabled().catch(() => true))) continue
        const text = (await button.innerText().catch(() => '')).trim()
        if (!/^(发布|发布文章|发表|立即发布|确认发布)$/u.test(text)) continue
        await button.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {})
        await button.click({ force: true })
        return true
      }
    }
    return false
  }

  private async clickZhihuConfirmIfPresent(page: Page): Promise<void> {
    const names = [/^\s*确认发布\s*$/u, /^\s*确定发布\s*$/u, /^\s*仍要发布\s*$/u, /^\s*确认\s*$/u, /^\s*确定\s*$/u]
    await page.waitForTimeout(800)
    for (const name of names) {
      const button = page.getByRole('button', { name }).last()
      if ((await button.count()) > 0 && (await button.isVisible({ timeout: 1000 }).catch(() => false))) {
        if (!(await button.isEnabled().catch(() => true))) continue
        await button.click({ force: true })
        await page.waitForTimeout(500)
        return
      }
    }
  }
}
