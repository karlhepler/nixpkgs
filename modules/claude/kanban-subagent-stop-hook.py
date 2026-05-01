#!/usr/bin/env python3
"""
kanban-subagent-stop-hook: SubagentStop hook that manages card lifecycle on agent stop.

Triggered when any sub-agent finishes execution. Parses the agent's transcript
to find the associated kanban card, then calls `kanban done` to attempt card
completion. The kanban CLI gates completion on its own criteria and cycle logic.

Flow:
  1. Identify card from transcript
  2. Permission stall check (exits early with allow if stalled)
  3. Anti-gaming detection (blocks if gaming detected)
  4. Call `kanban done <N> --session <S> 'agent stopped'`
     - exit 0 → allow() with success notification
     - exit 1 → block() with kanban's stderr/stdout as feedback (retryable)
     - exit 2 → allow() with surface-to-staff notification (max cycles reached)
     - other  → block() with the error

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

# Patterns for extracting card number and session from transcript lines
_KANBAN_CMD_PATTERN = re.compile(
    r'kanban\s+(?:criteria\s+check|show|status|done)\s+(\d+).*--session\s+([a-z0-9][a-z0-9-]*)',
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

# ---------------------------------------------------------------------------
# Hedge-word audit constants
# ---------------------------------------------------------------------------

HEDGE_PATTERNS = [
    r"\bconceptually\b",
    r"\beffectively\b",
    r"\bessentially\b",
    r"\bbasically\b",
    r"\bmore or less\b",
    r"\bin spirit\b",
    r"\bappears to\b",
    r"\bseems to\b",
    r"\bshould work\b",
    r"\blikely\b",
    r"\bpresumably\b",
    r"\bfunctionally\b",
    r"\broughly\b",  # approximately/roughly: legitimate in measurement contexts; flag with care
    r"\bapproximately\b",  # approximately/roughly: legitimate in measurement contexts; flag with care
    r"\bsort of\b",
    r"\bkind of\b",
    r"\bfor the most part\b",
    r"\btypically\b",
    r"\bgenerally\b",
]

CITATION_PATTERN = r"\b[A-Za-z0-9_\-]+(?:[./][A-Za-z0-9_\-]+)*\.[a-z]+:[0-9]+\b"  # path.ext:line

# Minimum number of file:line citations to consider a hedged return "grounded".
_HEDGE_CITATION_THRESHOLD = 3

# Minimum character length of final return text before running hedge audit.
_HEDGE_MIN_LENGTH = 400

# Maximum transcript size before skipping transcript-reading operations.
_TRANSCRIPT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

# ---------------------------------------------------------------------------

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

def allow(message: str = "", system_message: str = "") -> dict:
    """Return a decision=allow response."""
    result = {"decision": "allow"}
    if message:
        result["reason"] = message
    if system_message:
        result["systemMessage"] = system_message
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

    Returns the extracted output string, or empty string if not found.
    """
    # Size guard: skip for very large transcripts (consistent with gaming detection).
    try:
        if Path(transcript_path).stat().st_size > _TRANSCRIPT_MAX_BYTES:
            return ""
    except OSError:
        pass

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
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            text = blk.get("text", "")
                            if text.strip():
                                text_parts.append(text.strip())
                        elif isinstance(blk, str) and blk.strip():
                            text_parts.append(blk.strip())
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

            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") != "tool_use":
                    continue

                tool_name: str = blk.get("name", "")

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
                    tool_input = blk.get("input", {})
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
# Hedge-word audit
# ---------------------------------------------------------------------------

def _strip_code_and_quotes(text: str) -> str:
    """Remove triple-backtick code blocks and quoted strings from text.

    This prevents false positives where the agent quotes a user question or
    code snippet that happens to contain hedge words.
    """
    # Strip triple-backtick code blocks (```...```)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # Strip inline backtick code spans (`...`)
    text = re.sub(r"`[^`]*`", "", text)
    # Strip double-quoted strings — conservative: only single-line strings
    text = re.sub(r'"[^"\n]{0,300}"', "", text)
    # Note: single-quote stripping is intentionally omitted — it strips possessives
    # and contractions (e.g. "it's", "don't"), which can remove hedge words mid-sentence.
    # The primary false-positive risk is code blocks and inline code, handled above.
    return text


def hedge_audit(
    final_return_text: str,
    card_number: str,
    session: str,
    card_type: str = "work",
) -> str:
    """Audit the agent's final return text for hedge words without grounding evidence.

    Returns a non-empty SystemReminder string if the audit trips; empty string otherwise.

    Decision logic:
    - No hedges → no action (return "")
    - Hedges + ≥3 file:line citations → grounded, no action (return "")
    - Hedges + <3 citations → return SystemReminder string

    Edge-case skips:
    - card_type in ('research', 'review') → skip (these card types report analysis/findings
      which inherently use hedging language like "appears to", "generally", "likely")
    - len(final_return_text) < _HEDGE_MIN_LENGTH → skip (not enough text)
    """
    # Skip research and review cards — hedging language is expected for analytical reports.
    if card_type in ("research", "review"):
        return ""

    # Skip terse returns — not enough text to form a reliable hedge pattern.
    if len(final_return_text) < _HEDGE_MIN_LENGTH:
        return ""

    # Strip code blocks and quoted strings to reduce false positives.
    scan_text = _strip_code_and_quotes(final_return_text)

    # Find all hedge matches.
    detected_hedges: list[str] = []
    for pattern in HEDGE_PATTERNS:
        compiled = re.compile(pattern, re.IGNORECASE)
        matches = compiled.findall(scan_text)
        if matches:
            # Record the canonical hedge word (first capture or the match itself).
            detected_hedges.extend(matches)

    if not detected_hedges:
        return ""

    # Count file:line citations in the original text (not stripped — citations may
    # appear near code blocks).
    citation_matches = re.findall(CITATION_PATTERN, final_return_text)
    citation_count = len(citation_matches)

    if citation_count >= _HEDGE_CITATION_THRESHOLD:
        # Sufficiently grounded — hedge words are acceptable.
        return ""

    # Deduplicate hedge list for display, preserving order.
    seen: set[str] = set()
    unique_hedges: list[str] = []
    for h in detected_hedges:
        lh = h.lower()
        if lh not in seen:
            seen.add(lh)
            unique_hedges.append(h)

    hedge_list = ", ".join(f'"{h}"' for h in unique_hedges[:10])
    reminder = (
        f"\U0001f6a8 Hedge-word audit on card #{card_number} (session {session}):\n\n"
        f"The agent's final return contains hedging language without sufficient\n"
        f"file:line evidence. This pattern has historically masked stub work.\n\n"
        f"Hedges detected: {hedge_list}\n"
        f"Citations found: {citation_count} (need ≥{_HEDGE_CITATION_THRESHOLD} for acceptance)\n\n"
        f"Per § Hedge-Word Auto-Reject Trigger: spawn a verification card before\n"
        f"briefing the user. Use a domain specialist sub-agent (e.g., /researcher\n"
        f"or /debugger) with AC asserting concrete observable evidence."
    )
    return reminder


# ---------------------------------------------------------------------------
# Stuck-criterion detection
# ---------------------------------------------------------------------------

# Matches criterion index lines in `kanban done` stderr output.
# kanban done prints lines like:  "  [⬜]  [⬜ —]  1. some criterion text"
# We extract the 1-based index (the integer before the period).
_DONE_CRITERION_INDEX_PATTERN = re.compile(
    r'^\s*\[.*?\]\s+\[.*?\]\s+(\d+)\.',
    re.MULTILINE,
)

# Matches the same pattern in block-feedback messages previously sent to the
# agent (the hook embeds kanban's stderr verbatim in its block reason).
# Uses ^ anchor + re.MULTILINE (symmetric with _DONE_CRITERION_INDEX_PATTERN).
_BLOCK_FEEDBACK_CRITERION_INDEX_PATTERN = re.compile(r'^\s*\[.*?\]\s+\[.*?\]\s+(\d+)\.', re.MULTILINE)  # noqa: E501


def _extract_criterion_indices_from_done_output(done_output: str) -> set[int]:
    """Parse 1-based criterion indices from `kanban done` stderr output.

    Looks for lines with the pattern `[box] [box] N. text` and returns
    the set of integer indices found. Returns empty set on no match.
    """
    return {int(m.group(1)) for m in _DONE_CRITERION_INDEX_PATTERN.finditer(done_output)}


def _extract_criterion_indices_from_block_feedback(text: str) -> set[int]:
    """Parse 1-based criterion indices from a prior block-feedback message.

    Matches the same `[box] [box] N.` pattern embedded in feedback text.
    """
    return {int(m.group(1)) for m in _BLOCK_FEEDBACK_CRITERION_INDEX_PATTERN.finditer(text)}


def detect_stuck_criteria(
    current_done_output: str,
    transcript_path: str,
    card_number: str,
) -> list[int]:
    """Detect criteria that have been unchecked across 2+ consecutive cycles.

    A criterion is considered stuck only if it failed in the IMMEDIATELY
    PREVIOUS cycle AND fails again in the current cycle.  Criteria that failed
    earlier but were resolved (or the cycle was non-consecutive) are NOT flagged.

    Algorithm:
    1. Extract the set of unchecked criterion indices from the current
       `kanban done` exit-1 output.
    2. Scan the JSONL transcript for prior block-feedback messages from
       this hook (identified by "kanban done failed for card #N").
    3. Identify the most-recent such prior feedback message and extract the
       unchecked criterion indices it listed.
    4. Return the sorted list of indices that appear in BOTH the current output
       AND the most-recent prior feedback — these are stuck across two
       consecutive cycles.

    Fails open: any error returns an empty list so normal hook flow continues.

    Args:
        current_done_output: The stderr/stdout from the current `kanban done` call.
        transcript_path: Absolute path to the agent's JSONL transcript.
        card_number: The card number string (for scoping feedback lookups).

    Returns:
        Sorted list of 1-based criterion indices that are stuck (failed in the
        immediately previous cycle AND the current cycle). Empty list if none
        found or on any error.
    """
    try:
        current_indices = _extract_criterion_indices_from_done_output(current_done_output)
        if not current_indices:
            return []

        # Scan transcript for prior block feedback messages for this card.
        # The hook embeds "kanban done failed for card #N:" in the block reason,
        # followed by kanban's stderr verbatim.  We want only the most-recent
        # prior feedback to check for true consecutive-cycle failures.
        feedback_marker = f"kanban done failed for card #{card_number}:"
        most_recent_feedback: str | None = None

        try:
            if Path(transcript_path).stat().st_size > _TRANSCRIPT_MAX_BYTES:
                return []
        except OSError:
            pass

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
                    texts = _extract_text_from_entry(entry)
                    for text in texts:
                        if feedback_marker in text:
                            # Keep the last (most-recent) match
                            most_recent_feedback = text
        except (OSError, IOError) as exc:
            log_error(f"detect_stuck_criteria: failed to read transcript {transcript_path}: {exc}")
            return []

        if most_recent_feedback is None:
            return []

        previous_cycle_indices = _extract_criterion_indices_from_block_feedback(most_recent_feedback)
        stuck = sorted(current_indices & previous_cycle_indices)
        return stuck

    except Exception as exc:
        log_error(f"detect_stuck_criteria: unexpected error for card #{card_number}: {exc}")
        return []


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
    "done": "✅",       # review→done (Done)
    "redo": "🔄",       # review→doing (Redo)
    "todo": "⏸️",       # doing→todo (Deferred)
    "canceled": "❌",   # any→canceled (Canceled)
}

_STATE_TITLE = {
    "doing": "Work Started",
    "done": "Done",
    "redo": "Redo",
    "todo": "Deferred",
    "canceled": "Canceled",
}

_STATE_SOUND = {
    "doing": "Purr",         # Work Started — uplifting, positive energy
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
    return intent[:max_len - 1].rstrip() + "…"


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
        # Scrub embedded newlines — tmux names could theoretically contain them,
        # which would break the AppleScript string literal in send_transition_notification.
        safe_session = session.replace("\n", " ").replace("\r", " ")  # replace newline chars
        safe_window = window.replace("\n", " ").replace("\r", " ")  # replace newline chars
        if safe_session and safe_window:
            return f"{safe_session} → {safe_window}"
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
        card_line = f"#{card_number} — {snippet}"
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


def get_card_type(card_number: str, session: str, transcript_path: str = "") -> str:
    """Fetch card type, reading from injected XML in transcript first.

    Primary path: parse the injected <card> XML already present in the transcript
    (inserted by the PreToolUse hook). This avoids an extra kanban show call after
    kanban done has already moved the card to done state.

    Fallback: issue kanban show if the transcript path is not provided or the XML
    does not contain a type attribute.

    Returns 'work' on failure/absence (the most common type).
    """
    # Primary: read card type from transcript's injected XML (_CARD_XML_PATTERN).
    if transcript_path:
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
                    texts = _extract_text_from_entry(entry)
                    for text in texts:
                        m = re.search(
                            r'<card\b[^>]*\bnum="' + re.escape(card_number) + r'"[^>]*\btype="([^"]*)"',
                            text,
                            re.IGNORECASE,
                        )
                        if not m:
                            # Also try reversed attribute order: type before num
                            m = re.search(
                                r'<card\b[^>]*\btype="([^"]*)"[^>]*\bnum="' + re.escape(card_number) + r'"',
                                text,
                                re.IGNORECASE,
                            )
                        if m:
                            return m.group(1).strip().lower()
        except Exception:
            pass

    # Fallback: kanban show (used if transcript path absent or XML extraction failed).
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session], timeout=10)
        if result.returncode == 0:
            m = re.search(r'<card\b[^>]*\btype="([^"]*)"', result.stdout)
            if m:
                return m.group(1).strip().lower()
    except Exception:
        pass
    return "work"


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
# Main hook logic
# ---------------------------------------------------------------------------

def process_subagent_stop(payload: dict) -> dict:
    """
    Process a SubagentStop event.

    Steps:
    1. Identify card from transcript
    2. Permission stall check (short-circuit if stalled)
    3. Anti-gaming detection (block if gaming)
    4. Call kanban done and map exit code to allow/block
    """
    transcript_path = payload.get("agent_transcript_path", "")
    # Note: transcript_path is accepted without canonicalization (no Path.resolve()
    # or home-directory restriction). The path arrives from the Claude Code daemon,
    # which is a trusted internal process on this single-user system. Deferred —
    # revisit if this hook is ever exposed to multi-user or network-delivered input.

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

    # Step 2: Permission stall check.
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

    # Step 3: Anti-gaming detection.
    # Only fires when the card is still in 'doing' (retry scenario).
    # If the agent re-checked criteria without doing substantive work, block immediately.
    if status_for_stall_check == "doing" and detect_criteria_gaming(transcript_path):
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

    # Idempotency check: if the card is already in 'done' state, a prior stop event
    # has already triggered the lifecycle transition. Calling `kanban done` again
    # would error and surface as a false `Status: blocked` in the agent's final
    # return. Treat as a no-op. Fetch fresh status here (not reusing the earlier
    # `status_for_stall_check` from line 940) to narrow the TOCTOU window.
    fresh_status = get_card_status(card_number, session)
    if fresh_status == "done":
        log_info(f"Card #{card_number} already in done state — skipping kanban done call")
        return allow()

    # Step 4: Call kanban done and map exit code.
    log_info(f"Calling kanban done for card #{card_number}")
    done_result = run_kanban(
        ["done", card_number, "--session", session, "agent stopped"],
        timeout=60,
    )
    exit_code = done_result.returncode

    # Step 5: Hedge-word audit (additive, runs after kanban done regardless of outcome).
    # Fetch the card type here once — used for audit skip logic.
    # Reads from injected transcript XML first; falls back to kanban show only if needed.
    card_type = get_card_type(card_number, session, transcript_path=transcript_path)
    final_return_text = extract_agent_output(transcript_path)
    hedge_reminder = hedge_audit(final_return_text, card_number, session, card_type)
    if hedge_reminder:
        log_info(
            f"Hedge-word audit tripped for card #{card_number}: "
            f"{len(hedge_reminder)} char reminder generated"
        )

    if exit_code == 0:
        # Card completed successfully
        intent = get_card_intent(card_number, session)
        send_transition_notification(card_number, "done", intent)
        message = f"Card #{card_number} completed successfully."
        message += format_deferred_notification(session)
        log_info(f"Card #{card_number} done (exit 0)")
        return allow(message, system_message=hedge_reminder)

    if exit_code == 2:
        # Max cycles reached — allow stop, surface to staff; hedge_reminder forwarded.
        kanban_output = done_result.stderr.strip() or done_result.stdout.strip()
        max_cycles_msg = f"Card #{card_number} max cycles reached — requires manual intervention.\n\n{kanban_output}" + format_deferred_notification(session)
        log_info(f"Card #{card_number} max cycles reached (exit 2): {kanban_output}")
        return allow(max_cycles_msg, system_message=hedge_reminder)

    if exit_code == 1:
        # Retryable failure — block agent with kanban's feedback verbatim
        kanban_output = done_result.stderr.strip() or done_result.stdout.strip()
        reason = (
            f"kanban done failed for card #{card_number}:\n\n"
            f"{kanban_output}\n\n"
            f"Investigate each unchecked criterion, do the work to satisfy it, verify "
            f"your fix is correct, and only THEN run `kanban criteria check`. "
            f"The SubagentStop hook will call `kanban done` again automatically "
            f"when you stop."
        )
        log_info(f"Card #{card_number} not done yet (exit 1): {kanban_output}")

        # Stuck-criterion early warning: detect criteria unchecked on 2+ consecutive
        # cycles — a signal that the MoV itself may be structurally broken.
        stuck = detect_stuck_criteria(kanban_output, transcript_path, card_number)
        if stuck:
            indices_str = ", ".join(str(i) for i in stuck)
            log_info(
                f"Warning: Card #{card_number} criterion {indices_str} has failed AC "
                f"verification on 2+ consecutive cycles — MoV may be structurally broken. "
                f"Investigate before further retries."
            )

        return block(reason, system_message=hedge_reminder)

    # Other non-zero exit — unexpected error
    kanban_output = done_result.stderr.strip() or done_result.stdout.strip()
    reason = (
        f"kanban done returned unexpected exit code {exit_code} for card #{card_number}:\n\n"
        f"{kanban_output}\n\n"
        f"This may indicate a kanban CLI error. Investigate and retry."
    )
    log_error(f"Card #{card_number} kanban done exit {exit_code}: {kanban_output}")
    return block(reason)


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
