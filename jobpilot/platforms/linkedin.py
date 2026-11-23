"""
LinkedIn platform — Jobs search with Easy Apply.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from loguru import logger

from jobpilot.platforms.base import Platform
from jobpilot.platforms import selectors_linkedin as sel
from jobpilot.humanize import random_delay, random_scroll
from jobpilot.llm import answer_question, generate_cover_note
from jobpilot import db


class LinkedInPlatform(Platform):
    name = "linkedin"

    async def check_login(self, page: Any) -> str:
        try:
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            for indicator in sel.LOGGED_IN_INDICATORS:
                el = await page.query_selector(indicator)
                if el:
                    return "ok"
            for indicator in sel.CHECKPOINT_INDICATORS:
                el = await page.query_selector(indicator)
                if el:
                    return "checkpoint"
            if "login" in page.url or "authwall" in page.url:
                return "expired"
            return "expired"
        except Exception as e:
            logger.error(f"LinkedIn session check failed: {e}")
            return "missing"

    def _build_search_url(self, page_num: int = 0) -> str:
        params: dict[str, str] = {}
        search = self.config.search
        keywords = " ".join(search.titles + search.keywords)
        if keywords:
            params["keywords"] = keywords
        if search.locations:
            params["location"] = search.locations[0]
        if search.remote_only:
            params["f_WT"] = "2"  # Remote
        if search.posted_within_days <= 1:
            params["f_TPR"] = "r86400"
        elif search.posted_within_days <= 7:
            params["f_TPR"] = "r604800"
        elif search.posted_within_days <= 30:
            params["f_TPR"] = "r2592000"
        if self.config.behavior.easy_apply_only:
            params["f_AL"] = "true"
        if search.experience_level == "entry":
            params["f_E"] = "1,2"
        elif search.experience_level == "mid":
            params["f_E"] = "3,4"
        elif search.experience_level == "senior":
            params["f_E"] = "5,6"
        if page_num > 0:
            params["start"] = str(page_num * 25)
        return f"{sel.JOBS_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    async def search(self, page: Any) -> list[dict[str, Any]]:
        listings: list[dict[str, Any]] = []
        max_pages = 3  # Limit pagination

        for page_num in range(max_pages):
            url = self._build_search_url(page_num)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await random_scroll(page)
                await page.wait_for_timeout(2000)

                cards = await page.query_selector_all(sel.JOB_CARDS)
                if not cards:
                    break

                for card in cards:
                    try:
                        listing = await self._parse_card(page, card)
                        if listing:
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"Failed to parse LinkedIn card: {e}")

                # Check if there's a next page
                next_btn = await page.query_selector(sel.PAGINATION_NEXT)
                if not next_btn:
                    break

            except Exception as e:
                logger.error(f"LinkedIn search page {page_num} failed: {e}")
                break

            await random_delay(3, 6)

        return listings

    async def _parse_card(self, page: Any, card: Any) -> dict[str, Any] | None:
        title_el = await card.query_selector(sel.JOB_CARD_TITLE)
        company_el = await card.query_selector(sel.JOB_CARD_COMPANY)
        location_el = await card.query_selector(sel.JOB_CARD_LOCATION)
        link_el = await card.query_selector(sel.JOB_CARD_LINK)

        if not title_el or not link_el:
            return None

        title = (await title_el.inner_text()).strip()
        company = (await company_el.inner_text()).strip() if company_el else ""
        location = (await location_el.inner_text()).strip() if location_el else ""
        href = await link_el.get_attribute("href") or ""

        # Extract job ID from URL
        job_id_match = re.search(r"/view/(\d+)", href)
        if not job_id_match:
            job_id_match = re.search(r"currentJobId=(\d+)", href)
        platform_job_id = job_id_match.group(1) if job_id_match else href

        # Click to load detail panel
        try:
            await title_el.click()
            await page.wait_for_timeout(1500)
            desc_el = await page.query_selector(sel.JOB_DETAIL_DESCRIPTION)
            description = (await desc_el.inner_text()).strip() if desc_el else ""
        except Exception:
            description = ""

        full_url = f"https://www.linkedin.com/jobs/view/{platform_job_id}/" if platform_job_id.isdigit() else href

        return {
            "platform_job_id": platform_job_id,
            "title": title,
            "company": company,
            "location": location,
            "url": full_url,
            "description": description,
            "posted_at": None,
            "stipend": "",
        }

    async def parse_listing(self, page: Any, url: str) -> dict[str, Any]:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        title = ""
        company = ""
        location = ""
        description = ""

        for s in [sel.JOB_DETAIL_TITLE]:
            el = await page.query_selector(s)
            if el:
                title = (await el.inner_text()).strip()
                break

        el = await page.query_selector(sel.JOB_DETAIL_COMPANY)
        if el:
            company = (await el.inner_text()).strip()

        el = await page.query_selector(sel.JOB_DETAIL_LOCATION)
        if el:
            location = (await el.inner_text()).strip()

        el = await page.query_selector(sel.JOB_DETAIL_DESCRIPTION)
        if el:
            description = (await el.inner_text()).strip()

        return {
            "title": title,
            "company": company,
            "location": location,
            "description": description,
            "url": url,
        }

    async def apply(self, page: Any, listing: dict[str, Any]) -> dict[str, Any]:
        url = listing.get("url", "")
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

        # Check for external apply (not Easy Apply)
        ext_btn = await page.query_selector(sel.EXTERNAL_APPLY_BUTTON)
        if ext_btn:
            return {
                "success": False,
                "manual_needed": True,
                "reason": f"External apply — visit {url}",
            }

        # Click Easy Apply
        easy_btn = await page.query_selector(sel.EASY_APPLY_BUTTON)
        if not easy_btn:
            return {"success": False, "error": "Easy Apply button not found"}

        await easy_btn.click()
        await page.wait_for_timeout(2000)

        # Check modal opened
        modal = await page.query_selector(sel.EASY_APPLY_MODAL)
        if not modal:
            return {"success": False, "error": "Easy Apply modal did not open"}

        # Walk through multi-step form
        max_steps = 10
        for step in range(max_steps):
            # Fill any form fields
            await self._fill_form_fields(page)
            await page.wait_for_timeout(1000)

            # Check for submit button
            submit_btn = await page.query_selector(sel.EASY_APPLY_SUBMIT)
            if submit_btn:
                # This is the final step — submit (or not in dry-run, handled by runner)
                await submit_btn.click()
                await page.wait_for_timeout(2000)
                return {"success": True}

            # Check for review button
            review_btn = await page.query_selector(sel.EASY_APPLY_REVIEW)
            if review_btn:
                await review_btn.click()
                await page.wait_for_timeout(1500)
                continue

            # Click next
            next_btn = await page.query_selector(sel.EASY_APPLY_NEXT)
            if next_btn:
                await next_btn.click()
                await page.wait_for_timeout(1500)
                continue

            # No navigation button found — stuck
            break

        # Close the modal
        close_btn = await page.query_selector(sel.EASY_APPLY_CLOSE)
        if close_btn:
            await close_btn.click()
            discard_btn = await page.query_selector(sel.EASY_APPLY_DISCARD)
            if discard_btn:
                await discard_btn.click()

        return {"success": False, "manual_needed": True, "reason": "Could not complete Easy Apply steps"}

    async def _fill_form_fields(self, page: Any) -> None:
        """Fill text inputs, selects, and file uploads in the Easy Apply modal."""
        # Text inputs
        inputs = await page.query_selector_all(sel.FORM_TEXT_INPUT)
        for inp in inputs:
            value = await inp.input_value()
            if value:
                continue  # Already filled
            label_el = await inp.evaluate_handle(
                "el => el.closest('.jobs-easy-apply-form-section__grouping')?.querySelector('label')"
            )
            label = ""
            if label_el:
                label = await label_el.evaluate("el => el.textContent || ''")
                label = label.strip()
            if label:
                answer = await answer_question(
                    label, self.profile.experience_summary, self.profile.answer_bank
                )
                if answer:
                    await inp.fill(answer)

        # Textareas
        textareas = await page.query_selector_all(sel.FORM_TEXTAREA)
        for ta in textareas:
            value = await ta.input_value()
            if value:
                continue
            label_el = await ta.evaluate_handle(
                "el => el.closest('.jobs-easy-apply-form-section__grouping')?.querySelector('label')"
            )
            label = ""
            if label_el:
                label = await label_el.evaluate("el => el.textContent || ''")
                label = label.strip()
            if label:
                answer = await answer_question(
                    label, self.profile.experience_summary, self.profile.answer_bank
                )
                if answer:
                    await ta.fill(answer)

        # File upload (resume)
        file_inputs = await page.query_selector_all(sel.FORM_FILE_UPLOAD)
        for fi in file_inputs:
            if self.profile.resume_path:
                try:
                    await fi.set_input_files(self.profile.resume_path)
                except Exception as e:
                    logger.warning(f"Resume upload failed: {e}")
