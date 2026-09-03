import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.qianwen.com/")
    page.get_by_test_id("chat-input-content-measure").get_by_role("paragraph").click()
    page.get_by_role("textbox").fill("你好，你能帮我做什么呢？")
    page.get_by_label("发送消息").click()
    page.get_by_role("menuitem", name="复制为Markdown").click()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
