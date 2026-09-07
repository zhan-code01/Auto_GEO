import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(storage_state="D:\\GEO\\Auto_GEO-main\\backend\\csdn_storage_state.json")
    page = await context.new_page()
    await page.goto("https://mp.csdn.net/mp_blog/creation/editor")
    await page.locator("#el_mcm-id-9988-82 img").click()
    await page.locator("p").filter(has_text="目录").get_by_role("button").click()
    await page.get_by_placeholder("请输入文章标题（5～100个字）").click()
    await page.get_by_placeholder("请输入文章标题（5～100个字）").fill("此处输入的是文章的标题")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").click()
    await (
        page.locator("#cke_1_contents iframe")
        .content_frame.locator("body")
        .fill("此处输入的是文章的正文，我们可以在这个地方输入文字和图片等信息的哦")
    )
    await (
        page.locator("#cke_1_contents iframe")
        .content_frame.get_by_text("此处输入的是文章的正文，我们可以在这个地方输入文字和图片等信息的哦")
        .click()
    )
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.locator("#cke_1_contents iframe").content_frame.locator("body").press("ArrowRight")
    await page.get_by_role("button", name="添加文章标签").click()
    await page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签").click()
    await page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签").fill("这个是可以写入一些标签的位置")
    await page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签").press("Enter")
    await page.get_by_role("button", name="发布博客").click()
    await page.locator("#passportbox2").get_by_role("img").click()
    await page.get_by_role("button", name="添加文章标签").click()
    await page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签").click()
    await page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签").fill("可以添加多个哦")
    await page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签").press("Enter")
    await page.get_by_role("button", name="发布博客").click()
    page.once("dialog", lambda dialog: dialog.dismiss())
    await page.goto("https://mp.csdn.net/mp_blog/creation/editor")
    await page.close()

    # ---------------------
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
