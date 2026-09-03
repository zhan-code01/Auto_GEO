/**
 * AutoGeo 发布引擎 - 百家号（Baijiahao）发布器
 *
 * 百家号 (baijiahao.baidu.com) 图文发布器，继承 BasePublisher。
 * 入口: https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1
 *   (URL 取自 backend/config.py 的 PLATFORMS["baijiahao"].publish_url)
 *
 * 平台特点（与后端 baijiahao.py v3.1 保持一致）：
 *  - 当前版 (2026) 标题使用 Lexical 编辑器 (contenteditable div)
 *  - 当前版正文使用 UEditor（编辑器是 iframe#ueditor_0 内的 body）
 *  - 老版本：标题是 textarea / 正文是 #desc textarea
 *  - 选择器多层 fallback：当前版 → 旧版 → JS 注入
 *
 * 特殊流程（参考后端 _open_image_article_entry_if_needed）：
 *  - 如果 navigate 之后没有直接进入编辑器，而是在落地页（首页/创作中心），
 *    会自动点击 "发布图文" 入口进入编辑器
 *  - 之后还要在 clickPublish 阶段处理"预览并发布"按钮（"发布"也是合法文本）
 *  - 发布按钮文本可能是 "发布" / "确认发布" / "立即发布"
 *
 * 注意事项：
 *  - 标题最长 64 字（基类 fillTitle 不截断，依赖后端 article 限制）
 *  - 正文最长 20000 字（基类不截断，依赖后端 article 限制）
 *  - UEditor 必须用 setContent API 或 iframe body innerHTML 注入，
 *    普通 keyboard.type 在跨 iframe 边界时会失效
 *  - 不处理图片上传，只填纯文本（与后端 fillContent 降级路径一致）
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  百家号发布器
// ============================================================

export class BaijiahaoPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'baijiahao'

  // ---- 百家号图文编辑器（从 backend/config.py 同步）----
  publishUrl = 'https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1'
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  // ---- 标题选择器（多 fallback，对齐后端 baijiahao_selectors.TITLE_INPUT）----
  titleSelector = [
    // 当前版 Lexical 编辑器
    '[data-lexical-editor="true"]',
    '[data-testid="news-title-input"] [contenteditable="true"]',
    'div[class*="titleInput"] [contenteditable="true"]',
    // 旧版 textarea/input
    'textarea[placeholder*="请输入标题"]',
    'input[placeholder*="请输入标题"]',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    'div[class*="title"] textarea',
    'div[class*="title"] input',
    '#title',
  ].join(', ')

  // ---- 正文选择器（对齐 baijiahao_selectors.CONTENT_INPUT）----
  contentSelector = [
    // 当前版 UEditor iframe
    'iframe#ueditor_0',
    '#ueditor',
    '#ueditorContainer',
    // 旧版 textarea
    '#desc',
    // 通用富文本
    '[contenteditable="true"][data-placeholder*="请输入正文"]',
    '[contenteditable="true"][data-placeholder*="正文"]',
    'textarea[placeholder*="请输入正文"]',
    'textarea[placeholder*="正文"]',
    'div.editor-wrapper [contenteditable]',
    'div[class*="editor"] [contenteditable]',
    'div[class*="content"] [contenteditable]',
    '.ql-editor',
    '[contenteditable="true"]',
  ].join(', ')

  // ==========================================================
  //  主流程：覆盖 publish 处理"进入落地页需点 发布图文"的情况
  // ==========================================================

  /**
   * 百家号有个特殊流程：有时 publishUrl 会落到创作中心首页而不是直接进编辑器，
   * 这种情况需要点击 "发布图文" 入口按钮。后端在 _open_image_article_entry_if_needed
   * 实现了同样的逻辑；这里为了不破坏基类流程，在 publish 顶部做一次 pre-flight。
   */
  async publish(
    page: Page,
    article: any,
    account: any,
  ): Promise<{ success: boolean; url?: string; error?: string; manual_required?: boolean; manual_reason?: string }> {
    try {
      // 导航到 publishUrl（基类 publish 第一步也会做，这里提前到 pre-flight 之前以便
      // 检测落地页）。如果直接进编辑器，pre-flight 不会发现入口。
      if (!page.url().includes('baijiahao.baidu.com/builder/rc/edit')) {
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

        // 如果还在落地页（不是编辑器），点 "发布图文" 入口
        if (!page.url().includes('/builder/rc/edit')) {
          await this._openImageArticleEntry(page)
        }
      }
    } catch (err: any) {
      console.warn(`[${this.platform}] pre-flight 导航异常（继续基类流程）: ${err?.message ?? err}`)
    }

    // 走标准基类发布流程
    return super.publish(page, article, account)
  }

  /**
   * 点击首页/创作中心的 "发布图文" 入口（多选择器 fallback + 文本兜底）。
   * 与后端 _open_image_article_entry_if_needed 行为一致。
   */
  private async _openImageArticleEntry(page: Page): Promise<void> {
    const entrySelectors = [
      'button:has-text("发布图文")',
      'a:has-text("发布图文")',
      '[role="button"]:has-text("发布图文")',
      'div:has-text("发布图文")',
    ]

    for (const sel of entrySelectors) {
      try {
        const entry = page.locator(sel).first()
        if ((await entry.count()) > 0 && (await entry.isVisible({ timeout: 1500 }))) {
          const text = (await entry.innerText()).trim()
          if (text && !text.includes('发布图文')) continue
          await entry.click({ force: true })
          console.log(`[${this.platform}] 已点击 发布图文 入口: ${sel}`)
          await page.waitForTimeout(2000)
          return
        }
      } catch {
        continue
      }
    }

    // JS 兜底：精确匹配文本 "发布图文"
    try {
      const clicked = await page.evaluate(`() => {
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.display !== 'none' && style.visibility !== 'hidden';
        };
        const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], div, span'))
          .filter(el => visible(el) && (el.innerText || '').trim() === '发布图文');
        const target = candidates[0];
        if (!target) return false;
        target.click();
        return true;
      }`)
      if (clicked) {
        console.log(`[${this.platform}] 已通过 DOM 精确点击 发布图文 入口`)
        await page.waitForTimeout(2000)
      }
    } catch {
      // 忽略，继续走基类流程（fillTitle 找不到会 warn）
    }
  }

  // ==========================================================
  //  正文填写（百家号专用：UEditor iframe + Lexical 兼容）
  // ==========================================================

  /**
   * 百家号正文填充：四级降级策略，对齐后端 _fill_content。
   *   L0: UEditor API (UE_V2.instants['ueditorInstant0'].setContent)
   *   L1: iframe#ueditor_0 body 直接 innerHTML 注入
   *   L2: 旧版富文本 / contenteditable 元素 keyboard.type
   *   L3: 通用 contenteditable JS 注入
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const clean = this.markdownToPlainText(content || '')
    if (!clean) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    // 构建段落 HTML（用 <p> 包裹每段）
    const paragraphs = clean.split(/\n{2,}/)
    const htmlContent = paragraphs
      .map((p) => `<p>${this._escapeHtml(p.trim())}</p>`)
      .filter((p) => p !== '<p></p>')
      .join('') || `<p>${this._escapeHtml(clean)}</p>`

    // ---- L0: UEditor API setContent ----
    try {
      const ok = await page.evaluate(`(html) => {
        try {
          const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
          if (ue && typeof ue.setContent === 'function') {
            ue.setContent(html);
            if (typeof ue.fireEvent === 'function') {
              ue.fireEvent('contentchange');
            }
            return true;
          }
        } catch (e) {}
        return false;
      }`, htmlContent)
      if (ok) {
        await page.waitForTimeout(500)
        console.log(`[${this.platform}] 正文已填入 - L0 UEditor API (${clean.length} 字符)`)
        return
      }
    } catch {
      // UEditor API 不可用，继续下一级
    }

    // ---- L1: iframe#ueditor_0 body innerHTML 注入 ----
    try {
      const ok = await page.evaluate(`(html) => {
        try {
          const iframe = document.querySelector('iframe#ueditor_0');
          if (!iframe || !iframe.contentDocument) return false;
          const body = iframe.contentDocument.body;
          if (!body) return false;
          body.innerHTML = html;
          body.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
          body.dispatchEvent(new Event('change', { bubbles: true }));
          // 尝试同步到 UEditor
          try {
            const ue = window.UE_V2 && window.UE_V2.instants && window.UE_V2.instants['ueditorInstant0'];
            if (ue && typeof ue.sync === 'function') ue.sync('iframebody');
          } catch (e) {}
          return true;
        } catch (e) { return false; }
      }`, htmlContent)
      if (ok) {
        await page.waitForTimeout(500)
        console.log(`[${this.platform}] 正文已填入 - L1 iframe body (${clean.length} 字符)`)
        return
      }
    } catch {
      // iframe 注入失败，继续下一级
    }

    // ---- L2: 旧版富文本 / contenteditable 元素 keyboard.type ----
    // 跳过 iframe/#ueditor/iframeholder 选择器（这些就是 L0/L1 的目标）
    const l2Selectors = this.contentSelector
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s && !s.includes('iframe') && s !== '#ueditor' && s !== '#ueditorContainer' && s !== '#desc')
    for (const sel of l2Selectors) {
      try {
        const editor = page.locator(sel).first()
        if ((await editor.count()) > 0 && (await editor.isVisible({ timeout: 2000 }))) {
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
          console.log(`[${this.platform}] 正文已填入 - L2 ${sel} (${clean.length} 字符)`)
          return
        }
      } catch {
        continue
      }
    }

    // ---- L3: 通用 contenteditable JS 注入 ----
    const ok = await page.evaluate(`(text) => {
      // 优先尝试 iframe body
      try {
        const iframe = document.querySelector('iframe#ueditor_0');
        if (iframe && iframe.contentDocument && iframe.contentDocument.body) {
          const body = iframe.contentDocument.body;
          body.innerHTML = text.split(/\\n{2,}/).map(p =>
            '<p>' + p.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>') + '</p>'
          ).join('');
          body.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
          body.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        }
      } catch (e) {}

      // 回退：找主文档里最大的 contenteditable
      const nodes = Array.from(document.querySelectorAll('[contenteditable="true"]'));
      const target = nodes.find((el) => {
        const rect = el.getBoundingClientRect();
        const ph = (el.getAttribute('data-placeholder') || el.getAttribute('placeholder') || '') + ' ' + (el.innerText || '');
        if (ph.includes('标题')) return false;
        if (rect.height < 80) return false;
        return rect.width > 200;
      });
      if (!target) return false;
      target.focus();
      document.execCommand('selectAll', false, null);
      document.execCommand('delete', false, null);
      const html = text.split(/\\n{2,}/).map(p =>
        '<p>' + p.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>') + '</p>'
      ).join('');
      document.execCommand('insertHTML', false, html);
      target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }`, clean)
    if (ok) {
      console.log(`[${this.platform}] 正文已填入 - L3 JS 注入 (${clean.length} 字符)`)
    } else {
      console.warn(`[${this.platform}] 正文所有填充方式都失败`)
    }
  }

  // ==========================================================
  //  点击发布（百家号专用）
  // ==========================================================

  /**
   * 百家号发布按钮文本是 "发布" / "确认发布" / "立即发布"，
   * 过滤掉 "定时发布" / "发布设置" / "发布作品" / "发布图文" / "发布视频" 等干扰。
   * 点击后处理确认弹窗（"确认发布" / "确定发布" / "继续发布"）。
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
        document.querySelectorAll('button').forEach((btn) => {
          const text = (btn.innerText || '').trim();
          if (text === '发布' || text === '确认发布') {
            btn.disabled = false;
            btn.removeAttribute('disabled');
          }
        });
      }`)
    } catch {
      // 忽略
    }

    // 3. 找发布按钮
    const btnSelectors = [
      'button.cheetah-btn-primary:has-text("发布")',
      'button[class*="primary"]:has-text("发布")',
      'button:has-text("发布")',
      'button[class*="publish"]',
      'button[class*="submit"]',
      '[class*="publish"]:has-text("发布")',
      'button[type="submit"]:has-text("发布")',
    ]
    const excludeTexts = ['定时发布', '发布设置', '发布作品', '发布图文', '发布视频']
    const validTexts = ['发布', '确认发布', '发布文章', '立即发布']

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
      'button:has-text("继续")',
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
  //  等待发布结果（百家号专用）
  // ==========================================================

  /**
   * 百家号发布后没有固定的成功 URL，通常是：
   *   - 弹出 "发布成功" / "提交成功" / "审核中" 等提示文字
   *   - 或者 URL 跳转到 "作品管理" / "内容管理" / "home" 等
   * 这里先等文字提示，超时回退到 URL 变化检测。
   * 与后端 _wait_for_publish_result 行为一致（先失败 → 再成功 → 再 URL 跳转）。
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['发布成功', '提交成功', '审核中', '已发布']
    const failTexts = [
      '发布失败',
      '内容违规',
      '敏感词',
      '请设置封面',
      '请输入标题',
      '请输入正文',
      '不符合规范',
    ]

    for (let i = 0; i < 45; i++) {
      // 失败检测（先看失败）
      for (const t of failTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }))) {
            console.warn(`[${this.platform}] 检测到失败提示: ${t}`)
            throw new Error(`百家号发布失败: ${t}`)
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

      await page.waitForTimeout(1000)
    }

    // 超时：返回当前 URL
    console.warn(`[${this.platform}] 45 秒内未检测到明确结果，返回当前 URL`)
    return page.url()
  }

  // ==========================================================
  //  工具
  // ==========================================================

  protected override _escapeHtml(s: string): string {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
  }
}
