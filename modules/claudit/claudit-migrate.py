#!/usr/bin/env python3
"""
claudit-migrate: Idempotent data migration for the claudit metrics database.

Usage:
  claudit-migrate [--days N] [--db PATH]

Applies two idempotent operations to the claudit DB:

  1. PURGE: DELETE FROM kanban_card_events WHERE event_type IN ('review', 'redo')
     These event types were removed from the kanban model; their rows are stale
     and skew the dashboard's event-type breakdown. Safe to re-run — a no-op
     when the rows have already been removed.

  2. BACKFILL: For each commit from `git log --since=N days ago` in the
     nixpkgs repo (~/.config/nixpkgs), insert a claudit_annotations row with:
       - tags = 'git-commit'
       - recorded_at = commit author date, converted to UTC ISO 8601 with Z suffix
       - message = '<short-sha>: <subject>'
     Deduplicates by message — skips any row whose message already exists in
     the table. Re-running is always safe: 0 rows inserted on a clean DB.

The migration backs up the database first (timestamped .bak copy). If the DB
does not yet exist (fresh machine), it creates it with the full schema so that
migrate works without requiring the hook to fire first.

Options:
  --days N    Number of days of git history to backfill (default: 30)
  --db PATH   Override the database path (default: ~/.claude/metrics/claudit.db)
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"
NIXPKGS_REPO = Path.home() / ".config" / "nixpkgs"


# ---------------------------------------------------------------------------
# DDL — mirrors claudit-hook.py exactly (kept in sync; changes here require
# matching changes there and in the 'nuke' block in default.nix).
# ---------------------------------------------------------------------------

CREATE_AGENT_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS agent_metrics (
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT 'unknown',
    model TEXT NOT NULL DEFAULT 'unknown',
    kanban_session TEXT NOT NULL DEFAULT 'unknown',
    card_number INTEGER,
    git_repo TEXT NOT NULL DEFAULT 'unknown',
    working_directory TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    total_turns INTEGER NOT NULL DEFAULT 0,
    avg_turn_latency_seconds REAL NOT NULL DEFAULT 0.0,
    cache_hit_ratio REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (session_id, agent_id)
)
"""

CREATE_AGENT_TOOL_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS agent_tool_usage (
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL,
    bash_command TEXT NOT NULL DEFAULT '',
    bash_subcommand TEXT NOT NULL DEFAULT '',
    call_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (session_id, agent_id, tool_name, bash_command, bash_subcommand)
)
"""

CREATE_PERMISSION_DENIALS_SQL = """
CREATE TABLE IF NOT EXISTS permission_denials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    tool_use_id TEXT NOT NULL UNIQUE,
    tool_name TEXT NOT NULL,
    denied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

CREATE_KANBAN_CARD_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS kanban_card_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kanban_session TEXT NOT NULL,
    card_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    rejection_reasons TEXT,
    card_created_at TEXT,
    card_completed_at TEXT,
    card_type TEXT,
    ac_count INTEGER DEFAULT 0,
    git_project TEXT,
    from_column TEXT,
    to_column TEXT,
    persona TEXT
)
"""

CREATE_CLAUDIT_ANNOTATIONS_SQL = """
CREATE TABLE IF NOT EXISTS claudit_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    message TEXT NOT NULL,
    tags TEXT
)
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_am_session_id ON agent_metrics (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_am_kanban_session ON agent_metrics (kanban_session)",
    "CREATE INDEX IF NOT EXISTS idx_am_recorded_at ON agent_metrics (recorded_at)",
    "CREATE INDEX IF NOT EXISTS idx_am_last_seen_at ON agent_metrics (last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_am_git_repo ON agent_metrics (git_repo)",
    "CREATE INDEX IF NOT EXISTS idx_am_agent ON agent_metrics (agent)",
    "CREATE INDEX IF NOT EXISTS idx_am_model ON agent_metrics (model)",
    "CREATE INDEX IF NOT EXISTS idx_atu_session_id ON agent_tool_usage (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_atu_tool_name ON agent_tool_usage (tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_pd_session_id ON permission_denials (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_kce_kanban_session ON kanban_card_events (kanban_session)",
    "CREATE INDEX IF NOT EXISTS idx_kce_card_number ON kanban_card_events (card_number)",
    "CREATE INDEX IF NOT EXISTS idx_kce_recorded_at ON kanban_card_events (recorded_at)",
    "CREATE INDEX IF NOT EXISTS idx_claudit_annotations_recorded_at ON claudit_annotations (recorded_at)",
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they do not yet exist."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(CREATE_AGENT_METRICS_SQL)
    conn.execute(CREATE_AGENT_TOOL_USAGE_SQL)
    conn.execute(CREATE_PERMISSION_DENIALS_SQL)
    conn.execute(CREATE_KANBAN_CARD_EVENTS_SQL)
    conn.execute(CREATE_CLAUDIT_ANNOTATIONS_SQL)
    for idx_sql in CREATE_INDEXES_SQL:
        conn.execute(idx_sql)
    conn.commit()


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open (and initialize) the claudit metrics database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_db(db_path: Path) -> Path:
    """
    Copy the database to a timestamped .bak file in the same directory.

    If the DB does not yet exist, skips the copy (nothing to back up) and
    returns a sentinel path describing where the backup would have gone.
    Returns the backup path for reporting.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bak_path = db_path.with_name(f"{db_path.stem}.{timestamp}.bak")
    if db_path.exists():
        shutil.copy2(str(db_path), str(bak_path))
    return bak_path


# ---------------------------------------------------------------------------
# Step 1 — PURGE stale kanban_card_events rows
# ---------------------------------------------------------------------------

def purge_stale_events(conn: sqlite3.Connection) -> int:
    """
    DELETE rows from kanban_card_events where event_type IN ('review', 'redo').

    Idempotent: returns 0 when no matching rows exist.
    Returns the number of rows deleted.
    """
    cursor = conn.execute(
        "DELETE FROM kanban_card_events WHERE event_type IN ('review', 'redo')"
    )
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Step 2 — BACKFILL git-commit annotations
# ---------------------------------------------------------------------------

def author_date_to_utc(iso_with_offset: str) -> str:
    """
    Convert a git author date (ISO 8601 with timezone offset, e.g.
    '2026-06-16T17:01:48-04:00') to UTC with Z suffix
    ('2026-06-16T21:01:48Z').

    Falls back to returning the original string unchanged on parse failure
    so a single malformed commit does not abort the whole migration.
    """
    try:
        dt = datetime.fromisoformat(iso_with_offset)
        utc_dt = dt.astimezone(timezone.utc)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return iso_with_offset


def fetch_commits(days: int) -> list[dict]:
    """
    Run `git log --since=N days ago` in the nixpkgs repo and return a list of
    dicts with keys: sha, short_sha, author_date_utc, subject, message.

    Uses NUL-delimited output to handle subjects that contain newlines or
    special characters safely.

    Returns an empty list if the git command fails (e.g. repo not found).
    """
    # %x00 = NUL separator between commits; fields separated by %x01
    # Format per commit: <sha>%x01<short-sha>%x01<author-ISO-date>%x01<subject>
    fmt = "%H%x01%h%x01%aI%x01%s"
    try:
        result = subprocess.run(
            [
                "git",
                "-C", str(NIXPKGS_REPO),
                "log",
                f"--since={days} days ago",
                f"--format={fmt}%x00",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        print(f"warning: git log failed: {exc}", file=sys.stderr)
        return []

    if result.returncode != 0:
        print(f"warning: git log exited {result.returncode}: {result.stderr.strip()}", file=sys.stderr)
        return []

    commits = []
    for chunk in result.stdout.split("\x00"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split("\x01", 3)
        if len(parts) != 4:
            continue
        sha, short_sha, author_date_raw, subject = parts
        author_date_utc = author_date_to_utc(author_date_raw)
        message = f"{short_sha}: {subject}"
        commits.append({
            "sha": sha,
            "short_sha": short_sha,
            "author_date_utc": author_date_utc,
            "subject": subject,
            "message": message,
        })
    return commits


def backfill_annotations(conn: sqlite3.Connection, days: int) -> tuple[int, int]:
    """
    For each commit in the last N days, insert a claudit_annotations row unless
    a row with the same message already exists.

    Deduplicates by message (the '<short-sha>: <subject>' string). This matches
    the original direct-SQL backfill strategy and survives re-runs safely.

    Returns (inserted, skipped) counts.
    """
    commits = fetch_commits(days)
    if not commits:
        return 0, 0

    # Load all existing messages for git-commit annotations into a set for O(1) lookup.
    existing_rows = conn.execute(
        "SELECT message FROM claudit_annotations WHERE tags = 'git-commit'"
    ).fetchall()
    existing_messages = {row[0] for row in existing_rows}

    inserted = 0
    skipped = 0
    for commit in commits:
        if commit["message"] in existing_messages:
            skipped += 1
            continue
        conn.execute(
            """
            INSERT INTO claudit_annotations (recorded_at, message, tags)
            VALUES (?, ?, 'git-commit')
            """,
            (commit["author_date_utc"], commit["message"]),
        )
        existing_messages.add(commit["message"])
        inserted += 1

    conn.commit()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotent claudit DB migration: purge stale kanban events + backfill git-commit annotations.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        metavar="N",
        help="Days of git history to backfill (default: 30)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        metavar="PATH",
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    db_path: Path = args.db
    days: int = args.days

    # --- Back up the DB (or note that it does not exist yet) ---
    bak_path = backup_db(db_path)
    if db_path.exists():
        print(f"backup:   {bak_path}")
    else:
        print(f"info:     database not found at {db_path} — creating fresh schema")
        print("backup:   (skipped — nothing to back up)")

    # --- Open / initialize DB ---
    try:
        conn = open_db(db_path)
    except Exception as exc:
        print(f"error: could not open database: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        # --- Step 1: Purge stale event rows ---
        purged = purge_stale_events(conn)
        print(f"purged:   {purged} kanban_card_events rows (event_type IN ('review','redo'))")

        # --- Step 2: Backfill git-commit annotations ---
        inserted, skipped = backfill_annotations(conn, days)
        print(f"inserted: {inserted} claudit_annotations rows (git-commit, last {days} days)")
        print(f"skipped:  {skipped} claudit_annotations rows (already present)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
