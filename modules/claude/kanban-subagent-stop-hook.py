#!/usr/bin/env python3
"""
kanban-subagent-stop-hook: SubagentStop hook that implements the dual-loop AC
review system.

Triggered when any sub-agent finishes execution. Parses the agent's transcript
to find the associated kanban card, then runs an inner AC review loop using
claude -p --model haiku. If all criteria pass, the card is marked done and the
agent is allowed to stop. If criteria fail and review_cycles < 3, the agent is
blocked with failure details so it can fix and retry (outer loop). After 3
cycles, the agent is allowed to stop with a failure summary for staff.

Output format (SubagentStop hook):
    {"decision": "allow"}  — let the agent stop
    {"decision": "block", "reason": "..."}  — send agent back with feedback

Fails open: any error results in allowing the agent to stop unchanged.

Skip condition: BURNS_SESSION=1 env var means Ralph is running — skip AC review.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import traceback
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Suppress Python deprecation warnings to prevent stderr output,
# which Claude Code interprets as hook errors.
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-subagent-stop-hook-errors.log"
MAX_INNER_ITERATIONS = 2
MAX_OUTER_CYCLES = 3
CLAUDE_MAX_TURNS = 50
AC_REVIEWER_AGENT_PATH = Path.home() / ".claude" / "agents" / "ac-reviewer.md"

# ---------------------------------------------------------------------------
# Claudit DB integration — write AC reviewer token usage
# ---------------------------------------------------------------------------

_CLAUDIT_DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"

_CLAUDIT_PRICING = {
    "haiku": {
        "input": 0.25,
        "output": 1.25,
        "cache_read": 0.03,
        "cache_write": 0.30,
    },
}

_CREATE_AGENT_METRICS_SQL = """
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


_MIGRATE_KANBAN_CARD_EVENTS_REJECTION_REASONS_SQL = """
ALTER TABLE kanban_card_events ADD COLUMN rejection_reasons TEXT
"""


def _claudit_open_db() -> sqlite3.Connection | None:
    """Open (or create) the claudit metrics DB. Returns None on any failure."""
    try:
        _CLAUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_CLAUDIT_DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(_CREATE_AGENT_METRICS_SQL)
        # Idempotent migration: add rejection_reasons to kanban_card_events if absent.
        try:
            conn.execute(_MIGRATE_KANBAN_CARD_EVENTS_REJECTION_REASONS_SQL)
        except Exception as migration_exc:
            if "duplicate column name" not in str(migration_exc).lower():
                raise
        conn.commit()
        return conn
    except Exception as exc:
        log_error(f"claudit DB open failed: {exc}")
        return None


def _claudit_calculate_cost(input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    """Calculate USD cost for haiku model token usage."""
    prices = _CLAUDIT_PRICING["haiku"]
    per_million = 1_000_000.0
    return (
        input_tokens * prices["input"] / per_million
        + output_tokens * prices["output"] / per_million
        + cache_read * prices["cache_read"] / per_million
        + cache_write * prices["cache_write"] / per_million
    )


def _claudit_write_ac_reviewer_metrics(
    outer_session_id: str,
    kanban_session: str,
    card_number: str,
    working_directory: str,
    iteration: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> None:
    """Write AC reviewer token usage to the claudit SQLite DB. Never raises."""
    try:
        cost_usd = _claudit_calculate_cost(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
        # Use a synthetic session_id scoped to the outer session so metrics
        # appear grouped with the parent session in Grafana dashboards.
        # The agent_id encodes card + iteration to keep each run distinct.
        synthetic_session_id = f"ac-reviewer:{outer_session_id}" if outer_session_id else f"ac-reviewer:{uuid.uuid4()}"
        synthetic_agent_id = f"card-{card_number}-iter-{iteration}"

        cache_hit_ratio = 0.0
        denominator = input_tokens + cache_read_tokens
        if denominator > 0:
            cache_hit_ratio = cache_read_tokens / denominator

        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        conn = _claudit_open_db()
        if conn is None:
            return

        try:
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
                    synthetic_session_id,
                    synthetic_agent_id,
                    "ac-reviewer",
                    "haiku",
                    kanban_session,
                    int(card_number) if card_number else None,
                    "unknown",
                    working_directory,
                    now, now, now,
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    cost_usd,
                    1,   # total_turns = 1 per AC reviewer invocation
                    0.0,
                    cache_hit_ratio,
                ),
            )
            conn.commit()
            log_info(
                f"claudit: wrote ac-reviewer metrics for card #{card_number} iter {iteration}: "
                f"in={input_tokens} out={output_tokens} cache_read={cache_read_tokens} "
                f"cache_write={cache_write_tokens} cost=${cost_usd:.6f}"
            )
        finally:
            conn.close()
    except Exception as exc:
        log_error(f"claudit write failed for ac-reviewer card #{card_number} iter {iteration}: {exc}")


def _claudit_write_redo_rejection_reasons(
    card_number: str,
    kanban_session: str,
    rejection_reasons_json: str,
) -> None:
    """Update the most recent redo event for this card with rejection reasons.

    The kanban CLI inserts the redo row; this function runs immediately after
    and stamps rejection_reasons onto that row before the fail reasons are
    cleared by the redo operation.  Uses UPDATE ... WHERE id = (SELECT max(id)
    ...) to target only the latest row and avoid touching historical rows.

    Never raises — any failure is silently logged.
    """
    try:
        conn = _claudit_open_db()
        if conn is None:
            return
        try:
            conn.execute(
                """
                UPDATE kanban_card_events
                SET rejection_reasons = ?
                WHERE id = (
                    SELECT id FROM kanban_card_events
                    WHERE kanban_session = ?
                      AND card_number = ?
                      AND event_type = 'redo'
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (rejection_reasons_json, kanban_session, int(card_number)),
            )
            conn.commit()
            log_info(
                f"claudit: stamped rejection_reasons onto latest redo event "
                f"for card #{card_number} in session '{kanban_session}'"
            )
        finally:
            conn.close()
    except Exception as exc:
        log_error(
            f"claudit: failed to write redo rejection_reasons for card #{card_number}: {exc}"
        )


# Patterns for extracting card number and session from transcript lines
_KANBAN_CMD_PATTERN = re.compile(
    r'kanban\s+(?:criteria\s+check|review|show|status|done)\s+(\d+).*--session\s+([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern for "KANBAN CARD #N | Session: session-name" (injected by pretool hook)
_CARD_HEADER_PATTERN = re.compile(
    r'KANBAN\s+CARD\s+#(\d+)\s*\|\s*Session:\s*([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern for card reference in injected XML: card num="N" ... session="session-name"
_CARD_XML_PATTERN = re.compile(
    r'<card\s+[^>]*num="(\d+)"[^>]*session="([a-z0-9][a-z0-9-]*)"',
    re.IGNORECASE,
)

# Patterns for detecting permission-gate stalls in Claude Code dontAsk mode.
# Denied Bash commands produce tool results containing these phrases.
_PERMISSION_DENIAL_PATTERN = re.compile(
    r'(?:auto(?:matically)?[- ]denied|not allowed by.*permissions)',
    re.IGNORECASE,
)

# Markers that appear in block-feedback messages sent back to the agent after an
# AC review failure or unchecked-criteria rejection. Used by detect_criteria_gaming()
# to find the "last rejection point" in the transcript.
_BLOCK_FEEDBACK_MARKERS: list[str] = [
    "AC review failed for card",
    "kanban review failed for card",
    "unchecked acceptance criteria",
    "investigate each unchecked criterion",
    "investigate each failed criterion",
    "Anti-gaming gate triggered for card",
]

# Tool names (tool_use block "name" field) that constitute real, substantive work.
# kanban bookkeeping commands are deliberately excluded — they are not work.
_SUBSTANTIVE_TOOLS: frozenset[str] = frozenset([
    "Read",
    "Grep",
    "Glob",
    "Edit",
    "Write",
    "WebSearch",
    "WebFetch",
    "NotebookEdit",
    "Task",
])

# Matches any `kanban criteria ...` Bash invocation (bookkeeping, not work).
_KANBAN_CRITERIA_BASH: re.Pattern[str] = re.compile(
    r'^\s*kanban\s+criteria\s+',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises."""
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


INFO_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-subagent-stop-hook.log"


def log_info(message: str) -> None:
    """Log informational message to file. Never raises.

    Previously wrote to stderr, but Claude Code interprets any stderr output
    from hooks as errors — causing false 'hook error' labels in the UI.
    """
    try:
        INFO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(INFO_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Allow/block response helpers
# ---------------------------------------------------------------------------

def allow(message: str = "") -> dict:
    """Return a decision=allow response."""
    result = {"decision": "allow"}
    if message:
        result["reason"] = message
    return result


def block(reason: str, system_message: str = "") -> dict:
    """Return a decision=block response to send the agent back."""
    result = {"decision": "block", "reason": reason}
    if system_message:
        result["systemMessage"] = system_message
    return result


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def extract_agent_output(transcript_path: str) -> str:
    """
    Extract the agent's final substantive output from the JSONL transcript.

    Reads the transcript and returns the content of the last assistant message
    before the agent stopped. This is the agent's findings/deliverable summary.

    For review/research cards, this output IS the primary deliverable.
    For work cards, file inspection remains primary but this provides supplementary context.

    Returns the extracted output string, or empty string if not found.
    """
    last_assistant_content = ""
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                # Look for assistant-role messages
                if not isinstance(entry, dict):
                    continue

                role = entry.get("role", "")
                if role != "assistant":
                    continue

                content = entry.get("content", "")
                if isinstance(content, str) and content.strip():
                    last_assistant_content = content.strip()
                elif isinstance(content, list):
                    # Content may be a list of blocks; extract text blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text.strip():
                                text_parts.append(text.strip())
                        elif isinstance(block, str) and block.strip():
                            text_parts.append(block.strip())
                    if text_parts:
                        last_assistant_content = "\n".join(text_parts)
    except (OSError, IOError) as exc:
        log_error(f"Failed to read transcript for agent output at {transcript_path}: {exc}")

    return last_assistant_content


def extract_card_from_transcript(transcript_path: str) -> tuple[str, str] | None:
    """
    Parse the agent's transcript (JSONL) line by line to find the card number
    and session ID.

    Looks for:
    1. Injected card XML header from PreToolUse hook
    2. KANBAN CARD #N | Session: session-name header
    3. kanban CLI calls with card number and --session flag

    Returns (card_number_str, session_id) or None if not found.
    """
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                # Search through all string values in the entry for patterns
                text_to_search = _extract_text_from_entry(entry)
                for text in text_to_search:
                    # Try XML card pattern first (most specific from pretool hook)
                    m = _CARD_XML_PATTERN.search(text)
                    if m:
                        return (m.group(1), m.group(2))

                    # Try KANBAN CARD header pattern
                    m = _CARD_HEADER_PATTERN.search(text)
                    if m:
                        return (m.group(1), m.group(2))

                    # Try kanban CLI command pattern
                    m = _KANBAN_CMD_PATTERN.search(text)
                    if m:
                        return (m.group(1), m.group(2))
    except (OSError, IOError) as exc:
        log_error(f"Failed to read transcript at {transcript_path}: {exc}")
        return None

    return None


def detect_permission_stall(transcript_path: str) -> list[str]:
    """
    Scan the JSONL transcript for Bash permission denial signals.

    In Claude Code dontAsk mode, denied Bash commands produce tool_result
    entries whose content contains phrases like 'was automatically denied',
    'not allowed by your current permissions', or 'permission denied'.

    Returns a list of denied command descriptions (non-empty strings extracted
    near each denial), or an empty list if no denials are found or on error.
    Fails open: any exception is caught and an empty list is returned.
    """
    denied = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line, strict=False)
                except json.JSONDecodeError:
                    continue

                if not isinstance(entry, dict):
                    continue

                # Tool results appear as user-role messages in JSONL transcripts.
                # Filter to only user-role entries to avoid false positives from
                # assistant messages that discuss permissions in their reasoning.
                if entry.get("role") != "user":
                    continue

                content = entry.get("content", "")
                texts = _extract_text_from_entry(content)

                for text in texts:
                    if _PERMISSION_DENIAL_PATTERN.search(text):
                        # Extract a concise description: first non-empty line of the denial text
                        description = next(
                            (ln.strip() for ln in text.splitlines() if ln.strip()),
                            text[:120].strip(),
                        )
                        denied.append(description)
                        break  # one denial per entry is enough
    except Exception as exc:
        log_error(f"detect_permission_stall failed for {transcript_path}: {exc}")
        return []
    return denied


def _extract_text_from_entry(entry: dict | list | str, depth: int = 0) -> list[str]:
    """Recursively extract string values from a JSON entry, with depth limit."""
    if depth > 5:
        return []
    texts = []
    if isinstance(entry, str):
        texts.append(entry)
    elif isinstance(entry, dict):
        for v in entry.values():
            texts.extend(_extract_text_from_entry(v, depth + 1))
    elif isinstance(entry, list):
        for item in entry:
            texts.extend(_extract_text_from_entry(item, depth + 1))
    return texts


def detect_criteria_gaming(transcript_path: str) -> bool:
    """Detect whether an agent is gaming the AC review gate.

    The gaming pattern: after being blocked (AC review failure or unchecked
    criteria), the agent immediately re-runs `kanban criteria check` on the
    same criteria WITHOUT doing any real work first.

    Algorithm:
    1. Scan all JSONL entries to find the LAST block-feedback message
       (identified by _BLOCK_FEEDBACK_MARKERS phrases).
    2. After that message, scan assistant-role entries for:
       a. tool_use blocks naming a tool in _SUBSTANTIVE_TOOLS  → substantive work
       b. tool_use blocks for "Bash" whose input.command does NOT match
          _KANBAN_CRITERIA_BASH                               → substantive work
       c. tool_use blocks for "Bash" whose input.command matches
          _KANBAN_CRITERIA_BASH                               → criteria recheck
    3. Gaming = at least one criteria recheck found AND no substantive work.

    Fails open: any error returns False so normal hook flow is not interrupted.

    Args:
        transcript_path: Absolute path to the agent's JSONL transcript.

    Returns:
        True if gaming is detected, False otherwise (including on any error).
    """
    try:
        # --- Pass 1: load all entries and find the last block-feedback index ---
        entries: list[dict] = []
        try:
            with open(transcript_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line, strict=False)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict):
                        entries.append(entry)
        except (OSError, IOError) as exc:
            log_error(f"detect_criteria_gaming: failed to read transcript {transcript_path}: {exc}")
            return False

        if not entries:
            return False

        # Find the index of the LAST entry that contains a block-feedback marker.
        # Block-feedback is delivered as a "user" role message injected by the hook.
        last_feedback_index: int = -1
        for idx, entry in enumerate(entries):
            texts = _extract_text_from_entry(entry)
            for text in texts:
                if any(marker in text for marker in _BLOCK_FEEDBACK_MARKERS):
                    last_feedback_index = idx
                    break  # found a marker in this entry; move to next entry

        if last_feedback_index < 0:
            # No block-feedback message found — nothing to detect gaming against.
            return False

        log_info(
            f"detect_criteria_gaming: last block-feedback at entry index {last_feedback_index} "
            f"of {len(entries)} entries"
        )

        # --- Pass 2: scan entries AFTER the last feedback for tool_use blocks ---
        has_substantive_work = False
        has_criteria_recheck = False

        for entry in entries[last_feedback_index + 1:]:
            if entry.get("role") != "assistant":
                continue

            content = entry.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue

                tool_name: str = block.get("name", "")

                if tool_name in _SUBSTANTIVE_TOOLS:
                    has_substantive_work = True
                    log_info(f"detect_criteria_gaming: substantive tool '{tool_name}' found after feedback")
                    break  # one substantive tool is enough

                if tool_name.startswith("mcp__"):
                    has_substantive_work = True
                    log_info(f"detect_criteria_gaming: MCP tool '{tool_name}' found after feedback")
                    break  # one substantive tool is enough

                if tool_name == "Bash":
                    cmd: str = ""
                    tool_input = block.get("input", {})
                    if isinstance(tool_input, dict):
                        cmd = tool_input.get("command", "") or ""
                    if _KANBAN_CRITERIA_BASH.match(cmd):
                        has_criteria_recheck = True
                        log_info(f"detect_criteria_gaming: criteria recheck command found: {cmd[:80]!r}")
                    else:
                        # Non-kanban-criteria Bash command counts as substantive work.
                        has_substantive_work = True
                        log_info(f"detect_criteria_gaming: substantive Bash command found: {cmd[:80]!r}")
                        break

            if has_substantive_work:
                break  # no need to keep scanning

        gaming = has_criteria_recheck and not has_substantive_work
        log_info(
            f"detect_criteria_gaming: has_criteria_recheck={has_criteria_recheck} "
            f"has_substantive_work={has_substantive_work} → gaming={gaming}"
        )
        return gaming

    except Exception as exc:
        log_error(f"detect_criteria_gaming: unexpected error for {transcript_path}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Kanban CLI helpers
# ---------------------------------------------------------------------------

def run_kanban(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a kanban CLI command, capturing output."""
    cmd = ["kanban"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            log_info(f"kanban {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}")
        return result
    except subprocess.TimeoutExpired:
        log_error(f"kanban {' '.join(args)} timed out after {timeout}s")
        raise
    except FileNotFoundError:
        log_error("kanban CLI not found in PATH")


# ---------------------------------------------------------------------------
# macOS notification helpers
# ---------------------------------------------------------------------------

_STATE_EMOJI = {
    "doing": "🚂",      # todo→doing (Work Started)
    "review": "🔍",     # doing→review (In Review)
    "done": "✅",       # review→done (Done)
    "redo": "🔄",       # review→doing (Redo)
    "todo": "⏸️",       # doing→todo (Deferred)
    "canceled": "❌",   # any→canceled (Canceled)
}

_STATE_TITLE = {
    "doing": "Work Started",
    "review": "In Review",
    "done": "Done",
    "redo": "Redo",
    "todo": "Deferred",
    "canceled": "Canceled",
}

_STATE_SOUND = {
    "doing": "Pluck",        # Work Started — uplifting, positive energy
    "review": "Breeze",      # In Review — attention-grabbing pattern
    "done": "Pebble",        # Done — celebratory completion
    "redo": "Pluck",         # Redo — submarine alert suggests rework
    "todo": "Submerge",      # Deferred — subtle, gentle pause
    "canceled": "Mezzo",     # Canceled — low, final termination sound
}


def _truncate_intent(intent: str, max_len: int = 60) -> str:
    """Truncate intent to a short snippet for notifications."""
    intent = intent.replace("\n", " ").strip()
    if len(intent) <= max_len:
        return intent
    return intent[:max_len - 1].rstrip() + "\u2026"


def get_card_intent(card_number: str, session: str) -> str:
    """Fetch card intent from kanban show XML. Returns empty string on failure."""
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session], timeout=10)
        if result.returncode == 0:
            m = re.search(r"<intent>(.*?)</intent>", result.stdout, re.DOTALL)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return ""


def _get_tmux_context() -> str:
    """Get tmux session → window context string. Returns empty string if not in tmux."""
    tmux = os.environ.get("TMUX", "")
    tmux_pane = os.environ.get("TMUX_PANE", "")
    if not tmux or not tmux_pane:
        return ""
    try:
        session = subprocess.run(
            ["tmux", "display-message", "-t", tmux_pane, "-p", "#S"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        window = subprocess.run(
            ["tmux", "display-message", "-t", tmux_pane, "-p", "#W"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if session and window:
            return f"{session} \u2192 {window}"
    except Exception:
        pass
    return ""


def send_transition_notification(card_number: str, new_state: str, intent: str) -> None:
    """Send a macOS notification for a kanban state transition.

    Uses osascript to notify via Alacritty, same mechanism as bash hooks.
    Title: <emoji> <State Name>
    Body line 1: <tmux_session> → <tmux_window>
    Body line 2: #<N> — <card intent, truncated>

    Never raises — notification failure must not affect hook decisions.
    """
    try:
        emoji = _STATE_EMOJI.get(new_state, "")
        state_name = _STATE_TITLE.get(new_state, new_state.capitalize())
        title = f"{emoji} {state_name}" if emoji else state_name
        sound = _STATE_SOUND.get(new_state, "Glass")

        snippet = _truncate_intent(intent) if intent else f"card #{card_number}"
        card_line = f"#{card_number} \u2014 {snippet}"
        tmux_ctx = _get_tmux_context()
        body = f"{tmux_ctx}\n{card_line}" if tmux_ctx else card_line

        # Escape AppleScript string delimiters
        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
        safe_body = body.replace("\\", "\\\\").replace('"', '\\"')

        subprocess.run(
            [
                "osascript", "-e",
                f'tell application id "org.alacritty" to display notification '
                f'"{safe_body}" with title "{safe_title}" sound name "{sound}"',
            ],
            capture_output=True,
            timeout=5,
        )
        log_info(f"Sent transition notification: [{title}] {body}")
    except Exception as exc:
        log_error(f"send_transition_notification failed for card #{card_number} → {new_state}: {exc}")


def get_card_status(card_number: str, session: str) -> str | None:
    """Get the current column of a card. Returns column name or None on error."""
    try:
        result = run_kanban(["status", card_number, "--session", session])
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_card_type(card_number: str, session: str) -> str:
    """Get the card type (work, review, or research). Defaults to 'work'."""
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode == 0:
            m = re.search(r'type="(work|review|research)"', result.stdout)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "work"


def get_review_cycles(card_number: str, session: str) -> int:
    """Read the review_cycles count from the card XML."""
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode == 0:
            m = re.search(r'review-cycles="(\d+)"', result.stdout)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 0


# Prefix constant used to detect reviewer malfunction in process_subagent_stop
_REVIEWER_MALFUNCTION_PREFIX = "AC reviewer failed to evaluate any criteria"


def _extract_criteria_failures(card_number: str, session: str) -> str:
    """Read card XML and extract criteria that failed with their reasons.

    Returns a formatted string listing each failed criterion, or a fallback
    message if the card cannot be read.

    When the reviewer never called pass/fail on ANY criterion, returns a
    diagnostic prefixed with _REVIEWER_MALFUNCTION_PREFIX so callers can
    distinguish reviewer malfunction from legitimate work failures.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode != 0:
            return "Could not read card details to determine failure reasons."

        xml_output = result.stdout
        # Parse ALL <ac> elements to track their 1-based position, then report
        # only those with reviewer-met="fail" using their actual AC index.
        ac_pattern = re.compile(
            r'<ac\b([^>]*?)>(.*?)</ac>',
            re.DOTALL,
        )
        fail_pattern = re.compile(r'reviewer-met="fail"')
        reviewer_met_pattern = re.compile(r'reviewer-met="(pass|fail)"')
        reason_pattern = re.compile(r'reviewer-fail-reason="([^"]*)"')

        failures = []
        total_criteria = 0
        reviewer_interacted_count = 0
        for ac_index, match in enumerate(ac_pattern.finditer(xml_output), 1):
            total_criteria += 1
            attrs = match.group(1)
            if reviewer_met_pattern.search(attrs):
                reviewer_interacted_count += 1
            if not fail_pattern.search(attrs):
                continue
            criterion_text = match.group(2).strip()
            reason_match = reason_pattern.search(attrs)
            reason = reason_match.group(1) if reason_match else "no reason provided"
            failures.append(f"{ac_index}. [{criterion_text}]: {reason}")

        if failures:
            return "\n".join(failures)

        # Distinguish "reviewer found no failures" from "reviewer never interacted"
        if total_criteria > 0 and reviewer_interacted_count == 0:
            log_error(
                f"AC reviewer for card #{card_number} failed to call criteria pass/fail "
                f"on any of {total_criteria} criteria — reviewer produced no actionable output"
            )
            return (
                f"{_REVIEWER_MALFUNCTION_PREFIX} — 0/{total_criteria} criteria "
                f"received a pass/fail verdict. The reviewer ran but did not call "
                f"'kanban criteria pass' or 'kanban criteria fail' for any criterion. "
                f"This is a reviewer malfunction, not a work quality issue."
            )

        return "AC review did not pass, but no specific failure reasons were found on the card."

    except Exception as exc:
        log_error(f"Failed to extract criteria failures for card #{card_number}: {exc}")
        return "Could not determine failure reasons due to an error."


def _extract_criteria_failures_as_json(card_number: str, session: str) -> str | None:
    """Read card XML and return failed criteria as a JSON array string.

    Returns a JSON string of the form:
        [{"criterion": "<text>", "reason": "<why it failed>"}, ...]

    Returns None if the card cannot be read or no failures are found.
    Never raises.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode != 0:
            return None

        xml_output = result.stdout
        ac_pattern = re.compile(r'<ac\b([^>]*?)>(.*?)</ac>', re.DOTALL)
        fail_pattern = re.compile(r'reviewer-met="fail"')
        reason_pattern = re.compile(r'reviewer-fail-reason="([^"]*)"')

        failures = []
        for match in ac_pattern.finditer(xml_output):
            attrs = match.group(1)
            if not fail_pattern.search(attrs):
                continue
            criterion_text = match.group(2).strip()
            reason_match = reason_pattern.search(attrs)
            reason = reason_match.group(1) if reason_match else "no reason provided"
            failures.append({"criterion": criterion_text, "reason": reason})

        if not failures:
            return None

        return json.dumps(failures, ensure_ascii=False)

    except Exception as exc:
        log_error(f"Failed to extract criteria failures as JSON for card #{card_number}: {exc}")
        return None


def build_malfunction_retry_prompt(card_number: str, session: str, transcript_path: str) -> str:
    """Build a stripped-down prompt for malfunction retry AC review.

    Used when the first AC reviewer ran but never called pass or fail on any
    criterion. This prompt avoids inlining agent output (which may have
    confused the reviewer) and instead directs it to read the transcript file
    directly. Uses only pass/fail vocabulary and minimal instructions.
    """
    return f"""You are an AC reviewer for kanban card #{card_number} (session {session}).

The previous review attempt ran but never called pass or fail. You MUST call pass or fail for every criterion.

Step 1: Read the card:
  kanban show {card_number} --output-style=xml --session {session}

Step 2: Read the agent transcript for evidence:
  The agent transcript is at {transcript_path}. Read it to find the agent findings and work output.

Step 3: For each criterion, evaluate it against the evidence (files for work cards, transcript for review/research cards), then call exactly one of:
  - kanban criteria pass {card_number} <n> --session {session}
  - kanban criteria fail {card_number} <n> --reason '<why it failed>' --session {session}

Step 4: After every criterion has a pass or fail verdict, call:
  kanban done {card_number} '<one-sentence summary>' --session {session}

You MUST call pass or fail for EVERY criterion before calling done. Do not skip any.
"""


def _run_malfunction_retry(
    card_number: str,
    session: str,
    transcript_path: str,
    outer_session_id: str,
    working_directory: str,
) -> bool:
    """Run a single AC review pass as a malfunction retry.

    Uses build_malfunction_retry_prompt (stripped-down, transcript-based
    prompt) and the same subprocess pattern as run_inner_loop. Writes metrics
    to claudit DB with iteration=99 as a sentinel for malfunction retry.

    Returns True if the card reached done, False otherwise.
    Does NOT wrap in try/except — caller is responsible for exception handling.
    """
    log_info(f"Malfunction retry: launching single AC review pass for card #{card_number}")

    prompt = build_malfunction_retry_prompt(card_number, session, transcript_path)
    ac_reviewer_system_prompt = read_ac_reviewer_agent_definition()

    ac_env = {**os.environ, "KANBAN_AGENT": "ac-reviewer", "CLAUDIT_ROLE": "ac-reviewer"}

    claude_cmd = [
        "claude", "-p", "--model", "haiku", "--max-turns", str(CLAUDE_MAX_TURNS),
        "--system-prompt", ac_reviewer_system_prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions",
    ]

    result = subprocess.run(
        claude_cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
        env=ac_env,
    )

    if result.stderr.strip():
        log_info(f"Malfunction retry claude -p stderr: {result.stderr.strip()}")

    # Parse JSON output and write metrics with iteration=99 (sentinel)
    if result.stdout.strip():
        try:
            json_response = json.loads(result.stdout)
            usage = json_response.get("usage") or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
            cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)

            _claudit_write_ac_reviewer_metrics(
                outer_session_id=outer_session_id,
                kanban_session=session,
                card_number=card_number,
                working_directory=working_directory,
                iteration=99,  # sentinel for malfunction retry
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            log_error(f"Malfunction retry: failed to parse claude -p JSON output: {exc}")

    status = get_card_status(card_number, session)
    if status == "done":
        log_info(f"Malfunction retry: card #{card_number} reached done")
        return True

    log_info(f"Malfunction retry: card #{card_number} status after retry='{status}' — not done")
    return False


def get_all_criteria_numbers(card_number: str, session: str) -> list[int]:
    """Return 1-based index list of all acceptance criteria on a card.

    Reads the card XML and counts <ac> elements to produce a list like
    [1, 2, 3, ...].  Returns an empty list on any error.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode != 0:
            return []
        ac_count = len(re.findall(r'<ac\b', result.stdout))
        return list(range(1, ac_count + 1))
    except Exception as exc:
        log_error(f"get_all_criteria_numbers for card #{card_number}: {exc}")
        return []


def get_deferred_cards(session: str) -> list[str]:
    """Get list of card numbers in the todo column for this session."""
    try:
        result = run_kanban(["list", "--column", "todo", "--output-style=xml", "--session", session])
        if result.returncode == 0 and result.stdout.strip():
            # Extract card numbers from XML output
            return re.findall(r'num="(\d+)"', result.stdout)
    except Exception:
        pass
    return []


def format_deferred_notification(session: str) -> str:
    """Build deferred card notification string, or empty if none."""
    card_nums = get_deferred_cards(session)
    if card_nums:
        card_refs = ", ".join(f"#{n}" for n in card_nums)
        return f"\nDeferred cards awaiting action: {card_refs}"
    return ""


# ---------------------------------------------------------------------------
# Inner loop: Haiku AC review
# ---------------------------------------------------------------------------

def build_haiku_prompt(card_number: str, session: str, previous_context: str, agent_output: str = "", card_type: str = "work") -> str:
    """Build the prompt for the haiku AC reviewer.

    Verification strategy depends on card type:
    - work: evidence = filesystem (inspect files, run MoV commands)
    - review/research: evidence = agent output (verify findings were articulated)
    """
    previous_section = ""
    if previous_context:
        previous_section = f"""
Previous review context (accumulated from earlier passes — use this to avoid
re-checking criteria you already reviewed):
{previous_context}
"""

    is_findings_card = card_type in ("review", "research")

    agent_output_section = ""
    if agent_output:
        if is_findings_card:
            agent_output_section = f"""
Agent output (PRIMARY EVIDENCE — verify criteria against this):
---
{agent_output}
---
"""
        else:
            agent_output_section = f"""
Agent output (the sub-agent's final response — supplementary context):
---
{agent_output}
---

This is a work card. File inspection is primary evidence. Use the agent output
above as supplementary context only.
"""

    if is_findings_card:
        verification_step = f"""Step 2: For each acceptance criterion, verify it against the AGENT OUTPUT below.
This is a {card_type} card — the deliverable is the agent's findings/analysis.
- Read each criterion and its MoV
- Check whether the agent output satisfies what the MoV asks for"""
    else:
        verification_step = """Step 2: For each acceptance criterion, verify it by inspecting files, running
the Method of Verification (MoV) specified in the criterion text, or checking
whatever evidence is appropriate."""

    if is_findings_card:
        important_section = f"""IMPORTANT:
- Verify EVERY criterion. Do not skip any.
- Evidence source is the AGENT OUTPUT below — not the filesystem.
- The MoV tells you what to look for in the agent's output.
- Do NOT read source files to check if findings are "correct" — that re-does the {card_type}.
- CRITICAL — "assessed" ≠ "no defects found": The deliverable is the assessment itself.
  An agent that identifies HIGH-severity gaps has PASSED — finding deficiencies is success.
  Evaluate whether the agent COMPLETED and DELIVERED its assessment, not whether the
  assessed artifact is defect-free.
- Run kanban criteria pass/fail as you verify each criterion, not all at the end."""
    else:
        important_section = """IMPORTANT:
- Verify EVERY criterion. Do not skip any.
- Be thorough but efficient — max 2 file reads per criterion.
- Use the MoV in each criterion to guide your verification approach.
- Run kanban criteria pass/fail as you verify each criterion, not all at the end."""

    return f"""You are an AC reviewer for kanban card #{card_number} (session {session}).

Your job: Verify each acceptance criterion, then complete the card.

Step 1: Run this command to read the card:
  kanban show {card_number} --output-style=xml --session {session}

{verification_step}

{important_section}

Step 3: For each criterion you verify:
  - If it PASSES: kanban criteria pass {card_number} <n> --session {session}
  - If it FAILS: kanban criteria fail {card_number} <n> --reason '<why it failed>' --session {session}

Step 4: After all criteria have a pass or fail verdict, run:
  kanban done {card_number} '<one-sentence summary>' --session {session}

If kanban done fails (some criteria are unchecked or failed), that is expected.
Just ensure every criterion has been evaluated with pass or fail.
{agent_output_section}{previous_section}
"""


def read_ac_reviewer_agent_definition() -> str:
    """Read the ac-reviewer agent definition for use as system prompt.

    Same pattern as staff.bash: read agent definition, pass via --system-prompt.
    The file is deployed by Nix Home Manager (hms) and is guaranteed to exist.
    If missing, that is a deployment failure and should crash loudly.
    """
    return AC_REVIEWER_AGENT_PATH.read_text(encoding="utf-8")


def run_inner_loop(
    card_number: str,
    session: str,
    transcript_path: str = "",
    outer_session_id: str = "",
    working_directory: str = "",
) -> bool:
    """
    Run the inner AC review loop (max MAX_INNER_ITERATIONS iterations).

    Each iteration launches claude -p --model haiku to review criteria.
    After each iteration, checks if the card reached the done column.
    Token usage from each iteration is written to the claudit SQLite DB.

    Returns True if the card reached done, False otherwise.
    """
    accumulated_context = ""
    agent_output = extract_agent_output(transcript_path) if transcript_path else ""
    if agent_output:
        log_info(f"Extracted agent output for card #{card_number} ({len(agent_output)} chars)")

    # Detect card type to adjust verification strategy
    card_type = get_card_type(card_number, session)
    log_info(f"Card #{card_number} type: {card_type}")

    # Read ac-reviewer agent definition for use as system prompt
    # (same pattern as staff.bash: read agent definition, pass via --system-prompt)
    ac_reviewer_system_prompt = read_ac_reviewer_agent_definition()
    log_info("Loaded ac-reviewer agent definition as system prompt")

    for i in range(1, MAX_INNER_ITERATIONS + 1):
        log_info(f"Inner loop iteration {i}/{MAX_INNER_ITERATIONS} for card #{card_number}")

        prompt = build_haiku_prompt(card_number, session, accumulated_context, agent_output, card_type)

        try:
            # Set agent identity env vars so metrics identify this as ac-reviewer
            # (same pattern as staff.bash: KANBAN_AGENT + CLAUDIT_ROLE)
            ac_env = {**os.environ, "KANBAN_AGENT": "ac-reviewer", "CLAUDIT_ROLE": "ac-reviewer"}

            # Build claude command: load ac-reviewer agent definition as system prompt
            # (same mechanism as staff.bash loads staff-engineer via --system-prompt)
            # --output-format json enables structured response with usage stats
            claude_cmd = [
                "claude", "-p", "--model", "haiku", "--max-turns", str(CLAUDE_MAX_TURNS),
                "--system-prompt", ac_reviewer_system_prompt,
                "--output-format", "json",
                "--dangerously-skip-permissions",
            ]

            result = subprocess.run(
                claude_cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes per iteration
                env=ac_env,
            )
            iteration_stderr = result.stderr.strip()

            if iteration_stderr:
                log_info(f"claude -p stderr (iter {i}): {iteration_stderr}")

            # Parse JSON output and extract result text + token usage
            iteration_output = ""
            if result.stdout.strip():
                try:
                    json_response = json.loads(result.stdout)
                    iteration_output = json_response.get("result", "") or ""

                    # Extract token usage and write to claudit DB
                    usage = json_response.get("usage") or {}
                    input_tokens = int(usage.get("input_tokens", 0) or 0)
                    output_tokens = int(usage.get("output_tokens", 0) or 0)
                    cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
                    cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)

                    _claudit_write_ac_reviewer_metrics(
                        outer_session_id=outer_session_id,
                        kanban_session=session,
                        card_number=card_number,
                        working_directory=working_directory,
                        iteration=i,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read_tokens,
                        cache_write_tokens=cache_write_tokens,
                    )
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    log_error(f"Failed to parse claude -p JSON output on iter {i}: {exc}")
                    iteration_output = result.stdout.strip()

            accumulated_context += f"\n--- Pass {i} ---\n{iteration_output}\n"

        except subprocess.TimeoutExpired:
            log_error(f"claude -p timed out on iteration {i}")
            accumulated_context += f"\n--- Pass {i} ---\n[TIMED OUT]\n"
            continue
        except FileNotFoundError:
            # Let this propagate — caught by process_subagent_stop's except block
            # which surfaces a clear systemic error instead of burning redo cycles
            raise
        except Exception as exc:
            log_error(f"claude -p failed on iteration {i}: {exc}")
            accumulated_context += f"\n--- Pass {i} ---\n[ERROR: {exc}]\n"
            continue

        # Check if card reached done column
        status = get_card_status(card_number, session)
        if status == "done":
            log_info(f"Card #{card_number} reached done after {i} inner iteration(s)")
            return True

        # If card is not in review or done, something unexpected happened
        if status and status not in ("review", "doing", "done"):
            log_info(f"Card #{card_number} in unexpected status '{status}' — breaking inner loop")
            break

    return False


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------

def process_subagent_stop(payload: dict) -> dict:
    """
    Process a SubagentStop event.

    Steps:
    1. Identify card from transcript
    2. Call kanban review (hook responsibility, not agent's)
    3. Run inner AC review loop (haiku)
    4. Process result (allow/block)
    5. Append deferred card notification
    """
    transcript_path = payload.get("agent_transcript_path", "")
    outer_session_id = payload.get("session_id", "")
    working_directory = payload.get("cwd") or os.getcwd()

    if not transcript_path or not os.path.exists(transcript_path):
        log_info("No transcript path or file not found — allowing stop")
        return allow()

    # Step 1: Identify the card
    extracted = extract_card_from_transcript(transcript_path)
    if extracted is None:
        log_info("No kanban card found in transcript — allowing stop (not kanban-managed)")
        return allow()

    card_number, session = extracted
    log_info(f"Found card #{card_number} (session: {session})")

    # Check for permission-gate stall before doing anything else.
    # If the agent hit Bash auto-denials and the card is still doing (never completed),
    # short-circuit the retry loop — retrying won't help until permissions are granted.
    status_for_stall_check = get_card_status(card_number, session)
    if status_for_stall_check == "doing":
        denied_commands = detect_permission_stall(transcript_path)
        # Threshold >= 2: a single denial may be a one-off prompt issue;
        # two or more signals a systemic permission gap worth short-circuiting for.
        if len(denied_commands) >= 2:
            log_info(
                f"Permission stall detected for card #{card_number} — "
                f"{len(denied_commands)} denial(s) found in transcript"
            )
            denied_list = "\n".join(f"  - {cmd}" for cmd in denied_commands)
            message = (
                f"Card #{card_number} stalled due to permission gate(s). "
                f"The following Bash commands were automatically denied:\n\n"
                f"{denied_list}\n\n"
                f"Pre-register the required permissions via the perm CLI before re-launching:\n"
                f"  perm allow '<command-pattern>' --session {session}\n\n"
                f"Once permissions are granted, re-launch the agent to retry the card."
            )
            message += format_deferred_notification(session)
            return allow(message)

    # Step 2: Call kanban review (hook responsibility — agents no longer call this)
    status = get_card_status(card_number, session)
    if status is None:
        log_info(f"Could not get status for card #{card_number} — allowing stop")
        return allow()

    if status == "done":
        # Card already done (maybe by a previous hook run or manual intervention)
        message = f"Card #{card_number} is already done."
        message += format_deferred_notification(session)
        return allow(message)

    if status == "review":
        # Agent or a previous hook run already moved card to review — proceed to AC
        log_info(f"Card #{card_number} already in review — proceeding to AC review")
    elif status in ("doing", "todo"):
        # Anti-gaming check: only fires on 'doing' (retry scenario).
        # If the agent is retrying after a rejection but has done nothing but re-check
        # criteria (no Read/Grep/Edit/Write/Bash etc.), block immediately without
        # running the full AC review cycle.
        if status == "doing" and detect_criteria_gaming(transcript_path):
            log_info(
                f"Anti-gaming triggered for card #{card_number} — "
                "agent re-checked criteria without doing substantive work"
            )
            # Uncheck all criteria so the agent cannot coast on previously-checked ones.
            criteria_numbers = get_all_criteria_numbers(card_number, session)
            unchecked_count = 0
            for n in criteria_numbers:
                try:
                    run_kanban(["criteria", "uncheck", card_number, str(n), "--session", session])
                    unchecked_count += 1
                except Exception as uncheck_exc:
                    log_error(
                        f"anti-gaming: failed to uncheck criterion {n} for card #{card_number}: {uncheck_exc}"
                    )
            substantive_list = ", ".join(sorted(_SUBSTANTIVE_TOOLS))
            # Construct the uncheck status message based on whether unchecking succeeded
            if unchecked_count == len(criteria_numbers) and criteria_numbers:
                uncheck_status = (
                    "All criteria have been unchecked. Investigate each criterion, use the "
                    "appropriate tools to verify or fix the work, and only then run "
                    f"`kanban criteria check {card_number} <n> --session {session}`."
                )
            else:
                uncheck_status = "Criteria uncheck was attempted but may not have fully succeeded."
            gaming_reason = (
                f"Anti-gaming gate triggered for card #{card_number}.\n\n"
                f"You re-checked acceptance criteria after being blocked, but the hook "
                f"detected no substantive tool calls between the last rejection and this "
                f"stop. Simply re-checking criteria without doing real work bypasses the "
                f"quality gate and is not allowed.\n\n"
                f"Substantive tools (at least one required before re-checking criteria):\n"
                f"  {substantive_list}\n"
                f"  Bash commands that are NOT `kanban criteria ...` also count.\n\n"
                f"{uncheck_status}"
            )
            return block(gaming_reason)

        # Agent stopped without calling kanban review — call it ourselves
        log_info(f"Card #{card_number} is in '{status}' — hook calling kanban review")
        review_result = run_kanban(["review", card_number, "--session", session])
        if review_result.returncode != 0:
            # kanban review failed — unchecked criteria exist. Block the agent
            # with the error so it can investigate, fix, and re-check.
            review_error = review_result.stderr.strip() or review_result.stdout.strip()
            log_info(f"kanban review failed for card #{card_number}: {review_error}")
            reason = (
                f"kanban review failed for card #{card_number}:\n\n"
                f"{review_error}\n\n"
                f"You have unchecked acceptance criteria. Do NOT blindly check them off — "
                f"investigate each unchecked criterion, do the work to satisfy it, verify "
                f"your fix is correct, and only THEN run `kanban criteria check`. "
                f"The SubagentStop hook will call `kanban review` again automatically "
                f"when you stop."
            )
            return block(reason)
        log_info(f"kanban review succeeded for card #{card_number} — proceeding to AC review")
        # Notify: doing→review (fetch intent once and cache for reuse below)
        intent = get_card_intent(card_number, session)
        send_transition_notification(card_number, "review", intent)
    else:
        # Card in unexpected status (canceled, etc.) — allow stop
        log_info(f"Card #{card_number} in unexpected status '{status}' — allowing stop")
        message = f"Card #{card_number} is in '{status}' — cannot proceed with AC review."
        message += format_deferred_notification(session)
        return allow(message)

    # Step 3: Inner loop — Haiku AC verification
    log_info(f"Starting AC review inner loop for card #{card_number}")
    try:
        card_done = run_inner_loop(
            card_number,
            session,
            transcript_path,
            outer_session_id=outer_session_id,
            working_directory=working_directory,
        )
    except Exception as exc:
        log_error(f"AC review inner loop crashed for card #{card_number}: {exc}\n{traceback.format_exc()}")
        try:
            agent_output = extract_agent_output(transcript_path) if transcript_path else ""
        except Exception:
            agent_output = ""
        agent_excerpt = (agent_output[:500] + "...") if len(agent_output) > 500 else agent_output
        message = (
            f"Card #{card_number} AC review CRASHED — the hook encountered an unhandled error "
            f"during AC review. Card is stranded in 'review' status. "
            f"Staff engineer must intervene manually.\n\n"
            f"Error: {exc}"
        )
        if agent_excerpt:
            message += f"\n\nAgent output excerpt:\n{agent_excerpt}"
        message += format_deferred_notification(session)
        return allow(message)

    # Step 4: Process result
    # Reuse the cached intent fetched at the review transition above.
    # For cards that arrived already in 'review' (skipped the doing→review path),
    # intent may be unset — fetch it lazily only when needed.
    if card_done:
        # Notify: review→done
        card_intent = intent if 'intent' in dir() else get_card_intent(card_number, session)
        send_transition_notification(card_number, "done", card_intent)
        message = f"Card #{card_number} AC review passed — card completed."
        message += format_deferred_notification(session)
        return allow(message)

    # Re-check status — inner loop may have succeeded but returned False
    # (e.g. transient status check failure while haiku actually called kanban done)
    status = get_card_status(card_number, session)
    if status == "done":
        log_info(f"Card #{card_number} reached done (detected on re-check after inner loop)")
        # Notify: review→done (reuse cached intent)
        card_intent = intent if 'intent' in dir() else get_card_intent(card_number, session)
        send_transition_notification(card_number, "done", card_intent)
        message = f"Card #{card_number} AC review passed — card completed."
        message += format_deferred_notification(session)
        return allow(message)

    # Card not done after inner loop — check review cycles
    review_cycles = get_review_cycles(card_number, session)
    log_info(f"Card #{card_number} AC review failed — review_cycles={review_cycles}")

    if review_cycles >= MAX_OUTER_CYCLES:
        # Max cycles reached — allow stop, staff handles manually
        message = (
            f"Card #{card_number} AC review failed after {review_cycles} review cycle(s). "
            f"Max cycles ({MAX_OUTER_CYCLES}) reached — requires manual intervention by staff engineer."
        )
        message += format_deferred_notification(session)
        return allow(message)

    # Under max cycles — redo the card and block the agent
    # Read the card to get actual criteria failure reasons from the AC reviewer
    failure_details = _extract_criteria_failures(card_number, session)

    # If the reviewer itself malfunctioned (never called pass/fail on any criterion),
    # don't redo — the sub-agent's work may be correct, retrying won't fix a reviewer
    # issue. Allow stop with diagnostic so staff can intervene.
    if failure_details.startswith(_REVIEWER_MALFUNCTION_PREFIX):
        log_info(
            f"Reviewer malfunction for card #{card_number} — "
            f"attempting malfunction retry before falling through to allow-stop"
        )
        try:
            retry_succeeded = _run_malfunction_retry(
                card_number=card_number,
                session=session,
                transcript_path=transcript_path,
                outer_session_id=outer_session_id,
                working_directory=working_directory,
            )
            if retry_succeeded:
                # Notify: review→done (malfunction retry path) — reuse cached intent
                intent_for_retry_done = intent if 'intent' in dir() else get_card_intent(card_number, session)
                send_transition_notification(card_number, "done", intent_for_retry_done)
                message = f"Card #{card_number} AC review passed on malfunction retry — card completed."
                message += format_deferred_notification(session)
                return allow(message)
            log_info(
                f"Malfunction retry did not complete card #{card_number} — "
                f"falling through to allow-stop diagnostic"
            )
        except Exception as retry_exc:
            log_error(
                f"Malfunction retry crashed for card #{card_number}: {retry_exc}\n"
                f"{traceback.format_exc()}"
            )

        # Retry failed or crashed — fall through to existing allow-stop diagnostic
        log_error(
            f"Reviewer malfunction for card #{card_number} — "
            f"allowing stop for staff intervention instead of redo"
        )
        agent_output = extract_agent_output(transcript_path) if transcript_path else ""
        agent_excerpt = (agent_output[:500] + "...") if len(agent_output) > 500 else agent_output
        message = (
            f"Card #{card_number} AC reviewer malfunction — the reviewer ran but never "
            f"called criteria pass/fail on any criterion. The sub-agent's work may be "
            f"correct. Staff engineer should review manually or re-run AC review.\n\n"
            f"Reviewer diagnostic: {failure_details}"
        )
        if agent_excerpt:
            message += f"\n\nAgent output excerpt:\n{agent_excerpt}"
        message += format_deferred_notification(session)
        return allow(message)

    # Check card status before attempting redo — if it's already in a terminal state, skip redo
    status_before_redo = get_card_status(card_number, session)
    if status_before_redo in ("done", "canceled"):
        message = f"Card #{card_number} is already {status_before_redo}."
        message += format_deferred_notification(session)
        return allow(message)

    # Capture rejection reasons as JSON BEFORE kanban redo clears the fail reasons.
    # The kanban CLI's redo command clears reviewer_fail_reason on each criterion,
    # so this must happen before the redo call below.
    rejection_reasons_json = _extract_criteria_failures_as_json(card_number, session)

    # Run kanban redo to send card back to doing (increments review_cycles)
    redo_result = run_kanban(["redo", card_number, "--session", session])
    if redo_result.returncode != 0:
        log_error(f"kanban redo #{card_number} failed: {redo_result.stderr.strip()}")
        # If redo fails, allow stop — don't block agent in a broken state
        message = f"Card #{card_number} AC review failed but kanban redo also failed. Needs manual intervention."
        message += format_deferred_notification(session)
        return allow(message)

    # Notify: review→doing (redo) — reuse cached intent
    card_intent_for_redo = intent if 'intent' in dir() else get_card_intent(card_number, session)
    send_transition_notification(card_number, "redo", card_intent_for_redo)

    # Stamp the rejection reasons onto the redo event row the kanban CLI just inserted.
    if rejection_reasons_json is not None:
        _claudit_write_redo_rejection_reasons(
            card_number=card_number,
            kanban_session=session,
            rejection_reasons_json=rejection_reasons_json,
        )

    # Block the agent with failure details
    reason = (
        f"AC review failed for card #{card_number} "
        f"(cycle {review_cycles + 1}/{MAX_OUTER_CYCLES}). "
        f"The following criteria failed:\n\n{failure_details}"
    )
    system_message = (
        f"The AC reviewer found issues with your work. "
        f"Investigate each failed criterion, fix the underlying issue, verify your fix "
        f"is correct, and run `kanban criteria check {card_number} <n> --session {session}` "
        f"for each criterion you fix. The SubagentStop hook will call `kanban review` "
        f"automatically when you stop — do NOT call it yourself."
    )
    return block(reason, system_message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip if running inside a Burns/Ralph session
    if os.environ.get("BURNS_SESSION") == "1":
        print(json.dumps(allow()))
        return

    # Read the hook payload from stdin
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps(allow()))
        return

    try:
        payload = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        log_error(f"JSON decode error: {exc}")
        print(json.dumps(allow()))
        return

    result = process_subagent_stop(payload)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail open — never block agent stop due to hook failure
        log_error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
        print(json.dumps({"decision": "allow"}))
    sys.exit(0)
