#!/usr/bin/env python3
"""
crew: Unified tmux window/pane interaction CLI

Subcommands:
  list                     Enumerate tmux windows and panes (Claude panes only by default)
  tell <targets> <msg>     Send message + Enter to each target pane (targets first)
  read <targets>           Capture pane buffer content
  find <pattern> [targets] Search pane content for pattern
  status                   Composite: list + read N lines from every pane (Claude panes only by default)

Target format: <window>[.<pane>]  — pane defaults to 0
  comma-separated for multi-target: mild-forge,bold-sparrow.1

Output format: --format xml (default), --format json, or --format human

Claude-only filter (list, status):
  By default, list and status filter to panes running Claude. Claude Code installs
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
from typing import Dict, List, Optional, Tuple


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
# hyphens, dots, digits, commas — no spaces and no multi-word sentences.
# The heuristic fires when the first arg:
#   - contains two or more spaces (multi-word phrase), OR
#   - contains non-ASCII characters (emoji, Unicode punctuation), OR
#   - ends with common sentence-ending punctuation (. ? !)
#
# For ambiguous single-word or punctuation-free messages the heuristic stays
# silent and the new behavior (targets-first) is used — the user corrects if needed.
_LEGACY_ORDER_RE = re.compile(
    r"  "               # two or more spaces → multi-word phrase
    r"|[^\x00-\x7F]"   # non-ASCII (Unicode punctuation, emoji)
    r"|[.?!]$"         # ends with sentence-ending punctuation
)


def _looks_like_message_not_target(s: str) -> bool:
    """Return True if s looks like a human-readable message rather than a target spec."""
    return bool(_LEGACY_ORDER_RE.search(s))


def cmd_tell(targets_str: str, message: str, fmt: str, use_keys: bool = False) -> None:
    resolved = resolve_targets(targets_str, fmt=fmt)

    if fmt == "xml":
        root = ET.Element("tell")
    elif fmt == "json":
        json_targets: List[Dict] = []

    for tmux_target, label, _window_id in resolved:
        if use_keys:
            # Keys mode: split message into tmux key tokens and pass directly.
            # No -l flag — tokens are interpreted as tmux key names (Enter, Escape, C-c, etc.).
            tokens = message.split()
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_target] + tokens,
                check=False
            )
        else:
            # Text mode: send message as literal text, then Enter as a separate key.
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_target, message],
                check=False
            )
            time.sleep(0.15)
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_target, "Enter"],
                check=False
            )
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
        else:
            # bare window: kill via stable @id — immune to window index renumbering
            subprocess.run(["tmux", "kill-window", "-t", window_id], check=False)
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

def cmd_find(pattern: str, targets_str: Optional[str], lines: Optional[int], fmt: str) -> None:
    if targets_str:
        resolved = resolve_targets(targets_str, fmt=fmt)
    else:
        # Confine to the current tmux session only (M-01 fix: mirrors cmd_list/cmd_status).
        current_session = get_current_session()
        panes = get_all_panes(session=current_session)
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

def cmd_status(lines: int, fmt: str, show_all: bool = False) -> None:
    # Confine to the current tmux session only (P6.1).
    current_session = get_current_session()
    all_panes = get_all_panes(session=current_session)
    # By default, filter to Claude panes only. Pass show_all=True to include everything.
    panes = all_panes if show_all else [
        p for p in all_panes if is_claude_pane(p[4])
    ]

    if fmt == "xml":
        root = ET.Element("status", lines=str(lines))
        for session, window_index, window_name, pane_index, _pane_cmd in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            member = ET.SubElement(root, "member", crew=label)
            member.text = content
        print(xml_to_string(root))
    elif fmt == "json":
        members = []
        for session, window_index, window_name, pane_index, _pane_cmd in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            members.append({"crew": label, "content": content})
        print(json.dumps({"lines": lines, "members": members}, indent=2))
    else:
        # human: list first, then content per pane
        current_window_key = None
        for session, window_index, window_name, pane_index, pane_cmd in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                print(f"window: {window_name}")
                current_window_key = wkey
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


def _tmux_window_exists(name: str) -> bool:
    """Return True if a tmux window named exactly `name` exists in any session."""
    result = subprocess.run(
        ["tmux", "list-windows", "-a", "-F", "#{window_name}"],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return False
    return name in result.stdout.splitlines()


def _wait_for_prompt_ready(window_name: str, timeout: float = 30.0, poll_interval: float = 0.5) -> bool:
    """Poll the target window's pane 0 until it looks like Claude is ready for input.

    Looks for a prompt indicator: the '>' character that Claude Code shows when
    waiting for input, or the word 'claude' in the recent output.  Returns True
    when a ready signal is detected; returns False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", f"{window_name}.0", "-S", "-20"],
            capture_output=True, text=True, check=False
        )
        content = result.stdout
        # Claude Code prompt indicators: the '>' prompt char, or the assistant
        # turn marker (◆ or similar) that appears when Claude is ready.
        if content and (
            content.rstrip().endswith(">")
            or "> " in content
            or "claude" in content.lower()
            or "◆" in content
            or "✓" in content
        ):
            return True
        time.sleep(poll_interval)
    return False


def cmd_create(
    name: str,
    repo: Optional[str],
    branch: Optional[str],
    base: Optional[str],
    fmt: str,
    cmd_override: Optional[str] = None,
    tell: Optional[str] = None,
) -> None:
    """Create a git worktree, tmux window, and staff session end-to-end.

    Steps:
    1. Validate name (non-empty, filesystem-safe).
    2. Check for existing tmux window named <name>.
    3. Resolve repo (default: current git root).
    4. Resolve branch (default: <name>).
    5. Resolve base branch (default: current branch of repo).
    6. Expand worktree path to ~/worktrees/<name>.
    7. Check for existing worktree at that path.
    8. Create branch if it doesn't exist.
    9. Create git worktree.
    10. Create tmux window.
    11. Start staff (or --cmd override) in the new window (with --name <name> for display).
    12. If --tell was given: wait for prompt-ready, then deliver the initial message.
    13. Emit structured result.
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

    # --- 6. Expand worktree path ---
    worktree_path = os.path.expanduser(f"~/worktrees/{name}")

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
            ["git", "branch", branch, base],
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

    # --- 10. Create tmux window ---
    result = subprocess.run(
        ["tmux", "new-window", "-n", name, "-c", worktree_path, "-d"],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        # Worktree exists but window creation failed — report partial state, do NOT
        # auto-remove the worktree (user may have other uses for it).
        emit_error(
            f"tmux new-window failed: {result.stderr.strip()}. "
            f"Worktree was created at '{worktree_path}' but no tmux window was opened. "
            "You can manually open the window with: "
            f"tmux new-window -n {name} -c {worktree_path}",
            fmt,
            error_code="TMUX_WINDOW_FAILED",
            exit_code=1,
        )

    # --- 11. Start staff (or --cmd override) in the new window ---
    # Default command is `staff --name <name>` (spawns a staff engineer session).
    # The `--cmd` flag overrides the default; callers that need plain `claude` can
    # pass `--cmd claude`.
    #
    # Both `staff` and `claude` support -n/--name for display name — this sets the
    # session display name shown in the prompt box, /resume picker, and terminal
    # title. name is pre-validated by _SAFE_NAME_RE (alphanumeric/hyphens/underscores
    # only) — no shell quoting needed.
    base_cmd = cmd_override if cmd_override is not None else "staff"
    spawn_cmd = f"{base_cmd} --name {name}"
    subprocess.run(
        ["tmux", "send-keys", "-t", name, spawn_cmd, "Enter"],
        capture_output=True, check=False
    )

    # --- 12. Deliver initial message (--tell) ---
    # If --tell was provided, wait for the spawned process to reach a prompt-ready
    # state, then send the message.  Failure to detect prompt-ready within the
    # timeout is non-fatal — we still deliver the message on a best-effort basis
    # (the pane may have started but the prompt indicator may not have been seen).
    if tell is not None:
        _wait_for_prompt_ready(name)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{name}.0", tell],
            check=False
        )
        time.sleep(0.15)
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{name}.0", "Enter"],
            check=False
        )

    # --- 13. Emit structured result ---
    told = tell is not None
    if fmt == "xml":
        attrs: Dict[str, str] = dict(
            window=name,
            pane="0",
            worktree=worktree_path,
            branch=branch,
            repo=repo,
            session_name=name,
            command=base_cmd,
        )
        if told:
            attrs["told"] = "true"
        elem = ET.Element("created", **attrs)
        print(xml_to_string(elem))
    elif fmt == "json":
        obj: Dict = {
            "window": name,
            "pane": "0",
            "worktree": worktree_path,
            "branch": branch,
            "repo": repo,
            "session_name": name,
            "command": base_cmd,
        }
        if told:
            obj["told"] = True
        print(json.dumps(obj, indent=2))
    else:
        print(f"created: window={name} pane=0 worktree={worktree_path} branch={branch}")
        print(f"  {base_cmd} started with --name {name}")
        if told:
            print(f"  initial message delivered: {tell!r}")
        print(f"  switch to window: tmux select-window -t {name}")


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
    p_tell.add_argument("message", help="Message to send (text) or space-separated key tokens (with --keys)")
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
            "Default spawn command: `staff --name <name>` (staff engineer session).\n"
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
            "Command to spawn in the new window (default: 'staff'). "
            "The command is invoked as '<cmd> --name <name>'. "
            "Example: --cmd claude  (spawn plain Claude instead of staff engineer)"
        ),
    )
    p_create.add_argument(
        "--tell",
        default=None,
        dest="tell",
        metavar="MESSAGE",
        help=(
            "Initial message to send once the session is ready. Waits for a prompt-ready "
            "signal then delivers the message automatically. Replaces the two-call pattern "
            "`crew create foo && crew tell foo '...'`."
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
            cmd_tell(args.targets, args.message, fmt, use_keys=args.use_keys)
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
                       cmd_override=args.cmd_override, tell=args.tell)
        else:
            emit_error(f"unknown subcommand: {args.command}", fmt, error_code="UNKNOWN_SUBCOMMAND", exit_code=2)
    except KeyboardInterrupt:
        emit_error("interrupted", fmt, error_code="INTERRUPTED", exit_code=130)


if __name__ == "__main__":
    main()
