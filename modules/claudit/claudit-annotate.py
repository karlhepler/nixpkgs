#!/usr/bin/env python3
"""
claudit-annotate: Record a named annotation into the claudit metrics database.

Usage:
  claudit-annotate "message text"
  claudit-annotate --tags 'prompt,staff' "message text"

Inserts a row into claudit_annotations with the current UTC timestamp.
On success, prints the annotation ID and timestamp to stdout.
On failure, prints to stderr and exits with code 1.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"

CREATE_CLAUDIT_ANNOTATIONS_SQL = """
CREATE TABLE IF NOT EXISTS claudit_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    message TEXT NOT NULL,
    tags TEXT
);
"""

CREATE_CLAUDIT_ANNOTATIONS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_claudit_annotations_recorded_at
ON claudit_annotations(recorded_at);
"""


def open_db() -> sqlite3.Connection:
    """Open the claudit metrics database, creating tables if needed."""
    if not DB_PATH.exists():
        print(f"error: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(CREATE_CLAUDIT_ANNOTATIONS_SQL)
    conn.execute(CREATE_CLAUDIT_ANNOTATIONS_INDEX_SQL)
    conn.commit()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record an annotation into the claudit metrics database.",
    )
    parser.add_argument(
        "--tags",
        default=None,
        help="Comma-separated tags (e.g. 'prompt,staff')",
    )
    parser.add_argument("message", help="Annotation message text")
    args = parser.parse_args()

    try:
        conn = open_db()
    except Exception as exc:
        print(f"error: could not open database: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        cursor = conn.execute(
            """
            INSERT INTO claudit_annotations (message, tags)
            VALUES (?, ?)
            """,
            (args.message, args.tags),
        )
        conn.commit()
        annotation_id = cursor.lastrowid
        row = conn.execute(
            "SELECT recorded_at FROM claudit_annotations WHERE id = ?",
            (annotation_id,),
        ).fetchone()
        recorded_at = row[0] if row else "unknown"
        print(f"annotation {annotation_id} recorded at {recorded_at}")
    except Exception as exc:
        print(f"error: could not write annotation: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
