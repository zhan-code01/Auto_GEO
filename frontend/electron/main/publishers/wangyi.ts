/**
 * AutoGeo 发布引擎 - 网易号（Wangyi）发布器
 *
 * 网易号媒体开放平台发布器，继承 BasePublisher。
 * 入口: https://mp.163.com/admin/article/publish
 *
 * 平台特点：
 *  - 网易号是网易号媒体平台，编辑器是 Quill 类富文本
 *  - 标题是普通 input（#title / .article-title）
 *  - 正文是 contenteditable（.ql-editor / .article-editor）
 *  - 发布按钮文案有"发布" / "立即发布" / "提交"
 *
 * 注意事项：
 *  - 网易号对未登录用户会重定向到 login.html
 *    → 基类 isLoginPage 会检测出 "login"，返回 manual_required
 *  - 网易号有发布频率限制（每小时 5 篇 / 每天 30 篇），
 *    由后端 ArticleApi 处理，本类不重复
 *  - 发布成功后会弹"发布成功"提示，但 URL 通常不变（在发布管理列表）
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  网易号发布器
// ============================================================

export class WangyiPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'wangyi'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 网易号文章发布页 ----
  publishUrl = 'https://mp.163.com/admin/article/publish'

  // ---- 标题选择器（多 fallback，对齐后端） ----
  titleSelector = [
    'input[placeholder*="标题"]',
    'input[name*="title"]',
    'input.article-title',
    '#title',
  ].join(', ')

  // ---- 正文编辑器选择器（Quill / contenteditable） ----
  contentSelector = [
    '.article-content textarea',
    'textarea[name*="content"]',
    '.ql-editor',
    '[contenteditable="true"]',
    '#content',
    '.article-editor',
  ].join(', ')

  // ==========================================================
  //  正文填写（网易号专用）
  // ==========================================================

  /**
   * 网易号正文通常是 .ql-editor (Quill) 富文本，无法 fill。
   * 优先聚焦 + keyboard.insertText，回退 keyboard.type。
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    const selectors = this.contentSelector.split(',').map((s) => s.trim())
    let focused = false
    for (const sel of selectors) {
      try {
        const editor = page.locator(sel).first()
        if ((await editor.count()) === 0) continue
        if (!(await editor.isVisible({ timeout: 2000 }).catch(() => false))) continue
        await editor.scrollIntoViewIfNeeded().catch(() => {})
        await editor.click()
        await page.waitForTimeout(500)
        focused = true
        break
      } catch {
        continue
      }
    }

    if (!focused) {
      console.warn(`[${this.platform}] 未找到网易号正文编辑器`)
      return
    }

    // 清空
    await page.keyboard.press('Control+A').catch(() => {})
    await page.keyboard.press('Backspace').catch(() => {})

    // 优先用 keyboard.insertText（Playwright 标准粘贴 API，对换行更友好）
    try {
      await page.keyboard.insertText(plain)
      console.log(`[${this.platform}] 正文已通过 insertText 填入，共 ${plain.length} 字符`)
    } catch {
      // 兜底逐字符输入
      await page.keyboard.type(plain, { delay: 10 })
      console.log(`[${this.platform}] 正文已通过 keyboard.type 填入，共 ${plain.length} 字符`)
    }
  }

  // ==========================================================
  //  点击发布（网易号专用）
  // ==========================================================

  /**
   * 网易号发布按钮文案：发布 / 立即发布 / 提交。
   * 点击后通常有"确认发布"弹窗。
   */
  protected async clickPublish(page: Page): Promise<void> {
    const btnSelectors = [
      'button:has-text("发布")',
      'button:has-text("立即发布")',
      'button:has-text("提交")',
      '.publish-btn',
      '.submit-btn',
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
  //  等待发布结果（网易号专用）
  // ==========================================================

  /**
   * 网易号发布后通常不跳 URL，停留在发布管理列表。
   * 靠"发布成功" / "提交成功" / "已发布" 提示判断。
   * 30 秒兜底超时。
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['发布成功', '已发布', '提交成功']

    const deadline = Date.now() + 30_000
    while (Date.now() < deadline) {
      for (const t of successTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
            const url = page.url()
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
