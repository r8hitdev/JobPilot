"""
JobPilot CLI — serve | run [--dry-run] | stats
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger


def _configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    )
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    logger.add(
        str(logs_dir / "jobpilot.log"),
        rotation="5 MB",
        retention="7 days",
        level="DEBUG",
    )


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the web dashboard server."""
    from jobpilot.settings import load_env
    from jobpilot.db import init_db

    env = load_env()
    _configure_logging(env.log_level)
    init_db()

    # Lazy import of the web app — it may not exist yet
    try:
        from jobpilot.web.app import create_app
        import uvicorn

        app = create_app()
        logger.info(f"Starting JobPilot dashboard at http://{env.host}:{env.port}")
        uvicorn.run(app, host=env.host, port=env.port, log_level="info")
    except ImportError as e:
        logger.error(
            f"Web layer not available: {e}. "
            "The web/ package has not been built yet. "
            "Use 'python main.py run' or 'python main.py stats' instead."
        )
        sys.exit(1)


def cmd_run(args: argparse.Namespace) -> None:
    """Execute a job application run."""
    from jobpilot.settings import load_env, load_config, save_config
    from jobpilot.db import init_db

    env = load_env()
    _configure_logging(env.log_level)
    init_db()

    config = load_config()

    # If --mock, enable mock platform and disable others
    if args.mock:
        config.platforms.mock.enabled = True
        config.platforms.linkedin.enabled = False
        config.platforms.internshala.enabled = False
        config.platforms.google_jobs.enabled = False

    dry_run = args.dry_run if args.dry_run is not None else config.behavior.dry_run

    logger.info(f"Starting run (dry_run={dry_run}, mock={args.mock})")

    from jobpilot.runner import execute_run
    summary = asyncio.run(execute_run(dry_run=dry_run, cli_mode=True, config_override=config))

    print("\n" + "=" * 50)
    print("RUN SUMMARY")
    print("=" * 50)
    if isinstance(summary, dict) and "error" not in summary:
        print(f"  Found:    {summary.get('found', 0)}")
        print(f"  Filtered: {summary.get('filtered', 0)}")
        print(f"  Applied:  {summary.get('applied', 0)}")
        print(f"  Failed:   {summary.get('failed', 0)}")
        print(f"  Manual:   {summary.get('manual', 0)}")
    elif isinstance(summary, dict):
        print(f"  Error: {summary.get('error', 'Unknown')}")
    print("=" * 50)


def cmd_stats(args: argparse.Namespace) -> None:
    """Show statistics from the database."""
    from jobpilot.settings import load_env
    from jobpilot.db import (
        init_db, get_conn, get_today_stats, get_total_tokens,
        get_today_tokens, get_latest_runs, count_jobs, get_sessions,
        get_daily_application_counts,
    )

    env = load_env()
    _configure_logging(env.log_level)
    init_db()

    with get_conn() as conn:
        today = get_today_stats(conn)
        tokens_total = get_total_tokens(conn)
        tokens_today = get_today_tokens(conn)
        runs = get_latest_runs(conn, limit=5)
        sessions = get_sessions(conn)
        total_jobs = count_jobs(conn)
        total_applied = count_jobs(conn, status="applied")
        total_failed = count_jobs(conn, status="failed")
        total_manual = count_jobs(conn, status="manual_needed")
        daily_counts = get_daily_application_counts(conn)

    print("\n" + "=" * 50)
    print("JOBPILOT STATISTICS")
    print("=" * 50)

    print("\n📊 TODAY")
    print(f"  Applied:      {today['applied_today']}")
    print(f"  Found:        {today['found_today']}")
    print(f"  Manual needed:{today['manual_needed']}")
    print(f"  Tokens (in):  {tokens_today['tokens_in']}")
    print(f"  Tokens (out): {tokens_today['tokens_out']}")

    print(f"\n📈 ALL TIME")
    print(f"  Total jobs:   {total_jobs}")
    print(f"  Applied:      {total_applied}")
    print(f"  Failed:       {total_failed}")
    print(f"  Manual needed:{total_manual}")
    print(f"  Tokens (in):  {tokens_total['tokens_in']}")
    print(f"  Tokens (out): {tokens_total['tokens_out']}")

    if sessions:
        print(f"\n🔑 SESSIONS")
        for platform, info in sessions.items():
            status = info.get("status", "unknown")
            checked = info.get("checked_at", "never")
            emoji = {"ok": "🟢", "expired": "🔴", "checkpoint": "🟡", "missing": "⚫"}.get(status, "⚪")
            print(f"  {emoji} {platform}: {status} (checked: {checked})")

    if runs:
        print(f"\n🏃 RECENT RUNS (last {len(runs)})")
        for run in runs:
            mode = run.get("mode", "?")
            status = run.get("status", "?")
            applied = run.get("applied", 0)
            found = run.get("found", 0)
            started = run.get("started_at", "?")
            print(f"  [{mode}] {started} — {status} (found: {found}, applied: {applied})")

    if daily_counts:
        print(f"\n📅 DAILY APPLICATIONS (last 14 days)")
        for entry in daily_counts:
            day = entry.get("day", "?")
            cnt = entry.get("count", 0)
            bar = "█" * min(cnt, 40)
            print(f"  {day}: {bar} {cnt}")

    print("\n" + "=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jobpilot",
        description="JobPilot — autonomous job application agent",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the web dashboard")
    serve_parser.set_defaults(func=cmd_serve)

    # run
    run_parser = subparsers.add_parser("run", help="Execute a job application run")
    run_parser.add_argument("--dry-run", action="store_true", default=None,
                            help="Do everything except the final submit click")
    run_parser.add_argument("--live", action="store_true",
                            help="Run in live mode (actually submit applications)")
    run_parser.add_argument("--mock", action="store_true",
                            help="Use mock platform with fake jobs (no real site)")
    run_parser.set_defaults(func=cmd_run)

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show application statistics")
    stats_parser.set_defaults(func=cmd_stats)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Handle --live flag for run command
    if args.command == "run" and args.live:
        args.dry_run = False

    args.func(args)


if __name__ == "__main__":
    main()
