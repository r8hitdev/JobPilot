"""
JobPilot filters — keyword/location/stipend/company blacklist/dedupe rules.
Deterministic filtering runs BEFORE any LLM call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from loguru import logger


@dataclass
class FilterResult:
    """Result of applying filters to a job listing."""
    passed: bool
    reason: str = ""


def normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def check_must_include(
    title: str, description: str, must_include: list[str]
) -> FilterResult:
    """Check that at least one must-include keyword appears in title or description."""
    if not must_include:
        return FilterResult(passed=True)

    combined = normalize_text(f"{title} {description}")
    for kw in must_include:
        if kw.lower() in combined:
            return FilterResult(passed=True)

    return FilterResult(passed=False, reason=f"Missing required keywords: {must_include}")


def check_exclude_keywords(
    title: str, description: str, exclude_keywords: list[str]
) -> FilterResult:
    """Check that no excluded keywords appear in the title or description."""
    if not exclude_keywords:
        return FilterResult(passed=True)

    combined = normalize_text(f"{title} {description}")
    for kw in exclude_keywords:
        if kw.lower() in combined:
            return FilterResult(passed=False, reason=f"Excluded keyword found: '{kw}'")

    return FilterResult(passed=True)


def check_exclude_companies(
    company: str, exclude_companies: list[str]
) -> FilterResult:
    """Check the company is not in the blacklist (case-insensitive)."""
    if not exclude_companies:
        return FilterResult(passed=True)

    company_lower = company.strip().lower()
    for exc in exclude_companies:
        if exc.lower() == company_lower:
            return FilterResult(passed=False, reason=f"Company blacklisted: '{exc}'")

    return FilterResult(passed=True)


def check_min_stipend(
    stipend_text: str, min_stipend: int
) -> FilterResult:
    """
    Check that stipend meets minimum. Parses common formats like
    '₹10,000/month', '$500', '10000', 'Unpaid'.
    """
    if min_stipend <= 0:
        return FilterResult(passed=True)

    if not stipend_text or not stipend_text.strip():
        # No stipend info — let it through (could be a full-time job)
        return FilterResult(passed=True)

    # Extract numeric value
    cleaned = re.sub(r"[₹$,\s]", "", stipend_text)
    match = re.search(r"(\d+)", cleaned)
    if not match:
        # Can't parse stipend, let it through
        return FilterResult(passed=True)

    amount = int(match.group(1))
    if amount < min_stipend:
        return FilterResult(
            passed=False,
            reason=f"Stipend {stipend_text} below minimum {min_stipend}",
        )

    return FilterResult(passed=True)


def check_location(
    job_location: str,
    allowed_locations: list[str],
    remote_only: bool,
) -> FilterResult:
    """Check location matches allowed locations or remote preference."""
    if not allowed_locations and not remote_only:
        return FilterResult(passed=True)

    loc_lower = normalize_text(job_location)

    if remote_only:
        remote_terms = ["remote", "work from home", "wfh", "anywhere"]
        if any(term in loc_lower for term in remote_terms):
            return FilterResult(passed=True)
        return FilterResult(passed=False, reason=f"Not remote: '{job_location}'")

    if not allowed_locations:
        return FilterResult(passed=True)

    for allowed in allowed_locations:
        if allowed.lower() in loc_lower or loc_lower in allowed.lower():
            return FilterResult(passed=True)
        # Also pass if "remote" is in the location
        if "remote" in loc_lower:
            return FilterResult(passed=True)

    return FilterResult(
        passed=False,
        reason=f"Location '{job_location}' not in allowed: {allowed_locations}",
    )


def is_duplicate(
    title: str,
    company: str,
    existing_jobs: list[dict[str, Any]],
    threshold: int = 85,
) -> FilterResult:
    """
    Check if a job is a fuzzy duplicate of an existing one (same company, similar title).
    Uses rapidfuzz for fuzzy matching.
    """
    title_norm = normalize_text(title)
    company_norm = normalize_text(company)

    for job in existing_jobs:
        existing_company = normalize_text(job.get("company", ""))
        existing_title = normalize_text(job.get("title", ""))

        if company_norm == existing_company:
            similarity = fuzz.ratio(title_norm, existing_title)
            if similarity >= threshold:
                return FilterResult(
                    passed=False,
                    reason=f"Duplicate of '{job.get('title')}' at '{job.get('company')}' (similarity: {similarity}%)",
                )

    return FilterResult(passed=True)


def apply_all_filters(
    title: str,
    company: str,
    location: str,
    description: str,
    stipend: str,
    config_filters: dict[str, Any],
    config_search: dict[str, Any],
    existing_jobs: list[dict[str, Any]] | None = None,
) -> FilterResult:
    """
    Run all deterministic filters on a job listing.
    Returns FilterResult(passed=True) if the job passes all filters,
    or the first failing filter's result.
    """
    checks = [
        check_exclude_companies(company, config_filters.get("exclude_companies", [])),
        check_exclude_keywords(title, description, config_filters.get("exclude_keywords", [])),
        check_must_include(title, description, config_filters.get("must_include", [])),
        check_min_stipend(stipend, config_filters.get("min_stipend", 0)),
        check_location(
            location,
            config_search.get("locations", []),
            config_search.get("remote_only", False),
        ),
    ]

    for result in checks:
        if not result.passed:
            return result

    # Dedupe check
    if existing_jobs is not None:
        dedupe = is_duplicate(title, company, existing_jobs)
        if not dedupe.passed:
            return dedupe

    return FilterResult(passed=True)
