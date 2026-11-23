"""
JobPilot settings — pydantic models for config.yaml, profile.yaml, and .env.
Provides load/save helpers for YAML and environment-based settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"
PROFILE_PATH = ROOT_DIR / "profile.yaml"
DATA_DIR = ROOT_DIR / "data"
COOKIES_DIR = ROOT_DIR / "cookies"
LOGS_DIR = ROOT_DIR / "logs"


# ── .env settings ──────────────────────────────────────────────

class EnvSettings(BaseSettings):
    """Settings loaded from .env / environment variables."""
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    llm_api_key: str = ""
    llm_model: str = "nvidia/nemotron-mini-4b-instruct"
    llm_fallback_model: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {"env_file": str(ROOT_DIR / ".env"), "env_file_encoding": "utf-8", "extra": "ignore"}


# ── config.yaml models ────────────────────────────────────────

class SearchConfig(BaseModel):
    titles: list[str] = Field(default_factory=lambda: ["Software Engineer"])
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["Remote"])
    remote_only: bool = False
    job_type: str = "both"
    experience_level: str = "entry"
    posted_within_days: int = 7


class FiltersConfig(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    min_stipend: int = 0
    min_llm_score: int = 70


class ActiveHours(BaseModel):
    start: int = 9
    end: int = 22


class ScheduleConfig(BaseModel):
    enabled: bool = False
    time: str = "10:00"


class LimitsConfig(BaseModel):
    max_daily: dict[str, int] = Field(default_factory=lambda: {"linkedin": 15, "internshala": 30})
    max_per_run: int = 50
    delay_min: int = 8
    delay_max: int = 25
    active_hours: ActiveHours = Field(default_factory=ActiveHours)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)


class BehaviorConfig(BaseModel):
    dry_run: bool = True
    headless: bool = True
    easy_apply_only: bool = True
    restart_browser_every: int = 50


class PlatformToggle(BaseModel):
    enabled: bool = False


class PlatformsConfig(BaseModel):
    linkedin: PlatformToggle = Field(default_factory=lambda: PlatformToggle(enabled=True))
    internshala: PlatformToggle = Field(default_factory=lambda: PlatformToggle(enabled=True))
    google_jobs: PlatformToggle = Field(default_factory=lambda: PlatformToggle(enabled=True))
    mock: PlatformToggle = Field(default_factory=PlatformToggle)


class AppConfig(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    platforms: PlatformsConfig = Field(default_factory=PlatformsConfig)


# ── profile.yaml models ───────────────────────────────────────

class Education(BaseModel):
    degree: str = ""
    institution: str = ""
    year: int = 2024
    gpa: str = ""


class PersonalInfo(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    country: str = ""


class Links(BaseModel):
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


class Profile(BaseModel):
    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience_summary: str = ""
    resume_path: str = ""
    links: Links = Field(default_factory=Links)
    answer_bank: dict[str, str] = Field(default_factory=dict)


# ── YAML load / save helpers ──────────────────────────────────

def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_config(path: Path | None = None) -> AppConfig:
    """Load config.yaml into an AppConfig model."""
    return AppConfig(**_read_yaml(path or CONFIG_PATH))


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """Persist an AppConfig model to config.yaml."""
    _write_yaml(path or CONFIG_PATH, cfg.model_dump())


def load_profile(path: Path | None = None) -> Profile:
    """Load profile.yaml into a Profile model."""
    return Profile(**_read_yaml(path or PROFILE_PATH))


def save_profile(profile: Profile, path: Path | None = None) -> None:
    """Persist a Profile model to profile.yaml."""
    _write_yaml(path or PROFILE_PATH, profile.model_dump())


def load_env() -> EnvSettings:
    """Load environment / .env settings."""
    return EnvSettings()
