#!/usr/bin/env python3
"""
claudit2 metrics hook: Claude Code hook for capturing agent metrics into SQLite.

Triggered by Claude Code's Stop and SubagentStop events. Reads JSON payload
from stdin, parses the JSONL transcript, aggregates tokens per model, computes
cost, and writes to ~/.claude/metrics/claudit2.db.

Key differences from the V1 hook (claude-metrics-hook.py):
  - Single row per agent (session_id + agent_id primary key) instead of per model
  - Bash tool normalization: bash_command + bash_subcommand as separate columns
  - Model normalization: full model string collapsed to sonnet/opus/haiku short form
  - card_number extracted from transcript by scanning kanban CLI bash calls
  - git_repo derived from git remote get-url origin (falls back to basename(cwd))
  - Errors logged to ~/.claude/metrics/claudit2-errors.log (never to stderr/exit non-zero)
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"
ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "claudit-errors.log"

# ---------------------------------------------------------------------------
# Pricing table — per 1M tokens, keyed by normalized model name
# Prices last verified: 2026-03-13
# Source: https://www.anthropic.com/pricing
# ---------------------------------------------------------------------------
PRICING = {
    "sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "opus": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "haiku": {
        "input": 0.25,
        "output": 1.25,
        "cache_read": 0.03,
        "cache_write": 0.30,
    },
}

# ---------------------------------------------------------------------------
# DDL
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

# kanban_card_events is written by the kanban CLI; created here idempotently
# so Grafana can query it before any events have been recorded.
# NOTE: This DDL is intentionally duplicated in modules/kanban/kanban.py.
# Both files must stay in sync.
CREATE_KANBAN_CARD_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS kanban_card_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kanban_session TEXT NOT NULL,
    card_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
]


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------

def utc_now() -> str:
    """Return current UTC time as ISO 8601 with T-separator and Z suffix."""
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_timestamp(raw) -> float | None:
    """Parse ISO 8601 timestamp string into POSIX float. Returns None on failure."""
    if not raw or not isinstance(raw, str):
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Model normalization
# ---------------------------------------------------------------------------

def normalize_model(model: str) -> str:
    """
    Collapse full model strings to short form.

    Rules (substring match, case-insensitive):
      contains 'sonnet' -> 'sonnet'
      contains 'opus'   -> 'opus'
      contains 'haiku'  -> 'haiku'
      else              -> first 20 chars of original
    """
    lower = model.lower()
    if "sonnet" in lower:
        return "sonnet"
    if "opus" in lower:
        return "opus"
    if "haiku" in lower:
        return "haiku"
    return model[:20]


# ---------------------------------------------------------------------------
# Bash tool normalization
# ---------------------------------------------------------------------------

def normalize_bash_tool(command: str) -> tuple[str, str | None]:
    """
    Parse a Bash tool command string into (bash_command, bash_subcommand).

    bash_command  = first word (e.g. 'git', 'kanban', 'npm')
    bash_subcommand = second word if it exists AND does not start with '-',
                      else None (e.g. 'commit', 'do', 'run')

    Strips all flags and argument values — only the command and subcommand
    words are returned.
    """
    parts = command.strip().split()
    if not parts:
        return ("", None)
    bash_command = parts[0]
    bash_subcommand: str | None = None
    if len(parts) >= 2 and not parts[1].startswith("-"):
        bash_subcommand = parts[1]
    return (bash_command, bash_subcommand)


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------

def calculate_cost(model_normalized: str, tokens: dict) -> float:
    """
    Calculate USD cost given normalized model name and token counts.
    Falls back to sonnet rates for unknown models.
    All prices are per 1M tokens.
    """
    prices = PRICING.get(model_normalized, PRICING["sonnet"])
    per_million = 1_000_000.0
    return (
        tokens.get("input", 0) * prices["input"] / per_million
        + tokens.get("output", 0) * prices["output"] / per_million
        + tokens.get("cache_read", 0) * prices["cache_read"] / per_million
        + tokens.get("cache_write", 0) * prices["cache_write"] / per_million
    )


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
# Git repo detection
# ---------------------------------------------------------------------------

def get_git_repo(cwd: str) -> str:
    """
    Determine the git repo name for the given working directory.

    Runs: git -C <cwd> remote get-url origin
    Then strips everything before the last '/' and the '.git' suffix.
    Falls back to os.path.basename(cwd.rstrip('/')) on any failure.
    """
    fallback = os.path.basename(cwd.rstrip("/")) or "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return fallback
        url = result.stdout.strip()
        if not url:
            return fallback
        # Strip everything before the last '/' (guard: bare repo names have no slash)
        repo = url.rsplit("/", 1)[-1] if "/" in url else url
        # Strip .git suffix
        if repo.endswith(".git"):
            repo = repo[:-4]
        return repo or fallback
    except Exception:
        return fallback


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


def lookup_kanban_session(working_directory: str, session_id: str) -> str:
    """
    Return the friendly kanban session name for session_id, or 'unknown'.

    Walk up from cwd looking for .kanban/sessions.json. Sessions are keyed
    by the first 8 characters of the Claude session UUID.
    """
    prefix = session_id[:8]
    home = Path.home()
    current = Path(working_directory).resolve()

    while True:
        candidate = current / ".kanban" / "sessions.json"
        sessions = _read_sessions_file(candidate)
        result = sessions.get(prefix)
        if result is not None:
            return result
        if current == home or current.parent == current:
            break
        current = current.parent

    return "unknown"


# ---------------------------------------------------------------------------
# Card number extraction
# ---------------------------------------------------------------------------

# Pattern matches: kanban show N, kanban criteria check N, kanban review N
_CARD_NUMBER_PATTERN = re.compile(
    r'\bkanban\s+(?:show|criteria\s+check|review)\s+(\d+)\b'
)


def extract_card_number(transcript_path: str) -> int | None:
    """
    Scan the agent transcript for the first Bash tool call containing a
    kanban show/criteria check/review command and extract the card number.

    Returns None if not found.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                if '"assistant"' not in raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                msg = entry.get("message", {})
                for block in msg.get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name") != "Bash":
                        continue
                    command = block.get("input", {}).get("command", "")
                    match = _CARD_NUMBER_PATTERN.search(command)
                    if match:
                        return int(match.group(1))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# JSONL transcript parsing
# ---------------------------------------------------------------------------

_REJECTION_SENTINEL = "User rejected tool use"


def parse_transcript(transcript_path: str) -> dict:
    """
    Stream the JSONL transcript and aggregate:
      - Token counts (input, output, cache_read, cache_write) — summed across all models
      - Dominant model (most turns)
      - Turn count and timestamps for latency computation
      - Tool usage (tool_name, bash_command, bash_subcommand, call_count)
      - Permission denials (tool_use_id, tool_name)

    Returns:
        {
            "model": str,                # normalized short model name (dominant model)
            "input_tokens": int,
            "output_tokens": int,
            "cache_read_tokens": int,
            "cache_write_tokens": int,
            "total_turns": int,
            "timestamps": [float, ...],  # one per assistant turn
            "tools": {
                (tool_name, bash_cmd, bash_sub): int  # call_count
            },
            "tool_id_to_name": {str: str},
            "denials": [{"tool_use_id": str, "tool_name": str}, ...],
        }
    """
    # Per-model tracking (to determine dominant model)
    models: dict[str, dict] = {}
    # Aggregated totals (all models combined)
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    total_turns = 0
    timestamps: list[float] = []

    # tool_name_key -> call_count where tool_name_key is (tool_name, bash_cmd, bash_sub)
    tools: dict[tuple, int] = {}
    tool_id_to_name: dict[str, str] = {}
    denials: list[dict] = []

    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                has_assistant = '"assistant"' in raw_line
                has_tool_result = '"tool_result"' in raw_line

                if not has_assistant and not has_tool_result:
                    continue

                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")

                if entry_type == "assistant":
                    msg = entry.get("message", {})
                    raw_model = msg.get("model", "")

                    usage = msg.get("usage", {})
                    input_tokens = usage.get("input_tokens", 0) or 0
                    output_tokens = usage.get("output_tokens", 0) or 0
                    cache_read = usage.get("cache_read_input_tokens", 0) or 0

                    # cache_write: prefer nested cache_creation object (V4+ API),
                    # fall back to flat cache_creation_input_tokens field
                    cache_creation_obj = usage.get("cache_creation") or {}
                    if isinstance(cache_creation_obj, dict) and cache_creation_obj:
                        cache_write = (
                            (cache_creation_obj.get("ephemeral_5m_input_tokens", 0) or 0)
                            + (cache_creation_obj.get("ephemeral_1h_input_tokens", 0) or 0)
                        )
                    else:
                        cache_write = usage.get("cache_creation_input_tokens", 0) or 0

                    total_input += input_tokens
                    total_output += output_tokens
                    total_cache_read += cache_read
                    total_cache_write += cache_write
                    total_turns += 1

                    ts = parse_timestamp(entry.get("timestamp"))
                    if ts is not None:
                        timestamps.append(ts)

                    # Track per-model turn counts to determine dominant model
                    if raw_model:
                        if raw_model not in models:
                            models[raw_model] = {"turns": 0}
                        models[raw_model]["turns"] += 1

                    # Collect tool_use blocks
                    for block in msg.get("content", []):
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue

                        raw_tool_name = block.get("name", "unknown")
                        tool_id = block.get("id", "")

                        if raw_tool_name == "Bash":
                            command = block.get("input", {}).get("command", "")
                            bash_cmd, bash_sub = normalize_bash_tool(command)
                            tool_key = ("Bash", bash_cmd or None, bash_sub)
                            resolved_name = "Bash"
                        else:
                            tool_key = (raw_tool_name, None, None)
                            resolved_name = raw_tool_name

                        tools[tool_key] = tools.get(tool_key, 0) + 1

                        if tool_id:
                            tool_id_to_name[tool_id] = resolved_name

                elif entry_type == "tool_result":
                    tool_use_id = entry.get("tool_use_id", "")
                    tool_use_result = entry.get("toolUseResult")

                    if tool_use_result == _REJECTION_SENTINEL:
                        denial_tool_name = tool_id_to_name.get(tool_use_id, "unknown")
                        denials.append({
                            "tool_use_id": tool_use_id,
                            "tool_name": denial_tool_name,
                        })

    except Exception as exc:
        log_error(f"parse_transcript error: {exc}\n{traceback.format_exc()}")

    # Determine dominant model (most turns), fall back to 'unknown'
    dominant_model = "unknown"
    if models:
        dominant_raw = max(models, key=lambda m: models[m]["turns"])
        dominant_model = normalize_model(dominant_raw)

    return {
        "model": dominant_model,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "total_turns": total_turns,
        "timestamps": timestamps,
        "tools": tools,
        "tool_id_to_name": tool_id_to_name,
        "denials": denials,
    }


# ---------------------------------------------------------------------------
# Timing derivation
# ---------------------------------------------------------------------------

def compute_avg_latency(timestamps: list[float]) -> float:
    """Mean gap between consecutive timestamps. Returns 0.0 if < 2 timestamps."""
    if len(timestamps) < 2:
        return 0.0
    sorted_ts = sorted(timestamps)
    gaps = [sorted_ts[i + 1] - sorted_ts[i] for i in range(len(sorted_ts) - 1)]
    return sum(gaps) / len(gaps)


# ---------------------------------------------------------------------------
# DB initialization
# ---------------------------------------------------------------------------

def open_db() -> sqlite3.Connection:
    """Open (and initialize) the claudit2 metrics database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    try:
        conn.execute(CREATE_AGENT_METRICS_SQL)
        conn.execute(CREATE_AGENT_TOOL_USAGE_SQL)
        conn.execute(CREATE_PERMISSION_DENIALS_SQL)
        conn.execute(CREATE_KANBAN_CARD_EVENTS_SQL)

        for idx_sql in CREATE_INDEXES_SQL:
            conn.execute(idx_sql)

        conn.commit()
    except Exception:
        conn.close()
        raise

    return conn


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------

def write_agent_metrics(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: str,
    agent: str,
    model: str,
    kanban_session: str,
    card_number: int | None,
    git_repo: str,
    working_directory: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    cost_usd: float,
    total_turns: int,
    avg_turn_latency_seconds: float,
    cache_hit_ratio: float,
    now: str,
) -> None:
    """
    Upsert one row into agent_metrics keyed on (session_id, agent_id).

    On conflict: update all data columns and last_seen_at; preserve first_seen_at
    and recorded_at from the original insert.
    """
    conn.execute(
        """
        INSERT INTO agent_metrics (
            session_id, agent_id, agent, model, kanban_session, card_number,
            git_repo, working_directory,
            first_seen_at, last_seen_at, recorded_at,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            cost_usd, total_turns, avg_turn_latency_seconds, cache_hit_ratio
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        ON CONFLICT(session_id, agent_id) DO UPDATE SET
            agent = excluded.agent,
            model = excluded.model,
            kanban_session = excluded.kanban_session,
            card_number = excluded.card_number,
            git_repo = excluded.git_repo,
            working_directory = excluded.working_directory,
            last_seen_at = excluded.last_seen_at,
            input_tokens = excluded.input_tokens,
            output_tokens = excluded.output_tokens,
            cache_read_tokens = excluded.cache_read_tokens,
            cache_write_tokens = excluded.cache_write_tokens,
            cost_usd = excluded.cost_usd,
            total_turns = excluded.total_turns,
            avg_turn_latency_seconds = excluded.avg_turn_latency_seconds,
            cache_hit_ratio = excluded.cache_hit_ratio
        """,
        (
            session_id, agent_id, agent, model, kanban_session, card_number,
            git_repo, working_directory,
            now, now, now,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            cost_usd, total_turns, avg_turn_latency_seconds, cache_hit_ratio,
        ),
    )


def write_tool_usage(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: str,
    tools: dict[tuple, int],
) -> None:
    """
    Accumulate tool call counts across multiple hook fires for the same agent.

    Uses INSERT OR REPLACE with call_count = COALESCE(old, 0) + new to
    accumulate counts rather than overwrite them.

    bash_command and bash_subcommand are stored as empty strings (not NULL)
    to comply with PRIMARY KEY constraints (SQLite prohibits expressions in PKs).
    """
    for (tool_name, bash_command, bash_subcommand), call_count in tools.items():
        # Read existing count (if any) and add to it
        bash_cmd_val = bash_command or ""
        bash_sub_val = bash_subcommand or ""
        row = conn.execute(
            """
            SELECT call_count FROM agent_tool_usage
            WHERE session_id = ?
              AND agent_id = ?
              AND tool_name = ?
              AND bash_command = ?
              AND bash_subcommand = ?
            """,
            (session_id, agent_id, tool_name, bash_cmd_val, bash_sub_val),
        ).fetchone()
        existing_count = row[0] if row else 0
        new_count = existing_count + call_count

        conn.execute(
            """
            INSERT OR REPLACE INTO agent_tool_usage
                (session_id, agent_id, tool_name, bash_command, bash_subcommand, call_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_id,
                tool_name,
                bash_cmd_val,  # Empty string for non-Bash tools (not NULL)
                bash_sub_val,  # Empty string when no subcommand (not NULL)
                new_count,
            ),
        )


def write_permission_denials(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: str,
    denials: list[dict],
    now: str,
) -> None:
    """Insert permission denial rows. INSERT OR IGNORE on tool_use_id UNIQUE."""
    for denial in denials:
        conn.execute(
            """
            INSERT OR IGNORE INTO permission_denials
                (session_id, agent_id, tool_use_id, tool_name, denied_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                agent_id,
                denial["tool_use_id"],
                denial["tool_name"],
                now,
            ),
        )


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def log_error(message: str) -> None:
    """Append an error message to the claudit2 error log file."""
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now()
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass  # Logging failure must not propagate


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    payload = json.load(sys.stdin)

    # Detect event type. Use agent_transcript_path presence as primary signal
    # (matching the existing hook convention), with hook_event_name as fallback.
    is_subagent_stop = "agent_transcript_path" in payload

    if is_subagent_stop:
        agent = payload.get("agent_type") or "subagent"
        transcript_path = payload["agent_transcript_path"]
    else:
        agent = os.environ.get('CLAUDIT2_ROLE') or 'claude'
        transcript_path = payload.get("transcript_path", "")

    session_id = payload.get("session_id", "")
    agent_id = payload.get("agent_id") or ""
    working_directory = payload.get("cwd") or os.getcwd()

    if not transcript_path:
        return

    now = utc_now()

    # Parse transcript
    parsed = parse_transcript(transcript_path)

    # Early exit if transcript had no assistant turns (nothing to record)
    if parsed["total_turns"] == 0:
        return

    # Derive context fields
    kanban_session = lookup_kanban_session(working_directory, session_id)
    git_repo = get_git_repo(working_directory)

    # Extract card number only for subagent stops (not meaningful for parent)
    card_number: int | None = None
    if is_subagent_stop:
        card_number = extract_card_number(transcript_path)

    model = parsed["model"]
    input_tokens = parsed["input_tokens"]
    output_tokens = parsed["output_tokens"]
    cache_read_tokens = parsed["cache_read_tokens"]
    cache_write_tokens = parsed["cache_write_tokens"]
    total_turns = parsed["total_turns"]
    avg_latency = compute_avg_latency(parsed["timestamps"])
    cache_hit_ratio = compute_cache_hit_ratio(cache_read_tokens, input_tokens)
    cost_usd = calculate_cost(
        model,
        {
            "input": input_tokens,
            "output": output_tokens,
            "cache_read": cache_read_tokens,
            "cache_write": cache_write_tokens,
        },
    )

    conn = open_db()
    try:
        write_agent_metrics(
            conn,
            session_id=session_id,
            agent_id=agent_id,
            agent=agent,
            model=model,
            kanban_session=kanban_session,
            card_number=card_number,
            git_repo=git_repo,
            working_directory=working_directory,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost_usd,
            total_turns=total_turns,
            avg_turn_latency_seconds=avg_latency,
            cache_hit_ratio=cache_hit_ratio,
            now=now,
        )
        write_tool_usage(conn, session_id, agent_id, parsed["tools"])
        write_permission_denials(conn, session_id, agent_id, parsed["denials"], now)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_error(f"hook error: {exc}\n{traceback.format_exc()}")
    sys.exit(0)
