/**
 * AutoGeo 发布引擎 - 微信公众号发布器
 *
 * 微信公众号后台（mp.weixin.qq.com）发布器，继承 BasePublisher。
 *
 * 平台特点（与一般平台差异较大）：
 *  - publishUrl 落地是「图文消息草稿箱」，不是直接编辑器
 *  - 必须先点「写新图文」按钮才能进入真正的编辑器（带 token 参数）
 *  - 编辑器是 UEditor（#ueditor_0）富文本，新版过渡到 Tiptap（.ProseMirror）
 *  - 标题用 <textarea#title> 或带 placeholder 的 contenteditable
 *  - 正文是嵌套 iframe 或 contenteditable，page.fill 不可用，必须 keyboard.type
 *  - 发布按钮叫「保存并群发」或「群发」，不是「发布」
 *  - 发布后可能触发扫码验证（订阅号）或频率限制 → 需要人工介入
 *  - 标题含 # * ` " < > 等字符会被清理
 *
 * 注意事项：
 *  - 这是最高风险的平台：触发扫码或验证码后必须人工介入
 *  - fillContent 之前需要先打开编辑器（点击「写新图文」），用 JS 兜底增强稳定性
 *  - 等待结果时长 60 秒足够，但可能触发 120 秒扫码窗口
 *  - 封面是必填项（基类不处理，依赖后端 article.cover_url 字段）
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  微信公众号发布器
// ============================================================

export class WeixinPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'weixin'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 草稿箱入口（落地后还要点「写新图文」） ----
  publishUrl =
    'https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&lang=zh_CN'

  // ---- 标题选择器（多 fallback） ----
  titleSelector = [
    '#title',
    'textarea#title',
    'textarea[placeholder*="请输入标题"]',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    '.title-area textarea',
    '.title_input textarea',
    'div[class*="title"] textarea',
    'div[class*="title"] input',
    '[contenteditable="true"][data-placeholder*="标题"]',
  ].join(', ')

  // ---- 正文编辑器选择器（UEditor / Tiptap / 通用 contenteditable） ----
  contentSelector = [
    '#ueditor_0',
    '.edui-body-container',
    'iframe#ueditor_0_iframe',
    '.editor_area',
    '.rich_media_editor',
    '[contenteditable="true"][class*="editor"]',
    'div[class*="editable"][contenteditable="true"]',
    '.ProseMirror',
    '[contenteditable="true"]',
  ].join(', ')

  // ==========================================================
  //  「写新图文」入口（必须先点）
  // ==========================================================

  /**
   * 微信公众号的 fillContent 前置步骤：
   *   1) 检测是否已经在编辑器中
   *   2) 否则点击「写新图文」按钮（多重 fallback）
   *   3) 等待编辑器加载完成
   *
   * 然后再走标准的 fillContent 流程（HTML→纯文本→键盘输入）。
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    // ---- Step 1: 确保已进入编辑器 ----
    const inEditor = await this.isInEditor(page)
    if (!inEditor) {
      const opened = await this.openEditor(page)
      if (!opened) {
        console.warn(`[${this.platform}] 无法打开编辑器，跳过正文填写`)
        return
      }
      // 等待编辑器稳定渲染
      await page.waitForTimeout(3000)
    }

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
    // 微信 UEditor / Tiptap 对长文本友好；用 keyboard.insert_text 提升速度
    if (plain.length > 1000) {
      try {
        await page.keyboard.insertText(plain)
      } catch {
        await page.keyboard.type(plain, { delay: 10 })
      }
    } else {
      await page.keyboard.type(plain, { delay: 15 })
    }

    console.log(`[${this.platform}] 正文已填入，共 ${plain.length} 字符`)
  }

  /**
   * 检测是否已经在编辑器（标题或正文元素可见）。
   */
  private async isInEditor(page: Page): Promise<boolean> {
    for (const sel of this.titleSelector.split(',').map((s) => s.trim()).slice(0, 5)) {
      try {
        const node = page.locator(sel).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 1500 }).catch(() => false))) {
          return true
        }
      } catch {
        continue
      }
    }
    for (const sel of this.contentSelector.split(',').map((s) => s.trim()).slice(0, 5)) {
      try {
        const node = page.locator(sel).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 1500 }).catch(() => false))) {
          return true
        }
      } catch {
        continue
      }
    }
    // placeholder 兜底
    for (const ph of ['请输入标题', '请输入正文']) {
      try {
        const node = page.getByPlaceholder(ph).first()
        if ((await node.count()) > 0) return true
      } catch {
        continue
      }
    }
    return false
  }

  /**
   * 点击「写新图文」按钮进入编辑器。
   * 多级 fallback：CSS 选择器 → JS 精确匹配 → 点「图文消息」卡片。
   */
  private async openEditor(page: Page): Promise<boolean> {
    // ---- L1: CSS 选择器 ----
    const newBtnSelectors = [
      'button:has-text("写新图文")',
      'a:has-text("写新图文")',
      '.weui-desktop-btn_primary:has-text("写新图文")',
      '[role="button"]:has-text("写新图文")',
      'div:has-text("写新图文")',
    ]

    for (const sel of newBtnSelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) === 0) continue
        if (!(await btn.isVisible({ timeout: 1500 }).catch(() => false))) continue
        const text = (await btn.innerText().catch(() => '')).trim()
        if (text && !text.includes('写新图文') && !text.includes('图文')) continue
        await btn.scrollIntoViewIfNeeded().catch(() => {})
        await btn.click({ force: true })
        console.log(`[${this.platform}] 已点击写新图文按钮: ${sel}`)
        await page.waitForTimeout(3000)
        return true
      } catch {
        continue
      }
    }

    // ---- L2: JS 精确匹配 ----
    try {
      const clicked = await page.evaluate(`(() => {
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
              && style.display !== 'none' && style.visibility !== 'hidden';
        };
        const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], div, span'))
          .filter(el => visible(el) && (el.innerText || '').trim() === '写新图文');
        const target = candidates[0];
        if (!target) return false;
        target.click();
        return true;
      })()`)
      if (clicked) {
        console.log(`[${this.platform}] 已通过 DOM 精确点击"写新图文"`)
        await page.waitForTimeout(3000)
        return true
      }
    } catch {
      // ignore
    }

    // ---- L3: 兜底 - 先点"图文消息"卡片 ----
    const imageEntrySelectors = [
      'div:has-text("图文消息")',
      'a:has-text("图文消息")',
      '[class*="appmsg"]:has-text("图文")',
    ]

    for (const sel of imageEntrySelectors) {
      try {
        const entry = page.locator(sel).first()
        if ((await entry.count()) === 0) continue
        if (!(await entry.isVisible({ timeout: 1500 }).catch(() => false))) continue
        await entry.click({ force: true })
        console.log(`[${this.platform}] 已点击图文消息卡片: ${sel}`)
        await page.waitForTimeout(2000)
        // 再次尝试找"写新图文"
        for (const sub of newBtnSelectors.slice(0, 3)) {
          try {
            const btn = page.locator(sub).first()
            if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 1500 }).catch(() => false))) {
              await btn.click({ force: true })
              console.log(`[${this.platform}] 二级菜单已点击写新图文: ${sub}`)
              await page.waitForTimeout(3000)
              return true
            }
          } catch {
            continue
          }
        }
      } catch {
        continue
      }
    }

    console.warn(`[${this.platform}] 未能打开微信公众号编辑器`)
    return false
  }

  // ==========================================================
  //  点击发布（微信公众号专用）
  // ==========================================================

  /**
   * 微信公众号的发布流程：
   *   1. 点击「保存并群发」/「群发」按钮
   *   2. 可能弹出"确认群发？"弹窗
   *   3. 可能触发扫码验证（订阅号 / 风控）
   *   4. 可能触发验证码
   *
   * 注意：基类的 clickPublish 通用确认弹窗不够用，需要自定义。
   */
  protected async clickPublish(page: Page): Promise<void> {
    // 滚到底部确保发布按钮可见
    try {
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      await page.waitForTimeout(1000)
    } catch {
      // ignore
    }

    // ---- 第一步：找到并点击发布按钮 ----
    const publishSelectors = [
      '#js_send',
      'button:has-text("保存并群发")',
      'button:has-text("群发")',
      '.weui-desktop-btn_primary:has-text("群发")',
      'a:has-text("保存并群发")',
      '[role="button"]:has-text("群发")',
    ]

    let clicked = false
    for (const sel of publishSelectors) {
      try {
        const btns = page.locator(sel)
        const count = await btns.count()
        for (let i = count - 1; i >= 0; i--) {
          const btn = btns.nth(i)
          if (!(await btn.isVisible({ timeout: 1000 }).catch(() => false))) continue
          const text = (await btn.innerText().catch(() => '')).trim()
          if (text.includes('保存为草稿') || text.includes('保存草稿') || text.includes('定时') || text.includes('设置')) continue
          if (!text.includes('群发') && !text.includes('发布') && !text.includes('保存并群发')) continue
          await btn.scrollIntoViewIfNeeded().catch(() => {})
          await btn.click({ force: true })
          clicked = true
          console.log(`[${this.platform}] 已点击发布按钮: ${text} (selector: ${sel})`)
          break
        }
        if (clicked) break
      } catch {
        continue
      }
    }

    if (!clicked) {
      console.warn(`[${this.platform}] 未找到发布按钮`)
      return
    }

    // ---- 第二步：处理可能的二次确认弹窗 ----
    await page.waitForTimeout(2000)

    const confirmSelectors = [
      'button:has-text("确认群发")',
      '.weui-desktop-dialog__btn-primary',
      '.js_dialog_confirm',
      '.weui-desktop-modal__btn-primary',
      'button:has-text("确定")',
      'button:has-text("确认")',
    ]

    for (const sel of confirmSelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 2000 }).catch(() => false))) {
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
  //  等待发布结果（微信公众号专用）
  // ==========================================================

  /**
   * 等待发布结果：
   *   1) 检测成功提示（"群发成功" / "发布成功" / "已群发" 等）
   *   2) 检测失败提示（"发布失败" / "请添加封面" / "内容违规" 等）→ 抛错
   *   3) 检测 URL 跳转到 appmsg_list（草稿箱）
   *   4) 兜底返回当前 URL
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['群发成功', '发布成功', '已群发', '提交成功', '正在群发', '已发送']
    const failTexts = [
      '发布失败',
      '群发失败',
      '内容违规',
      '请添加封面',
      '请上传封面',
      '请输入标题',
      '请输入正文',
      '敏感词',
      '频次过高',
      '超过限制',
      '操作频繁',
      '包含违法',
      '未通过审核',
    ]

    const deadline = Date.now() + 60_000
    let lastUrl = page.url()
    while (Date.now() < deadline) {
      // 检测失败提示
      for (const t of failTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }).catch(() => false))) {
            const text = (await node.innerText().catch(() => t)).trim()
            throw new Error(`微信提示失败: ${text}`)
          }
        } catch (err) {
          if (err instanceof Error && err.message.startsWith('微信提示失败')) {
            throw err
          }
          continue
        }
      }

      // 检测成功提示
      for (const t of successTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
            const url = page.url()
            console.log(`[${this.platform}] 检测到成功提示: ${t} → ${url}`)
            return url
          }
        } catch {
          continue
        }
      }

      // URL 变化（特别是跳转回 appmsg_list）
      const url = page.url()
      if (url !== lastUrl) {
        lastUrl = url
        if (url.includes('appmsg_list') || url.includes('send_ok') || url.includes('success')) {
          console.log(`[${this.platform}] URL 已跳转到发布成功标识: ${url}`)
          return url
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
