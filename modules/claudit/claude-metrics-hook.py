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

V4 additions:
- Fix: cache_creation_1h_tokens now reads from the nested
  usage.cache_creation.ephemeral_1h_input_tokens field (previously always 0).
  cache_creation_5m_tokens similarly reads from
  usage.cache_creation.ephemeral_5m_input_tokens, with fallback to the
  flat usage.cache_creation_input_tokens field for older API responses.
- New: git_branch column captures the gitBranch field from each JSONL entry,
  enabling cost/usage filtering by branch.
- New: is_sidechain column captures the isSidechain boolean from each JSONL
  entry, enabling filtering of internal reasoning chains from turn counts.
- Migration: existing databases gain git_branch and is_sidechain columns via
  ALTER TABLE ... ADD COLUMN (no-op if already present).

V5 additions:
- New: permission_denials table captures tool use rejections where the user
  denied a permission prompt (toolUseResult == "User rejected tool use").
  Each row records session_id, agent_id, role, tool_name, tool_input (JSON),
  tool_use_id, and kanban_session for dashboard filtering.
- Detection: parser identifies tool_result entries with the rejection string,
  then walks the transcript to find the matching assistant tool_use block by
  tool_use_id to recover tool_name and tool_input.
- Migration: CREATE TABLE IF NOT EXISTS is idempotent for existing databases.

V6 additions:
- New: kanban_card_events table created here (idempotent) for Grafana
  availability before the first kanban CLI event. Written by kanban CLI.
- Migration: existing databases gain card_created_at, card_completed_at,
  card_type, ac_count, git_project, from_column, to_column columns on the
  kanban_card_events table via ALTER TABLE ... ADD COLUMN (no-op if present).
  This fixes "no such column" errors in Grafana dashboard panels that query
  these columns (DORA metrics, flow tracking, estimation calibration panels).

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
# Prices last verified: 2026-02-25
# Source: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
#
# Model identifier patterns per family:
#   "opus"     — claude-opus-4, claude-opus-4-5, claude-opus-4-6 (current gen, $5/$25)
#                NOTE: legacy models claude-opus-4-1 and claude-3-opus billed at
#                $15 input / $75 output / $18.75 cache-write-5m / $30 cache-write-1h /
#                $1.50 cache-read. Those are deprecated and cost here will be understated
#                if encountered.
#   "sonnet"   — claude-sonnet-4, claude-sonnet-4-5, claude-sonnet-4-6,
#                claude-sonnet-3-7 (deprecated)
#   "haiku-3.5"— claude-haiku-3-5 (deprecated)
#   "haiku"    — claude-haiku-4-5 and newer haiku models ($1/$5). NOTE: legacy
#                claude-haiku-3 billed at $0.25 input / $1.25 output; cost will be
#                overstated if encountered. haiku-3.5 is handled by the "haiku-3.5"
#                key above.
#   "unknown"  — unrecognised model strings; cost recorded as $0.00
# ---------------------------------------------------------------------------
PRICING = {
    "opus": {
        # claude-opus-4, claude-opus-4-5, claude-opus-4-6
        "input": 5.00,
        "output": 25.00,
        "cache_creation_5m": 6.25,
        "cache_creation_1h": 10.00,
        "cache_read": 0.50,
    },
    "sonnet": {
        # claude-sonnet-4, claude-sonnet-4-5, claude-sonnet-4-6
        "input": 3.00,
        "output": 15.00,
        "cache_creation_5m": 3.75,
        "cache_creation_1h": 6.00,
        "cache_read": 0.30,
    },
    "haiku-3.5": {
        # claude-haiku-3-5 (deprecated)
        "input": 0.80,
        "output": 4.00,
        "cache_creation_5m": 1.00,
        "cache_creation_1h": 1.60,
        "cache_read": 0.08,
    },
    "haiku": {
        # claude-haiku-4-5 and newer haiku models
        "input": 1.00,
        "output": 5.00,
        "cache_creation_5m": 1.25,
        "cache_creation_1h": 2.00,
        "cache_read": 0.10,
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
    git_branch TEXT,
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
    is_sidechain INTEGER NOT NULL DEFAULT 0,
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

CREATE_TABLE_PERMISSION_DENIALS_SQL = """
CREATE TABLE IF NOT EXISTS permission_denials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    tool_name TEXT NOT NULL,
    tool_input TEXT,
    tool_use_id TEXT,
    kanban_session TEXT,
    UNIQUE(session_id, tool_use_id)
)
"""

# V6: kanban_card_events — written by the kanban CLI on all column transitions.
# Created here (idempotent) so Grafana can query the table even before the
# first event occurs.  Also created by the kanban CLI itself on first use.
# NOTE: This DDL is intentionally duplicated in modules/kanban/kanban.py
# Both files must stay in sync — changes here require matching changes there.
CREATE_TABLE_KANBAN_CARD_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS kanban_card_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_number TEXT NOT NULL,
    event_type TEXT NOT NULL,
    persona TEXT,
    model TEXT,
    kanban_session TEXT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    card_created_at TEXT,
    card_completed_at TEXT,
    card_type TEXT,
    ac_count INTEGER,
    git_project TEXT,
    from_column TEXT,
    to_column TEXT
)
"""

# NOTE: These index definitions are intentionally duplicated in modules/kanban/kanban.py
# Both files must stay in sync — changes here require matching changes there.
CREATE_INDEX_KANBAN_CARD_EVENTS_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_kanban_card_events_event_type ON kanban_card_events (event_type)",
    "CREATE INDEX IF NOT EXISTS idx_kanban_card_events_persona ON kanban_card_events (persona)",
    "CREATE INDEX IF NOT EXISTS idx_kanban_card_events_recorded_at ON kanban_card_events (recorded_at)",
]

# V6 migration: add columns that were added to kanban_card_events in V6 but may
# be absent in databases created before this version (CREATE TABLE IF NOT EXISTS
# is a no-op on existing tables, so ALTER TABLE is required for existing DBs).
# OperationalError ("duplicate column name") is caught and ignored — idempotent.
# NOTE: This migration list is intentionally duplicated in modules/kanban/kanban.py
# Both files must stay in sync — changes here require matching changes there.
V6_KANBAN_MIGRATION_SQL = [
    "ALTER TABLE kanban_card_events ADD COLUMN card_created_at TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN card_completed_at TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN card_type TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN ac_count INTEGER",
    "ALTER TABLE kanban_card_events ADD COLUMN git_project TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN from_column TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN to_column TEXT",
]


CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_session_id ON agent_metrics (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_recorded_at ON agent_metrics (recorded_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_role ON agent_metrics (role)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_model_family ON agent_metrics (model_family)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_kanban_session ON agent_metrics (kanban_session)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_git_branch ON agent_metrics (git_branch)",
    "CREATE INDEX IF NOT EXISTS idx_agent_metrics_is_sidechain ON agent_metrics (is_sidechain)",
    "CREATE INDEX IF NOT EXISTS idx_tool_usage_session_id ON agent_tool_usage (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_tool_usage_tool_name ON agent_tool_usage (tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_tool_usage_role ON agent_tool_usage (role)",
    "CREATE INDEX IF NOT EXISTS idx_permission_denials_session_id ON permission_denials (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_permission_denials_tool_name ON permission_denials (tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_permission_denials_kanban_session ON permission_denials (kanban_session)",
]

# Columns added in V4 that may be absent in existing databases (pre-V4).
# ALTER TABLE ... ADD COLUMN is idempotent here because we catch OperationalError
# ("duplicate column name") and continue — no data is lost.
V4_MIGRATION_SQL = [
    "ALTER TABLE agent_metrics ADD COLUMN git_branch TEXT",
    "ALTER TABLE agent_metrics ADD COLUMN is_sidechain INTEGER NOT NULL DEFAULT 0",
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
_REJECTION_SENTINEL = "User rejected tool use"


def parse_transcript(transcript_path: str) -> dict:
    """
    Stream the JSONL transcript and aggregate token counts per model,
    tool usage counts, timing information, and permission denials.

    Returns a dict with the following top-level keys:

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
        },
        "denials": [
            {
                "tool_name": str,
                "tool_input": str | None,   # JSON-serialised input dict
                "tool_use_id": str,
            },
            ...
        ],
        "git_branch": str | None,   # last non-None gitBranch seen in transcript
        "is_sidechain": bool,       # True if any entry has isSidechain=True
    """
    models = {}
    tools: dict[str, dict] = {}
    # Maps tool_use_id -> {"name": str, "input": dict | None}
    tool_id_to_info: dict[str, dict] = {}
    denials: list[dict] = []
    git_branch: str | None = None
    is_sidechain: bool = False

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

            # Capture session-level fields present on all entry types
            raw_branch = entry.get("gitBranch")
            if raw_branch and isinstance(raw_branch, str):
                git_branch = raw_branch
            if entry.get("isSidechain") is True:
                is_sidechain = True

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

                # cache_creation tokens: prefer the nested cache_creation object
                # (ephemeral_5m_input_tokens / ephemeral_1h_input_tokens) introduced
                # in newer API responses.  Fall back to the flat
                # cache_creation_input_tokens field for older responses that only
                # reported a single 5-minute bucket.
                cache_creation_obj = usage.get("cache_creation") or {}
                if isinstance(cache_creation_obj, dict) and cache_creation_obj:
                    cache_creation_5m = cache_creation_obj.get("ephemeral_5m_input_tokens", 0) or 0
                    cache_creation_1h = cache_creation_obj.get("ephemeral_1h_input_tokens", 0) or 0
                else:
                    # Flat fallback: treat all creation tokens as 5m bucket
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
                    tool_input = block.get("input")
                    # For Bash tools, enrich name with the command being run
                    if tool_name == "Bash":
                        command = block.get("input", {}).get("command", "")
                        if command:
                            tool_name = f"Bash:{command[:500]}"
                    if tool_name not in tools:
                        tools[tool_name] = {"calls": 0, "errors": 0}
                    tools[tool_name]["calls"] += 1
                    if tool_id:
                        tool_id_to_info[tool_id] = {"name": tool_name, "input": tool_input}

            # --- Tool result messages: detect errors and permission denials ---
            elif entry_type == "tool_result":
                tool_use_id = entry.get("tool_use_id", "")
                is_error = entry.get("is_error", False)
                tool_use_result = entry.get("toolUseResult")

                # Permission denial: toolUseResult is the sentinel string
                if tool_use_result == _REJECTION_SENTINEL:
                    info = tool_id_to_info.get(tool_use_id, {})
                    denial_tool_name = info.get("name", "unknown")
                    denial_tool_input = info.get("input")
                    denial_input_str: str | None = None
                    if denial_tool_input is not None:
                        try:
                            denial_input_str = json.dumps(denial_tool_input)
                        except (TypeError, ValueError):
                            denial_input_str = None
                    denials.append({
                        "tool_name": denial_tool_name,
                        "tool_input": denial_input_str,
                        "tool_use_id": tool_use_id,
                    })

                if not is_error:
                    continue
                # Match error back to the tool name when possible
                tool_name = tool_id_to_info.get(tool_use_id, {}).get("name")
                if tool_name and tool_name in tools:
                    tools[tool_name]["errors"] += 1
                else:
                    # Unmatched error — attribute to a sentinel bucket
                    sentinel = "_unmatched_error"
                    if sentinel not in tools:
                        tools[sentinel] = {"calls": 0, "errors": 0}
                    tools[sentinel]["errors"] += 1

    # Preserve backward-compatible key name alongside new tool_id_to_info
    tool_id_to_name = {tid: info["name"] for tid, info in tool_id_to_info.items()}

    return {
        "models": models,
        "tools": tools,
        "tool_id_to_name": tool_id_to_name,
        "denials": denials,
        "git_branch": git_branch,
        "is_sidechain": is_sidechain,
    }


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
def _read_sessions_file(path: Path) -> dict:
    """Read a sessions.json file, returning empty dict on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def lookup_kanban_session(working_directory: str, session_id: str):
    """
    Return the friendly kanban session name for session_id, or None.

    Strategy:
    1. Check {working_directory}/.kanban/sessions.json first (fast path,
       works when payload contains correct cwd).
    2. If not found, scan all .kanban/sessions.json files under $HOME.
       This handles the case where cwd is absent from the payload and
       os.getcwd() returns a different directory than the project's root.

    sessions.json keys are the first 8 characters of the Claude session UUID
    (matching how kanban session-hook stores them via resolve_session_name).
    """
    prefix = session_id[:8]

    # Fast path: cwd-based lookup
    sessions_path = Path(working_directory) / ".kanban" / "sessions.json"
    sessions = _read_sessions_file(sessions_path)
    result = sessions.get(prefix)
    if result is not None:
        return result

    # Fallback: search all .kanban/sessions.json files under $HOME
    home = Path.home()
    for candidate in home.rglob(".kanban/sessions.json"):
        if candidate == sessions_path:
            continue
        sessions = _read_sessions_file(candidate)
        result = sessions.get(prefix)
        if result is not None:
            return result

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
    # V5: permission_denials table — CREATE IF NOT EXISTS is idempotent
    conn.execute(CREATE_TABLE_PERMISSION_DENIALS_SQL)
    # V6: kanban_card_events table — written by kanban CLI, created here for
    # Grafana availability even before the first column transition event is written.
    conn.execute(CREATE_TABLE_KANBAN_CARD_EVENTS_SQL)
    for idx_sql in CREATE_INDEX_KANBAN_CARD_EVENTS_SQL:
        conn.execute(idx_sql)

    # V6 migration: add columns to kanban_card_events for databases that predate V6.
    # ALTER TABLE ADD COLUMN is safe to retry — OperationalError is raised if the
    # column already exists, which we silently ignore.
    for alter_sql in V6_KANBAN_MIGRATION_SQL:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass

    # V4 migration: add new columns to existing databases that predate V4.
    # ALTER TABLE ADD COLUMN is safe to retry — OperationalError is raised if
    # the column already exists, which we silently ignore.
    for alter_sql in V4_MIGRATION_SQL:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass

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
    git_branch,
    models: dict,
    tools: dict,
    denials: list,
    duration_seconds: float,
    avg_turn_latency_seconds: float,
    is_sidechain: bool,
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
    is_sidechain_int = 1 if is_sidechain else 0

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
                working_directory, kanban_session, git_branch,
                model, model_family,
                turns, input_tokens, output_tokens,
                cache_creation_5m_tokens, cache_creation_1h_tokens, cache_read_tokens,
                cost_usd,
                duration_seconds, avg_turn_latency_seconds,
                cache_hit_ratio, tool_calls, tool_errors,
                is_sidechain
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, agent_id, role, model) DO UPDATE SET
                working_directory = excluded.working_directory,
                kanban_session = excluded.kanban_session,
                git_branch = excluded.git_branch,
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
                tool_errors = excluded.tool_errors,
                is_sidechain = excluded.is_sidechain
            """,
            (
                session_id,
                agent_id,
                role,
                working_directory,
                kanban_session,
                git_branch,
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
                is_sidechain_int,
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

    # V5: write permission denials — INSERT OR IGNORE prevents duplicate rows
    # when the hook fires multiple times for the same session.  tool_use_id is
    # the natural unique key for a single denial event; pairing it with
    # session_id gives a globally unique constraint.
    for denial in denials:
        conn.execute(
            """
            INSERT OR IGNORE INTO permission_denials (
                session_id, agent_id, role,
                tool_name, tool_input, tool_use_id,
                kanban_session
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_id,
                role,
                denial["tool_name"],
                denial["tool_input"],
                denial["tool_use_id"],
                kanban_session,
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
    working_directory = payload.get("cwd") or os.getcwd()
    kanban_session = lookup_kanban_session(working_directory, session_id)

    if not transcript_path:
        return

    parsed = parse_transcript(transcript_path)
    models = parsed["models"]
    tools = parsed["tools"]
    denials = parsed["denials"]
    git_branch = parsed["git_branch"]
    is_sidechain = parsed["is_sidechain"]

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
            git_branch=git_branch,
            models=models,
            tools=tools,
            denials=denials,
            duration_seconds=duration_seconds,
            avg_turn_latency_seconds=avg_turn_latency_seconds,
            is_sidechain=is_sidechain,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never exit non-zero — hook must not disrupt Claude Code
        pass
