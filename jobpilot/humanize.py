"""
JobPilot humanize — random delays, small scrolls, active-hours check.
Makes automated browsing look more natural.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

from loguru import logger


async def random_delay(min_seconds: int = 8, max_seconds: int = 25) -> float:
    """Wait a random amount of time between actions. Returns the delay used."""
    delay = random.uniform(min_seconds, max_seconds)
    logger.debug(f"Humanize delay: {delay:.1f}s")
    await asyncio.sleep(delay)
    return delay


async def random_scroll(page: object) -> None:
    """Perform a small random scroll on the page to mimic human behavior."""
    try:
        scroll_y = random.randint(100, 400)
        direction = random.choice([1, -1])
        await page.evaluate(f"window.scrollBy(0, {scroll_y * direction})")  # type: ignore[attr-defined]
        await asyncio.sleep(random.uniform(0.3, 1.0))
    except Exception:
        pass  # Non-critical


def is_within_active_hours(start_hour: int = 9, end_hour: int = 22) -> bool:
    """Check whether the current time is within the configured active-hours window."""
    now = datetime.now()
    current_hour = now.hour
    if start_hour <= end_hour:
        return start_hour <= current_hour < end_hour
    else:
        # Wraps around midnight (e.g., 22-6)
        return current_hour >= start_hour or current_hour < end_hour


async def type_like_human(page: object, selector: str, text: str) -> None:
    """Type text with random inter-keystroke delays."""
    try:
        await page.click(selector)  # type: ignore[attr-defined]
        for char in text:
            await page.keyboard.press(char)  # type: ignore[attr-defined]
            await asyncio.sleep(random.uniform(0.03, 0.12))
    except Exception as e:
        # Fallback to direct fill
        try:
            await page.fill(selector, text)  # type: ignore[attr-defined]
        except Exception:
            logger.warning(f"Could not type into {selector}: {e}")
