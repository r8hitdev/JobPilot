"""
Abstract base class for all platform integrations.
Each platform must implement: check_login, search, parse_listing, apply.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jobpilot.settings import AppConfig, Profile


class Platform(ABC):
    """Abstract base for a job platform (LinkedIn, Internshala, Google Jobs, Mock)."""

    name: str = ""

    def __init__(self, config: AppConfig, profile: Profile) -> None:
        self.config = config
        self.profile = profile

    @abstractmethod
    async def check_login(self, page: Any) -> str:
        """
        Check if the user is logged in on this platform.
        Returns: 'ok' | 'expired' | 'checkpoint' | 'missing'.
        """
        ...

    @abstractmethod
    async def search(self, page: Any) -> list[dict[str, Any]]:
        """
        Search for jobs using the configured filters.
        Returns a list of raw listing dicts with keys:
            platform_job_id, title, company, location, url, description,
            posted_at, stipend
        """
        ...

    @abstractmethod
    async def parse_listing(self, page: Any, url: str) -> dict[str, Any]:
        """
        Parse a single job listing page into a structured dict.
        """
        ...

    @abstractmethod
    async def apply(self, page: Any, listing: dict[str, Any]) -> dict[str, Any]:
        """
        Apply to a job. Returns:
            {"success": True} on success,
            {"success": False, "manual_needed": True, "reason": "..."} if needs manual,
            {"success": False, "error": "..."} on failure.
        """
        ...
