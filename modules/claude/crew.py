#!/usr/bin/env python3
"""
crew: Unified tmux window/pane interaction CLI

Subcommands:
  list                     Enumerate tmux windows and panes
  tell <msg> <targets>     Send message + Enter to each target pane
  read <targets>           Capture pane buffer content
  find <pattern> [targets] Search pane content for pattern
  status                   Composite: list + read N lines from every pane

Target format: <window>[.<pane>]  — pane defaults to 0
  comma-separated for multi-target: mild-forge,bold-sparrow.1

Output format: --format xml (default) or --format human
"""

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# tmux helpers
# ---------------------------------------------------------------------------

def get_window_lookup() -> Dict[str, str]:
    """Return dict mapping window_name -> session:window_index (first-match)."""
    result = subprocess.run(
        ["tmux", "list-windows", "-a", "-F", "#{session_name}:#{window_index}: #{window_name}"],
        capture_output=True, text=True, check=False
    )
    lookup: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        # format: session:index: name (flags)
        session_idx, _, rest = line.partition(": ")
        name = rest.split()[0] if rest.split() else ""
        if name and name not in lookup:
            lookup[name] = session_idx
    return lookup


def get_all_panes() -> List[Tuple[str, str, str, str]]:
    """Return list of (session, window_index, window_name, pane_index) tuples."""
    result = subprocess.run(
        ["tmux", "list-panes", "-a", "-F",
         "#{session_name}|#{window_index}|#{window_name}|#{pane_index}"],
        capture_output=True, text=True, check=False
    )
    panes = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            panes.append(tuple(parts))
    return panes


def resolve_targets(targets_str: str) -> List[Tuple[str, str]]:
    """
    Parse comma-separated target string into list of (tmux_target, label) pairs.

    tmux_target: session:window_index.pane_index  (usable with -t)
    label:       window_name.pane_index           (human-readable crew= attr)

    Exits with error if any target cannot be resolved.
    """
    lookup = get_window_lookup()
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
            print(f"Error: pane index must be numeric, got '{pane_index}' in target '{raw}'",
                  file=sys.stderr)
            sys.exit(1)

        key = lookup.get(window_name)
        if key is None:
            print(f"Error: tmux window '{window_name}' not found (target '{raw}')",
                  file=sys.stderr)
            available = list(lookup.keys())
            if available:
                print(f"Available windows: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)

        tmux_target = f"{key}.{pane_index}"
        label = f"{window_name}.{pane_index}"
        resolved.append((tmux_target, label))

    if not resolved:
        print("Error: no valid targets specified", file=sys.stderr)
        sys.exit(1)

    return resolved


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
# Subcommand: list
# ---------------------------------------------------------------------------

def cmd_list(fmt: str) -> None:
    panes = get_all_panes()

    if fmt == "xml":
        root = ET.Element("crew")
        current_window: Optional[ET.Element] = None
        current_window_key: Optional[str] = None

        for session, window_index, window_name, pane_index in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                current_window = ET.SubElement(root, "window", name=window_name)
                current_window_key = wkey
            ET.SubElement(current_window, "pane", index=pane_index)

        print(xml_to_string(root))
    else:
        # human format
        current_window_key = None
        for session, window_index, window_name, pane_index in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                print(f"window: {window_name}")
                current_window_key = wkey
            print(f"  pane: {pane_index}")


# ---------------------------------------------------------------------------
# Subcommand: tell
# ---------------------------------------------------------------------------

def cmd_tell(message: str, targets_str: str, fmt: str) -> None:
    resolved = resolve_targets(targets_str)

    if fmt == "xml":
        root = ET.Element("tell")

    for tmux_target, label in resolved:
        # send message then Enter as two separate send-keys calls
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
        else:
            print(f"sent -> {label}")

    if fmt == "xml":
        print(xml_to_string(root))


# ---------------------------------------------------------------------------
# Subcommand: read
# ---------------------------------------------------------------------------

def cmd_read(targets_str: str, lines: Optional[int], fmt: str) -> None:
    resolved = resolve_targets(targets_str)
    lines_attr = str(lines) if lines is not None else "all"

    if len(resolved) == 1:
        tmux_target, label = resolved[0]
        content = capture_pane(tmux_target, lines)
        if fmt == "xml":
            elem = ET.Element("output", crew=label, lines=lines_attr)
            elem.text = content
            print(xml_to_string(elem))
        else:
            print(f"--- {label} ---")
            print(content, end="")
    else:
        if fmt == "xml":
            root = ET.Element("reads")
            for tmux_target, label in resolved:
                content = capture_pane(tmux_target, lines)
                child = ET.SubElement(root, "output", crew=label, lines=lines_attr)
                child.text = content
            print(xml_to_string(root))
        else:
            for tmux_target, label in resolved:
                content = capture_pane(tmux_target, lines)
                print(f"--- {label} ---")
                print(content, end="")
                print()


# ---------------------------------------------------------------------------
# Subcommand: dismiss
# ---------------------------------------------------------------------------

def cmd_dismiss(targets_str: str, fmt: str) -> None:
    """Dismiss (kill) one or more tmux panes or windows.

    When fmt == "xml", output is wrapped in a <dismiss> root element, e.g.:
        <dismiss><target crew="worker.0" status="dismissed" /></dismiss>
    The root element name matches the subcommand name, consistent with the
    <tell> pattern used by cmd_tell.
    """
    raw_tokens = targets_str.split(",")
    resolved = resolve_targets(targets_str)

    if fmt == "xml":
        root = ET.Element("dismiss")

    for raw, (tmux_target, label) in zip(raw_tokens, resolved):
        if "." in raw:
            subprocess.run(["tmux", "kill-pane", "-t", tmux_target], check=False)
        else:
            # bare window: kill the whole window via session:window_index (drop pane suffix)
            window_target = tmux_target.rsplit(".", 1)[0]
            subprocess.run(["tmux", "kill-window", "-t", window_target], check=False)
        if fmt == "xml":
            ET.SubElement(root, "target", crew=label, status="dismissed")
        else:
            print(f"dismissed -> {label}")

    if fmt == "xml":
        print(xml_to_string(root))


# ---------------------------------------------------------------------------
# Subcommand: find
# ---------------------------------------------------------------------------

def cmd_find(pattern: str, targets_str: Optional[str], lines: Optional[int], fmt: str) -> None:
    if targets_str:
        resolved = resolve_targets(targets_str)
    else:
        # all panes
        panes = get_all_panes()
        resolved = []
        for session, window_index, window_name, pane_index in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            resolved.append((tmux_target, label))

    compiled = re.compile(pattern)

    if fmt == "xml":
        root = ET.Element("matches", pattern=pattern)
    else:
        found_any = False

    for tmux_target, label in resolved:
        content = capture_pane(tmux_target, lines)
        for lineno, line in enumerate(content.splitlines(), start=1):
            if compiled.search(line):
                if fmt == "xml":
                    match_elem = ET.SubElement(root, "match", crew=label, line=str(lineno))
                    match_elem.text = line
                else:
                    print(f"{label}:{lineno}: {line}")
                    found_any = True

    if fmt == "xml":
        print(xml_to_string(root))
    else:
        if not found_any:
            print("(no matches found)")


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def cmd_status(lines: int, fmt: str) -> None:
    panes = get_all_panes()

    if fmt == "xml":
        root = ET.Element("status", lines=str(lines))
        for session, window_index, window_name, pane_index in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            member = ET.SubElement(root, "member", crew=label)
            member.text = content
        print(xml_to_string(root))
    else:
        # human: list first, then content per pane
        current_window_key = None
        for session, window_index, window_name, pane_index in panes:
            wkey = f"{session}:{window_index}"
            if wkey != current_window_key:
                print(f"window: {window_name}")
                current_window_key = wkey
            print(f"  pane: {pane_index}")

        print()

        for session, window_index, window_name, pane_index in panes:
            tmux_target = f"{session}:{window_index}.{pane_index}"
            label = f"{window_name}.{pane_index}"
            content = capture_pane(tmux_target, lines)
            print(f"--- {label} (last {lines} lines) ---")
            print(content, end="")
            print()


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crew",
        description="Unified tmux window/pane interaction CLI"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["xml", "human"],
        default="xml",
        help="Output format: xml (default) or human"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="Enumerate tmux windows and panes")

    # tell
    p_tell = sub.add_parser("tell", help="Send message + Enter to target pane(s)")
    p_tell.add_argument("message", help="Message to send")
    p_tell.add_argument("targets", help="Comma-separated targets (window[.pane])")

    # read
    p_read = sub.add_parser("read", help="Capture pane buffer content")
    p_read.add_argument("targets", help="Comma-separated targets (window[.pane])")
    p_read.add_argument(
        "--lines", "-n",
        type=int,
        default=None,
        help="Tail last N lines from buffer (default: full buffer)"
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

    # status
    p_status = sub.add_parser(
        "status",
        help="Composite: list windows then read N lines from every pane"
    )
    p_status.add_argument(
        "--lines", "-n",
        type=int,
        default=100,
        help="Lines to read per pane (default: 100)"
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    fmt = args.format

    if args.command == "list":
        cmd_list(fmt)
    elif args.command == "tell":
        cmd_tell(args.message, args.targets, fmt)
    elif args.command == "read":
        cmd_read(args.targets, args.lines, fmt)
    elif args.command == "dismiss":
        cmd_dismiss(args.targets, fmt)
    elif args.command == "find":
        cmd_find(args.pattern, args.targets, args.lines, fmt)
    elif args.command == "status":
        cmd_status(args.lines, fmt)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
