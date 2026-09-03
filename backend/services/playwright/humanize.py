# -*- coding: utf-8 -*-
"""
Human-like delays and input simulation.
移植自 Content Pilot (MIT) —— 让所有发布器的操作更像真人。
"""

import asyncio
import random
from typing import Optional

from playwright.async_api import Locator, Page


async def random_delay(min_sec: float = 2.0, max_sec: float = 8.0) -> None:
    """Wait a random duration to mimic human behavior."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def short_delay() -> None:
    """Brief pause between actions (0.5-1.5s)."""
    await asyncio.sleep(random.uniform(0.5, 1.5))


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type text with human-like speed variation.

    特点：字符间隔 50-150ms，5%几率出现较长停顿。
    """
    locator = page.locator(selector).first
    await locator.click()
    await short_delay()
    for idx, char in enumerate(text):
        await page.keyboard.type(char, delay=random.randint(50, 150))
        if random.random() < 0.05:  # 偶发长停顿（模拟思考/查资料）
            await asyncio.sleep(random.uniform(0.3, 0.8))
    if len(text) > 300:
        # 长文本中间休息一下
        await asyncio.sleep(random.uniform(1.0, 3.0))


async def human_click(page: Page, selector: str) -> None:
    """Click with a small random offset within element bounds."""
    locator = page.locator(selector).first
    box = await locator.bounding_box()
    if box:
        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        await page.mouse.click(x, y)
    else:
        await locator.click(force=True)
    await short_delay()


async def human_click_locator(locator: Locator) -> bool:
    """Click a locator with random offset. Returns True on success."""
    try:
        box = await locator.bounding_box()
        if box:
            # Generate random offsets within bounds
            x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
            y = box["y"] + box["height"] * random.uniform(0.2, 0.8)
            await locator.page.mouse.click(x, y)
            await short_delay()
            return True
        else:
            await locator.click(force=True)
            return True
    except Exception:
        return False


async def scroll_humanlike(page: Page, direction: str = "down", amount: int = 300) -> None:
    """Scroll subtly, as a human would."""
    for _ in range(random.randint(2, 5)):
        delta = amount * random.uniform(0.5, 1.5)
        if direction == "down":
            await page.mouse.wheel(0, delta)
        else:
            await page.mouse.wheel(0, -delta)
        await asyncio.sleep(random.uniform(0.1, 0.3))
