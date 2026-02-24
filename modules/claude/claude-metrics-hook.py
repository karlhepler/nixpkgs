#!/usr/bin/env python3
"""
claude-metrics-hook: Claude Code hook for capturing agent metrics into SQLite.

Triggered by Claude Code's Stop and SubagentStop events. Reads JSON payload
from stdin, parses the JSONL transcript, aggregates tokens per model, computes
cost, and writes one row per model to ~/.claude/metrics/claude-metrics.db.

V2 additions: tool usage per session, session duration, turn latency, cache
hit ratio, and tool error counts.

V3 fix: UPSERT keyed on (session_id, agent_id, role, model) prevents duplicate
rows when the hook fires multiple times per session (once per SubagentStop and
once at final Stop). Each subsequent fire replaces the previous row with the
latest cumulative totals from the transcript.

Never exits non-zero — all errors are swallowed silently to avoid disrupting
Claude Code's hook pipeline.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
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
    agent_id TEXT NOT NULL DEFAULT '',
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
    cost_usd REAL NOT NULL DEFAULT 0.0,
    duration_seconds REAL DEFAULT 0.0,
    avg_turn_latency_seconds REAL DEFAULT 0.0,
    cache_hit_ratio REAL DEFAULT 0.0,
    tool_calls INTEGER DEFAULT 0,
    tool_errors INTEGER DEFAULT 0,
    UNIQUE(session_id, agent_id, role, model)
)
"""

CREATE_TABLE_TOOL_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS agent_tool_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    tool_name TEXT NOT NULL,
    call_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, agent_id, role, tool_name)
)
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_session_id ON agent_metrics (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_recorded_at ON agent_metrics (recorded_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_role ON agent_metrics (role)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_model_family ON agent_metrics (model_family)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_kanban_session ON agent_metrics (kanban_session)",
    "CREATE INDEX IF NOT EXISTS idx_tool_usage_session_id ON agent_tool_usage (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_tool_usage_tool_name ON agent_tool_usage (tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_tool_usage_role ON agent_tool_usage (role)",
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
    """
    Calculate USD cost given model family and token counts.

    All prices in PRICING table are per 1 million tokens.
    Token counts are raw totals from transcripts.
    Formula: (tokens / 1_000_000) * price_per_million = cost_usd
    """
    prices = PRICING.get(family, PRICING["unknown"])
    per_million = 1_000_000.0
    cost = (
        tokens.get("input", 0) * prices["input"] / per_million
        + tokens.get("output", 0) * prices["output"] / per_million
        + tokens.get("cache_creation_5m", 0) * prices["cache_creation_5m"] / per_million
        + tokens.get("cache_creation_1h", 0) * prices["cache_creation_1h"] / per_million
        + tokens.get("cache_read", 0) * prices["cache_read"] / per_million
    )
    return cost


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------
def parse_timestamp(raw) -> float | None:
    """
    Parse an ISO 8601 timestamp string into a POSIX float.
    Returns None if raw is absent or unparseable.
    """
    if not raw or not isinstance(raw, str):
        return None
    # Normalise trailing Z to +00:00 for fromisoformat compatibility
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Cache hit ratio
# ---------------------------------------------------------------------------
def compute_cache_hit_ratio(cache_read: int, input_tokens: int) -> float:
    """cache_read / (input_tokens + cache_read), 0.0 if denominator is zero."""
    denominator = input_tokens + cache_read
    if denominator == 0:
        return 0.0
    return cache_read / denominator


# ---------------------------------------------------------------------------
# JSONL transcript parsing
# ---------------------------------------------------------------------------
def parse_transcript(transcript_path: str) -> dict:
    """
    Stream the JSONL transcript and aggregate token counts per model,
    tool usage counts, and timing information.

    Returns a dict with two top-level keys:

        "models": {
            "claude-sonnet-4-20250514": {
                "turns": int,
                "input": int,
                "output": int,
                "cache_creation_5m": int,
                "cache_creation_1h": int,
                "cache_read": int,
                "timestamps": [float, ...],   # one per assistant turn
            },
            ...
        },
        "tools": {
            "Read": {"calls": int, "errors": int},
            "Write": {"calls": int, "errors": int},
            ...
        },
        "tool_id_to_name": {
            "toolu_abc": "Read",
            ...
        }
    """
    models = {}
    tools: dict[str, dict] = {}
    tool_id_to_name: dict[str, str] = {}

    with open(transcript_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            # Fast pre-filter — only parse lines likely to be relevant
            has_assistant = '"assistant"' in raw_line
            has_tool_result = '"tool_result"' in raw_line

            if not has_assistant and not has_tool_result:
                continue

            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")

            # --- Assistant messages: tokens + tool_use blocks ---
            if entry_type == "assistant":
                msg = entry.get("message", {})
                model = msg.get("model", "")
                if not model:
                    continue

                usage = msg.get("usage", {})
                input_tokens = usage.get("input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0
                cache_creation_5m = usage.get("cache_creation_input_tokens", 0) or 0
                cache_creation_1h = 0
                cache_read = usage.get("cache_read_input_tokens", 0) or 0

                if model not in models:
                    models[model] = {
                        "turns": 0,
                        "input": 0,
                        "output": 0,
                        "cache_creation_5m": 0,
                        "cache_creation_1h": 0,
                        "cache_read": 0,
                        "timestamps": [],
                    }

                rec = models[model]
                rec["turns"] += 1
                rec["input"] += input_tokens
                rec["output"] += output_tokens
                rec["cache_creation_5m"] += cache_creation_5m
                rec["cache_creation_1h"] += cache_creation_1h
                rec["cache_read"] += cache_read

                ts = parse_timestamp(entry.get("timestamp"))
                if ts is not None:
                    rec["timestamps"].append(ts)

                # Collect tool_use blocks from content array
                for block in msg.get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    tool_name = block.get("name", "unknown")
                    tool_id = block.get("id", "")
                    # For Bash tools, enrich name with the command being run
                    if tool_name == "Bash":
                        command = block.get("input", {}).get("command", "")
                        if command:
                            truncated = command[:50] + "..." if len(command) > 50 else command
                            tool_name = f"Bash:{truncated}"
                    if tool_name not in tools:
                        tools[tool_name] = {"calls": 0, "errors": 0}
                    tools[tool_name]["calls"] += 1
                    if tool_id:
                        tool_id_to_name[tool_id] = tool_name

            # --- Tool result messages: detect errors ---
            elif entry_type == "tool_result":
                tool_use_id = entry.get("tool_use_id", "")
                is_error = entry.get("is_error", False)
                if not is_error:
                    continue
                # Match error back to the tool name when possible
                tool_name = tool_id_to_name.get(tool_use_id)
                if tool_name and tool_name in tools:
                    tools[tool_name]["errors"] += 1
                else:
                    # Unmatched error — attribute to a sentinel bucket
                    sentinel = "_unmatched_error"
                    if sentinel not in tools:
                        tools[sentinel] = {"calls": 0, "errors": 0}
                    tools[sentinel]["errors"] += 1

    return {"models": models, "tools": tools}


# ---------------------------------------------------------------------------
# Duration / latency derivation
# ---------------------------------------------------------------------------
def compute_timing(models: dict) -> tuple[float, float]:
    """
    Derive (duration_seconds, avg_turn_latency_seconds) from per-model
    timestamp lists.

    Collects all timestamps across models, sorts them, then:
      - duration  = last - first
      - latency   = mean gap between consecutive timestamps

    Returns (0.0, 0.0) if fewer than two timestamps are available.
    """
    all_ts: list[float] = []
    for rec in models.values():
        all_ts.extend(rec.get("timestamps", []))

    if len(all_ts) < 2:
        return 0.0, 0.0

    all_ts.sort()
    duration = all_ts[-1] - all_ts[0]
    gaps = [all_ts[i + 1] - all_ts[i] for i in range(len(all_ts) - 1)]
    avg_latency = sum(gaps) / len(gaps)
    return duration, avg_latency


# ---------------------------------------------------------------------------
# Kanban session lookup
# ---------------------------------------------------------------------------
def lookup_kanban_session(working_directory: str, session_id: str):
    """
    Read {working_directory}/.kanban/sessions.json and return the friendly
    session name for session_id. Returns None on any failure.

    sessions.json keys are the first 8 characters of the Claude session UUID
    (matching how kanban session-hook stores them via resolve_session_name).
    """
    try:
        sessions_path = Path(working_directory) / ".kanban" / "sessions.json"
        with open(sessions_path, "r", encoding="utf-8") as fh:
            sessions = json.load(fh)
        return sessions.get(session_id[:8])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SQLite writer
# ---------------------------------------------------------------------------
def _needs_recreation(conn: sqlite3.Connection) -> bool:
    """
    Return True if agent_metrics lacks the UNIQUE constraint introduced in V3.

    SQLite encodes inline UNIQUE constraints as auto-named indexes with sql=NULL
    (e.g. sqlite_autoindex_agent_metrics_1). We detect presence of the V3
    constraint by checking whether any such autoindex exists on agent_metrics,
    which only appears after the UNIQUE clause is added to the DDL.
    """
    cur = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='index' AND tbl_name='agent_metrics' "
        "AND name LIKE 'sqlite_autoindex_%'"
    )
    return cur.fetchone()[0] == 0


def open_db() -> sqlite3.Connection:
    """Open (and migrate) the metrics database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    # V3 migration: if the unique constraint on agent_metrics is missing, drop
    # and recreate both tables so the new DDL (with UNIQUE) takes effect.
    # This is a one-time operation on existing databases.
    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='agent_metrics'"
        ).fetchone()[0]
        if existing and _needs_recreation(conn):
            conn.execute("DROP TABLE IF EXISTS agent_metrics")
            conn.execute("DROP TABLE IF EXISTS agent_tool_usage")
            conn.commit()
    except sqlite3.OperationalError:
        pass

    # Create tables (fresh DB or post-migration)
    conn.execute(CREATE_TABLE_SQL)
    conn.execute(CREATE_TABLE_TOOL_USAGE_SQL)

    for idx_sql in CREATE_INDEX_SQL:
        conn.execute(idx_sql)

    conn.commit()
    return conn


def write_metrics(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: str,
    role: str,
    working_directory: str,
    kanban_session,
    models: dict,
    tools: dict,
    duration_seconds: float,
    avg_turn_latency_seconds: float,
) -> None:
    """
    Upsert one row per model into agent_metrics and one row per tool_name
    into agent_tool_usage.

    Uses INSERT INTO ... ON CONFLICT DO UPDATE SET rather than INSERT OR REPLACE
    so that the row's id and recorded_at are preserved across hook re-fires.
    INSERT OR REPLACE deletes then re-inserts (changing id and recorded_at),
    which causes Grafana panels to flicker when time-series queries filter by
    recorded_at — the row appears to move forward in time on each hook fire.
    """
    for model, tokens in models.items():
        family = detect_model_family(model)
        cost = calculate_cost(family, tokens)
        cache_hit_ratio = compute_cache_hit_ratio(
            tokens["cache_read"], tokens["input"]
        )
        total_tool_calls = sum(t["calls"] for t in tools.values())
        total_tool_errors = sum(t["errors"] for t in tools.values())

        conn.execute(
            """
            INSERT INTO agent_metrics (
                session_id, agent_id, role,
                working_directory, kanban_session,
                model, model_family,
                turns, input_tokens, output_tokens,
                cache_creation_5m_tokens, cache_creation_1h_tokens, cache_read_tokens,
                cost_usd,
                duration_seconds, avg_turn_latency_seconds,
                cache_hit_ratio, tool_calls, tool_errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, agent_id, role, model) DO UPDATE SET
                working_directory = excluded.working_directory,
                kanban_session = excluded.kanban_session,
                model_family = excluded.model_family,
                turns = excluded.turns,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                cache_creation_5m_tokens = excluded.cache_creation_5m_tokens,
                cache_creation_1h_tokens = excluded.cache_creation_1h_tokens,
                cache_read_tokens = excluded.cache_read_tokens,
                cost_usd = excluded.cost_usd,
                duration_seconds = excluded.duration_seconds,
                avg_turn_latency_seconds = excluded.avg_turn_latency_seconds,
                cache_hit_ratio = excluded.cache_hit_ratio,
                tool_calls = excluded.tool_calls,
                tool_errors = excluded.tool_errors
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
                duration_seconds,
                avg_turn_latency_seconds,
                cache_hit_ratio,
                total_tool_calls,
                total_tool_errors,
            ),
        )

    for tool_name, counts in tools.items():
        conn.execute(
            """
            INSERT INTO agent_tool_usage (
                session_id, agent_id, role,
                tool_name, call_count, error_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, agent_id, role, tool_name) DO UPDATE SET
                call_count = excluded.call_count,
                error_count = excluded.error_count
            """,
            (
                session_id,
                agent_id,
                role,
                tool_name,
                counts["calls"],
                counts["errors"],
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
    agent_id = payload.get("agent_id") or ""
    working_directory = os.getcwd()
    kanban_session = lookup_kanban_session(working_directory, session_id)
    print(
        f"DEBUG kanban: cwd={working_directory}, session_id={session_id}, "
        f"first8={session_id[:8]}, kanban_session={kanban_session}",
        file=sys.stderr,
    )

    if not transcript_path:
        return

    parsed = parse_transcript(transcript_path)
    models = parsed["models"]
    tools = parsed["tools"]

    if not models:
        return

    duration_seconds, avg_turn_latency_seconds = compute_timing(models)

    conn = open_db()
    try:
        write_metrics(
            conn,
            session_id=session_id,
            agent_id=agent_id,
            role=role,
            working_directory=working_directory,
            kanban_session=kanban_session,
            models=models,
            tools=tools,
            duration_seconds=duration_seconds,
            avg_turn_latency_seconds=avg_turn_latency_seconds,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never exit non-zero — hook must not disrupt Claude Code
        pass
