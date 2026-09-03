/**
 * AutoGeo ???? - ????Xiaohongshu????
 *
 * ???? xiaohongshu.py ????????
 *  - ?????? ? ???????
 *  - contenteditable ???????? click + keyboard.type
 *  - ??????????????????/???
 *  - ????????????????? / URL ??
 *
 * ?? BasePublisher????????????????????????
 */

import { BasePublisher } from './base'
import type { Page } from 'playwright'

export class XiaohongshuPublisher extends BasePublisher {
  platform = 'xiaohongshu'
  publishUrl = 'https://creator.xiaohongshu.com/publish/publish'

  // ???????????????????????????????????????
  loginMarkers = ['text=??', 'text=????', 'text=?????']

  titleSelector = [
    'input[placeholder*="????"]',
    'input[placeholder*="????"]',
    'input[placeholder*="??"]',
    'textarea[placeholder*="??"]',
    'input.max-title',
    '.title-input input',
    '.titleInput input',
    '.title textarea',
    '.title input',
  ].join(', ')

  contentSelector = [
    'textarea[placeholder*="????"]',
    'textarea[placeholder*="????"]',
    'textarea[placeholder*="??"]',
    'textarea[placeholder*="??"]',
    'textarea[placeholder*="??"]',
    'div[contenteditable="true"]',
    '.ql-editor',
    '.ProseMirror',
    '.editor-content',
    '.article-editor',
    '.note-content textarea',
  ].join(', ')

  /**
   * ????????? contenteditable ??????????????????
   */
  protected async fillContent(page: Page, content: string | null): Promise<void> {
    const plain = this.markdownToPlainText(content || '')
    if (!plain) {
      console.warn(`[${this.platform}] ?????????`)
      return
    }

    const selectors = this.contentSelector.split(',').map((s) => s.trim())
    let clicked = false
    for (const sel of selectors) {
      try {
        const editor = page.locator(sel).first()
        if ((await editor.count()) === 0) continue
        if (!(await editor.isVisible({ timeout: 2000 }).catch(() => false))) continue
        await editor.scrollIntoViewIfNeeded().catch(() => {})
        await editor.click()
        await page.waitForTimeout(500)
        clicked = true
        break
      } catch {
        continue
      }
    }

    if (!clicked) {
      try {
        await page.focus(this.contentSelector)
        await page.waitForTimeout(500)
      } catch (err) {
        console.warn(`[${this.platform}] ?????????: ${(err as Error).message}`)
        return
      }
    }

    await page.keyboard.press('Control+A').catch(() => {})
    await page.keyboard.press('Backspace').catch(() => {})
    await page.keyboard.type(plain, { delay: 10 })
    console.log(`[${this.platform}] ??????? ${plain.length} ??`)
  }

  /**
   * ???????????????? ??? ? ????/?? ? ???????
   */
  protected async clickPublish(page: Page): Promise<void> {
    const layoutClicked = await this.tryClickButton(page, ['????'])
    if (layoutClicked) {
      await page.waitForTimeout(1500)
      await this.tryClickButton(page, ['???'])
      await page.waitForTimeout(1000)
    }

    const excludeTexts = ['????', '??', '??', '??', '???']
    const published = await this.tryClickButton(page, ['????', '??'], { exclude: excludeTexts })
    if (!published) {
      console.warn(`[${this.platform}] ??????????????????`)
      await this.findAndClickPublishButton(page)
    }

    await page.waitForTimeout(1000)
    await this.tryClickButton(page, ['??', '??', '????', '????'], { timeoutMs: 2000 })
  }

  /**
   * ?????????????URL ????????????? publish ????
   */
  protected async waitForResult(page: Page): Promise<string> {
    const successTexts = ['????', '????', '???', '????']
    const errorTexts = ['????', '???', '???', '??', '??']

    const deadline = Date.now() + 45_000
    while (Date.now() < deadline) {
      for (const t of successTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
            const url = page.url()
            console.log(`[${this.platform}] ?????????: ${t} ? ${url}`)
            return url
          }
        } catch {
          continue
        }
      }

      for (const t of errorTexts) {
        try {
          const node = page.getByText(t, { exact: false }).first()
          if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
            const text = await node.innerText().catch(() => t)
            throw new Error(`?????????: ${text}`)
          }
        } catch (err) {
          if (err instanceof Error && err.message.startsWith('?????????')) throw err
          continue
        }
      }

      const url = page.url()
      if (!url.includes('/publish/publish') && url.includes('creator.xiaohongshu.com')) {
        console.log(`[${this.platform}] URL ???????: ${url}`)
        return url
      }

      await page.waitForTimeout(1000)
    }

    const finalUrl = page.url()
    console.warn(`[${this.platform}] ????????????? URL: ${finalUrl}`)
    return finalUrl
  }

  /**
   * ???????????????????????? + ?????
   */
  protected async tryClickButton(
    page: Page,
    texts: string[],
    options: { exclude?: string[]; timeoutMs?: number } = {},
  ): Promise<boolean> {
    const { exclude = [], timeoutMs = 3000 } = options
    void timeoutMs

    for (const text of texts) {
      try {
        const btns = page.getByRole('button', { name: new RegExp(text) })
        const count = await btns.count()
        for (let i = 0; i < count; i++) {
          const btn = btns.nth(i)
          if (!(await btn.isVisible({ timeout: 1500 }).catch(() => false))) continue
          const inner = (await btn.innerText().catch(() => '')) || ''
          if (exclude.some((ex) => inner.includes(ex))) continue
          await btn.scrollIntoViewIfNeeded().catch(() => {})
          await btn.click({ timeout: 5000 })
          console.log(`[${this.platform}] ????: "${text}" (role)`)
          return true
        }
      } catch {
        // ?? :has-text ??
      }

      try {
        const btn = page.locator(`button:has-text("${text}")`).first()
        if ((await btn.count()) === 0) continue
        if (!(await btn.isVisible({ timeout: 1500 }).catch(() => false))) continue
        const inner = (await btn.innerText().catch(() => '')) || ''
        if (exclude.some((ex) => inner.includes(ex))) continue
        await btn.scrollIntoViewIfNeeded().catch(() => {})
        await btn.click({ timeout: 5000 })
        console.log(`[${this.platform}] ????: "${text}" (css)`)
        return true
      } catch {
        continue
      }
    }
    return false
  }
}
