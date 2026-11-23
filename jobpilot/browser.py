"""
JobPilot browser — launch Chromium, context management, route-blocking,
session checking, and screenshots. Uses Playwright async API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from jobpilot.settings import LOGS_DIR, load_config
from jobpilot.cookies import load_cookies_file, cookies_to_playwright

# Blocked resource patterns for RAM saving
BLOCKED_PATTERNS = [
    "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif", "**/*.svg", "**/*.webp",
    "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.eot",
    "**/*.mp4", "**/*.webm", "**/*.ogg", "**/*.mp3",
    "**/analytics*", "**/tracking*", "**/ads*", "**/pixel*",
    "**/google-analytics*", "**/googletagmanager*",
]

CHROMIUM_ARGS = [
    "--disable-gpu",
    "--disable-extensions",
    "--disable-dev-shm-usage",
    "--js-flags=--max-old-space-size=256",
    "--no-sandbox",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-translate",
    "--mute-audio",
]


class BrowserManager:
    """Manages a single Playwright Chromium browser instance."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._jobs_since_restart: int = 0

    @property
    def is_running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def launch(self, headless: bool = True) -> None:
        """Launch Chromium with memory-saving args."""
        from playwright.async_api import async_playwright

        if self.is_running:
            return

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=CHROMIUM_ARGS,
        )
        self._jobs_since_restart = 0
        logger.info(f"Browser launched (headless={headless})")

    async def new_context(self, platform: str | None = None) -> Any:
        """
        Create a new browser context with route-blocking.
        If platform is given, injects saved cookies.
        """
        if not self.is_running:
            raise RuntimeError("Browser not running")

        # Close old context if any
        await self.close_context()

        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # Block heavy resources to save RAM
        await self._context.route("**/*", self._route_handler)

        # Inject cookies if platform specified
        if platform:
            cookies = load_cookies_file(platform)
            if cookies:
                pw_cookies = cookies_to_playwright(cookies)
                try:
                    await self._context.add_cookies(pw_cookies)
                    logger.info(f"Injected {len(pw_cookies)} cookies for {platform}")
                except Exception as e:
                    logger.warning(f"Failed to inject some cookies for {platform}: {e}")

        self._page = await self._context.new_page()
        return self._page

    async def _route_handler(self, route: Any) -> None:
        """Block images, fonts, media, and analytics to save RAM."""
        url = route.request.url
        resource_type = route.request.resource_type

        if resource_type in ("image", "font", "media"):
            await route.abort()
            return

        # Block analytics/tracking
        blocked_domains = ["google-analytics", "googletagmanager", "facebook.com/tr",
                           "doubleclick", "analytics", "tracking"]
        if any(d in url for d in blocked_domains):
            await route.abort()
            return

        await route.continue_()

    async def close_context(self) -> None:
        """Close the current context and page."""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

    async def close(self) -> None:
        """Shut down the browser entirely."""
        await self.close_context()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Browser closed")

    async def restart_if_needed(self, threshold: int = 50, headless: bool = True) -> None:
        """Restart browser after processing `threshold` jobs to reclaim RAM."""
        self._jobs_since_restart += 1
        if self._jobs_since_restart >= threshold:
            logger.info(f"Restarting browser after {self._jobs_since_restart} jobs")
            await self.close()
            await self.launch(headless=headless)

    async def take_screenshot(self, name: str = "") -> Path | None:
        """Take a screenshot and save to logs/. Returns the path."""
        if not self._page:
            return None
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{name}_{ts}.png" if name else f"screenshot_{ts}.png"
        path = LOGS_DIR / filename
        try:
            await self._page.screenshot(path=str(path))
            logger.debug(f"Screenshot saved: {path}")
            return path
        except Exception as e:
            logger.warning(f"Failed to take screenshot: {e}")
            return None

    @property
    def page(self) -> Any:
        return self._page

    @property
    def context(self) -> Any:
        return self._context


# Session checking helpers

async def check_session(page: Any, platform: str) -> str:
    """
    Check if the user is logged in on the given platform.
    Returns: 'ok', 'expired', 'checkpoint', 'missing'.
    """
    try:
        if platform == "linkedin":
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            # Check for logged-in indicator
            if await page.query_selector('[data-control-name="identity_welcome_message"]') or \
               await page.query_selector('.feed-identity-module') or \
               await page.query_selector('div.feed-shared-actor'):
                return "ok"
            # Check for checkpoint/verification
            if await page.query_selector('[data-test="challenge"]') or \
               "checkpoint" in page.url:
                return "checkpoint"
            return "expired"

        elif platform == "internshala":
            await page.goto("https://internshala.com/student/dashboard", wait_until="domcontentloaded", timeout=30000)
            if await page.query_selector('.profile_container') or \
               await page.query_selector('#student_dashboard'):
                return "ok"
            if "login" in page.url:
                return "expired"
            return "expired"

        elif platform == "google":
            await page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=30000)
            if await page.query_selector('[data-ogsr-up]') or \
               await page.query_selector('.gb_A'):
                return "ok"
            return "expired"

        return "missing"
    except Exception as e:
        logger.error(f"Session check failed for {platform}: {e}")
        return "missing"
