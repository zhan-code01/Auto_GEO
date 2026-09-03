/**
 * AutoGeo 发布引擎 - 博客园（Cnblogs）发布器
 *
 * 博客园写博客编辑器，继承 BasePublisher。
 * 入口: https://i.cnblogs.com/EditPosts.aspx
 *
 * 平台特点：
 *  - 博客园编辑器是经典 ASP.NET WebForm 风格 + TinyMCE 类富文本
 *  - 标题是普通 input（#post-title / #txtTitle）
 *  - 正文是 textarea 或 contenteditable（#post-body / #txtContent）
 *  - 后端发布按钮有"发布"/"保存"/"立即发布"几种文案
 *
 * 注意事项：
 *  - 博客园有 #txtContent 和 #post-body 两种 id，新旧版本可能用其一
 *  - 博客园对发布频率较敏感（每小时 10 篇 / 每天 50 篇）
 *    → 限流在 ArticleApi 层处理，本类不重复
 *  - 发布成功后 URL 不会跳到文章页（在博客园后台列表），靠"发布成功"提示判断
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  博客园发布器
// ============================================================

export class CnblogsPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'cnblogs'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 博客园写博编辑器 ----
  publishUrl = 'https://i.cnblogs.com/EditPosts.aspx'

  // ---- 标题选择器（多 fallback，对齐后端） ----
  titleSelector = [
    'input[placeholder*="标题"]',
    'input[name*="title"]',
    '#post-title',
    'input#txtTitle',
    '#txtTitle',
  ].join(', ')

  // ---- 正文编辑器选择器（textarea / contenteditable） ----
  contentSelector = [
    '#post-body',
    '#txtContent',
    'textarea[name*="content"]',
    '.editor-view',
    '.markdown-body',
    '[contenteditable="true"]',
  ].join(', ')

  // ==========================================================
  //  正文填写（博客园专用）
  // ==========================================================

  /**
   * 博客园正文可能是 textarea（#txtContent）也可能是 contenteditable（#post-body）。
   *  - textarea：优先用 page.fill（直接覆盖）
   *  - contenteditable：用 keyboard.type（逐字输入，保留富文本语义）
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    const selectors = this.contentSelector.split(',').map((s) => s.trim())

    // 找到第一个可见的正文编辑器
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
      console.warn(`[${this.platform}] 未找到博客园正文编辑器`)
      return
    }

    await editor.scrollIntoViewIfNeeded().catch(() => {})
    await editor.click()
    await page.waitForTimeout(500)

    if (tagName === 'input' || tagName === 'textarea') {
      // 普通 input/textarea → 直接 fill
      await (editor as any).fill('')
      await (editor as any).fill(plain)
      console.log(`[${this.platform}] 正文已通过 fill 填入 ${tagName}，共 ${plain.length} 字符`)
    } else {
      // contenteditable → 逐字符输入
      await page.keyboard.press('Control+A').catch(() => {})
      await page.keyboard.press('Backspace').catch(() => {})
      await page.keyboard.type(plain, { delay: 10 })
      console.log(`[${this.platform}] 正文已通过 keyboard.type 填入 ${tagName}，共 ${plain.length} 字符`)
    }
  }

  // ==========================================================
  //  点击发布（博客园专用）
  // ==========================================================

  /**
   * 博客园发布按钮文案不统一（"发布"/"保存"/"立即发布"），
   * 加上基类 fallback 即可。点击后可能有"确认"弹窗。
   */
  protected async clickPublish(page: Page): Promise<void> {
    const btnSelectors = [
      'button:has-text("发布")',
      'button:has-text("立即发布")',
      'button:has-text("保存")',
      'input:has-text("发布")',
      '#btnPublish',
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
  //  等待发布结果（博客园专用）
  // ==========================================================

  /**
   * 博客园发布成功后：
   *   1) 弹出"发布成功" / "已发布" / "保存成功" 提示
   *   2) URL 跳到 /posts 或回到 /EditPosts.aspx 列表
   * 不依赖 URL 跳转，靠成功提示判断。
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['发布成功', '已发布', '保存成功']

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

    // 兜底返回当前 URL
    const finalUrl = page.url()
    console.warn(`[${this.platform}] 等待发布结果超时，返回当前 URL: ${finalUrl}`)
    return finalUrl
  }
}
