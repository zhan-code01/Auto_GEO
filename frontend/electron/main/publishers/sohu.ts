/**
 * AutoGeo 发布引擎 - 搜狐号（Sohu）发布器
 *
 * 搜狐号 (mp.sohu.com) 图文发布器，继承 BasePublisher。
 * 入口: https://mp.sohu.com/mpfe/v4/contentManagement/firstpage
 *   (URL 取自 backend/config.py 的 PLATFORMS["sohu"].publish_url)
 *
 * 平台特点（与后端 sohu.py v1.0 保持一致）：
 *  - publishUrl 是后台首页（firstpage），不是直接进入编辑器
 *  - 需要在 firstpage 上点击 "发布内容" 按钮进入 Quill 图文编辑器
 *  - 标题是 input[placeholder*="5-72"]（搜狐号标题 5-72 字）
 *  - 正文是 Quill 富文本编辑器 (.ql-editor，contenteditable)
 *  - 选择器多层 fallback：input placeholder → 通用 contenteditable
 *
 * 特殊流程（必须处理！这是搜狐号与其它平台最大的区别）：
 *  - 导航到 firstpage 后，必须点击 "发布内容" 按钮才能进入编辑器
 *  - 如果首次点击没等到编辑器，需要重试
 *  - 搜狐号后台有 introjs 新手引导 / Element UI 遮罩，可能会挡住发布按钮
 *  - 后端的 _navigate_to_editor / _click_publish_entry 实现了完整的两步导航
 *
 * 注意事项：
 *  - 标题最长 72 字（基类 fillTitle 不截断，依赖后端 article 限制）
 *  - 正文最长 20000 字（基类不截断，依赖后端 article 限制）
 *  - Quill 必须用 paste 事件注入 (ClipboardEvent + DataTransfer)
 *  - 不处理图片上传，只填纯文本
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  搜狐号发布器
// ============================================================

export class SohuPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'sohu'

  // ---- 搜狐号后台首页（firstpage，从 backend/config.py 同步）----
  // ⚠️ 注意：这不是编辑器 URL，是后台首页 URL
  //    需要在 publish 中点击 "发布内容" 按钮才能进入 Quill 编辑器
  publishUrl = 'https://mp.sohu.com/mpfe/v4/contentManagement/firstpage'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 标题选择器（多 fallback，对齐后端 sohu_selectors.TITLE_INPUT）----
  titleSelector = [
    // 当前版 input（v18.6 实践值）
    'input[placeholder="请输入标题（5-72字）"]',
    'input[placeholder*="5-72"]',
    'input[placeholder*="标题"]',
    // 通用兜底
    'input[class*="title"]',
    'div[class*="title"] input',
    '#title',
    'input[name="title"]',
  ].join(', ')

  // ---- 正文选择器（对齐 sohu_selectors.CONTENT_EDITOR）----
  contentSelector = [
    '.ql-editor',
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][class*="content"]',
    "div[class*='editor'] [contenteditable='true']",
    '[contenteditable="true"]',
  ].join(', ')

  // ==========================================================
  //  主流程：覆盖 publish 处理"firstpage -> 点击 发布内容"
  // ==========================================================

  /**
   * 搜狐号特殊流程：
   *   1. 导航到 firstpage
   *   2. 在 firstpage 上点击 "发布内容" 按钮
   *   3. 等待 Quill 编辑器加载
   *   4. 走标准 fillTitle / fillContent / clickPublish / waitForResult
   *
   * 与后端 _navigate_to_editor 行为一致（带 3 次重试）。
   */
  async publish(
    page: Page,
    article: any,
    account: any,
  ): Promise<{ success: boolean; url?: string; error?: string; manual_required?: boolean; manual_reason?: string }> {
    try {
      // 1. 导航到 firstpage
      await page.goto(this.publishUrl, {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      })
      // 等待 SPA 渲染
      try {
        await page.waitForLoadState('networkidle', { timeout: 15000 })
      } catch {
        // networkidle 超时不致命
      }
      await page.waitForTimeout(2000)

      // 2. 如果已经在编辑器（极少见），跳过点击入口
      let inEditor = await this._hasEditor(page)
      if (!inEditor) {
        // 3. 点击 "发布内容" 按钮（带重试）
        let clicked = false
        for (let attempt = 0; attempt < 3; attempt++) {
          clicked = await this._clickPublishEntry(page)
          if (clicked) {
            // 等待编辑器加载（最多 15 秒）
            for (let i = 0; i < 15; i++) {
              if (await this._hasEditor(page)) {
                inEditor = true
                break
              }
              await page.waitForTimeout(1000)
            }
            if (inEditor) break
          }
          // 等待后重试（页面可能慢渲染）
          await page.waitForTimeout(2000)
        }
        if (!inEditor) {
          console.warn(`[${this.platform}] 3 次点击 发布内容 后仍未进入编辑器，继续走基类流程（fillTitle 会 warn）`)
        }
      }
    } catch (err: any) {
      console.warn(`[${this.platform}] 搜狐号 pre-flight 异常（继续基类流程）: ${err?.message ?? err}`)
    }

    return super.publish(page, article, account)
  }

  /**
   * 点击 firstpage 上的 "发布内容" 按钮。
   * 与后端 _click_publish_entry 行为一致。
   */
  private async _clickPublishEntry(page: Page): Promise<boolean> {
    const entrySelectors = [
      'button:has-text("发布内容")',
      'span:has-text("发布内容")',
      'a:has-text("发布内容")',
      '[class*="publish"]:has-text("发布")',
      'li:has-text("发布内容")',
    ]

    for (const sel of entrySelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 1500 }))) {
          await btn.click({ force: true })
          console.log(`[${this.platform}] 已点击 发布内容 按钮: ${sel}`)
          await page.waitForTimeout(2000)
          return true
        }
      } catch {
        continue
      }
    }

    // 文本兜底
    try {
      const node = page.getByText('发布内容', { exact: false }).first()
      if ((await node.count()) > 0 && (await node.isVisible({ timeout: 1500 }))) {
        await node.click({ force: true })
        console.log(`[${this.platform}] 已点击 发布内容 按钮（文本兜底）`)
        await page.waitForTimeout(2000)
        return true
      }
    } catch {
      // 忽略
    }

    return false
  }

  /**
   * 检测 Quill 编辑器是否已加载。
   * 对齐后端 sohu_selectors.EDITOR_READY_SELECTORS。
   */
  private async _hasEditor(page: Page): Promise<boolean> {
    // 1. Quill 编辑器存在
    try {
      if ((await page.locator('.ql-editor').count()) > 0) {
        return true
      }
    } catch {
      // 忽略
    }
    // 2. 标题 input 可见
    try {
      const inp = page.locator('input[placeholder*="标题"]').first()
      if ((await inp.count()) > 0 && (await inp.isVisible({ timeout: 500 }))) {
        return true
      }
    } catch {
      // 忽略
    }
    // 3. 文字兜底
    for (const t of ['请输入标题', '发布内容']) {
      try {
        const node = page.getByText(t, { exact: false }).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }))) {
          return true
        }
      } catch {
        continue
      }
    }
    return false
  }

  // ==========================================================
  //  正文填写（搜狐号专用：Quill paste 注入）
  // ==========================================================

  /**
   * 搜狐号正文填充：三级降级策略。
   *   L0: Quill paste 事件注入（ClipboardEvent + DataTransfer）
   *   L1: keyboard.type 逐字输入
   *   L2: 通用 contenteditable JS 注入
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const clean = this.markdownToPlainText(content || '')
    if (!clean) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    // ---- L0: Quill paste 事件 ----
    try {
      const ok = await page.evaluate(`(text) => {
        const editor = document.querySelector('.ql-editor');
        if (!editor) return false;
        editor.focus();
        // 清空现有内容
        editor.innerHTML = '';
        // 构造 paste 事件
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
        editor.dispatchEvent(ev);
        // 兜底：直接设置 innerHTML
        if (!editor.innerText || editor.innerText.trim().length === 0) {
          editor.innerHTML = text.split(/\\n{2,}/).map(p =>
            '<p>' + p.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>') + '</p>'
          ).join('');
          editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
        }
        return true;
      }`, clean)
      if (ok) {
        await page.waitForTimeout(500)
        const filled = await page.evaluate<number>(`() => {
          const e = document.querySelector('.ql-editor');
          return e ? (e.innerText || '').trim().length : 0;
        }`)
        if (filled > 0) {
          console.log(`[${this.platform}] 正文已填入 - L0 Quill paste (${clean.length} 字符, 实际 ${filled})`)
          return
        }
      }
    } catch {
      // 继续下一级
    }

    // ---- L1: keyboard.type 逐字输入 ----
    try {
      const editor = page.locator('.ql-editor').first()
      if ((await editor.count()) > 0) {
        await editor.click({ force: true })
        await page.waitForTimeout(300)
        await page.keyboard.press('Control+A')
        await page.keyboard.press('Backspace')
        await page.waitForTimeout(200)
        if (clean.length > 1000) {
          try {
            await page.keyboard.insertText(clean)
          } catch {
            await page.keyboard.type(clean, { delay: 10 })
          }
        } else {
          await page.keyboard.type(clean, { delay: 15 })
        }
        console.log(`[${this.platform}] 正文已填入 - L1 keyboard (${clean.length} 字符)`)
        return
      }
    } catch {
      // 继续下一级
    }

    // ---- L2: 通用 contenteditable JS 注入 ----
    const ok = await page.evaluate(`(text) => {
      let target = document.querySelector('.ql-editor');
      if (!target) {
        const nodes = Array.from(document.querySelectorAll('[contenteditable="true"]'));
        target = nodes.find((el) => {
          const rect = el.getBoundingClientRect();
          return rect.height > 100 && rect.width > 200;
        });
      }
      if (!target) return false;
      target.focus();
      target.innerHTML = text.split(/\\n{2,}/).map(p =>
        '<p>' + p.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>') + '</p>'
      ).join('');
      target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }`, clean)
    if (ok) {
      console.log(`[${this.platform}] 正文已填入 - L2 JS 注入 (${clean.length} 字符)`)
    } else {
      console.warn(`[${this.platform}] 正文所有填充方式都失败`)
    }
  }

  // ==========================================================
  //  点击发布（搜狐号专用）
  // ==========================================================

  /**
   * 搜狐号发布按钮：
   *   - 主按钮 li.publish-report-btn 文本 "发布"
   *   - 部分版本直接是 button "发布"
   * 过滤掉 "定时发布" / "发布设置" / "发布视频" / "存为草稿" / "保存草稿" 等干扰。
   * 点击后处理二次确认弹窗（"确认发布" / "确定"）。
   */
  protected async clickPublish(page: Page): Promise<void> {
    // 1. 滚到底部
    try {
      await page.evaluate(`window.scrollTo(0, document.body.scrollHeight)`)
    } catch {
      // 忽略
    }
    await page.waitForTimeout(800)

    // 2. 强制启用可能被禁用按钮
    try {
      await page.evaluate(`() => {
        document.querySelectorAll('button, li').forEach((btn) => {
          const text = (btn.innerText || '').trim();
          if (text === '发布' || text === '预览并发布' || text === '确认发布') {
            if ('disabled' in btn) btn.disabled = false;
            btn.removeAttribute('disabled');
            btn.classList.remove('is-disabled');
            btn.classList.remove('disabled');
          }
        });
      }`)
    } catch {
      // 忽略
    }

    // 3. 找发布按钮
    const btnSelectors = [
      'li.publish-report-btn:has-text("发布")',
      'li.publish-report-btn.active.positive-button:has-text("发布")',
      'button:has-text("发布")',
      'button[class*="primary"]:has-text("发布")',
      'button[class*="publish"]',
      '[class*="publish"]:has-text("发布")',
    ]
    const excludeTexts = ['定时发布', '发布设置', '发布视频', '发布图文', '存为草稿', '保存草稿']
    const validTexts = ['发布', '预览并发布', '确认发布', '立即发布']

    let clicked = false
    for (const sel of btnSelectors) {
      try {
        const buttons = page.locator(sel)
        const count = await buttons.count()
        for (let i = count - 1; i >= 0; i--) {
          const btn = buttons.nth(i)
          if (!(await btn.isVisible({ timeout: 800 }).catch(() => false))) continue
          const text = (await btn.innerText()).trim()
          if (excludeTexts.some((bad) => text.includes(bad))) continue
          if (!validTexts.includes(text)) continue
          await btn.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {})
          await btn.click({ force: true })
          console.log(`[${this.platform}] 点击发布按钮: ${text} (${sel})`)
          clicked = true
          break
        }
        if (clicked) break
      } catch {
        continue
      }
    }

    if (!clicked) {
      console.warn(`[${this.platform}] 未找到可点击的发布按钮`)
      return
    }

    // 4. 处理二次确认弹窗
    await page.waitForTimeout(1500)
    const confirmSelectors = [
      'button:has-text("确认发布")',
      'button:has-text("确定发布")',
      'button:has-text("继续发布")',
      'button:has-text("确认")',
      'button:has-text("确定")',
      '.el-button--primary:has-text("确认")',
      '.mp-dialog button:has-text("确认")',
    ]
    for (const sel of confirmSelectors) {
      try {
        const btn = page.locator(sel).last()
        if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 1500 }))) {
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
  //  等待发布结果（搜狐号专用）
  // ==========================================================

  /**
   * 搜狐号发布成功后：
   *   - 弹出 "发布成功" / "提交成功" / "审核中" / "已发布" 等提示
   *   - URL 跳转到 contentManagement / articleList / manage / home / list 等
   * 先查失败，再查成功，再查 URL 跳转；超时返回当前 URL。
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['发布成功', '提交成功', '审核中', '已发布']
    const failTexts = [
      '发布失败',
      '内容违规',
      '包含敏感词',
      '不符合规范',
      '请设置封面',
      '请选择封面',
      '请输入标题',
      '请输入正文',
      '正文不能为空',
      '标题字数',
      '上传失败',
      '不能为空',
    ]
    // 搜狐号发布成功后 URL 跳转模式（对齐后端 sohu_selectors.SUCCESS_URL_PATTERN）
    const successUrlPattern = /(contentManagement|articleList|article_list|manage|home|list)/i
    const lastUrl = page.url()

    for (let i = 0; i < 45; i++) {
      // 失败检测
      for (const t of failTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }))) {
            console.warn(`[${this.platform}] 检测到失败提示: ${t}`)
            return page.url()
          }
        } catch {
          continue
        }
      }

      // 成功文字检测
      for (const t of successTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }))) {
            console.log(`[${this.platform}] 检测到成功提示: ${t}`)
            return page.url()
          }
        } catch {
          continue
        }
      }

      // URL 跳转检测
      if (page.url() !== lastUrl && successUrlPattern.test(page.url())) {
        console.log(`[${this.platform}] 检测到 URL 跳转: ${page.url()}`)
        return page.url()
      }

      await page.waitForTimeout(1000)
    }

    console.warn(`[${this.platform}] 45 秒内未检测到明确结果，返回当前 URL`)
    return page.url()
  }
}
