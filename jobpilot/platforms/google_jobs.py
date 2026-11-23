"""
Google Jobs platform — used only for job discovery.
Collects listing links and keeps only those pointing to LinkedIn or Internshala.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from loguru import logger

from jobpilot.platforms.base import Platform
from jobpilot.platforms import selectors_google as sel
from jobpilot.humanize import random_delay, random_scroll


class GoogleJobsPlatform(Platform):
    name = "google_jobs"

    async def check_login(self, page: Any) -> str:
        """Google Jobs doesn't strictly require login, but we check Google session."""
        try:
            await page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=20000)
            # Look for signed-in indicators
            signed_in = await page.query_selector('[data-ogsr-up]')
            if signed_in:
                return "ok"
            # Even without login, Google Jobs works
            return "ok"
        except Exception:
            return "ok"  # Google Jobs works without login

    def _build_search_url(self, title: str, location: str) -> str:
        query = f"{title} {location} jobs"
        params = {"q": query, "ibp": "htl;jobs"}
        return f"{sel.GOOGLE_JOBS_URL}?{urllib.parse.urlencode(params)}"

    async def search(self, page: Any) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        search = self.config.search

        for title in search.titles[:3]:  # Limit queries
            for location in search.locations[:2]:
                url = self._build_search_url(title, location)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                    await random_scroll(page)

                    # Find apply links within the jobs widget
                    links = await page.query_selector_all(sel.APPLY_LINK)
                    for link in links:
                        try:
                            href = await link.get_attribute("href") or ""
                            # Keep only LinkedIn and Internshala links
                            if "linkedin.com" in href or "internshala.com" in href:
                                text_el = await link.query_selector("span")
                                text = (await text_el.inner_text()).strip() if text_el else ""

                                platform = "linkedin" if "linkedin.com" in href else "internshala"
                                # Extract job ID from URL
                                job_id = self._extract_job_id(href, platform)

                                listings.append({
                                    "platform_job_id": f"gj_{job_id}",
                                    "title": title,  # Use search title as fallback
                                    "company": text or "",
                                    "location": location,
                                    "url": href,
                                    "description": "",
                                    "posted_at": None,
                                    "stipend": "",
                                    "source_platform": platform,
                                })
                        except Exception as e:
                            logger.debug(f"Failed to parse Google Jobs link: {e}")

                except Exception as e:
                    logger.error(f"Google Jobs search failed for '{title} {location}': {e}")

                await random_delay(3, 6)

        return listings

    def _extract_job_id(self, url: str, platform: str) -> str:
        if platform == "linkedin":
            match = re.search(r"/view/(\d+)", url)
            return match.group(1) if match else url[:64]
        elif platform == "internshala":
            match = re.search(r"/(\d+)/?$", url)
            return match.group(1) if match else url[:64]
        return url[:64]

    async def parse_listing(self, page: Any, url: str) -> dict[str, Any]:
        """Google Jobs listings are redirect links — we just return the URL."""
        return {"url": url, "title": "", "company": "", "description": ""}

    async def apply(self, page: Any, listing: dict[str, Any]) -> dict[str, Any]:
        """Google Jobs doesn't apply directly — mark as manual_needed with the URL."""
        return {
            "success": False,
            "manual_needed": True,
            "reason": f"Apply via source platform: {listing.get('url', '')}",
        }
