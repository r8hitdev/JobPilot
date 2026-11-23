"""
JobPilot database — SQLite (WAL mode), schema, migrations, and repository layer.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from jobpilot.settings import DATA_DIR

DB_PATH = DATA_DIR / "jobpilot.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,
    platform_job_id TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    posted_at       TEXT,
    stipend         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'found',
    score           INTEGER,
    reason          TEXT NOT NULL DEFAULT '',
    applied_at      TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, platform_job_id)
);

CREATE TABLE IF NOT EXISTS qa_cache (
    question_hash   TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'llm',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    mode            TEXT NOT NULL DEFAULT 'dry',
    found           INTEGER NOT NULL DEFAULT 0,
    filtered        INTEGER NOT NULL DEFAULT 0,
    applied         INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    manual          INTEGER NOT NULL DEFAULT 0,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS sessions (
    platform        TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'missing',
    checked_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER,
    ts              TEXT NOT NULL DEFAULT (datetime('now')),
    level           TEXT NOT NULL DEFAULT 'info',
    platform        TEXT,
    message         TEXT NOT NULL DEFAULT ''
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path | None = None) -> None:
    """Create the database and all tables if they don't exist."""
    p = db_path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(p)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA_SQL)


@contextmanager
def get_conn(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a database connection with WAL mode and row_factory."""
    p = db_path or DB_PATH
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Job Repository ────────────────────────────────────────────

def insert_job(
    conn: sqlite3.Connection,
    platform: str,
    platform_job_id: str,
    title: str = "",
    company: str = "",
    location: str = "",
    url: str = "",
    description: str = "",
    posted_at: str | None = None,
    stipend: str = "",
    status: str = "found",
    score: int | None = None,
    reason: str = "",
) -> int | None:
    """Insert a job. Returns the row id, or None if it's a duplicate."""
    try:
        cur = conn.execute(
            """INSERT INTO jobs (platform, platform_job_id, title, company, location,
               url, description, posted_at, stipend, status, score, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (platform, platform_job_id, title, company, location,
             url, description, posted_at, stipend, status, score, reason),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def job_exists(conn: sqlite3.Connection, platform: str, platform_job_id: str) -> bool:
    """Check whether a job with this platform+id already exists."""
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE platform = ? AND platform_job_id = ?",
        (platform, platform_job_id),
    ).fetchone()
    return row is not None


def update_job_status(
    conn: sqlite3.Connection,
    job_id: int,
    status: str,
    score: int | None = None,
    reason: str | None = None,
    error: str | None = None,
    applied_at: str | None = None,
) -> None:
    """Update the status (and optionally score/reason/error) of a job."""
    parts = ["status = ?"]
    vals: list[Any] = [status]
    if score is not None:
        parts.append("score = ?")
        vals.append(score)
    if reason is not None:
        parts.append("reason = ?")
        vals.append(reason)
    if error is not None:
        parts.append("error = ?")
        vals.append(error)
    if applied_at is not None:
        parts.append("applied_at = ?")
        vals.append(applied_at)
    vals.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(parts)} WHERE id = ?", vals)
    conn.commit()


def get_jobs(
    conn: sqlite3.Connection,
    platform: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    min_score: int | None = None,
) -> list[dict[str, Any]]:
    """Query jobs with optional filters, paginated."""
    clauses: list[str] = []
    vals: list[Any] = []
    if platform:
        clauses.append("platform = ?")
        vals.append(platform)
    if status:
        clauses.append("status = ?")
        vals.append(status)
    if search:
        clauses.append("(title LIKE ? OR company LIKE ?)")
        vals.extend([f"%{search}%", f"%{search}%"])
    if min_score is not None:
        clauses.append("score >= ?")
        vals.append(min_score)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    vals.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM jobs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", vals
    ).fetchall()
    return [dict(r) for r in rows]


def count_jobs(conn: sqlite3.Connection, platform: str | None = None, status: str | None = None) -> int:
    """Count jobs with optional filters."""
    clauses: list[str] = []
    vals: list[Any] = []
    if platform:
        clauses.append("platform = ?")
        vals.append(platform)
    if status:
        clauses.append("status = ?")
        vals.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    row = conn.execute(f"SELECT COUNT(*) FROM jobs{where}", vals).fetchone()
    return row[0] if row else 0


def get_today_applied_count(conn: sqlite3.Connection, platform: str) -> int:
    """Count how many jobs were applied to today for a given platform."""
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE platform = ? AND status = 'applied' AND date(applied_at) = date('now')",
        (platform,),
    ).fetchone()
    return row[0] if row else 0


def get_today_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Get aggregate stats for today."""
    def _count(query: str, params: tuple = ()) -> int:
        r = conn.execute(query, params).fetchone()
        return r[0] if r else 0

    return {
        "applied_today": _count(
            "SELECT COUNT(*) FROM jobs WHERE status='applied' AND date(applied_at)=date('now')"
        ),
        "found_today": _count(
            "SELECT COUNT(*) FROM jobs WHERE date(created_at)=date('now')"
        ),
        "manual_needed": _count(
            "SELECT COUNT(*) FROM jobs WHERE status='manual_needed'"
        ),
    }


def get_daily_application_counts(conn: sqlite3.Connection, days: int = 14) -> list[dict[str, Any]]:
    """Return per-day applied counts for the last N days."""
    rows = conn.execute(
        """SELECT date(applied_at) as day, COUNT(*) as count
           FROM jobs WHERE status='applied'
           AND applied_at >= date('now', ?)
           GROUP BY date(applied_at) ORDER BY day""",
        (f"-{days} days",),
    ).fetchall()
    return [dict(r) for r in rows]


# ── QA Cache Repository ──────────────────────────────────────

def _hash_question(q: str) -> str:
    return hashlib.sha256(q.strip().lower().encode()).hexdigest()[:32]


def get_cached_answer(conn: sqlite3.Connection, question: str) -> str | None:
    """Look up a cached answer for a normalized question."""
    h = _hash_question(question)
    row = conn.execute("SELECT answer FROM qa_cache WHERE question_hash = ?", (h,)).fetchone()
    return row[0] if row else None


def cache_answer(conn: sqlite3.Connection, question: str, answer: str, source: str = "llm") -> None:
    """Store or update a cached answer."""
    h = _hash_question(question)
    conn.execute(
        """INSERT INTO qa_cache (question_hash, question, answer, source)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(question_hash) DO UPDATE SET answer=excluded.answer, source=excluded.source""",
        (h, question.strip(), answer, source),
    )
    conn.commit()


def get_all_qa(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all cached QA pairs."""
    rows = conn.execute("SELECT * FROM qa_cache ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_qa(conn: sqlite3.Connection, question_hash: str) -> None:
    """Delete a cached QA pair."""
    conn.execute("DELETE FROM qa_cache WHERE question_hash = ?", (question_hash,))
    conn.commit()


# ── Run Repository ────────────────────────────────────────────

def create_run(conn: sqlite3.Connection, mode: str = "dry") -> int:
    """Create a new run record and return its id."""
    cur = conn.execute("INSERT INTO runs (mode) VALUES (?)", (mode,))
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def update_run(conn: sqlite3.Connection, run_id: int, **kwargs: Any) -> None:
    """Update run fields."""
    if not kwargs:
        return
    parts = [f"{k} = ?" for k in kwargs]
    vals = list(kwargs.values()) + [run_id]
    conn.execute(f"UPDATE runs SET {', '.join(parts)} WHERE id = ?", vals)
    conn.commit()


def get_latest_runs(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent runs."""
    rows = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_total_tokens(conn: sqlite3.Connection) -> dict[str, int]:
    """Sum tokens across all runs."""
    row = conn.execute("SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) FROM runs").fetchone()
    return {"tokens_in": row[0], "tokens_out": row[1]}


def get_today_tokens(conn: sqlite3.Connection) -> dict[str, int]:
    """Sum tokens for today's runs."""
    row = conn.execute(
        "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0) FROM runs WHERE date(started_at)=date('now')"
    ).fetchone()
    return {"tokens_in": row[0], "tokens_out": row[1]}


# ── Session Repository ────────────────────────────────────────

def update_session(conn: sqlite3.Connection, platform: str, status: str) -> None:
    """Upsert session status for a platform."""
    conn.execute(
        """INSERT INTO sessions (platform, status, checked_at) VALUES (?, ?, datetime('now'))
           ON CONFLICT(platform) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at""",
        (platform, status),
    )
    conn.commit()


def get_sessions(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Return session status for all platforms."""
    rows = conn.execute("SELECT * FROM sessions").fetchall()
    return {r["platform"]: dict(r) for r in rows}


# ── Event Repository ─────────────────────────────────────────

def insert_event(
    conn: sqlite3.Connection,
    message: str,
    level: str = "info",
    platform: str | None = None,
    run_id: int | None = None,
) -> int:
    """Insert a log event and return its id."""
    cur = conn.execute(
        "INSERT INTO events (run_id, level, platform, message) VALUES (?, ?, ?, ?)",
        (run_id, level, platform, message),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def get_events(
    conn: sqlite3.Connection,
    run_id: int | None = None,
    level: str | None = None,
    platform: str | None = None,
    limit: int = 100,
    after_id: int | None = None,
) -> list[dict[str, Any]]:
    """Query events, optionally filtered and paginated by id."""
    clauses: list[str] = []
    vals: list[Any] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        vals.append(run_id)
    if level:
        clauses.append("level = ?")
        vals.append(level)
    if platform:
        clauses.append("platform = ?")
        vals.append(platform)
    if after_id is not None:
        clauses.append("id > ?")
        vals.append(after_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    vals.append(limit)
    rows = conn.execute(f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?", vals).fetchall()
    return [dict(r) for r in rows]
