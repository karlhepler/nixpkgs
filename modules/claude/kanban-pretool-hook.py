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

Skip condition: BURNS_SESSION=1 env var means Ralph is running — skip injection
to avoid confusing the model with kanban context.

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
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import traceback
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

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
    except Exception:  # intentional: last-resort log utility must never raise
        pass


def _write_log(path: Path, message: str) -> None:
    """Append a timestamped message to a log file. Never raises.

    Rotates the log file to <path>.1 when it exceeds _LOG_MAX_BYTES,
    then starts a fresh file (one backup generation kept).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed(path)
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
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
    """
    # Pattern 1: "KANBAN CARD #N | Session: session-name"
    m = _CARD_FULL_PATTERN.search(prompt)
    if m:
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

def inject_card_into_prompt(prompt: str, card_xml: str, card_number: str, session: str) -> str:
    """
    Prepend the card XML to the agent prompt, separated by a clear boundary.

    The injected block is placed BEFORE the original prompt so the agent
    sees the card details immediately without having to call kanban show.
    """
    header = (
        f"<!-- Kanban card #{card_number} (session: {session}) "
        f"injected by PreToolUse hook -->\n"
        f"{card_xml}\n"
        f"<!-- End of injected card content -->\n\n"
    )
    return header + prompt


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
        log_error(f"destructive-git parse failure: {e}")
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
        if result.returncode != 0 or not result.stdout.strip():
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
        log_error(f"_fetch_doing_card_for_session failed for session={session_id}: {e}")
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
        if result.returncode != 0 or not result.stdout.strip():
            return None
        root = ET.fromstring(result.stdout.strip())
        ef_el = root.find("edit-files")
        if ef_el is None:
            return (card_number, [])
        files = [f.text.strip() for f in ef_el.findall("f") if f.text and f.text.strip()]
        return (card_number, files)
    except Exception as e:
        log_error(f"_fetch_card_editfiles failed for card={card_number}: {e}")
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
    - BURNS_SESSION=1 is handled upstream (early return in main).
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
            log_info(f"Bash denied — git stash drop from sub-agent session={session_id}")
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
            log_info(f"Bash denied — git stash push/save/bare from sub-agent session={session_id}")
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
            log_info(f"Bash denied — git checkout -p (interactive) from sub-agent session={session_id}")
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
            log_info(f"Bash denied — git reset --hard from sub-agent session={session_id}")
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
            log_info(f"Bash denied — destructive git op (no file target) from sub-agent session={session_id}")
            return deny_with_reason(reason)

        # Check each file against editFiles
        if card_info is None:
            # Could not fetch card info — fail open (do not block)
            log_error(f"Could not fetch card for session={session_id} — skipping destructive git check")
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
            log_info(f"Bash denied — destructive git op on {file_targets}, card #{card_num} has no editFiles, session={session_id}")
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
            log_info(f"Bash denied — destructive git op on out-of-scope files {out_of_scope}, card #{card_num}, session={session_id}")
            return deny_with_reason(reason)

    return None  # All checks passed — allow


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
    """Return a permissionDecision=deny response with a reason message."""
    return {
        "continue": False,
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
    # Skip if running inside a Burns/Ralph session to avoid confusing Ralph
    # with kanban context injection.
    if os.environ.get("BURNS_SESSION") == "1":
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

    # Destructive git operation check for Bash calls from sub-agents.
    # This fires before the Agent-only injection logic below.
    if tool_name == "Bash":
        denial = _validate_bash_destructive_git(payload)
        if denial is not None:
            print(json.dumps(denial))
            return
        print(json.dumps(allow_unchanged()))
        return

    # For all other non-Agent tools, pass through unchanged.
    if tool_name != "Agent":
        print(json.dumps(allow_unchanged()))
        return

    # Extract prompt from tool_input
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        print(json.dumps(allow_unchanged()))
        return

    prompt = tool_input.get("prompt", "")

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
    skill_bypass = bool(pre_injection_prompt and "SKILL_AGENT_BYPASS" in pre_injection_prompt)
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
        run_in_background = tool_input.get("run_in_background")
        if run_in_background is not True:
            # Only check the pre-injection portion to prevent card XML from injecting bypass.
            if "FOREGROUND_AUTHORIZED" not in pre_injection_prompt:
                reason = (
                    "Agent tool call denied: missing `run_in_background: true`. "
                    "All Agent tool calls MUST run in the background to keep the "
                    "coordination loop available. Add `run_in_background: true` to "
                    "your Agent tool call. Exception: Permission Gate Recovery "
                    "Option C — include 'FOREGROUND_AUTHORIZED' in the delegation "
                    "prompt to allow a foreground launch."
                )
                log_info("Agent denied — missing run_in_background: true")
                print(json.dumps(deny_with_reason(reason)))
                return

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

    # Inject card content into the prompt
    new_prompt = inject_card_into_prompt(prompt, card_xml, card_number, session)

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
