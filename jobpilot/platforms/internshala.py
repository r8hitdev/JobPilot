"""
Internshala platform — search internships/jobs, apply with cover letter and custom questions.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from jobpilot.platforms.base import Platform
from jobpilot.platforms import selectors_internshala as sel
from jobpilot.humanize import random_delay, random_scroll
from jobpilot.llm import answer_question, generate_cover_note
from jobpilot import db


class IntershalaPlatform(Platform):
    name = "internshala"

    async def check_login(self, page: Any) -> str:
        try:
            await page.goto("https://internshala.com/student/dashboard",
                            wait_until="domcontentloaded", timeout=30000)
            for indicator in sel.LOGGED_IN_INDICATORS:
                el = await page.query_selector(indicator)
                if el:
                    return "ok"
            for indicator in sel.CHECKPOINT_INDICATORS:
                el = await page.query_selector(indicator)
                if el:
                    return "checkpoint"
            if "login" in page.url or "registration" in page.url:
                return "expired"
            return "expired"
        except Exception as e:
            logger.error(f"Internshala session check failed: {e}")
            return "missing"

    def _build_search_url(self, page_num: int = 1) -> str:
        search = self.config.search
        job_type = search.job_type

        if job_type == "full-time":
            base = sel.JOB_SEARCH_URL
        else:
            base = sel.INTERNSHIP_SEARCH_URL

        # Build filter path segments
        parts: list[str] = []
        if search.titles:
            keywords = ",".join(t.lower().replace(" ", "-") for t in search.titles)
            parts.append(f"keywords-{keywords}")
        if search.locations:
            locs = ",".join(loc.lower().replace(" ", "-") for loc in search.locations)
            parts.append(f"location-{locs}")

        url = base
        if parts:
            url += "/".join(parts) + "/"
        if page_num > 1:
            url += f"page-{page_num}/"

        return url

    async def search(self, page: Any) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        max_pages = 3

        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(page_num)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await random_scroll(page)
                await page.wait_for_timeout(2000)

                cards = await page.query_selector_all(sel.LISTING_CARD)
                if not cards:
                    break

                for card in cards:
                    try:
                        listing = await self._parse_card(card)
                        if listing:
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"Failed to parse Internshala card: {e}")

                # Check pagination
                next_link = await page.query_selector(sel.PAGINATION_NEXT)
                if not next_link:
                    break

            except Exception as e:
                logger.error(f"Internshala search page {page_num} failed: {e}")
                break

            await random_delay(3, 6)

        return listings

    async def _parse_card(self, card: Any) -> dict[str, Any] | None:
        title_el = await card.query_selector(sel.LISTING_TITLE)
        company_el = await card.query_selector(sel.LISTING_COMPANY)
        location_el = await card.query_selector(sel.LISTING_LOCATION)
        stipend_el = await card.query_selector(sel.LISTING_STIPEND)
        link_el = await card.query_selector(sel.LISTING_LINK)

        if not title_el:
            return None

        title = (await title_el.inner_text()).strip()
        company = (await company_el.inner_text()).strip() if company_el else ""
        location = (await location_el.inner_text()).strip() if location_el else ""
        stipend = (await stipend_el.inner_text()).strip() if stipend_el else ""
        href = ""
        if link_el:
            href = await link_el.get_attribute("href") or ""
            if href and not href.startswith("http"):
                href = f"https://internshala.com{href}"

        # Extract ID from card attribute or URL
        internship_id = await card.get_attribute(sel.LISTING_ID_ATTR) or ""
        if not internship_id and href:
            match = re.search(r"/(\d+)/?$", href)
            internship_id = match.group(1) if match else href

        return {
            "platform_job_id": str(internship_id),
            "title": title,
            "company": company,
            "location": location,
            "url": href,
            "description": "",  # Will be fetched on detail page
            "posted_at": None,
            "stipend": stipend,
        }

    async def parse_listing(self, page: Any, url: str) -> dict[str, Any]:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        result: dict[str, Any] = {"url": url}
        for key, s in [("title", sel.DETAIL_TITLE), ("company", sel.DETAIL_COMPANY),
                       ("location", sel.DETAIL_LOCATION), ("description", sel.DETAIL_DESCRIPTION),
                       ("stipend", sel.DETAIL_STIPEND)]:
            el = await page.query_selector(s)
            result[key] = (await el.inner_text()).strip() if el else ""

        return result

    async def apply(self, page: Any, listing: dict[str, Any]) -> dict[str, Any]:
        url = listing.get("url", "")
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

        # Click Apply
        apply_btn = await page.query_selector(sel.APPLY_BUTTON)
        if not apply_btn:
            return {"success": False, "error": "Apply button not found"}

        await apply_btn.click()
        await page.wait_for_timeout(2000)

        # Fill cover letter
        cover_ta = await page.query_selector(sel.COVER_LETTER_TEXTAREA)
        if cover_ta:
            cover_note = await generate_cover_note(
                job_title=listing.get("title", ""),
                company=listing.get("company", ""),
                description=listing.get("description", ""),
                profile_summary=self.profile.experience_summary,
            )
            await cover_ta.fill(cover_note)

        # Fill custom questions
        questions = await page.query_selector_all(sel.CUSTOM_QUESTION)
        for q_el in questions:
            label_el = await q_el.query_selector(sel.CUSTOM_QUESTION_TEXT)
            input_el = await q_el.query_selector(sel.CUSTOM_QUESTION_INPUT)
            if label_el and input_el:
                q_text = (await label_el.inner_text()).strip()
                if q_text:
                    # Check DB cache first
                    with db.get_conn() as conn:
                        cached = db.get_cached_answer(conn, q_text)
                    if cached:
                        answer = cached
                    else:
                        answer = await answer_question(
                            q_text, self.profile.experience_summary, self.profile.answer_bank
                        )
                        if answer:
                            with db.get_conn() as conn:
                                db.cache_answer(conn, q_text, answer, source="llm")
                    if answer:
                        await input_el.fill(answer)

        await page.wait_for_timeout(1000)

        # Submit
        submit_btn = await page.query_selector(sel.SUBMIT_BUTTON)
        if not submit_btn:
            return {"success": False, "manual_needed": True, "reason": "Submit button not found"}

        await submit_btn.click()
        await page.wait_for_timeout(2000)

        return {"success": True}
