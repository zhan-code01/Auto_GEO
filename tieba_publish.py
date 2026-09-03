import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    await page.goto("https://tieba.baidu.com/")
    await page.locator("#top-bar div").filter(has_text="发贴").nth(2).click()
    await page.get_by_placeholder("选择吧").click()
    await page.get_by_placeholder("选择吧").fill("餐饮加盟")
    await page.get_by_text("餐饮加盟").first.click()
    await page.locator("#tb-editor-title").get_by_role("paragraph").click()
    await page.locator("#tb-editor-title div").fill("世界你好啊，我爱你世界")
    await page.locator("#tb-editor-content").get_by_role("paragraph").click()
    await page.locator("#tb-editor-content div").fill("世界如此多娇")
    await page.locator("div:nth-child(4) > .action-icon > use").click()
    await page.locator("div:nth-child(4) > .action-icon > use").click()
    await page.get_by_text("发布", exact=True).click()
    await page.locator("#top-bar img").nth(2).click()
    async with page.expect_popup() as page1_info:
        await page.get_by_text("个人主页").click()
    page1 = await page1_info.value
    await page1.locator(".thread-setting > svg").click()
    await page1.locator("div").filter(has_text="删除").nth(2).click()
    await page1.get_by_text("确定", exact=True).click()
    await page1.close()
    await page.close()

    # ---------------------
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
