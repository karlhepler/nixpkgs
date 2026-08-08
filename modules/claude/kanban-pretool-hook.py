#!/usr/bin/env python3
"""
kanban-pretool-hook: PreToolUse(Agent) hook that injects kanban card content
into sub-agent prompts.

Triggered by Claude Code's PreToolUse event when tool_name == 'Agent'.
Reads the agent prompt, extracts the card number and session ID, fetches the
card content via `kanban show`, and injects it at the beginning of the prompt.

Output format (PreToolUse hook):
    {"hookSpecificOutput": {"permissionDecision": "allow", "updatedInput": {"prompt": "..."}}}

Fails open: any error (no card found, kanban show fails, JSON parse error)
results in allowing the tool call unchanged.

Skip condition: PERSONAL_TRAINER_SESSION=1 means a non-coordinator session is
running — skip injection to avoid confusing the model with kanban context.

Known Issues:
    - Claude Code displays 'PreToolUse:Agent hook error' in the UI even when
      this hook succeeds (exits 0, valid JSON, no stderr). This is a cosmetic
      UI bug in Claude Code, not a hook failure. The hook's info log at
      ~/.claude/metrics/kanban-pretool-hook.log confirms successful injection.
      See: https://github.com/anthropics/claude-code/issues/17088
    - updatedInput may be silently dropped if multiple PreToolUse hooks match
      the same tool (we only register one for Agent, so this should not apply).
      See: https://github.com/anthropics/claude-code/issues/15897
"""

import fnmatch
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import traceback
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

from _session_env import is_non_coordinator_session

# Suppress Python deprecation warnings to prevent stderr output,
# which Claude Code interprets as hook errors.
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ERROR_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-pretool-hook-errors.log"
INFO_LOG_PATH = Path.home() / ".claude" / "metrics" / "kanban-pretool-hook.log"

# Patterns for extracting card number and session from agent prompts.
# Priority order: most specific first.
#
# Pattern 1: "KANBAN CARD #N | Session: session-name"  (current delegation template)
_CARD_FULL_PATTERN = re.compile(
    r'KANBAN\s+CARD\s+#(\d+)\s*\|\s*Session:\s*([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern 2: "card #N" or "#N" with "--session session-name" nearby
_CARD_SESSION_PATTERN = re.compile(
    r'(?:card\s+)?#(\d+)[^\n]*--session\s+([a-z0-9][a-z0-9-]*)',
    re.IGNORECASE,
)

# Pattern 3: Standalone card number with session on same or adjacent line
# e.g. "card #123" anywhere + "session noble-maple" anywhere
_CARD_BARE_PATTERN = re.compile(r'card\s+#(\d+)', re.IGNORECASE)
_SESSION_BARE_PATTERN = re.compile(r'[Ss]ession[:\s]+([a-z0-9][a-z0-9-]+)')

# Markers for enforcement bypasses in agent prompts
_SKILL_AGENT_BYPASS_RE = re.compile(r'^\s*SKILL_AGENT_BYPASS\s*$', re.MULTILINE)
_FOREGROUND_AUTHORIZED_RE = re.compile(r'^\s*FOREGROUND_AUTHORIZED\s*$', re.MULTILINE)


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------

_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB cap before rotation

# Hard ceiling on the length of a SINGLE logged line, applied before it is
# written to disk. Distinct from _LOG_MAX_BYTES above, which rotates the
# WHOLE FILE once its total size crosses a threshold — this one caps a
# single line.
#
# Note this is NOT primarily a classification-integrity fix (unlike the
# sibling cap in kanban-subagent-stop-hook.py's log_error()):
# hook-error-digest-hook.py's _CURATED_CLASSIFIERS_BY_FILENAME maps
# "kanban-pretool-hook-errors.log" to an EMPTY classifier list, so every
# line from this file already resolves via the generic fallback classifier
# regardless of truncation — there is no curated anchor phrase here that
# truncation could sever. The reason to cap is the whole-LINE re-read cost:
# hook-error-digest-hook.py aggregates this log under the same per-run
# PER_RUN_LINE_CAP (a per-run *line-count* cap, not a byte cap) as its
# siblings, so one pathological line (e.g. an oversized interpolated
# stderr/cwd/path field) would otherwise be re-read whole on every digest
# run until the next 10 MB rotation. Capped here, applied inside
# _write_log() so it covers both log_error() and log_info() in one place —
# _write_log() is this file's single shared writer, unlike
# kanban-subagent-stop-hook.py, which has two independent writer functions.
_LOG_MAX_LINE_CHARS = 4000


def _rotate_log_if_needed(path: Path) -> None:
    """Rotate path → path.1 when the file exceeds _LOG_MAX_BYTES. Never raises."""
    try:
        if path.exists() and path.stat().st_size >= _LOG_MAX_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            path.rename(rotated)
    except Exception:  # intentional: last-resort log utility must never raise
        pass


def _truncate_log_line(message: str) -> str:
    """Truncate a single log message to _LOG_MAX_LINE_CHARS.

    Appends an elision marker with the original length so a reader of the
    log knows the message was cut rather than assuming it is complete.
    Truncates the TAIL (keeps the first _LOG_MAX_LINE_CHARS characters) —
    see _LOG_MAX_LINE_CHARS above for why this file has no anchor-position
    concern to preserve.
    """
    if len(message) <= _LOG_MAX_LINE_CHARS:
        return message
    return message[:_LOG_MAX_LINE_CHARS] + f"... [truncated, {len(message)} chars total]"


def _write_log(path: Path, message: str) -> None:
    """Append a timestamped message to a log file. Never raises.

    Rotates the log file to <path>.1 when it exceeds _LOG_MAX_BYTES,
    then starts a fresh file (one backup generation kept). The message
    itself is capped to _LOG_MAX_LINE_CHARS before being written — see
    _truncate_log_line.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(path)
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        capped_message = _truncate_log_line(message)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {capped_message}\n")
    except Exception:  # intentional: last-resort log utility must never raise
        pass


def log_error(message: str) -> None:
    """Append an error to the hook error log. Never raises."""
    _write_log(ERROR_LOG_PATH, message)


def log_info(message: str) -> None:
    """Append an info message to the hook info log. Never raises."""
    _write_log(INFO_LOG_PATH, message)


# ---------------------------------------------------------------------------
# Card/session extraction
# ---------------------------------------------------------------------------

def extract_card_and_session(prompt: str) -> tuple[str, str] | None:
    """
    Parse card number and session ID from the agent prompt.

    Returns (card_number_str, session_id) or None if not found.
    Tries patterns from most to least specific.

    Multi-card safety: if Pattern 1 finds multiple KANBAN CARD headers (e.g. a
    prompt quoting a prior delegation or composing multiple cards), the extraction
    is ambiguous — acting on the first match could mutate the wrong card's
    agent_launch_pending flag. In that case, log a warning and return None so the
    clear callback is skipped entirely for that invocation.
    """
    # Pattern 1: "KANBAN CARD #N | Session: session-name"
    all_matches = _CARD_FULL_PATTERN.findall(prompt)
    if len(all_matches) > 1:
        log_error(
            f"extract_card_and_session: multiple KANBAN CARD headers found "
            f"({len(all_matches)} matches) — skipping clear callback to avoid "
            f"wrong-card mutation"
        )
        return None
    if len(all_matches) == 1:
        m = _CARD_FULL_PATTERN.search(prompt)
        return (m.group(1), m.group(2))

    # Pattern 2: "#N ... --session session-name" on same line
    m = _CARD_SESSION_PATTERN.search(prompt)
    if m:
        return (m.group(1), m.group(2))

    # Pattern 3: Combine bare card + bare session from anywhere in prompt
    card_m = _CARD_BARE_PATTERN.search(prompt)
    session_m = _SESSION_BARE_PATTERN.search(prompt)
    if card_m and session_m:
        return (card_m.group(1), session_m.group(1))

    return None


# ---------------------------------------------------------------------------
# Kanban card fetch
# ---------------------------------------------------------------------------

def fetch_card_xml(card_number: str, session: str) -> str | None:
    """
    Run `kanban show <card_number> --output-style=xml --session <session>`.
    Returns the XML string on success, None on any failure.
    """
    try:
        result = subprocess.run(
            ["kanban", "show", card_number, "--output-style=xml", "--session", session],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            log_error(
                f"kanban show #{card_number} failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
            return None
        output = result.stdout.strip()
        if not output:
            log_error(f"kanban show #{card_number} returned empty output")
            return None
        return output
    except subprocess.TimeoutExpired:
        log_error(f"kanban show #{card_number} timed out")
        return None
    except FileNotFoundError:
        log_error("kanban CLI not found in PATH")
        return None
    except Exception as exc:
        log_error(f"kanban show #{card_number} unexpected error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def inject_card_into_prompt(
    prompt: str,
    card_xml: str,
    card_number: str,
    session: str,
    progress_protocol_block: "str | None" = None,
) -> str:
    """
    Prepend the card XML to the agent prompt, separated by a clear boundary.

    The injected block is placed BEFORE the original prompt so the agent
    sees the card details immediately without having to call kanban show.

    progress_protocol_block, when provided (non-None, non-empty), is appended
    immediately after the card XML boundary and before the original prompt —
    see build_progress_protocol_block() for when this is populated.
    """
    header = (
        f"<!-- Kanban card #{card_number} (session: {session}) "
        f"injected by PreToolUse hook -->\n"
        f"{card_xml}\n"
        f"<!-- End of injected card content -->\n\n"
    )
    if progress_protocol_block:
        header += progress_protocol_block + "\n\n"
    return header + prompt


# Minimum number of <edit-files><f> entries required to trigger automatic
# progress-protocol injection. "More than one" per card #3428's design —
# a single-file card doesn't need cross-edit resumption bookkeeping.
_PROGRESS_PROTOCOL_MIN_EDIT_FILES = 2


def _count_edit_files_in_card_xml(card_xml: str) -> int:
    """
    Parse card_xml for <edit-files><f>...</f></edit-files> entries and
    return the count of non-empty entries, summed across every sibling
    <edit-files> element (card XML can carry more than one).

    Fails open: any parse failure (malformed XML, missing element, wrong
    type) returns 0 rather than raising. A 0 result simply means the
    progress-protocol block is not injected — this function must never be
    the reason an Agent launch is blocked or a hook crashes.
    """
    try:
        if not card_xml or not isinstance(card_xml, str):
            return 0
        root = ET.fromstring(card_xml)
        ef_els = root.findall("edit-files")
        if not ef_els:
            return 0
        return sum(
            len([f for f in ef_el.findall("f") if f.text and f.text.strip()])
            for ef_el in ef_els
        )
    except Exception as exc:
        # Fail-open is the design here, not an error condition — parse
        # failures simply mean no injection. Logged at INFO (not ERROR) so
        # this never pollutes the operator-facing error digest.
        log_info(f"_count_edit_files_in_card_xml: parse failure: {exc!r}")
        return 0


def build_progress_protocol_block(card_number: str) -> str:
    """
    Return the per-edit progress protocol block for card_number, with the
    card number substituted into the .scratchpad/<card>-progress.md path.

    Wording is sourced from
    modules/claude/global/output-styles/staff-engineer.md
    § Card Sizing and Scope ("Per-edit progress protocol block") — keep the
    two in sync if the wording ever changes; that section documents the
    manual-paste fallback for single-file cards, this function is the
    automatic-injection path for multi-file cards (see
    _PROGRESS_PROTOCOL_MIN_EDIT_FILES).
    """
    return (
        "PROGRESS PROTOCOL (mandatory):\n"
        f"Before starting each file edit, read .scratchpad/{card_number}-progress.md.\n"
        "If the file exists and lists files as DONE, skip those — resume at the\n"
        "next un-DONE target.\n"
        "\n"
        "After completing each file edit, IMMEDIATELY append `DONE: <file-path>` to\n"
        f".scratchpad/{card_number}-progress.md BEFORE starting the next edit. Every single\n"
        "edit. Not at milestones. Not at section boundaries. Not at \"natural break\n"
        "points.\" Per-edit, no exceptions.\n"
        "\n"
        "If you stall or context-exhausts mid-turn, the continuation agent reads\n"
        "this file and resumes from the next un-DONE path. Missing a progress write\n"
        "means duplicated work at best, lost work at worst."
    )


def _resolve_progress_protocol_block(card_xml: str, card_number: str) -> "str | None":
    """
    Decide whether to inject the automatic progress-protocol block for this
    card, and return it (or None).

    Returns None when either:
    - card_xml already contains the literal string "PROGRESS PROTOCOL" —
      the coordinator hand-pasted the block into the card's action text
      already, so injecting again would duplicate the instructions; or
    - fewer than _PROGRESS_PROTOCOL_MIN_EDIT_FILES <edit-files><f> entries
      are present (see _count_edit_files_in_card_xml).

    This is the sole decision boundary main() consults — tests exercise it
    directly rather than only through the end-to-end main() path, so that
    removing or weakening the threshold check fails a test.
    """
    if "PROGRESS PROTOCOL" in card_xml:
        return None
    edit_files_count = _count_edit_files_in_card_xml(card_xml)
    if edit_files_count < _PROGRESS_PROTOCOL_MIN_EDIT_FILES:
        return None
    return build_progress_protocol_block(card_number)


# ---------------------------------------------------------------------------
# .kanban/ path guard (Edit, Write, MultiEdit, NotebookEdit, Bash)
# ---------------------------------------------------------------------------

# The protected directory prefix. Confirmed in modules/kanban/kanban.py line 215:
# `root = base_dir / ".kanban"`
_KANBAN_DIR = ".kanban"

# Bash commands that identify the kanban CLI — always allowed even if the
# argument string mentions .kanban/ paths.
# Anchored to start-of-command with negative lookahead to prevent false positives:
#   - `kanban-foo write .kanban/file.json` → NOT matched (kanban-prefixed binary)
#   - `nix-shell -p kanban -c '...'`       → NOT matched (kanban as flag arg)
#   - `echo 'kanban'`                       → NOT matched (kanban as shell text)
# Correctly matches:
#   - `kanban list`                                     → matched
#   - `kanban criteria check 1 2 --session free-brook`  → matched
#   - `/nix/store/abc123-kanban/bin/kanban list`        → matched
#   - `.kanban-wrapped list`                            → matched
# The negative lookahead `(?![-\w])` ensures `kanban` is NOT followed by `-` or
# alphanumeric characters — so `kanban-foo` does not match (hyphen-prefixed binary).
_KANBAN_CLI_RE = re.compile(
    r'^\s*(?:kanban(?![-\w])|\.kanban-wrapped\b|/[^\s]*/bin/kanban\b)',
)

# Regex patterns for Bash mutation operations targeting .kanban/
# Each pattern is compiled case-insensitively. All use raw string literals.
# Note: patterns use \b word boundary instead of trailing / to also catch
# references like `.kanban` without a trailing slash (e.g. os.chdir(".kanban")).
_KANBAN_BASH_DENY_PATTERNS: list[re.Pattern] = [
    # shell redirection writing to .kanban/
    re.compile(r'(>|>>)\s*\.?\.?/?\.?/?\.?kanban/', re.IGNORECASE),
    # in-place edits via sed
    re.compile(r'\bsed\s+(-i|--in-place)\b.*\.kanban\b', re.IGNORECASE),
    # awk to .kanban/
    re.compile(r'\bawk\b.*>\s*.*\.kanban\b', re.IGNORECASE),
    # jq in-place mutation (--argfile is a read, not a write — excluded)
    re.compile(r'\bjq\b.*-i.*\.kanban\b', re.IGNORECASE),
    # python invocations referencing .kanban (with or without trailing slash)
    re.compile(r'\bpython3?\s+(-c|-m).*\.kanban\b', re.IGNORECASE),
    # perl in-place
    re.compile(r'\bperl\s+(-i|-pe).*\.kanban\b', re.IGNORECASE),
    # file moves/deletes/links — ln and link create symlinks (symlink bypass)
    re.compile(r'\b(rm|mv|cp|ln|link)\b.*\.kanban/', re.IGNORECASE),
    # cp -s / cp --symbolic creates a symlink (separate pattern for flag order)
    re.compile(r'\bcp\s+(-s|--symbolic)\b.*\.kanban\b', re.IGNORECASE),
    # tee
    re.compile(r'\btee\s+.*\.kanban\b', re.IGNORECASE),
]

_KANBAN_PATH_DENY_MESSAGE = (
    "Direct file modification of .kanban/ is prohibited. "
    "Use the kanban CLI: `kanban criteria check`, `kanban criteria uncheck`, etc. "
    "If the AC is broken, stop and report — do not work around it."
)


def _is_under_kanban_dir(path_str: str) -> bool:
    """Return True if path_str is under the .kanban/ directory.

    Handles both absolute paths and relative paths. Does not resolve symlinks
    (intentional: we check the literal path the tool was given, not what it
    resolves to — an agent providing a .kanban/ path is always suspicious).
    """
    if not path_str:
        return False
    p = Path(path_str)
    # Check each component — handles both relative (.kanban/foo) and
    # absolute paths that contain .kanban/ anywhere in the hierarchy.
    parts = p.parts
    return _KANBAN_DIR in parts or (len(parts) > 0 and parts[0] == _KANBAN_DIR)


def _is_kanban_cli_command(command: str) -> bool:
    """Return True if the Bash command invokes the kanban CLI binary.

    The kanban CLI is always allowed — even if its arguments reference .kanban/
    paths (e.g., `kanban show` reads from .kanban/ internally). Checks for:
    - `kanban <args>` at the start of the command (anchored — NOT mid-string)
    - `.kanban-wrapped <args>` (the nix shim)
    - Any nix-store path ending in `/bin/kanban` at start of command

    Anchored to start-of-command to prevent false positives:
    - `kanban-foo write .kanban/file.json` → False (different binary)
    - `nix-shell -p kanban -c '...'` → False (kanban as a flag argument)
    - `echo 'kanban'` → False (kanban as shell text, no .kanban/ involved)
    """
    return bool(_KANBAN_CLI_RE.search(command))


def _check_kanban_path_guard(tool_name: str, tool_input: dict) -> "tuple[bool, str]":
    """Check whether a tool call targets a path under .kanban/.

    Returns (allowed: bool, reason: str).
    - allowed=True  → tool call is permitted; reason is empty.
    - allowed=False → tool call must be denied; reason explains why.

    Rules:
    - Edit/Write/MultiEdit on .kanban/* → DENY
    - NotebookEdit on .kanban/* → DENY
    - Bash invoking the kanban CLI → ALLOW unconditionally (checked first)
    - Bash with mutation patterns targeting .kanban/ → DENY
    - All reads (cat, rg, ls, etc.) targeting .kanban/ → ALLOW (no path guard)
    - All other tools → ALLOW

    # Known regex limitations: this guard cannot catch every Bash bypass.
    # Examples that evade detection (caught instead by the prompt-level
    # prohibition in modules/claude/global/agents/*.md):
    #   - `cd .kanban/doing && python3 -c '...'` (cd first, then mutate)
    #   - `K=.kanban; sed -i 's/x/y/' $K/foo.json` (var substitution)
    #   - `bash -c 'echo x > .kanban/foo'` (extra shell layer)
    # The prompt-level rule is the primary defense; this regex is a backstop.
    """
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "") or ""
        if _is_under_kanban_dir(file_path):
            return (False, _KANBAN_PATH_DENY_MESSAGE)
        return (True, "")

    if tool_name == "MultiEdit":
        file_path = tool_input.get("file_path", "") or ""
        if _is_under_kanban_dir(file_path):
            return (False, _KANBAN_PATH_DENY_MESSAGE)
        return (True, "")

    if tool_name == "NotebookEdit":
        notebook_path = tool_input.get("notebook_path", "") or ""
        if _is_under_kanban_dir(notebook_path):
            return (False, _KANBAN_PATH_DENY_MESSAGE)
        return (True, "")

    if tool_name == "Bash":
        command = tool_input.get("command", "") or ""
        # Kanban CLI allowlist: always permit kanban commands even if they
        # reference .kanban/ paths internally.
        if _is_kanban_cli_command(command):
            return (True, "")
        # Check for mutation patterns targeting .kanban/
        for pattern in _KANBAN_BASH_DENY_PATTERNS:
            if pattern.search(command):
                return (False, _KANBAN_PATH_DENY_MESSAGE)
        return (True, "")

    return (True, "")


# ---------------------------------------------------------------------------
# Destructive git operation validation (Bash tool calls from sub-agents)
# ---------------------------------------------------------------------------

# Shell operator tokens used to split compound commands.
_SHELL_OPS = frozenset(["&&", "||", ";", "|", "&"])


def _is_sub_agent(payload: dict) -> bool:
    """Return True if this hook call comes from inside a sub-agent.

    Claude Code populates 'agent_id' in the hook payload only when the hook
    fires inside a subagent call. The field is absent in main-session calls.

    RELIABILITY NOTE (verified against Claude Code 2.1.118, 2026-04-23):
    This is a single-point-of-failure. If 'agent_id' is ever absent from a
    sub-agent payload (version regression, format change) or present in a
    main-session payload (future session IDs), the safeguard silently bypasses.
    Recommend revisiting on major Claude Code version bumps to verify the
    'agent_id' field remains a reliable sub-agent discriminator.
    """
    return bool(payload.get("agent_id"))


def _normalize_semicolons(tokens: list) -> list:
    """Expand tokens that embed bare semicolons into separate operator tokens.

    shlex.split does not treat ';' as an operator — it merges it with adjacent
    content when there is no surrounding whitespace (e.g., 'cmd;next'). This
    function splits those embedded semicolons so _split_on_shell_ops can
    correctly identify command segment boundaries.
    """
    result = []
    for tok in tokens:
        if ';' not in tok:
            result.append(tok)
            continue
        parts = tok.split(';')
        for i, part in enumerate(parts):
            if part:
                result.append(part)
            if i < len(parts) - 1:
                result.append(';')
    return result


def _split_on_shell_ops(tokens: list) -> list:
    """Split token list on shell control operators into command segments."""
    segments = []
    current = []
    for tok in tokens:
        if tok in _SHELL_OPS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _tokenize_command(command: str) -> list:
    """Tokenize a shell command string using shlex, splitting on operators.

    Returns a list of segments where each segment is a list of tokens.
    Fails open (returns empty list) on shlex errors.
    """
    if not command or not command.strip():
        return []
    segments_out = []
    for line in command.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            # Unterminated quotes or other shlex error — fail open
            continue
        tokens = _normalize_semicolons(tokens)
        segments_out.extend(_split_on_shell_ops(tokens))
    return segments_out


# Result type for destructive op detection:
#   "stash_drop"         → unconditional denial (no file target)
#   "stash_push"         → unconditional denial for sub-agents (moves entire working tree)
#   list[str]            → file paths that are targets of destructive ops
#   None                 → no destructive op detected (allow)
def _extract_destructive_git_targets(segment: list) -> "str | list | None":
    """Analyse a single tokenized command segment for destructive git ops.

    Returns:
        "stash_drop"  — if the segment is `git stash drop` (unconditional denial)
        "stash_push"  — if the segment is `git stash` / `git stash push` /
                        `git stash save` / `git stash --keep-index` (unconditional
                        denial for sub-agents — moves entire working tree into stash,
                        hiding files from parallel cards; editFiles-based scoping is
                        inapplicable because there are no file targets)
        list[str]     — file paths targeted by a destructive op (may be empty if
                        the op takes files but none were parsed, treated as safe)
        None          — not a destructive git op
    """
    if not segment or segment[0] != "git":
        return None

    if len(segment) < 2:
        return None

    subcmd = segment[1]

    # git stash drop — no file target; unconditional denial
    if subcmd == "stash" and len(segment) >= 3 and segment[2] == "drop":
        return "stash_drop"

    # git stash push / git stash save / git stash (bare) / git stash --keep-index
    # These all move the entire working tree into a stash, hiding files from parallel
    # cards. editFiles-based scoping is inapplicable — block unconditionally for
    # sub-agents. Non-destructive read forms (pop, apply, list, show) are not here.
    if subcmd == "stash":
        # Bare `git stash` with no subcommand (len == 2): equivalent to push
        if len(segment) == 2:
            return "stash_push"
        third = segment[2]
        # push, save, or --keep-index (with or without additional flags/args)
        if third in ("push", "save", "--keep-index"):
            return "stash_push"
        # `git stash --keep-index` may appear as a top-level flag before any
        # subcommand (e.g. `git stash --keep-index --include-untracked`)
        if "--keep-index" in segment[2:]:
            return "stash_push"

    # git checkout: destructive only with '--' flag or '-p' flag with file arg.
    # git checkout <branch> and git checkout -b <branch> are NOT destructive.
    if subcmd == "checkout":
        rest = segment[2:]
        if "--" in rest:
            # git checkout -- [files...]
            dd_idx = rest.index("--")
            files = rest[dd_idx + 1:]
            return files if files else []
        if "-p" in rest:
            # git checkout -p [file] — interactive hunk revert
            p_idx = rest.index("-p")
            files = [t for t in rest[p_idx + 1:] if not t.startswith("-")]
            # If no explicit file, treat as potentially any file — block
            return files if files else ["<interactive-hunk-revert>"]
        # Non-destructive: branch switch, -b, etc.
        return None

    # git restore [--staged] <file>
    if subcmd == "restore":
        rest = segment[2:]
        files = [t for t in rest if not t.startswith("-")]
        return files if files else []

    # git reset -- <file> and git reset HEAD -- <file>
    # Special case: git reset --hard unconditionally reverts all tracked files.
    # Only detect file-targeted resets when '--' separator is explicitly present to
    # avoid false-positives on mode resets like `git reset --soft HEAD~1`.
    if subcmd == "reset":
        rest = segment[2:]
        if "--hard" in rest:
            # git reset --hard reverts ALL tracked files — no file target needed
            return ["<all-tracked>"]
        if "--" in rest:
            dd_idx = rest.index("--")
            files = rest[dd_idx + 1:]
            return files if files else []
        # Without '--', we cannot reliably distinguish file args from tree-ish refs.
        # Fail open to avoid blocking legitimate mode resets (e.g. --soft, --mixed).
        # Known gap: `git reset HEAD <file>` (without --) is not detected.
        return None

    # git clean [-f] [-d] [--] [<file>...] / git clean -fd
    if subcmd == "clean":
        rest = segment[2:]
        files = [t for t in rest if not t.startswith("-")]
        # Remove '--' separator if present
        files = [f for f in files if f != "--"]
        # Even with no file target, git clean is destructive
        return files if files else ["<all-untracked>"]

    return None


def _parse_destructive_git_ops(command: str) -> list:
    """Parse a (possibly compound) shell command for destructive git operations.

    Returns a list of (segment_tokens, result) tuples where result is either
    "stash_drop" or a list of file path strings.  Returns empty list when no
    destructive ops are detected.

    Fails open (returns empty list) on any parsing error.
    """
    findings = []
    try:
        segments = _tokenize_command(command)
        for seg in segments:
            result = _extract_destructive_git_targets(seg)
            if result is not None:
                findings.append((seg, result))
    except Exception as e:
        log_error(f"destructive-git parse failure: {e!r}")
        return []
    return findings


def _fetch_doing_card_for_session(session_id: str) -> "tuple[str, list[str]] | None":
    """Fetch the 'doing' kanban card for the given session.

    Returns (card_number, edit_files_list) or None on any failure.
    edit_files_list is a (possibly empty) list of path strings from <edit-files>.
    """
    try:
        result = subprocess.run(
            ["kanban", "list", "--session", session_id, "--column", "doing",
             "--output-style=xml"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # ANOMALOUS: the kanban CLI itself failed (crash, outage, etc).
            # Distinct from the benign "no card in doing" case below — an
            # operator needs to know infrastructure is failing, not just that
            # a lookup came back empty.
            log_error(
                f"kanban CLI failed for session={session_id!r}: "
                f"kanban list exited {result.returncode}, "
                f"stderr={result.stderr.strip()[:500]!r}"
            )
            return None
        if not result.stdout.strip():
            # BENIGN: the session genuinely has no card in 'doing'. Common,
            # expected, and not worth error-log noise.
            return None
        root = ET.fromstring(result.stdout.strip())
        # Find the first card element anywhere in the XML
        card_el = root.find(".//c")
        if card_el is None:
            return None
        card_number = card_el.get("n", "")
        if not card_number:
            return None
        # The list output doesn't include edit-files — fetch the full card
        return _fetch_card_editfiles(card_number, session_id)
    except Exception as e:
        log_error(f"_fetch_doing_card_for_session failed for session={session_id!r}: {e!r}")
        return None


def _fetch_card_editfiles(card_number: str, session_id: str) -> "tuple[str, list[str]] | None":
    """Fetch edit-files for a specific card via kanban show.

    Returns (card_number, edit_files_list) or None on failure.
    """
    try:
        result = subprocess.run(
            ["kanban", "show", card_number, "--output-style=xml", "--session", session_id],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # ANOMALOUS: the kanban CLI itself failed (crash, outage, etc).
            # Distinct from the benign "card has no edit-files" case below —
            # an operator needs to know infrastructure is failing, not just
            # that a lookup came back empty.
            log_error(
                f"kanban CLI failed for card={card_number}: "
                f"kanban show exited {result.returncode}, "
                f"stderr={result.stderr.strip()[:500]!r}"
            )
            return None
        if not result.stdout.strip():
            # BENIGN: the card lookup returned nothing to parse. Common,
            # expected, and not worth error-log noise.
            return None
        root = ET.fromstring(result.stdout.strip())
        ef_el = root.find("edit-files")
        if ef_el is None:
            return (card_number, [])
        files = [f.text.strip() for f in ef_el.findall("f") if f.text and f.text.strip()]
        return (card_number, files)
    except Exception as e:
        log_error(f"_fetch_card_editfiles failed for card={card_number}: {e!r}")
        return None


def _normalize_path(path_str: str, cwd: str) -> str:
    """Normalize a target path string to a relative path from cwd.

    Absolute paths are made relative to cwd. Relative paths are kept as-is
    (already relative to cwd for comparison purposes).

    Path.resolve() is called on both arguments before comparison to canonicalize
    dot-segments (e.g. a/b/../c → a/c) and resolve symlinks. If resolve() fails
    (e.g. symlink loop, permission error), falls back to the unresolved path.
    """
    p = Path(path_str)
    if p.is_absolute():
        try:
            resolved_p = p.resolve()
            resolved_cwd = Path(cwd).resolve()
            return str(resolved_p.relative_to(resolved_cwd))
        except OSError:
            # resolve() failed (e.g. symlink loop) — fall back to unresolved comparison
            log_error(f"_normalize_path: resolve() failed for {path_str!r}, falling back to unresolved")
        except ValueError:
            # Path is outside cwd — return as-is for rejection
            pass
        return path_str
    return path_str


def _file_in_editfiles(target: str, edit_files: list, cwd: str) -> bool:
    """Return True if target matches any pattern in edit_files.

    Uses fnmatch for glob support. Compares normalized (relative) paths.

    Glob matching notes:
    - fnmatch '*' does NOT cross path separators (e.g. '*.py' won't match 'src/foo.py'
      via primary check, but WILL match via the basename fallback below).
    - The basename fallback is ONLY applied when the pattern contains no path separator.
      This prevents 'foo.py' (intended as a root-level filename) from matching
      'src/foo.py' or 'deep/nested/foo.py' — which would be over-permissive.
    - '**' globstar is NOT supported by fnmatch and will silently never match.
      Card authors wanting recursive matches should use bare filename patterns like
      '*.py' (matches via basename fallback) or list files explicitly.
    """
    normalized = _normalize_path(target, cwd)
    for pattern in edit_files:
        # Primary match: full normalized path against pattern
        if fnmatch.fnmatch(normalized, pattern):
            return True
        # Basename fallback: only for glob patterns (containing * or ?) that have no path
        # separator. This lets '*.py' match the basename of 'src/foo.py', while preventing
        # a plain filename like 'foo.py' from incorrectly matching 'src/foo.py' (over-permission).
        # Gated on two conditions:
        #   1. Pattern has no '/' — prevents path-qualified patterns from using basename fallback.
        #   2. Pattern contains '*' or '?' — prevents plain filenames from over-matching.
        # Note: '**' globstar is NOT supported by fnmatch and will silently never match.
        # Card authors wanting recursive matches should use '*.py' (matches via this fallback)
        # or list files explicitly.
        has_glob = "*" in pattern or "?" in pattern
        if "/" not in pattern and has_glob and fnmatch.fnmatch(Path(normalized).name, pattern):
            return True
    return False


def _validate_bash_destructive_git(payload: dict) -> "dict | None":
    """Validate a Bash tool call for destructive git operations on out-of-scope files.

    Returns a deny response dict if the command should be blocked, or None to allow.

    Rules:
    - Only applies when running inside a sub-agent (agent_id present in payload).
    - Non-coordinator sessions are handled upstream (early return in main).
    - Parses the command for destructive git ops.
    - Fetches the doing card's editFiles for the sub-agent's session.
    - Rejects if any target file is not in editFiles.
    - git stash drop → rejected unconditionally (no file target, global destruction).
    - git stash / git stash push / git stash save / git stash --keep-index → rejected
      unconditionally for sub-agents (moves entire working tree; no editFiles scoping possible).
    - git reset --hard → rejected unconditionally (reverts ALL tracked files).
    - git checkout -p (no file) → rejected unconditionally (interactive session blocked).

    Fails-open paths (any of these allows the op through without blocking):
    1. shlex parse error in _tokenize_command: unterminated quotes cause that line to be
       skipped (fail open) — ensures a parse bug never blocks legitimate work.
    2. kanban lookup failure: if _fetch_doing_card_for_session raises or returns None,
       the check is skipped with a log_error call. A sustained kanban outage creates a
       bypass window; monitor log_error calls for operational awareness.
    3. Exception in _parse_destructive_git_ops: any unexpected error during op detection
       returns an empty findings list (allow), logged via log_error.

    The fail-open design is intentional: this is a defense-in-depth layer, not the
    primary access control. Infrastructure failures must not block legitimate sub-agent work.
    """
    if not _is_sub_agent(payload):
        return None  # Main session — bypass

    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return None

    findings = _parse_destructive_git_ops(command)
    if not findings:
        return None

    # Lazy-load card info only if destructive ops were found
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")

    card_info = None
    if session_id:
        card_info = _fetch_doing_card_for_session(session_id)

    for seg, result in findings:
        cmd_repr = " ".join(seg)

        if result == "stash_drop":
            card_num = card_info[0] if card_info else "unknown"
            reason = (
                f"DENIED: `{cmd_repr}` — `git stash drop` is unconditionally blocked for sub-agents.\n"
                f"Card: #{card_num}\n"
                "git stash drop destroys stashed changes that may contain uncommitted work from other cards.\n"
                "If a stash is blocking you, STOP and report the issue in your final return — "
                "do not destroy stash contents outside your card's scope."
            )
            log_info(f"Bash denied — git stash drop from sub-agent session={session_id!r}")
            return deny_with_reason(reason)

        if result == "stash_push":
            card_num = card_info[0] if card_info else "unknown"
            reason = (
                f"DENIED: `{cmd_repr}` — `git stash` is a destructive cross-card operation "
                f"(moves working-tree files into a stash, hiding them from parallel cards). "
                f"Sub-agents MUST NEVER run `git stash` / `git stash push` / `git stash save`.\n"
                f"Card: #{card_num}\n"
                "If an AC failure seems to require stashing, STOP and report in your final return — "
                "the MoV is the issue, not the working tree."
            )
            log_info(f"Bash denied — git stash push/save/bare from sub-agent session={session_id!r}")
            return deny_with_reason(reason)

        # result is a list of file paths (possibly with sentinel values)
        file_targets = result

        # Handle <interactive-hunk-revert> sentinel: git checkout -p with no file arg.
        # This is blocked unconditionally — not because the file is out of scope, but
        # because launching an interactive session is incompatible with sub-agent execution.
        if file_targets == ["<interactive-hunk-revert>"]:
            card_num = card_info[0] if card_info else "unknown"
            reason = (
                f"DENIED: `{cmd_repr}` — `git checkout -p` launches an interactive hunk-revert "
                f"session and is blocked for sub-agents regardless of editFiles.\n"
                f"Card: #{card_num}\n"
                "Interactive sessions cannot run inside a sub-agent. Surface the underlying scope "
                "issue in your final return instead of reverting."
            )
            log_info(f"Bash denied — git checkout -p (interactive) from sub-agent session={session_id!r}")
            return deny_with_reason(reason)

        # Handle <all-tracked> sentinel: git reset --hard reverts ALL tracked files.
        # Always blocked for sub-agents — no editFiles check needed.
        if "<all-tracked>" in file_targets:
            card_num = card_info[0] if card_info else "unknown"
            reason = (
                f"DENIED: `{cmd_repr}` — `git reset --hard` reverts ALL tracked files and is "
                f"always out of scope for a card-bounded sub-agent.\n"
                f"Card: #{card_num}\n"
                "This operation would revert files outside your card's editFiles scope.\n"
                "If an AC is failing, STOP and report the broken AC in your final return — "
                "do not revert the entire working tree."
            )
            log_info(f"Bash denied — git reset --hard from sub-agent session={session_id!r}")
            return deny_with_reason(reason)

        if not file_targets:
            # Destructive op but no parseable file targets (e.g. git clean <all>)
            card_num = card_info[0] if card_info else "unknown"
            card_ef = card_info[1] if card_info else []
            reason = (
                f"DENIED: `{cmd_repr}` — destructive git operation with no specific file target.\n"
                f"Card: #{card_num}\n"
                f"Card editFiles: {card_ef if card_ef else '(none listed)'}\n"
                "Destructive operations that affect the whole working tree are blocked for sub-agents.\n"
                "If an AC is failing, STOP and report the broken AC in your final return — "
                "do not attempt to revert or clean files outside your card's scope."
            )
            log_info(f"Bash denied — destructive git op (no file target) from sub-agent session={session_id!r}")
            return deny_with_reason(reason)

        # Check each file against editFiles
        if card_info is None:
            # Could not fetch card info — fail open (do not block)
            log_error(f"Could not fetch card for session={session_id!r} — skipping destructive git check")
            return None

        card_num, edit_files = card_info

        if not edit_files:
            # Card has no editFiles defined — block all destructive ops
            reason = (
                f"DENIED: `{cmd_repr}` — destructive git operation on file(s) that are NOT in card editFiles.\n"
                f"Card: #{card_num}\n"
                f"Card editFiles: (none listed)\n"
                f"Target file(s): {file_targets}\n"
                "This kind of destructive operation on out-of-scope files has caused data loss.\n"
                "If an AC is failing because of this file's state, STOP and report the broken AC in your "
                "final return — do not revert files outside your card's scope."
            )
            log_info(f"Bash denied — destructive git op on {file_targets}, card #{card_num} has no editFiles, session={session_id!r}")
            return deny_with_reason(reason)

        out_of_scope = [
            f for f in file_targets
            if not _file_in_editfiles(f, edit_files, cwd)
        ]

        if out_of_scope:
            reason = (
                f"DENIED: `{cmd_repr}` — target file(s) are NOT in card #{card_num} editFiles.\n"
                f"Out-of-scope file(s): {out_of_scope}\n"
                f"Card editFiles: {edit_files}\n"
                "This kind of destructive operation on out-of-scope files has caused data loss.\n"
                "If an AC is failing because of this file's state, STOP and report the broken AC in your "
                "final return — do not revert files outside your card's scope."
            )
            log_info(f"Bash denied — destructive git op on out-of-scope files {out_of_scope}, card #{card_num}, session={session_id!r}")
            return deny_with_reason(reason)

    return None  # All checks passed — allow


# ---------------------------------------------------------------------------
# rm safety guard (Bash tool calls from sub-agents)
# ---------------------------------------------------------------------------
#
# GitHub issue #17. Two confirmed occurrences of a sub-agent deleting its own
# scratchpad file mid-card; the second happened despite an explicit prose
# no-rm restriction in that card's prompt. This is an additional check in the
# existing Bash-validation shape (see "Destructive git operation validation"
# above), reusing the same tokenizer and the same agent_id gating via
# _is_sub_agent — not new infrastructure.
#
# SCOPE (decided — see card #3535, do not re-litigate):
#   DENY (a) any `rm` whose target path touches .scratchpad/, and
#   DENY (b) any RECURSIVE `rm` (-r, -R, -rf, --recursive, and combined
#            short-flag spellings) regardless of target.
#   ALLOW non-recursive `rm` of a named file that is not under .scratchpad/ —
#   an implementation agent legitimately deletes a deprecated file; a blanket
#   deny would break that and push agents toward workarounds.
#
# Deliberately OUT OF SCOPE for this check: `find -delete`, `truncate`, and
# clobbering shell redirection. Omitted by decision, not oversight.

_SCRATCHPAD_DIR = ".scratchpad"

_RM_SCRATCHPAD_DENY_MESSAGE = (
    "DENIED: `rm` targeting .scratchpad/ is blocked for sub-agents.\n"
    ".scratchpad/ is auto-pruned (entries older than 90 days) by the "
    "SessionStart hook, so deleting from it buys nothing — and it is shared "
    "across concurrent sessions, so the file you're targeting may belong to "
    "another card's in-flight findings.\n"
    "Leave the file in place. If you believe it is genuinely blocking your "
    "work, STOP and report the conflict in your final return instead of "
    "deleting it."
)

_RM_RECURSIVE_DENY_MESSAGE = (
    "DENIED: recursive `rm` (-r, -R, -rf, --recursive, or a combined "
    "short-flag spelling) is blocked for sub-agents.\n"
    "Recursive delete is denied outright — a single recursive rm can erase "
    "an entire directory tree in one shot with no confirmation step and no "
    "undo, which is too large a blast radius for an agent operating without "
    "an interactive user to catch a mistake.\n"
    "This is not a signal to work around it by deleting the same files one "
    "at a time — if a directory genuinely needs to go, STOP and report the "
    "conflict in your final return instead of finding another way to delete it."
)


def _is_under_scratchpad_dir(path_str: str) -> bool:
    """Return True if path_str is under the .scratchpad/ directory.

    Handles both absolute paths and relative paths, mirroring
    _is_under_kanban_dir. Does not resolve symlinks — the literal path the
    tool was given is what matters here.
    """
    if not path_str:
        return False
    p = Path(path_str)
    parts = p.parts
    return _SCRATCHPAD_DIR in parts or (len(parts) > 0 and parts[0] == _SCRATCHPAD_DIR)


def _rm_segment_is_recursive(segment: list) -> bool:
    """Return True if an `rm` command segment carries a recursive flag.

    Detects `-r`, `-R`, `--recursive` (with or without `=value`), and any
    combined short-flag cluster containing `r`/`R` (e.g. `-rf`, `-fr`, `-Rf`).
    `rm`'s short options are limited to the letters f, i, I, r, R, d, v — so
    checking for `r`/`R` anywhere in a single-dash cluster is safe and cannot
    false-positive on an unrelated long-flag word.

    Stops scanning a segment once a bare `--` end-of-options marker is seen,
    since everything after that is a filename, not a flag.
    """
    for tok in segment[1:]:
        if tok == "--":
            break
        if tok == "--recursive" or tok.startswith("--recursive="):
            return True
        if tok.startswith("--"):
            continue  # other long flags — not recursive unless matched above
        if tok.startswith("-") and len(tok) > 1:
            if "r" in tok[1:].lower():
                return True
    return False


def _rm_segment_targets(segment: list) -> list:
    """Return the non-flag target tokens (file paths) from an `rm` segment.

    Everything after a bare `--` is treated as a target regardless of its
    leading character. Before `--`, any token starting with `-` (and longer
    than just `-`) is treated as a flag, not a target.
    """
    targets = []
    seen_dashdash = False
    for tok in segment[1:]:
        if tok == "--":
            seen_dashdash = True
            continue
        if not seen_dashdash and tok.startswith("-") and tok != "-":
            continue
        targets.append(tok)
    return targets


def _is_assignment_token(tok: str) -> bool:
    """Return True if tok looks like a shell VAR=VALUE assignment.

    Used to skip `env`'s own leading assignment tokens (e.g. `env FOO=bar rm
    ...`) so the wrapper-stripping walk reaches the real command.
    """
    if "=" not in tok:
        return False
    name = tok.split("=", 1)[0]
    return bool(name) and (name[0].isalpha() or name[0] == "_") and all(
        c.isalnum() or c == "_" for c in name
    )


# ---------------------------------------------------------------------------
# Wrapper-own-flag handling (GitHub issue #29 / card #3550)
#
# DESIGN DECISION (do not re-propose the rejected alternative below without
# re-reading this comment first):
#
# Chosen shape — (a) enumerate each wrapper's own flags explicitly, mirroring
# how the xargs branch already skips its leading dash-prefixed tokens.
#
# Rejected alternative: (b) invert the test — instead of naming each
# wrapper's flags, scan forward for the first token that is *not* a known
# wrapper name, *not* dash-prefixed, and *not* a VAR=VAL assignment, and
# treat THAT as the real command. This looks more general (closes the whole
# class instead of one flag at a time) but was rejected because `env` has
# flags that consume a FOLLOWING token as their argument (`-u NAME`,
# `-C DIR`, `-a ARGV0`, `-S STRING` — confirmed via `env --help`, GNU
# coreutils). A "skip leading dash-tokens" loop stops at `VARNAME` in
# `env -u VARNAME rm ...` because `VARNAME` does not start with a dash — it
# lands on `VARNAME` as the supposed real command, not `rm`, which is just a
# different flavor of the same evasion this fix exists to close. Closing
# that gap requires knowing WHICH flags consume a following argument, which
# is exactly the per-flag enumeration (a) already requires. Since (b) cannot
# be implemented correctly without the same enumeration, it is (a) wearing a
# more-general-looking shape, not a cheaper alternative — so (a) was kept
# for its directness and auditability.
# ---------------------------------------------------------------------------

# env's short flags that consume the NEXT token as a separate argument (per
# `env --help`, GNU coreutils): -a ARGV0, -u NAME, -C DIR, -S STRING. Every
# other env flag (-i, -0, -v, bare `-`, and all --long forms) is either
# argument-free or carries its argument attached via `=` in the same token
# (e.g. `--unset=NAME`), so none of those need a following token skipped.
_ENV_ARG_TAKING_SHORT_FLAGS = frozenset(["-a", "-u", "-C", "-S"])


def _strip_env_flags(seg: list) -> list:
    """Skip env's own flags and VAR=VAL assignments, landing on the real command.

    Called with the tokens AFTER the leading `env` token already removed.
    Handles:
      - VAR=VAL assignments (delegates to _is_assignment_token)
      - `--` end-of-options marker (consumed, then stop scanning)
      - any `--long` form (bare or =value-attached): a single token, skipped
      - bare `-` (implies -i): a single token, skipped
      - Bundled short-flag clusters — a single dash-prefixed token may pack
        several of env's short flags together (POSIX-style bundling, e.g.
        `-iu`, `-ia`, `-i0u`), and GNU env genuinely parses them that way
        (confirmed against the real binary: `env -iu FOO echo x` and
        `env -iuFOO echo x` both ran `echo x`, GNU coreutils 9.8). This
        function walks each character of the cluster left to right:
          - a char whose flag (-a, -u, -C, -S) takes an argument consumes
            everything remaining IN THE SAME TOKEN as its attached argument
            (e.g. the `FOO` in `-iuFOO`); if nothing remains in the token,
            the NEXT token is consumed as its separate-token argument
            (e.g. the `FOO` in `-iu FOO`) — either way parsing of the
            cluster stops there, since GNU env's own bundling stops at the
            first arg-taking flag too
          - every other char (-i, -0, -v) is a no-arg flag and simply
            advances to the next character in the same token
        This single code path also covers the single-flag case (e.g. `-u`,
        `-C`) — a one-character cluster — so no separate exact-match branch
        is needed for the unbundled forms.
    Stops at the first token that is none of the above — that token is the
    real command (or a further wrapper, handled by the outer loop).
    """
    while seg:
        tok = seg[0]
        if _is_assignment_token(tok):
            seg = seg[1:]
            continue
        if tok == "--":
            seg = seg[1:]
            break
        if tok == "-":
            seg = seg[1:]
            continue
        if tok.startswith("--"):
            seg = seg[1:]
            continue
        if tok.startswith("-") and len(tok) > 1:
            # Bundled short-flag cluster (see docstring). Walk the chars
            # after the leading '-' to find whether an arg-taking flag
            # appears, and whether its argument is attached in this same
            # token or must be pulled from the next token.
            consume_next_token = False
            chars = tok[1:]
            for i, ch in enumerate(chars):
                if ("-" + ch) in _ENV_ARG_TAKING_SHORT_FLAGS:
                    consume_next_token = not chars[i + 1:]
                    break
            seg = seg[1:]
            if consume_next_token and seg:
                seg = seg[1:]
            continue
        break
    return seg


# DECISION (GitHub issue #29 / card #3554, corrected by card #3556) —
# Bundled command flags: `command` recognizes exactly three flags total
# (-p, -v, -V — see docstring below), so the only possible bundles are
# combinations of those three characters. A bundle containing `v` or `V`
# is inherently a lookup regardless of what else is bundled with it, so a
# form like `-pv`/`-vp` is safe to leave unrecognized — it becomes
# `real[0]` itself (`!= "rm"`), an accidental-but-correct ALLOW, exactly
# like the pre-existing `command -p -v` unbundled case. That is NOT true of
# a **p-only bundle** (`-pp`, `-ppp`, any token whose characters after the
# leading `-` are all `p`): card #3556's live probe against the real bash
# builtin confirmed `command -pp echo hi` and `command -ppp echo hi2` both
# perform a REAL INVOCATION (print `hi`/`hi2`, rc=0) — unlike a `v`/`V`-
# containing bundle, which stays lookup-only. A p-only bundle therefore had
# to be stripped the same way repeated exact `-p` tokens already were,
# because leaving it as an unrecognized token lets it become `real[0]`
# instead of the real command hiding behind it, silently skipping the rm
# guard entirely. (An unrecognized-character bundle like `-pw` is a
# separate case: bash's own getopts rejects it outright — `command -pw echo
# hi` errors `command: -w: invalid option`, rc=2, no invocation — so no
# fix is needed there; it never reaches an executable command at all.)
def _strip_command_own_flags_for_lookup_check(seg: list) -> "tuple[list, bool]":
    """Skip `command`'s own -p flag(s) (bundled or not); report whether
    -v/-V follows.

    Called with the tokens AFTER the leading `command` token already
    removed. bash's `command` builtin recognizes exactly three flags
    (POSIX: `command [-p] [-v|-V] name`): -p (use default PATH, still a real
    invocation) and -v/-V (lookup only, no invocation). Returns
    (remaining_tokens, is_lookup) — the caller must leave the ORIGINAL
    segment untouched when is_lookup is True (see FALSE-POSITIVE GUARD on
    _strip_command_wrappers).

    Strips a **p-only bundle** — a token whose characters after the leading
    `-` are ALL `p` (e.g. `-p`, `-pp`, `-ppp`) — the same way repeated exact
    `-p` tokens were already stripped, because bash performs a real
    invocation for that shape (see the decision comment immediately above
    this function). Does NOT parse a bundle containing `v`/`V` (e.g.
    `-pv`/`-vp`) as a single token — any such bundle is inherently a
    lookup, so leaving it unrecognized still lands on the correct ALLOW via
    the accidental-but-safe path documented above.
    """
    rest = seg
    while rest and rest[0].startswith("-") and set(rest[0][1:]) == {"p"}:
        rest = rest[1:]
    if rest and rest[0] in ("-v", "-V"):
        return (rest, True)
    return (rest, False)


def _strip_command_wrappers(segment: list) -> list:
    """Strip leading shell-wrapper tokens so the real command lands at seg[0].

    Handles, in any combination and repetition: `env` (its leading VAR=VAL
    assignment tokens AND its own flags — see _strip_env_flags), `command`
    (its own -p flag — see _strip_command_own_flags_for_lookup_check),
    `xargs` (and its leading flag tokens, e.g. -0, -n1, -I{}), the block
    keywords `do`/`then`/`else`, and shell-grouping artifacts `(` / `{` that
    shlex leaves either standalone (space before the wrapped command, e.g.
    `{ rm ...`) or attached to the first token (no space, e.g. `(rm ...`).

    FALSE-POSITIVE GUARD: `command -v rm` / `command -V rm` (with or without
    a leading `-p`) are lookups, not deletions. When `command`'s own flags
    resolve to -v or -V, this returns the segment UNCHANGED so seg[0] stays
    "command" and the caller's `seg[0] != "rm"` check allows it through.

    This only closes evasions decidable from the tokenized segment itself —
    see "Known residual limits" above _validate_bash_rm_guard for the forms
    that remain out of reach (variable expansion, pipe-fed xargs, symlinks).
    """
    seg = list(segment)
    while seg:
        tok = seg[0]

        if tok in ("(", "{"):
            seg = seg[1:]
            continue
        if tok and tok[0] in ("(", "{"):
            rest = tok.lstrip("({")
            seg = ([rest] if rest else []) + seg[1:]
            continue

        if tok == "command":
            rest, is_lookup = _strip_command_own_flags_for_lookup_check(seg[1:])
            if is_lookup:
                return segment  # lookup, not deletion — leave untouched
            seg = rest
            continue

        if tok == "env":
            seg = _strip_env_flags(seg[1:])
            continue

        if tok == "xargs":
            seg = seg[1:]
            while seg and seg[0] != "-" and seg[0].startswith("-"):
                seg = seg[1:]
            continue

        if tok in ("do", "then", "else"):
            seg = seg[1:]
            continue

        break

    return seg


# Known residual limits — this guard is defense-in-depth behind the global
# CLAUDE.md § Scratchpad prose rule, not an exhaustive control. Three
# evasions are not decidable from the pre-expansion command string this hook
# receives, and are not attempted here:
#   1. Shell-variable expansion, e.g. `S=.scratchpad; rm $S/foo.md` — the
#      literal path never appears in the command text the hook sees.
#   2. Pipe-fed xargs where targets arrive on stdin, e.g.
#      `find .scratchpad -type f | xargs rm` — the rm segment carries no
#      target operand for _rm_segment_targets to inspect.
#   3. Symlink indirection — a symlink pointing into .scratchpad/ lets `rm`
#      delete real scratchpad content via a path that never contains the
#      literal string ".scratchpad".
def _validate_bash_rm_guard(payload: dict) -> "dict | None":
    """Validate a Bash tool call for unsafe `rm` invocations from sub-agents.

    Returns a deny response dict if the command should be blocked, or None
    to allow. Only applies inside a sub-agent (agent_id present in payload) —
    the coordinator is never gated by this check.

    Fails open: any tokenizer error is logged and treated as allow, matching
    the fail-open design of _validate_bash_destructive_git above.
    """
    if not _is_sub_agent(payload):
        return None  # Main session — bypass

    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return None

    try:
        segments = _tokenize_command(command)
    except Exception as e:
        log_error(f"rm-guard parse failure: {e!r}")
        return None

    for seg in segments:
        if not seg:
            continue

        real = _strip_command_wrappers(seg)
        if not real or real[0] != "rm":
            continue

        cmd_repr = " ".join(seg)  # log the original, wrapped form for context

        if _rm_segment_is_recursive(real):
            log_info(f"Bash denied — recursive rm from sub-agent: {cmd_repr}")
            return deny_with_reason(_RM_RECURSIVE_DENY_MESSAGE)

        targets = _rm_segment_targets(real)
        if any(_is_under_scratchpad_dir(t) for t in targets):
            log_info(f"Bash denied — rm targeting .scratchpad/ from sub-agent: {cmd_repr}")
            return deny_with_reason(_RM_SCRATCHPAD_DENY_MESSAGE)

    return None  # No unsafe rm detected — allow


# ---------------------------------------------------------------------------
# isolation:"worktree" + kanban card guard (Agent tool calls)
# ---------------------------------------------------------------------------
#
# GitHub issue #39 / card #3608. `kanban criteria check <card> <n> --session
# <session>` (and `kanban show`, `kanban status`) fail with the literal error
# "No card found matching '<N>'" when run from inside an isolation-spawned
# ephemeral worktree — the kanban session cannot be resolved from that
# directory context. Confirmed independently in two sessions on the same day,
# on unrelated cards, with the identical error string. This affects EVERY
# kanban-tracked card delegated with isolation on, regardless of what the
# card touches, so the sub-agent can never check a single criterion and the
# card can never reach done. Separately, the ephemeral worktree is
# auto-cleaned when judged unchanged, and because .scratchpad/ is git-ignored
# a findings file written there is invisible to that check and is destroyed
# silently.
#
# Reachability of the `isolation` field on the Agent tool_input payload was
# confirmed against a REAL captured PreToolUse-equivalent transcript entry
# (not merely assumed from a schema doc): a live Claude Code session
# transcript (~/.claude/projects/.../2940813f-282c-4b1c-bf5f-5b62d9730b63.jsonl)
# contains an actual `tool_use` block with `name == "Agent"` whose `input`
# dict carries `isolation: "worktree"` as a sibling key to `subagent_type`,
# `description`, `run_in_background`, and `prompt` — the exact same keys this
# hook already reads off `tool_input` elsewhere in this file (see
# `tool_input.get("subagent_type", ...)`, `tool_input.get("description", ...)`,
# `tool_input.get("run_in_background")` above). The PreToolUse hook's
# `tool_input` mirrors that same `input` object, so `isolation` reaches this
# hook the same way those other fields already do.
#
# Detection: this guard counts _CARD_FULL_PATTERN matches directly (see the
# docstring on _check_isolation_worktree_card_guard below for why it does
# NOT reuse extract_card_and_session() here, unlike the "no kanban card
# reference found in prompt" deny (below, in main()), which still does).
# Card #3612 / GitHub issue #39 follow-up: the original version of this
# guard called extract_card_and_session() and inherited two behaviors that
# invert for this consumer — ambiguity-as-absence on 2+ full headers, and a
# loose bare-pattern fallback that matched ordinary prose. Fixed by giving
# this guard its own direct full-pattern-only count.

_ISOLATION_WORKTREE_CARD_DENY_MESSAGE = (
    "Agent tool call denied: `isolation: \"worktree\"` cannot be paired with a "
    "kanban card reference.\n"
    "Running a kanban-tracked sub-agent inside an isolation-spawned ephemeral "
    "worktree breaks kanban session resolution — `kanban criteria check`, "
    "`kanban show`, and `kanban status` all fail with the literal error "
    "\"No card found matching '<N>'\" from that directory context, so the "
    "sub-agent can never check a single criterion and the card can never "
    "reach done. Separately, the ephemeral worktree is auto-cleaned when "
    "judged unchanged, silently destroying any .scratchpad/ findings "
    "(git-ignored, so invisible to that unchanged-check).\n"
    "Corrected form: delegate without isolation — drop the `isolation` "
    "argument entirely. A kanban card's file-conflict scheduling already "
    "comes from its declared editFiles, so isolation buys nothing here."
)


def _check_isolation_worktree_card_guard(tool_input: dict, prompt: str) -> "dict | None":
    """Deny an Agent call that pairs isolation:"worktree" with a kanban card.

    Returns a deny response dict if the call should be blocked, or None to
    allow. Fails open on a missing or unrecognized `isolation` value — an
    absent field, or any value other than "worktree" (case/whitespace
    normalized — see below), denies nothing.

    Card-reference detection (tightened by card #3612 / GitHub issue #39):
    this guard does its OWN direct count of _CARD_FULL_PATTERN matches
    rather than delegating to extract_card_and_session(). That function was
    built for a different consumer (the agent_launch_pending-clearing
    callback) where a false positive is harmless — it just skips clearing a
    flag for one extra card. Two of its behaviors invert for this guard,
    where a false positive means WRONGLY BLOCKING legitimate work:
      - extract_card_and_session returns None (fail-open, i.e. "no card
        found") when the full pattern matches MORE THAN ONCE. For its
        original consumer that ambiguity is a deliberate mutation-safety
        fail-safe. For this guard, ambiguity is not absence: two or more
        full card headers alongside isolation:"worktree" is exactly the
        dangerous case this guard exists to catch, so it must still deny.
      - extract_card_and_session falls back to a loose bare "card #N" +
        "session ..." pair matched independently anywhere in the prompt,
        with no proximity requirement. That fallback turns ordinary English
        prose (e.g. a delegation whose body happens to mention "card #42"
        and "session token expiry" in unrelated sentences) into a false
        "card reference found" — wrongly denying legitimate parallel-file
        delegations that never contained an actual kanban card header.
    This guard therefore counts only _CARD_FULL_PATTERN matches: one or
    more full headers -> a card reference is present -> deny; zero -> no
    card reference -> allow (fall through to the pre-existing "no kanban
    card reference found in prompt" deny below, which still uses
    extract_card_and_session and its loose fallback is fine there — a
    prose-only card mention that this guard now ignores).

    A card referenced ONLY in bare prose form (no full "KANBAN CARD #N |
    Session: ..." header) will no longer trigger THIS guard — that is a
    deliberate, accepted tradeoff, not a gap: extract_card_and_session()
    itself is intentionally left unmodified (its ambiguity fail-safe and
    loose fallback remain correct for its original consumer).
    """
    isolation_raw = tool_input.get("isolation", "")
    # Normalized to guard against case/whitespace variance in the LLM-
    # emitted value (e.g. " Worktree ", "WORKTREE") — same category of
    # serialization hazard as the run_in_background string-vs-bool
    # handling above (see "LLM serialization hazard" comment near
    # run_in_background_raw). UNVERIFIED: no confirmed live emission of a
    # non-canonical isolation value has been observed — the security review
    # that raised this could not access the Agent tool's schema and
    # explicitly declined to assert exploitability in either direction.
    # This normalization is defense-in-depth consistent with this file's
    # existing pattern, not a response to a confirmed bypass.
    if str(isolation_raw).strip().lower() != "worktree":
        return None
    if len(_CARD_FULL_PATTERN.findall(prompt)) == 0:
        return None
    log_info("Agent denied — isolation=worktree paired with a kanban card reference")
    return deny_with_reason(_ISOLATION_WORKTREE_CARD_DENY_MESSAGE)


# ---------------------------------------------------------------------------
# Allow response helpers
# ---------------------------------------------------------------------------

def allow_unchanged() -> dict:
    """Return a permissionDecision=allow response with no prompt modification."""
    return {
        "continue": True,
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "",
        }
    }


def allow_with_updated_prompt(original_input: dict, new_prompt: str) -> dict:
    """Return a permissionDecision=allow response with updated prompt.

    CRITICAL: updatedInput must contain ALL original tool_input fields, not just
    prompt. Claude Code replaces (not merges) tool_input with updatedInput, so
    omitting fields like run_in_background, subagent_type, model, and description
    causes them to be silently stripped — resulting in agents running in the
    foreground despite the caller setting run_in_background: true.
    """
    updated = dict(original_input)
    updated["prompt"] = new_prompt
    return {
        "continue": True,
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "",
            "updatedInput": updated,
        }
    }


def deny_with_reason(reason: str) -> dict:
    """Return a permissionDecision=deny response with a reason message.

    Only hookSpecificOutput.permissionDecision = "deny" (with
    permissionDecisionReason carrying the message for Claude) is emitted at
    the top level. Per ~/.claude/CLAUDE.md section "Tool-Block Recovery", a
    denial is either MECHANICAL (the rejection text names a corrected form of
    the same action — apply it and retry in the same turn) or a PROHIBITION
    (the action itself is forbidden in any form, and the agent must stop and
    report the block in its own final return). Both classes require the
    agent's turn to survive the denial so it can either retry or emit that
    report; halting the turn at this hook would make either recovery path
    structurally impossible, so no turn-halting field is emitted here.
    """
    return {
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Skip if running inside a non-coordinator session (Personal Trainer, etc.)
    # to avoid injecting kanban coordinator context where it doesn't belong.
    # is_non_coordinator_session() checks PERSONAL_TRAINER_SESSION=1;
    # add new session-type flags in _session_env.py as new modes are introduced.
    if is_non_coordinator_session():
        print(json.dumps(allow_unchanged()))
        return

    # Read the hook payload from stdin
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps(allow_unchanged()))
        return

    try:
        payload = json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        log_error(f"JSON decode error: {exc}")
        print(json.dumps(allow_unchanged()))
        return

    # Verify tool name — handle Bash validation separately from Agent injection.
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    # .kanban/ path guard — runs for Edit, Write, MultiEdit, NotebookEdit, Bash.
    # Order inside _check_kanban_path_guard:
    #   1. kanban-CLI allowlist (Bash only) — always passes kanban commands through
    #   2. path-guard deny patterns
    # This must run BEFORE the destructive-git check so the kanban CLI allowlist
    # takes effect for Bash before any other analysis.
    if tool_name in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"):
        allowed, reason = _check_kanban_path_guard(tool_name, tool_input)
        if not allowed:
            log_info(f"{tool_name} denied — .kanban/ path guard: {reason[:80]}")
            print(json.dumps(deny_with_reason(reason)))
            return

    # Destructive git operation check for Bash calls from sub-agents.
    # This fires after the .kanban/ path guard (which handles kanban CLI allowlist).
    if tool_name == "Bash":
        denial = _validate_bash_destructive_git(payload)
        if denial is not None:
            print(json.dumps(denial))
            return
        denial = _validate_bash_rm_guard(payload)
        if denial is not None:
            print(json.dumps(denial))
            return
        print(json.dumps(allow_unchanged()))
        return

    # For all other non-Agent tools, pass through unchanged.
    if tool_name != "Agent":
        print(json.dumps(allow_unchanged()))
        return

    # Extract prompt from tool_input (already fetched above, re-verify type for Agent path)
    if not isinstance(tool_input, dict):
        print(json.dumps(allow_unchanged()))
        return

    prompt = tool_input.get("prompt", "")

    # isolation:"worktree" + kanban card guard — see the section comment above
    # _check_isolation_worktree_card_guard for the full rationale (card #3608
    # / GitHub issue #39). Runs unconditionally for every Agent call, ahead of
    # the SKILL_AGENT_BYPASS check below, because this is a mechanical
    # incompatibility (kanban session resolution breaks inside the ephemeral
    # worktree), not a policy check a skill-spawned bypass should skip.
    isolation_denial = _check_isolation_worktree_card_guard(tool_input, prompt)
    if isolation_denial is not None:
        print(json.dumps(isolation_denial))
        return

    # Extract only the pre-injection portion of the prompt for marker checks.
    # inject_card_into_prompt prepends card XML ending with
    # "<!-- End of injected card content -->". When an agent prompt already
    # contains a previous injection (e.g. nested delegation), the injected card
    # XML could contain arbitrary text including bypass markers. Checking only
    # the original (post-injection-delimiter) portion prevents card content from
    # influencing enforcement decisions.
    _INJECTION_END = "<!-- End of injected card content -->"
    if _INJECTION_END in prompt:
        pre_injection_prompt = prompt[prompt.index(_INJECTION_END) + len(_INJECTION_END):]
    else:
        pre_injection_prompt = prompt

    # SKILL_AGENT_BYPASS: Skills (e.g. /commit) may spawn Agent calls without
    # kanban cards, background mode, or subagent_type. If the prompt contains
    # the bypass marker, skip all enforcement deny rules but still attempt card
    # injection if a card reference is present.
    # Only check the pre-injection portion to prevent card XML from injecting bypass.
    skill_bypass = bool(
        pre_injection_prompt
        and _SKILL_AGENT_BYPASS_RE.search(pre_injection_prompt)
    )
    if skill_bypass:
        log_info("SKILL_AGENT_BYPASS detected — skipping enforcement rules")

    if not skill_bypass:
        # Check for missing or empty description field — deny launch if absent
        description = tool_input.get("description", "")
        if not description or not str(description).strip():
            reason = (
                "Agent tool call denied: missing or empty 'description' field. "
                "Include a meaningful description on all Agent/Task tool calls "
                "so the completion notification identifies the agent (instead of 'undefined')."
            )
            log_info("Agent denied — missing description field")
            print(json.dumps(deny_with_reason(reason)))
            return

        # Check for missing or invalid subagent_type — deny launch if absent
        subagent_type_check = tool_input.get("subagent_type", "")
        if not subagent_type_check or not str(subagent_type_check).strip():
            reason = (
                "Agent tool call denied: missing or empty 'subagent_type' field. "
                "Always specify a subagent_type (e.g. swe-backend, swe-frontend, "
                "researcher). The general-purpose agent is prohibited — there is "
                "always a more appropriate specialist."
            )
            log_info("Agent denied — missing subagent_type field")
            print(json.dumps(deny_with_reason(reason)))
            return

        # Deny the literal "general-purpose" subagent_type (case-insensitive).
        # Defense-in-depth: the staff engineer prompt already prohibits it, but
        # concrete examples in docs were overriding the prose instruction.
        if str(subagent_type_check).strip().lower() == "general-purpose":
            reason = (
                "Agent tool call denied: subagent_type 'general-purpose' is "
                "prohibited. There is always a more appropriate specialist. "
                "Use a specific subagent_type instead (e.g. swe-backend, "
                "swe-frontend, swe-fullstack, swe-devex, swe-infra, swe-sre, "
                "swe-security, researcher, scribe, debugger)."
            )
            log_info(f"Agent denied — general-purpose subagent_type: {subagent_type_check!r}")
            print(json.dumps(deny_with_reason(reason)))
            return

    if not prompt:
        print(json.dumps(allow_unchanged()))
        return

    if not skill_bypass:
        # Check for missing run_in_background: true — deny foreground launches unless
        # Option C is explicitly authorized via FOREGROUND_AUTHORIZED marker in prompt.
        #
        # LLM serialization hazard: Claude Code models sometimes emit run_in_background
        # as the JSON string "true" instead of the boolean true. Both must be accepted.
        # The canonical form is boolean true; the string "true" is treated as equivalent.
        # Any other value (False, "false", None, absent) is treated as not-set. This is
        # no longer a deny path: absent FOREGROUND_AUTHORIZED triggers self-heal to True
        # (see below); present FOREGROUND_AUTHORIZED allows the foreground launch as-is.
        #
        # String comparison: strip() removes leading/trailing whitespace (including
        # Unicode whitespace) before lowercasing, so "True", "TRUE", " true " all match.
        # In practice JSON-deserialized strings from Claude Code will be clean ASCII,
        # but strip() is harmless and handles any edge-case whitespace variation.
        # `is True` (identity) is used for booleans — not `== True` — so integer 1
        # and other truthy non-bool scalars are correctly denied.
        run_in_background_raw = tool_input.get("run_in_background")
        run_in_background = (
            run_in_background_raw is True
            or (isinstance(run_in_background_raw, str) and run_in_background_raw.strip().lower() == "true")
        )
        if not run_in_background:
            # Only check the pre-injection portion to prevent card XML from injecting bypass.
            if not _FOREGROUND_AUTHORIZED_RE.search(pre_injection_prompt):
                # serialization-proof fix-up: Claude Code models non-deterministically
                # serialize run_in_background as the JSON string "true" instead of boolean
                # true, and CC drops schema-invalid string values before the PreToolUse hook
                # stdin — so the hook sees the field ABSENT. Boolean true is never dropped.
                # Mutate tool_input in-place so the downstream allow_with_updated_prompt
                # (which snapshots via dict(tool_input)) picks up the fix naturally — giving
                # full parity with the happy path: run_in_background=True AND card XML injected
                # AND agent attribution, all in one updatedInput. DO NOT return early here;
                # fall through to card-reference extraction and the normal card-injection path.
                tool_input["run_in_background"] = True
                log_info("Agent run_in_background absent/non-boolean — injecting True (serialization-proof)")

        # Extract card number and session from prompt — deny if missing
        extracted = extract_card_and_session(prompt)
        if extracted is None:
            reason = (
                "Agent tool call denied: no kanban card reference found in prompt. "
                "Every Agent delegation must reference a card created with `kanban do`. "
                "Include 'KANBAN CARD #<N> | Session: <session-id>' at the top of "
                "the delegation prompt. Create the card first, then launch the agent."
            )
            log_info("Agent denied — no card reference in prompt")
            print(json.dumps(deny_with_reason(reason)))
            return
    else:
        # Bypass mode: still attempt card injection if a card reference exists
        extracted = extract_card_and_session(prompt)

    # If no card reference found (only possible in bypass mode), allow unchanged
    if extracted is None:
        print(json.dumps(allow_unchanged()))
        return

    card_number, session = extracted
    log_info(f"card found: #{card_number} session={session}")

    # Fetch card XML via kanban CLI
    card_xml = fetch_card_xml(card_number, session)
    if card_xml is None:
        # kanban show failed — fail open
        print(json.dumps(allow_unchanged()))
        return
    log_info(f"card XML fetched successfully for #{card_number}")

    # Automatic per-edit progress-protocol injection for multi-file work cards
    # (card #3428): more than one <edit-files><f> entry means partial progress
    # can be lost on a mid-turn strand, so the block is injected without the
    # coordinator having to remember to paste it. Fails open via
    # _count_edit_files_in_card_xml — a parse failure yields 0 and no injection,
    # never a blocked launch. See _resolve_progress_protocol_block() for the
    # full decision (threshold + already-present guard).
    progress_protocol_block = _resolve_progress_protocol_block(card_xml, card_number)

    # Inject card content into the prompt
    new_prompt = inject_card_into_prompt(
        prompt, card_xml, card_number, session, progress_protocol_block
    )

    # Clear agent_launch_pending flag — confirms the agent was actually launched.
    # Invokes: kanban clear-agent-launch-pending (cmd_clear_agent_launch_pending in kanban.py).
    # Fails open: any error here must not block the agent launch.
    #
    # Phase 2 ordering note: this call runs synchronously BEFORE the kanban agent
    # update below. If interrupted between here and the agent update (e.g. Python
    # crash, SIGKILL), the card will show agent_launch_pending=False but with a
    # stale/empty agent field. The card is NOT a phantom (it was genuinely launched),
    # but its agent attribution will be wrong. This is an acceptable rare edge case
    # for Phase 1; Phase 2 phantom-doing detection should treat missing agent as
    # "launched, agent unknown" rather than "phantom". (stale attribution, no phantom)
    #
    # Fail-open consequence: if this call fails (timeout, CLI unavailable), the flag
    # stays True. The Phase 2 phantom-doing detector will see the card as still-pending
    # after the actual launch — a false-positive phantom detection for this card.
    # Logged to ERROR_LOG_PATH so the condition is observable.
    try:
        clear_result = subprocess.run(
            ["kanban", "clear-agent-launch-pending", card_number, "--session", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if clear_result.returncode != 0:
            log_error(
                f"kanban clear-agent-launch-pending failed for #{card_number} "
                f"(exit {clear_result.returncode})"
            )
        else:
            log_info(f"agent_launch_pending cleared for #{card_number}")
    except subprocess.TimeoutExpired:
        log_error(f"kanban clear-agent-launch-pending timed out for #{card_number}")
    except Exception as exc:
        log_error(f"kanban clear-agent-launch-pending failed for #{card_number}: {exc}")

    # Update card's agent field with the actual sub-agent type.
    # Run synchronously so we know it succeeded before attempting the DB update.
    subagent_type = tool_input.get("subagent_type", "")
    if subagent_type:
        agent_updated = False
        try:
            result = subprocess.run(
                ["kanban", "agent", card_number, subagent_type, "--session", session],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            agent_updated = result.returncode == 0
            if not agent_updated:
                log_error(
                    f"kanban agent update failed for #{card_number} "
                    f"(exit {result.returncode})"
                )
        except subprocess.TimeoutExpired:
            log_error(f"kanban agent update timed out for #{card_number}")
        except Exception as exc:
            log_error(f"kanban agent update failed for #{card_number}: {exc}")

        # After a successful kanban agent call, backfill the 'created' event row
        # in the metrics DB so it reflects the correct agent from the start.
        if agent_updated:
            _METRICS_DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"
            normalized_agent = subagent_type.lower().replace(" ", "-")
            # persona mirrors agent (None when agent is "unassigned")
            persona = normalized_agent if normalized_agent != "unassigned" else None
            try:
                conn = sqlite3.connect(str(_METRICS_DB_PATH))
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout=5000")
                    conn.execute(
                        """
                        UPDATE kanban_card_events
                        SET agent = ?, persona = ?
                        WHERE card_number = ? AND event_type = 'create'
                        """,
                        (normalized_agent, persona, card_number),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as exc:
                log_error(
                    f"DB update of created event failed for #{card_number}: {exc}"
                )

    log_info(f"prompt updated successfully for #{card_number} session={session}")
    print(json.dumps(allow_with_updated_prompt(tool_input, new_prompt)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_error(f"hook error: {exc}\n{traceback.format_exc()}")
    # Always exit 0 — hook must never block agent launch
    sys.exit(0)
