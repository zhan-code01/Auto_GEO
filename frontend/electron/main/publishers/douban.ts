/**
 * AutoGeo 发布引擎 - 豆瓣（Douban）发布器
 *
 * 豆瓣日记发布器，继承 BasePublisher。
 * 入口: https://www.douban.com/note
 *
 * 平台特点：
 *  - 豆瓣是社交+日记平台，写日记是最贴近"发布文章"的能力
 *  - 编辑器相对简陋：标题是 input，正文是 textarea 或 contenteditable
 *  - 发布成功后 URL 跳到 /note/<id>/ 形式
 *  - 豆瓣对发布频率有限制（每小时 5 篇 / 每天 20 篇），
 *    由后端 ArticleApi 处理，本类不重复
 *
 * 注意事项：
 *  - 豆瓣首页对未登录用户会拦截到登录页
 *    → 基类 isLoginPage 会检测出 "login"，返回 manual_required
 *  - 豆瓣日记编辑器对内容长度有限制（最长 50000 字），
 *    由后端 article 控制器控制，本类不截断
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  豆瓣发布器
// ============================================================

export class DoubanPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'douban'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 豆瓣日记编辑器 ----
  publishUrl = 'https://www.douban.com/note'

  // ---- 标题选择器（多 fallback，对齐后端） ----
  titleSelector = [
    'input[placeholder*="标题"]',
    'input[name*="title"]',
    'input.note-title',
    '#title',
  ].join(', ')

  // ---- 正文编辑器选择器（textarea / contenteditable） ----
  contentSelector = [
    'textarea[name*="content"]',
    'textarea[name*="text"]',
    '#content',
    '[contenteditable="true"]',
    '.note-editor',
  ].join(', ')

  // ==========================================================
  //  正文填写（豆瓣专用）
  // ==========================================================

  /**
   * 豆瓣正文通常是 textarea（#content），少数版本是 contenteditable。
   *  - textarea：用 page.fill（最快）
   *  - contenteditable：退化为 keyboard.type
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    const selectors = this.contentSelector.split(',').map((s) => s.trim())
    let editor: ReturnType<Page['locator']> | null = null
    let tagName = ''
    for (const sel of selectors) {
      try {
        const loc = page.locator(sel).first()
        if ((await loc.count()) === 0) continue
        if (!(await loc.isVisible({ timeout: 2000 }).catch(() => false))) continue
        tagName = ((await loc.evaluate((el) => el.tagName.toLowerCase())) as string) || ''
        editor = loc
        break
      } catch {
        continue
      }
    }

    if (!editor) {
      console.warn(`[${this.platform}] 未找到豆瓣正文编辑器`)
      return
    }

    await editor.scrollIntoViewIfNeeded().catch(() => {})
    await editor.click()
    await page.waitForTimeout(500)

    if (tagName === 'input' || tagName === 'textarea') {
      await (editor as any).fill('')
      await (editor as any).fill(plain)
      console.log(`[${this.platform}] 正文已通过 fill 填入 ${tagName}，共 ${plain.length} 字符`)
    } else {
      await page.keyboard.press('Control+A').catch(() => {})
      await page.keyboard.press('Backspace').catch(() => {})
      await page.keyboard.type(plain, { delay: 10 })
      console.log(`[${this.platform}] 正文已通过 keyboard.type 填入 ${tagName}，共 ${plain.length} 字符`)
    }
  }

  // ==========================================================
  //  点击发布（豆瓣专用）
  // ==========================================================

  /**
   * 豆瓣日记发布按钮文案通常是"发布" / "发布日记" / "保存"。
   * 点击后可能弹出"确认发布"对话框。
   */
  protected async clickPublish(page: Page): Promise<void> {
    const btnSelectors = [
      'button:has-text("发布")',
      'button:has-text("发布日记")',
      'button:has-text("保存")',
      '.publish-btn',
      '.btn-publish',
    ]

    let clicked = false
    for (const sel of btnSelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) === 0) continue
        if (!(await btn.isVisible({ timeout: 2000 }).catch(() => false))) continue
        await btn.scrollIntoViewIfNeeded().catch(() => {})
        await btn.click()
        clicked = true
        console.log(`[${this.platform}] 点击发布按钮: ${sel}`)
        break
      } catch {
        continue
      }
    }

    if (!clicked) {
      console.warn(`[${this.platform}] 未找到专属发布按钮，尝试基类逻辑`)
      await this.findAndClickPublishButton(page)
    }

    // 处理可能的确认弹窗
    await page.waitForTimeout(1500)

    const confirmSelectors = [
      'button:has-text("确定")',
      'button:has-text("确认")',
      'button:has-text("发布")',
      '.modal-confirm button',
      '[role="dialog"] button:has-text("确定")',
    ]
    for (const sel of confirmSelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 1500 }).catch(() => false))) {
          await btn.click()
          console.log(`[${this.platform}] 点击确认按钮: ${sel}`)
          break
        }
      } catch {
        continue
      }
    }
  }

  // ==========================================================
  //  等待发布结果（豆瓣专用）
  // ==========================================================

  /**
   * 豆瓣日记发布成功后 URL 会跳到 https://www.douban.com/note/<id>/
   * 优先等 URL 切换，再兜底"发布成功"提示。
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['发布成功', '已发布']

    const deadline = Date.now() + 30_000
    while (Date.now() < deadline) {
      const url = page.url()

      // 命中日记详情 URL 模式
      if (/\/note\/\d+/.test(url) && !url.includes('edit')) {
        console.log(`[${this.platform}] URL 已跳到日记详情: ${url}`)
        return url
      }

      // 检测成功提示
      for (const t of successTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
            console.log(`[${this.platform}] 检测到发布成功提示: ${t} → ${url}`)
            return url
          }
        } catch {
          continue
        }
      }
      await page.waitForTimeout(1000)
    }

    const finalUrl = page.url()
    console.warn(`[${this.platform}] 等待发布结果超时，返回当前 URL: ${finalUrl}`)
    return finalUrl
  }
}
