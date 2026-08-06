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

Skip condition: PERSONAL_TRAINER_SESSION=1 means a non-coordinator session is
running — skip AC review. See _session_env.is_non_coordinator_session().
"""

import html
import json
import os
import re
import subprocess
import sys
import time
import traceback
import warnings
from datetime import datetime, timezone
from pathlib import Path

from _session_env import is_non_coordinator_session

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

# Hard ceiling on the length of a SINGLE log_error() message, applied before
# it is written to disk. Distinct from the other two length-related limits
# in this file: _LOG_MAX_BYTES (above) rotates the WHOLE FILE once its total
# size crosses a threshold; _AUTO_ATTEMPT_MAX_OUTPUT_CHARS (near
# _truncate_output, below) caps relayed subprocess stdout/stderr text. This
# one caps a single log LINE. Without it, one pathological interpolated
# value (e.g. an oversized cwd or a large nested payload field logged via
# !r) can produce a single line large enough that
# hook-error-digest-hook.py's PER_RUN_LINE_CAP (a per-run *line-count* cap,
# not a byte cap — see that module's CAPS section) re-reads the same
# enormous line, whole, on every digest run until the next rotation.
#
# Applied universally inside log_error() below (every call site), not just
# the diagnostic-fields call site that surfaced the gap (card #3384, see
# .scratchpad/review-payload-security.md § 3). The same unbounded pattern
# was already accepted for `transcript_path` at this file's oldest
# log_error() call site (line ~1413) before this change — capping only the
# newly-added fields would draw an arbitrary line between "old" and "new"
# interpolated content on the exact same message. Capping once, inside
# log_error(), fixes the whole class consistently.
_LOG_MAX_LINE_CHARS = 4000


def _rotate_log_if_needed(path: Path) -> None:
    """Rotate path → path.1 when the file exceeds _LOG_MAX_BYTES. Never raises."""
    try:
        if path.exists() and path.stat().st_size >= _LOG_MAX_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            path.rename(rotated)
    except Exception:
        pass


def _truncate_log_line(message: str) -> str:
    """Truncate a log_error() message to _LOG_MAX_LINE_CHARS.

    Appends an elision marker with the original length — same shape as
    _truncate_output/_truncate_intent below — so a reader of the log knows
    the message was cut rather than assuming it is complete.

    Truncates the TAIL (keeps the first _LOG_MAX_LINE_CHARS characters).
    This is safe for hook-error-digest-hook.py's classification for five of
    the six _HOT_LOG_CLASSIFIERS patterns: each of those five matches text at
    or very near the START of the message — e.g. the "transcript-path-missing"
    classifier matches "non-empty transcript_path that does not exist", the
    fixed preamble text this file writes BEFORE the appended session_id/
    agent_id/agent_type/cwd/tool_use_id fields (kanban-subagent-stop-hook.py:
    1413-1414, hook-error-digest-hook.py:154) — so cutting the tail never
    removes the anchor phrase those classifiers search for.

    Known exception: "kanban-command-timeout"
    (hook-error-digest-hook.py:159, r"kanban .+ timed out after \\d+s") anchors
    on a SUFFIX — "timed out after Ns" — that comes AFTER the unbounded
    `' '.join(args)` field in this file's `f"kanban {' '.join(args)} timed out
    after {timeout}s"` message (kanban-subagent-stop-hook.py:965). If that
    joined `args` string ever grew past ~3990 characters, tail-truncation
    would cut the required suffix away and this entry would fall through to
    the generic fallback classifier instead of matching
    "kanban-command-timeout". Not currently reachable: every run_kanban()
    call site in this file passes a short, bounded argument list (subcommand
    name, card number, --session, session name), never free-text content —
    but this is an unenforced invariant, not a structural guarantee.
    """
    if len(message) <= _LOG_MAX_LINE_CHARS:
        return message
    return message[:_LOG_MAX_LINE_CHARS] + f"... [truncated, {len(message)} chars total]"


def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises.

    Rotates the log file to <path>.1 when it exceeds _LOG_MAX_BYTES,
    then starts a fresh file (one backup generation kept). The message
    itself is capped to _LOG_MAX_LINE_CHARS before being written — see
    _truncate_log_line.
    """
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(ERROR_LOG_PATH)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        capped_message = _truncate_log_line(message)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {capped_message}\n")
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


def _find_card_match_in_texts(text_to_search: list[str]) -> tuple[str, str] | None:
    """Find the first card match within a single entry's extracted text strings.

    Checks each text string in order; for a given string, pattern priority is
    XML > header > CLI (the most specific/authoritative pattern wins). Returns
    as soon as any pattern matches any string. Returns None if nothing matches.
    """
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
    return None


def _entry_has_anchor_pattern(text_to_search: list[str]) -> bool:
    """True if any text contains a hook-injected anchor pattern (XML or header).

    These two patterns are the only ones the PreToolUse hook itself injects
    into the prompt — they are trusted, non-agent-controlled content. The CLI
    pattern is deliberately excluded: it also matches commands the agent
    chooses to run (or quote in its own prose), which is agent-controlled.
    """
    for text in text_to_search:
        if _CARD_XML_PATTERN.search(text) or _CARD_HEADER_PATTERN.search(text):
            return True
    return False


def _extract_trustworthy_texts_from_entry(entry) -> list[str]:
    """Extract text values from a transcript entry, excluding assistant free-text/prose.

    Used only for entries STRICTLY AFTER the last hook-injected anchor (see
    extract_card_from_transcript's trust-anchor resolution). Assistant
    "text"-type content blocks and plain-string assistant content represent
    the agent's own narrative output — the exact untrusted surface described
    by the trust-boundary finding (an agent's final return commonly echoes
    command examples it ran, or references an unrelated card, in prose).
    tool_use input fields (real command invocations the agent issued) and all
    non-assistant-role content (hook-injected prompts, tool results) remain
    eligible to override the anchor.
    """
    if not isinstance(entry, dict):
        return _extract_text_from_entry(entry)

    if entry.get("role", "") != "assistant":
        return _extract_text_from_entry(entry)

    content = entry.get("content", "")
    if isinstance(content, str):
        return []  # plain assistant string content is untrusted prose

    texts: list[str] = []
    if isinstance(content, list):
        for blk in content:
            if not isinstance(blk, dict):
                continue  # bare string list items are untrusted prose fragments
            if blk.get("type") == "tool_use":
                texts.extend(_extract_text_from_entry(blk.get("input", {})))
            # "text"-type blocks (and any other block type) are excluded here —
            # conservatively treated as agent narrative, not a real invocation.
    return texts


def _resolve_card_from_entries_info(
    entries_info: list[tuple[bool, tuple[str, str] | None, tuple[str, str] | None]],
) -> tuple[str, str] | None:
    """Resolve the final (card_number, session) from per-entry scan results.

    entries_info[i] = (is_anchor, match_all, match_trustworthy) for the i-th
    JSONL entry, in file order. See extract_card_from_transcript for the
    trust-anchor resolution algorithm this implements.
    """
    last_anchor_idx: int | None = None
    for i in range(len(entries_info) - 1, -1, -1):
        if entries_info[i][0]:
            last_anchor_idx = i
            break

    if last_anchor_idx is None:
        # No hook-injected anchor anywhere in the (scanned-so-far) transcript —
        # fall back to latest-match-overall, unfiltered (the original
        # latest-match-wins behavior, used when there's nothing trusted to
        # anchor to, e.g. an un-injected SendMessage continuation).
        found: tuple[str, str] | None = None
        for _, match_all, _ in entries_info:
            if match_all:
                found = match_all
        return found

    # Anchor found: start from its own (inherently trustworthy) match, then
    # only allow trustworthy matches STRICTLY AFTER it to override — this lets
    # a continued agent's later, legitimate `kanban criteria check <newCard>`
    # invocation win, while preventing the agent's own final-return prose from
    # redirecting resolution to an unrelated card it merely mentions.
    found = entries_info[last_anchor_idx][1]
    for i in range(last_anchor_idx + 1, len(entries_info)):
        _, _, match_trustworthy = entries_info[i]
        if match_trustworthy:
            found = match_trustworthy
    return found


def extract_card_from_transcript(transcript_path: str) -> tuple[str, str] | None:
    """
    Parse the agent's transcript (JSONL) line by line to find the card number
    and session ID.

    Looks for:
    1. Injected card XML header from PreToolUse hook
    2. KANBAN CARD #N | Session: session-name header
    3. kanban CLI calls with card number and --session flag

    Trust-anchor resolution: patterns 1 and 2 (XML/header) are hook-injected,
    non-agent-controlled content — the trusted anchor. Resolution finds the
    LAST anchor entry in the transcript, then returns the LATEST match AT OR
    AFTER that anchor — but for entries STRICTLY AFTER the anchor, only
    "trustworthy" text is eligible to override (tool_use input fields and any
    non-assistant-role content; assistant free-text/prose is excluded — see
    _extract_trustworthy_texts_from_entry). This keeps a continued agent's
    later, legitimate `kanban criteria check <newCard> ...` invocation able to
    override a stale anchor, while preventing the agent's own final-return
    prose from redirecting resolution to an unrelated card it merely mentions.

    If NO hook-injected anchor exists anywhere in the transcript (e.g. an
    un-injected SendMessage continuation), falls back to the latest match
    found ANYWHERE in the file, unfiltered (the original latest-match-wins
    behavior). Pattern priority (XML > header > CLI) is preserved within a
    single line/entry via _find_card_match_in_texts() in both cases.

    Returns (card_number_str, session_id), or None if no card reference is
    found anywhere in the transcript.
    """
    # Size guard: skip for very large transcripts (consistent with sibling
    # transcript-scanning functions extract_agent_output/detect_criteria_gaming).
    try:
        if Path(transcript_path).stat().st_size > _TRANSCRIPT_MAX_BYTES:
            return None
    except OSError:
        pass

    entries_info: list[tuple[bool, tuple[str, str] | None, tuple[str, str] | None]] = []
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

                # Search through all string values in the entry for patterns.
                text_to_search = _extract_text_from_entry(entry)
                match_all = _find_card_match_in_texts(text_to_search)
                is_anchor = _entry_has_anchor_pattern(text_to_search)
                match_trustworthy = _find_card_match_in_texts(
                    _extract_trustworthy_texts_from_entry(entry)
                )
                entries_info.append((is_anchor, match_all, match_trustworthy))
    except (OSError, IOError) as exc:
        log_error(f"Failed to read transcript at {transcript_path}: {exc}")
        # A match already accumulated before the read error survives —
        # resolve from whatever was scanned so far rather than discarding it.
        return _resolve_card_from_entries_info(entries_info)

    return _resolve_card_from_entries_info(entries_info)


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


# ---------------------------------------------------------------------------
# Auto-attempt: run each unmet criterion's mov_commands before block/retry
# ---------------------------------------------------------------------------
#
# `kanban criteria check <card> <n>` is the single source of truth for running
# a criterion's mov_commands — see cmd_criteria_check() in kanban.py. It already
# iterates mov_commands in order, short-circuits on the first failure, and
# rejects a criterion with empty/missing mov_commands ("invalid AC ... no
# programmatic verification provided"), never marking it met.
#
# The functions below simply INVOKE that same CLI command proactively, for
# every criterion still unmet, instead of waiting for the agent to remember to
# run it. This is not a new verification path and does not relax the gate —
# it removes a dependency on agent memory. A criterion with no mov_commands is
# never vacuously passed: the CLI itself rejects it with a non-zero exit,
# exactly as it would if the agent had run the same command by hand.

# Matches an entire <ac ...>...</ac> block (attributes + body), used to find
# the `met` attribute and any nested <command timeout="..."/> children.
_AC_BLOCK_PATTERN = re.compile(r'<ac\b([^>]*)>(.*?)</ac>', re.DOTALL | re.IGNORECASE)
_AC_MET_ATTR_PATTERN = re.compile(r'\bmet="([^"]*)"', re.IGNORECASE)
# Matches every <command .../> element regardless of whether it declares a
# timeout attribute, so each one can be counted toward the budget even when
# it has none (see _MOV_COMMAND_TIMEOUT_ATTR_PATTERN, applied per-match below).
# A pattern that required the timeout attribute to match at all would silently
# contribute zero for commands lacking one, instead of the intended default.
_MOV_COMMAND_PATTERN = re.compile(r'<command\b([^>]*)>', re.IGNORECASE)
_MOV_COMMAND_TIMEOUT_ATTR_PATTERN = re.compile(r'\btimeout="([^"]*)"', re.IGNORECASE)

# Fixed overhead added on top of the sum of a criterion's own declared
# mov_commands timeouts, to account for kanban CLI startup/write overhead when
# sizing the outer subprocess timeout for `kanban criteria check`.
_AUTO_ATTEMPT_TIMEOUT_BUFFER_SECONDS = 30

# Fallback per-command timeout budget when a <command> timeout attribute is
# missing or unparsable (mirrors kanban.py's own mov_commands default).
_MOV_COMMAND_DEFAULT_TIMEOUT_SECONDS = 30

# Hard ceiling on any single criterion's computed timeout_budget. Without this,
# a single typo'd timeout attribute (e.g. "300000" instead of "30") would
# inflate the outer `kanban criteria check` subprocess timeout without limit.
# Set generously above the longest MoV timeout declared anywhere in this repo
# (~300s) so no legitimate criterion is ever clamped.
_AUTO_ATTEMPT_MAX_TIMEOUT_SECONDS = 600

# Hard ceiling on the TOTAL wall-clock time auto_attempt_unmet_criteria spends
# across all unmet criteria on one card. Each criterion is individually
# timeout-bounded, but without an aggregate cap a card with many unmet
# criteria could add many minutes to the SubagentStop completion path before
# Step 4 (`kanban done`) ever runs. Once exceeded, remaining criteria are left
# unattempted this cycle — they simply stay unmet, which is the safe
# degradation (Step 4 still proceeds normally).
_AUTO_ATTEMPT_TOTAL_BUDGET_SECONDS = 900

# Hard ceiling on how many characters of a failing mov_command's stdout/stderr
# are relayed into the block reason and log line, so a pathological command
# emitting megabytes of output cannot bloat the hook's response payload or log
# file. See _truncate_output below.
_AUTO_ATTEMPT_MAX_OUTPUT_CHARS = 2000


def _truncate_output(text: str) -> str:
    """Truncate relayed subprocess output to _AUTO_ATTEMPT_MAX_OUTPUT_CHARS.

    Appends a clear elision marker when truncation occurs, so a reader of the
    block reason or log knows the text was cut rather than assuming it's the
    command's entire output.
    """
    if len(text) <= _AUTO_ATTEMPT_MAX_OUTPUT_CHARS:
        return text
    return text[:_AUTO_ATTEMPT_MAX_OUTPUT_CHARS] + f"... [truncated, {len(text)} chars total]"


def get_unmet_criteria(card_number: str, session: str) -> list[dict]:
    """Return every acceptance criterion currently unmet (met != "true").

    Reads the card XML (same source `get_all_criteria_numbers` reads) and
    returns, in document order, one dict per unmet criterion:
        {"index": <1-based int>, "timeout_budget": <int seconds>}

    `timeout_budget` is the sum of that criterion's own declared mov_commands
    timeouts (as authored on the card, defaulting missing/unparsable ones to
    _MOV_COMMAND_DEFAULT_TIMEOUT_SECONDS) plus a fixed overhead buffer — sized
    so the outer `kanban criteria check` call (which itself runs those
    commands) cannot time out before the commands it wraps legitimately would.
    A criterion with no mov_commands still gets the buffer alone, which is
    ample for the CLI's immediate "invalid AC" rejection. The result is
    clamped to _AUTO_ATTEMPT_MAX_TIMEOUT_SECONDS so a single mistyped timeout
    attribute cannot inflate the outer timeout without bound.

    Returns an empty list on any error — fails open, leaving the auto-attempt
    step a no-op and the existing kanban-done-based flow entirely unchanged.
    """
    try:
        result = run_kanban(["show", card_number, "--output-style=xml", "--session", session])
        if result.returncode != 0:
            return []

        unmet: list[dict] = []
        for idx, m in enumerate(_AC_BLOCK_PATTERN.finditer(result.stdout), start=1):
            attrs, body = m.group(1), m.group(2)
            met_match = _AC_MET_ATTR_PATTERN.search(attrs)
            met = met_match.group(1).strip().lower() if met_match else "false"
            if met == "true":
                continue

            timeouts: list[int] = []
            for cmd_m in _MOV_COMMAND_PATTERN.finditer(body):
                timeout_m = _MOV_COMMAND_TIMEOUT_ATTR_PATTERN.search(cmd_m.group(1))
                if timeout_m is None:
                    # No timeout attribute at all — apply the default rather
                    # than silently contributing zero (see comment above
                    # _MOV_COMMAND_PATTERN).
                    timeouts.append(_MOV_COMMAND_DEFAULT_TIMEOUT_SECONDS)
                    continue
                try:
                    timeouts.append(int(timeout_m.group(1)))
                except (TypeError, ValueError):
                    timeouts.append(_MOV_COMMAND_DEFAULT_TIMEOUT_SECONDS)

            timeout_budget = min(
                sum(timeouts) + _AUTO_ATTEMPT_TIMEOUT_BUFFER_SECONDS,
                _AUTO_ATTEMPT_MAX_TIMEOUT_SECONDS,
            )
            unmet.append({"index": idx, "timeout_budget": timeout_budget})

        return unmet
    except Exception as exc:
        log_error(f"get_unmet_criteria for card #{card_number}: {exc}")
        return []


def auto_attempt_unmet_criteria(card_number: str, session: str) -> list[str]:
    """Proactively run `kanban criteria check` for every currently-unmet criterion.

    For each unmet criterion:
      - All of its mov_commands exit 0 → kanban marks it met (exit 0); no
        further action needed here.
      - Any mov_command fails, or mov_commands is empty/missing → kanban
        itself returns non-zero with a diagnostic (the specific failing
        command, its exit code, and stdout/stderr, OR the "invalid AC ... no
        programmatic verification provided" message) — that diagnostic is
        collected verbatim into the returned list.

    Returns a list of human-readable failure descriptions for criteria that
    remain unmet after this attempt (empty if everything got marked met, or if
    there was nothing to attempt). Fails open: any error while listing unmet
    criteria returns an empty list, leaving the existing kanban-done-based
    flow entirely unchanged.

    Each criterion's `kanban criteria check` invocation is individually
    contained in its own try/except — mirroring the containment already
    applied to the anti-gaming uncheck loop and to this function's own call to
    get_unmet_criteria above — so a single criterion whose mov_command output
    triggers an unexpected exception (e.g. non-UTF-8 subprocess output
    raising UnicodeDecodeError) cannot cascade out of this function and cause
    Step 4 (`kanban done`, the authoritative check) to be skipped entirely.
    That criterion is simply treated as still-unmet and the loop continues.

    The loop also enforces an aggregate wall-clock budget
    (_AUTO_ATTEMPT_TOTAL_BUDGET_SECONDS) across all unmet criteria on the
    card: once exceeded, remaining criteria are left unattempted this cycle
    rather than letting a card with many unmet criteria stall the
    SubagentStop completion path indefinitely.
    """
    try:
        unmet = get_unmet_criteria(card_number, session)
    except Exception as exc:
        log_error(f"auto_attempt_unmet_criteria: failed to list unmet criteria for card #{card_number}: {exc}")
        return []

    failures: list[str] = []
    started_at = time.monotonic()
    for criterion in unmet:
        if time.monotonic() - started_at > _AUTO_ATTEMPT_TOTAL_BUDGET_SECONDS:
            log_info(
                f"Auto-attempt: aggregate time budget "
                f"({_AUTO_ATTEMPT_TOTAL_BUDGET_SECONDS}s) exceeded for card "
                f"#{card_number} — leaving remaining unmet criteria "
                f"unattempted this cycle; Step 4 proceeds normally."
            )
            break

        index = criterion["index"]
        timeout = criterion["timeout_budget"]
        try:
            result = run_kanban(
                ["criteria", "check", card_number, str(index), "--session", session],
                timeout=timeout,
            )
        except Exception as exc:
            # Contained: one criterion's unexpected failure (e.g. malformed
            # subprocess output) must not cascade into skipping Step 4 for
            # the whole card. Treat as still-unmet and move on.
            log_error(
                f"auto_attempt_unmet_criteria: criterion {index} for card "
                f"#{card_number} raised unexpectedly (contained, treated as "
                f"still unmet): {exc}"
            )
            failures.append(f"Criterion {index}: auto-attempt raised an unexpected error: {exc}")
            continue

        if result.returncode == 0:
            log_info(f"Auto-attempt: criterion {index} passed for card #{card_number}")
        else:
            output = _truncate_output(result.stderr.strip() or result.stdout.strip())
            failures.append(f"Criterion {index}: {output}")
            log_info(
                f"Auto-attempt: criterion {index} still unmet for card #{card_number} "
                f"(exit {result.returncode}): {output}"
            )

    return failures


def _card_numbers_in_mine_bucket(stdout: str) -> list[str]:
    r"""Extract card numbers from ONLY the `<mine>...</mine>` bucket of a
    `kanban list --output-style=xml --session <s>` response.

    `--session` does not filter the payload down to that session's cards —
    it buckets the FULL board into `<mine>` (cards owned by the given
    session) and `<others>` (every other session's cards), per
    modules/kanban/kanban.py's cmd_list and
    modules/kanban/tests/test_kanban_list_xml_schema.py's documented schema.
    Matching `<c n="(\d+)"` against the whole response (as both callers of
    this helper originally did) matches straight through the `<others>`
    bucket too, attributing a foreign session's cards to this one. Scope to
    `<mine>` first, and only search for `<c ` elements inside that slice.

    `<mine>` is emitted only when non-empty (cmd_list: `if mine_cards:
    print("<mine>")`) — no `<mine>` tag in stdout means this session owns no
    cards in the queried column, and the correct result is `[]`.
    """
    mine_match = re.search(r'<mine>(.*?)</mine>', stdout, re.DOTALL)
    if not mine_match:
        return []
    return re.findall(r'<c n="(\d+)"', mine_match.group(1))


def get_deferred_cards(session: str) -> list[str]:
    """Get list of card numbers in the todo column for this session."""
    try:
        result = run_kanban(["list", "--column", "todo", "--output-style=xml", "--session", session])
        if result.returncode == 0 and result.stdout.strip():
            return _card_numbers_in_mine_bucket(result.stdout)
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


def cards_in_doing_for_session(session_id: str) -> list[str] | None:
    """Return card numbers in the 'doing' column for a session, or None.

    Used only by process_subagent_stop's missing-transcript-path branch, to
    decide whether a "transcript_path not found" event can actually strand a
    card (see that call site). Mirrors get_deferred_cards' regex-based
    extraction from `kanban list --output-style=xml` above, for consistency
    with the rest of this file.

    Returns:
      - []            : the read succeeded (exit 0, stdout structurally
                         matches kanban's board XML) and no card is in
                         'doing' for this session — a normal, successful
                         result, NOT a failure.
      - [<num>, ...]   : the read succeeded and these cards are in 'doing'.
      - None           : the read could not be completed OR could not be
                         trusted: no session_id, a non-zero exit from
                         run_kanban (which already collapses subprocess
                         timeouts/FileNotFoundError to a non-zero
                         returncode), any unexpected exception, OR an exit-0
                         response whose stdout does not structurally look
                         like kanban's board XML at all (see the "<board"
                         check below) — exit 0 with garbled/empty/truncated
                         output is an UNKNOWN, not a confirmed-empty board,
                         and must not be silently downgraded to "no card is
                         stranded". Callers MUST treat None as "unknown, not
                         'no cards'" and fall back to the pre-existing
                         ERROR-level report unchanged (fail-open).

    Deliberately does not itself call log_error on failure: the caller is
    the single point of truth for what gets logged when this returns None,
    so a failed read here does not ALSO produce a second, differently-worded
    error line alongside the caller's own fallback report.

    Never raises.
    """
    if not session_id:
        return None
    try:
        result = run_kanban(
            ["list", "--column", "doing", "--output-style=xml", "--session", session_id],
            timeout=10,
        )
        if result.returncode != 0:
            return None
        stdout = result.stdout
        # Distinguish a genuinely successful, confirmed-empty parse from an
        # exit-0-but-unparseable response. `cmd_list`'s xml branch
        # (modules/kanban/kanban.py) prints the opening `<board...>` tag
        # unconditionally, before it ever checks whether any column has
        # cards — so every real, successful `kanban list --output-style=xml`
        # invocation's stdout contains the literal substring "<board",
        # whether or not the 'doing' column is actually empty (verified
        # against modules/kanban/tests/test_kanban_list_xml_schema.py's
        # documented schema, which this file is prohibited from executing
        # directly). An exit-0 response that lacks that root element
        # entirely (empty stdout, truncated output, or anything else that
        # did not come from a real board read) is not a confirmed-empty
        # board — it is unknown, and must fall back to the caller's
        # existing None/ERROR path rather than being silently treated as
        # "no card is stranded".
        if "<board" not in stdout:
            return None
        # Scope to the `<mine>` bucket only — see _card_numbers_in_mine_bucket
        # above for why: `--session` buckets the FULL board into `<mine>`
        # (this session's cards) and `<others>` (every other session's
        # cards); matching `<c n="(\d+)"` against the whole response matches
        # straight through `<others>` too, wrongly attributing a foreign
        # session's doing-card to this one.
        return _card_numbers_in_mine_bucket(stdout)
    except Exception:
        return None


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

    # These two early-exit cases are deliberately NOT logged identically.
    # An empty transcript_path is the common, benign case — many Task calls
    # (lightweight lookups, non-kanban-managed agents) never carry one. A
    # NON-EMPTY path whose file does not exist is a different, anomalous
    # signal: the daemon told us to look at something specific and it was
    # not there. Collapsing both into one log_info line makes the anomalous
    # case indistinguishable from routine noise — see card #3312's
    # determination (.scratchpad/3312-hook-determination.md) for the
    # evidence this exact silent branch is what stranded cards #3292 and
    # #3305 at status=doing with every criterion met: card identification,
    # and therefore `kanban done`, was never attempted for either card
    # because this guard fired first. Surfacing it via log_error (rather
    # than retrying) is the fix — see the determination's "Fix implemented"
    # section for why a retry was not chosen.
    if not transcript_path:
        log_info("No transcript path provided — allowing stop (not kanban-managed)")
        return allow()

    if not os.path.exists(transcript_path):
        # Discriminator: whether a card can actually be stranded by this
        # event depends on whether any card for this session is currently
        # in 'doing'. This states a per-occurrence verifiable fact rather
        # than a conclusion about the population of all such events — see
        # card #3421's investigation (cards #3408, #3410) for why a blanket
        # "these are phantom" claim is not warranted: the producer of these
        # events was never identified. FAIL OPEN: any failure to read the
        # board (no session_id, non-zero exit, timeout, or exception) falls
        # back to today's ERROR-level report unchanged — see
        # cards_in_doing_for_session's docstring.
        session_id_for_check = payload.get('session_id', '')
        cards_in_doing = cards_in_doing_for_session(session_id_for_check)

        if cards_in_doing is None:
            # Board read failed (or no session_id available) — cannot
            # determine whether a card is at risk. Fall back to the
            # original, unconditional stranding-risk report (unchanged from
            # before this discriminator existed).
            log_error(
                f"SubagentStop received a non-empty transcript_path that does not "
                f"exist on disk: {transcript_path!r}. The card this stop belonged "
                f"to could not be identified, so kanban done was never attempted "
                f"— the card may be silently stranded in 'doing'. This may "
                f"indicate a race (transcript not yet flushed/moved to its final "
                f"path) or a stale/incorrect path from the daemon. "
                f"session_id={payload.get('session_id', '')!r} "
                f"agent_id={payload.get('agent_id', '')!r} "
                f"agent_type={payload.get('agent_type', '')!r} "
                f"cwd={payload.get('cwd', '')!r} "
                f"tool_use_id={payload.get('tool_use_id', '')!r}"
            )
        elif cards_in_doing:
            # One or more cards ARE in 'doing' for this session — one of
            # them may genuinely be the card this stop belonged to. Keep
            # ERROR and name the card(s) so the reader has something
            # concrete to check.
            card_list = ", ".join(f"#{c}" for c in cards_in_doing)
            log_error(
                f"SubagentStop received a non-empty transcript_path that does not "
                f"exist on disk: {transcript_path!r}. The card this stop belonged "
                f"to could not be identified, so kanban done was never attempted. "
                f"Session {session_id_for_check!r} has card(s) {card_list} in "
                f"'doing' right now — one of these may be silently stranded by "
                f"this event. This may indicate a race (transcript not yet "
                f"flushed/moved to its final path) or a stale/incorrect path "
                f"from the daemon. "
                f"session_id={payload.get('session_id', '')!r} "
                f"agent_id={payload.get('agent_id', '')!r} "
                f"agent_type={payload.get('agent_type', '')!r} "
                f"cwd={payload.get('cwd', '')!r} "
                f"tool_use_id={payload.get('tool_use_id', '')!r}"
            )
        else:
            # No card for this session is in 'doing' — no card can be
            # stranded by this occurrence. Logged below error level
            # (log_info, not log_error): a per-occurrence fact, not a
            # generalization that this class of event is spurious.
            log_info(
                f"SubagentStop received a non-empty transcript_path that does not "
                f"exist on disk: {transcript_path!r}. No card for session "
                f"{session_id_for_check!r} is currently in 'doing', so no card "
                f"is stranded by this occurrence. This may still indicate a "
                f"race (transcript not yet flushed/moved to its final path) "
                f"or a stale/incorrect path from the daemon. "
                f"session_id={payload.get('session_id', '')!r} "
                f"agent_id={payload.get('agent_id', '')!r} "
                f"agent_type={payload.get('agent_type', '')!r} "
                f"cwd={payload.get('cwd', '')!r} "
                f"tool_use_id={payload.get('tool_use_id', '')!r}"
            )
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

    # Step 3.5: Auto-attempt every unmet criterion by running `kanban criteria
    # check` directly, before falling back to the block/retry decision below.
    # This is not a relaxation of the quality gate — mov_commands are executed
    # by the same CLI command either way (see auto_attempt_unmet_criteria's
    # docstring) — it just removes the dependency on the agent remembering to
    # invoke the check after finishing real work.
    auto_attempt_failures = auto_attempt_unmet_criteria(card_number, session)

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

        # Auto-attempt feedback: the specific failing command(s) and their exit
        # code/stderr for criteria the hook already tried and could not resolve
        # (Step 3.5 above). Appended as its own section — kept separate from
        # kanban_output so detect_stuck_criteria's regex scan below still parses
        # kanban done's own output only.
        auto_attempt_section = ""
        if auto_attempt_failures:
            auto_attempt_detail = "\n".join(f"  - {f}" for f in auto_attempt_failures)
            auto_attempt_section = (
                f"\n\nAuto-attempt results (the hook already ran `kanban criteria check` "
                f"for each unmet criterion before this check — no need to re-run these "
                f"exact commands again until you've made a change):\n{auto_attempt_detail}"
            )

        reason = (
            f"kanban done failed for card #{card_number}:\n\n"
            f"{kanban_output}"
            f"{auto_attempt_section}\n\n"
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
    # Skip if running inside a non-coordinator session (Personal Trainer, etc.).
    # is_non_coordinator_session() checks PERSONAL_TRAINER_SESSION=1;
    # add new session-type flags in _session_env.py as new modes are introduced.
    if is_non_coordinator_session():
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
