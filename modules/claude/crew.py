#!/usr/bin/env python3
"""
crew: Unified tmux window/pane interaction CLI

Subcommands:
  list                     Enumerate tmux windows and panes (Claude panes only by default)
  tell <targets> <msg>     Send message + Enter to each target pane (targets first)
  read <targets>           Capture pane buffer content
  find <pattern> [targets] Search pane content for pattern
  status                   Composite: list + read N lines from every pane (Claude panes only by default)
  smithers <name>          Create a horizontal split in the target window and run smithers in the new pane

Target format: <window>[.<pane>]  — pane defaults to 0
  comma-separated for multi-target: mild-forge,bold-sparrow.1

Output format: --format xml (default), --format json, or --format human

Claude-only filter (list, find, status):
  By default, list, find (no-targets path), and status filter to panes running Claude. Claude Code installs
  as a versioned binary (e.g. ~/.local/share/claude/versions/2.1.116) symlinked from
  ~/.local/bin/claude, so tmux #{pane_current_command} reports the version number
  (e.g. "2.1.116") rather than "claude". The filter matches: literal "claude",
  literal "node" (older installs), or a semver-like version string (digits.digits...)
  as a practical catch-all. Use --all to include all panes regardless of command.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Session readiness sentinel helpers
# ---------------------------------------------------------------------------
# crew create --tell uses a sentinel file dropped by the SessionStart hook
# (crew-lifecycle-hook.py) to determine when Claude Code has finished booting.
# This is deterministic: the file's existence is the signal. The old approach
# (polling pane buffer for TUI box-drawing chars with a 60s timeout) failed
# in nix-flake repos where startup takes 60s+.

_CREW_SENTINEL_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "crew")


def _sentinel_path(name: str) -> str:
    """Return the readiness sentinel path for the session with the given name."""
    return os.path.join(_CREW_SENTINEL_DIR, f"ready-{name}")


def _clean_stale_sentinel(name: str) -> None:
    """Remove any stale sentinel for <name> before spawning a new session.

    A leftover sentinel from a crashed or dismissed prior session would cause
    _wait_for_sentinel to return immediately (false-ready). Cleaning it before
    spawn ensures the sentinel observed by the wait was written by THIS session.
    """
    sentinel = _sentinel_path(name)
    try:
        os.unlink(sentinel)
    except FileNotFoundError:
        pass  # Already absent — nothing to do.
    except OSError as exc:
        print(
            f"[crew] warning: could not remove stale sentinel '{sentinel}': {exc}",
            file=sys.stderr,
        )


def _cleanup_sentinel(name: str) -> None:
    """Remove the readiness sentinel for <name> on session cleanup (dismiss).

    Sentinels must not leak after a session is dismissed.
    Same as _clean_stale_sentinel but with a dismiss-specific log label.
    """
    sentinel = _sentinel_path(name)
    try:
        os.unlink(sentinel)
    except FileNotFoundError:
        pass  # Already absent — nothing to do.
    except OSError as exc:
        print(
            f"[crew] warning: could not remove sentinel '{sentinel}' on dismiss: {exc}",
            file=sys.stderr,
        )


# Outer wall-clock ceiling for sentinel-readiness wait. Failure backstop only —
# sentinel-detection itself is event-driven via fswatch and not bounded by this
# ceiling under normal operation.
_SENTINEL_WAIT_CEILING_SECONDS = 5 * 60.0


def _hook_present_in_settings() -> bool:
    """Return True if crew-lifecycle-hook.py is configured as a SessionStart hook.

    Parses the deployed Claude Code settings.json to check whether the SessionStart
    hook command line includes 'crew-lifecycle-hook.py'. Used to distinguish
    'hook not installed' from 'session crashed during boot' after ceiling elapsed.

    Falls back to True (assume hook present / crashed) on any parse error so that
    the safer diagnostic is shown when settings.json is malformed or unreadable.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
    settings_path = os.path.join(config_dir, "settings.json")
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        hooks = settings.get("hooks", {})
        session_start_hooks = hooks.get("SessionStart", [])
        for hook in session_start_hooks:
            # Each hook entry may be a dict with a "command" key or a plain string.
            if isinstance(hook, dict):
                cmd = hook.get("command", "")
            elif isinstance(hook, str):
                cmd = hook
            else:
                continue
            if "crew-lifecycle-hook.py" in cmd:
                return True
        return False
    except Exception:
        # Malformed settings.json or unreadable — assume hook is present (safer).
        return True


def _wait_for_sentinel(
    name: str,
    ceiling: float = _SENTINEL_WAIT_CEILING_SECONDS,
    poll_interval: float = 0.5,
) -> tuple:  # Tuple[bool, Optional[str]]
    """Wait for the readiness sentinel file to appear for the given session name.

    The sentinel is dropped by crew-lifecycle-hook.py's SessionStart handler
    once Claude Code has fully initialised. Waiting on the file is deterministic:
    no timing assumptions, no pane-buffer parsing.

    Detection mechanism: fswatch (macOS kqueue backend, guaranteed by
    modules/packages.nix). Watches the sentinel directory for file-created events,
    wakes the moment the sentinel appears. Zero-latency detection — no polling
    interval delay. fswatch is Nix-guaranteed; if it is missing, a clear
    RuntimeError is raised to surface the contract violation.

    Returns (ready: bool, reason: Optional[str]):
      (True, None)    — sentinel observed within ceiling.
      (False, reason) — ceiling elapsed; reason distinguishes:
          "session never reported ready — SessionStart hook missing in target settings.json"
          "session never reported ready — likely crashed during boot, check tmux pane"
    """
    sentinel = _sentinel_path(name)

    # Fast path: sentinel already present from a very quick boot.
    if os.path.exists(sentinel):
        return True, None

    # fswatch is guaranteed by modules/packages.nix. Probe to verify it is on PATH;
    # if missing, raise a loud error so the operator sees the contract violation
    # rather than a silent hang or confusing timeout.
    fswatch_path = "fswatch"
    probe = subprocess.run(
        [fswatch_path, "--version"],
        capture_output=True, check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "fswatch probe failed (exit {}) — fswatch is Nix-guaranteed via "
            "modules/packages.nix; check $PATH".format(probe.returncode)
        )

    deadline = time.monotonic() + ceiling

    # fswatch loop: each iteration blocks in fswatch until an event fires in
    # the sentinel directory, then rechecks os.path.exists. If fswatch exits
    # due to its own timeout (subprocess.TimeoutExpired) we stop and fall
    # through to the ceiling-elapsed logic below.
    while time.monotonic() < deadline:
        if os.path.exists(sentinel):
            return True, None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            subprocess.run(
                [fswatch_path, "-1", "--latency", "0.1", _CREW_SENTINEL_DIR],
                capture_output=True, check=False,
                timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            break
    if os.path.exists(sentinel):
        return True, None

    # Ceiling elapsed — distinguish hook-missing from crash by parsing settings.json.
    # If the hook is not configured, the sentinel will never appear regardless of
    # session state. If it is configured, a missing sentinel means the session
    # likely crashed during boot.
    if not _hook_present_in_settings():
        reason = (
            "session never reported ready — SessionStart hook missing in target settings.json"
        )
    else:
        reason = (
            "session never reported ready — likely crashed during boot, check tmux pane"
        )
    return False, reason


# ---------------------------------------------------------------------------
# tmux helpers
# ---------------------------------------------------------------------------

def get_current_session() -> Optional[str]:
    """Return the name of the tmux session crew is running inside, or None if not in tmux."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True, check=False
    )
    name = result.stdout.strip()
    return name if name else None


def get_current_window_id() -> Optional[str]:
    """Return the stable @N window ID of the window crew is running inside, or None."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{window_id}"],
        capture_output=True, text=True, check=False
    )
    wid = result.stdout.strip()
    return wid if wid else None


def get_window_lookup(session: Optional[str] = None) -> Dict[str, Tuple[str, str]]:
    """Return dict mapping window_name -> (session:window_index, window_id) (first-match).

    window_id is the stable @N identifier assigned by tmux that does not change
    when windows are killed or renumbered.

    If session is provided, only windows in that session are included.
    """
    if session is not None:
        cmd = ["tmux", "list-windows", "-t", session, "-F",
               "#{session_name}:#{window_index}|#{window_id}|#{window_name}"]
    else:
        cmd = ["tmux", "list-windows", "-a", "-F",
               "#{session_name}:#{window_index}|#{window_id}|#{window_name}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    lookup: Dict[str, Tuple[str, str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        session_idx, window_id, rest = parts
        name = rest.split()[0] if rest.split() else ""
        if name and name not in lookup:
            lookup[name] = (session_idx, window_id)
    return lookup


def get_all_panes(session: Optional[str] = None) -> List[Tuple[str, str, str, str, str]]:
    """Return list of (session, window_index, window_name, pane_index, pane_current_command) tuples.

    If session is provided, only panes in that session are returned.
    """
    if session is not None:
        cmd = ["tmux", "list-panes", "-t", session, "-s", "-F",
               "#{session_name}|#{window_index}|#{window_name}|#{pane_index}|#{pane_current_command}"]
    else:
        cmd = ["tmux", "list-panes", "-a", "-F",
               "#{session_name}|#{window_index}|#{window_name}|#{pane_index}|#{pane_current_command}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    panes = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5:
            panes.append(tuple(parts))
    return panes


# Regex to identify Claude Code panes via pane_current_command.
#
# Claude Code installs as a versioned binary (e.g. ~/.local/share/claude/versions/2.1.116)
# symlinked from ~/.local/bin/claude. tmux #{pane_current_command} reports the binary name,
# which is the version string (e.g. "2.1.116"), not "claude".
#
# The pattern matches:
#   - "claude"      — literal name (future installs, wrappers, or older versions)
#   - "node"        — older Claude Code installs that shipped as a node script
#   - "2.1.116" etc — semver-like version string (digits.digits or digits.digits.digits)
#                     matching the current versioned-binary install pattern
#
# This is intentionally permissive on the version side: any command that looks like
# a version number (starts with a digit, contains a dot) is treated as Claude. Non-Claude
# panes typically run shell processes (zsh, bash, sh, fish) or named tools (smithers,
# vim, etc.) — none of which match this pattern.
_CLAUDE_COMMAND_RE = re.compile(r"^(claude|node|\d+\.\d+.*)$")


def is_claude_pane(pane_current_command: str) -> bool:
    """Return True if the pane is likely running Claude Code based on its current command."""
    return bool(_CLAUDE_COMMAND_RE.match(pane_current_command))


def _resolve_targets_with_lookup(
    targets_str: str,
    lookup: Dict[str, Tuple[str, str]],
    fmt: str = "xml",
    available_context: str = "",
) -> List[Tuple[str, str, str]]:
    """
    Core resolution logic shared by resolve_targets and resolve_targets_in_session.

    Returns list of (tmux_target, label, window_id) triples.
    fmt: output format for structured error emission.
    available_context: extra text appended to the "available windows" error line.
    """
    resolved = []
    for raw in targets_str.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "." in raw:
            window_name, _, pane_str = raw.rpartition(".")
            pane_index = pane_str
        else:
            window_name = raw
            pane_index = "0"

        if not re.match(r"^\d+$", pane_index):
            emit_error(
                f"pane index must be numeric, got '{pane_index}' in target '{raw}'",
                fmt,
                error_code="INVALID_TARGET",
                exit_code=2,
            )

        entry = lookup.get(window_name)
        if entry is None:
            msg = (
                f"tmux window '{window_name}' not found (target '{raw}')"
                + (f" {available_context}" if available_context else "")
            )
            available = list(lookup.keys())
            if available and fmt == "human":
                print(f"Available windows: {', '.join(available)}", file=sys.stderr)
            emit_error(msg, fmt, error_code="WINDOW_NOT_FOUND", exit_code=1)

        session_idx, window_id = entry
        tmux_target = f"{session_idx}.{pane_index}"
        label = f"{window_name}.{pane_index}"
        resolved.append((tmux_target, label, window_id))

    if not resolved:
        emit_error("no valid targets specified", fmt, error_code="NO_TARGETS", exit_code=2)

    return resolved


def resolve_targets(targets_str: str, fmt: str = "xml") -> List[Tuple[str, str, str]]:
    """
    Parse comma-separated target string into list of (tmux_target, label, window_id) triples.

    Searches all sessions. For session-scoped resolution (e.g. dismiss), use
    resolve_targets_in_session instead.

    tmux_target: session:window_index.pane_index  (usable with -t for non-kill operations)
    label:       window_name.pane_index           (human-readable crew= attr)
    window_id:   @N stable identifier             (use for kill operations to avoid index-shift)

    Exits with error if any target cannot be resolved.
    """
    lookup = get_window_lookup()
    return _resolve_targets_with_lookup(targets_str, lookup, fmt=fmt)


def resolve_targets_in_session(
    targets_str: str,
    session: str,
    fmt: str = "xml",
) -> List[Tuple[str, str, str]]:
    """
    Like resolve_targets but restricted to windows in the given session.

    If a target window name is not found in the specified session, exits with
    an error that clearly states the session scope constraint.
    """
    lookup = get_window_lookup(session=session)
    return _resolve_targets_with_lookup(
        targets_str,
        lookup,
        fmt=fmt,
        available_context=f"in session '{session}'",
    )


def capture_pane(tmux_target: str, lines: Optional[int] = None) -> str:
    """Capture pane buffer. If lines is set, tail last N lines; else full buffer.

    Note: tmux capture-pane -S -N pads output with blank lines for unused
    terminal rows. Strip trailing blank lines so the caller gets only real
    content, and the line count does not exceed N.
    """
    cmd = ["tmux", "capture-pane", "-p", "-t", tmux_target]
    if lines is not None:
        cmd += ["-S", f"-{lines}"]
    else:
        cmd += ["-S", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    raw = result.stdout
    # Strip trailing blank lines (tmux pads unused terminal rows with empty lines)
    stripped_lines = raw.splitlines()
    while stripped_lines and stripped_lines[-1].strip() == "":
        stripped_lines.pop()
    return "\n".join(stripped_lines) + "\n" if stripped_lines else ""


def capture_pane_full(tmux_target: str) -> List[str]:
    """Capture the full pane buffer and return as a list of lines (no trailing blanks)."""
    cmd = ["tmux", "capture-pane", "-p", "-t", tmux_target, "-S", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    all_lines = result.stdout.splitlines()
    # Strip trailing blank lines (tmux pads unused terminal rows with empty lines)
    while all_lines and all_lines[-1].strip() == "":
        all_lines.pop()
    return all_lines


def capture_pane_slice(
    tmux_target: str,
    offset: int,
    lines: Optional[int],
) -> Tuple[str, int, int, int]:
    """Capture a slice of the pane buffer with position metadata.

    Returns (content, first_line, last_line, total_lines) where line numbers
    are 1-based and inclusive.  content ends with a newline when non-empty.

    offset: 0-based starting line index into the full buffer.
    lines:  number of lines to return (None -> all lines from offset onward).
    """
    all_lines = capture_pane_full(tmux_target)
    total = len(all_lines)

    start = min(offset, total)
    end = total if lines is None else min(start + lines, total)

    sliced = all_lines[start:end]
    content = "\n".join(sliced) + "\n" if sliced else ""

    # 1-based inclusive range for human-readable metadata.
    # first_line is unconditionally start+1 so that past-end offsets yield
    # the self-documenting empty-range form "lines 201-200 of 200" rather
    # than the ambiguous "lines 200-200 of 200".
    first_line = start + 1
    last_line = end
    return content, first_line, last_line, total


# ---------------------------------------------------------------------------
# XML output helpers
# ---------------------------------------------------------------------------

def indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Add pretty-print indentation to an ElementTree in-place."""
    indent = "\n" + "  " * level
    if len(elem):
        elem.text = indent + "  "
        elem.tail = indent
        for child in elem:
            indent_xml(child, level + 1)
        # last child tail should close at parent level
        child.tail = indent  # noqa: F821
    else:
        elem.tail = indent
    if level == 0:
        elem.tail = "\n"


def xml_to_string(elem: ET.Element) -> str:
    """Serialize an ElementTree element to a string with XML declaration."""
    indent_xml(elem)
    return ET.tostring(elem, encoding="unicode")


# ---------------------------------------------------------------------------
# Structured error output
# ---------------------------------------------------------------------------

def emit_error(message: str, fmt: str, error_code: str = "", exit_code: int = 1) -> None:
    """Emit a structured error and exit.

    - xml/json modes: emit structured output to stdout and exit with exit_code.
    - human mode: emit plain text to stderr and exit with exit_code.

    Exit codes:
      1   — operational error (window not found, tmux unavailable, etc.)
      2   — argument/usage error (bad target format, missing required args)
      130 — KeyboardInterrupt (SIGINT)
    """
    if fmt == "xml":
        attrs: Dict[str, str] = {"message": message}
        if error_code:
            attrs["error_code"] = error_code
        elem = ET.Element("error", **attrs)
        print(xml_to_string(elem))
    elif fmt == "json":
        obj: Dict[str, str] = {"error": message}
        if error_code:
            obj["error_code"] = error_code
        print(json.dumps(obj))
    else:
        print(f"Error: {message}", file=sys.stderr)

    if exit_code == 2:
        sys.exit(2)
    elif exit_code == 130:
        sys.exit(130)
    else:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Path mangling utility
# ---------------------------------------------------------------------------

def _mangle_path_to_project_key(path: str) -> str:
    """Convert an absolute filesystem path to a Claude Code project directory key.

    Claude Code stores per-project session files under ~/.claude/projects/<key>/,
    where <key> is derived from the project path by replacing every '/' with '-'
    and prepending a leading '-'.

    Example:
        /Users/karlhepler/worktrees/mazedesignhq/maze-monorepo
        → -Users-karlhepler-worktrees-mazedesignhq-maze-monorepo

    Rule is derived from observed ~/.claude/projects/ layout; may need updating
    on Claude Code upgrades.
    """
    return path.replace("/", "-")


# ---------------------------------------------------------------------------
# Subcommand: project-path
# ---------------------------------------------------------------------------

def cmd_project_path(worktree: str, fmt: str, send: object) -> None:
    """Resolve a worktree path to its Claude Code project directory key.

    Accepts an absolute path or '.' (which resolves to cwd). Emits the mangled
    project key and lists any .jsonl session files found at that path.

    send port (object-style):
        send.result(worktree_path, project_key, sessions_dir_exists, session_files)
        send.failure(error_code, message)
    """
    # Resolve the path — '.' expands to cwd.
    raw_path = worktree if worktree != "." else os.getcwd()
    resolved = os.path.abspath(raw_path)

    if not os.path.exists(resolved):
        send.failure("PATH_NOT_FOUND", f"path does not exist: {resolved}")
        return
    if not os.path.isdir(resolved):
        send.failure("NOT_A_DIRECTORY", f"path is not a directory: {resolved}")
        return

    project_key = _mangle_path_to_project_key(resolved)
    sessions_dir = Path.home() / ".claude" / "projects" / project_key
    sessions_dir_exists = sessions_dir.exists()

    session_files: List[Dict] = []
    if sessions_dir_exists:
        for entry in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            mtime = datetime.fromtimestamp(entry.stat().st_mtime).isoformat(timespec="seconds")
            session_files.append({"id": entry.stem, "mtime": mtime})

    send.result(resolved, project_key, sessions_dir_exists, session_files)


class _ProjectPathSend:
    """Presenter-binding for cmd_project_path that emits structured output."""

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt

    def result(
        self,
        worktree_path: str,
        project_key: str,
        sessions_dir_exists: bool,
        session_files: List[Dict],
    ) -> None:
        if self._fmt == "xml":
            root = ET.Element(
                "project-path",
                worktree=worktree_path,
                key=project_key,
                sessions_dir_exists=str(sessions_dir_exists).lower(),
            )
            for sf in session_files:
                ET.SubElement(root, "session", id=sf["id"], mtime=sf["mtime"])
            print(xml_to_string(root))
        elif self._fmt == "json":
            print(json.dumps({
                "worktree": worktree_path,
                "project_key": project_key,
                "sessions_dir_exists": sessions_dir_exists,
                "sessions": session_files,
            }, indent=2))
        else:
            print(f"worktree:    {worktree_path}")
            print(f"project_key: {project_key}")
            print(f"sessions_dir_exists: {sessions_dir_exists}")
            if session_files:
                print("sessions:")
                for sf in session_files:
                    print(f"  {sf['id']}  (mtime: {sf['mtime']})")
            else:
                print("sessions: (none)")

    def failure(self, error_code: str, message: str) -> None:
        emit_error(message, self._fmt, error_code=error_code, exit_code=1)


# ---------------------------------------------------------------------------
# Subcommand: sessions
# ---------------------------------------------------------------------------

def cmd_sessions(
    fmt: str,
    send: object,
    window_filter: Optional[str] = None,
    worktree_filter: Optional[str] = None,
) -> None:
    """List Claude session IDs for tmux windows in the current session.

    For each active tmux window (or a filtered subset), determines the
    worktree path, mangles it to a Claude project directory key, and scans
    ~/.claude/projects/<key>/ for .jsonl session files.

    Args:
        fmt: Output format (xml, json, human).
        send: Output port object with methods:
            send.session(window, worktree, session_id, last_modified) — one per session file
            send.warning(message) — no sessions found for a requested window
            send.failure(error_code, message) — window not found or filesystem error
        window_filter: If given, restrict to this single window name.
        worktree_filter: If given, use this explicit path instead of tmux windows.
    """
    current_session = get_current_session()

    if worktree_filter is not None:
        # Explicit worktree path: emit sessions for that path directly.
        resolved = os.path.abspath(worktree_filter)
        _emit_sessions_for_worktree(
            window_name="(explicit)",
            worktree_path=resolved,
            send=send,
        )
        return

    # Build window list from current tmux session.
    lookup = get_window_lookup(session=current_session)

    if window_filter is not None:
        if window_filter not in lookup:
            send.failure(
                "WINDOW_NOT_FOUND",
                f"tmux window '{window_filter}' not found in current session. "
                f"Available: {', '.join(sorted(lookup.keys())) or '(none)'}",
            )
            return
        windows_to_scan = {window_filter: lookup[window_filter]}
    else:
        windows_to_scan = lookup

    found_any = False
    last_worktree: Optional[str] = None
    for window_name, (session_idx, _window_id) in windows_to_scan.items():
        # Determine the pane's current working directory.
        result = subprocess.run(
            ["tmux", "display-message", "-t", f"{session_idx}.0", "-p", "#{pane_current_path}"],
            capture_output=True, text=True, check=False,
        )
        worktree_path = result.stdout.strip()
        if not worktree_path:
            continue

        last_worktree = worktree_path
        found_any = _emit_sessions_for_worktree(
            window_name=window_name,
            worktree_path=worktree_path,
            send=send,
            found_any=found_any,
        )

    if window_filter is not None and not found_any:
        location = f" at {last_worktree}" if last_worktree else ""
        send.warning(f"no Claude sessions found for window '{window_filter}'{location}")


def _emit_sessions_for_worktree(
    window_name: str,
    worktree_path: str,
    send: object,
    found_any: bool = False,
) -> bool:
    """Scan ~/.claude/projects/<key>/ for .jsonl files and emit via send.session.

    Returns True if at least one session was emitted (or found_any was already True).
    """
    project_key = _mangle_path_to_project_key(worktree_path)
    sessions_dir = Path.home() / ".claude" / "projects" / project_key

    if not sessions_dir.exists():
        return found_any

    session_files = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for entry in session_files:
        mtime = datetime.fromtimestamp(entry.stat().st_mtime).isoformat(timespec="seconds")
        send.session(window_name, worktree_path, entry.stem, mtime)
        found_any = True

    return found_any


class _SessionsSend:
    """Presenter-binding for cmd_sessions that buffers output until flush().

    All methods buffer their output. Call flush() once after cmd_sessions
    returns to emit the final structured document. The human format emits
    session rows inline (they are naturally streaming), but warnings/failures
    are emitted via flush() as well.
    """

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt
        self._sessions: List[Dict] = []
        self._warning: Optional[str] = None
        self._root: Optional[ET.Element] = None
        if fmt == "xml":
            self._root = ET.Element("sessions")

    def session(
        self,
        window: str,
        worktree: str,
        session_id: str,
        last_modified: str,
    ) -> None:
        if self._fmt == "xml":
            ET.SubElement(
                self._root,
                "session",
                window=window,
                worktree=worktree,
                id=session_id,
                modified=last_modified,
            )
        elif self._fmt == "json":
            self._sessions.append({
                "window": window,
                "worktree": worktree,
                "id": session_id,
                "modified": last_modified,
            })
        else:
            print(f"{session_id}  window={window}  worktree={worktree}  modified={last_modified}")

    def warning(self, message: str) -> None:
        # Store the warning; flush() emits it as part of the final document.
        self._warning = message

    def failure(self, error_code: str, message: str) -> None:
        emit_error(message, self._fmt, error_code=error_code, exit_code=1)

    def flush(self) -> None:
        """Emit buffered output. Must be called after cmd_sessions returns."""
        if self._fmt == "xml":
            if self._warning is not None:
                ET.SubElement(self._root, "warning", message=self._warning)
            print(xml_to_string(self._root))
        elif self._fmt == "json":
            obj: Dict = {"sessions": self._sessions}
            if self._warning is not None:
                obj["warning"] = self._warning
            print(json.dumps(obj, indent=2))
        else:
            # human format: session rows already emitted inline; emit warning to stderr
            if self._warning is not None:
                print(f"warning: {self._warning}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommand: resume
# ---------------------------------------------------------------------------

def _find_session_files(worktree_path: str) -> List[Dict]:
    """Scan ~/.claude/projects/<key>/ for .jsonl files sorted by mtime descending.

    Returns a list of dicts: [{"id": "<uuid>", "mtime": "<iso>", "path": Path}, ...].
    Returns empty list if the projects directory does not exist.
    """
    project_key = _mangle_path_to_project_key(worktree_path)
    sessions_dir = Path.home() / ".claude" / "projects" / project_key

    if not sessions_dir.exists():
        return []

    results = []
    for entry in sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        mtime = datetime.fromtimestamp(entry.stat().st_mtime).isoformat(timespec="seconds")
        results.append({"id": entry.stem, "mtime": mtime, "path": entry})
    return results


def _resolve_worktree_for_name(name: str) -> Optional[str]:
    """Resolve a worktree path for a given window name.

    Strategy:
    1. Check active tmux windows: if a window named <name> exists, return its pane's
       current working directory.
    2. Fall back to scanning ~/worktrees/ for a directory matching the name.

    Returns the resolved path string, or None if not found.
    """
    # Deliberately cross-session: on recovery we may need to locate a worktree
    # whose originating tmux session no longer exists, so we scan ALL tmux
    # windows first, then fall back to ~/worktrees/<name>. This is the one
    # intentional deviation from crew's single-session-scope discipline.
    #
    # Strategy 1: look for an active tmux window with this name.
    lookup = get_window_lookup()
    if name in lookup:
        session_idx, _window_id = lookup[name]
        result = subprocess.run(
            ["tmux", "display-message", "-t", f"{session_idx}.0", "-p", "#{pane_current_path}"],
            capture_output=True, text=True, check=False,
        )
        path = result.stdout.strip()
        if path and os.path.isdir(path):
            return path

    # Strategy 2: scan ~/worktrees/ for a matching directory.
    # New worktrees use the nested layout ~/worktrees/<org>/<repo>/<branch>.
    # Pre-existing flat-layout worktrees use ~/worktrees/<name>.
    # We check the nested layout first (preferred), then fall back to flat.
    worktree_root = os.environ.get("WORKTREE_ROOT") or os.path.expanduser("~/worktrees")
    worktree_root_path = Path(worktree_root)

    # Nested layout: ~/worktrees/<org>/<repo>/<name>
    # Scan two levels deep under the worktree root for a leaf directory named <name>.
    for org_dir in sorted(worktree_root_path.iterdir()) if worktree_root_path.is_dir() else []:
        if not org_dir.is_dir():
            continue
        for repo_dir in sorted(org_dir.iterdir()):
            if not repo_dir.is_dir():
                continue
            nested_candidate = repo_dir / name
            if nested_candidate.is_dir():
                return str(nested_candidate)

    # Flat layout: ~/worktrees/<name> (pre-existing worktrees, pre-fix)
    flat_candidate = worktree_root_path / name
    if flat_candidate.is_dir():
        return str(flat_candidate)

    return None


def cmd_resume(
    name: str,
    session_id: Optional[str],
    fmt: str,
    send: object,
) -> None:
    """Recreate a tmux window and resume a Claude session inside it.

    Steps:
    1. Validate window name via _SAFE_NAME_RE.
    2. Abort if window <name> already exists.
    3. Resolve worktree path from active tmux windows or ~/worktrees/<org>/<repo>/<name>
       (nested layout, e.g., ~/worktrees/orgA/repoB/<name>).
    4. Scan ~/.claude/projects/<key>/ for .jsonl session files.
    5. If --session not given, pick the most recent .jsonl by mtime.
    6. If no session file found, emit NO_SESSION failure.
    7. Create tmux window: tmux new-window -n <name> -c <worktree_path> -d
    8. Launch: staff --name <name> --resume <session_id> via tmux send-keys.
    9. Emit structured success.

    send port (object-style):
        send.resumed(window, session_id, worktree, command) — success
        send.warning(message) — advisory (e.g. multiple sessions, picked most recent)
        send.failure(error_code, message) — abort on error
    """
    # --- 1. Validate name ---
    if not name:
        send.failure("INVALID_NAME", "name must not be empty")
        return

    if not _SAFE_NAME_RE.match(name):
        send.failure(
            "INVALID_NAME",
            f"name '{name}' is not filesystem-safe: use only alphanumeric characters, "
            "hyphens, and underscores",
        )
        return

    # --- 2. Check for existing tmux window ---
    if _tmux_window_exists(name):
        send.failure(
            "WINDOW_EXISTS",
            f"tmux window '{name}' already exists — dismiss it first or choose a different name",
        )
        return

    # --- 3. Resolve worktree path ---
    worktree_path = _resolve_worktree_for_name(name)
    if worktree_path is None:
        send.failure(
            "WORKTREE_NOT_FOUND",
            f"could not find a worktree for '{name}'. "
            f"No active tmux window with that name and no worktree directory "
            f"matching '{name}' under ~/worktrees/. "
            "Use `crew create` to start a new session instead.",
        )
        return

    # --- 4. Scan for session files ---
    if session_id is not None:
        # Explicit session ID: verify it exists.
        project_key = _mangle_path_to_project_key(worktree_path)
        sessions_dir = Path.home() / ".claude" / "projects" / project_key
        session_file = sessions_dir / f"{session_id}.jsonl"
        if not session_file.exists():
            send.failure(
                "NO_SESSION",
                f"session file '{session_id}.jsonl' not found at {sessions_dir}. "
                "Use `crew sessions` to list available sessions, or `crew create` to start a new one.",
            )
            return
        chosen_session_id = session_id
    else:
        # Infer most recent session.
        session_files = _find_session_files(worktree_path)
        if not session_files:
            send.failure(
                "NO_SESSION",
                f"no Claude session files found for worktree '{worktree_path}'. "
                "Use `crew create` to start a new session instead.",
            )
            return

        chosen_session_id = session_files[0]["id"]

        # Warn if multiple sessions exist and we picked the most recent.
        if len(session_files) > 1:
            others = ", ".join(sf["id"] for sf in session_files[1:])
            send.warning(
                f"multiple sessions found for '{name}'; using most recent ({chosen_session_id}). "
                f"Other candidates: {others}. "
                f"Use --session <id> to select a specific session."
            )

    # --- 7. Create tmux window ---
    result = subprocess.run(
        ["tmux", "new-window", "-n", name, "-c", worktree_path, "-d"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        send.failure(
            "TMUX_WINDOW_FAILED",
            f"tmux new-window failed: {result.stderr.strip()}",
        )
        return

    # --- 8. Launch staff --model sonnet --name <name> --resume <session_id> ---
    spawn_cmd = f"staff --model sonnet --name {name} --resume {chosen_session_id}"
    subprocess.run(
        ["tmux", "send-keys", "-t", name, spawn_cmd, "Enter"],
        capture_output=True, check=False,
    )

    # --- 9. Emit success ---
    send.resumed(name, chosen_session_id, worktree_path, spawn_cmd)


class _ResumeSend:
    """Presenter-binding for cmd_resume that emits structured output."""

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt
        self._warned = False

    def resumed(
        self,
        window: str,
        session_id: str,
        worktree: str,
        command: str,
    ) -> None:
        if self._fmt == "xml":
            elem = ET.Element(
                "resumed",
                window=window,
                session=session_id,
                worktree=worktree,
                command=command,
            )
            print(xml_to_string(elem))
        elif self._fmt == "json":
            print(json.dumps({
                "window": window,
                "session": session_id,
                "worktree": worktree,
                "command": command,
            }, indent=2))
        else:
            print(f"resumed: window={window} session={session_id} worktree={worktree}")
            print(f"  {command}")

    def warning(self, message: str) -> None:
        if self._fmt in ("xml", "json"):
            # Warnings before success are printed to stderr in structured modes
            # so they don't corrupt the primary structured output.
            print(f"warning: {message}", file=sys.stderr)
        else:
            print(f"warning: {message}", file=sys.stderr)

    def failure(self, error_code: str, message: str) -> None:
        emit_error(message, self._fmt, error_code=error_code, exit_code=1)


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------

def cmd_list(fmt: str, show_all: bool = False) -> None:
    # Confine to the current tmux session only (P6.1).
    # Equivalent to: tmux list-windows -t <current-session> (not list-windows -a).
    current_session = get_current_session()
    all_panes = get_all_panes(session=current_session)
    # By default, filter to Claude panes only. Pass show_all=True to include everything.
    panes = all_panes if show_all else [
        p for p in all_panes if is_claude_pane(p[4])
    ]

    if fmt == "xml":
        root = ET.Element("crew")
        current_window: Optional[ET.Element] = None
        current_window_key: Optional[str] = None

        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                current_window = ET.SubElement(root, "window", name=window_name)
                current_window_key = wkey
            ET.SubElement(current_window, "pane", index=pane_index, command=pane_cmd)

        print(xml_to_string(root))
    elif fmt == "json":
        windows: List[Dict] = []
        current_window_key = None
        current_window_obj: Optional[Dict] = None
        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                current_window_obj = {"name": window_name, "panes": []}
                windows.append(current_window_obj)
                current_window_key = wkey
            current_window_obj["panes"].append({"index": pane_index, "command": pane_cmd})
        print(json.dumps({"windows": windows}, indent=2))
    else:
        # human format
        current_window_key = None
        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                print(f"window: {window_name}")
                current_window_key = wkey
            print(f"  pane: {pane_index} ({pane_cmd})")


# ---------------------------------------------------------------------------
# Subcommand: tell
# ---------------------------------------------------------------------------

# Heuristic to detect legacy argument order (message first, targets last).
# A first positional arg that looks like a natural-language message rather than
# a target spec is flagged. Target specs are short identifiers: word characters,
# hyphens, digits — no spaces (_SAFE_NAME_RE at the bottom of this file enforces
# this for crew-managed window names). Any space in the first positional arg is
# therefore unambiguously a message, not a target.
# The heuristic fires when the first arg:
#   - contains any space (messages have spaces; target specs never do), OR
#   - contains non-ASCII characters (emoji, Unicode punctuation), OR
#   - ends with common sentence-ending punctuation (. ? !)
#
# For ambiguous single-word or punctuation-free messages the heuristic stays
# silent and the new behavior (targets-first) is used — the user corrects if needed.
_LEGACY_ORDER_RE = re.compile(
    r" "                # any space — _SAFE_NAME_RE prohibits spaces in crew-managed window
                        # names, so any space in the first positional arg is unambiguously
                        # a message, not a target spec
    r"|[^\x00-\x7F]"   # non-ASCII (Unicode punctuation, emoji)
    r"|[.?!]$"         # ends with sentence-ending punctuation
)


def _looks_like_message_not_target(s: str) -> bool:
    """Return True if s looks like a human-readable message rather than a target spec."""
    return bool(_LEGACY_ORDER_RE.search(s))


def cmd_tell(targets_str: str, message: Optional[str], fmt: str, use_keys: bool = False, tell_file: Optional[str] = None) -> None:
    # --tell-file: read message from file; delete only after all targets received successfully.
    file_path_to_delete: Optional[str] = None
    if tell_file is not None:
        try:
            with open(tell_file, encoding="utf-8") as fh:
                message = fh.read().rstrip("\n")
        except OSError as exc:
            emit_error(
                f"--tell-file '{tell_file}': {exc.strerror}",
                fmt,
                error_code="TELL_FILE_ERROR",
                exit_code=1,
            )
        else:
            file_path_to_delete = tell_file

    resolved = resolve_targets(targets_str, fmt=fmt)

    if fmt == "xml":
        root = ET.Element("tell")
    elif fmt == "json":
        json_targets: List[Dict] = []

    # Track delivery success across all targets: file is only deleted when every
    # tmux send-keys subprocess exits 0. Any failure (non-zero returncode or
    # exception) prevents deletion so the caller can retry.
    all_delivered = True
    for tmux_target, label, _window_id in resolved:
        try:
            if use_keys:
                # Keys mode: split message into tmux key tokens and pass directly.
                # No -l flag — tokens are interpreted as tmux key names (Enter, Escape, C-c, etc.).
                tokens = (message or "").split()
                result = subprocess.run(
                    ["tmux", "send-keys", "-t", tmux_target] + tokens,
                    check=False
                )
                if result.returncode != 0:
                    all_delivered = False
            else:
                # Text mode: send message as literal text, then Enter as a separate key.
                result = subprocess.run(
                    ["tmux", "send-keys", "-t", tmux_target, message or ""],
                    check=False
                )
                if result.returncode != 0:
                    all_delivered = False
                else:
                    time.sleep(0.15)
                    result_enter = subprocess.run(
                        ["tmux", "send-keys", "-t", tmux_target, "Enter"],
                        check=False
                    )
                    if result_enter.returncode != 0:
                        all_delivered = False
        except Exception:
            all_delivered = False
        if fmt == "xml":
            ET.SubElement(root, "target", crew=label, status="sent")
        elif fmt == "json":
            json_targets.append({"crew": label, "status": "sent"})
        else:
            print(f"sent -> {label}")

    if fmt == "xml":
        print(xml_to_string(root))
    elif fmt == "json":
        print(json.dumps({"targets": json_targets}, indent=2))

    # Delete only after all targets received successfully (mirrors kanban do --file semantics).
    # File is preserved on any delivery failure so the caller can retry.
    if file_path_to_delete is not None and all_delivered:
        os.unlink(file_path_to_delete)


# ---------------------------------------------------------------------------
# Subcommand: read
# ---------------------------------------------------------------------------

def _read_one(
    tmux_target: str,
    label: str,
    lines: Optional[int],
    offset: Optional[int],
    fmt: str,
    parent: Optional[ET.Element] = None,
) -> Optional[Dict]:
    """Read a single pane and emit output (xml child or human text) or return dict for JSON.

    When offset is None the legacy path is used (tail last N lines) for full
    backward compatibility.  When offset is provided the paginated slice path
    is used and position metadata is included.

    For fmt == "json", returns a dict instead of printing; caller is responsible
    for final JSON emission.  For all other formats, returns None.
    """
    if offset is None:
        # Legacy path: tail last N lines, no position metadata.
        content = capture_pane(tmux_target, lines)
        lines_attr = str(lines) if lines is not None else "all"
        if fmt == "xml":
            if parent is not None:
                child = ET.SubElement(parent, "output", crew=label, lines=lines_attr)
                child.text = content
            else:
                elem = ET.Element("output", crew=label, lines=lines_attr)
                elem.text = content
                print(xml_to_string(elem))
        elif fmt == "json":
            return {"crew": label, "lines": lines_attr, "content": content}
        else:
            print(f"--- {label} ---")
            print(content, end="")
    else:
        # Paginated path: absolute offset + limit with position metadata.
        content, first_line, last_line, total = capture_pane_slice(tmux_target, offset, lines)
        position_header = f"lines {first_line}-{last_line} of {total}"
        if fmt == "xml":
            attrs = {
                "crew": label,
                "lines": str(lines) if lines is not None else "all",
                "from": str(offset),
                "position": position_header,
            }
            if parent is not None:
                child = ET.SubElement(parent, "output", **attrs)
                child.text = content
            else:
                elem = ET.Element("output", **attrs)
                elem.text = content
                print(xml_to_string(elem))
        elif fmt == "json":
            return {
                "crew": label,
                "lines": str(lines) if lines is not None else "all",
                "from": offset,
                "position": position_header,
                "content": content,
            }
        else:
            print(f"--- {label} ({position_header}) ---")
            print(content, end="")
    return None


def cmd_read(targets_str: str, lines: Optional[int], offset: Optional[int], fmt: str) -> None:
    resolved = resolve_targets(targets_str, fmt=fmt)

    if fmt == "json":
        outputs = []
        for tmux_target, label, _window_id in resolved:
            obj = _read_one(tmux_target, label, lines, offset, fmt)
            if obj is not None:
                outputs.append(obj)
        if len(outputs) == 1:
            print(json.dumps(outputs[0], indent=2))
        else:
            print(json.dumps({"reads": outputs}, indent=2))
    elif len(resolved) == 1:
        tmux_target, label, _window_id = resolved[0]
        _read_one(tmux_target, label, lines, offset, fmt, parent=None)
    else:
        if fmt == "xml":
            root = ET.Element("reads")
            for tmux_target, label, _window_id in resolved:
                _read_one(tmux_target, label, lines, offset, fmt, parent=root)
            print(xml_to_string(root))
        else:
            for i, (tmux_target, label, _window_id) in enumerate(resolved):
                _read_one(tmux_target, label, lines, offset, fmt, parent=None)
                if i < len(resolved) - 1:
                    print()


# ---------------------------------------------------------------------------
# Subcommand: dismiss
# ---------------------------------------------------------------------------

def cmd_dismiss(targets_str: str, fmt: str) -> None:
    """Dismiss (kill) one or more tmux panes or windows.

    Safety constraints:
    - Only targets in the CURRENT tmux session are permitted. Targets
      resolving to a different session are rejected with an error before any
      kill is attempted.
    - The invoking window (the window crew itself is running in) is protected
      from self-kill and rejected with an error.

    Uses stable tmux window IDs (@N) for kill targeting so that index-shift
    caused by earlier kills in the same loop does not cause later targets to
    miss or hit wrong windows.

    When fmt == "xml", output is wrapped in a <dismiss> root element, e.g.:
        <dismiss><target crew="worker.0" status="dismissed" /></dismiss>
    The root element name matches the subcommand name, consistent with the
    <tell> pattern used by cmd_tell.
    """
    current_session = get_current_session()
    current_window_id = get_current_window_id()

    if current_session is None:
        emit_error(
            "crew dismiss must be run inside a tmux session",
            fmt,
            error_code="NOT_IN_TMUX",
            exit_code=1,
        )

    # Resolve targets scoped to the current session only.
    raw_tokens = [t.strip() for t in targets_str.split(",") if t.strip()]
    resolved = resolve_targets_in_session(targets_str, current_session, fmt=fmt)

    # Safety pre-checks: validate all targets before killing any.
    for raw, (tmux_target, label, window_id) in zip(raw_tokens, resolved):
        # Extract session from tmux_target (format: session:index.pane)
        target_session = tmux_target.split(":")[0]
        if target_session != current_session:
            emit_error(
                f"target '{raw}' belongs to session '{target_session}', "
                f"not the current session '{current_session}'. "
                "crew dismiss is scoped to the current session only.",
                fmt,
                error_code="WRONG_SESSION",
                exit_code=1,
            )
        if current_window_id and window_id == current_window_id:
            emit_error(
                f"target '{raw}' is the current window ({window_id}) — "
                "crew dismiss cannot kill the window it is running in.",
                fmt,
                error_code="SELF_KILL",
                exit_code=1,
            )

    if fmt == "xml":
        root = ET.Element("dismiss")
    elif fmt == "json":
        json_dismissed: List[Dict] = []

    for raw, (tmux_target, label, window_id) in zip(raw_tokens, resolved):
        if "." in raw:
            # pane target: use stable @id.pane_index so index-shift doesn't affect us
            _, pane_index = tmux_target.rsplit(".", 1)
            stable_target = f"{window_id}.{pane_index}"
            subprocess.run(["tmux", "kill-pane", "-t", stable_target], check=False)
            # Pane dismissals don't remove the whole session, so no sentinel cleanup.
        else:
            # bare window: kill via stable @id — immune to window index renumbering
            subprocess.run(["tmux", "kill-window", "-t", window_id], check=False)
            # Clean up the readiness sentinel so it doesn't leak after session exit.
            # The window name is the raw target itself (no pane suffix for bare windows).
            _cleanup_sentinel(raw)
        if fmt == "xml":
            ET.SubElement(root, "target", crew=label, status="dismissed")
        elif fmt == "json":
            json_dismissed.append({"crew": label, "status": "dismissed"})
        else:
            print(f"dismissed -> {label}")

    if fmt == "xml":
        print(xml_to_string(root))
    elif fmt == "json":
        print(json.dumps({"targets": json_dismissed}, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: find
# ---------------------------------------------------------------------------

def cmd_find(pattern: str, targets_str: Optional[str], lines: Optional[int], fmt: str) -> None:  # filter: is_claude_pane + self-exclusion (no-targets path)
    if targets_str:
        resolved = resolve_targets(targets_str, fmt=fmt)
    else:
        # Confine to the current tmux session only (M-01 fix: mirrors cmd_list/cmd_status).
        # By default, filter to Claude panes only and exclude the caller's own window
        # (mirrors cmd_list/cmd_status behavior to prevent false positives from sstaff pane).
        current_session = get_current_session()
        current_window_id = get_current_window_id()
        lookup = get_window_lookup(session=current_session)
        # Build reverse map: window_name -> window_id for self-exclusion.
        window_id_by_name: Dict[str, str] = {
            name: wid for name, (_idx, wid) in lookup.items()
        }
        all_panes = get_all_panes(session=current_session)
        # Filter to Claude panes; exclude panes in the caller's own window.
        panes = [
            p for p in all_panes
            if is_claude_pane(p[4])
            and (not current_window_id or window_id_by_name.get(p[2]) != current_window_id)
        ]
        resolved = []
        for session, window_index, window_name, pane_index, _pane_cmd in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            resolved.append((tmux_target, label, ""))

    compiled = re.compile(pattern)

    if fmt == "xml":
        root = ET.Element("matches", pattern=pattern)
    elif fmt == "json":
        json_matches: List[Dict] = []
    else:
        found_any = False

    for tmux_target, label, _window_id in resolved:
        content = capture_pane(tmux_target, lines)
        for lineno, line in enumerate(content.splitlines(), start=1):
            if compiled.search(line):
                if fmt == "xml":
                    match_elem = ET.SubElement(root, "match", crew=label, line=str(lineno))
                    match_elem.text = line
                elif fmt == "json":
                    json_matches.append({"crew": label, "line": lineno, "text": line})
                else:
                    print(f"{label}:{lineno}: {line}")
                    found_any = True

    if fmt == "xml":
        print(xml_to_string(root))
    elif fmt == "json":
        print(json.dumps({"pattern": pattern, "matches": json_matches}, indent=2))
    else:
        if not found_any:
            print("(no matches found)")


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def _build_status_panes(
    show_all: bool,
    current_session: Optional[str],
) -> List[Tuple[str, str, str, str, str]]:
    """Build the list of panes to include in crew status output.

    Default (show_all=False): include Claude panes (pane 0 of windows running Claude)
    PLUS any additional panes in those same windows (e.g., smithers in pane 1).
    This ensures that when a staff engineer window has a smithers split, both panes
    appear in the status output so sstaff sees the full picture.

    show_all=True: include all panes regardless of command (existing behaviour).
    """
    all_panes = get_all_panes(session=current_session)

    if show_all:
        return all_panes

    # Identify windows that have at least one Claude pane.
    claude_window_keys: set = set()
    for session, window_index, _window_name, _pane_index, pane_cmd in all_panes:
        if is_claude_pane(pane_cmd):
            claude_window_keys.add(f"{session}:{window_index}")

    # Include ALL panes from windows that have a Claude pane.
    # This surfaces smithers (or any other pane) alongside the Claude pane.
    return [
        p for p in all_panes
        if f"{p[0]}:{p[1]}" in claude_window_keys
    ]


def cmd_status(lines: int, fmt: str, show_all: bool = False) -> None:
    # Confine to the current tmux session only (P6.1).
    current_session = get_current_session()
    panes = _build_status_panes(show_all=show_all, current_session=current_session)

    if fmt == "xml":
        root = ET.Element("status", lines=str(lines))
        current_window_key: Optional[str] = None
        current_window_elem: Optional[ET.Element] = None
        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            if wkey != current_window_key:
                current_window_elem = ET.SubElement(root, "window", name=window_name)
                current_window_key = wkey
            pane_elem = ET.SubElement(
                current_window_elem,  # type: ignore[arg-type]
                "pane",
                index=pane_index,
                command=pane_cmd,
                crew=label,
            )
            pane_elem.text = content
        print(xml_to_string(root))
    elif fmt == "json":
        windows_out: List[Dict] = []
        current_window_key_j: Optional[str] = None
        current_window_obj: Optional[Dict] = None
        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            if wkey != current_window_key_j:
                current_window_obj = {"name": window_name, "panes": []}
                windows_out.append(current_window_obj)
                current_window_key_j = wkey
            current_window_obj["panes"].append(  # type: ignore[index]
                {"index": pane_index, "command": pane_cmd, "crew": label, "content": content}
            )
        print(json.dumps({"lines": lines, "windows": windows_out}, indent=2))
    else:
        # human: list first, then content per pane
        current_window_key_h: Optional[str] = None
        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key_h:
                print(f"window: {window_name}")
                current_window_key_h = wkey
            print(f"  pane: {pane_index} ({pane_cmd})")

        print()

        for session, window_index, window_name, pane_index, _pane_cmd in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            print(f"--- {label} (last {lines} lines) ---")
            print(content, end="")
            print()


# ---------------------------------------------------------------------------
# Subcommand: create
# ---------------------------------------------------------------------------

# Regex for filesystem-safe names: alphanumeric, hyphens, underscores only.
# No dots, slashes, spaces, or shell-special characters.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _git_rev_parse(args: List[str], cwd: Optional[str] = None) -> Optional[str]:
    """Run git rev-parse with given args, return stdout stripped or None on failure."""
    result = subprocess.run(
        ["git", "rev-parse"] + args,
        capture_output=True, text=True, check=False, cwd=cwd
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_current_branch(repo: str) -> Optional[str]:
    """Return the current branch name of the given repo, or None if detached/error."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, check=False, cwd=repo
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _branch_exists(repo: str, branch: str) -> bool:
    """Return True if branch exists locally in the given repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        capture_output=True, text=True, check=False, cwd=repo
    )
    return result.returncode == 0


# Regex to extract org/repo from git remote URLs.
# Handles both SSH (git@github.com:org/repo.git) and HTTPS (https://host/org/repo.git).
# Source of truth: modules/git/workout.bash — sed -E 's#.*[:/]([^/]+/[^/]+)\.git$#\1#'
#
# Intentional extension beyond modules/git/workout.bash: the `.git` suffix is
# optional in this regex so SSH URLs like `git@github.com:org/repo` (without
# `.git`) extract correctly. workout.bash's sed formula requires `.git` and
# exits with an error for those inputs. Safer for crew users.
_REMOTE_URL_ORG_REPO_RE = re.compile(
    r".*[:/]([^/]+/[^/]+?)(?:\.git)?$"
)


def _extract_org_repo_from_remote(remote_url: str) -> Optional[str]:
    """Extract '<org>/<repo>' from a git remote URL.

    Supports SSH (git@github.com:org/repo.git) and HTTPS
    (https://github.com/org/repo.git) URLs, with or without .git suffix.

    Returns the org/repo string, or None if the URL cannot be parsed.
    """
    m = _REMOTE_URL_ORG_REPO_RE.match(remote_url.strip())
    if not m:
        return None
    return m.group(1)


def _git_remote_url(repo: str, remote: str = "origin") -> Optional[str]:
    """Return the URL of the given git remote, or None on failure."""
    result = subprocess.run(
        ["git", "remote", "get-url", remote],
        capture_output=True, text=True, check=False, cwd=repo
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_worktree_path(repo: str, branch: str) -> Tuple[str, bool]:
    """Resolve the canonical worktree path for a given repo and branch.

    Matches the path formula used by modules/git/workout.bash:
        ${WORKTREE_ROOT:-$HOME/worktrees}/<org>/<repo>/<branch>

    Where <org>/<repo> is extracted from the git remote 'origin' URL.

    Falls back to the flat layout (${WORKTREE_ROOT:-$HOME/worktrees}/<branch>)
    if the origin remote is absent or the URL cannot be parsed.

    Args:
        repo:   Absolute path to the git repository root.
        branch: The branch name to be checked out in the worktree.

    Returns:
        A tuple of (path, used_fallback) where:
        - path is the absolute path string for the new worktree directory.
        - used_fallback is True when the flat layout was used due to a missing
          or unparseable remote, False when the nested org/repo layout was used.
        Callers should warn the user when used_fallback is True, because flat
        layout paths diverge from the nested layout that crew resume scans for.
    """
    worktree_root = os.environ.get("WORKTREE_ROOT") or os.path.expanduser("~/worktrees")

    remote_url = _git_remote_url(repo)
    if remote_url:
        org_repo = _extract_org_repo_from_remote(remote_url)
        if org_repo and ".." not in org_repo:
            return os.path.join(worktree_root, org_repo, branch), False

    # Fallback: no remote or unparseable URL — use flat layout for safety.
    return os.path.join(worktree_root, branch), True


def _git_has_uncommitted_changes(repo: str) -> bool:
    """Return True if the repo has any uncommitted changes (staged or unstaged)."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=False, cwd=repo
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _fetch_base_if_tracked(repo: str, base: str) -> str:
    """Fetch latest origin/<base> if base tracks a remote.

    Returns the effective base ref to use for branch creation:
    - If tracks origin and fetch succeeded → 'origin/<base>'
    - If tracks origin but fetch failed    → '<base>' (local fallback)
    - If local-only                        → '<base>'

    Note: assumes a single remote named 'origin' (standard git convention).
    Multi-remote setups are not supported by this helper; extend with explicit
    remote selection if needed.
    """
    upstream_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", f"{base}@{{upstream}}"],
        capture_output=True, text=True, check=False, cwd=repo
    )

    if upstream_result.returncode != 0:
        # Local-only: no upstream tracking ref
        print(
            f"Base '{base}' is local-only, using local ref",
            file=sys.stderr,
        )
        return base

    # Branch tracks a remote — attempt fetch
    print(f"Fetching latest origin/{base}...", file=sys.stderr)
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", base],
        capture_output=True, text=True, check=False, cwd=repo
    )

    if fetch_result.returncode != 0:
        print(
            f"warning: fetch origin/{base} failed (using local ref): "
            f"{fetch_result.stderr.strip()}",
            file=sys.stderr,
        )
        return base  # fallback: use local branch ref

    return f"origin/{base}"  # use remote-tracking ref for branch creation


def _tmux_window_exists(name: str) -> bool:
    """Return True if a tmux window named exactly `name` exists in any session."""
    result = subprocess.run(
        ["tmux", "list-windows", "-a", "-F", "#{window_name}"],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return False
    return name in result.stdout.splitlines()


def _deliver_tell(
    window_name: str,
    tell: str,
    verify_timeout: float = 5.0,
    poll_interval: float = 0.25,
) -> Tuple[bool, str]:
    """Deliver the tell payload via send-keys and verify it appears in the pane.

    Returns (success: bool, reason: str).
    success=True means the tell text was observed in the pane after delivery.
    success=False means either send-keys failed or verification timed out.

    Note: newlines in the tell payload will fragment the message because
    tmux send-keys converts literal newlines to Enter keystrokes. Callers
    needing multi-line briefs should pre-process the payload or use the
    tempfile injection pattern (see modules/git/workout-claude.py).
    """
    # Guard: empty or whitespace-only tell cannot be verified — return failure
    # immediately rather than letting "" in result.stdout produce a false
    # told=true (empty string is always a substring of any string in Python).
    tell_excerpt = tell[:40].strip()
    if not tell_excerpt:
        return False, "empty tell: nothing to deliver"

    # Send the message text
    r1 = subprocess.run(
        ["tmux", "send-keys", "-t", f"{window_name}.0", tell],
        capture_output=True, check=False,
    )
    if r1.returncode != 0:
        return False, f"send-keys text failed (exit {r1.returncode})"

    time.sleep(0.15)

    # Send Enter
    r2 = subprocess.run(
        ["tmux", "send-keys", "-t", f"{window_name}.0", "Enter"],
        capture_output=True, check=False,
    )
    if r2.returncode != 0:
        return False, f"send-keys Enter failed (exit {r2.returncode})"

    # Verify: poll until the tell text appears in the pane (or timeout).
    # Use a short excerpt to keep the check stable across line wrapping.
    # tell_excerpt is computed at the top of this function.
    deadline = time.monotonic() + verify_timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", f"{window_name}.0", "-S", "-50"],
            capture_output=True, text=True, check=False,
        )
        if tell_excerpt in result.stdout:
            return True, "verified"
        time.sleep(poll_interval)

    return False, "verification timeout: tell text not observed in pane"


def run_post_switch_hook(source_repo: str, worktree_path: str, branch: str) -> Optional[Tuple[int, str]]:
    """Run .git/workout-hooks/post-switch if it exists in the source repo.

    Returns None if the hook is absent (no-op).
    Returns (returncode, tail_output) if the hook ran, where tail_output is the
    last 20 lines of combined stdout+stderr for failure diagnosis.
    """
    hook_path = os.path.join(source_repo, ".git", "workout-hooks", "post-switch")
    if not os.path.isfile(hook_path):
        return None
    if not os.access(hook_path, os.X_OK):
        print(f"[crew] warning: {hook_path} exists but is not executable; skipping post-switch hook", file=sys.stderr)
        return None

    # Env var contract: WORKTREE_PATH, SOURCE_REPO, BRANCH provided for hooks
    # that need them. The maze-monorepo reference hook uses only `cwd` today;
    # these are forward-looking.
    env = os.environ.copy()
    env["WORKTREE_PATH"] = worktree_path
    env["SOURCE_REPO"] = source_repo
    env["BRANCH"] = branch

    result = subprocess.run(
        [hook_path],
        cwd=worktree_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    tail_lines = combined.splitlines()[-20:]
    tail_output = "\n".join(tail_lines)
    return result.returncode, tail_output


# ---------------------------------------------------------------------------
# tmux fire-and-forget helper
# ---------------------------------------------------------------------------

def _tmux_fire_and_forget(args: list, context: str) -> None:
    """Run a tmux subprocess where failure is non-fatal but should be visible.

    Used for cosmetic / best-effort tmux operations (e.g. setting window icons,
    sending initial keystrokes) where blocking on failure would harm UX more than
    a missing side-effect would. Non-zero returncodes and exceptions raised by
    subprocess.run itself are surfaced to stderr; nothing is raised back to the
    caller.
    """
    try:
        result = subprocess.run(args, capture_output=True, check=False)
    except Exception as exc:  # pragma: no cover — covered by test_helper_does_not_raise_on_subprocess_exception
        print(
            f"[crew create] tmux call raised during {context}: {' '.join(args)} "
            f"({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        print(
            f"[crew create] tmux call failed during {context}: {' '.join(args)} "
            f"(exit {result.returncode}): {stderr}",
            file=sys.stderr,
        )


def cmd_create(
    name: str,
    repo: Optional[str],
    branch: Optional[str],
    base: Optional[str],
    fmt: str,
    cmd_override: Optional[str] = None,
    tell: Optional[str] = None,
    no_worktree: bool = False,
    tell_file: Optional[str] = None,
    mcp_trust: str = "all",
) -> None:
    """Create a git worktree, tmux window, and staff session end-to-end.

    Steps:
    1. Validate name (non-empty, filesystem-safe).
    1b. Validate --no-worktree flag combinations.
    1c. Resolve --tell-file into tell payload (read file, schedule delete on success).
    2. Check for existing tmux window named <name>.
    3. Resolve repo (default: current git root).
    4. Resolve branch (default: <name>).
    5. Resolve base branch (default: current branch of repo).
    6. Resolve worktree path to ~/worktrees/<org>/<repo>/<branch>.
    7. Check for existing worktree at that path.
    8. Create branch if it doesn't exist.
    9. Create git worktree.
    9b. Run .git/workout-hooks/post-switch if present (silent no-op if absent).
    10. Create tmux window.
    11. If --tell: clean stale sentinel for <name>, then start staff in the new window.
    12. If --tell: wait for readiness sentinel (dropped by SessionStart lifecycle hook),
        then deliver the initial message. Outer ceiling is 5 minutes; failure reason
        distinguishes hook-missing from session crash.
    13. Emit structured result.
    14. Auto-delete --tell-file on successful tell delivery.

    When no_worktree=True, steps 4-9 are skipped and the repo directory itself is
    used as the tmux window cwd. Incompatible with --branch and --base.
    """

    # --- 1. Validate name ---
    if not name:
        emit_error("name must not be empty", fmt, error_code="INVALID_NAME", exit_code=2)

    if not _SAFE_NAME_RE.match(name):
        emit_error(
            f"name '{name}' is not filesystem-safe: use only alphanumeric characters, "
            "hyphens, and underscores",
            fmt,
            error_code="INVALID_NAME",
            exit_code=2,
        )

    # --- 1b. Validate --no-worktree flag combinations ---
    if no_worktree:
        if branch is not None:
            emit_error(
                "--branch is incompatible with --no-worktree: no worktree is being "
                "created, so there is no branch to check out. Use --repo to point at "
                "the directory containing the branch you want.",
                fmt,
                error_code="INCOMPATIBLE_FLAGS",
                exit_code=2,
            )
        if base is not None:
            emit_error(
                "--base is incompatible with --no-worktree: --base specifies the "
                "branch to create a new worktree from, which is not applicable when "
                "--no-worktree is set.",
                fmt,
                error_code="INCOMPATIBLE_FLAGS",
                exit_code=2,
            )

    # --- 1c. Resolve --tell-file into tell payload ---
    # Read file content now (fail fast if unreadable) and schedule deletion on
    # successful delivery. The file is preserved if delivery fails.
    tell_file_path: Optional[str] = None
    if tell_file is not None:
        try:
            with open(tell_file, encoding="utf-8") as fh:
                tell = fh.read().rstrip("\n")
        except OSError as exc:
            emit_error(
                f"--tell-file '{tell_file}': {exc.strerror}",
                fmt,
                error_code="TELL_FILE_ERROR",
                exit_code=1,
            )
        tell_file_path = tell_file

    # --- 2. Check for existing tmux window ---
    if _tmux_window_exists(name):
        emit_error(
            f"tmux window '{name}' already exists — choose a different name or "
            "dismiss the existing window first",
            fmt,
            error_code="WINDOW_EXISTS",
            exit_code=2,
        )

    # --- 3. Resolve repo ---
    if repo is None:
        detected = _git_rev_parse(["--show-toplevel"])
        if detected is None:
            emit_error(
                "not inside a git repository and --repo was not specified",
                fmt,
                error_code="NOT_A_GIT_REPO",
                exit_code=1,
            )
        repo = detected
    else:
        repo = os.path.expanduser(repo)
        if not os.path.isdir(repo):
            emit_error(
                f"--repo path '{repo}' does not exist or is not a directory",
                fmt,
                error_code="REPO_NOT_FOUND",
                exit_code=1,
            )
        # Verify it is a git repo
        if _git_rev_parse(["--show-toplevel"], cwd=repo) is None:
            emit_error(
                f"--repo path '{repo}' is not a git repository",
                fmt,
                error_code="NOT_A_GIT_REPO",
                exit_code=1,
            )

    if no_worktree:
        # --- No-worktree path: use repo dir directly as the tmux window cwd ---
        # Steps 4 (branch), 5 (base), 6 (worktree path expansion),
        # 7 (existing worktree check), 8 (branch creation), 9 (git worktree add)
        # are all skipped.

        # Git-repo invariant is already enforced by step 3 before reaching here.

        # Warn on uncommitted changes — don't block.
        if _git_has_uncommitted_changes(repo):
            print(
                f"warning: '{repo}' has uncommitted changes. "
                "The staff session will start in a dirty working tree.",
                file=sys.stderr,
            )

        worktree_path = repo  # tmux cwd = repo root

    else:
        # --- Worktree path (existing behavior) ---

        # --- 4. Resolve branch ---
        if branch is None:
            branch = name

        # --- 5. Resolve base branch ---
        if base is None:
            base = _git_current_branch(repo)
            if base is None:
                emit_error(
                    f"could not determine current branch of '{repo}' (detached HEAD?) — "
                    "specify --base explicitly",
                    fmt,
                    error_code="DETACHED_HEAD",
                    exit_code=1,
                )

        # --- 5a. Verify base exists (local or remote) ---
        base_ref_result = subprocess.run(
            ["git", "rev-parse", "--verify", base],
            capture_output=True, text=True, check=False, cwd=repo
        )
        if base_ref_result.returncode != 0:
            emit_error(
                f"base branch '{base}' does not exist locally or as a remote-tracking ref",
                fmt,
                error_code="BRANCH_NOT_FOUND",
                exit_code=1,
            )

        # --- 5b. Fetch base from origin if tracked (before worktree creation) ---
        effective_base = _fetch_base_if_tracked(repo, base)

        # --- 6. Resolve worktree path ---
        # Uses the same org/repo-nested formula as modules/git/workout.bash:
        #   ${WORKTREE_ROOT:-~/worktrees}/<org>/<repo>/<branch>
        # This avoids flat-namespace collisions when multiple repos share branch names.
        assert repo is not None  # guaranteed by step 3
        assert branch is not None  # guaranteed by step 4
        worktree_path, used_fallback = resolve_worktree_path(repo, branch)
        if used_fallback:
            print(
                f"warning: no 'origin' remote configured for '{repo}'; "
                f"worktree placed at '{worktree_path}'\n"
                "  crew create and workout normally use "
                "~/worktrees/<org>/<repo>/<branch> layout.\n"
                "  With no remote, falling back to flat layout. crew resume may not "
                "find this worktree via the nested scan; specify the full path "
                "manually if needed.",
                file=sys.stderr,
            )

        # --- 7. Check for existing worktree at that path ---
        if os.path.exists(worktree_path):
            emit_error(
                f"worktree path '{worktree_path}' already exists — remove it or choose "
                "a different name",
                fmt,
                error_code="WORKTREE_EXISTS",
                exit_code=2,
            )

        # --- 8. Create branch if it doesn't exist ---
        branch_was_new = False
        if not _branch_exists(repo, branch):
            result = subprocess.run(
                ["git", "branch", branch, effective_base],
                capture_output=True, text=True, check=False, cwd=repo
            )
            if result.returncode != 0:
                emit_error(
                    f"failed to create branch '{branch}' from '{base}': "
                    f"{result.stderr.strip()}",
                    fmt,
                    error_code="BRANCH_CREATE_FAILED",
                    exit_code=1,
                )
            branch_was_new = True

        # --- 9. Create git worktree ---
        result = subprocess.run(
            ["git", "worktree", "add", worktree_path, branch],
            capture_output=True, text=True, check=False, cwd=repo
        )
        if result.returncode != 0:
            # Clean up branch if we just created it
            if branch_was_new:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True, check=False, cwd=repo
                )
            emit_error(
                f"git worktree add failed: {result.stderr.strip()}",
                fmt,
                error_code="WORKTREE_ADD_FAILED",
                exit_code=1,
            )

    # --- 9b. Run post-switch hook (worktree path only) ---
    # The legacy workout CLI runs .git/workout-hooks/post-switch after worktree creation.
    # crew create mirrors that behavior so spawned sessions start fully initialized
    # (mise trust, pnpm install, etc.). Absent hook = silent no-op.
    if not no_worktree:
        assert branch is not None
        hook_result = run_post_switch_hook(repo, worktree_path, branch)
        if hook_result is not None:
            hook_rc, hook_tail = hook_result
            if hook_rc != 0:
                emit_error(
                    f"post-switch hook exited {hook_rc} — worktree setup incomplete. "
                    f"Last output:\n{hook_tail}",
                    fmt,
                    error_code="POST_SWITCH_HOOK_FAILED",
                    exit_code=1,
                )

    # --- 10. Create tmux window ---
    result = subprocess.run(
        ["tmux", "new-window", "-n", name, "-c", worktree_path, "-d"],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        # Worktree exists but window creation failed — report partial state, do NOT
        # auto-remove the worktree (user may have other uses for it).
        if no_worktree:
            partial_state_msg = (
                f"No worktree was created (--no-worktree mode). "
                f"You can manually open the window with: "
                f"tmux new-window -n {name} -c {worktree_path}"
            )
        else:
            partial_state_msg = (
                f"Worktree was created at '{worktree_path}' but no tmux window was opened. "
                f"You can manually open the window with: "
                f"tmux new-window -n {name} -c {worktree_path}"
            )
        emit_error(
            f"tmux new-window failed: {result.stderr.strip()}. {partial_state_msg}",
            fmt,
            error_code="TMUX_WINDOW_FAILED",
            exit_code=1,
        )

    # --- 10b. Apply emoji icon to the new window ---
    # Karl's manual flow assigns a random emoji icon to every new tmux window via
    # an after-new-window hook that calls `random-emoji`. That hook sets the
    # @theme_plugin_inactive_window_icon and @theme_plugin_active_window_icon window
    # options used by the Tokyo Night theme to display an emoji before the window
    # name in the status bar (e.g. "🦊 audit").
    #
    # When `tmux new-window -d` creates a detached window, the hook fires but
    # targets the CALLER's current window (not the new one) because focus never
    # switches. The icon therefore lands on the wrong window, leaving crew-created
    # windows without an emoji.
    #
    # Fix: explicitly invoke `random-emoji` via `tmux run-shell -t <name>.0` after
    # the window is created. Running it in the new window's pane context ensures
    # `tmux set-window-option` inside `random-emoji` targets the correct window.
    #
    # The window NAME itself is unchanged by `random-emoji` — it only sets window
    # options used by the theme. Bare-name resolution in `get_window_lookup` (which
    # matches on `#{window_name}`) therefore continues to work without modification.
    _tmux_fire_and_forget(
        ["tmux", "run-shell", "-t", f"{name}.0", "random-emoji"],
        context="random-emoji icon assignment",
    )

    # --- 11. Start staff (or --cmd override) in the new window ---
    # Default command is `staff --model sonnet --name <name>` (spawns a staff
    # engineer session pinned to Sonnet — prevents accidental Opus burns on
    # crew-spawned sessions). The `--cmd` flag overrides the default entirely;
    # callers that need plain `claude` or a different model can pass `--cmd claude`.
    #
    # Both `staff` and `claude` support -n/--name for display name — this sets the
    # session display name shown in the prompt box, /resume picker, and terminal
    # title. name is pre-validated by _SAFE_NAME_RE (alphanumeric/hyphens/underscores
    # only) — no shell quoting needed.
    #
    # Clean any stale sentinel unconditionally before spawning. A leftover sentinel
    # from a crashed or dismissed prior session would cause _wait_for_sentinel to
    # return immediately (false-ready) for any future --tell caller. Defense-in-depth:
    # even callers not currently using --tell benefit from a clean slate.
    _clean_stale_sentinel(name)
    base_cmd = cmd_override if cmd_override is not None else "staff"
    if cmd_override is None:
        spawn_cmd = f"staff --model sonnet --name {name}"
    else:
        spawn_cmd = f"{cmd_override} --name {name}"
    _tmux_fire_and_forget(
        ["tmux", "send-keys", "-t", name, spawn_cmd, "Enter"],
        context="staff session startup",
    )

    # --- 12. Deliver initial message (--tell) ---
    # Wait for the readiness sentinel dropped by the SessionStart lifecycle hook
    # (crew-lifecycle-hook.py) before delivering the brief. The sentinel's
    # existence is a ground-truth signal that Claude Code has fully initialised
    # and is ready for input — deterministic regardless of how long nix flake
    # evaluation or direnv bootstrap takes.
    told = False
    told_reason: Optional[str] = None

    if tell is not None:
        ready, wait_reason = _wait_for_sentinel(name)
        if not ready:
            # Sentinel never appeared within the outer ceiling (5 minutes).
            # wait_reason already contains the appropriate diagnostic string.
            told_reason = wait_reason
        else:
            told, told_reason = _deliver_tell(name, tell)
            if not told:
                print(
                    f"warning: --tell delivery failed: {told_reason}",
                    file=sys.stderr,
                )

    # --- 13. Emit structured result ---
    if fmt == "xml":
        attrs: Dict[str, str] = dict(
            window=name,
            pane="0",
            worktree=worktree_path,
            repo=repo,
            session_name=name,
            command=base_cmd,
        )
        if no_worktree:
            attrs["no_worktree"] = "true"
        else:
            attrs["branch"] = branch  # type: ignore[assignment]
        # told field now reflects VERIFIED delivery, not just attempt
        if tell is not None:
            attrs["told"] = "true" if told else "false"
            if not told and told_reason:
                attrs["told_reason"] = told_reason
        elem = ET.Element("created", **attrs)
        print(xml_to_string(elem))
    elif fmt == "json":
        obj: Dict = {
            "window": name,
            "pane": "0",
            "worktree": worktree_path,
            "repo": repo,
            "session_name": name,
            "command": base_cmd,
        }
        if no_worktree:
            obj["no_worktree"] = True
        else:
            obj["branch"] = branch
        if tell is not None:
            obj["told"] = told
            if not told and told_reason:
                obj["told_reason"] = told_reason
        print(json.dumps(obj, indent=2))
    else:
        if no_worktree:
            print(f"created: window={name} pane=0 worktree={worktree_path} no_worktree=true")
        else:
            print(f"created: window={name} pane=0 worktree={worktree_path} branch={branch}")
        print(f"  {base_cmd} started with --name {name}")
        if tell is not None and told:
            print(f"  initial message delivered: {tell!r}")
        elif tell is not None and not told:
            print(f"  initial message delivery failed: {told_reason}")
        print(f"  switch to window: tmux select-window -t {name}")

    # --- 14. Auto-delete --tell-file on successful tell delivery ---
    if tell_file_path is not None and told:
        os.unlink(tell_file_path)


# ---------------------------------------------------------------------------
# Subcommand: smithers
# ---------------------------------------------------------------------------

# Split percentage for `crew smithers` horizontal (top/bottom) splits.
#
# This value matches the tmux keybinding for prefix+s in modules/tmux/default.nix:
#   bind-key -N "Split vertically (25% bottom)" s split-window -v -c "#{pane_current_path}" -l "25%"
#
# The keybinding creates a new bottom pane that is 25% of the total window height.
# `crew smithers` uses the same percentage so the layout is consistent with the
# user's existing muscle-memory keybinding for vertical splits.
_SMITHERS_SPLIT_PERCENT = 25


def _list_panes_in_window(session_idx: str) -> List[Tuple[str, str, str]]:
    """Return panes in the given window as list of (pane_index, pane_current_command, pane_current_path).

    session_idx is in 'session:window_index' format (e.g. 'free-brook:0').
    """
    result = subprocess.run(
        [
            "tmux", "list-panes",
            "-t", session_idx,
            "-F", "#{pane_index}|#{pane_current_command}|#{pane_current_path}",
        ],
        capture_output=True, text=True, check=False,
    )
    panes = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            panes.append(tuple(parts))  # type: ignore[arg-type]
    return panes  # type: ignore[return-value]


def _pane_is_running_smithers(pane: Tuple[str, str, str]) -> bool:
    """Return True if the pane appears to be running smithers.

    Checks pane_current_command against 'smithers' (exact match).
    smithers is a named Python wrapper installed by Nix, so pane_current_command
    reports 'smithers' (not 'python3' or a version string). This is the simplest
    and most reliable check — no scrollback scraping needed.

    Subshell detection gap: when smithers spawns a child process (gh, python3,
    etc.) that becomes the pane's foreground command, tmux reports the child as
    pane_current_command and this function returns False. The failure mode is
    SAFE — cmd_smithers returns AMBIGUOUS_PANE_STATE (rc=1) rather than
    silently overwriting the pane. Workaround: wait for smithers to return to
    idle, then re-invoke; or kill the pane and re-invoke from scratch.
    """
    _idx, pane_current_command, _path = pane
    return pane_current_command == "smithers"


def _split_window_horizontal(session_idx: str, percent: int, cwd: str) -> Optional[str]:
    """Create a horizontal (top/bottom) split below the current pane in the given window.

    Uses `split-window -v` which creates a new pane BELOW the existing one.
    `-l <percent>%` sets the new pane size as a percentage of the total window height.
    `-c <cwd>` sets the new pane's working directory.

    Returns the new pane index as a string, or None on failure.
    """
    result = subprocess.run(
        [
            "tmux", "split-window",
            "-v",
            "-t", session_idx,
            "-l", f"{percent}%",
            "-c", cwd,
            "-P",        # print new pane index to stdout
            "-F", "#{pane_index}",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    pane_index = result.stdout.strip()
    return pane_index if pane_index else None


def _send_command_to_pane(pane_target: str, cmd: str) -> bool:
    """Send a command string followed by Enter to the given pane target.

    pane_target is in 'session:window_index.pane_index' format.
    Returns True on success, False on failure.

    Note: cmd must not contain shell-special characters that would confuse
    tmux send-keys. 'smithers' (no args) is safe as-is.
    """
    result = subprocess.run(
        ["tmux", "send-keys", "-t", pane_target, cmd, "Enter"],
        capture_output=True, check=False,
    )
    return result.returncode == 0


def cmd_smithers(name: str, fmt: str) -> int:
    """Create a horizontal split in the target window and run smithers in the new pane.

    Idempotency contract:
      - No split exists → create 25% bottom split (matching prefix+s keybinding),
        set cwd to pane 0's cwd (the worktree), run 'smithers' in the new pane.
      - Split exists AND running smithers → report already-running, return 0 (success).
      - Split exists but NOT running smithers → error with clear surface (ambiguous state;
        refuse to overwrite so the user can decide).
      - Window not found → error.

    'smithers' auto-detects the PR from the worktree's current branch — no args needed.
    """
    lookup = get_window_lookup()
    entry = lookup.get(name)
    if entry is None:
        available = sorted(lookup.keys())
        msg = f"tmux window '{name}' not found"
        if available:
            msg += f". Available windows: {', '.join(available)}"
        if fmt == "xml":
            elem = ET.Element("error", message=msg, error_code="WINDOW_NOT_FOUND")
            print(xml_to_string(elem))
        elif fmt == "json":
            print(json.dumps({"error": msg, "error_code": "WINDOW_NOT_FOUND"}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    session_idx, _window_id = entry  # session_idx is 'session:window_index'

    panes = _list_panes_in_window(session_idx)

    if len(panes) > 1:
        # A split already exists. Check whether smithers is running in any of the extra panes.
        smithers_pane = next((p for p in panes if _pane_is_running_smithers(p)), None)
        if smithers_pane is not None:
            pane_index, _cmd, _path = smithers_pane
            msg = f"smithers already running in pane {name}.{pane_index}"
            if fmt == "xml":
                elem = ET.Element(
                    "smithers",
                    status="already-running",
                    window=name,
                    pane=str(pane_index),
                    message=msg,
                )
                print(xml_to_string(elem))
            elif fmt == "json":
                print(json.dumps({
                    "status": "already-running",
                    "window": name,
                    "pane": pane_index,
                    "message": msg,
                }))
            else:
                print(msg)
            return 0

        # Extra pane(s) exist but none are running smithers — ambiguous state.
        extra_pane_info = ", ".join(
            f"pane {p[0]} ({p[1]})" for p in panes if p[0] != "0"
        )
        msg = (
            f"window '{name}' has extra pane(s) but none running smithers "
            f"({extra_pane_info}) — refusing to overwrite"
        )
        if fmt == "xml":
            elem = ET.Element(
                "error",
                message=msg,
                error_code="AMBIGUOUS_PANE_STATE",
                window=name,
            )
            print(xml_to_string(elem))
        elif fmt == "json":
            print(json.dumps({"error": msg, "error_code": "AMBIGUOUS_PANE_STATE", "window": name}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    # No split yet — pane 0 is the only pane. Get its cwd for the new pane.
    pane_0_cwd = panes[0][2] if panes else ""
    if not pane_0_cwd:
        # Fallback: query pane 0 cwd via display-message if list-panes path was empty.
        result = subprocess.run(
            ["tmux", "display-message", "-t", f"{session_idx}.0", "-p", "#{pane_current_path}"],
            capture_output=True, text=True, check=False,
        )
        pane_0_cwd = result.stdout.strip()

    new_pane_index = _split_window_horizontal(session_idx, _SMITHERS_SPLIT_PERCENT, pane_0_cwd)
    if new_pane_index is None:
        msg = f"tmux split-window failed for window '{name}'"
        if fmt == "xml":
            elem = ET.Element("error", message=msg, error_code="SPLIT_FAILED", window=name)
            print(xml_to_string(elem))
        elif fmt == "json":
            print(json.dumps({"error": msg, "error_code": "SPLIT_FAILED", "window": name}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    pane_target = f"{session_idx}.{new_pane_index}"
    ok = _send_command_to_pane(pane_target, "smithers")
    if not ok:
        msg = f"send-keys to pane {pane_target} failed"
        if fmt == "xml":
            elem = ET.Element("error", message=msg, error_code="SEND_KEYS_FAILED", window=name)
            print(xml_to_string(elem))
        elif fmt == "json":
            print(json.dumps({"error": msg, "error_code": "SEND_KEYS_FAILED", "window": name}))
        else:
            print(f"Error: {msg}", file=sys.stderr)
        return 1

    msg = f"started smithers in pane {name}.{new_pane_index}"
    if fmt == "xml":
        elem = ET.Element(
            "smithers",
            status="started",
            window=name,
            pane=str(new_pane_index),
            message=msg,
        )
        print(xml_to_string(elem))
    elif fmt == "json":
        print(json.dumps({
            "status": "started",
            "window": name,
            "pane": new_pane_index,
            "message": msg,
        }))
    else:
        print(msg)
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def non_negative_int(value: str) -> int:
    """Argparse type validator that accepts only non-negative integers."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid integer")
    if n < 0:
        raise argparse.ArgumentTypeError(
            f"--from value must be >= 0, got {n}"
        )
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crew",
        description="Unified tmux window/pane interaction CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # NOTE: This CLI uses --format (not --output-style). The kanban CLI uses
    # --output-style=xml for historical reasons; these Python CLIs standardize
    # on --format. Coordinators must use the correct flag per tool.
    parser.add_argument(
        "--format", "-f",
        choices=["xml", "json", "human"],
        default="xml",
        help="Output format: xml (default), json, or human. Note: kanban uses --output-style, not --format."
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser(
        "list",
        help="Enumerate tmux windows and panes in the current session (Claude panes only by default)",
        description=(
            "List tmux windows and panes confined to the CURRENT tmux session.\n\n"
            "Output format: defaults to XML (--format xml). No flag is required for\n"
            "structured AI-coordinator output — XML is the default. Example:\n"
            "  crew list              # XML output for current session\n"
            "  crew list --format human   # human-readable\n"
            "  crew list --all        # include non-Claude panes\n\n"
            "Note: crew list never returns windows from other tmux sessions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_list.add_argument(
        "--all", "-a",
        action="store_true",
        dest="show_all",
        default=False,
        help="Include all panes regardless of running command (default: Claude panes only)"
    )

    # tell
    p_tell = sub.add_parser(
        "tell",
        help="Send message + Enter to target pane(s)",
        description=(
            "Send input to one or more target pane(s).\n\n"
            "Pane 0 is the default — omit the pane suffix for normal use:\n"
            "  crew tell platform-bootstrap \"Your initial brief here.\"\n"
            "Use the dot-suffix only for exceptional multi-pane windows:\n"
            "  crew tell platform-bootstrap.1 \"message to pane 1\"\n\n"
            "Default (no --keys): message is sent as literal text followed by Enter.\n"
            "With --keys: message is interpreted as space-separated tmux key tokens\n"
            "passed directly to tmux send-keys (no Enter appended automatically).\n\n"
            "Key token examples:\n"
            "  crew tell pricing --keys \"Enter\"            # bare Enter to pane 0\n"
            "  crew tell pricing.0 --keys \"Down Down Enter\"  # arrow-nav then confirm\n"
            "  crew tell pricing.0 --keys \"Escape\"           # cancel a dialog\n"
            "  crew tell pricing.0 --keys \"C-c\"              # interrupt (Ctrl-C)\n"
            "  crew tell pricing.0 --keys \"Tab Space\"        # tab then space\n\n"
            "Supported token conventions: Enter, Return, Escape, Tab, Space, BSpace,\n"
            "Up, Down, Left, Right, PageUp, PageDown, Home, End, F1-F12,\n"
            "C-<letter> (Ctrl), M-<letter> (Meta/Alt). Tokens are passed through to\n"
            "tmux directly — tmux will error on unrecognized names."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_tell.add_argument("targets", help="Comma-separated targets (window[.pane]); pane defaults to 0")
    tell_msg_group = p_tell.add_mutually_exclusive_group()
    tell_msg_group.add_argument(
        "message",
        nargs="?",
        default=None,
        help=(
            "Message to send (text) or space-separated key tokens (with --keys). "
            "Required unless --tell-file is given."
        ),
    )
    tell_msg_group.add_argument(
        "--tell-file",
        default=None,
        dest="tell_file",
        metavar="PATH",
        help=(
            "Alternative to the positional message — read tell body from PATH (UTF-8). "
            "File is auto-deleted after all targets receive successfully (mirrors `kanban do --file`). "
            "Mutually exclusive with the positional message argument."
        ),
    )
    p_tell.add_argument(
        "--keys",
        action="store_true",
        default=False,
        dest="use_keys",
        help=(
            "Interpret message as space-separated tmux key tokens instead of literal text. "
            "Tokens are passed directly to tmux send-keys without the -l literal flag and "
            "without an automatic Enter. Example: --keys \"Down Down Enter\""
        ),
    )

    # read
    p_read = sub.add_parser("read", help="Capture pane buffer content")
    p_read.add_argument("targets", help="Comma-separated targets (window[.pane])")
    p_read.add_argument(
        "--lines", "-n",
        type=int,
        default=None,
        help="Number of lines to return (default: full buffer or all lines from --from offset)"
    )
    p_read.add_argument(
        "--from",
        dest="from_line",
        type=non_negative_int,
        default=None,
        metavar="N",
        help=(
            "0-based line offset into the full pane buffer (default: omitted — "
            "uses legacy tail-last-N behavior). When set, enables paginated mode: "
            "returns lines [N .. N+--lines-1] with a position metadata header "
            "('lines X-Y of Z') per target."
        )
    )

    # dismiss
    p_dismiss = sub.add_parser("dismiss", help="Kill target pane(s) or window(s)")
    p_dismiss.add_argument("targets", help="Comma-separated targets (window[.pane])")

    # find
    p_find = sub.add_parser("find", help="Search pane content for pattern")
    p_find.add_argument("pattern", help="Regex pattern to search for")
    p_find.add_argument(
        "targets",
        nargs="?",
        default=None,
        help="Comma-separated targets (default: all panes)"
    )
    p_find.add_argument(
        "--lines", "-n",
        type=int,
        default=None,
        help="Limit search scope to last N lines per pane"
    )

    # create
    p_create = sub.add_parser(
        "create",
        description=(
            "End-to-end staff session creation: create a git worktree, open a tmux "
            "window, and start a staff engineer session in that window — all in one command.\n\n"
            "Default spawn command: `staff --model sonnet --name <name>` (staff engineer session).\n"
            "Override with --cmd if you need a different process (e.g. --cmd claude).\n\n"
            "Optionally deliver an initial brief in the same call with --tell:\n"
            "  crew create platform-bootstrap --tell \"Build the auth service...\"\n"
            "This replaces the two-step `crew create foo; crew tell foo \"...\"`.\n\n"
            "Pane targeting: all windows start with a single pane (index 0). Use\n"
            "`crew tell <window> <msg>` to reach it — the .0 suffix is optional."
        ),
        help="Create worktree + tmux window + staff session (end-to-end)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_create.add_argument("name", help="Session name: used for the tmux window, worktree directory, and branch name")
    p_create.add_argument(
        "--repo",
        default=None,
        help="Path to the git repository (default: current git repo via git rev-parse --show-toplevel)",
    )
    p_create.add_argument(
        "--branch",
        default=None,
        help="Branch name to checkout in the worktree (default: <name>)",
    )
    p_create.add_argument(
        "--base",
        default=None,
        help="Base branch to create the new branch from (default: current branch of the repo)",
    )
    p_create.add_argument(
        "--cmd",
        default=None,
        dest="cmd_override",
        help=(
            "Command to spawn in the new window. "
            "When omitted, the default is 'staff --model sonnet --name <name>'. "
            "When provided, the command is invoked as '<cmd> --name <name>' — "
            "--model sonnet is NOT injected (caller controls the model). "
            "Example: --cmd claude  (spawn plain Claude instead of staff engineer)"
        ),
    )
    create_tell_group = p_create.add_mutually_exclusive_group()
    create_tell_group.add_argument(
        "--tell",
        default=None,
        dest="tell",
        metavar="MESSAGE",
        help=(
            "Initial message to send once the session is ready. Waits for a prompt-ready "
            "signal then delivers the message automatically. Replaces the two-call pattern "
            "`crew create foo && crew tell foo '...'`. Mutually exclusive with --tell-file."
        ),
    )
    create_tell_group.add_argument(
        "--tell-file",
        default=None,
        dest="tell_file",
        metavar="PATH",
        help=(
            "Alternative to --tell — read the initial message from PATH (UTF-8). "
            "File is auto-deleted on successful delivery (mirrors `kanban do --file`). "
            "Mutually exclusive with --tell."
        ),
    )
    p_create.add_argument(
        "--no-worktree",
        action="store_true",
        default=False,
        dest="no_worktree",
        help=(
            "Start the staff session directly in the --repo directory WITHOUT creating "
            "a new git worktree. Use this for 'work directly on main' or existing-branch "
            "workflows. Incompatible with --branch and --base."
        ),
    )
    p_create.add_argument(
        "--mcp-trust",
        default="all",
        dest="mcp_trust",
        choices=["all", "this", "none"],
        help=(
            "How to answer the MCP server trust modal when it appears during startup. "
            "'all' (default) — trust this and all future MCP servers in this project. "
            "'this' — trust only this MCP server. "
            "'none' — continue without using this MCP server. "
            "Only applies to MCP trust modals; workspace-trust is always auto-accepted."
        ),
    )

    # status
    p_status = sub.add_parser(
        "status",
        help="Composite: list windows then read N lines from every pane (Claude panes only by default)"
    )
    p_status.add_argument(
        "--lines", "-n",
        type=int,
        default=100,
        help="Lines to read per pane (default: 100)"
    )
    p_status.add_argument(
        "--all", "-a",
        action="store_true",
        dest="show_all",
        default=False,
        help="Include all panes regardless of running command (default: Claude panes only)"
    )

    # project-path
    p_project_path = sub.add_parser(
        "project-path",
        help="Show the Claude Code project directory key for a worktree path",
        description=(
            "Resolve a worktree path to its Claude Code project directory key.\n\n"
            "Claude Code stores session files under ~/.claude/projects/<key>/. This\n"
            "command shows the key for a given worktree and lists any .jsonl session\n"
            "files found there.\n\n"
            "Examples:\n"
            "  crew project-path .                                 # current directory\n"
            "  crew project-path ~/worktrees/myorg/my-repo         # explicit path\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_project_path.add_argument(
        "worktree",
        help="Path to the worktree directory (use '.' for current working directory)",
    )

    # resume
    p_resume = sub.add_parser(
        "resume",
        help="Recreate a tmux window and resume an existing Claude session",
        description=(
            "Resume a previously created crew session by recreating the tmux window\n"
            "and launching `staff --name <name> --resume <session_id>`.\n\n"
            "The worktree path is resolved from active tmux windows or ~/worktrees/<org>/<repo>/<name>.\n"
            "If --session is omitted, the most recent session file (by mtime) is used.\n\n"
            "Examples:\n"
            "  crew resume mirrordx                    # infer most recent session\n"
            "  crew resume mirrordx --session <uuid>   # use explicit session ID\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_resume.add_argument(
        "name",
        help="Window name (must match a worktree under ~/worktrees/ or an active tmux window)",
    )
    p_resume.add_argument(
        "--session",
        default=None,
        metavar="ID",
        help=(
            "Session UUID to resume (default: most recent .jsonl by mtime). "
            "Use `crew sessions --window <name>` to list available session IDs."
        ),
    )

    # sessions
    p_sessions = sub.add_parser(
        "sessions",
        help="List Claude session IDs for tmux windows in the current session",
        description=(
            "Enumerate Claude Code session files for active tmux windows.\n\n"
            "For each window, resolves the pane's working directory to a Claude\n"
            "project key and lists .jsonl session files sorted by most-recent first.\n\n"
            "Examples:\n"
            "  crew sessions                         # all windows in current session\n"
            "  crew sessions --window mirrordx        # sessions for a specific window\n"
            "  crew sessions --worktree ~/worktrees/foo  # sessions for an explicit path\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sessions.add_argument(
        "--window",
        default=None,
        metavar="NAME",
        help="Restrict to sessions for this tmux window name",
    )
    p_sessions.add_argument(
        "--worktree",
        default=None,
        metavar="PATH",
        help="Use an explicit worktree path instead of tmux window lookup",
    )

    # smithers
    p_smithers = sub.add_parser(
        "smithers",
        help="Create a horizontal split in a crew member's window and run smithers in the new pane",
        description=(
            "Drop a smithers pane into the target crew member's tmux window.\n\n"
            "Creates a horizontal split (25% bottom — matches prefix+s keybinding) below\n"
            "pane 0 and runs `smithers` in the new pane. smithers auto-detects the PR\n"
            "from the worktree's current branch — no arguments needed.\n\n"
            "Idempotency:\n"
            "  - No split exists → create split and start smithers.\n"
            "  - Split exists AND smithers is running → report already-running (success).\n"
            "  - Split exists but NOT running smithers → error (ambiguous state).\n\n"
            "IMPORTANT: This subcommand is sstaff-only. Staff engineers do NOT invoke\n"
            "`crew smithers` — sstaff uses it after a staff session creates a draft PR.\n\n"
            "Examples:\n"
            "  crew smithers pricing          # start smithers in pricing window\n"
            "  crew smithers auth             # start smithers in auth window\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_smithers.add_argument(
        "name",
        help="Crew member window name (the tmux window where smithers should be launched)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    fmt = args.format

    try:
        if args.command == "list":
            cmd_list(fmt, show_all=args.show_all)
        elif args.command == "tell":
            # Legacy-order detection (best-effort): if the first positional arg
            # (now expected to be targets) looks like a human-readable message
            # rather than a target spec, emit a clear usage error so callers
            # using the old <message> <targets> order get an actionable hint
            # rather than a confusing "window not found" error.
            if _looks_like_message_not_target(args.targets):
                emit_error(
                    "`crew tell` argument order changed. "
                    "Use `crew tell <targets> <message>` (targets first, message last). "
                    "You passed what looks like a message as the first argument.",
                    fmt,
                    error_code="LEGACY_ARG_ORDER",
                    exit_code=2,
                )
            # At least one source of message content must be provided.
            # (argparse mutually_exclusive_group handles the both-given case.)
            if args.message is None and args.tell_file is None:
                emit_error(
                    "crew tell: a message is required — provide a positional message or --tell-file PATH.",
                    fmt,
                    error_code="MISSING_MESSAGE",
                    exit_code=2,
                )
            cmd_tell(
                args.targets,
                args.message,
                fmt,
                use_keys=args.use_keys,
                tell_file=args.tell_file,
            )
        elif args.command == "read":
            cmd_read(args.targets, args.lines, args.from_line, fmt)
        elif args.command == "dismiss":
            cmd_dismiss(args.targets, fmt)
        elif args.command == "find":
            cmd_find(args.pattern, args.targets, args.lines, fmt)
        elif args.command == "status":
            cmd_status(args.lines, fmt, show_all=args.show_all)
        elif args.command == "create":
            cmd_create(args.name, args.repo, args.branch, args.base, fmt,
                       cmd_override=args.cmd_override, tell=args.tell,
                       no_worktree=args.no_worktree, tell_file=args.tell_file,
                       mcp_trust=args.mcp_trust)
        elif args.command == "project-path":
            send = _ProjectPathSend(fmt)
            cmd_project_path(args.worktree, fmt, send)
        elif args.command == "resume":
            send = _ResumeSend(fmt)
            cmd_resume(args.name, args.session, fmt, send)
        elif args.command == "sessions":
            send = _SessionsSend(fmt)
            cmd_sessions(fmt, send, window_filter=args.window, worktree_filter=args.worktree)
            send.flush()
        elif args.command == "smithers":
            rc = cmd_smithers(args.name, fmt)
            sys.exit(rc)
        else:
            emit_error(f"unknown subcommand: {args.command}", fmt, error_code="UNKNOWN_SUBCOMMAND", exit_code=2)
    except KeyboardInterrupt:
        emit_error("interrupted", fmt, error_code="INTERRUPTED", exit_code=130)


if __name__ == "__main__":
    main()
