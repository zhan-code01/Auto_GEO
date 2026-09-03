/**
 * AutoGeo 发布引擎 - 头条号（Toutiao）发布器
 *
 * 头条号 (mp.toutiao.com) 图文发布器，继承 BasePublisher。
 * 入口: https://mp.toutiao.com/profile_v4/graphic/publish
 *   (URL 取自 backend/config.py 的 PLATFORMS["toutiao"].publish_url)
 *
 * 平台特点（与后端 toutiao.py v1.0 保持一致）：
 *  - 标题使用 byte-input 组件（textarea.byte-input__inner）
 *  - 正文使用 ProseMirror 富文本编辑器（.ProseMirror）
 *  - 选择器多层 fallback：byte-input → data-placeholder → 通用 contenteditable
 *  - 头条标题限制 5-30 字
 *
 * 特殊流程：
 *  - 后台有新手引导 / 活动浮层 / 各种弹窗，但这些是页面级处理，前端发布器不重复
 *  - 点击发布后会弹出手机预览的二次确认弹窗，需点击 "确认发布"
 *  - 发布按钮文本是 "预览并发布"（部分版本直接是 "发布"）
 *
 * 注意事项：
 *  - 标题最长 30 字（基类 fillTitle 不截断，依赖后端 article 限制）
 *  - 正文最长 20000 字（基类不截断，依赖后端 article 限制）
 *  - ProseMirror 必须用 paste 事件注入（ClipboardEvent），普通 keyboard.type 也可
 *    作为降级，但容易丢格式；优先用 paste
 *  - 不处理图片上传，只填纯文本
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

// ============================================================
//  头条号发布器
// ============================================================

export class ToutiaoPublisher extends BasePublisher {
  // ---- 平台标识 ----
  platform = 'toutiao'

  // ---- 头条号图文发布页（从 backend/config.py 同步）----
  publishUrl = 'https://mp.toutiao.com/profile_v4/graphic/publish?is_new_connect=0&is_new_user=0'

  // ---- 标题选择器（多 fallback，对齐后端 toutiao_selectors.TITLE_INPUT）----
  titleSelector = [
    // 当前版 byte-input 组件
    'textarea.byte-input__inner',
    '.title-input textarea',
    'textarea[placeholder*="标题"]',
    'input[placeholder*="标题"]',
    // V4 后台 data-placeholder 写法
    'div[data-placeholder="请输入标题（5-30个字）"]',
    'div[data-placeholder*="请输入标题"]',
    '[contenteditable="true"][data-placeholder*="标题"]',
    // 通用兜底
    'div[class*="title"] textarea',
    'div[class*="title"] input',
    '#title',
    'input[name="title"]',
  ].join(', ')

  // ---- 正文选择器（对齐 toutiao_selectors.CONTENT_INPUT）----
  contentSelector = [
    // ProseMirror（头条正文主编辑器，contenteditable）
    '.ProseMirror',
    // 通用富文本兜底
    '[contenteditable="true"][data-placeholder*="正文"]',
    '[contenteditable="true"][class*="article"]',
    "div[class*='editor'] [contenteditable='true']",
    '.ql-editor',
    '[contenteditable="true"]',
  ].join(', ')

  // 头条号对发布频率较敏感，配置保守限制
  rateLimit = { maxPerHour: 3, maxPerDay: 10, minIntervalMinutes: 3 }

  async publish(page: Page, article: any, account: any): Promise<any> {
    // 频率限制（头条号对发布频率敏感）
    const rate = this.checkRateLimitPublic(this.platform)
    if (!rate.allowed) {
      console.warn(`[${this.platform}] 频率限制: ${rate.reason}`)
      return { success: false, error: `[${this.platform}] 发布频率限制: ${rate.reason}` }
    }

    let stage = "navigate"
    try {
      await page.goto(this.publishUrl, { waitUntil: 'domcontentloaded', timeout: 30000 })

      stage = "login_check"
      const initialManual = await this.detectManualIntervention(page)
      if (initialManual || this.isLoginPage(page.url())) {
        const reason = initialManual || `平台 ${this.platform} 需要登录，当前 URL: ${page.url()}`
        return { success: false, manual_required: true, manual_reason: reason }
      }

      stage = "fill_title"
      await this.fillTitle(page, article.title)
      stage = "fill_content"
      await this.fillContent(page, article.content)
      stage = "insert_images"
      await this.insertArticleImages(page, article)
      stage = "handle_cover"
      await this.handleCover(page, article)
      stage = "publish"
      await this.clickPublish(page)
      stage = "wait_result"
      const url = await this.waitForResult(page)
      this.recordPublishSuccessPublic(this.platform)
      return { success: true, url }
    } catch (err: any) {
      const reason = err?.message ?? '发布过程中发生未知错误'
      await this.saveDebugSnapshot(page, stage).catch(() => {})
      if (this.looksLikeManualIntervention(reason)) {
        return { success: false, manual_required: true, manual_reason: `[${this.platform}] ${stage}: ${reason}` }
      }
      return { success: false, error: `[${this.platform}] ${stage}失败: ${reason}` }
    }
  }


  // ==========================================================
  //  正文填写（头条号专用：ProseMirror paste 注入）
  // ==========================================================

  /**
   * 头条号正文填充：三级降级策略。
   *   L0: ProseMirror paste 事件注入（ClipboardEvent + DataTransfer）
   *   L1: keyboard.type 逐字输入
   *   L2: 通用 contenteditable JS 注入
   */
  protected async fillTitle(page: Page, title: string | null): Promise<void> {
    const clean = String(title || '').trim().slice(0, 30)
    if (!clean) {
      console.warn(`[${this.platform}] title is empty, skip fillTitle`)
      return
    }

    const locators = [
      '.publish-editor-title textarea',
      '.publish-editor-title input',
      '.assistant-title textarea',
      this.titleSelector,
    ]

    for (const selector of locators) {
      try {
        const loc = page.locator(selector).first()
        if ((await loc.count()) === 0 || !(await loc.isVisible({ timeout: 1200 }).catch(() => false))) continue
        const ok = await loc.evaluate((el: any, value: string) => {
          const setNativeValue = (node: any, text: string) => {
            const proto = node.tagName === 'TEXTAREA'
              ? (window as any).HTMLTextAreaElement.prototype
              : (window as any).HTMLInputElement.prototype
            const desc = Object.getOwnPropertyDescriptor(proto, 'value')
            if (desc?.set) desc.set.call(node, text)
            else node.value = text
          }
          el.scrollIntoView({ block: 'center', inline: 'nearest' })
          el.focus()
          if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
            setNativeValue(el, value)
          } else {
            el.textContent = value
            const selection = window.getSelection()
            const range = document.createRange()
            range.selectNodeContents(el)
            range.collapse(false)
            selection?.removeAllRanges()
            selection?.addRange(range)
          }
          el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }))
          el.dispatchEvent(new Event('change', { bubbles: true }))
          const actual = String(
            el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'
              ? el.value
              : (el.innerText || el.textContent || ''),
          ).trim()
          return actual.includes(value.slice(0, Math.min(8, value.length)))
        }, clean)
        if (ok) {
          console.log(`[${this.platform}] title filled exactly (${selector}): ${clean}`)
          return
        }
      } catch {
        continue
      }
    }

    const ok = await page.evaluate((value: string) => {
      const nodes = Array.from(document.querySelectorAll(
        '.publish-editor-title textarea, .publish-editor-title input, .assistant-title textarea, textarea, input, [contenteditable="true"]',
      )) as any[]
      const visible = (el: any) => {
        const rect = el.getBoundingClientRect()
        const style = window.getComputedStyle(el)
        return rect.width > 100 && rect.height > 10
          && rect.top >= 0 && rect.top < window.innerHeight
          && style.display !== 'none' && style.visibility !== 'hidden'
      }
      const el = nodes.find((node) => {
        const ph = node.getAttribute('placeholder') || node.getAttribute('data-placeholder') || ''
        const cls = String(node.className || '')
        return visible(node) && (ph.includes('标题') || cls.includes('title')
          || node.closest('.publish-editor-title') || node.closest('.assistant-title'))
      })
      if (!el) return false
      el.focus()
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
        const proto = el.tagName === 'TEXTAREA'
          ? (window as any).HTMLTextAreaElement.prototype
          : (window as any).HTMLInputElement.prototype
        const desc = Object.getOwnPropertyDescriptor(proto, 'value')
        if (desc?.set) desc.set.call(el, value)
        else el.value = value
      } else {
        el.textContent = value
      }
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
      const actual = String(
        el.tagName === 'TEXTAREA' || el.tagName === 'INPUT'
          ? el.value
          : (el.innerText || el.textContent || ''),
      ).trim()
      return actual.includes(value.slice(0, Math.min(8, value.length)))
    }, clean)
    if (!ok) throw new Error(`[${this.platform}] title fill failed`)
    console.log(`[${this.platform}] title filled exactly (DOM fallback): ${clean}`)
  }

  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const clean = this.markdownToPlainText(content || '')
    if (!clean) {
      console.warn(`[${this.platform}] 正文为空，跳过填写`)
      return
    }

    // ---- L0: ProseMirror paste 事件 ----
    try {
      const ok = await page.evaluate(`(text) => {
        const editor = document.querySelector('.ProseMirror');
        if (!editor) return false;
        editor.focus();
        // 清空现有内容
        editor.innerHTML = '';
        // 构造 paste 事件
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
        editor.dispatchEvent(ev);
        // 兜底：直接设置 innerHTML（paste 不一定被 ProseMirror 接管）
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
        // 校验是否真的写入了
        const filled = await page.evaluate<number>(`() => {
          const e = document.querySelector('.ProseMirror');
          return e ? (e.innerText || '').trim().length : 0;
        }`)
        if (filled > 0) {
          console.log(`[${this.platform}] 正文已填入 - L0 ProseMirror paste (${clean.length} 字符, 实际 ${filled})`)
          return
        }
      }
    } catch {
      // 继续下一级
    }

    // ---- L1: keyboard.type 逐字输入 ----
    try {
      const editor = page.locator('.ProseMirror').first()
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
      const nodes = Array.from(document.querySelectorAll('[contenteditable="true"]'));
      const target = nodes.find((el) => el.classList.contains('ProseMirror'))
        || nodes.find((el) => {
          const rect = el.getBoundingClientRect();
          return rect.height > 100 && rect.width > 200;
        });
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
  //  封面上传（头条号专用：强制要求封面 → 点击免费正版图片）
  // ==========================================================

  /**
   * 头条号强制要求封面。策略：
   *   1. 先尝试找 cover input[type=file] 直接注入（如果有本地图片）
   *   2. 兜底：点击「免费正版图片」→ 随机选一张 → 确认
   */
  protected async handleCover(page: Page, article: any): Promise<void> {
    console.log(`[${this.platform}] 处理封面...`)

    try {
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
      await page.waitForTimeout(800)
    } catch {
      // 忽略
    }

    // ---- Step 1: 尝试直接文件注入（有本地图片时）----
    const coverPath = this.getCoverImagePath(article)
    if (coverPath) {
      console.log(`[${this.platform}] 尝试注入封面文件: ${coverPath}`)
      try {
        const fileInput = page.locator('input[type="file"][accept*="image"]').first()
        if ((await fileInput.count()) > 0) {
          await fileInput.setInputFiles(coverPath)
          await page.waitForTimeout(2000)
          console.log(`[${this.platform}] 封面已注入`)
          return
        }
      } catch (err: any) {
        console.warn(`[${this.platform}] 文件注入封面失败:`, err.message)
      }
    }

    // ---- Step 2: 点击「免费正版图片」----
    console.log(`[${this.platform}] 尝试点击免费正版图片...`)
    const freeBtnSelectors = [
      'button:has-text("免费正版图片")',
      'span:has-text("免费正版图片")',
      'div:has-text("免费正版图片")',
      '[class*="free"]:has-text("免费")',
      '[class*="image"]:has-text("免费")',
      'a:has-text("免费正版图片")',
    ]

    let freeBtnClicked = false
    for (const sel of freeBtnSelectors) {
      try {
        const btn = page.locator(sel).first()
        if ((await btn.count()) > 0 && (await btn.isVisible({ timeout: 1500 }).catch(() => false))) {
          await btn.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {})
          await btn.click({ force: true })
          console.log(`[${this.platform}] 已点击免费正版图片 (${sel})`)
          freeBtnClicked = true
          break
        }
      } catch {
        continue
      }
    }

    if (!freeBtnClicked) {
      console.warn(`[${this.platform}] 未找到「免费正版图片」按钮，尝试直接发布（可能被拒）`)
      return
    }

    // ---- Step 3: 等待图片库弹窗出现，并切到「免费正版图片」tab ----
    await page.waitForTimeout(1000)
    await this.switchToFreeImageTab(page)
    await page.waitForTimeout(1500)

    // ---- Step 4: 随机选一张图片 ----
    const picSelectors = [
      '.mp-ic-img-drawer .ic-search li.item .hover-icon',
      '.pgc-ic-image-tab-scope .ic-search li.item .hover-icon',
      '.mp-ic-img-drawer .ic-search li.item[style*="background-image"]',
      '.pgc-ic-image-tab-scope .ic-search li.item[style*="background-image"]',
      '.ic-search .wall-rows li.item',
      '.ic-search ul.list li.item',
      '.byte-modal__body img',
      '.byte-drawer-content img',
      '[class*="modal"] img',
      'img[src*="p3"]',
      '[class*="gallery"] img',
      '[class*="image-picker"] img',
      '[class*="img-list"] img',
      '.byte-image img',
      'img[class*="thumb"]',
      'img[class*="cover"]',
    ]

    let picClicked = false
    for (const sel of picSelectors) {
      try {
        const imgs = page.locator(sel)
        const count = await imgs.count()
        if (count > 0) {
          // 随机选一张（避开第一个可能是广告的）
          const idx = Math.min(Math.floor(Math.random() * Math.min(count, 8)) + 1, count - 1)
          const img = imgs.nth(idx)
          if (await img.isVisible({ timeout: 1000 }).catch(() => false)) {
            await img.click({ force: true })
            console.log(`[${this.platform}] 已选择第 ${idx + 1}/${count} 张免费图片`)
            picClicked = true
            await page.waitForTimeout(1500)
            break
          }
        }
      } catch {
        continue
      }
    }

    if (!picClicked) {
      await this.switchToFreeImageTab(page)
      await page.waitForTimeout(2000)
      picClicked = await page.evaluate(`() => {
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width >= 80 && rect.height >= 60
            && rect.bottom >= 0 && rect.top <= window.innerHeight
            && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const bgItems = Array.from(document.querySelectorAll(
          '.mp-ic-img-drawer .ic-search li.item, .pgc-ic-image-tab-scope .ic-search li.item, .ic-search ul.list li.item'
        )).filter((el) => visible(el) && String(el.getAttribute('style') || '').includes('background-image'));
        const bgItem = bgItems[Math.min(1, bgItems.length - 1)] || bgItems[0];
        if (bgItem) {
          bgItem.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
          bgItem.click();
          return true;
        }
        const imgs = Array.from(document.querySelectorAll('img'))
          .filter((img) => {
            const src = img.currentSrc || img.src || '';
            return src && !src.startsWith('data:') && !src.includes('base64') && visible(img);
          });
        const img = imgs[Math.min(1, imgs.length - 1)] || imgs[0];
        if (!img) return false;
        (img.closest('[class*="item"], [class*="card"], [class*="image"], li, div') || img).click();
        return true;
      }`)
      if (picClicked) {
        console.log(`[${this.platform}] 已通过 DOM 兜底选择免费正版图片`)
        await page.waitForTimeout(1500)
      }
    }

    if (!picClicked) {
      console.warn(`[${this.platform}] 未找到免费图片库中的图片`)
      return
    }

    if (await this.confirmFreeImageSelection(page) && await this.hasCoverSelected(page)) {
      await this.closeImageDrawer(page)
      return
    }
    await this.closeImageDrawer(page)
    console.warn(`[${this.platform}] 未能确认免费正版图片选择，尝试直接发布`)
  }

  private async confirmFreeImageSelection(page: Page): Promise<boolean> {
    await page.waitForTimeout(500)
    const selectors = [
      '.mp-ic-img-drawer .holder-bar .btns button:has-text("确定")',
      '.mp-ic-img-drawer .holder-bar button:has-text("确定")',
      '.mp-ic-img-drawer button.byte-btn-primary:has-text("确定")',
      '.mp-ic-img-drawer button:has-text("确定")',
      '.byte-drawer-wrapper:has(.mp-ic-img-drawer) .holder-bar .btns button:has-text("确定")',
      '.byte-drawer-wrapper:has(.mp-ic-img-drawer) button.byte-btn-primary:has-text("确定")',
      '.byte-drawer-wrapper:has(.mp-ic-img-drawer) button:has-text("确定")',
    ]
    for (const selector of selectors) {
      try {
        const buttons = page.locator(selector)
        const count = await buttons.count()
        for (let i = count - 1; i >= 0; i--) {
          const btn = buttons.nth(i)
          if (!(await btn.isVisible({ timeout: 800 }).catch(() => false))) continue
          const text = (await btn.innerText()).trim()
          if (text !== '确定') continue
          const disabled = await btn.evaluate((el: any) =>
            Boolean(el.disabled)
            || el.getAttribute('aria-disabled') === 'true'
            || String(el.className || '').includes('disabled'),
          )
          if (disabled) continue
          await btn.click({ force: true })
          console.log(`[${this.platform}] 已点击免费图片选择确定按钮 (${selector})`)
          await page.waitForTimeout(1500)
          return true
        }
      } catch {
        continue
      }
    }

    const clicked = await page.evaluate<boolean>(`() => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0
          && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const drawer = document.querySelector('.mp-ic-img-drawer');
      const root = drawer ? (drawer.closest('.byte-drawer-wrapper') || drawer) : document;
      const buttons = Array.from(root.querySelectorAll('button'));
      const btn = buttons.reverse().find((el) => visible(el)
        && (el.innerText || '').trim() === '确定'
        && !el.disabled
        && el.getAttribute('aria-disabled') !== 'true'
        && !String(el.className || '').includes('disabled'));
      if (!btn) return false;
      btn.click();
      return true;
    }`)
    if (clicked) {
      console.log(`[${this.platform}] 已通过 DOM 兜底点击免费图片选择确定按钮`)
      await page.waitForTimeout(1500)
      return true
    }
    console.warn(`[${this.platform}] 未找到免费图片选择确定按钮`)
    return false
  }

  private async hasCoverSelected(page: Page): Promise<boolean> {
    try {
      return await page.evaluate(`() => {
        const nodes = Array.from(document.querySelectorAll(
          '.article-cover-img-wrap img, .article-cover-images img, [class*="article-cover"] img'
        ));
        return nodes.some((img) => {
          const rect = img.getBoundingClientRect();
          const src = img.currentSrc || img.src || '';
          return rect.width > 40 && rect.height > 30
            && src
            && !src.startsWith('data:image/gif')
            && !src.includes('base64,R0lGOD');
        });
      }`)
    } catch {
      return false
    }
  }

  private async isImageDrawerVisible(page: Page): Promise<boolean> {
    try {
      return await page.evaluate(`() => {
        const drawer = document.querySelector('.mp-ic-img-drawer');
        if (!drawer) return false;
        const wrapper = drawer.closest('.byte-drawer-wrapper') || drawer;
        const rect = wrapper.getBoundingClientRect();
        const style = window.getComputedStyle(wrapper);
        return rect.width > 0 && rect.height > 0
          && style.display !== 'none'
          && style.visibility !== 'hidden'
          && !String(wrapper.className || '').includes('hide');
      }`)
    } catch {
      return false
    }
  }

  private async closeImageDrawer(page: Page): Promise<void> {
    try {
      if (!(await this.isImageDrawerVisible(page))) return
      const selectors = [
        '.mp-ic-img-drawer .byte-drawer-close-icon',
        '.byte-drawer-wrapper:has(.mp-ic-img-drawer) .byte-drawer-close-icon',
        '.mp-ic-img-drawer button[class*="close"]',
      ]
      for (const sel of selectors) {
        const btn = page.locator(sel).first()
        if ((await btn.count()) > 0 && await btn.isVisible({ timeout: 500 }).catch(() => false)) {
          await btn.click({ force: true })
          await page.waitForTimeout(800)
          console.log(`[${this.platform}] 已关闭图片选择抽屉`)
          return
        }
      }
      await page.keyboard.press('Escape')
      await page.waitForTimeout(500)
    } catch {
      // ignore
    }
  }

  private async switchToFreeImageTab(page: Page): Promise<boolean> {
    try {
      const switched = await page.evaluate(`() => {
        const labels = ['免费正版图片', '正版图片', '免费图片'];
        const isVisible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = window.getComputedStyle(el);
          return rect.width > 0 && rect.height > 0
            && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const nodes = Array.from(document.querySelectorAll('button, a, span, div, [role="tab"]'));
        for (const label of labels) {
          const target = nodes.find((el) => isVisible(el) && (el.innerText || '').trim() === label)
            || nodes.find((el) => isVisible(el) && (el.innerText || '').includes(label));
          if (target) {
            target.click();
            return true;
          }
        }
        return false;
      }`)
      if (switched) {
        console.log(`[${this.platform}] 已切换到免费正版图片标签`)
      }
      return Boolean(switched)
    } catch (err: any) {
      console.warn(`[${this.platform}] 切换免费正版图片标签失败:`, err.message)
      return false
    }
  }

  // ==========================================================
  //  点击发布（头条号专用）
  // ==========================================================

  /**
   * 头条号发布按钮文本是 "预览并发布"（部分版本 "发布"），
   * 过滤掉 "定时发布" / "发布设置" / "发布视频" / "发布图文" 等干扰。
   * 点击后处理二次确认弹窗（"确认发布" / "确定发布"）。
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
          if (text === '发布' || text === '预览并发布' || text === '确认发布') {
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
      'button:has-text("预览并发布")',
      'button.byte-btn-primary:has-text("预览并发布")',
      'button[class*="primary"]:has-text("预览并发布")',
      'button.byte-btn-primary:has-text("发布")',
      'button[class*="primary"]:has-text("发布")',
      'button:has-text("发布")',
      'button[class*="publish"]',
      'button[class*="submit"]',
      '[class*="publish"]:has-text("发布")',
      'button[type="submit"]:has-text("发布")',
    ]
    const excludeTexts = ['定时发布', '发布设置', '发布视频', '发布图文']
    const validTexts = ['预览并发布', '发布', '确认发布', '立即发布']

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

    // 4. 处理二次确认弹窗（手机预览 → 确认发布）
    await page.waitForTimeout(1500)
    const confirmSelectors = [
      'button:has-text("确认发布")',
      'button:has-text("确定发布")',
      'button:has-text("继续发布")',
      '.byte-modal__footer button:has-text("确认发布")',
      '.byte-modal__footer button.byte-btn-primary',
      'button:has-text("确认")',
      'button:has-text("确定")',
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

    const manualReason = await this.detectManualIntervention(page)
    if (manualReason) {
      throw new Error(manualReason)
    }
  }

  // ==========================================================
  //  等待发布结果（头条号专用）
  // ==========================================================

  /**
   * 头条号发布成功后：
   *   - 弹出 "发布成功" / "提交成功" / "审核中" 等提示
   *   - URL 跳转到内容管理 / articles / manage 等
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
    ]
    // 头条发布成功后 URL 跳转模式（对齐后端 toutiao_selectors.SUCCESS_URL_PATTERN）
    const successUrlPattern = /(articles|content_manage|content|graphic\/home|manage|home)/i
    const lastUrl = page.url()

    for (let i = 0; i < 45; i++) {
      const manualReason = await this.detectManualIntervention(page)
      if (manualReason) {
        throw new Error(manualReason)
      }

      // 失败检测
      for (const t of failTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 300 }))) {
            console.warn(`[${this.platform}] 检测到失败提示: ${t}`)
            throw new Error(`头条号发布失败: ${t}`)
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

  protected looksLikeManualIntervention(message: string): boolean {
    const lower = (message || '').toLowerCase()
    return ['登录', '登陆', 'login', 'passport', '验证码', '验证', 'captcha', '滑块', '风控', '安全'].some((key) =>
      lower.includes(key.toLowerCase()),
    )
  }

  protected async detectManualIntervention(page: Page): Promise<string | null> {
    const url = page.url().toLowerCase()
    if (['login', 'signin', 'passport', 'captcha', 'verify', 'security'].some((indicator) => url.includes(indicator))) {
      return '当前页面进入登录或安全验证流程，请人工完成后重新授权/重试发布'
    }

    try {
      const text = await page.evaluate<string | null>(`() => {
        const keywords = ['安全验证', '身份验证', '验证码', '人机验证', '滑块', '风控', '操作频繁'];
        const scopeSelector = [
          '.byte-modal', '.byte-message', '.byte-notification', '.byte-toast',
          '[class*="captcha"]', '[class*="verify"]', '[class*="security"]'
        ].join(',');
        const nodes = Array.from(document.querySelectorAll(scopeSelector));
        for (const node of nodes) {
          const rect = node.getBoundingClientRect();
          const style = window.getComputedStyle(node);
          if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') {
            continue;
          }
          const text = (node.innerText || '').trim();
          if (keywords.some((keyword) => text.includes(keyword))) {
            return text;
          }
        }
        return null;
      }`)
      return text
    } catch {
      return null
    }
  }
}
