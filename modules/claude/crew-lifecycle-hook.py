#!/usr/bin/env python3
"""
crew-lifecycle-hook: PostToolUse(Bash) hook that manages pulse cron lifecycle
based on 'crew create' and 'crew dismiss' commands.

Triggered by Claude Code's PostToolUse event when tool_name == 'Bash'.

- After 'crew create <name>': injects a CronCreate directive (idempotent —
  model checks CronList first and only creates if no pulse cron exists).
- After 'crew dismiss <name>': injects a conditional CronDelete directive —
  model checks crew list for remaining Staff windows and deletes the pulse
  cron only when zero Staff sessions remain.

This replaces the SessionStart-based unconditional CronCreate approach so
that no tokens are spent when no Staff sessions are active.

Output format (PostToolUse hook):
    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}
    (exit 0 with no stdout) — silent for all other commands

Fails open: any error results in silent exit 0.
"""

import argparse
import json
import os
import re
import sys


# Pulse cron schedule and label (must match what CronCreate uses so CronList
# can identify it for idempotency checks and CronDelete targeting).
_PULSE_CRON_SCHEDULE = "*/10 * * * *"
_PULSE_CRON_LABEL = "pulse-cron"

_PULSE_CRON_COMMAND = (
    "STEP 1: Run `crew list` to enumerate active Claude panes in the current tmux session. "
    "Your window name is `senior-staff-engineer` — if the only pane listed is your own, exit silently, send no response. "
    "STEP 2: Run `crew find 'local agents still running|Working for|Churned for|Baked for|\\u2733 \\w+|[\\u280b\\u2819\\u2839\\u2838\\u283c\\u2834\\u2826\\u2827\\u2807\\u280f]' --lines 30` to check whether any other Claude pane is actively working. "
    "Active-work indicators: 'local agents still running', 'Working for', 'Churned for', 'Baked for', '\\u2733 ' followed by a verb, or braille spinner characters. "
    "If `crew find` returns no matches across all panes, all panes are idle — exit silently, send no response. "
    "If any `crew` command errors, skip this pulse cycle silently. "
    "STEP 3: If `crew find` matched at least one active-work indicator, run `crew status --lines 20` and surface any actionable items (stalled, completed, or errored Staff sessions) per your normal pulse behavior."
)

_SENTINEL = "<<pulse-cron-lifecycle>>"

# Match 'crew create <name>' at the start of the command (after stripping leading whitespace).
_CREW_CREATE_RE = re.compile(r"^\s*crew\s+create\s+\S")

# Match 'crew dismiss <name>' at the start of the command (after stripping leading whitespace).
_CREW_DISMISS_RE = re.compile(r"^\s*crew\s+dismiss\s+\S")


def _additional_context(msg: str) -> str:
    """Wrap msg in the PostToolUse additionalContext response envelope."""
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    })


def _is_senior_staff() -> bool:
    """Return True if the current session is a Senior Staff session."""
    return os.environ.get("KANBAN_AGENT") == "senior-staff-engineer"


def _on_crew_create() -> None:
    """Emit CronCreate directive (idempotent: model checks CronList first)."""
    msg = (
        f"{_SENTINEL} A new Staff session was just created. "
        f"Call CronList now. "
        f"If no cron with label '{_PULSE_CRON_LABEL}' exists, "
        f"call CronCreate with schedule '{_PULSE_CRON_SCHEDULE}', "
        f"label '{_PULSE_CRON_LABEL}', "
        f"and command: {_PULSE_CRON_COMMAND} "
        f"If a cron with that label already exists, skip CronCreate."
    )
    print(_additional_context(msg))


def _on_crew_dismiss() -> None:
    """Emit CronDelete directive (conditional: only if no Staff windows remain)."""
    msg = (
        f"{_SENTINEL} A Staff session was just dismissed. "
        f"Call `crew list --format xml` now. "
        f"Count windows whose name is NOT 'senior-staff-engineer' (these are Staff sessions). "
        f"If zero such windows remain, call CronDelete for the cron with label '{_PULSE_CRON_LABEL}'. "
        f"If one or more Staff windows remain, leave the cron running."
    )
    print(_additional_context(msg))


def show_help() -> None:
    print("crew-lifecycle-hook - PostToolUse hook that manages pulse cron lifecycle")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Manages the pulse cron lifecycle based on 'crew create' and")
    print("  'crew dismiss' commands so the cron runs only when Staff sessions exist.")
    print("  Replaces the SessionStart-based unconditional CronCreate approach.")
    print()
    print("TRIGGER:")
    print("  PostToolUse(Bash) — fires after every Bash tool call.")
    print("  Only emits context when the command is 'crew create ...' or 'crew dismiss ...'.")
    print("  Silent for all other commands.")
    print()
    print("  Only fires for Senior Staff sessions (KANBAN_AGENT=senior-staff-engineer).")
    print()
    print("CRON INSTALL (crew create):")
    print("  Injects: call CronList; if no pulse-cron exists, call CronCreate.")
    print("  Idempotent: multiple crew creates do not install multiple crons.")
    print()
    print("CRON DELETE (crew dismiss):")
    print("  Injects: call crew list; if zero non-sstaff windows remain, call CronDelete.")
    print("  Conditional: cron survives as long as at least one Staff window is active.")
    print()
    print("OUTPUT:")
    print("  Emits hookSpecificOutput.additionalContext with lifecycle directive.")
    print("  Silent (no stdout) for non-matching commands or non-sstaff sessions.")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as PostToolUse(Bash) hook.")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    raw = sys.stdin.read()

    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Only act for Senior Staff sessions
    if not _is_senior_staff():
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "").lstrip()

    if _CREW_CREATE_RE.match(command):
        _on_crew_create()
    elif _CREW_DISMISS_RE.match(command):
        _on_crew_dismiss()

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Fail open — never break PostToolUse for all sessions
