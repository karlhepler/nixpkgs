#!/usr/bin/env python3
"""
claude-metrics-hook: Claude Code hook for capturing agent metrics into SQLite.

Triggered by Claude Code's Stop and SubagentStop events. Reads JSON payload
from stdin, parses the JSONL transcript, aggregates tokens per model, computes
cost, and writes one row per model to ~/.claude/metrics/claude-metrics.db.

Never exits non-zero — all errors are swallowed silently to avoid disrupting
Claude Code's hook pipeline.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Pricing table — per 1M tokens, keyed by model family
# ---------------------------------------------------------------------------
PRICING = {
    "opus": {
        "input": 15.00,
        "output": 75.00,
        "cache_creation_5m": 18.75,
        "cache_creation_1h": 0.00,  # not yet billed separately
        "cache_read": 1.50,
    },
    "sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation_5m": 3.75,
        "cache_creation_1h": 0.00,
        "cache_read": 0.30,
    },
    "haiku-3.5": {
        "input": 0.80,
        "output": 4.00,
        "cache_creation_5m": 1.00,
        "cache_creation_1h": 0.00,
        "cache_read": 0.08,
    },
    "haiku": {
        "input": 0.80,
        "output": 4.00,
        "cache_creation_5m": 1.00,
        "cache_creation_1h": 0.00,
        "cache_read": 0.08,
    },
    "unknown": {
        "input": 0.00,
        "output": 0.00,
        "cache_creation_5m": 0.00,
        "cache_creation_1h": 0.00,
        "cache_read": 0.00,
    },
}

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT,
    role TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    working_directory TEXT,
    kanban_session TEXT,
    model TEXT NOT NULL,
    model_family TEXT NOT NULL,
    turns INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_5m_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_1h_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0
)
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_session_id ON agent_metrics (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_recorded_at ON agent_metrics (recorded_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_role ON agent_metrics (role)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_model_family ON agent_metrics (model_family)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_kanban_session ON agent_metrics (kanban_session)",
]

DB_PATH = Path.home() / ".claude" / "metrics" / "claude-metrics.db"


# ---------------------------------------------------------------------------
# Model family detection
# ---------------------------------------------------------------------------
def detect_model_family(model: str) -> str:
    """Parse model string to determine pricing family."""
    lower = model.lower()
    if "opus" in lower:
        return "opus"
    if "sonnet" in lower:
        return "sonnet"
    # haiku-3.5 check must come before generic haiku check
    if "haiku" in lower and "3-5" in lower:
        return "haiku-3.5"
    if "haiku" in lower and "3.5" in lower:
        return "haiku-3.5"
    if "haiku" in lower:
        return "haiku"
    return "unknown"


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------
def calculate_cost(family: str, tokens: dict) -> float:
    """Calculate USD cost given model family and token counts."""
    prices = PRICING.get(family, PRICING["unknown"])
    per_million = 1_000_000.0
    cost = (
        tokens["input"] * prices["input"] / per_million
        + tokens["output"] * prices["output"] / per_million
        + tokens["cache_creation_5m"] * prices["cache_creation_5m"] / per_million
        + tokens["cache_creation_1h"] * prices["cache_creation_1h"] / per_million
        + tokens["cache_read"] * prices["cache_read"] / per_million
    )
    return cost


# ---------------------------------------------------------------------------
# JSONL transcript parsing
# ---------------------------------------------------------------------------
def parse_transcript(transcript_path: str) -> dict:
    """
    Stream the JSONL transcript and aggregate token counts per model.

    Returns a dict keyed by model string:
        {
            "claude-sonnet-4-20250514": {
                "turns": int,
                "input": int,
                "output": int,
                "cache_creation_5m": int,
                "cache_creation_1h": int,
                "cache_read": int,
            },
            ...
        }
    """
    aggregates = {}

    with open(transcript_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            # Fast pre-filter — skip lines that cannot contain assistant data
            if '"assistant"' not in raw_line:
                continue

            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            model = msg.get("model", "")
            if not model:
                continue

            usage = msg.get("usage", {})
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            # cache_creation_input_tokens → cache_creation_5m_tokens
            cache_creation_5m = usage.get("cache_creation_input_tokens", 0) or 0
            # cache_creation_1h not yet surfaced by Claude Code
            cache_creation_1h = 0
            cache_read = usage.get("cache_read_input_tokens", 0) or 0

            if model not in aggregates:
                aggregates[model] = {
                    "turns": 0,
                    "input": 0,
                    "output": 0,
                    "cache_creation_5m": 0,
                    "cache_creation_1h": 0,
                    "cache_read": 0,
                }

            rec = aggregates[model]
            rec["turns"] += 1
            rec["input"] += input_tokens
            rec["output"] += output_tokens
            rec["cache_creation_5m"] += cache_creation_5m
            rec["cache_creation_1h"] += cache_creation_1h
            rec["cache_read"] += cache_read

    return aggregates


# ---------------------------------------------------------------------------
# Kanban session lookup
# ---------------------------------------------------------------------------
def lookup_kanban_session(working_directory: str, session_id: str):
    """
    Read {working_directory}/.kanban/sessions.json and return the friendly
    session name for session_id. Returns None on any failure.
    """
    try:
        sessions_path = Path(working_directory) / ".kanban" / "sessions.json"
        with open(sessions_path, "r", encoding="utf-8") as fh:
            sessions = json.load(fh)
        return sessions.get(session_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SQLite writer
# ---------------------------------------------------------------------------
def open_db() -> sqlite3.Connection:
    """Open (and migrate) the metrics database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(CREATE_TABLE_SQL)
    for idx_sql in CREATE_INDEX_SQL:
        conn.execute(idx_sql)
    conn.commit()
    return conn


def write_metrics(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id,
    role: str,
    working_directory: str,
    kanban_session,
    aggregates: dict,
) -> None:
    """Insert one row per model into agent_metrics."""
    for model, tokens in aggregates.items():
        family = detect_model_family(model)
        cost = calculate_cost(family, tokens)

        conn.execute(
            """
            INSERT INTO agent_metrics (
                session_id, agent_id, role,
                working_directory, kanban_session,
                model, model_family,
                turns, input_tokens, output_tokens,
                cache_creation_5m_tokens, cache_creation_1h_tokens, cache_read_tokens,
                cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_id,
                role,
                working_directory,
                kanban_session,
                model,
                family,
                tokens["turns"],
                tokens["input"],
                tokens["output"],
                tokens["cache_creation_5m"],
                tokens["cache_creation_1h"],
                tokens["cache_read"],
                cost,
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    payload = json.load(sys.stdin)

    # Detect hook type by which keys are present
    if "agent_transcript_path" in payload:
        # SubagentStop
        role = payload.get("agent_type") or "subagent"
        transcript_path = payload["agent_transcript_path"]
    else:
        # Stop (parent session)
        role = "parent"
        transcript_path = payload.get("transcript_path", "")

    session_id = payload.get("session_id", "")
    agent_id = payload.get("agent_id") or None
    working_directory = os.getcwd()
    kanban_session = lookup_kanban_session(working_directory, session_id)

    if not transcript_path:
        return

    aggregates = parse_transcript(transcript_path)
    if not aggregates:
        return

    conn = open_db()
    try:
        write_metrics(
            conn,
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            working_directory=working_directory,
            kanban_session=kanban_session,
            aggregates=aggregates,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never exit non-zero — hook must not disrupt Claude Code
        pass
