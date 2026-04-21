#!/usr/bin/env python3
"""
senior-staff-staleness-hook: PreToolUse(Bash) hook that polls Senior Staff
session windows when the last poll is stale.

Triggered by Claude Code's PreToolUse event when tool_name == 'Bash'.
Reads a roster of active Senior Staff tmux session windows from
.scratchpad/senior-staff-roster.json and, when the last poll is >60 seconds
old, captures recent output from each session's Claude pane via `crew read`
and prints a summary for model visibility.

Fails open: any error results in silent exit 0.

ROSTER FORMAT:
  .scratchpad/senior-staff-roster.json:
  {"sessions":[
    {"window":"pricing","workstream":"Stripe pricing model",
     "panes":{"0":"claude (staff-engineer)","1":"smithers (ci)"}}
  ]}

CLAUDE PANE DISCOVERY:
  For each session, the hook scans the 'panes' map for the first pane whose
  description contains 'claude' (case-insensitive) and polls that pane via
  crew read. If no match is found (or no panes field exists), falls back to
  pane 0.

STALENESS GATE:
  Reads unix epoch from .scratchpad/senior-staff-last-poll.
  If missing or >60s old: polls all sessions, prints summary, updates timestamp.
  If <60s old: no-op (silent).

CONFIGURATION:
  Configured in modules/claude/default.nix as PreToolUse(Bash) hook.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROSTER_FILE = Path(".scratchpad/senior-staff-roster.json")
TIMESTAMP_FILE = Path(".scratchpad/senior-staff-last-poll")
STALENESS_SECONDS = 60


def show_help() -> None:
    print("senior-staff-staleness-hook - PreToolUse hook that polls Senior Staff session windows")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code before Bash tool use.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Automatically refreshes Senior Staff session awareness by polling recent")
    print("  output from each registered session window when the last poll is >60s stale.")
    print()
    print("TRIGGER:")
    print("  PreToolUse(Bash) — fires before every Bash tool call.")
    print("  Only actually polls when .scratchpad/senior-staff-roster.json exists AND")
    print("  .scratchpad/senior-staff-last-poll is missing or >60 seconds old.")
    print()
    print("ROSTER FORMAT:")
    print("  .scratchpad/senior-staff-roster.json:")
    print('  {"sessions":[')
    print('    {"window":"pricing","workstream":"Stripe pricing model",')
    print('     "panes":{"0":"claude (staff-engineer)","1":"smithers (ci)"}}')
    print('  ]}')
    print()
    print("CLAUDE PANE DISCOVERY:")
    print("  For each session, the hook scans the 'panes' map for the first pane")
    print("  whose description contains 'claude' (case-insensitive) and polls that")
    print("  pane via crew read. If no match is found (or no panes field")
    print("  exists), the hook falls back to pane 0.")
    print()
    print("STALENESS GATE:")
    print("  Reads unix epoch from .scratchpad/senior-staff-last-poll.")
    print("  If missing or >60s old: polls all sessions, prints summary, updates timestamp.")
    print("  If <60s old: no-op (silent).")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as PreToolUse(Bash) hook.")


def find_claude_pane(panes: dict) -> str:
    """
    Find the first pane key whose description contains 'claude' (case-insensitive).
    Falls back to '0' if no match is found or panes is empty.
    """
    for key, description in panes.items():
        if "claude" in str(description).lower():
            return key
    return "0"


def poll_sessions(roster: dict, now: int) -> None:
    """Poll all sessions in the roster and print a summary."""
    sessions = roster.get("sessions", [])
    if not sessions:
        return

    age = now - read_last_poll()
    print(f"--- Senior Staff Session Update ({age}s since last poll) ---")

    for session_entry in sessions:
        window = session_entry.get("window", "")
        workstream = session_entry.get("workstream", "")

        if not window:
            continue

        panes = session_entry.get("panes", {})
        claude_pane = find_claude_pane(panes)

        pane_ref = f"{window}.{claude_pane}"
        workstream_suffix = f" ({workstream})" if workstream else ""
        print(f"\nSession: {pane_ref}{workstream_suffix}")

        try:
            result = subprocess.run(
                ["crew", "read", pane_ref, "--lines", "30", "--format", "human"],
                capture_output=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
            )
            window_output = result.stdout.strip() if result.stdout else ""
            if result.returncode != 0:
                print(f"  [{pane_ref} not found or could not be read — roster may be drifting from tmux reality]")
                continue
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            print(f"  [{pane_ref} not found or could not be read — roster may be drifting from tmux reality]")
            continue

        if not window_output:
            print("  [no recent output]")
        else:
            for line in window_output.splitlines():
                print(f"  {line}")

    print()
    print("--- End Senior Staff Session Update ---")


def read_last_poll() -> int:
    """Read the last poll timestamp from disk. Returns 0 if missing or invalid."""
    try:
        content = TIMESTAMP_FILE.read_text().strip()
        return int(content)
    except (FileNotFoundError, ValueError, OSError):
        return 0


def write_timestamp(now: int) -> None:
    """Write the current timestamp to the timestamp file."""
    try:
        TIMESTAMP_FILE.write_text(str(now))
    except OSError:
        pass  # Fail open


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    # Consume stdin (we don't use the hook payload, but must read it)
    sys.stdin.read()

    # Feature detection: no-op if roster doesn't exist
    if not ROSTER_FILE.exists():
        sys.exit(0)

    now = int(time.time())
    last_poll = read_last_poll()
    age = now - last_poll

    if age < STALENESS_SECONDS:
        # Not stale yet — no-op
        sys.exit(0)

    # Load roster
    try:
        roster = json.loads(ROSTER_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        # Malformed or unreadable roster — update timestamp and exit
        write_timestamp(now)
        sys.exit(0)

    sessions = roster.get("sessions", [])
    if not sessions:
        # Empty roster — update timestamp and exit
        write_timestamp(now)
        sys.exit(0)

    # Poll is stale (or first run) — gather session output
    poll_sessions(roster, now)

    # Update the timestamp
    write_timestamp(now)
    sys.exit(0)


if __name__ == "__main__":
    main()
