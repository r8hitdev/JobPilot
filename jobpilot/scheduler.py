"""
JobPilot scheduler — APScheduler (AsyncIOScheduler) for optional daily runs.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from jobpilot.settings import load_config

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def _scheduled_run() -> None:
    """Callback for the scheduled daily run."""
    from jobpilot.runner import execute_run, run_state
    config = load_config()
    if run_state.is_running:
        logger.info("Scheduled run skipped — another run is in progress")
        return
    dry_run = config.behavior.dry_run
    logger.info(f"Scheduled run starting (dry_run={dry_run})")
    await execute_run(dry_run=dry_run)


def configure_schedule() -> None:
    """Read config and set up or remove the daily schedule."""
    config = load_config()
    sched = get_scheduler()

    # Remove existing job if any
    existing = sched.get_job("daily_run")
    if existing:
        sched.remove_job("daily_run")

    if config.limits.schedule.enabled:
        time_str = config.limits.schedule.time
        try:
            hour, minute = time_str.split(":")
            trigger = CronTrigger(hour=int(hour), minute=int(minute))
            sched.add_job(_scheduled_run, trigger, id="daily_run", replace_existing=True)
            logger.info(f"Scheduled daily run at {time_str}")
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid schedule time '{time_str}': {e}")
    else:
        logger.info("Schedule disabled")


def start_scheduler() -> None:
    """Start the scheduler if not already running."""
    sched = get_scheduler()
    if not sched.running:
        configure_schedule()
        sched.start()
        logger.info("Scheduler started")


def stop_scheduler() -> None:
    """Stop the scheduler."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("Scheduler stopped")
