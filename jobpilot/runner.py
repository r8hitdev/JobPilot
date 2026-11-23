"""
JobPilot runner — orchestrates a run, enforces daily caps, stop flag, event emitter.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from jobpilot import db, events, filters
from jobpilot.browser import BrowserManager
from jobpilot.events import event_bus
from jobpilot.llm import get_run_tokens, reset_run_tokens, score_job
from jobpilot.humanize import random_delay, is_within_active_hours
from jobpilot.settings import load_config, load_profile, AppConfig, Profile


class RunState:
    """Tracks the state of the current run, including stop flag."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.should_stop: bool = False
        self.current_run_id: int | None = None
        self.mode: str = "dry"
        self._task: asyncio.Task[None] | None = None

    def request_stop(self) -> None:
        self.should_stop = True

    @property
    def status(self) -> str:
        if self.is_running:
            return "running"
        if self.should_stop:
            return "stopped"
        return "idle"


# Global run state
run_state = RunState()


def _get_platform_instance(name: str, config: AppConfig, profile: Profile) -> Any:
    """Lazily import and instantiate a platform by name."""
    if name == "linkedin":
        from jobpilot.platforms.linkedin import LinkedInPlatform
        return LinkedInPlatform(config, profile)
    elif name == "internshala":
        from jobpilot.platforms.internshala import IntershalaPlatform
        return IntershalaPlatform(config, profile)
    elif name == "google_jobs":
        from jobpilot.platforms.google_jobs import GoogleJobsPlatform
        return GoogleJobsPlatform(config, profile)
    elif name == "mock":
        from jobpilot.platforms.mock import MockPlatform
        return MockPlatform(config, profile)
    else:
        raise ValueError(f"Unknown platform: {name}")


async def execute_run(
    dry_run: bool = True,
    cli_mode: bool = False,
    config_override: AppConfig | None = None,
) -> dict[str, Any]:
    """
    Execute a full application run. This is the main orchestration function.

    Args:
        dry_run: If True, skip the final submit click.
        cli_mode: If True, running from CLI (no web server).
        config_override: If provided, use this config instead of loading from file.

    Returns:
        Summary dict with counts.
    """
    global run_state

    if run_state.is_running:
        await event_bus.publish("Run already in progress", level="warning")
        return {"error": "Run already in progress"}

    config = config_override or load_config()
    profile = load_profile()
    run_state.is_running = True
    run_state.should_stop = False
    run_state.mode = "dry" if dry_run else "live"
    reset_run_tokens()

    db.init_db()
    summary = {"found": 0, "filtered": 0, "applied": 0, "failed": 0, "manual": 0}

    with db.get_conn() as conn:
        run_id = db.create_run(conn, mode=run_state.mode)
        run_state.current_run_id = run_id

    await event_bus.publish(
        f"Run started (mode={'DRY RUN' if dry_run else 'LIVE'})",
        level="info", run_id=run_id,
    )

    browser = BrowserManager()

    try:
        # Check active hours
        active_hours = config.limits.active_hours
        if not is_within_active_hours(active_hours.start, active_hours.end):
            await event_bus.publish(
                f"Outside active hours ({active_hours.start}:00–{active_hours.end}:00). Skipping.",
                level="warning", run_id=run_id,
            )
            # Still proceed in dry-run or if user explicitly started
            if not dry_run and not cli_mode:
                run_state.is_running = False
                return summary

        # Launch browser
        await browser.launch(headless=config.behavior.headless)

        # Determine enabled platforms
        platform_names = []
        platforms_cfg = config.platforms
        if platforms_cfg.mock.enabled:
            platform_names.append("mock")
        if platforms_cfg.linkedin.enabled:
            platform_names.append("linkedin")
        if platforms_cfg.internshala.enabled:
            platform_names.append("internshala")
        if platforms_cfg.google_jobs.enabled:
            platform_names.append("google_jobs")

        if not platform_names:
            await event_bus.publish("No platforms enabled", level="warning", run_id=run_id)

        total_applied_this_run = 0
        max_per_run = config.limits.max_per_run

        for pname in platform_names:
            if run_state.should_stop:
                await event_bus.publish("Run stopped by user", level="warning", run_id=run_id)
                break

            await event_bus.publish(f"Processing platform: {pname}", level="info",
                                   platform=pname, run_id=run_id)

            try:
                platform = _get_platform_instance(pname, config, profile)

                # Get daily cap
                daily_cap = config.limits.max_daily.get(pname, 50)
                with db.get_conn() as conn:
                    already_applied_today = db.get_today_applied_count(conn, pname)

                if already_applied_today >= daily_cap:
                    await event_bus.publish(
                        f"Daily cap reached for {pname} ({already_applied_today}/{daily_cap})",
                        level="warning", platform=pname, run_id=run_id,
                    )
                    continue

                remaining_cap = daily_cap - already_applied_today

                # Create context and check session (skip for mock)
                if pname != "mock":
                    page = await browser.new_context(platform=pname)
                    session_status = await platform.check_login(page)
                    with db.get_conn() as conn:
                        db.update_session(conn, pname, session_status)

                    if session_status != "ok":
                        await event_bus.publish(
                            f"Session {session_status} for {pname} — skipping",
                            level="error", platform=pname, run_id=run_id,
                        )
                        await browser.take_screenshot(f"{pname}_session_{session_status}")
                        continue
                else:
                    page = None

                # Search for jobs
                await event_bus.publish(f"Searching for jobs on {pname}...",
                                        level="info", platform=pname, run_id=run_id)
                raw_listings = await platform.search(page)
                summary["found"] += len(raw_listings)
                await event_bus.publish(f"Found {len(raw_listings)} listings on {pname}",
                                        level="info", platform=pname, run_id=run_id)

                # Process each listing
                for listing in raw_listings:
                    if run_state.should_stop:
                        break
                    if total_applied_this_run >= max_per_run:
                        await event_bus.publish(
                            f"Max per run reached ({max_per_run})",
                            level="warning", run_id=run_id,
                        )
                        break

                    title = listing.get("title", "")
                    company = listing.get("company", "")
                    location = listing.get("location", "")
                    description = listing.get("description", "")
                    stipend = listing.get("stipend", "")
                    platform_job_id = listing.get("platform_job_id", "")
                    url = listing.get("url", "")

                    # Dedupe against DB
                    with db.get_conn() as conn:
                        if db.job_exists(conn, pname, platform_job_id):
                            await event_bus.publish(
                                f"Skipping duplicate: {title} at {company}",
                                level="debug", platform=pname, run_id=run_id,
                            )
                            continue

                    # Insert as found
                    with db.get_conn() as conn:
                        job_id = db.insert_job(
                            conn, platform=pname, platform_job_id=platform_job_id,
                            title=title, company=company, location=location,
                            url=url, description=description,
                            posted_at=listing.get("posted_at"),
                            stipend=stipend, status="found",
                        )
                    if job_id is None:
                        continue

                    # Deterministic filters (no fuzzy dedupe here — exact dedupe
                    # is already handled by job_exists above via platform+job_id)
                    filter_result = filters.apply_all_filters(
                        title=title, company=company, location=location,
                        description=description, stipend=stipend,
                        config_filters=config.filters.model_dump(),
                        config_search=config.search.model_dump(),
                        existing_jobs=None,
                    )
                    if not filter_result.passed:
                        with db.get_conn() as conn:
                            db.update_job_status(conn, job_id, "filtered_out",
                                                 reason=filter_result.reason)
                        summary["filtered"] += 1
                        await event_bus.publish(
                            f"Filtered: {title} — {filter_result.reason}",
                            level="debug", platform=pname, run_id=run_id,
                        )
                        continue

                    # LLM scoring
                    try:
                        score_result = await score_job(
                            title=title, company=company, description=description,
                            candidate_summary=profile.experience_summary,
                            search_titles=config.search.titles,
                        )
                        score = score_result["score"]
                        reason = score_result["reason"]
                    except Exception as e:
                        logger.error(f"Scoring failed for {title}: {e}")
                        score = 0
                        reason = f"Scoring error: {e}"

                    if score < config.filters.min_llm_score:
                        with db.get_conn() as conn:
                            db.update_job_status(conn, job_id, "low_score",
                                                 score=score, reason=reason)
                        await event_bus.publish(
                            f"Low score ({score}): {title} — {reason}",
                            level="info", platform=pname, run_id=run_id,
                        )
                        continue

                    # Update score
                    with db.get_conn() as conn:
                        db.update_job_status(conn, job_id, "queued",
                                             score=score, reason=reason)

                    # Check cap again
                    with db.get_conn() as conn:
                        already_applied_today = db.get_today_applied_count(conn, pname)
                    if already_applied_today >= daily_cap:
                        await event_bus.publish(
                            f"Daily cap hit for {pname}",
                            level="warning", platform=pname, run_id=run_id,
                        )
                        break

                    # Apply
                    await event_bus.publish(
                        f"{'[DRY RUN] Would apply' if dry_run else 'Applying'}: {title} at {company} (score: {score})",
                        level="info", platform=pname, run_id=run_id,
                    )

                    if dry_run:
                        with db.get_conn() as conn:
                            db.update_job_status(
                                conn, job_id, "dry_run", score=score, reason=reason,
                            )
                        summary["applied"] += 1
                        total_applied_this_run += 1
                    else:
                        try:
                            apply_result = await platform.apply(page, listing)
                            if apply_result.get("success"):
                                now = datetime.now(timezone.utc).isoformat()
                                with db.get_conn() as conn:
                                    db.update_job_status(
                                        conn, job_id, "applied",
                                        score=score, reason=reason, applied_at=now,
                                    )
                                summary["applied"] += 1
                                total_applied_this_run += 1
                            elif apply_result.get("manual_needed"):
                                with db.get_conn() as conn:
                                    db.update_job_status(
                                        conn, job_id, "manual_needed",
                                        score=score, reason=apply_result.get("reason", ""),
                                    )
                                summary["manual"] += 1
                            else:
                                with db.get_conn() as conn:
                                    db.update_job_status(
                                        conn, job_id, "failed",
                                        error=apply_result.get("error", "Unknown"),
                                    )
                                summary["failed"] += 1
                        except Exception as e:
                            await browser.take_screenshot(f"{pname}_error")
                            with db.get_conn() as conn:
                                db.update_job_status(conn, job_id, "failed", error=str(e))
                            summary["failed"] += 1
                            await event_bus.publish(
                                f"Apply failed: {title} — {e}",
                                level="error", platform=pname, run_id=run_id,
                            )

                    # Humanize delay
                    await random_delay(config.limits.delay_min, config.limits.delay_max)

                    # Restart browser if needed
                    await browser.restart_if_needed(
                        threshold=config.behavior.restart_browser_every,
                        headless=config.behavior.headless,
                    )

            except Exception as e:
                await event_bus.publish(
                    f"Platform {pname} error: {e}",
                    level="error", platform=pname, run_id=run_id,
                )
                try:
                    await browser.take_screenshot(f"{pname}_crash")
                except Exception:
                    pass

    except Exception as e:
        await event_bus.publish(f"Run error: {e}", level="error", run_id=run_id)
        logger.exception("Run failed")

    finally:
        await browser.close()
        run_state.is_running = False

        # Update run record
        tokens = get_run_tokens()
        with db.get_conn() as conn:
            if run_state.current_run_id:
                db.update_run(
                    conn, run_state.current_run_id,
                    ended_at=datetime.now(timezone.utc).isoformat(),
                    found=summary["found"],
                    filtered=summary["filtered"],
                    applied=summary["applied"],
                    failed=summary["failed"],
                    manual=summary["manual"],
                    tokens_in=tokens.prompt_tokens,
                    tokens_out=tokens.completion_tokens,
                    status="completed",
                )
            # Store events in DB
            for evt in event_bus.get_history():
                db.insert_event(
                    conn,
                    message=evt.message,
                    level=evt.level,
                    platform=evt.platform,
                    run_id=evt.run_id,
                )

        await event_bus.publish(
            f"Run finished — Found: {summary['found']}, Filtered: {summary['filtered']}, "
            f"Applied: {summary['applied']}, Failed: {summary['failed']}, Manual: {summary['manual']}",
            level="info", run_id=run_id,
        )

    return summary


def start_run_background(dry_run: bool = True) -> None:
    """Start a run as a background asyncio task (called from web server)."""
    if run_state.is_running:
        return

    loop = asyncio.get_event_loop()
    run_state._task = loop.create_task(execute_run(dry_run=dry_run))


def stop_run() -> None:
    """Signal the current run to stop."""
    run_state.request_stop()
