#!/usr/bin/env python3
"""
kanban-subagent-stop-hook: SubagentStop hook that implements the programmatic MoV verification system.

Triggered when any sub-agent finishes execution. Parses the agent's transcript
to find the associated kanban card, then runs programmatic MoV commands for each
criterion. If all criteria pass, the card is marked done. If criteria fail and
review_cycles < 3, the agent is blocked with failure details so it can fix and
retry (outer loop). After 3 cycles, the agent is allowed to stop with a failure
summary for staff.

All AC must be programmatic (mov_type: "programmatic" with non-empty mov_commands).
Any criterion that is not programmatic is treated as invalid and auto-failed with
the message "invalid AC: no programmatic verification provided".

Output format (SubagentStop hook):
    {"decision": "allow"}  — let the agent stop
    {"decision": "block", "reason": "..."}  — send agent back with feedback

Fails open: any error results in allowing the agent to stop unchanged.

Skip condition: BURNS_SESSION=1 env var means Ralph is running — skip AC review.
"""

import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import traceback
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
MAX_OUTER_CYCLES = 3

# ---------------------------------------------------------------------------
# Claudit DB integration — write redo rejection reasons
# ---------------------------------------------------------------------------

_CLAUDIT_DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"

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

_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB cap before rotation


def _rotate_log_if_needed(path: Path) -> None:
    """Rotate path → path.1 when the file exceeds _LOG_MAX_BYTES. Never raises."""
    try:
        if path.exists() and path.stat().st_size >= _LOG_MAX_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            path.rename(rotated)
    except Exception:
        pass


def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises.

    Rotates the log file to <path>.1 when it exceeds _LOG_MAX_BYTES,
    then starts a fresh file (one backup generation kept).
    """
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(ERROR_LOG_PATH)
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
    Rotates the log file to <path>.1 when it exceeds _LOG_MAX_BYTES,
    then starts a fresh file (one backup generation kept).
    """
    try:
        INFO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(INFO_LOG_PATH)
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
        # Size guard: skip gaming detection for very large transcripts to avoid
        # spiking Python memory usage (50 MB transcript → ~200-300 MB in-memory).
        # Fail open: a large transcript is unlikely to be gaming anyway.
        _TRANSCRIPT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
        try:
            transcript_size = Path(transcript_path).stat().st_size
            if transcript_size > _TRANSCRIPT_MAX_BYTES:
                log_info(
                    f"detect_criteria_gaming: transcript too large "
                    f"({transcript_size} bytes > {_TRANSCRIPT_MAX_BYTES}) — skipping gaming check"
                )
                return False
        except OSError:
            pass  # file stat failure is non-fatal; proceed to load attempt

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

            # Two-level break pattern: the inner `break` above exits the content
            # block loop for *this* entry. This outer check exits the entry loop
            # entirely once substantive work is confirmed — no need to scan further.
            if has_substantive_work:
                break

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
    """Run a kanban CLI command, capturing output.

    Always returns a CompletedProcess — never returns None, never re-raises.
    On TimeoutExpired: returns a synthetic result with returncode=124 and a
    timeout message in stderr (consistent with GNU timeout's exit code).
    On FileNotFoundError: returns a synthetic result with returncode=127 and
    a "kanban not found" message in stderr (consistent with shell exit code
    for command-not-found).
    """
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
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=124,
            stdout="",
            stderr=f"kanban {' '.join(args)} timed out after {timeout}s",
        )
    except FileNotFoundError:
        log_error("kanban CLI not found in PATH")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=127,
            stdout="",
            stderr="kanban: command not found",
        )


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
    "doing": "Purr",         # Work Started — uplifting, positive energy
    "review": "Blow",        # In Review — attention-grabbing pattern
    "done": "Hero",          # Done — celebratory completion
    "redo": "Morse",         # Redo — submarine alert suggests rework
    "todo": "Pop",           # Deferred — subtle, gentle pause
    "canceled": "Bottle",    # Canceled — low, final termination sound
}


def _truncate_intent(intent: str, max_len: int = 60) -> str:
    """Truncate intent to a short snippet for notifications."""
    intent = intent.replace("\n", " ").strip()
    if len(intent) <= max_len:
        return intent
    return intent[:max_len - 1].rstrip() + "\u2026"


def get_card_intent(card_number: str, session: str) -> str:
    """Fetch card intent from kanban show XML. Returns empty string on failure.

    Decodes XML/HTML entities (e.g., &amp;#x27; → ', &amp; → &) from the intent text.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session], timeout=10)
        if result.returncode == 0:
            m = re.search(r"<intent>(.*?)</intent>", result.stdout, re.DOTALL)
            if m:
                encoded_intent = m.group(1).strip()
                # Decode XML/HTML entities: &amp;#x27; → ', &amp; → &, &lt; → <, etc.
                return html.unescape(encoded_intent)
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


# Prefix constant used to detect MoV no-results condition in process_subagent_stop
_MOV_NO_RESULTS_PREFIX = "Hook ran MoV commands but no criteria reached pass/fail state"


def _extract_criteria_failures(card_number: str, session: str) -> str:
    """Read card XML and extract criteria that failed with their reasons.

    Returns a formatted string listing each failed criterion, or a fallback
    message if the card cannot be read.

    When no criterion received a pass/fail verdict, returns a
    diagnostic prefixed with _MOV_NO_RESULTS_PREFIX so callers can
    distinguish this condition from legitimate work failures.
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
            inner_text = match.group(2)
            # Strip <movCommands>...</movCommands> subtree so programmatic criteria don't
            # pollute the reason hint with XML noise (mirrors get_card_criteria() stripping).
            mov_commands_match = re.search(r'<movCommands>.*?</movCommands>', inner_text, re.DOTALL)
            if mov_commands_match:
                criterion_text = inner_text[:mov_commands_match.start()].strip()
            else:
                criterion_text = inner_text.strip()
            reason_match = reason_pattern.search(attrs)
            reason = reason_match.group(1) if reason_match else "no reason provided"
            failures.append(f"{ac_index}. [{criterion_text}]: {reason}")

        if failures:
            return "\n".join(failures)

        # Distinguish "hook found no failures" from "hook never set pass/fail"
        if total_criteria > 0 and reviewer_interacted_count == 0:
            log_error(
                f"Hook for card #{card_number} ran MoV commands but no criteria reached pass/fail "
                f"on any of {total_criteria} criteria — hook produced no actionable output"
            )
            return (
                f"{_MOV_NO_RESULTS_PREFIX} — 0/{total_criteria} criteria "
                f"received a pass/fail verdict. "
                f"Hook ran MoV commands but no criteria reached pass/fail state."
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


# ---------------------------------------------------------------------------
# Programmatic MoV execution (hook-side reviewer dispatch)
# ---------------------------------------------------------------------------

# Exit codes that indicate MoV tooling/infrastructure failure (not work failure).
# These are treated as mov_error: no pass/fail, structured diagnostic emitted.
# exit 2 = bash syntax error at runtime (e.g. unclosed brackets, invalid substitutions).
# This matches kanban.py's cmd_criteria_check classification (line 1697: treats 127, 126, 2
# as mov_error). Without exit 2 here, a MoV authoring bug surfaces to the agent as a work
# failure — the agent wastes a retry cycle chasing a phantom deficiency.
_MOV_ERROR_EXIT_CODES = frozenset([126, 127, 124, 2])


def get_git_root() -> str:
    """Return the git repository root for use as cwd during MoV execution.

    Uses git rev-parse --show-toplevel. Falls back to the current working
    directory if the git command fails (e.g. not in a git repo).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            root = result.stdout.strip()
            if root:
                return root
    except Exception as exc:
        log_error(f"get_git_root: git rev-parse failed: {exc}")
    return os.getcwd()


def get_card_criteria(card_number: str, session: str) -> list[dict]:
    """Load card criteria as structured dicts from kanban show XML output.

    Each returned dict has at minimum:
      - index (int): 1-based criterion position
      - text (str): criterion statement
      - mov_type (str): "programmatic" or "semantic" (defaults to "semantic" if absent)
      - mov_commands (list[dict]): list of {cmd, timeout} for programmatic criteria (v5 schema)
      - agent_met (bool): whether the agent checked this criterion
      - reviewer_met (str | None): "pass", "fail", or None

    Parses the v5 <movCommands><command cmd="..." timeout="..."/>...</movCommands> subtree.
    v4 singular mov-command/mov-timeout attributes are not supported.

    Returns an empty list on any error.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode != 0:
            log_error(f"get_card_criteria: kanban show failed for card #{card_number}")
            return []

        xml_output = result.stdout
        # Match <ac ...> ... </ac> blocks, capturing attributes and full inner content
        ac_pattern = re.compile(r'<ac\b([^>]*?)>(.*?)</ac>', re.DOTALL)
        # Match <command cmd="..." timeout="..."/> entries inside <movCommands>
        mov_cmd_pattern = re.compile(r'<command\s[^>]*cmd="([^"]*)"[^>]*timeout="([^"]*)"[^>]*/>')
        criteria = []
        for idx, match in enumerate(ac_pattern.finditer(xml_output), 1):
            attrs_str = match.group(1)
            inner = match.group(2)

            def _attr(name: str, default: str = "") -> str:
                m = re.search(rf'{re.escape(name)}="([^"]*)"', attrs_str)
                return html.unescape(m.group(1)) if m else default

            mov_type = _attr("mov-type") or "unknown"

            agent_met_str = _attr("agent-met") or "false"
            agent_met = agent_met_str.lower() == "true"

            reviewer_met_str = _attr("reviewer-met") or ""
            reviewer_met: str | None = reviewer_met_str if reviewer_met_str in ("pass", "fail") else None

            # Parse v5 <movCommands> subtree from inner content
            mov_commands: list[dict] = []
            mov_commands_match = re.search(r'<movCommands>(.*?)</movCommands>', inner, re.DOTALL)
            if mov_commands_match:
                mov_commands_inner = mov_commands_match.group(1)
                for cmd_match in mov_cmd_pattern.finditer(mov_commands_inner):
                    cmd_str = html.unescape(cmd_match.group(1))
                    timeout_str = cmd_match.group(2)
                    try:
                        timeout_val = int(timeout_str)
                    except ValueError:
                        timeout_val = 30
                    mov_commands.append({"cmd": cmd_str, "timeout": timeout_val})

            # Extract criterion text: everything in inner before <movCommands> (or all of inner)
            if mov_commands_match:
                text = inner[:mov_commands_match.start()].strip()
            else:
                text = inner.strip()

            criteria.append({
                "index": idx,
                "text": text,
                "mov_type": mov_type,
                "mov_commands": mov_commands,
                "agent_met": agent_met,
                "reviewer_met": reviewer_met,
            })

        return criteria

    except Exception as exc:
        log_error(f"get_card_criteria for card #{card_number}: {exc}")
        return []


def run_programmatic_mov(
    criterion: dict,
    card_number: str,
    session: str,
    git_root: str,
) -> str | None:
    """Execute a programmatic MoV criterion by iterating its mov_commands array.

    Iterates mov_commands in array order. Short-circuits on the first non-zero exit,
    recording which command failed (by index) along with its stdout/stderr.

    Exit code classification per command:
      - 0: continue to next command (or pass criterion if last command)
      - 127/126/124: mov_error — emit structured diagnostic, leave reviewer_met as None
      - other nonzero: kanban criteria fail with captured output as reason

    Returns a mov_error diagnostic string if any command produced a tooling error,
    or None if the criterion was passed or failed cleanly.
    """
    idx = criterion["index"]
    mov_commands = criterion.get("mov_commands") or []

    if not mov_commands:
        log_info(
            f"run_programmatic_mov: card #{card_number} criterion {idx}: "
            f"no mov_commands — skipping"
        )
        return None

    for cmd_idx, cmd_entry in enumerate(mov_commands):
        mov_command = cmd_entry.get("cmd", "")
        mov_timeout = cmd_entry.get("timeout", 30)

        log_info(
            f"run_programmatic_mov: card #{card_number} criterion {idx} "
            f"command[{cmd_idx}]={mov_command!r} timeout={mov_timeout}s cwd={git_root!r}"
        )

        try:
            # shell=True is required: MoV commands are shell expressions (pipes, redirection,
            # compound tests). Commands are coordinator-authored and stored in card XML —
            # not user-supplied at runtime. Validate at card-authoring time.
            proc = subprocess.run(
                mov_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=mov_timeout,
                cwd=git_root,
                env={**os.environ},
            )
            exit_code = proc.returncode
            stdout_out = proc.stdout.strip()
            stderr_out = proc.stderr.strip()
        except subprocess.TimeoutExpired:
            # Treat timeout as exit code 124 (same as GNU timeout convention)
            log_error(
                f"run_programmatic_mov: card #{card_number} criterion {idx} "
                f"command[{cmd_idx}] timed out after {mov_timeout}s"
            )
            diagnostic = (
                f"\n=== MoV ERROR (criterion {idx}, card {card_number}) ===\n"
                f"Failed command index: {cmd_idx}\n"
                f"Command: {mov_command}\n"
                f"Exit code: 124 (timeout after {mov_timeout}s)\n"
                f"Stderr: (timeout — no output captured)\n"
                f"Stdout: (timeout — no output captured)\n"
                f"This is likely an MoV bug, not an agent work failure. "
                f"Coordinator should review.\n"
                f"=== END ==="
            )
            return diagnostic
        except Exception as exc:
            log_error(
                f"run_programmatic_mov: card #{card_number} criterion {idx} "
                f"command[{cmd_idx}] subprocess error: {exc}"
            )
            diagnostic = (
                f"\n=== MoV ERROR (criterion {idx}, card {card_number}) ===\n"
                f"Failed command index: {cmd_idx}\n"
                f"Command: {mov_command}\n"
                f"Exit code: (subprocess error — command could not be launched)\n"
                f"Stderr: {exc}\n"
                f"Stdout: \n"
                f"This is likely an MoV bug, not an agent work failure. "
                f"Coordinator should review.\n"
                f"=== END ==="
            )
            return diagnostic

        log_info(
            f"run_programmatic_mov: card #{card_number} criterion {idx} "
            f"command[{cmd_idx}]: exit_code={exit_code} "
            f"stdout={stdout_out[:120]!r} stderr={stderr_out[:120]!r}"
        )

        if exit_code == 0:
            # This command passed — continue to next command in array
            continue

        if exit_code in _MOV_ERROR_EXIT_CODES:
            diagnostic = (
                f"\n=== MoV ERROR (criterion {idx}, card {card_number}) ===\n"
                f"Failed command index: {cmd_idx}\n"
                f"Command: {mov_command}\n"
                f"Exit code: {exit_code}\n"
                f"Stderr: {stderr_out or '(empty)'}\n"
                f"Stdout: {stdout_out or '(empty)'}\n"
                f"This is likely an MoV bug, not an agent work failure. "
                f"Coordinator should review.\n"
                f"=== END ==="
            )
            log_info(
                f"run_programmatic_mov: card #{card_number} criterion {idx} "
                f"command[{cmd_idx}] mov_error (exit {exit_code}) — short-circuiting"
            )
            return diagnostic

        # Other nonzero — work failure; short-circuit
        combined_output = "\n".join(filter(None, [stderr_out, stdout_out])) or f"exit {exit_code}"
        run_kanban([
            "criteria", "fail", card_number, str(idx),
            "--reason", combined_output[:500],
            "--session", session,
        ])
        log_info(
            f"run_programmatic_mov: card #{card_number} criterion {idx} "
            f"command[{cmd_idx}] FAILED (exit {exit_code}) — short-circuiting"
        )
        return None

    # All commands passed
    run_kanban(["criteria", "pass", card_number, str(idx), "--session", session])
    log_info(
        f"run_programmatic_mov: card #{card_number} criterion {idx} PASSED "
        f"(all {len(mov_commands)} command(s) exited 0)"
    )
    return None


def run_programmatic_criteria(
    card_number: str,
    session: str,
    criteria: list[dict],
    git_root: str,
) -> list[str]:
    """Execute all programmatic criteria for a card and return any mov_error diagnostics.

    Only processes criteria where mov_type == "programmatic" and mov_commands is non-empty.
    Skips criteria already reviewed (reviewer_met is not None).
    Non-programmatic criteria are auto-failed by `run_inner_loop` before this function is called.

    Returns a list of mov_error diagnostic strings (may be empty).
    """
    programmatic = [
        c for c in criteria
        if c.get("mov_type") == "programmatic" and c.get("mov_commands")
    ]
    log_info(
        f"run_programmatic_criteria: card #{card_number} has "
        f"{len(programmatic)} programmatic criterion/criteria to evaluate"
    )

    mov_errors: list[str] = []
    for criterion in programmatic:
        if criterion.get("reviewer_met") is not None:
            log_info(
                f"run_programmatic_criteria: card #{card_number} criterion "
                f"{criterion['index']} already reviewed ({criterion['reviewer_met']}) — skipping"
            )
            continue
        diagnostic = run_programmatic_mov(criterion, card_number, session, git_root)
        if diagnostic is not None:
            mov_errors.append(diagnostic)

    return mov_errors


def format_deferred_notification(session: str) -> str:
    """Build deferred card notification string, or empty if none."""
    card_nums = get_deferred_cards(session)
    if card_nums:
        card_refs = ", ".join(f"#{n}" for n in card_nums)
        return f"\nDeferred cards awaiting action: {card_refs}"
    return ""


# ---------------------------------------------------------------------------
# Inner loop: programmatic AC review
# ---------------------------------------------------------------------------

def run_inner_loop(
    card_number: str,
    session: str,
    transcript_path: str = "",
    outer_session_id: str = "",
    working_directory: str = "",
) -> tuple[bool, list[str]]:
    """
    Run the AC review loop — programmatic criteria only.

    Dispatch flow:
    1. Load card criteria. Any criterion that is not programmatic (mov_type !=
       "programmatic" or missing mov_commands) is treated as invalid AC and
       auto-failed with the message "invalid AC: no programmatic verification
       provided".
    2. For each valid programmatic criterion: run each command in mov_commands via
       subprocess, classify exit code, call kanban criteria pass/fail (or emit
       mov_error diagnostic).
    3. Attempt kanban done directly (programmatic-only path — no Haiku LLM).

    Returns (card_done: bool, mov_error_diagnostics: list[str]).
    mov_error_diagnostics contains structured diagnostic blocks for exit codes
    127/126/124 — these indicate MoV tooling failures, not work failures.
    Callers should surface them to the coordinator.
    """
    # Resolve git root once — used as cwd for all programmatic MoV executions
    git_root = get_git_root()
    log_info(f"run_inner_loop: git root for MoV execution: {git_root!r}")

    # --- Step 1: Load criteria and flag invalid (non-programmatic) AC ---
    criteria = get_card_criteria(card_number, session)
    valid_criteria = []
    invalid_count = 0
    for c in criteria:
        if c.get("mov_type") == "programmatic" and c.get("mov_commands"):
            valid_criteria.append(c)
        else:
            # Auto-fail: no programmatic verification provided
            idx = c["index"]
            log_info(
                f"run_inner_loop: card #{card_number} criterion {idx} "
                f"is invalid AC (mov_type={c.get('mov_type')!r}, "
                f"mov_commands={c.get('mov_commands')!r}) — auto-failing"
            )
            run_kanban([
                "criteria", "fail", card_number, str(idx),
                "--reason", "invalid AC: no programmatic verification provided",
                "--session", session,
            ])
            invalid_count += 1

    if invalid_count:
        log_info(
            f"run_inner_loop: card #{card_number} — "
            f"{invalid_count} invalid AC auto-failed"
        )

    log_info(
        f"run_inner_loop: card #{card_number} — "
        f"{len(valid_criteria)} valid programmatic criterion/criteria to evaluate"
    )

    # --- Step 2: Run programmatic criteria ---
    mov_error_diagnostics: list[str] = []
    if valid_criteria:
        mov_error_diagnostics = run_programmatic_criteria(
            card_number, session, valid_criteria, git_root
        )
        if mov_error_diagnostics:
            log_info(
                f"run_inner_loop: card #{card_number} has "
                f"{len(mov_error_diagnostics)} mov_error diagnostic(s)"
            )

    # --- Step 3: Attempt kanban done ---
    log_info(
        f"run_inner_loop: card #{card_number} — "
        f"attempting kanban done after programmatic MoV evaluation"
    )
    done_result = run_kanban(
        ["done", card_number, "Programmatic MoV criteria verified by hook", "--session", session]
    )
    if done_result.returncode == 0:
        log_info(f"run_inner_loop: card #{card_number} reached done")
        return True, mov_error_diagnostics
    # kanban done failed (some criteria still not passing) — signal failure
    log_info(
        f"run_inner_loop: card #{card_number} kanban done failed: "
        f"{done_result.stderr.strip() or done_result.stdout.strip()}"
    )
    return False, mov_error_diagnostics


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------

def process_subagent_stop(payload: dict) -> dict:
    """
    Process a SubagentStop event.

    Steps:
    1. Identify card from transcript
    2. Call kanban review (hook responsibility, not agent's)
    3. Run inner AC review loop (programmatic-only — no LLM)
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

    # Step 3: Inner loop — programmatic MoV dispatch
    log_info(f"Starting AC review inner loop for card #{card_number}")
    mov_error_diagnostics: list[str] = []
    try:
        card_done, mov_error_diagnostics = run_inner_loop(
            card_number,
            session,
            transcript_path,
            outer_session_id=outer_session_id,
            working_directory=working_directory,
        )
    except Exception as exc:
        log_error(f"AC review inner loop crashed for card #{card_number}: {exc}\n{traceback.format_exc()}")
        message = (
            f"Card #{card_number} AC review CRASHED — the hook encountered an unhandled error "
            f"during AC review. Card is stranded in 'review' status. "
            f"Staff engineer must intervene manually.\n\n"
            f"Error: {exc}"
        )
        message += format_deferred_notification(session)
        return allow(message)

    # Step 4: Process result
    # Reuse the cached intent fetched at the review transition above.
    # For cards that arrived already in 'review' (skipped the doing→review path),
    # intent may be unset — fetch it lazily only when needed.
    if card_done:
        message = f"Card #{card_number} AC review passed — card completed."
        if mov_error_diagnostics:
            message += "\n" + "\n".join(mov_error_diagnostics)
        message += format_deferred_notification(session)
        return allow(message)

    # Re-check status — inner loop may have succeeded but returned False
    # (e.g. transient status check failure while the hook actually called kanban done)
    status = get_card_status(card_number, session)
    if status == "done":
        log_info(f"Card #{card_number} reached done (detected on re-check after inner loop)")
        message = f"Card #{card_number} AC review passed — card completed."
        if mov_error_diagnostics:
            message += "\n" + "\n".join(mov_error_diagnostics)
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
        if mov_error_diagnostics:
            message += "\n" + "\n".join(mov_error_diagnostics)
        message += format_deferred_notification(session)
        return allow(message)

    # Under max cycles — redo the card and block the agent
    # Read the card to get actual criteria failure reasons
    failure_details = _extract_criteria_failures(card_number, session)

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

    # P2.3 — Auto-uncheck failing criteria BEFORE kanban redo.
    # This guarantees the state machine: after redo, every criterion that failed is
    # unchecked so the agent cannot coast on stale checked-but-failed criteria.
    # Read the criteria freshly so we have accurate reviewer_met state.
    pre_redo_criteria = get_card_criteria(card_number, session)
    for c in pre_redo_criteria:
        if c.get("reviewer_met") == "fail":
            n = c["index"]
            uncheck_result = run_kanban(
                ["criteria", "uncheck", card_number, str(n), "--session", session]
            )
            if uncheck_result.returncode == 0:
                log_info(
                    f"auto-uncheck: unchecked criterion {n} for card #{card_number} "
                    f"(reviewer_met=fail)"
                )
            else:
                log_error(
                    f"auto-uncheck: failed to uncheck criterion {n} for card #{card_number}: "
                    f"{uncheck_result.stderr.strip()}"
                )

    # Run kanban redo to send card back to doing (increments review_cycles)
    redo_result = run_kanban(["redo", card_number, "--session", session])
    if redo_result.returncode != 0:
        log_error(f"kanban redo #{card_number} failed: {redo_result.stderr.strip()}")
        # If redo fails, allow stop — don't block agent in a broken state
        message = f"Card #{card_number} AC review failed but kanban redo also failed. Needs manual intervention."
        message += format_deferred_notification(session)
        return allow(message)

    # Notify: review→doing (redo) — reuse cached intent from the doing→review transition
    # above (if that path ran); otherwise fetch it now.
    try:
        card_intent_for_redo = intent
    except NameError:
        card_intent_for_redo = get_card_intent(card_number, session)
    send_transition_notification(card_number, "redo", card_intent_for_redo)

    # Stamp the rejection reasons onto the redo event row the kanban CLI just inserted.
    if rejection_reasons_json is not None:
        _claudit_write_redo_rejection_reasons(
            card_number=card_number,
            kanban_session=session,
            rejection_reasons_json=rejection_reasons_json,
        )

    # P2.4 — Retry feedback redesign: LOCKED PASSED / MUST FIX partition.
    # Partition criteria into those that passed (locked) vs those that failed (must fix).
    # Use pre_redo_criteria which has the reviewer_met state before redo cleared it.
    locked_passed_lines = []
    must_fix_lines = []
    for c in pre_redo_criteria:
        n = c["index"]
        text = c["text"]
        reviewer_met = c.get("reviewer_met")
        if reviewer_met == "pass":
            locked_passed_lines.append(f"  {n}. [{text}]")
        elif reviewer_met == "fail":
            # Find failure reason from failure_details string or fall back to generic message
            reason_hint = ""
            for line in failure_details.splitlines():
                if line.startswith(f"{n}. "):
                    # Format: "N. [text]: reason" — extract after the colon
                    colon_idx = line.find("]: ")
                    if colon_idx != -1:
                        reason_hint = line[colon_idx + 3:]
                    break
            must_fix_lines.append(f"  {n}. [{text}]{': ' + reason_hint if reason_hint else ''}")

    locked_section = ""
    if locked_passed_lines:
        locked_section = (
            "\n✅ LOCKED PASSED — do NOT re-verify these:\n"
            + "\n".join(locked_passed_lines)
        )

    must_fix_section = ""
    if must_fix_lines:
        must_fix_section = (
            "\n❌ MUST FIX — re-check after fixing:\n"
            + "\n".join(must_fix_lines)
        )

    reason = (
        f"AC review failed for card #{card_number} "
        f"(cycle {review_cycles + 1}/{MAX_OUTER_CYCLES})."
        f"{locked_section}"
        f"{must_fix_section}\n\n"
        f"Fix only the MUST FIX items. Do not touch code governing LOCKED PASSED criteria. "
        f"After each MUST FIX is complete, run "
        f"`kanban criteria check {card_number} <n> --session {session}` "
        f"for that specific criterion."
    )
    if mov_error_diagnostics:
        reason += "\n" + "\n".join(mov_error_diagnostics)

    system_message = (
        f"AC review found issues with your work. "
        f"Focus only on unchecked criteria. LOCKED PASSED criteria are done — "
        f"don't re-check, don't modify their governing code. "
        f"Investigate each MUST FIX criterion, fix the underlying issue, verify your fix "
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
