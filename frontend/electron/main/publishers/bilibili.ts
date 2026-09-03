/**
 * AutoGeo 发布引擎 - 哔哩哔哩（B站专栏）发布器
 *
 * B站创作中心专栏发布器（member.bilibili.com），继承 BasePublisher。
 *
 * 平台特点：
 *  - 专栏编辑器入口是「新的创作」按钮，落地后是列表页（含草稿搜索框），
 *    必须先点「新的创作」才会加载真正的编辑器（iframe 嵌套）
 *  - 编辑器可能是 Quill.js（.ql-editor）或自研 contenteditable
 *  - 标题最长 30 字；正文最长 20000 字（基类不截断）
 *  - 发布按钮文字常为「发布」/「立即投稿」/「发布文章」
 *  - 发布成功通常不会跳转到文章页，而是停留在创作者中心，
 *    需要通过成功提示或 URL 变化判断
 *
 * 注意事项：
 *  - publishUrl 落地是列表页，需要处理「点新的创作」进入编辑器的额外步骤
 *  - 标题和正文都是 contenteditable 富文本，需用 keyboard.type 逐字输入
 *  - 后端限制：标题不能包含 # * " 字符（基类 fillTitle 不自动处理）
 *  - 当前实现未做封面上传（依赖后端 article.cover_url 字段）
 *  - 选 publishUrl 走 2024+ 新版入口；若 B站回滚到旧版，需要重新适配
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  B站专栏发布器
// ============================================================

export class BilibiliPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'bilibili'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- B站创作中心专栏编辑器入口 ----
  // 注意：这是列表页，落地后还要点「新的创作」才会加载真正的编辑器 iframe
  publishUrl =
    'https://member.bilibili.com/platform/upload/text/new-article'

  // ---- 标题选择器（多 fallback，对齐 backend/bilibili_selectors.py） ----
  titleSelector = [
    'input[placeholder="请输入标题（建议30字以内）"]',
    'textarea[placeholder="请输入标题（建议30字以内）"]',
    'input[placeholder*="请输入文章标题"]',
    'input[placeholder*="输入文章标题"]',
    'input[placeholder*="文章标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    'input.input-val[type="text"][placeholder*="标题"]',
    'input[placeholder*="请输入标题"]',
    'input[placeholder*="标题"]',
    '.article-title input',
    '.article-title [contenteditable="true"]',
    'textarea[placeholder*="标题"]',
  ].join(', ')

  // ---- 正文编辑器选择器（contenteditable 富文本，多 fallback） ----
  contentSelector = [
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][placeholder*="正文"]',
    '[contenteditable="true"][data-placeholder*="内容"]',
    '[contenteditable="true"][placeholder*="内容"]',
    '.editor-body [contenteditable="true"]',
    '.article-content [contenteditable="true"]',
    '.content-editor [contenteditable="true"]',
    'div.ql-editor.ql-blank[contenteditable="true"]',
    'div.ql-editor[contenteditable="true"]',
    '.ql-editor',
    '.ProseMirror[contenteditable="true"]',
    '[contenteditable="true"]',
  ].join(', ')

  // ==========================================================
  //  「新的创作」入口（publishUrl 落地是列表页）
  // ==========================================================

  /**
   * 进入编辑器之前需要点击「新的创作」按钮。
   * 这里在 fillContent 之前自动尝试一次（如果还在列表页）。
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    // ---- Step 1: 确保已进入编辑器（点「新的创作」） ----
    await this.ensureInEditor(page)

    // ---- Step 2: HTML → 纯文本 ----
    const plain = this.markdownToPlainText(content || '')
    if (!plain) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    // ---- Step 3: 找到正文编辑器并点击聚焦 ----
    const selectors = this.contentSelector.split(',').map((s) => s.trim())
    let focused = false
    for (const sel of selectors) {
      try {
        const editor = page.locator(sel).first()
        if ((await editor.count()) === 0) continue
        if (!(await editor.isVisible({ timeout: 2000 }).catch(() => false))) continue
        await editor.scrollIntoViewIfNeeded().catch(() => {})
        await editor.click({ force: true })
        await page.waitForTimeout(500)
        focused = true
        break
      } catch {
        continue
      }
    }

    if (!focused) {
      console.warn(`[${this.platform}] 无法定位正文编辑器，尝试 focus 兜底`)
      try {
        await page.focus(this.contentSelector)
        await page.waitForTimeout(500)
      } catch (err) {
        console.warn(
          `[${this.platform}] 正文编辑器 focus 失败: ${(err as Error).message}`,
        )
        return
      }
    }

    // ---- Step 4: 清空已有内容 ----
    await page.keyboard.press('Control+A').catch(() => {})
    await page.keyboard.press('Backspace').catch(() => {})
    await page.waitForTimeout(300)

    // ---- Step 5: 逐字符输入 ----
    await page.keyboard.type(plain, { delay: 10 })

    console.log(`[${this.platform}] 正文已填入，共 ${plain.length} 字符`)
  }

  /**
   * 尝试点「新的创作」按钮，确保已进入真正的编辑器。
   * 如果编辑器已经存在则直接返回。
   */
  private async ensureInEditor(page: Page): Promise<void> {
    // 已检测到 contenteditable 编辑器 → 直接返回
    for (const sel of this.contentSelector.split(',').map((s) => s.trim()).slice(0, 5)) {
      try {
        const node = page.locator(sel).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 1000 }).catch(() => false))) {
          return
        }
      } catch {
        continue
      }
    }

    // 未进入编辑器，尝试点「新的创作」按钮
    const newBtnSelectors = [
      'button:has-text("新的创作")',
      'a:has-text("新的创作")',
      'button:has-text("新建创作")',
      'a:has-text("新建创作")',
      'button:has-text("写专栏")',
      'a:has-text("写专栏")',
      'button:has-text("开始创作")',
      'a:has-text("专栏投稿")',
      'button:has-text("发布专栏")',
      'a:has-text("发布专栏")',
      '.create-article-btn',
      '[class*="create-btn"]',
    ]

    for (const sel of newBtnSelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) === 0) continue
        if (!(await btn.isVisible({ timeout: 1500 }).catch(() => false))) continue
        await btn.scrollIntoViewIfNeeded().catch(() => {})
        await btn.click({ force: true })
        console.log(`[${this.platform}] 点击「新的创作」入口: ${sel}`)
        await page.waitForTimeout(3000)

        // 检查是否进入了编辑器
        for (const edSel of this.contentSelector.split(',').map((s) => s.trim()).slice(0, 5)) {
          try {
            const ed = page.locator(edSel).first()
            if ((await ed.count()) > 0 && (await ed.isVisible({ timeout: 2000 }).catch(() => false))) {
              return
            }
          } catch {
            continue
          }
        }
      } catch {
        continue
      }
    }

    // 尝试备用编辑页直链
    console.warn(`[${this.platform}] 未找到「新的创作」按钮，尝试备用 URL`)
    const fallbackUrls = [
      'https://member.bilibili.com/platform/upload-text/edit',
      'https://member.bilibili.com/platform/upload/text/edit',
    ]
    for (const url of fallbackUrls) {
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
        await page.waitForTimeout(3000)
        for (const edSel of this.contentSelector.split(',').map((s) => s.trim()).slice(0, 5)) {
          try {
            const ed = page.locator(edSel).first()
            if ((await ed.count()) > 0 && (await ed.isVisible({ timeout: 2000 }).catch(() => false))) {
              return
            }
          } catch {
            continue
          }
        }
      } catch {
        continue
      }
    }

    console.warn(`[${this.platform}] 未能确认进入编辑器，继续尝试填写正文`)
  }

  // ==========================================================
  //  点击发布（B站专用）
  // ==========================================================

  /**
   * B站的发布流程：
   *   1. 点击「发布」/「立即投稿」按钮（精确匹配 role + 文本）
   *   2. 可能弹出二次确认弹窗（「确认发布」/「确定投稿」）
   */
  protected async clickPublish(page: Page): Promise<void> {
    // 先滚到底部确保发布按钮在视口内
    try {
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      await page.waitForTimeout(500)
    } catch {
      // ignore
    }

    // ---- 第一步：找到并点击发布按钮 ----
    const btnSelectors = [
      'button:has-text("立即投稿")',
      'button:has-text("发布文章")',
      'button:has-text("发布专栏")',
      'button:has-text("发布")',
      '.publish-btn:has-text("发布")',
      '[class*="publish"]:has-text("发布")',
      'button:has-text("投稿")',
      'button[class*="submit"]',
      'button[class*="publish"]',
      '[class*="submit-btn"]',
      '.submit-btn',
    ]

    let clicked = false
    for (const sel of btnSelectors) {
      const btn = page.locator(sel).first()
      try {
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
      throw new Error('B站发布按钮未找到')
    }

    // ---- 第二步：处理可能的二次确认弹窗 ----
    await page.waitForTimeout(1500)

    const confirmSelectors = [
      'button:has-text("确认发布")',
      'button:has-text("确定发布")',
      'button:has-text("确认投稿")',
      'button:has-text("确定投稿")',
      'button:has-text("确认")',
      'button:has-text("确定")',
      '.confirm-publish-btn',
      '.modal button:has-text("确认")',
      '.dialog button:has-text("确认")',
      '[class*="modal"] button:has-text("确定")',
      '[class*="dialog"] button:has-text("确定")',
    ]

    for (const sel of confirmSelectors) {
      const btn = page.locator(sel).first()
      try {
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

  protected async handleCover(page: Page, article: any): Promise<void> {
    const cover = this.getCoverImagePath(article)
    if (!cover) return

    const uploaded = await this.uploadFilesBySelectors(
      page,
      [
        'input[type="file"][accept*="image"]',
        'input[type="file"][accept*=".jpg"]',
        'input[type="file"]',
      ],
      [cover],
      '封面',
    )
    if (!uploaded) {
      console.warn(`[${this.platform}] 未找到可用封面上传入口，继续尝试发布`)
    }
  }

  // ==========================================================
  //  等待发布结果（B站专用）
  // ==========================================================

  /**
   * B站发布后通常不会跳转到文章页，而是停留在创作中心。
   * 判断逻辑：
   *   1) 页面出现"发布成功" / "投稿成功" / "已发布" 等提示
   *   2) URL 离开编辑器（不包含 edit/upload）
   *   3) 兜底返回当前 URL
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successKeywords = ['发布成功', '投稿成功', '已发布', '文章发布', '专栏发布成功', '内容已提交']
    const failureKeywords = ['发布失败', '投稿失败', '上传失败', '标题不能为空', '内容不能为空', '请上传封面', '封面不能为空', '验证码', '安全验证', '操作频繁']

    const deadline = Date.now() + 60_000
    while (Date.now() < deadline) {
      await this.assertNoVisibleText(page, failureKeywords, 'B站发布失败或需要人工处理')

      // 检测成功提示
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

      // URL 变化（离开编辑器页）也算成功
      const url = page.url()
      if (
        url.includes('member.bilibili.com') &&
        !url.includes('/edit') &&
        !url.includes('/upload')
      ) {
        console.log(`[${this.platform}] URL 已离开编辑器: ${url}`)
        return url
      }

      await page.waitForTimeout(1000)
    }

    throw new Error('B站发布结果等待超时')
  }
}
