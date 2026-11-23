"""
JobPilot cookie handling — parse Cookie-Editor JSON & Netscape cookies.txt,
normalize sameSite/expiry/domain, validate, and store under cookies/.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from jobpilot.settings import COOKIES_DIR

# Domain-to-platform mapping
PLATFORM_DOMAINS: dict[str, list[str]] = {
    "linkedin": [".linkedin.com", "linkedin.com", "www.linkedin.com"],
    "internshala": [".internshala.com", "internshala.com", "www.internshala.com"],
    "google": [".google.com", "google.com", "accounts.google.com", "www.google.com"],
}


def _normalize_domain(domain: str) -> str:
    """Ensure domain has a leading dot for proper cookie matching."""
    domain = domain.strip().lower()
    if not domain.startswith("."):
        domain = "." + domain
    return domain


def _normalize_same_site(value: Any) -> str:
    """Normalize sameSite to a valid Playwright value."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("strict", "lax", "none"):
            return v.capitalize() if v != "none" else "None"
    return "Lax"


def _normalize_expiry(expiry: Any) -> float | None:
    """Normalize expiry to a Unix timestamp float, or None for session cookies."""
    if expiry is None:
        return None
    try:
        ts = float(expiry)
        if ts < 0:
            return None
        return ts
    except (ValueError, TypeError):
        return None


def parse_cookie_editor_json(raw: str) -> list[dict[str, Any]]:
    """
    Parse Cookie-Editor extension JSON export format.
    Returns a list of normalized cookie dicts suitable for Playwright.

    Cookie-Editor format: list of objects with keys:
    name, value, domain, path, expirationDate, httpOnly, secure, sameSite
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of cookies")

    cookies = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        value = entry.get("value", "")
        if not name or not value:
            continue

        domain = entry.get("domain", "")
        path = entry.get("path", "/")
        expiry = entry.get("expirationDate") or entry.get("expiry")
        http_only = bool(entry.get("httpOnly", False))
        secure = bool(entry.get("secure", False))
        same_site = _normalize_same_site(entry.get("sameSite", "Lax"))

        cookie: dict[str, Any] = {
            "name": str(name),
            "value": str(value),
            "domain": _normalize_domain(domain) if domain else "",
            "path": str(path),
            "httpOnly": http_only,
            "secure": secure,
            "sameSite": same_site,
        }
        exp = _normalize_expiry(expiry)
        if exp is not None:
            cookie["expires"] = exp

        cookies.append(cookie)

    return cookies


def parse_netscape_cookies_txt(raw: str) -> list[dict[str, Any]]:
    """
    Parse Netscape cookies.txt (used by 'Get cookies.txt LOCALLY' extension).
    Format: domain  flag  path  secure  expiry  name  value
    Lines starting with # are comments. Each field is tab-separated.
    """
    cookies = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, _flag, path, secure_str, expiry_str, name, value = parts[:7]
        if not name or not value:
            continue

        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": _normalize_domain(domain),
            "path": path,
            "httpOnly": False,
            "secure": secure_str.upper() == "TRUE",
            "sameSite": "Lax",
        }
        exp = _normalize_expiry(expiry_str)
        if exp is not None and exp > 0:
            cookie["expires"] = exp

        cookies.append(cookie)

    return cookies


def parse_cookies(raw: str) -> list[dict[str, Any]]:
    """
    Auto-detect format and parse cookies from raw text.
    Tries JSON first, then Netscape cookies.txt.
    """
    stripped = raw.strip()
    if stripped.startswith("["):
        return parse_cookie_editor_json(stripped)
    else:
        return parse_netscape_cookies_txt(stripped)


def filter_cookies_for_platform(cookies: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    """Filter cookies to only those relevant for the given platform."""
    domains = PLATFORM_DOMAINS.get(platform, [])
    if not domains:
        return cookies

    result = []
    for c in cookies:
        cookie_domain = c.get("domain", "").lower()
        for pd in domains:
            if cookie_domain.endswith(pd) or pd.endswith(cookie_domain):
                result.append(c)
                break
    return result


def validate_cookies(cookies: list[dict[str, Any]], platform: str) -> dict[str, Any]:
    """
    Validate cookies for a platform.
    Returns {"valid": bool, "count": int, "expired": int, "errors": list[str]}.
    """
    errors: list[str] = []
    expired = 0
    now = datetime.now(timezone.utc).timestamp()

    platform_cookies = filter_cookies_for_platform(cookies, platform)

    if not platform_cookies:
        errors.append(f"No cookies found for platform '{platform}'")
        return {"valid": False, "count": 0, "expired": 0, "errors": errors}

    for c in platform_cookies:
        exp = c.get("expires")
        if exp is not None and exp < now:
            expired += 1

    active = len(platform_cookies) - expired
    if active == 0:
        errors.append("All cookies are expired")

    return {
        "valid": active > 0 and not errors,
        "count": len(platform_cookies),
        "expired": expired,
        "errors": errors,
    }


def save_cookies_file(cookies: list[dict[str, Any]], platform: str) -> Path:
    """
    Save cookies to a JSON file under cookies/.
    Sets file permissions to 600 (owner read/write only).
    Returns the path.
    """
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    path = COOKIES_DIR / f"{platform}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows doesn't support Unix permissions
    logger.info(f"Saved {len(cookies)} cookies for {platform} to {path}")
    return path


def load_cookies_file(platform: str) -> list[dict[str, Any]]:
    """Load saved cookies for a platform from cookies/. Returns [] if not found."""
    path = COOKIES_DIR / f"{platform}.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load cookies for {platform}: {e}")
        return []


def delete_cookies_file(platform: str) -> bool:
    """Delete saved cookies for a platform. Returns True if file was deleted."""
    path = COOKIES_DIR / f"{platform}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def cookies_to_playwright(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert normalized cookies to Playwright's add_cookies format.
    Playwright requires 'url' or 'domain', and specific key names.
    """
    result = []
    for c in cookies:
        pw_cookie: dict[str, Any] = {
            "name": c["name"],
            "value": c["value"],
            "path": c.get("path", "/"),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "sameSite": c.get("sameSite", "Lax"),
        }
        domain = c.get("domain", "")
        if domain:
            pw_cookie["domain"] = domain
        exp = c.get("expires")
        if exp is not None:
            pw_cookie["expires"] = exp
        result.append(pw_cookie)
    return result
