/**
 * AutoGeo 发布引擎 - 企鹅号（Penguin）发布器
 *
 * 腾讯企鹅号（om.qq.com）发布器，继承 BasePublisher。
 * publish_url: https://om.qq.com/article/articlePublish
 *
 * 平台特点：
 *  - 企鹅号编辑器是 Quill.js（.ql-editor）富文本
 *  - 也支持 contenteditable 的 textarea 回退
 *  - 正文编辑器是 Quill / contenteditable，page.fill 不可用
 *  - 发布按钮叫"发布"/"立即发布"/"提交"
 *  - 发布成功通常会弹出"发布成功"/"已发布"/"提交成功"提示
 *  - URL 不会跳转，停留在文章管理列表
 *
 * 注意事项：
 *  - 后端企鹅号 publisher 没有 selectors 文件，选择器基于 backend/penguin.py 内联列表
 *  - 企鹅号对内容敏感词审核严格，可能直接拒绝发布
 *  - 选 publishUrl 走文章发布页（图文编辑器），如果平台改为视频优先需要重新适配
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  企鹅号发布器
// ============================================================

export class PenguinPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'penguin'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 企鹅号图文编辑器入口 ----
  publishUrl = 'https://om.qq.com/article/articlePublish'

  // ---- 标题选择器（多 fallback） ----
  titleSelector = [
    'input[placeholder*="标题"]',
    'input[name*="title"]',
    '.article-title input',
    'input.article-title',
    '#title',
    'textarea[placeholder*="标题"]',
  ].join(', ')

  // ---- 正文编辑器选择器（Quill / contenteditable / textarea 多重 fallback） ----
  contentSelector = [
    '.article-content textarea',
    'textarea[name*="content"]',
    '.ql-editor',
    '[contenteditable="true"]',
    '#content',
    '.article-editor',
    'textarea[placeholder*="正文"]',
    'textarea[placeholder*="内容"]',
  ].join(', ')

  // ==========================================================
  //  正文填写（企鹅号专用）
  // ==========================================================

  /**
   * 企鹅号编辑器是 Quill.js（contenteditable）。
   * 先点击获取焦点，再通过 keyboard.type 逐字输入。
   * （fill() 只能填 input/textarea，对 contenteditable 无效）
   *
   * 兜底：textarea 用 fill
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    // ---- 1. 找到第一个可用的正文选择器 ----
    const selectors = this.contentSelector.split(',').map((s) => s.trim())
    let filled = false

    for (const sel of selectors) {
      try {
        const editor = page.locator(sel).first()
        if ((await editor.count()) === 0) continue
        if (!(await editor.isVisible({ timeout: 2000 }).catch(() => false))) continue

        // 区分 textarea / contenteditable
        const isTextarea = sel.includes('textarea') || (await editor.evaluate('el => el.tagName.toLowerCase()').catch(() => '')) === 'textarea'

        if (isTextarea) {
          // textarea: 直接 fill
          await editor.fill(plain)
          console.log(`[${this.platform}] 正文已通过 textarea 填入，共 ${plain.length} 字符 (selector: ${sel})`)
        } else {
          // contenteditable: 点击 + keyboard.type
          await editor.scrollIntoViewIfNeeded().catch(() => {})
          await editor.click({ force: true })
          await page.waitForTimeout(500)
          await page.keyboard.press('Control+A').catch(() => {})
          await page.keyboard.press('Backspace').catch(() => {})
          await page.waitForTimeout(300)
          await page.keyboard.type(plain, { delay: 10 })
          console.log(`[${this.platform}] 正文已通过键盘输入，共 ${plain.length} 字符 (selector: ${sel})`)
        }
        filled = true
        break
      } catch {
        continue
      }
    }

    if (!filled) {
      // 兜底用 focus
      try {
        await page.focus(this.contentSelector)
        await page.waitForTimeout(500)
        await page.keyboard.type(plain, { delay: 10 })
        console.log(`[${this.platform}] 正文已通过 focus 兜底输入，共 ${plain.length} 字符`)
      } catch (err) {
        console.warn(`[${this.platform}] 无法定位正文编辑器: ${(err as Error).message}`)
      }
    }
  }

  // ==========================================================
  //  点击发布（企鹅号专用）
  // ==========================================================

  /**
   * 企鹅号发布流程：
   *   1. 点击"发布"/"立即发布"/"提交"按钮
   *   2. 可能弹出二次确认弹窗
   */
  protected async clickPublish(page: Page): Promise<void> {
    // ---- 第一步：找到并点击发布按钮 ----
    const btnSelectors = [
      'button:has-text("立即发布")',
      'button:has-text("发布")',
      'button:has-text("提交")',
      '.publish-btn',
      '.submit-btn',
      'button[class*="publish"]',
      'button[class*="submit"]',
    ]

    let clicked = false
    for (const sel of btnSelectors) {
      try {
        const btn = page.locator(sel).first()
        if (
          (await btn.count()) > 0 &&
          (await btn.isVisible({ timeout: 2000 }).catch(() => false))
        ) {
          await btn.scrollIntoViewIfNeeded().catch(() => {})
          await btn.click({ force: true })
          clicked = true
          console.log(`[${this.platform}] 点击发布按钮: ${sel}`)
          break
        }
      } catch {
        continue
      }
    }

    if (!clicked) {
      console.warn(`[${this.platform}] 未找到发布按钮`)
      return
    }

    // ---- 第二步：处理二次确认弹窗 ----
    await page.waitForTimeout(1500)

    const confirmSelectors = [
      'button:has-text("确定")',
      'button:has-text("确认")',
      'button:has-text("确认发布")',
      'button:has-text("立即发布")',
      '.modal-confirm button',
      '[role="dialog"] button:has-text("确定")',
      '.weui-desktop-dialog__btn-primary',
    ]

    for (const sel of confirmSelectors) {
      try {
        const btn = page.locator(sel).first()
        if (
          (await btn.count()) > 0 &&
          (await btn.isVisible({ timeout: 2000 }).catch(() => false))
        ) {
          await btn.click({ force: true })
          console.log(`[${this.platform}] 点击确认按钮: ${sel}`)
          break
        }
      } catch {
        continue
      }
    }
  }

  // ==========================================================
  //  等待发布结果（企鹅号专用）
  // ==========================================================

  /**
   * 企鹅号发布后通常停留在文章管理列表，URL 不变。
   * 判断逻辑：
   *   1) 页面出现"发布成功"/"已发布"/"提交成功"提示
   *   2) 兜底返回当前 URL
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successKeywords = ['发布成功', '已发布', '提交成功', '发布完成']

    const deadline = Date.now() + 45_000
    while (Date.now() < deadline) {
      for (const kw of successKeywords) {
        try {
          const node = page.getByText(kw, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
            const url = page.url()
            console.log(`[${this.platform}] 检测到发布成功提示: ${kw} → ${url}`)
            return url
          }
        } catch {
          continue
        }
      }

      await page.waitForTimeout(1000)
    }

    // 兜底返回当前 URL
    const finalUrl = page.url()
    console.warn(`[${this.platform}] 等待发布结果超时，返回当前 URL: ${finalUrl}`)
    return finalUrl
  }
}
