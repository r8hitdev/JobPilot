"""
Mock platform — generates fake job listings for demo/testing.
No browser or real site interaction. Selectable via config (platforms.mock.enabled)
or CLI (--mock flag implicit with mock enabled in config).
"""

from __future__ import annotations

import random
import uuid
from typing import Any

from jobpilot.platforms.base import Platform


# Realistic fake job data
_MOCK_COMPANIES = [
    "TechCorp", "InnoSoft", "DataBridge", "CloudNine Labs", "PixelForge",
    "NeuralOps", "Quantum Stack", "GreenLeaf Tech", "CipherSec", "VeloCode",
    "Nebula Systems", "PrimeLogic", "BlueShift AI", "Arcadia Software", "ZenithDev",
]

_MOCK_TITLES = [
    "Software Engineer Intern", "Backend Developer", "Python Developer",
    "Full Stack Developer", "Junior Software Engineer", "Data Engineer Intern",
    "API Developer", "DevOps Intern", "Software Development Intern",
    "Machine Learning Intern", "Frontend Developer", "QA Engineer Intern",
    "Cloud Engineer Intern", "Mobile App Developer", "Platform Engineer",
]

_MOCK_LOCATIONS = [
    "Bangalore, India", "Remote", "Mumbai, India", "Hyderabad, India",
    "Delhi, India", "Pune, India", "Work from Home", "Chennai, India",
]

_MOCK_DESCRIPTIONS = [
    "We are looking for a talented developer to join our team. Requirements: Python, "
    "REST APIs, SQL databases. You will work on building scalable backend services "
    "using FastAPI and PostgreSQL. Good understanding of Git and CI/CD pipelines required.",

    "Join our engineering team to build next-generation cloud infrastructure. "
    "Must have experience with Python, Docker, and Kubernetes. Strong problem-solving "
    "skills and ability to work in an agile environment.",

    "Exciting internship opportunity! Work on real projects with our senior engineers. "
    "Skills needed: Python, JavaScript, React. You will contribute to our web platform "
    "and learn modern development practices.",

    "Looking for a backend developer with Django/FastAPI experience. Must be comfortable "
    "with SQL databases, Redis, and message queues. Prior internship experience preferred.",

    "Data engineering role focused on building ETL pipelines. Required: Python, SQL, "
    "Apache Spark basics. Nice to have: AWS experience, Docker.",

    "We need a motivated developer to help build our API platform. Tech stack: "
    "Python, FastAPI, PostgreSQL, Redis. Remote-friendly position with flexible hours.",

    "Frontend developer needed for our dashboard product. Must know React, TypeScript, "
    "and CSS. Experience with data visualization libraries is a plus.",

    "Join our security team as a QA intern. You'll write automated tests using Python "
    "and Selenium. Good understanding of web security basics preferred.",
]

_MOCK_STIPENDS = [
    "₹15,000/month", "₹20,000/month", "₹10,000/month", "₹25,000/month",
    "₹30,000/month", "Unpaid", "₹5,000/month", "₹40,000/month",
    "₹8,000/month", "",
]


def _generate_fake_jobs(count: int = 15) -> list[dict[str, Any]]:
    """Generate a list of fake job listings."""
    jobs = []
    for i in range(count):
        job_id = f"mock_{uuid.uuid4().hex[:8]}"
        jobs.append({
            "platform_job_id": job_id,
            "title": random.choice(_MOCK_TITLES),
            "company": random.choice(_MOCK_COMPANIES),
            "location": random.choice(_MOCK_LOCATIONS),
            "url": f"https://mock.jobpilot.local/jobs/{job_id}",
            "description": random.choice(_MOCK_DESCRIPTIONS),
            "posted_at": None,
            "stipend": random.choice(_MOCK_STIPENDS),
        })
    return jobs


class MockPlatform(Platform):
    """Mock platform for demo and testing. No real browser interaction."""

    name = "mock"

    async def check_login(self, page: Any) -> str:
        """Mock always returns ok — no real session needed."""
        return "ok"

    async def search(self, page: Any) -> list[dict[str, Any]]:
        """Return a batch of fake job listings."""
        count = min(self.config.limits.max_per_run, 15)
        return _generate_fake_jobs(count)

    async def parse_listing(self, page: Any, url: str) -> dict[str, Any]:
        """Return a fake parsed listing."""
        return {
            "title": random.choice(_MOCK_TITLES),
            "company": random.choice(_MOCK_COMPANIES),
            "location": random.choice(_MOCK_LOCATIONS),
            "description": random.choice(_MOCK_DESCRIPTIONS),
            "url": url,
        }

    async def apply(self, page: Any, listing: dict[str, Any]) -> dict[str, Any]:
        """Mock apply always succeeds."""
        return {"success": True}
