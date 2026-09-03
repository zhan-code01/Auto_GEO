import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    await page.goto("https://mp.toutiao.com/profile_v4/graphic/publish?is_new_connect=0&is_new_user=0")
    await page.get_by_role("heading", name="头条创作助手").locator("svg").click()
    await page.get_by_placeholder("请输入文章标题（2～30个字）").click()
    await page.get_by_placeholder("请输入文章标题（2～30个字）").fill("世界你好")
    await page.get_by_role("paragraph").click()
    await page.locator("div").filter(has_text=re.compile(r"^请输入正文$")).fill("你好世界\n\n\n")
    await page.locator(".add-icon").click()
    await page.get_by_text("免费正版图片").click()
    await page.locator(".wall-rows > div > .list > li").first.click()
    await page.get_by_role("button", name="确定").click()
    await page.get_by_role("button", name="预览并发布").click()
    await page.get_by_role("button", name="确认发布").click()
    await page.locator(".byte-modal-close-icon").click()
    await page.locator("g > circle").first.click()
    await page.get_by_role("link", name="文章").click()
    await page.locator(".byte-drawer-mask").click()
    await page.locator("g > path").first.click()
    async with page.expect_popup() as page1_info:
        await page.get_by_role("link", name="鲲界科技-丘总").click()
    page1 = await page1_info.value
    await page1.locator("div").filter(has_text=re.compile(r"^0阅读2分钟前置顶$")).get_by_role("button").click()
    await page1.locator("div").filter(has_text=re.compile(r"^0阅读2分钟前置顶$")).get_by_role("button").click()

    # ---------------------
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
